"""Inventory business logic — search, KPIs, adjustment, safety-stock breach.

Per SCO-49 / PAGES_WORKFLOW.md §1.

Settings knobs are sourced from module constants today; SCO-53 will swap these
for the settings-registry lookup. The names match `inventory.*` keys appended
to SETTINGS_REGISTRY.md in the same commit.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from wms.models import SKU, Location, Lot
from wms.schemas.inventory import (
    AdjustOut,
    AdjustRequest,
    BelowSafetyRow,
    InventoryKPIs,
    LotOut,
    LotSearchOut,
    SKUDetailOut,
)
from wms.services import audit_log

# ── Settings (mirrored in SETTINGS_REGISTRY.md → folded into SCO-53) ────────
AGING_BUCKET_DAYS: list[int] = [30, 60, 90]
EXPIRING_SOON_DAYS: int = 7
ADJUST_LARGE_THRESHOLD: int = 100  # |delta| above this requires Lvl 4+
KPI_CACHE_TTL_SEC: int = 300
SEARCH_LIMIT_MAX: int = 200

EVT_INVENTORY_ADJUSTED = "inventory.adjusted"


# ── KPI cache (per-process, TTL-based) ──────────────────────────────────────
@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


_kpi_cache: dict[str, _CacheEntry] = {}
_kpi_cache_lock = threading.Lock()


def _cache_get(key: str) -> Any | None:
    with _kpi_cache_lock:
        entry = _kpi_cache.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            _kpi_cache.pop(key, None)
            return None
        return entry.value


def _cache_set(key: str, value: Any, ttl: int = KPI_CACHE_TTL_SEC) -> None:
    with _kpi_cache_lock:
        _kpi_cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + ttl)


def _cache_clear() -> None:
    """Test helper — flush the in-process KPI cache."""
    with _kpi_cache_lock:
        _kpi_cache.clear()


# ── Helpers ─────────────────────────────────────────────────────────────────
def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so user input can't broaden the match."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _today() -> date:
    return datetime.now(UTC).date()


def _age_days(received_at: datetime) -> int:
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - received_at).days


def _aging_bucket(received_at: datetime, buckets: list[int] | None = None) -> str:
    buckets = buckets or AGING_BUCKET_DAYS
    age = _age_days(received_at)
    last = 0
    for b in buckets:
        if age <= b:
            return f"{last}-{b}" if last else f"0-{b}"
        last = b + 1
    return f"{buckets[-1]}+"


def _is_expired(expires_at: date | None, today: date | None = None) -> bool:
    return expires_at is not None and expires_at <= (today or _today())


def _expiring_soon(expires_at: date | None, days: int = EXPIRING_SOON_DAYS) -> bool:
    if expires_at is None:
        return False
    delta = (expires_at - _today()).days
    return 0 <= delta <= days


def _serialize_lot(lot: Lot, sku: SKU, loc: Location | None) -> LotOut:
    return LotOut(
        id=lot.id,
        lot_code=lot.lot_code,
        sku_code=sku.code,
        sku_description=sku.description,
        location_code=loc.code if loc else None,
        location_is_overflow=bool(loc.is_overflow) if loc else False,
        location_is_qa_hold=bool(loc.is_qa_hold) if loc else False,
        quantity=lot.quantity,
        qa_hold=lot.qa_hold,
        received_at=lot.received_at,
        expires_at=lot.expires_at,
        supplier=lot.supplier,
        aging_bucket=_aging_bucket(lot.received_at),
        expiring_soon=_expiring_soon(lot.expires_at),
    )


# ── Search ──────────────────────────────────────────────────────────────────
def list_lots(
    db: Session,
    site_id: str,
    *,
    sku_code: str | None = None,
    lot_code: str | None = None,
    location_code: str | None = None,
    qa_hold: bool | None = None,
    expiring_within_days: int | None = None,
    aging_bucket: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LotSearchOut:
    limit = max(1, min(int(limit), SEARCH_LIMIT_MAX))
    offset = max(0, int(offset))

    query = (
        db.query(Lot, SKU, Location)
        .join(SKU, Lot.sku_id == SKU.id)
        .outerjoin(Location, Lot.location_id == Location.id)
        .filter(Lot.site_id == site_id)
    )

    if sku_code:
        query = query.filter(func.lower(SKU.code) == sku_code.lower())
    if lot_code:
        query = query.filter(func.lower(Lot.lot_code) == lot_code.lower())
    if location_code:
        query = query.filter(func.lower(Location.code) == location_code.lower())
    if qa_hold is not None:
        query = query.filter(Lot.qa_hold.is_(qa_hold))
    if expiring_within_days is not None:
        if expiring_within_days < 0:
            raise ValueError("expiring_within_days must be >= 0")
        today = _today()
        cutoff = date.fromordinal(today.toordinal() + int(expiring_within_days))
        query = query.filter(Lot.expires_at.isnot(None), Lot.expires_at <= cutoff)
    if q:
        like = f"%{_escape_like(q.lower())}%"
        query = query.filter(
            or_(
                func.lower(SKU.code).like(like, escape="\\"),
                func.lower(SKU.description).like(like, escape="\\"),
                func.lower(Lot.lot_code).like(like, escape="\\"),
                func.lower(func.coalesce(Lot.supplier, "")).like(like, escape="\\"),
            )
        )

    rows = query.order_by(Lot.received_at.desc()).all()

    if aging_bucket:
        rows = [r for r in rows if _aging_bucket(r[0].received_at) == aging_bucket]

    total = len(rows)
    paged = rows[offset : offset + limit]

    items = [_serialize_lot(lot, sku, loc) for lot, sku, loc in paged]
    return LotSearchOut(total=total, limit=limit, offset=offset, items=items)


# ── SKU aggregate ────────────────────────────────────────────────────────────
def get_sku_detail(db: Session, site_id: str, sku_code: str) -> SKUDetailOut:
    sku = (
        db.query(SKU)
        .filter(SKU.site_id == site_id, func.lower(SKU.code) == sku_code.lower())
        .one_or_none()
    )
    if sku is None:
        raise LookupError(f"SKU '{sku_code}' not found at site '{site_id}'")

    lots = db.query(Lot).filter(Lot.site_id == site_id, Lot.sku_id == sku.id).all()
    today = _today()
    on_hand_total = 0
    available = 0
    qa_hold_qty = 0
    expired_qty = 0
    for lot in lots:
        on_hand_total += lot.quantity
        if lot.qa_hold:
            qa_hold_qty += lot.quantity
            continue
        if _is_expired(lot.expires_at, today):
            expired_qty += lot.quantity
            continue
        if lot.quantity > 0:
            available += lot.quantity

    return SKUDetailOut(
        sku_code=sku.code,
        description=sku.description,
        uom=sku.uom,
        reorder_point=sku.reorder_point,
        safety_stock=sku.safety_stock,
        on_hand_total=on_hand_total,
        available=available,
        qa_hold_qty=qa_hold_qty,
        expired_qty=expired_qty,
        lot_count=len(lots),
    )


# ── KPIs (cached) ───────────────────────────────────────────────────────────
def _compute_kpis(db: Session, site_id: str) -> InventoryKPIs:
    today = _today()
    expired_case = case(
        (Lot.expires_at.isnot(None) & (Lot.expires_at <= today), Lot.quantity),
        else_=0,
    )
    qa_case = case((Lot.qa_hold.is_(True), Lot.quantity), else_=0)
    available_case = case(
        (
            Lot.qa_hold.is_(False)
            & (Lot.expires_at.is_(None) | (Lot.expires_at > today))
            & (Lot.quantity > 0),
            Lot.quantity,
        ),
        else_=0,
    )

    row = (
        db.query(
            func.coalesce(func.sum(Lot.quantity), 0),
            func.coalesce(func.sum(available_case), 0),
            func.coalesce(func.sum(qa_case), 0),
            func.coalesce(func.sum(expired_case), 0),
        )
        .filter(Lot.site_id == site_id)
        .one()
    )
    total_on_hand, available, qa_hold_qty, _expired_qty = row

    qa_hold_lots = (
        db.query(func.count(Lot.id))
        .filter(Lot.site_id == site_id, Lot.qa_hold.is_(True))
        .scalar()
        or 0
    )

    # SKUs under safety stock = those whose available < safety_stock
    safety_breach = len(below_safety_stock(db, site_id))

    sku_count = (
        db.query(func.count(SKU.id)).filter(SKU.site_id == site_id).scalar() or 0
    )

    return InventoryKPIs(
        total_on_hand=int(total_on_hand),
        available=int(available),
        qa_hold_qty=int(qa_hold_qty),
        qa_hold_lots=int(qa_hold_lots),
        slow_movers=0,  # populated by reports module (SCO-52) — zero, not 500
        skus_below_safety=safety_breach,
        sku_count=int(sku_count),
        cached_at=datetime.now(UTC),
    )


def get_kpis(db: Session, site_id: str, *, refresh: bool = False) -> InventoryKPIs:
    key = f"kpis::{site_id}"
    if not refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    value = _compute_kpis(db, site_id)
    _cache_set(key, value)
    return value


# ── Adjustment ──────────────────────────────────────────────────────────────
def adjust_lot(
    db: Session,
    *,
    site_id: str,
    actor_id: int | None,
    actor_level: int,
    payload: AdjustRequest,
) -> AdjustOut:
    if payload.delta == 0:
        raise ValueError("delta must be non-zero")

    lot = (
        db.query(Lot)
        .filter(Lot.id == payload.lot_id, Lot.site_id == site_id)
        .with_for_update()
        .one_or_none()
    )
    if lot is None:
        raise LookupError(f"Lot {payload.lot_id} not found at site '{site_id}'")

    was = int(lot.quantity)
    new_qty = was + int(payload.delta)
    if new_qty < 0:
        raise ValueError("adjustment would drop quantity below zero")

    if abs(payload.delta) > ADJUST_LARGE_THRESHOLD and actor_level < 4:
        raise PermissionError("Large adjustments require permission_level >= 4")

    lot.quantity = new_qty
    audit_log.record(
        db,
        event_type=EVT_INVENTORY_ADJUSTED,
        actor_id=actor_id,
        site_id=site_id,
        detail={
            "lot_id": lot.id,
            "lot_code": lot.lot_code,
            "was": was,
            "now": new_qty,
            "delta": int(payload.delta),
            "reason": payload.reason,
        },
        commit=False,
    )
    db.commit()
    return AdjustOut(lot_id=lot.id, was=was, now=new_qty, delta=int(payload.delta))


# ── Safety-stock breach ─────────────────────────────────────────────────────
def below_safety_stock(db: Session, site_id: str) -> list[BelowSafetyRow]:
    today = _today()
    rows = (
        db.query(SKU.id, SKU.code, SKU.description, SKU.reorder_point, SKU.safety_stock)
        .filter(SKU.site_id == site_id, SKU.safety_stock > 0)
        .all()
    )
    out: list[BelowSafetyRow] = []
    for sku_id, code, desc, reorder, safety in rows:
        available = (
            db.query(func.coalesce(func.sum(Lot.quantity), 0))
            .filter(
                Lot.site_id == site_id,
                Lot.sku_id == sku_id,
                Lot.qa_hold.is_(False),
                Lot.quantity > 0,
                or_(Lot.expires_at.is_(None), Lot.expires_at > today),
            )
            .scalar()
            or 0
        )
        if int(available) < int(safety):
            out.append(
                BelowSafetyRow(
                    sku_code=code,
                    description=desc,
                    available=int(available),
                    reorder_point=int(reorder),
                    safety_stock=int(safety),
                    shortfall=int(safety) - int(available),
                )
            )
    return out



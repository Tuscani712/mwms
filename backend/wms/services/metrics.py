"""Read-only metrics aggregator — SCO-52 MVP.

MVP endpoints power:
  - /reports/dashboard       (home KPI tiles)
  - /reports/inventory-aging (lots bucketed by received_at age)
  - /reports/production      (yield % by recipe, total WOs)
  - /reports/shipping        (on-time % stub from shipment counts)

MVP cuts (TODO in code for future iter):
  - No (site_id, report, params_hash) → in-process cache. Add LRU later.
  - No `?refresh=1` audit-event emission.
  - Date-range guards default to no-window; will plug `reports.date_range_max_days`
    once SCO-53 (settings registry) lands.
  - No outlier detection / CSV streaming / full genealogy walk (separate
    follow-up endpoints).
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from wms.models import (
    ASN,
    SKU,
    Lot,
    Order,
    Receipt,
    Recipe,
    Shipment,
    WorkOrder,
)

# ─── Dashboard KPI tiles ────────────────────────────────────────────────

def dashboard(db: Session, site_id: str) -> dict[str, Any]:
    """Compact KPI block for the home page. Each value comes from one
    SELECT — no heavy joins. Future caching layer will key on (site_id)."""
    today = date.today()
    today_dt = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

    open_orders = (
        db.query(func.count(Order.id))
        .filter(Order.site_id == site_id, Order.status == "open")
        .scalar() or 0
    )
    receipts_today = (
        db.query(func.count(Receipt.id))
        .filter(Receipt.site_id == site_id, Receipt.received_at >= today_dt)
        .scalar() or 0
    )
    shipments_today = (
        db.query(func.count(Shipment.id))
        .filter(Shipment.site_id == site_id, Shipment.dispatched_at >= today_dt)
        .scalar() or 0
    ) if hasattr(Shipment, "dispatched_at") else 0
    open_wos = (
        db.query(func.count(WorkOrder.id))
        .filter(WorkOrder.site_id == site_id, WorkOrder.status.in_(("draft", "reserved", "running")))
        .scalar() or 0
    )
    total_lots = (
        db.query(func.count(Lot.id))
        .filter(Lot.site_id == site_id)
        .scalar() or 0
    )
    qa_held_lots = (
        db.query(func.count(Lot.id))
        .filter(Lot.site_id == site_id, Lot.qa_hold.is_(True))
        .scalar() or 0
    )
    inbound = (
        db.query(func.count(ASN.id))
        .filter(ASN.site_id == site_id, ASN.status.in_(("scheduled", "arrived", "receiving")))
        .scalar() or 0
    )
    return {
        "site_id": site_id,
        "open_orders": open_orders,
        "receipts_today": receipts_today,
        "shipments_today": shipments_today,
        "open_work_orders": open_wos,
        "total_lots": total_lots,
        "qa_held_lots": qa_held_lots,
        "inbound_asns": inbound,
    }


# ─── Inventory aging ────────────────────────────────────────────────────

_AGING_BUCKETS = [(0, 7, "0-7d"), (8, 30, "8-30d"), (31, 90, "31-90d"), (91, 9999, "91d+")]


def inventory_aging(db: Session, site_id: str) -> dict[str, Any]:
    rows = (
        db.query(Lot, SKU)
        .join(SKU, Lot.sku_id == SKU.id)
        .filter(Lot.site_id == site_id, Lot.quantity > 0)
        .all()
    )
    buckets = {label: {"label": label, "lot_count": 0, "total_qty": 0} for _, _, label in _AGING_BUCKETS}
    now = datetime.now(UTC)
    for lot, _sku in rows:
        received = lot.received_at
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        days = (now - received).days
        for lo, hi, label in _AGING_BUCKETS:
            if lo <= days <= hi:
                buckets[label]["lot_count"] += 1
                buckets[label]["total_qty"] += lot.quantity
                break
    return {
        "site_id": site_id,
        "buckets": list(buckets.values()),
        "total_lots": sum(b["lot_count"] for b in buckets.values()),
    }


# ─── Production yield ───────────────────────────────────────────────────

def production_yield(db: Session, site_id: str) -> dict[str, Any]:
    """Per-recipe yield: (sum actual child-lot qty) / (sum reserved input qty).
    MVP MVP — a tighter metric would compare actual_qty against target_qty.
    For now we surface both numerators for transparency."""
    wos = (
        db.query(WorkOrder)
        .filter(WorkOrder.site_id == site_id, WorkOrder.status == "completed")
        .all()
    )
    by_recipe: dict[int, dict[str, Any]] = {}
    for wo in wos:
        agg = by_recipe.setdefault(
            wo.recipe_id,
            {"recipe_id": wo.recipe_id, "wo_count": 0, "target_total": 0, "completed_at_last": None},
        )
        agg["wo_count"] += 1
        agg["target_total"] += wo.target_qty
        # `completed_at` updated to the most-recent.
        if wo.completed_at and (agg["completed_at_last"] is None or wo.completed_at > agg["completed_at_last"]):
            agg["completed_at_last"] = wo.completed_at

    # Attach product SKU code for readability.
    recipe_ids = list(by_recipe.keys())
    recipe_rows = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all() if recipe_ids else []
    sku_map = {s.id: s for s in db.query(SKU).filter(SKU.id.in_([r.sku_id for r in recipe_rows])).all()}
    for r in recipe_rows:
        if r.id in by_recipe:
            by_recipe[r.id]["sku_code"] = sku_map[r.sku_id].code if r.sku_id in sku_map else None

    return {
        "site_id": site_id,
        "total_completed_work_orders": len(wos),
        "by_recipe": list(by_recipe.values()),
    }


# ─── Shipping on-time ───────────────────────────────────────────────────

def shipping_summary(db: Session, site_id: str) -> dict[str, Any]:
    """Total shipments + open orders. Real on-time % requires a
    `promised_at` column on Order which doesn't exist yet — that's why
    we stop short of computing it. TODO(SCO-52 v2): add column + metric."""
    total_shipments = (
        db.query(func.count(Shipment.id)).filter(Shipment.site_id == site_id).scalar() or 0
    )
    open_orders = (
        db.query(func.count(Order.id))
        .filter(Order.site_id == site_id, Order.status == "open")
        .scalar() or 0
    )
    return {
        "site_id": site_id,
        "total_shipments": total_shipments,
        "open_orders": open_orders,
        # TODO(SCO-52 v2): on-time pct.
    }

"""Quality (QA) business logic — SCO-50 MVP.

Open / decide holds on lots. Reuses the existing qc_holds + lots tables.

MVP cuts (TODO in code for future iter):
- No supplier_performance aggregation endpoint.
- No KPI aggregator (severity histogram, oldest-open-days).
- No escalation tier colouring (server-side flag on each row).
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from wms.models import Lot, QCHold


def list_holds(db: Session, *, site_id: str, status: str | None = "open") -> list[QCHold]:
    q = db.query(QCHold).filter(QCHold.site_id == site_id)
    if status == "open":
        q = q.filter(QCHold.resolved_at.is_(None))
    elif status == "resolved":
        q = q.filter(QCHold.resolved_at.is_not(None))
    # status='all' → no filter
    return q.order_by(QCHold.opened_at.desc()).all()


def get_hold(db: Session, hold_id: int, site_id: str) -> QCHold:
    hold = (
        db.query(QCHold)
        .filter(QCHold.id == hold_id, QCHold.site_id == site_id)
        .one_or_none()
    )
    if hold is None:
        raise ValueError(f"Hold {hold_id} not found in site {site_id}")
    return hold


def open_hold(
    db: Session,
    *,
    site_id: str,
    lot_id: int,
    reason: str,
    severity: str,
    opened_by: int | None,
) -> QCHold:
    lot = db.get(Lot, lot_id)
    if lot is None or lot.site_id != site_id:
        raise ValueError(f"Lot {lot_id} not found in site {site_id}")

    # Refuse duplicate-open: if there's already an open hold on this lot,
    # return 409 via ValueError with the existing id encoded.
    existing = (
        db.query(QCHold)
        .filter(QCHold.lot_id == lot_id, QCHold.resolved_at.is_(None))
        .first()
    )
    if existing is not None:
        raise ValueError(f"Lot already on hold (#{existing.id})")

    hold = QCHold(
        site_id=site_id,
        lot_id=lot_id,
        reason=reason,
        severity=severity,
        opened_by=opened_by,
    )
    lot.qa_hold = True
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold


def decide_hold(db: Session, hold_id: int, site_id: str, decision: str) -> QCHold:
    """release | destroy | rework. Each transitions the lot accordingly."""
    decision = decision.lower().strip()
    if decision not in {"release", "destroy", "rework"}:
        raise ValueError("decision must be release|destroy|rework")

    hold = get_hold(db, hold_id, site_id)
    if hold.resolved_at is not None:
        raise ValueError(f"Hold already resolved as '{hold.resolution}'")

    lot = db.get(Lot, hold.lot_id)
    if lot is None:
        raise ValueError("Lot vanished")

    if decision == "release":
        lot.qa_hold = False
    elif decision == "destroy":
        lot.quantity = 0
        lot.qa_hold = False  # nothing left to hold
    elif decision == "rework":
        # MVP: clear the hold. The "spawn a draft work order linked to the
        # lot" behaviour from PAGES_WORKFLOW.md §2 is deferred — we'd need
        # to ask which recipe to rework against. TODO(SCO-50 v2).
        lot.qa_hold = False

    hold.resolution = decision
    hold.resolved_at = datetime.now(UTC)
    db.commit()
    db.refresh(hold)
    return hold

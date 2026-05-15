"""Shipping business logic — orders → picks → consolidation → truck → packing slip."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from wms.models import SKU, Lot, Order, OrderLine, Pick, Shipment
from wms.schemas.shipping import (
    ConsolidationLotPlan,
    ConsolidationPlan,
    PackingSlip,
    PackingSlipLine,
    PickAssignmentRequest,
    TruckLoadStatus,
)

FEFO_THRESHOLD_DAYS = 7


def list_orders(db: Session, site_id: str, status: str | None = None) -> list[Order]:
    q = db.query(Order).filter(Order.site_id == site_id)
    if status:
        q = q.filter(Order.status == status)
    return q.order_by(Order.ship_by.asc().nullslast(), Order.id.asc()).all()


def _pick_lots(db: Session, site_id: str, sku_id: int, qty_needed: int, strategy: str) -> list[Lot]:
    q = db.query(Lot).filter(
        Lot.site_id == site_id,
        Lot.sku_id == sku_id,
        Lot.qa_hold.is_(False),
        Lot.quantity > 0,
    )
    if strategy == "FEFO":
        q = q.order_by(Lot.expires_at.asc().nullslast(), Lot.received_at.asc())
    else:
        q = q.order_by(Lot.received_at.asc())

    chosen: list[Lot] = []
    remaining = qty_needed
    for lot in q.all():
        if remaining <= 0:
            break
        chosen.append(lot)
        remaining -= lot.quantity
    return chosen


def consolidation_plan(
    db: Session, site_id: str, order_id: int, order_line_id: int
) -> ConsolidationPlan:
    order = db.query(Order).filter(Order.id == order_id, Order.site_id == site_id).one()
    line = db.query(OrderLine).filter(OrderLine.id == order_line_id, OrderLine.order_id == order.id).one()
    sku = db.query(SKU).filter(SKU.id == line.sku_id).one()

    fefo_window = date.today() + timedelta(days=FEFO_THRESHOLD_DAYS)
    earliest_lot = (
        db.query(Lot)
        .filter(Lot.site_id == site_id, Lot.sku_id == sku.id, Lot.qa_hold.is_(False), Lot.quantity > 0)
        .order_by(Lot.expires_at.asc().nullslast())
        .first()
    )
    fefo_triggered = (
        line.fefo_required
        or (earliest_lot is not None and earliest_lot.expires_at is not None and earliest_lot.expires_at <= fefo_window)
    )
    strategy = "FEFO" if fefo_triggered else "FIFO"

    qty_needed = max(0, line.qty_ordered - line.qty_picked)
    lots = _pick_lots(db, site_id, sku.id, qty_needed, strategy)

    plan: list[ConsolidationLotPlan] = []
    remaining = qty_needed
    qty_available = 0
    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, lot.quantity)
        qty_available += take
        plan.append(
            ConsolidationLotPlan(
                lot_code=lot.lot_code,
                location_code=None,
                qty=take,
                expires_at=lot.expires_at,
                strategy=strategy,
            )
        )
        remaining -= take

    return ConsolidationPlan(
        order_code=order.order_code,
        sku_code=sku.code,
        qty_required=qty_needed,
        qty_available=qty_available,
        plan=plan,
        fefo_triggered=fefo_triggered,
    )


def assign_pick(
    db: Session, site_id: str, user_id: int | None, payload: PickAssignmentRequest
) -> list[Pick]:
    order = db.query(Order).filter(Order.id == payload.order_id, Order.site_id == site_id).one()
    line = db.query(OrderLine).filter(
        OrderLine.id == payload.order_line_id, OrderLine.order_id == order.id
    ).one()
    if payload.qty <= 0:
        raise ValueError("Quantity must be positive")

    lots = _pick_lots(db, site_id, line.sku_id, payload.qty, payload.strategy)
    if not lots:
        raise ValueError("No available lots for SKU (all on hold or out of stock)")

    picks: list[Pick] = []
    remaining = payload.qty
    for lot in lots:
        if remaining <= 0:
            break
        take = min(remaining, lot.quantity)
        pick = Pick(
            order_id=order.id,
            order_line_id=line.id,
            lot_id=lot.id,
            qty_picked=take,
            picker_id=user_id,
            strategy=payload.strategy,
        )
        db.add(pick)
        lot.quantity -= take
        line.qty_picked += take
        remaining -= take
        picks.append(pick)

    if remaining > 0:
        raise ValueError(f"Insufficient inventory: short by {remaining} units")

    if line.qty_picked >= line.qty_ordered:
        all_filled = all(ln.qty_picked >= ln.qty_ordered for ln in order.lines)
        if all_filled:
            order.status = "picked"

    db.commit()
    for p in picks:
        db.refresh(p)
    return picks


def load_truck(db: Session, site_id: str, shipment_id: int, order_id: int) -> TruckLoadStatus:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id, Shipment.site_id == site_id).one()
    order = db.query(Order).filter(Order.id == order_id, Order.site_id == site_id).one()

    order_weight = 0.0
    for line in order.lines:
        sku = db.query(SKU).filter(SKU.id == line.sku_id).one()
        order_weight += sku.unit_weight_kg * line.qty_picked

    shipment.loaded_weight_kg += order_weight
    order.truck_id = shipment.truck_id
    order.status = "loaded"
    db.commit()
    db.refresh(shipment)

    return TruckLoadStatus(
        shipment_id=shipment.id,
        truck_id=shipment.truck_id,
        capacity_kg=shipment.truck_capacity_kg,
        loaded_kg=shipment.loaded_weight_kg,
        remaining_kg=max(0.0, shipment.truck_capacity_kg - shipment.loaded_weight_kg),
        over_budget=shipment.loaded_weight_kg > shipment.truck_capacity_kg,
    )


def packing_slip(db: Session, site_id: str, order_id: int) -> PackingSlip:
    order = db.query(Order).filter(Order.id == order_id, Order.site_id == site_id).one()
    picks = db.query(Pick).filter(Pick.order_id == order.id).all()

    lines: list[PackingSlipLine] = []
    for pk in picks:
        lot = db.query(Lot).filter(Lot.id == pk.lot_id).one()
        sku = db.query(SKU).filter(SKU.id == lot.sku_id).one()
        lines.append(
            PackingSlipLine(
                sku_code=sku.code,
                description=sku.description,
                lot_code=lot.lot_code,
                qty=pk.qty_picked,
            )
        )
    return PackingSlip(
        order_code=order.order_code,
        customer=order.customer,
        shipped_at=datetime.now(UTC),
        lines=lines,
    )

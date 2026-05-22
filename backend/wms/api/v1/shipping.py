"""Shipping router."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import SKU, Lot, Order, OrderLine, User
from wms.schemas.shipping import (
    ConsolidationPlan,
    OrderCreate,
    OrderLineOut,
    OrderOut,
    PackingSlip,
    PickAssignmentRequest,
    PickOut,
    TruckLoadRequest,
    TruckLoadStatus,
)
from wms.services import shipping as svc

router = APIRouter(prefix="/shipping", tags=["shipping"])


def _serialize_order(db: Session, order: Order) -> OrderOut:
    sku_ids = [ln.sku_id for ln in order.lines]
    sku_map = {s.id: s for s in db.query(SKU).filter(SKU.id.in_(sku_ids)).all()} if sku_ids else {}
    return OrderOut(
        id=order.id,
        order_code=order.order_code,
        customer=order.customer,
        priority=order.priority,
        status=order.status,
        ship_by=order.ship_by,
        truck_id=order.truck_id,
        lines=[
            OrderLineOut(
                id=line.id,
                sku_code=sku_map[line.sku_id].code,
                sku_description=sku_map[line.sku_id].description,
                qty_ordered=line.qty_ordered,
                qty_picked=line.qty_picked,
                fefo_required=line.fefo_required,
            )
            for line in order.lines
        ],
    )


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OrderOut]:
    orders = svc.list_orders(db, user.site_id, status_filter)
    return [_serialize_order(db, o) for o in orders]


@router.get("/consolidation/{order_id}/{order_line_id}", response_model=ConsolidationPlan)
def consolidation(
    order_id: int,
    order_line_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConsolidationPlan:
    try:
        return svc.consolidation_plan(db, user.site_id, order_id, order_line_id)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/picks", response_model=list[PickOut])
def create_picks(
    payload: PickAssignmentRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[PickOut]:
    try:
        picks = svc.assign_pick(db, user.site_id, user.id, payload)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    out: list[PickOut] = []
    for p in picks:
        lot = db.query(Lot).filter(Lot.id == p.lot_id).one()
        out.append(
            PickOut(
                id=p.id,
                order_id=p.order_id,
                lot_code=lot.lot_code,
                qty_picked=p.qty_picked,
                strategy=p.strategy,
                picked_at=p.picked_at,
            )
        )
    return out


@router.post("/truck-load", response_model=TruckLoadStatus)
def truck_load(
    payload: TruckLoadRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TruckLoadStatus:
    try:
        return svc.load_truck(db, user.site_id, payload.shipment_id, payload.order_id)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/packing-slip/{order_id}", response_model=PackingSlip)
def packing_slip(
    order_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PackingSlip:
    return svc.packing_slip(db, user.site_id, order_id)


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrderOut:
    """Create a sales order with line items in the caller's site."""
    if db.query(Order).filter(Order.order_code == payload.order_code).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order {payload.order_code} already exists")
    sku_ids = [ln.sku_id for ln in payload.lines]
    skus = {
        s.id: s
        for s in db.query(SKU).filter(SKU.id.in_(sku_ids), SKU.site_id == user.site_id).all()
    }
    missing = [sid for sid in sku_ids if sid not in skus]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"SKU(s) {missing} not found in site {user.site_id}",
        )

    order = Order(
        site_id=user.site_id,
        order_code=payload.order_code,
        customer=payload.customer,
        priority=payload.priority,
        ship_by=payload.ship_by,
        status="open",
    )
    db.add(order)
    db.flush()
    for ln in payload.lines:
        db.add(
            OrderLine(
                order_id=order.id,
                sku_id=ln.sku_id,
                qty_ordered=ln.qty_ordered,
                fefo_required=ln.fefo_required,
            )
        )
    db.commit()
    db.refresh(order)
    return _serialize_order(db, order)

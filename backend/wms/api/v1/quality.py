"""Quality (QA) router — holds list + open + decide (SCO-50 MVP)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import SKU, Lot, User
from wms.schemas.quality import HoldDecideRequest, HoldOpenRequest, HoldOut
from wms.services import quality as svc

router = APIRouter(prefix="/quality", tags=["quality"])


def _serialize(db: Session, hold) -> HoldOut:
    lot = db.get(Lot, hold.lot_id)
    sku = db.get(SKU, lot.sku_id) if lot else None
    return HoldOut(
        id=hold.id,
        site_id=hold.site_id,
        lot_id=hold.lot_id,
        lot_code=lot.lot_code if lot else None,
        sku_code=sku.code if sku else None,
        reason=hold.reason,
        severity=hold.severity,
        opened_at=hold.opened_at,
        resolved_at=hold.resolved_at,
        resolution=hold.resolution,
        opened_by=hold.opened_by,
        status="open" if hold.resolved_at is None else "resolved",
    )


@router.get("/holds", response_model=list[HoldOut])
def list_holds(
    status_filter: str | None = "open",
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[HoldOut]:
    rows = svc.list_holds(db, site_id=user.site_id, status=status_filter)
    return [_serialize(db, r) for r in rows]


@router.post("/holds", response_model=HoldOut, status_code=status.HTTP_201_CREATED)
def open_hold(
    payload: HoldOpenRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> HoldOut:
    try:
        hold = svc.open_hold(
            db,
            site_id=user.site_id,
            lot_id=payload.lot_id,
            reason=payload.reason,
            severity=payload.severity,
            opened_by=user.id,
        )
    except ValueError as e:
        msg = str(e)
        if msg.startswith("Lot already on hold"):
            raise HTTPException(status.HTTP_409_CONFLICT, msg) from None
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg) from None
    return _serialize(db, hold)


@router.post("/holds/{hold_id}/decide", response_model=HoldOut)
def decide_hold(
    hold_id: int,
    payload: HoldDecideRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> HoldOut:
    try:
        hold = svc.decide_hold(db, hold_id, user.site_id, payload.decision)
    except ValueError as e:
        msg = str(e)
        if "already resolved" in msg:
            raise HTTPException(status.HTTP_409_CONFLICT, msg) from None
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg) from None
    return _serialize(db, hold)

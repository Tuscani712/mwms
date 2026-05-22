"""Receiving router."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import ASN, SKU, ASNLine, User
from wms.schemas.receiving import (
    ASNCreate,
    ASNLineOut,
    ASNOut,
    CheckInRequest,
    PutawaySuggestion,
    ReceiptCreate,
    ReceiptOut,
)
from wms.services import receiving as svc

router = APIRouter(prefix="/receiving", tags=["receiving"])


def _serialize_asn(db: Session, asn) -> ASNOut:
    sku_ids = [line.sku_id for line in asn.lines]
    sku_map = {s.id: s for s in db.query(SKU).filter(SKU.id.in_(sku_ids)).all()}
    return ASNOut(
        id=asn.id,
        asn_code=asn.asn_code,
        supplier=asn.supplier,
        dock_door=asn.dock_door,
        status=asn.status,
        eta=asn.eta,
        arrived_at=asn.arrived_at,
        lines=[
            ASNLineOut(
                id=line.id,
                sku_code=sku_map[line.sku_id].code,
                sku_description=sku_map[line.sku_id].description,
                expected_qty=line.expected_qty,
                received_qty=line.received_qty,
                qc_status=line.qc_status,
            )
            for line in asn.lines
        ],
    )


@router.get("/inbound", response_model=list[ASNOut])
def inbound(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[ASNOut]:
    asns = svc.list_inbound(db, user.site_id)
    return [_serialize_asn(db, a) for a in asns]


@router.post("/check-in", response_model=ASNOut)
def check_in(
    payload: CheckInRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ASNOut:
    try:
        asn = svc.check_in_asn(db, user.site_id, payload.asn_id, payload.dock_door)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _serialize_asn(db, asn)


@router.post("/receipts", response_model=ReceiptOut)
def create_receipt(
    payload: ReceiptCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ReceiptOut:
    try:
        receipt = svc.create_receipt(db, user.site_id, user.id, payload)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    from wms.models import ReceiptLine

    rls = db.query(ReceiptLine).filter(ReceiptLine.receipt_id == receipt.id).all()
    return ReceiptOut(
        id=receipt.id,
        asn_id=receipt.asn_id,
        received_at=receipt.received_at,
        variance_notes=receipt.variance_notes,
        total_variance=sum(rl.qty_variance for rl in rls),
        lot_ids=[rl.lot_id for rl in rls if rl.lot_id is not None],
    )


@router.get("/putaway-suggestions/{asn_id}", response_model=list[PutawaySuggestion])
def putaway(
    asn_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[PutawaySuggestion]:
    return svc.putaway_suggestions(db, user.site_id, asn_id)


@router.post("/asns", response_model=ASNOut, status_code=status.HTTP_201_CREATED)
def create_asn(
    payload: ASNCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ASNOut:
    """Create an inbound ASN with line items. Each line SKU must belong to
    the caller's site; ASN code must be unique."""
    if db.query(ASN).filter(ASN.asn_code == payload.asn_code).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"ASN {payload.asn_code} already exists")

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

    asn = ASN(
        site_id=user.site_id,
        asn_code=payload.asn_code,
        supplier=payload.supplier,
        eta=payload.eta,
        status="scheduled",
    )
    db.add(asn)
    db.flush()
    for ln in payload.lines:
        db.add(ASNLine(asn_id=asn.id, sku_id=ln.sku_id, expected_qty=ln.expected_qty))
    db.commit()
    db.refresh(asn)
    return _serialize_asn(db, asn)

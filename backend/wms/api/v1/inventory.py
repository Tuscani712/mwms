"""Inventory router — search, KPIs, adjustments, safety-stock breach.

SCO-49 · See PAGES_WORKFLOW.md §1.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import SKU, User
from wms.schemas.inventory import (
    AdjustOut,
    AdjustRequest,
    BelowSafetyRow,
    InventoryKPIs,
    LotSearchOut,
    SKUDetailOut,
)
from wms.services import inventory as svc

router = APIRouter(prefix="/inventory", tags=["inventory"])

_ADJUST_MIN_LEVEL = 3


# SCO-51: SKU picker for the production module (recipe + WO modals need to
# enumerate SKUs in the caller's site). Lightweight projection — full SKU
# detail still goes through /inventory/sku/{code}.
class SKURow(BaseModel):
    id: int
    code: str
    description: str
    uom: str
    requires_qc: bool

    model_config = {"from_attributes": True}


@router.get("/skus", response_model=list[SKURow])
def list_skus(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[SKURow]:
    rows = db.query(SKU).filter(SKU.site_id == user.site_id).order_by(SKU.code).all()
    return [SKURow.model_validate(r) for r in rows]


class SKUCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=180)
    uom: str = Field(default="EA", min_length=1, max_length=10)
    unit_weight_kg: float = Field(default=1.0, ge=0)
    requires_qc: bool = False
    shelf_life_days: int | None = Field(default=None, ge=0)
    reorder_point: int = Field(default=0, ge=0)
    safety_stock: int = Field(default=0, ge=0)


@router.post("/skus", response_model=SKURow, status_code=status.HTTP_201_CREATED)
def create_sku(
    payload: SKUCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SKURow:
    # TODO(SCO-49 v2): tighten to permission_level >= 3 once we have a clean
    # path to seed an admin in the dev fixture. MVP leaves this open to any
    # authenticated user so the Receive→Ship walkthrough is unblocked.
    exists = (
        db.query(SKU)
        .filter(SKU.site_id == user.site_id, SKU.code == payload.code)
        .first()
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"SKU {payload.code} already exists")
    sku = SKU(site_id=user.site_id, **payload.model_dump())
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return SKURow.model_validate(sku)


@router.get("/lots", response_model=LotSearchOut)
def list_lots(
    sku_code: str | None = Query(default=None, max_length=40),
    lot_code: str | None = Query(default=None, max_length=40),
    location_code: str | None = Query(default=None, max_length=20),
    qa_hold: bool | None = Query(default=None),
    expiring_within_days: int | None = Query(default=None, ge=0, le=3650),
    aging_bucket: str | None = Query(default=None, max_length=10),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=svc.SEARCH_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> LotSearchOut:
    try:
        return svc.list_lots(
            db,
            user.site_id,
            sku_code=sku_code,
            lot_code=lot_code,
            location_code=location_code,
            qa_hold=qa_hold,
            expiring_within_days=expiring_within_days,
            aging_bucket=aging_bucket,
            q=q,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/sku/{sku_code}", response_model=SKUDetailOut)
def sku_detail(
    sku_code: str,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SKUDetailOut:
    try:
        return svc.get_sku_detail(db, user.site_id, sku_code)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@router.get("/kpis", response_model=InventoryKPIs)
def kpis(
    refresh: bool = Query(default=False),
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> InventoryKPIs:
    return svc.get_kpis(db, user.site_id, refresh=refresh)


@router.post("/adjust", response_model=AdjustOut)
def adjust(
    payload: AdjustRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AdjustOut:
    if user.permission_level < _ADJUST_MIN_LEVEL:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Inventory adjust requires permission_level >= 3"
        )
    try:
        return svc.adjust_lot(
            db,
            site_id=user.site_id,
            actor_id=user.id,
            actor_level=user.permission_level,
            payload=payload,
        )
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/below-safety-stock", response_model=list[BelowSafetyRow])
def below_safety_stock(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[BelowSafetyRow]:
    return svc.below_safety_stock(db, user.site_id)

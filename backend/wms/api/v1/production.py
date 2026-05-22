"""Production router — recipes + work orders (SCO-51 MVP).

Permission gates here are intentionally light for the MVP — any authenticated
user may create recipes / WOs. Production rollout should layer in:
  - `production.recipe_edit_requires_level` (default 3)
  - `production.shortage_override_requires_level` (default 4)
  - supervisor-only on /cancel
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import SKU, Lot, User
from wms.schemas.production import (
    PreflightResult,
    RecipeCreate,
    RecipeLineOut,
    RecipeOut,
    ReservationOut,
    WorkOrderCancelRequest,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderOut,
)
from wms.services import production as svc

router = APIRouter(prefix="/production", tags=["production"])


# ─── Serialization helpers ──────────────────────────────────────────────

def _serialize_recipe(db: Session, recipe) -> RecipeOut:
    lines = svc.get_recipe_lines(db, recipe.id)
    sku_ids = [ln.ingredient_sku_id for ln in lines] + [recipe.sku_id]
    sku_map = {s.id: s for s in db.query(SKU).filter(SKU.id.in_(sku_ids)).all()}
    return RecipeOut(
        id=recipe.id,
        sku_id=recipe.sku_id,
        sku_code=sku_map.get(recipe.sku_id).code if sku_map.get(recipe.sku_id) else None,
        version=recipe.version,
        locked_by=recipe.locked_by,
        created_at=recipe.created_at,
        lines=[
            RecipeLineOut(
                id=ln.id,
                ingredient_sku_id=ln.ingredient_sku_id,
                ingredient_sku_code=(
                    sku_map[ln.ingredient_sku_id].code if ln.ingredient_sku_id in sku_map else None
                ),
                qty_per_unit=ln.qty_per_unit,
                uom=ln.uom,
            )
            for ln in lines
        ],
    )


def _serialize_wo(db: Session, wo) -> WorkOrderOut:
    reservations = svc.get_reservations(db, wo.id)
    lot_map = {
        lot.id: lot for lot in db.query(Lot).filter(Lot.id.in_([r.lot_id for r in reservations])).all()
    } if reservations else {}
    return WorkOrderOut(
        id=wo.id,
        recipe_id=wo.recipe_id,
        recipe_version_snapshot=wo.recipe_version_snapshot,
        target_qty=wo.target_qty,
        status=wo.status,
        site_id=wo.site_id,
        started_at=wo.started_at,
        completed_at=wo.completed_at,
        supervisor_id=wo.supervisor_id,
        created_at=wo.created_at,
        reservations=[
            ReservationOut(
                id=r.id,
                lot_id=r.lot_id,
                lot_code=lot_map[r.lot_id].lot_code if r.lot_id in lot_map else None,
                qty_reserved=r.qty_reserved,
            )
            for r in reservations
        ],
    )


# ─── Recipe endpoints ───────────────────────────────────────────────────

@router.get("/recipes", response_model=list[RecipeOut])
def list_recipes(
    sku_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[RecipeOut]:
    recipes = svc.list_recipes(db, sku_id=sku_id)
    return [_serialize_recipe(db, r) for r in recipes]


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
def get_recipe(
    recipe_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RecipeOut:
    try:
        recipe = svc.get_recipe(db, recipe_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None
    return _serialize_recipe(db, recipe)


@router.post("/recipes", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RecipeOut:
    try:
        recipe = svc.create_recipe(db, payload)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return _serialize_recipe(db, recipe)


# ─── Work order endpoints ───────────────────────────────────────────────

@router.get("/work-orders", response_model=list[WorkOrderOut])
def list_work_orders(
    status_filter: str | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[WorkOrderOut]:
    wos = svc.list_work_orders(db, site_id=user.site_id, status=status_filter)
    return [_serialize_wo(db, w) for w in wos]


@router.get("/work-orders/{wo_id}", response_model=WorkOrderOut)
def get_work_order(
    wo_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkOrderOut:
    try:
        wo = svc.get_work_order(db, wo_id, user.site_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None
    return _serialize_wo(db, wo)


@router.post("/work-orders", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(
    payload: WorkOrderCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkOrderOut:
    try:
        wo = svc.create_work_order(
            db, site_id=user.site_id, supervisor_id=user.id, payload=payload
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return _serialize_wo(db, wo)


@router.post("/work-orders/{wo_id}/preflight", response_model=PreflightResult)
def preflight(
    wo_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PreflightResult:
    try:
        return svc.preflight_work_order(db, wo_id, user.site_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


@router.post("/work-orders/{wo_id}/start", response_model=WorkOrderOut)
def start(
    wo_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkOrderOut:
    try:
        wo = svc.start_work_order(db, wo_id, user.site_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return _serialize_wo(db, wo)


@router.post("/work-orders/{wo_id}/complete", response_model=WorkOrderOut)
def complete(
    wo_id: int,
    payload: WorkOrderCompleteRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkOrderOut:
    try:
        wo, _ = svc.complete_work_order(db, wo_id, user.site_id, payload)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return _serialize_wo(db, wo)


@router.post("/work-orders/{wo_id}/cancel", response_model=WorkOrderOut)
def cancel(
    wo_id: int,
    payload: WorkOrderCancelRequest | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkOrderOut:
    try:
        wo = svc.cancel_work_order(db, wo_id, user.site_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None
    return _serialize_wo(db, wo)

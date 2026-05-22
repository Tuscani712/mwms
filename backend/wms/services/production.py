"""Production business logic — recipes + work order lifecycle (SCO-51 MVP).

State machine: draft → reserved → running → completed.
`cancel` is the only exit from reserved/running short of completed.

MVP simplifications (TODO comments live at each call site for future iter):
- Recipe edits update in place. Real spec wants version-bump-on-edit so that
  running WOs keep their `recipe_version_snapshot`. Snapshot column is in
  place; we always write version=recipe.version on WO create, so once
  bump-on-edit is wired the snapshot already protects historical WOs.
- Reservation uses ordinary SQLAlchemy SELECT + INSERT. Two concurrent
  preflights on the same scarce lot can race and over-allocate. Production
  rollout should add SQLite `BEGIN IMMEDIATE` / Postgres `FOR UPDATE`.
- No BOM unit conversion (recipe.uom must equal lot.sku.uom).
- No yield variance audit emission (just the genealogy + qty deltas).
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from wms.models import (
    SKU,
    Lot,
    LotGenealogy,
    Recipe,
    RecipeLine,
    WorkOrder,
    WorkOrderReservation,
)
from wms.schemas.production import (
    PreflightResult,
    RecipeCreate,
    ReservationOut,
    ShortageOut,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
)

# ─── Recipes ────────────────────────────────────────────────────────────

def list_recipes(db: Session, *, sku_id: int | None = None) -> list[Recipe]:
    q = db.query(Recipe)
    if sku_id is not None:
        q = q.filter(Recipe.sku_id == sku_id)
    return q.order_by(Recipe.sku_id, Recipe.version.desc()).all()


def get_recipe(db: Session, recipe_id: int) -> Recipe:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise ValueError(f"Recipe {recipe_id} not found")
    return recipe


def get_recipe_lines(db: Session, recipe_id: int) -> list[RecipeLine]:
    return db.query(RecipeLine).filter(RecipeLine.recipe_id == recipe_id).all()


def create_recipe(db: Session, payload: RecipeCreate) -> Recipe:
    if db.get(SKU, payload.sku_id) is None:
        raise ValueError(f"SKU {payload.sku_id} not found")
    for line in payload.lines:
        if db.get(SKU, line.ingredient_sku_id) is None:
            raise ValueError(f"Ingredient SKU {line.ingredient_sku_id} not found")

    # TODO(SCO-51 v2): version-bump-on-edit. If a recipe for this sku_id
    # already exists, increment from MAX(version) instead of starting at 1.
    recipe = Recipe(sku_id=payload.sku_id, version=1)
    db.add(recipe)
    db.flush()
    for line in payload.lines:
        db.add(
            RecipeLine(
                recipe_id=recipe.id,
                ingredient_sku_id=line.ingredient_sku_id,
                qty_per_unit=line.qty_per_unit,
                uom=line.uom,
            )
        )
    db.commit()
    db.refresh(recipe)
    return recipe


# ─── Work orders ────────────────────────────────────────────────────────

def list_work_orders(
    db: Session, *, site_id: str, status: str | None = None
) -> list[WorkOrder]:
    q = db.query(WorkOrder).filter(WorkOrder.site_id == site_id)
    if status:
        q = q.filter(WorkOrder.status == status)
    return q.order_by(WorkOrder.created_at.desc()).all()


def get_work_order(db: Session, wo_id: int, site_id: str) -> WorkOrder:
    wo = (
        db.query(WorkOrder)
        .filter(WorkOrder.id == wo_id, WorkOrder.site_id == site_id)
        .one_or_none()
    )
    if wo is None:
        raise ValueError(f"WorkOrder {wo_id} not found in site {site_id}")
    return wo


def get_reservations(db: Session, wo_id: int) -> list[WorkOrderReservation]:
    return (
        db.query(WorkOrderReservation)
        .filter(WorkOrderReservation.work_order_id == wo_id)
        .all()
    )


def create_work_order(
    db: Session, *, site_id: str, supervisor_id: int | None, payload: WorkOrderCreate
) -> WorkOrder:
    recipe = get_recipe(db, payload.recipe_id)
    wo = WorkOrder(
        recipe_id=recipe.id,
        recipe_version_snapshot=recipe.version,
        target_qty=payload.target_qty,
        status="draft",
        site_id=site_id,
        supervisor_id=supervisor_id,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


def _fifo_lots(db: Session, site_id: str, sku_id: int) -> list[Lot]:
    """Available lots for an ingredient SKU, FIFO by received_at.
    Excludes qa_hold and zero-quantity lots.
    """
    return (
        db.query(Lot)
        .filter(
            Lot.site_id == site_id,
            Lot.sku_id == sku_id,
            Lot.qa_hold.is_(False),
            Lot.quantity > 0,
        )
        .order_by(Lot.received_at.asc())
        .all()
    )


def preflight_work_order(db: Session, wo_id: int, site_id: str) -> PreflightResult:
    """Allocate ingredient lots FIFO. If anything is short, return shortages
    array and leave the WO in draft. Otherwise write reservation rows and
    flip WO to 'reserved'."""
    wo = get_work_order(db, wo_id, site_id)
    if wo.status != "draft":
        raise ValueError(f"WO must be in draft (currently '{wo.status}')")

    recipe_lines = get_recipe_lines(db, wo.recipe_id)

    # Clear any prior reservations from this WO (defensive — preflight should
    # only run once on a draft, but if a caller retries we don't want orphans).
    db.query(WorkOrderReservation).filter(
        WorkOrderReservation.work_order_id == wo.id
    ).delete(synchronize_session=False)

    proposed: list[WorkOrderReservation] = []
    shortages: list[ShortageOut] = []
    sku_code_cache: dict[int, str] = {}

    for line in recipe_lines:
        required = line.qty_per_unit * wo.target_qty
        # TODO(SCO-51 v2): BOM unit conversion via SKU.unit_weight_kg if
        # line.uom != lot.sku.uom. For now we assume matched units.
        remaining = required
        for lot in _fifo_lots(db, site_id, line.ingredient_sku_id):
            if remaining <= 0:
                break
            take = min(lot.quantity, remaining)
            proposed.append(
                WorkOrderReservation(
                    work_order_id=wo.id,
                    lot_id=lot.id,
                    qty_reserved=int(take),
                )
            )
            remaining -= take

        if remaining > 0:
            sku = db.get(SKU, line.ingredient_sku_id)
            code = sku.code if sku else None
            sku_code_cache[line.ingredient_sku_id] = code or ""
            shortages.append(
                ShortageOut(
                    ingredient_sku_id=line.ingredient_sku_id,
                    ingredient_sku_code=code,
                    required=required,
                    available=required - remaining,
                    short_by=remaining,
                )
            )

    if shortages:
        # MVP: 200 OK with shortages[] and WO stays draft.
        # TODO(SCO-51 v2): allow shortage_override on /start with reason.
        db.commit()
        return PreflightResult(
            work_order_id=wo.id, status="draft", reservations=[], shortages=shortages
        )

    # Atomic-ish: write all reservation rows then flip status.
    # TODO(SCO-51 v2): wrap in BEGIN IMMEDIATE (SQLite) / FOR UPDATE (PG).
    for r in proposed:
        db.add(r)
    wo.status = "reserved"
    db.commit()
    db.refresh(wo)

    lot_code_cache = {
        lot.id: lot.lot_code
        for lot in db.query(Lot).filter(Lot.id.in_([p.lot_id for p in proposed])).all()
    }
    res_out = [
        ReservationOut(
            id=p.id,
            lot_id=p.lot_id,
            lot_code=lot_code_cache.get(p.lot_id),
            qty_reserved=p.qty_reserved,
        )
        for p in proposed
    ]
    return PreflightResult(
        work_order_id=wo.id, status="reserved", reservations=res_out, shortages=[]
    )


def start_work_order(db: Session, wo_id: int, site_id: str) -> WorkOrder:
    wo = get_work_order(db, wo_id, site_id)
    if wo.status != "reserved":
        raise ValueError(f"WO must be in reserved (currently '{wo.status}')")
    wo.status = "running"
    wo.started_at = datetime.now(UTC)
    db.commit()
    db.refresh(wo)
    return wo


def complete_work_order(
    db: Session, wo_id: int, site_id: str, payload: WorkOrderCompleteRequest
) -> tuple[WorkOrder, Lot]:
    """Decrement ingredient lots by reservation qty, write LotGenealogy edges,
    create one child Lot of the recipe's product SKU at `actual_qty`."""
    wo = get_work_order(db, wo_id, site_id)
    if wo.status != "running":
        raise ValueError(f"WO must be in running (currently '{wo.status}')")

    reservations = get_reservations(db, wo.id)
    recipe = get_recipe(db, wo.recipe_id)
    product_sku = db.get(SKU, recipe.sku_id)
    if product_sku is None:
        raise ValueError("Recipe product SKU missing")

    # Decrement ingredient lots.
    for res in reservations:
        lot = db.get(Lot, res.lot_id)
        if lot is None:
            raise ValueError(f"Reserved lot {res.lot_id} missing at completion")
        if lot.quantity < res.qty_reserved:
            # Shouldn't happen under normal flow — defensive guard.
            raise ValueError(
                f"Lot {lot.lot_code} qty {lot.quantity} below reservation "
                f"{res.qty_reserved}"
            )
        lot.quantity -= res.qty_reserved

    # Create the child (product) lot.
    child_code = (
        payload.output_lot_code
        or f"LOT-PROD-{wo.id}-{int(datetime.now(UTC).timestamp())}"
    )
    child_lot = Lot(
        site_id=site_id,
        lot_code=child_code,
        sku_id=product_sku.id,
        quantity=payload.actual_qty,
        qa_hold=product_sku.requires_qc,
    )
    db.add(child_lot)
    db.flush()

    # Write genealogy edges (one per reservation).
    for res in reservations:
        db.add(
            LotGenealogy(
                parent_lot_id=res.lot_id,
                child_lot_id=child_lot.id,
                quantity_consumed=res.qty_reserved,
            )
        )

    wo.status = "completed"
    wo.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(wo)
    db.refresh(child_lot)

    # TODO(SCO-51 v2): yield variance audit. If
    #   abs(actual_qty - target_qty) / target_qty > production.yield_variance_threshold
    # emit `production.yield_variance_high` via wms.services.audit_log.record().
    return wo, child_lot


def cancel_work_order(db: Session, wo_id: int, site_id: str) -> WorkOrder:
    wo = get_work_order(db, wo_id, site_id)
    if wo.status in ("completed", "cancelled"):
        # Idempotent — canceling a terminal WO is a noop.
        return wo
    db.query(WorkOrderReservation).filter(
        WorkOrderReservation.work_order_id == wo.id
    ).delete(synchronize_session=False)
    wo.status = "cancelled"
    db.commit()
    db.refresh(wo)
    return wo

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

    # TODO(SCO-51 v2): version-bump-on-edit.
    # ────────────────────────────────────────────────────────────────────
    # On create_recipe today we always set version=1 because we don't
    # distinguish "first recipe for this SKU" from "next version of an
    # existing recipe". The edit_recipe endpoint (api/v1/production.py)
    # is the proper place for version bumps; this branch handles initial
    # creation only.
    #
    # When edit_recipe is implemented, this initial-create path should:
    #   - Query MAX(version) for payload.sku_id.
    #   - If no rows exist → version = 1 (current behavior).
    #   - If rows exist → reject 409 "Use PUT /recipes/{id} to bump
    #     version instead of POST /recipes for an additional version."
    # That keeps the create vs version-bump semantics distinct at the
    # API level rather than overloading POST.
    # ────────────────────────────────────────────────────────────────────
    # SCO-142: persist the optional display name (trimmed, empty-allowed —
    # the serializer falls back to "Recipe #{id}" for blank names).
    recipe = Recipe(
        sku_id=payload.sku_id,
        version=1,
        name=(payload.name or "").strip()[:80],
    )
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
        # TODO(SCO-51 v2): BOM unit conversion.
        # ────────────────────────────────────────────────────────────────
        # Today preflight assumes recipe.uom == lot.uom for every
        # ingredient. Real plants run recipes in (e.g.) kilograms while
        # lots are received in pounds, or in liters of solvent while the
        # SKU is tracked in pounds. The conversion is one of:
        #   - mass→mass (kg↔lb): pure unit factor, always possible
        #   - volume→volume (L↔gal): pure unit factor, always possible
        #   - mass↔volume: requires SKU.density_kg_per_l — currently NOT
        #     in the schema. Add it before wiring this branch.
        #   - count↔mass: requires SKU.unit_weight_kg (already present)
        #
        # Algorithm to implement:
        #   1. Resolve lot.sku to get its native uom + unit_weight_kg
        #      (+ density once added).
        #   2. Call _convert_uom(from_uom=line.uom, to_uom=lot_sku.uom,
        #                        qty=required, sku=lot_sku).
        #   3. _convert_uom returns either a float (converted qty) or
        #      raises ConversionImpossibleError with structured detail.
        #   4. On ConversionImpossibleError: ADD an entry to shortages[] with
        #          error_kind="conversion_impossible"
        #          required (original), available=0, short_by=required,
        #          from_uom=line.uom, to_uom=lot_sku.uom,
        #          message="No density on SKU XYZ — cannot convert kg→L"
        #      DO NOT raise — preflight stays a 200 with shortages[] so
        #      the UI can render the failure inline next to qty
        #      shortages (see frontend doPreflight in production.js).
        #   5. On success: use converted qty as `required` for the rest
        #      of the FIFO loop below.
        #
        # Schema TODO: add SKU.density_kg_per_l (nullable Float) before
        # wiring mass↔volume conversion. unit_weight_kg already exists.
        # ────────────────────────────────────────────────────────────────
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
    # TODO(SCO-51 v2): atomic locking on reservation write.
    # ────────────────────────────────────────────────────────────────────
    # Today: two concurrent preflights on the same scarce lot read the
    # same `lot.quantity`, each compute a satisfying reservation set, and
    # both commit — over-allocating by the smaller of the two.
    #
    # Engine-specific fix (must branch on db.bind.dialect.name):
    #   - SQLite ('sqlite'):
    #       db.connection().execute(text("BEGIN IMMEDIATE"))
    #     Must be called BEFORE the first _fifo_lots() in this function,
    #     not here. Acquires a write lock on the whole DB until commit —
    #     serializes preflights but doesn't block reads. Acceptable for
    #     single-site SQLite deployments; not for hot production paths.
    #   - PostgreSQL ('postgresql'):
    #       Modify _fifo_lots() to append `.with_for_update(skip_locked=True)`
    #       on the SQLAlchemy query. This row-locks each candidate lot;
    #       a concurrent preflight either waits or skips locked rows
    #       (the skip variant prevents deadlock at the cost of possibly
    #       returning a shortage that would have resolved with a tiny
    #       wait — accept that tradeoff).
    #   - Other dialects: raise on startup. We're not supporting them.
    #
    # Test that proves the fix:
    #   tests/test_production_concurrency.py — spawn two threads, each
    #   preflighting a WO that needs the same lot. After both return,
    #   sum(reservations).qty must equal lot.quantity_before — never
    #   exceed it. Today this test would fail; that's the canary.
    # ────────────────────────────────────────────────────────────────────
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

    # TODO(SCO-51 v2): yield variance audit.
    # ────────────────────────────────────────────────────────────────────
    # The frontend's complete-WO modal already warns the operator
    # client-side when |actual - target| / target > 0.01 — that's UX
    # only and not load-bearing. The server-side audit event is what
    # makes variance investigable after the fact.
    #
    # Implementation:
    #   threshold = settings_store.get(
    #       "production.yield_variance_threshold",
    #       scope_type="site", scope_value=site_id,
    #       default=0.01,
    #   )
    #   variance = abs(payload.actual_qty - wo.target_qty) / wo.target_qty
    #   if variance > threshold:
    #       audit_log.record(
    #           db,
    #           action="production.yield_variance_high",
    #           actor_id=user.id,   # add user param to complete_work_order
    #           target_type="work_order",
    #           target_id=wo.id,
    #           detail_json={
    #               "work_order_id": wo.id,
    #               "recipe_id": wo.recipe_id,
    #               "target_qty": wo.target_qty,
    #               "actual_qty": payload.actual_qty,
    #               "variance": round(variance, 4),
    #               "threshold": threshold,
    #               "direction": "over" if payload.actual_qty > wo.target_qty else "under",
    #               "child_lot_code": child_lot.lot_code,
    #           },
    #       )
    #
    # Both over- and under-yield count. Over-yield often signals
    # ingredient misweighing; under-yield can signal contamination,
    # equipment loss, or a recipe error.
    #
    # The audit row alone is queryable via /admin/audit?action=
    # production.yield_variance_high — the frontend already renders that
    # feed on production.html (Yield Variance section, currently empty).
    #
    # Tests to add (tests/test_production_yield_variance.py):
    #   - over-yield emits the event
    #   - under-yield emits the event
    #   - within-threshold does NOT emit
    #   - boundary (variance == threshold): does NOT emit (strict >)
    #   - detail_json shape matches the spec above
    #   - threshold from settings store overrides default
    # ────────────────────────────────────────────────────────────────────
    return wo, child_lot


def count_workorders_for_recipe(db: Session, recipe_id: int) -> int:
    """SCO-142: how many WorkOrders reference this recipe.

    Used by the delete_recipe guard to refuse with a 409 + count when the
    recipe is still in use. Counts WOs across all statuses (including
    completed/cancelled) because the snapshot pattern means historical
    rows still meaningfully reference the recipe id for audit walks.
    """
    return (
        db.query(WorkOrder).filter(WorkOrder.recipe_id == recipe_id).count()
    )


def delete_recipe(db: Session, recipe_id: int) -> dict:
    """SCO-142: hard-delete a recipe + its lines.

    Caller (router) handles permission gating + audit emission. This
    service is the FK-safe pivot point:
      - Raises ValueError("not found") if recipe missing → router → 404.
      - Raises ValueError("in use by N work order(s)") if any WO
        references the recipe → router → 409 with N in detail.
      - Otherwise deletes RecipeLine rows then the Recipe row in a
        single commit, and returns a snapshot dict the router can use
        for the audit event detail.
    """
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise ValueError(f"Recipe {recipe_id} not found")
    wo_count = count_workorders_for_recipe(db, recipe.id)
    if wo_count > 0:
        # Surface the count so the operator knows what to clean up first.
        raise ValueError(
            f"Recipe is referenced by {wo_count} work order(s). "
            f"Cancel or complete those work orders before deleting."
        )
    # Snapshot before delete — router uses this for audit detail_json.
    snapshot = {
        "id": recipe.id,
        "name": recipe.name or "",
        "sku_id": recipe.sku_id,
        "version": recipe.version,
    }
    # Cascade RecipeLine rows (recipe-owned by definition).
    db.query(RecipeLine).filter(RecipeLine.recipe_id == recipe.id).delete(
        synchronize_session=False
    )
    db.delete(recipe)
    db.commit()
    return snapshot


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


# ═══════════════════════════════════════════════════════════════════════════
# SCO-51 v2 contract stubs — frontend already calls these contracts; the
# implementations below raise so the failure mode is loud not silent.
# ═══════════════════════════════════════════════════════════════════════════


class ConversionImpossibleError(Exception):
    """Raised when BOM unit conversion cannot be performed.

    Carries enough detail for the caller (preflight_work_order) to convert
    it into a structured shortage entry rather than a 500. Do NOT let this
    bubble up to the API layer — catch it inside the FIFO loop.
    """

    def __init__(self, from_uom: str, to_uom: str, reason: str, sku_code: str = ""):
        super().__init__(f"Cannot convert {from_uom}→{to_uom} for {sku_code}: {reason}")
        self.from_uom = from_uom
        self.to_uom = to_uom
        self.reason = reason
        self.sku_code = sku_code

    def to_detail(self) -> dict:
        """Shape consumed by the frontend's conversion-impossible row."""
        return {
            "error_kind": "conversion_impossible",
            "from_uom": self.from_uom,
            "to_uom": self.to_uom,
            "reason": self.reason,
            "sku_code": self.sku_code,
        }


def _convert_uom(*, from_uom: str, to_uom: str, qty: float, sku) -> float:
    """Convert `qty` from `from_uom` to `to_uom` for a given SKU.

    NOT YET IMPLEMENTED (SCO-51 v2). When wired:
      - Same-uom: return qty unchanged.
      - Mass↔mass (kg↔lb↔g↔oz): pure factor table.
      - Volume↔volume (L↔gal↔mL↔fl_oz): pure factor table.
      - Mass↔volume: requires sku.density_kg_per_l (not yet in schema).
        Raise ConversionImpossibleError if missing.
      - Count↔mass: requires sku.unit_weight_kg (already present).
        Raise ConversionImpossibleError if zero/None.

    Raises:
        ConversionImpossibleError: when the conversion is fundamentally
            impossible given the SKU's available metadata.
    """
    if from_uom == to_uom:
        return qty
    # Conservative default until the conversion table is implemented.
    sku_code = getattr(sku, "code", "") or ""
    raise ConversionImpossibleError(
        from_uom=from_uom,
        to_uom=to_uom,
        reason="unit conversion not yet implemented",
        sku_code=sku_code,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SCO-51 v2 test checklist (mirrors PAGES_WORKFLOW.md §3 — owed tests):
#
#   tests/test_production_versioning.py
#     [ ] PUT /recipes/{id} creates v+1 row, leaves original unchanged
#     [ ] running WO retains its recipe_version_snapshot through edits
#     [ ] Lvl < production.recipe_edit_requires_level → 403
#     [ ] POST /recipes for an existing sku_id → 409 (force PUT path)
#
#   tests/test_production_conversion.py
#     [ ] same-uom: identity passthrough
#     [ ] mass→mass (kg→lb): correct factor
#     [ ] count→mass via unit_weight_kg
#     [ ] mass→volume without density → ConversionImpossibleError
#     [ ] preflight returns shortage with error_kind=conversion_impossible
#         when conversion fails; does NOT raise to the API layer
#
#   tests/test_production_concurrency.py
#     [ ] two parallel preflights on the same scarce lot serialize;
#         sum(reservations).qty ≤ lot.quantity_before
#     [ ] SQLite BEGIN IMMEDIATE path
#     [ ] Postgres skip_locked path (skipped on SQLite CI)
#
#   tests/test_production_yield_variance.py
#     [ ] over-yield emits production.yield_variance_high
#     [ ] under-yield emits same event
#     [ ] within-threshold does NOT emit
#     [ ] boundary (variance == threshold): does NOT emit (strict >)
#     [ ] detail_json shape matches spec in complete_work_order TODO
#     [ ] settings_store override of threshold takes effect
# ═══════════════════════════════════════════════════════════════════════════

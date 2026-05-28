"""Production Pydantic schemas — recipes + work orders (SCO-51 MVP)."""

from datetime import datetime

from pydantic import BaseModel, Field

# ─── Recipes ────────────────────────────────────────────────────────────

class RecipeLineIn(BaseModel):
    ingredient_sku_id: int
    qty_per_unit: float = Field(gt=0)
    uom: str = "EA"


class RecipeLineOut(BaseModel):
    id: int
    ingredient_sku_id: int
    ingredient_sku_code: str | None = None
    qty_per_unit: float
    uom: str

    model_config = {"from_attributes": True}


class RecipeCreate(BaseModel):
    sku_id: int
    # SCO-142: optional human-readable label for the recipe. Empty string
    # is accepted; the response serializer falls back to "Recipe #{id}"
    # so the UI always has something readable to render.
    name: str = Field(default="", max_length=80)
    lines: list[RecipeLineIn] = Field(min_length=1)


class RecipeOut(BaseModel):
    id: int
    name: str
    sku_id: int
    sku_code: str | None = None
    version: int
    locked_by: int | None
    created_at: datetime
    lines: list[RecipeLineOut] = []

    model_config = {"from_attributes": True}


# ─── Work Orders ────────────────────────────────────────────────────────

class WorkOrderCreate(BaseModel):
    recipe_id: int
    # SCO-143: target yield in base UoM, decimal.
    target_qty: float = Field(gt=0)


class ReservationOut(BaseModel):
    id: int
    lot_id: int
    lot_code: str | None = None
    qty_reserved: float  # SCO-143

    model_config = {"from_attributes": True}


class ShortageOut(BaseModel):
    ingredient_sku_id: int
    ingredient_sku_code: str | None = None
    required: float
    available: float
    short_by: float


class WorkOrderOut(BaseModel):
    id: int
    recipe_id: int
    recipe_version_snapshot: int
    target_qty: float  # SCO-143
    status: str
    site_id: str
    started_at: datetime | None
    completed_at: datetime | None
    supervisor_id: int | None
    created_at: datetime
    reservations: list[ReservationOut] = []

    model_config = {"from_attributes": True}


class PreflightResult(BaseModel):
    work_order_id: int
    status: str  # "reserved" or "draft" (when shortages exist)
    reservations: list[ReservationOut] = []
    shortages: list[ShortageOut] = []


class WorkOrderCompleteRequest(BaseModel):
    # SCO-143: actual yield in base UoM, decimal.
    actual_qty: float = Field(ge=0)
    output_lot_code: str | None = None


class WorkOrderCancelRequest(BaseModel):
    reason: str | None = None

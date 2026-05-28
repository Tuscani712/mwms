"""Inventory Pydantic schemas."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class LotOut(BaseModel):
    id: int
    lot_code: str
    sku_code: str
    sku_description: str
    location_code: str | None
    location_is_overflow: bool
    location_is_qa_hold: bool
    quantity: float  # SCO-143: base UoM, decimal-capable
    qa_hold: bool
    received_at: datetime
    expires_at: date | None
    supplier: str | None
    aging_bucket: str  # "0-30" | "31-60" | "61-90" | "90+"
    expiring_soon: bool

    model_config = {"from_attributes": True}


class LotSearchOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[LotOut]


class SKUDetailOut(BaseModel):
    sku_code: str
    description: str
    uom: str
    reorder_point: float  # SCO-143
    safety_stock: float  # SCO-143
    on_hand_total: float  # SCO-143
    available: float  # excludes qa_hold + expired
    qa_hold_qty: float
    expired_qty: float
    lot_count: int


class InventoryKPIs(BaseModel):
    total_on_hand: float  # SCO-143
    available: float
    qa_hold_qty: float
    qa_hold_lots: int
    slow_movers: int  # SKUs with zero outbound movement (placeholder until reports module)
    skus_below_safety: int
    sku_count: int
    cached_at: datetime


class AdjustRequest(BaseModel):
    lot_id: int
    delta: float  # SCO-143: may be negative; decimal-capable
    reason: str = Field(min_length=1, max_length=255)


class AdjustOut(BaseModel):
    lot_id: int
    was: float  # SCO-143
    now: float
    delta: float


class BelowSafetyRow(BaseModel):
    sku_code: str
    description: str
    available: float  # SCO-143
    reorder_point: float
    safety_stock: float
    shortfall: float  # safety_stock - available, always positive

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
    quantity: int
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
    reorder_point: int
    safety_stock: int
    on_hand_total: int
    available: int  # excludes qa_hold + expired
    qa_hold_qty: int
    expired_qty: int
    lot_count: int


class InventoryKPIs(BaseModel):
    total_on_hand: int
    available: int
    qa_hold_qty: int
    qa_hold_lots: int
    slow_movers: int  # SKUs with zero outbound movement (placeholder until reports module)
    skus_below_safety: int
    cached_at: datetime


class AdjustRequest(BaseModel):
    lot_id: int
    delta: int  # may be negative
    reason: str = Field(min_length=1, max_length=255)


class AdjustOut(BaseModel):
    lot_id: int
    was: int
    now: int
    delta: int


class BelowSafetyRow(BaseModel):
    sku_code: str
    description: str
    available: int
    reorder_point: int
    safety_stock: int
    shortfall: int  # safety_stock - available, always positive

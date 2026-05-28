"""Shipping Pydantic schemas."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class OrderLineOut(BaseModel):
    id: int
    sku_code: str
    sku_description: str
    qty_ordered: float  # SCO-143: base UoM
    qty_picked: float
    fefo_required: bool

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    order_code: str
    customer: str
    priority: str
    status: str
    ship_by: date | None
    truck_id: str | None
    lines: list[OrderLineOut] = []

    model_config = {"from_attributes": True}


class PickAssignmentRequest(BaseModel):
    order_id: int
    order_line_id: int
    qty: float = Field(gt=0)  # SCO-143
    strategy: str = Field(default="FIFO", pattern="^(FIFO|FEFO)$")


class PickOut(BaseModel):
    id: int
    order_id: int
    lot_code: str
    qty_picked: float  # SCO-143
    strategy: str
    picked_at: datetime

    model_config = {"from_attributes": True}


class ConsolidationLotPlan(BaseModel):
    lot_code: str
    location_code: str | None
    qty: float  # SCO-143
    expires_at: date | None
    strategy: str


class ConsolidationPlan(BaseModel):
    order_code: str
    sku_code: str
    qty_required: float  # SCO-143
    qty_available: float
    plan: list[ConsolidationLotPlan]
    fefo_triggered: bool


class TruckLoadRequest(BaseModel):
    shipment_id: int
    order_id: int


class TruckLoadStatus(BaseModel):
    shipment_id: int
    truck_id: str
    capacity_kg: float
    loaded_kg: float
    remaining_kg: float
    over_budget: bool


class PackingSlipLine(BaseModel):
    sku_code: str
    description: str
    lot_code: str
    qty: float  # SCO-143


class PackingSlip(BaseModel):
    order_code: str
    customer: str
    shipped_at: datetime
    lines: list[PackingSlipLine]


class OrderLineIn(BaseModel):
    sku_id: int
    qty_ordered: float = Field(gt=0)  # SCO-143
    fefo_required: bool = False


class OrderCreate(BaseModel):
    order_code: str = Field(min_length=1, max_length=40)
    customer: str = Field(min_length=1, max_length=120)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    ship_by: date | None = None
    lines: list[OrderLineIn] = Field(min_length=1)

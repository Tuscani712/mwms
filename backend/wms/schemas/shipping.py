"""Shipping Pydantic schemas."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class OrderLineOut(BaseModel):
    id: int
    sku_code: str
    sku_description: str
    qty_ordered: int
    qty_picked: int
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
    qty: int = Field(gt=0)
    strategy: str = Field(default="FIFO", pattern="^(FIFO|FEFO)$")


class PickOut(BaseModel):
    id: int
    order_id: int
    lot_code: str
    qty_picked: int
    strategy: str
    picked_at: datetime

    model_config = {"from_attributes": True}


class ConsolidationLotPlan(BaseModel):
    lot_code: str
    location_code: str | None
    qty: int
    expires_at: date | None
    strategy: str


class ConsolidationPlan(BaseModel):
    order_code: str
    sku_code: str
    qty_required: int
    qty_available: int
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
    qty: int


class PackingSlip(BaseModel):
    order_code: str
    customer: str
    shipped_at: datetime
    lines: list[PackingSlipLine]

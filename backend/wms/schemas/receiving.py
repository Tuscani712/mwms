"""Receiving Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class ASNLineOut(BaseModel):
    id: int
    sku_code: str
    sku_description: str
    expected_qty: int
    received_qty: int
    qc_status: str
    # SCO-138: propagate the SKU's QC requirement so the receipt editor can
    # auto-pass lines whose SKU was created with "Does Not Require QC".
    requires_qc: bool = False

    model_config = {"from_attributes": True}


class ASNOut(BaseModel):
    id: int
    asn_code: str
    supplier: str
    dock_door: str | None
    status: str
    eta: datetime | None
    arrived_at: datetime | None
    lines: list[ASNLineOut] = []

    model_config = {"from_attributes": True}


class CheckInRequest(BaseModel):
    asn_id: int
    dock_door: str = Field(min_length=1, max_length=10)


class ReceiptLineIn(BaseModel):
    asn_line_id: int
    qty_received: int = Field(ge=0)
    qc_passed: bool = True


class ReceiptCreate(BaseModel):
    asn_id: int
    lines: list[ReceiptLineIn]
    variance_notes: str | None = None


class ReceiptOut(BaseModel):
    id: int
    asn_id: int
    received_at: datetime
    variance_notes: str | None = None
    total_variance: int = 0
    lot_ids: list[int] = []

    model_config = {"from_attributes": True}


class PutawaySuggestion(BaseModel):
    sku_code: str
    qty: int
    primary_location: str | None
    primary_capacity_left: int
    overflow_location: str | None
    overflow_capacity_left: int
    rationale: str


class ASNLineIn(BaseModel):
    sku_id: int
    expected_qty: int = Field(ge=1)


class ASNCreate(BaseModel):
    asn_code: str = Field(min_length=1, max_length=40)
    supplier: str = Field(min_length=1, max_length=120)
    eta: datetime | None = None
    lines: list[ASNLineIn] = Field(min_length=1)

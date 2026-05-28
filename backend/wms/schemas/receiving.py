"""Receiving Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class ASNLineOut(BaseModel):
    id: int
    sku_code: str
    sku_description: str
    # SCO-143: ASN quantities are in PURCHASE UoM (bag, pack, case).
    expected_qty: float
    received_qty: float
    qc_status: str
    # SCO-138: propagate the SKU's QC requirement so the receipt editor can
    # auto-pass lines whose SKU was created with "Does Not Require QC".
    requires_qc: bool = False
    # SCO-143: expose conversion context so the UI can show "10 BAG ×
    # 50.0 LB = 500 LB stocked" inline without a second fetch. Blank
    # purchase_uom + factor=1.0 means no conversion (purchased as base).
    purchase_uom: str = ""
    base_uom: str = "EA"
    base_per_purchase_unit: float = 1.0

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
    # SCO-143: qty in PURCHASE UoM; service multiplies by
    # sku.base_per_purchase_unit to derive Lot.quantity in base UoM.
    qty_received: float = Field(ge=0)
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
    total_variance: float = 0.0  # SCO-143
    lot_ids: list[int] = []

    model_config = {"from_attributes": True}


class PutawaySuggestion(BaseModel):
    sku_code: str
    qty: float  # SCO-143: base UoM
    primary_location: str | None
    primary_capacity_left: int  # capacities stay int — slot-count, not weight
    overflow_location: str | None
    overflow_capacity_left: int
    rationale: str


class ASNLineIn(BaseModel):
    sku_id: int
    # SCO-143: PURCHASE UoM (e.g., 10 bags), decimal-allowed (broken half-bag).
    expected_qty: float = Field(gt=0)


class ASNCreate(BaseModel):
    asn_code: str = Field(min_length=1, max_length=40)
    supplier: str = Field(min_length=1, max_length=120)
    eta: datetime | None = None
    lines: list[ASNLineIn] = Field(min_length=1)

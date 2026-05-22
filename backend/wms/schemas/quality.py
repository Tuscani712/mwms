"""Quality (QA) Pydantic schemas — SCO-50 MVP."""

from datetime import datetime

from pydantic import BaseModel, Field


class HoldOpenRequest(BaseModel):
    lot_id: int
    reason: str = Field(min_length=1, max_length=255)
    severity: str = "medium"  # low / medium / high


class HoldDecideRequest(BaseModel):
    decision: str  # release | destroy | rework


class HoldOut(BaseModel):
    id: int
    site_id: str
    lot_id: int
    lot_code: str | None = None
    sku_code: str | None = None
    reason: str
    severity: str
    opened_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    opened_by: int | None
    status: str  # derived: 'open' if resolved_at None else 'resolved'

    model_config = {"from_attributes": True}

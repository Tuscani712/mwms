"""User Title Pydantic schemas (SCO-70)."""

from datetime import datetime

from pydantic import BaseModel, Field


class TitleOut(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime
    created_by: int | None = None

    model_config = {"from_attributes": True}


class TitleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class TitleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_active: bool | None = None

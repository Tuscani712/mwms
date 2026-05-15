"""Profile-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

PROFILE_FIELDS = ["email", "password", "display_name", "display_picture", "theme"]


class FieldPolicy(BaseModel):
    visible: bool = True
    editable: bool = True


class ProfileOut(BaseModel):
    """Returned by GET /profile — full read-only identity + editable + per-field policy."""

    # Read-only identity
    id: int
    employee_code: str
    full_name: str
    site_id: str
    department: str | None
    role: str
    shift: str | None
    permission_level: int

    # Editable values (current)
    email: str
    display_name: str | None
    display_picture_url: str | None
    theme: str

    # Policy resolved at the user×role×site×global level
    field_policy: dict[str, FieldPolicy]

    # Pending requests so the UI can show "awaiting approval" pills
    pending_requests: list[str] = []


class EmailUpdate(BaseModel):
    email: EmailStr


class PasswordUpdate(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=4, max_length=72)


class DisplayChangeRequest(BaseModel):
    requested_value: str = Field(min_length=1, max_length=500)


class ChangeRequestOut(BaseModel):
    id: int
    user_id: int
    field_name: str
    requested_value: str
    status: str
    requested_at: datetime
    decided_by: int | None = None
    decided_at: datetime | None = None
    decision_notes: str | None = None

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    approve: bool
    notes: str | None = None


class FieldVisibilityRule(BaseModel):
    id: int | None = None
    scope_type: str = Field(pattern="^(global|site|role|user)$")
    scope_value: str | None = None
    field_name: str
    visible: bool = True
    editable: bool = True

    model_config = {"from_attributes": True}

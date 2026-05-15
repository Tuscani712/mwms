"""Auth-related Pydantic schemas."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    employee_code: str
    password: str
    site_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    site_id: str
    role: str
    full_name: str
    permission_level: int


class UserOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    email: str
    role: str
    site_id: str
    permission_level: int

    model_config = {"from_attributes": True}

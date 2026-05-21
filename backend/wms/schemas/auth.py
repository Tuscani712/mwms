"""Auth-related Pydantic schemas."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    employee_code: str
    password: str
    site_id: str


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    site_id: str
    role: str
    full_name: str
    permission_level: int
    # MFA fields — populated when a second factor is required.
    mfa_required: bool = False
    mfa_enrolled: bool = False
    mfa_challenge_token: str | None = None
    # SCO-99: signals the frontend to push the user into a forced
    # password-change flow before any other route is reachable.
    must_change_password: bool = False


class MFAChallenge(BaseModel):
    challenge_token: str
    code: str


class MFAEnrollVerify(BaseModel):
    code: str


class MFAResetRequest(BaseModel):
    user_id: int


class UserOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    email: str
    role: str
    site_id: str
    permission_level: int

    model_config = {"from_attributes": True}

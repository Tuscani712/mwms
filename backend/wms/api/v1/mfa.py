"""MFA endpoints — profile enrollment + login challenge verification."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wms.core.config import get_settings
from wms.core.deps import get_current_user, get_session
from wms.core.security import create_access_token, decode_token
from wms.models import User, UserMFA
from wms.schemas.auth import MFAChallenge, MFAEnrollVerify, TokenResponse
from wms.services import mfa as mfa_svc

MFA_CHALLENGE_TTL_SECONDS = 300

router = APIRouter(prefix="/profile/mfa", tags=["mfa"])
auth_router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


class EnrollmentStart(BaseModel):
    otpauth_uri: str
    backup_codes: list[str]
    secret: str  # exposed once so the user can manually key it if QR fails


class MFAStatus(BaseModel):
    enrolled: bool
    has_pending_enrollment: bool


def create_mfa_challenge_token(employee_code: str, site_id: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": employee_code,
        "site_id": site_id,
        "purpose": "mfa_challenge",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=MFA_CHALLENGE_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_mfa_challenge(token: str) -> dict:
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid challenge token: {e}") from e
    if payload.get("purpose") != "mfa_challenge":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not an MFA challenge token")
    return payload


@router.get("/status", response_model=MFAStatus)
def mfa_status(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> MFAStatus:
    row = db.query(UserMFA).filter(UserMFA.user_id == user.id).one_or_none()
    return MFAStatus(
        enrolled=bool(row and row.enabled),
        has_pending_enrollment=bool(row and not row.enabled),
    )


@router.post("/setup", response_model=EnrollmentStart)
def setup_mfa(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> EnrollmentStart:
    row, codes, uri = mfa_svc.begin_enrollment(db, user)
    return EnrollmentStart(otpauth_uri=uri, backup_codes=codes, secret=row.secret)


@router.post("/verify", response_model=MFAStatus)
def verify_mfa(
    payload: MFAEnrollVerify,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MFAStatus:
    try:
        mfa_svc.confirm_enrollment(db, user, payload.code)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return MFAStatus(enrolled=True, has_pending_enrollment=False)


@router.delete("/disable", response_model=MFAStatus)
def disable_mfa(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> MFAStatus:
    mfa_svc.disable_mfa(db, user.id)
    return MFAStatus(enrolled=False, has_pending_enrollment=False)


@auth_router.post("/verify", response_model=TokenResponse)
def complete_mfa_login(
    payload: MFAChallenge, db: Session = Depends(get_session)
) -> TokenResponse:
    """Exchange (challenge_token, code) for a full access token."""
    claims = decode_mfa_challenge(payload.challenge_token)
    user = (
        db.query(User)
        .filter(User.employee_code == claims["sub"], User.site_id == claims["site_id"])
        .one_or_none()
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if not mfa_svc.verify_user_code(db, user, payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA code")

    token = create_access_token(subject=user.employee_code, site_id=user.site_id, role=user.role)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return TokenResponse(
        access_token=token,
        site_id=user.site_id,
        role=user.role,
        full_name=user.full_name,
        permission_level=user.permission_level,
        mfa_required=False,
        mfa_enrolled=True,
    )


__all__ = ["router", "auth_router", "create_mfa_challenge_token", "JWTError"]

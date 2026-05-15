"""Auth router — login, current user."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from wms.api.v1.mfa import create_mfa_challenge_token
from wms.core.deps import get_current_user, get_session
from wms.core.security import create_access_token, verify_password
from wms.models import User
from wms.schemas.auth import LoginRequest, TokenResponse, UserOut
from wms.services import audit_log as audit
from wms.services import mfa as mfa_svc
from wms.services import password_policy as policy_svc

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_session),
) -> TokenResponse:
    user = (
        db.query(User)
        .filter(
            User.employee_code == payload.employee_code,
            User.site_id == payload.site_id,
            User.is_active.is_(True),
        )
        .first()
    )
    if not user or not verify_password(payload.password, user.hashed_password):
        audit.record(
            db,
            event_type=audit.EVT_LOGIN_FAILURE,
            user_id=user.id if user else None,
            site_id=payload.site_id,
            request=request,
            detail={"employee_code": payload.employee_code},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials or site")

    resolved = policy_svc.resolve_password_policy(db, user)
    enrolled = mfa_svc.is_enrolled(db, user.id)

    if resolved.get("require_mfa") and enrolled:
        # Password is correct, but the user must present a second factor.
        return TokenResponse(
            access_token=None,
            site_id=user.site_id,
            role=user.role,
            full_name=user.full_name,
            permission_level=user.permission_level,
            mfa_required=True,
            mfa_enrolled=True,
            mfa_challenge_token=create_mfa_challenge_token(user.employee_code, user.site_id),
        )

    token = create_access_token(subject=user.employee_code, site_id=user.site_id, role=user.role)
    user.last_login_at = datetime.now(UTC)
    audit.record(
        db,
        event_type=audit.EVT_LOGIN_SUCCESS,
        user_id=user.id,
        site_id=user.site_id,
        request=request,
        commit=False,
    )
    db.commit()

    return TokenResponse(
        access_token=token,
        site_id=user.site_id,
        role=user.role,
        full_name=user.full_name,
        permission_level=user.permission_level,
        mfa_required=False,
        # If policy requires MFA but user isn't enrolled, the frontend treats this
        # as a forced-enrollment session (token is valid for /profile/mfa/setup).
        mfa_enrolled=enrolled,
    )


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> User:
    return current

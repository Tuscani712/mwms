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
from wms.services import login_guard as guard
from wms.services import mfa as mfa_svc
from wms.services import password_policy as policy_svc

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _client_ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_session),
) -> TokenResponse:
    ip = _client_ip(request)
    ua = _client_ua(request)

    # SEC-1: per-IP rate limit. Stops 1/sec-faster credential stuffing before
    # touching DB. Trusted-local (no client.host) skips the limit.
    ip_ok, ip_retry = guard.check_ip_rate_limit(ip)
    if not ip_ok:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests; slow down.",
            headers={"Retry-After": str(max(1, int(ip_retry) + 1))},
        )

    # SEC-1: per-account lockout. Stage derives from failures since last reset.
    lock = guard.evaluate_lockout(db, payload.employee_code, payload.site_id)
    if lock.locked:
        guard.record_attempt(
            db,
            employee_code=payload.employee_code,
            site_id=payload.site_id,
            success=False,
            failure_reason="locked_out",
            ip=ip,
            user_agent=ua,
        )
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account temporarily locked. Try again in {lock.retry_after_seconds}s.",
            headers={"Retry-After": str(lock.retry_after_seconds)},
        )

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
        guard.record_attempt(
            db,
            employee_code=payload.employee_code,
            site_id=payload.site_id,
            success=False,
            failure_reason="bad_credentials" if user else "unknown_user",
            ip=ip,
            user_agent=ua,
        )
        audit.record(
            db,
            event_type=audit.EVT_LOGIN_FAILURE,
            user_id=user.id if user else None,
            site_id=payload.site_id,
            request=request,
            detail={"employee_code": payload.employee_code},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials or site")

    # SEC-1: password verified — record success so lockout state resets even if
    # MFA challenge follows. Brute-force protection is for the password layer;
    # MFA has its own throttling envelope.
    guard.record_attempt(
        db,
        employee_code=payload.employee_code,
        site_id=payload.site_id,
        success=True,
        ip=ip,
        user_agent=ua,
        commit=False,
    )

    resolved = policy_svc.resolve_password_policy(db, user)
    enrolled = mfa_svc.is_enrolled(db, user.id)

    if resolved.get("require_mfa") and enrolled:
        # Password is correct, but the user must present a second factor.
        # Commit the success row so lockout state resets even before MFA verify.
        db.commit()
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
        # SCO-99: signal force-change so the frontend can route to the modal
        # before exposing the user to any other page chrome.
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> User:
    return current

"""Auth router — login, current user."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.core.security import create_access_token, verify_password
from wms.models import User
from wms.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_session)) -> TokenResponse:
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
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials or site")

    token = create_access_token(subject=user.employee_code, site_id=user.site_id, role=user.role)
    user.last_login_at = datetime.now(UTC)
    db.commit()

    return TokenResponse(
        access_token=token,
        site_id=user.site_id,
        role=user.role,
        full_name=user.full_name,
        permission_level=user.permission_level,
    )


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> User:
    return current

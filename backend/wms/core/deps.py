"""FastAPI dependencies: DB session + current authenticated user with per-site enforcement."""

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from wms.core.security import decode_token
from wms.db.session import get_db
from wms.models import Site, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# SCO-99: when must_change_password is set, the user can only hit these
# paths until they rotate. Anything else returns 403 password_change_required.
_FORCE_CHANGE_ALLOWED_SUFFIXES = (
    "/auth/me",
    "/auth/login",
    "/profile/password",
    "/profile/password-policy",
    "/health",
)


def get_session() -> Generator[Session, None, None]:
    yield from get_db()


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_session),
) -> User:
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e

    employee_code = payload.get("sub")
    site_id = payload.get("site_id")
    if not employee_code or not site_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token")

    user = (
        db.query(User)
        .filter(User.employee_code == employee_code, User.site_id == site_id, User.is_active.is_(True))
        .first()
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    # SECURITY_AUDIT.md L-4: reject tokens for sites that have been taken offline
    # (e.g., maintenance window, security incident, decommission).
    site = db.query(Site).filter(Site.id == user.site_id).first()
    if site is not None and not site.is_online:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Site is offline")
    # SCO-99: force-change gate. Lock the user out of every route except the
    # ones they need to actually change their password. Detail string is a
    # stable machine code the frontend can branch on.
    if user.must_change_password:
        path = request.url.path
        if not any(path.endswith(suffix) for suffix in _FORCE_CHANGE_ALLOWED_SUFFIXES):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "password_change_required"
            )
    return user


def require_role(*roles: str):
    """Dependency factory for role-based gates."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Requires one of: {', '.join(roles)}"
            )
        return user

    return _checker

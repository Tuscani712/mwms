"""FastAPI dependencies: DB session + current authenticated user with per-site enforcement."""

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from wms.core.security import decode_token
from wms.db.session import get_db
from wms.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_session() -> Generator[Session, None, None]:
    yield from get_db()


def get_current_user(
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

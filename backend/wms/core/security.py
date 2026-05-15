"""Password hashing + JWT issuance/decoding."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from wms.core.config import get_settings

BCRYPT_MAX_BYTES = 72


def _to_bytes(value: str) -> bytes:
    """bcrypt only accepts up to 72 bytes.

    Historical behaviour: silent truncation. As of SCO-42 / SECURITY_AUDIT.md M-1
    the API layer rejects >72-byte inputs upstream via `assert_password_bcrypt_safe`,
    so anything reaching here is already safe. Truncation is kept as belt-and-
    suspenders against direct service-layer callers.
    """
    return value.encode("utf-8")[:BCRYPT_MAX_BYTES]


def assert_password_bcrypt_safe(password: str) -> None:
    """Raise ValueError if `password` would be silently truncated by bcrypt.

    Pydantic schemas should call this from a field_validator so the user sees a
    clear 422 instead of a successful login that only validates the first 72 bytes.
    """
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password must not exceed {BCRYPT_MAX_BYTES} bytes when UTF-8 encoded "
            "(bcrypt limit). Use a shorter passphrase."
        )


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    *, subject: str, site_id: str, role: str, extra: dict[str, Any] | None = None
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "site_id": site_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e

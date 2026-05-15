"""TOTP MFA: stdlib-only RFC 6238 implementation + bcrypt-hashed backup codes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy.orm import Session

from wms.core.security import hash_password, verify_password
from wms.models import User, UserMFA

TOTP_PERIOD = 30
TOTP_DIGITS = 6
BACKUP_CODE_COUNT = 8
SECRET_BYTES = 20  # 160-bit secret (TOTP standard)


def _generate_secret() -> str:
    """Random base32 secret (no padding) — safe for otpauth:// URIs."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _b32_decode_pad(secret: str) -> bytes:
    pad = (-len(secret)) % 8
    return base64.b32decode(secret + ("=" * pad), casefold=True)


def _hotp(secret: str, counter: int) -> str:
    key = _b32_decode_pad(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**TOTP_DIGITS)
    return str(code).zfill(TOTP_DIGITS)


def totp_now(secret: str, *, at: float | None = None) -> str:
    counter = int((at if at is not None else time.time()) // TOTP_PERIOD)
    return _hotp(secret, counter)


def verify_totp(secret: str, code: str, *, drift: int = 1) -> bool:
    """Verify code within ±drift × 30s windows (handles clock skew)."""
    if not code or not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    counter = int(time.time() // TOTP_PERIOD)
    for offset in range(-drift, drift + 1):
        if hmac.compare_digest(_hotp(secret, counter + offset), code):
            return True
    return False


def otpauth_uri(secret: str, *, account: str, issuer: str = "WMS") -> str:
    """Build the otpauth:// URI for QR-code rendering by the client."""
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )


def _new_backup_codes(n: int = BACKUP_CODE_COUNT) -> list[str]:
    """Plaintext one-time codes formatted as `xxxx-xxxx` (10 chars, 50 bits entropy)."""
    out = []
    for _ in range(n):
        raw = secrets.token_hex(4)  # 8 hex chars
        out.append(f"{raw[:4]}-{raw[4:]}")
    return out


def begin_enrollment(db: Session, user: User) -> tuple[UserMFA, list[str], str]:
    """Create or reset a *pending* MFA row. Returns (row, plaintext_codes, otpauth_uri)."""
    row = db.query(UserMFA).filter(UserMFA.user_id == user.id).one_or_none()
    secret = _generate_secret()
    codes = _new_backup_codes()
    hashed = [hash_password(c) for c in codes]
    if row is None:
        row = UserMFA(user_id=user.id, secret=secret, enabled=False,
                      backup_codes_json=json.dumps(hashed))
        db.add(row)
    else:
        row.secret = secret
        row.enabled = False
        row.verified_at = None
        row.backup_codes_json = json.dumps(hashed)
    db.commit()
    db.refresh(row)
    return row, codes, otpauth_uri(secret, account=user.employee_code)


def confirm_enrollment(db: Session, user: User, code: str) -> UserMFA:
    """Activate MFA after the user proves possession of the authenticator."""
    row = db.query(UserMFA).filter(UserMFA.user_id == user.id).one_or_none()
    if row is None:
        raise ValueError("Start enrollment first")
    if not verify_totp(row.secret, code):
        raise ValueError("Invalid code")
    row.enabled = True
    row.verified_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def verify_user_code(db: Session, user: User, code: str) -> bool:
    """Accept either a current TOTP or a one-time backup code. Consumes the backup code if used."""
    row = db.query(UserMFA).filter(UserMFA.user_id == user.id, UserMFA.enabled.is_(True)).one_or_none()
    if row is None:
        return False
    if verify_totp(row.secret, code):
        row.last_used_at = datetime.now(UTC)
        db.commit()
        return True
    # Try backup codes
    codes_list = json.loads(row.backup_codes_json or "[]")
    for idx, hashed in enumerate(codes_list):
        if verify_password(code, hashed):
            codes_list.pop(idx)
            row.backup_codes_json = json.dumps(codes_list)
            row.last_used_at = datetime.now(UTC)
            db.commit()
            return True
    return False


def disable_mfa(db: Session, user_id: int) -> None:
    """Hard reset: removes the row so the user must re-enroll."""
    row = db.query(UserMFA).filter(UserMFA.user_id == user_id).one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()


def is_enrolled(db: Session, user_id: int) -> bool:
    row = db.query(UserMFA).filter(UserMFA.user_id == user_id, UserMFA.enabled.is_(True)).one_or_none()
    return row is not None

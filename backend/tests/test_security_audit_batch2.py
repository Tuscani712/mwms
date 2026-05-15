"""Regression tests for SCO-42/43 (M-1, M-5). L-2 is config-only and verified by CI."""

import pytest
from pydantic import ValidationError

from wms.api.v1.admin_users import UserCreate
from wms.core.security import (
    BCRYPT_MAX_BYTES,
    assert_password_bcrypt_safe,
)
from wms.schemas.profile import PasswordUpdate

# ── M-1: bcrypt byte-length validation ─────────────────────────────────


def test_assert_password_bcrypt_safe_accepts_72_bytes_ascii():
    assert_password_bcrypt_safe("a" * BCRYPT_MAX_BYTES)  # exactly at boundary, must pass


def test_assert_password_bcrypt_safe_rejects_73_bytes_ascii():
    with pytest.raises(ValueError, match="72 bytes"):
        assert_password_bcrypt_safe("a" * (BCRYPT_MAX_BYTES + 1))


def test_assert_password_bcrypt_safe_rejects_emoji_above_limit():
    """Emoji are 4 bytes each in UTF-8 — a 19-char emoji string is 76 bytes."""
    emoji_string = "🙂" * 19  # 4 bytes × 19 = 76 bytes > 72
    with pytest.raises(ValueError, match="72 bytes"):
        assert_password_bcrypt_safe(emoji_string)


def test_password_update_schema_rejects_oversized_password():
    with pytest.raises(ValidationError):
        PasswordUpdate(current_password="old", new_password="a" * 73)


def test_user_create_schema_rejects_oversized_password():
    """The admin-create endpoint also goes through the validator."""
    with pytest.raises(ValidationError):
        UserCreate(
            employee_code="X1",
            email="x@y.z",
            full_name="X",
            permission_level=1,
            password="a" * 80,
        )


def test_password_change_endpoint_returns_422_on_long_password(client, auth_headers):
    """End-to-end: an oversized password produces a 422 before reaching bcrypt."""
    r = client.put(
        "/api/v1/profile/password",
        json={"current_password": "password123", "new_password": "a" * 80},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ── M-5: global JSON body size cap ─────────────────────────────────────


def test_oversized_json_body_returns_413(client, auth_headers, monkeypatch):
    """Any JSON endpoint must reject bodies over the cap with 413."""
    from wms.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_json_body_bytes", 256)  # tight cap for the test

    # Build a payload whose body is comfortably over the cap
    big_payload = {"new_password": "x" * 300, "current_password": "password123"}
    r = client.put("/api/v1/profile/password", json=big_payload, headers=auth_headers)
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"].lower()


def test_normal_json_body_is_unaffected(client, auth_headers):
    """Sanity-check: typical payloads pass the middleware untouched."""
    # We expect 400 from the password validator (wrong current pw), NOT 413
    r = client.put(
        "/api/v1/profile/password",
        json={"current_password": "wrong-pw", "new_password": "newpass1!"},
        headers=auth_headers,
    )
    assert r.status_code in (400, 200)


def test_upload_endpoint_bypasses_json_cap(client, auth_headers, monkeypatch):
    """The avatar upload uses its own cap; the JSON middleware must not pre-empt it."""
    import io

    from PIL import Image

    from wms.core.config import get_settings

    settings = get_settings()
    # Set JSON cap absurdly low to prove the upload path bypasses it.
    monkeypatch.setattr(settings, "max_json_body_bytes", 16)

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 100, 50)).save(buf, format="PNG")
    png_bytes = buf.getvalue()
    assert len(png_bytes) > 16  # confirm the PNG is bigger than the bogus JSON cap

    r = client.post(
        "/api/v1/profile/picture/upload",
        files={"file": ("a.png", png_bytes, "image/png")},
        headers=auth_headers,
    )
    # Must NOT be 413 — the upload route is exempt
    assert r.status_code == 200

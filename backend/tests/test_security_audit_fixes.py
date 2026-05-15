"""Regression tests for the four pre-staged fixes from SECURITY_AUDIT.md."""

import pytest

from wms.core.config import DEFAULT_SECRET_SENTINEL, InsecureConfigError, Settings
from wms.core.security import hash_password
from wms.models import User
from wms.services import mfa as mfa_svc

# ── C-1: production refuses to boot with the default secret ─────────────


def test_assert_secure_for_env_rejects_default_in_production():
    s = Settings(env="production", secret_key=DEFAULT_SECRET_SENTINEL)
    with pytest.raises(InsecureConfigError):
        s.assert_secure_for_env()


def test_assert_secure_for_env_allows_default_in_development():
    s = Settings(env="development", secret_key=DEFAULT_SECRET_SENTINEL)
    s.assert_secure_for_env()  # must not raise


def test_assert_secure_for_env_allows_explicit_key_anywhere():
    s = Settings(env="production", secret_key="a-real-long-random-string-32-chars-min")
    s.assert_secure_for_env()  # must not raise


# ── H-2: MFA disable requires current password ─────────────────────────


def _enroll(client, auth_headers):
    setup = client.post("/api/v1/profile/mfa/setup", headers=auth_headers).json()
    code = mfa_svc.totp_now(setup["secret"])
    client.post("/api/v1/profile/mfa/verify", json={"code": code}, headers=auth_headers)
    return setup


def test_mfa_disable_rejects_wrong_password(client, auth_headers):
    _enroll(client, auth_headers)
    r = client.post(
        "/api/v1/profile/mfa/disable",
        json={"current_password": "definitely-not-it"},
        headers=auth_headers,
    )
    assert r.status_code == 401
    status = client.get("/api/v1/profile/mfa/status", headers=auth_headers).json()
    assert status["enrolled"] is True


def test_mfa_disable_accepts_correct_password(client, auth_headers):
    _enroll(client, auth_headers)
    r = client.post(
        "/api/v1/profile/mfa/disable",
        json={"current_password": "password123"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    status = client.get("/api/v1/profile/mfa/status", headers=auth_headers).json()
    assert status["enrolled"] is False


# ── M-4: MFA challenge error is generic ─────────────────────────────────


def test_mfa_challenge_error_does_not_leak_jose_details(client):
    r = client.post(
        "/api/v1/auth/mfa/verify",
        json={"challenge_token": "this.is.not.a.real.jwt", "code": "123456"},
    )
    assert r.status_code == 401
    detail = r.json()["detail"]
    # Generic phrasing only — no JWTError / JOSE / signature / expiry strings
    assert detail == "Invalid or expired challenge token"


# ── I-1: deactivated user's existing JWT stops working ──────────────────


def test_existing_token_invalidated_when_user_deactivated(client, seeded_db):
    # Seed an admin to do the deactivation
    admin = User(
        site_id="WHS-001",
        employee_code="WHS-001-ADMIN",
        email="admin@wms.local",
        full_name="Admin",
        role="admin",
        permission_level=4,
        hashed_password=hash_password("password123"),
    )
    seeded_db.add(admin)
    seeded_db.commit()

    # Operator logs in and gets a token
    op_login = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-001"},
    ).json()
    op_headers = {"Authorization": f"Bearer {op_login['access_token']}"}
    # Sanity: token works
    assert client.get("/api/v1/auth/me", headers=op_headers).status_code == 200

    # Admin deactivates the operator
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-ADMIN", "password": "password123", "site_id": "WHS-001"},
    ).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}
    target_id = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one().id
    assert client.delete(f"/api/v1/admin/users/{target_id}", headers=admin_headers).status_code == 200

    # Operator's still-unexpired token must now be rejected
    r = client.get("/api/v1/auth/me", headers=op_headers)
    assert r.status_code == 401

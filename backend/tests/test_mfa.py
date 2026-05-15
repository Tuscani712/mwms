"""MFA enrollment + login challenge + admin reset."""

from wms.core.security import hash_password
from wms.models import PasswordPolicy, User
from wms.services import mfa as mfa_svc


def _login(client, employee_code="WHS-001-001", password="password123", site_id="WHS-001"):
    return client.post(
        "/api/v1/auth/login",
        json={"employee_code": employee_code, "password": password, "site_id": site_id},
    )


def test_setup_returns_uri_and_backup_codes(client, auth_headers):
    r = client.post("/api/v1/profile/mfa/setup", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/WMS%3AWHS-001-001")
    assert "secret=" in body["otpauth_uri"]
    assert "issuer=WMS" in body["otpauth_uri"]
    assert len(body["backup_codes"]) == 8
    assert all(len(c) == 9 and "-" in c for c in body["backup_codes"])  # xxxx-xxxx


def test_verify_activates_mfa(client, auth_headers, seeded_db):
    setup = client.post("/api/v1/profile/mfa/setup", headers=auth_headers).json()
    code = mfa_svc.totp_now(setup["secret"])

    r = client.post("/api/v1/profile/mfa/verify", json={"code": code}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enrolled"] is True

    status = client.get("/api/v1/profile/mfa/status", headers=auth_headers).json()
    assert status["enrolled"] is True


def test_verify_rejects_bad_code(client, auth_headers):
    client.post("/api/v1/profile/mfa/setup", headers=auth_headers)
    r = client.post("/api/v1/profile/mfa/verify", json={"code": "000000"}, headers=auth_headers)
    assert r.status_code == 400


def test_login_returns_challenge_when_mfa_required_and_enrolled(client, seeded_db, auth_headers):
    # Enroll the user
    setup = client.post("/api/v1/profile/mfa/setup", headers=auth_headers).json()
    code = mfa_svc.totp_now(setup["secret"])
    client.post("/api/v1/profile/mfa/verify", json={"code": code}, headers=auth_headers)

    # Require MFA at role scope
    seeded_db.add(PasswordPolicy(scope_type="role", scope_value="operator", require_mfa=True))
    seeded_db.commit()

    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True
    assert body["mfa_enrolled"] is True
    assert body["access_token"] is None
    assert body["mfa_challenge_token"]


def test_mfa_challenge_token_exchanges_for_real_token(client, seeded_db, auth_headers):
    setup = client.post("/api/v1/profile/mfa/setup", headers=auth_headers).json()
    enroll_code = mfa_svc.totp_now(setup["secret"])
    client.post("/api/v1/profile/mfa/verify", json={"code": enroll_code}, headers=auth_headers)

    seeded_db.add(PasswordPolicy(scope_type="role", scope_value="operator", require_mfa=True))
    seeded_db.commit()

    challenge = _login(client).json()["mfa_challenge_token"]
    code = mfa_svc.totp_now(setup["secret"])

    r = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": challenge, "code": code}
    )
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["mfa_required"] is False


def test_backup_code_works_and_is_consumed(client, seeded_db, auth_headers):
    setup = client.post("/api/v1/profile/mfa/setup", headers=auth_headers).json()
    backup = setup["backup_codes"][0]
    enroll_code = mfa_svc.totp_now(setup["secret"])
    client.post("/api/v1/profile/mfa/verify", json={"code": enroll_code}, headers=auth_headers)

    seeded_db.add(PasswordPolicy(scope_type="role", scope_value="operator", require_mfa=True))
    seeded_db.commit()

    challenge = _login(client).json()["mfa_challenge_token"]
    r = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": challenge, "code": backup}
    )
    assert r.status_code == 200

    # Same backup code must NOT work a second time
    challenge2 = _login(client).json()["mfa_challenge_token"]
    r2 = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": challenge2, "code": backup}
    )
    assert r2.status_code == 401


def test_login_without_mfa_requirement_returns_token_directly(client):
    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["mfa_required"] is False


def test_mfa_required_but_not_enrolled_returns_token_with_enroll_flag(client, seeded_db):
    seeded_db.add(PasswordPolicy(scope_type="role", scope_value="operator", require_mfa=True))
    seeded_db.commit()

    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    # Token issued so user can hit /profile/mfa/setup, but flagged as not yet enrolled.
    assert body["access_token"]
    assert body["mfa_required"] is False
    assert body["mfa_enrolled"] is False


def test_admin_can_reset_user_mfa(client, seeded_db, auth_headers):
    # Add a level-4 admin user
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

    # Operator enrolls
    setup = client.post("/api/v1/profile/mfa/setup", headers=auth_headers).json()
    enroll_code = mfa_svc.totp_now(setup["secret"])
    client.post("/api/v1/profile/mfa/verify", json={"code": enroll_code}, headers=auth_headers)

    # Admin logs in and resets the operator
    admin_token = _login(client, employee_code="WHS-001-ADMIN").json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    op = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = client.post(
        "/api/v1/admin/policy/mfa-reset",
        json={"user_id": op.id},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    status = client.get("/api/v1/profile/mfa/status", headers=auth_headers).json()
    assert status["enrolled"] is False


def test_operator_cannot_reset_mfa(client, auth_headers, seeded_db):
    op_id = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one().id
    r = client.post(
        "/api/v1/admin/policy/mfa-reset", json={"user_id": op_id}, headers=auth_headers
    )
    assert r.status_code == 403

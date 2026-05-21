"""SCO-99: first-login forced password change.

Admin-created users land with must_change_password=True. They can log in,
fetch /auth/me, and rotate via PUT /profile/password — and nothing else.
A successful rotation clears the flag and unlocks the rest of the app.
"""

from __future__ import annotations

from wms.core.security import hash_password
from wms.models import User


def _seed(db, *, code, level, must=False, site="WHS-001"):
    u = User(
        site_id=site,
        employee_code=code,
        email=f"{code.lower()}@wms.local",
        full_name=f"User {code}",
        role="admin" if level == 5 else "operator",
        permission_level=level,
        hashed_password=hash_password("password123"),
        must_change_password=must,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, code, pw="password123"):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": pw, "site_id": "WHS-001"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


# ── Admin-created user gets must_change_password=True ───────────────────


def test_admin_creates_user_with_must_change_password_set(client, seeded_db):
    admin = _seed(seeded_db, code="ADMIN-L5", level=5)
    token = _login(client, admin.employee_code)["access_token"]
    r = client.post(
        "/api/v1/admin/users",
        headers=_h(token),
        json={
            "employee_code": "NEW-USER",
            "email": "new@wms.local",
            "full_name": "New User",
            "permission_level": 1,
            "password": "TempPass1!",
        },
    )
    assert r.status_code == 201
    new_user = (
        seeded_db.query(User).filter(User.employee_code == "NEW-USER").first()
    )
    assert new_user.must_change_password is True


# ── Login surfaces the flag in TokenResponse ────────────────────────────


def test_login_surfaces_must_change_password_in_response(client, seeded_db):
    _seed(seeded_db, code="FORCED-USER", level=1, must=True)
    body = _login(client, "FORCED-USER")
    assert body["must_change_password"] is True
    # Token is still issued so the user can hit the password endpoint.
    assert body["access_token"]


def test_login_normal_user_returns_must_change_false(client, seeded_db):
    _seed(seeded_db, code="NORMAL-USER", level=1, must=False)
    body = _login(client, "NORMAL-USER")
    assert body["must_change_password"] is False


# ── Route gate: locked-out routes 403 with password_change_required ─────


def test_locked_out_of_admin_list_until_rotated(client, seeded_db):
    _seed(seeded_db, code="LOCKED-L5", level=5, must=True)
    token = _login(client, "LOCKED-L5")["access_token"]
    r = client.get("/api/v1/admin/users", headers=_h(token))
    assert r.status_code == 403
    assert r.json()["detail"] == "password_change_required"


def test_can_still_hit_auth_me_during_force_change(client, seeded_db):
    _seed(seeded_db, code="FORCED-ME", level=1, must=True)
    token = _login(client, "FORCED-ME")["access_token"]
    r = client.get("/api/v1/auth/me", headers=_h(token))
    assert r.status_code == 200
    assert r.json()["employee_code"] == "FORCED-ME"


# ── Successful rotation clears the flag ─────────────────────────────────


def test_password_change_clears_must_change_flag(client, seeded_db):
    _seed(seeded_db, code="ROTATING", level=1, must=True)
    token = _login(client, "ROTATING")["access_token"]
    r = client.put(
        "/api/v1/profile/password",
        headers=_h(token),
        json={"current_password": "password123", "new_password": "NewPass1!"},
    )
    assert r.status_code == 200, r.text

    # Flag cleared.
    user = (
        seeded_db.query(User).filter(User.employee_code == "ROTATING").first()
    )
    assert user.must_change_password is False

    # And the gate is now off — old token still works on /admin (assuming
    # role permits; this user is L1 so they'll still 403 for permission,
    # but NOT with password_change_required). We verify via /auth/me only.
    r2 = client.get("/api/v1/auth/me", headers=_h(token))
    assert r2.status_code == 200


def test_password_change_to_same_password_rejected(client, seeded_db):
    _seed(seeded_db, code="TRYING-SAME", level=1, must=True)
    token = _login(client, "TRYING-SAME")["access_token"]
    r = client.put(
        "/api/v1/profile/password",
        headers=_h(token),
        json={"current_password": "password123", "new_password": "password123"},
    )
    assert r.status_code == 400
    assert "differ" in r.json()["detail"].lower()


# ── Re-login after rotation: flag stays false ───────────────────────────


def test_relogin_after_rotation_has_must_change_false(client, seeded_db):
    _seed(seeded_db, code="REROLLED", level=1, must=True)
    tok1 = _login(client, "REROLLED")["access_token"]
    client.put(
        "/api/v1/profile/password",
        headers=_h(tok1),
        json={"current_password": "password123", "new_password": "FreshPass1!"},
    )
    # Log in fresh with the new password.
    body = _login(client, "REROLLED", pw="FreshPass1!")
    assert body["must_change_password"] is False

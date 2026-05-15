"""Profile flow tests — read, edit, approval, field-visibility precedence."""

from wms.core.security import hash_password
from wms.models import User, UserProfileField


def test_get_profile_returns_identity_and_policy(client, auth_headers):
    r = client.get("/api/v1/profile", headers=auth_headers)
    assert r.status_code == 200
    p = r.json()
    assert p["employee_code"] == "WHS-001-001"
    assert p["site_id"] == "WHS-001"
    assert "field_policy" in p
    assert "email" in p["field_policy"]
    assert p["field_policy"]["email"]["visible"] is True


def test_email_update_when_editable(client, auth_headers):
    r = client.put("/api/v1/profile/email", json={"email": "new@example.com"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "new@example.com"


def test_email_blocked_by_role_policy(client, seeded_db, auth_headers):
    seeded_db.add(UserProfileField(scope_type="role", scope_value="operator",
                                   field_name="email", visible=True, editable=False))
    seeded_db.commit()
    r = client.put("/api/v1/profile/email", json={"email": "blocked@example.com"}, headers=auth_headers)
    assert r.status_code == 403


def test_password_update_validates_current(client, auth_headers):
    r = client.put("/api/v1/profile/password",
                   json={"current_password": "wrong", "new_password": "newpass"},
                   headers=auth_headers)
    assert r.status_code == 400

    r = client.put("/api/v1/profile/password",
                   json={"current_password": "password123", "new_password": "newpass"},
                   headers=auth_headers)
    assert r.status_code == 200


def test_display_name_creates_pending_request(client, auth_headers):
    r = client.post("/api/v1/profile/display-name-request",
                    json={"requested_value": "TheBoss"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["field_name"] == "display_name"

    # And it shows up in /profile.pending_requests
    r = client.get("/api/v1/profile", headers=auth_headers)
    assert "display_name" in r.json()["pending_requests"]


def test_user_scope_overrides_role_scope(client, seeded_db, auth_headers):
    # Role says editable=False; user-specific row says editable=True
    seeded_db.add(UserProfileField(scope_type="role", scope_value="operator",
                                   field_name="email", visible=True, editable=False))
    seeded_db.add(UserProfileField(scope_type="user", scope_value="WHS-001-001",
                                   field_name="email", visible=True, editable=True))
    seeded_db.commit()
    r = client.put("/api/v1/profile/email", json={"email": "override@example.com"}, headers=auth_headers)
    assert r.status_code == 200


def test_admin_decides_request_and_applies_change(client, seeded_db, auth_headers):
    # Operator submits a display_name request
    client.post("/api/v1/profile/display-name-request",
                json={"requested_value": "Maverick"}, headers=auth_headers)

    # Add an L4 supervisor at the same site
    seeded_db.add(User(
        site_id="WHS-001", employee_code="WHS-001-MGR",
        email="mgr@x.io", full_name="Site Manager",
        role="manager", permission_level=4,
        hashed_password=hash_password("mgr12345"),
    ))
    seeded_db.commit()

    mgr_login = client.post("/api/v1/auth/login",
                            json={"employee_code": "WHS-001-MGR",
                                  "password": "mgr12345", "site_id": "WHS-001"})
    mgr_token = mgr_login.json()["access_token"]
    mgr_headers = {"Authorization": f"Bearer {mgr_token}"}

    pending = client.get("/api/v1/admin/profile/requests", headers=mgr_headers).json()
    assert len(pending) >= 1
    req_id = pending[0]["id"]

    r = client.post(f"/api/v1/admin/profile/requests/{req_id}/decide",
                    json={"approve": True, "notes": "ok"}, headers=mgr_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Operator's profile should now have the new display_name
    me = client.get("/api/v1/profile", headers=auth_headers).json()
    assert me["display_name"] == "Maverick"

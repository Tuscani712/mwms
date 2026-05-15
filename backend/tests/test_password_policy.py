"""Password policy enforcement + admin upsert."""

from wms.models import PasswordPolicy


def test_policy_endpoint_returns_defaults(client, auth_headers):
    r = client.get("/api/v1/profile/password-policy", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["min_length"] >= 4
    assert body["_source"] in ("default", "global:default", "role:operator")


def test_password_change_rejected_when_too_short(client, seeded_db, auth_headers):
    seeded_db.add(PasswordPolicy(scope_type="role", scope_value="operator",
                                 min_length=8, require_digit=True, require_special=True))
    seeded_db.commit()

    r = client.put("/api/v1/profile/password",
                   json={"current_password": "password123", "new_password": "short"},
                   headers=auth_headers)
    assert r.status_code == 400
    assert "at least 8" in r.json()["detail"].lower() or "8 characters" in r.json()["detail"]


def test_password_change_accepted_when_complies(client, seeded_db, auth_headers):
    seeded_db.add(PasswordPolicy(scope_type="role", scope_value="operator",
                                 min_length=8, require_digit=True, require_special=True))
    seeded_db.commit()

    r = client.put("/api/v1/profile/password",
                   json={"current_password": "password123", "new_password": "ValidPass1!"},
                   headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_admin_can_upsert_policy(client, seeded_db, auth_headers):
    # Operator (level 1) → 403
    r = client.put("/api/v1/admin/policy/password",
                   json={"scope_type": "role", "scope_value": "operator", "min_length": 12},
                   headers=auth_headers)
    assert r.status_code == 403

"""Sites router — list + admin CRUD (SCO-54).

Covers:
- List is open to authed callers (login picker)
- Non-master, non-Lvl-5 callers are 403'd on every write
- Master Lvl 5 can create / update / toggle / delete
- Master site itself can't be deleted or taken offline
- Sites with users / departments refuse delete (409) so we don't orphan FKs
- Toggle cooldown returns 429 within the window
- ID format validation (uppercase, alphanumeric + dash)
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import Session

from wms.api.v1.sites import _last_toggle_at
from wms.core.security import hash_password
from wms.models import Site, User
from wms.models.orgmeta import Department

# ── Helpers ─────────────────────────────────────────────────────────────


def _mcs_admin(db: Session, *, level: int = 5) -> User:
    if db.get(Site, "MCS") is None:
        db.add(Site(id="MCS", name="Master", city="HQ", is_master=True, is_online=True))
        db.commit()
    u = User(
        site_id="MCS",
        employee_code="MCS-ADMIN",
        email="mcs-admin@wms.local",
        full_name="Master Admin",
        role="admin",
        permission_level=level,
        hashed_password=hash_password("password123"),
    )
    db.add(u)
    db.commit()
    return u


def _login(client, code: str, site: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": "password123", "site_id": site},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset_toggle_cooldown():
    """Clear the per-process cooldown map between tests — otherwise the second
    test in the same process would inherit the prior toggle timestamps."""
    _last_toggle_at.clear()
    yield
    _last_toggle_at.clear()


# ── List ────────────────────────────────────────────────────────────────


def test_list_sites_open_to_any_caller(client):
    """Login picker hits this unauthenticated; must not require a token."""
    r = client.get("/api/v1/sites")
    assert r.status_code == 200
    assert any(s["id"] == "WHS-001" for s in r.json())


# ── Authorization gates ─────────────────────────────────────────────────


def test_operator_cannot_create_site(client, auth_headers):
    r = client.post(
        "/api/v1/sites",
        headers=auth_headers,
        json={"id": "WHS-NEW", "name": "Nope", "city": "Nowhere"},
    )
    assert r.status_code == 403


def test_non_master_lvl5_cannot_create_site(client, seeded_db):
    # WHS-001 site already exists from seed; promote its user to lvl 5
    u = seeded_db.query(User).filter_by(employee_code="WHS-001-001").one()
    u.permission_level = 5
    seeded_db.commit()
    token = _login(client, "WHS-001-001", "WHS-001")
    r = client.post(
        "/api/v1/sites",
        headers=_h(token),
        json={"id": "WHS-NEW", "name": "Nope", "city": "Nowhere"},
    )
    assert r.status_code == 403
    assert "master site" in r.json()["detail"].lower()


# ── CRUD happy path (master Lvl 5) ──────────────────────────────────────


def test_master_admin_full_crud(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")

    # Create
    r = client.post(
        "/api/v1/sites",
        headers=_h(token),
        json={"id": "WHS-TEST", "name": "Smoke", "city": "Testville"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "WHS-TEST"

    # Get detail includes counts
    r = client.get("/api/v1/sites/WHS-TEST", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["user_count"] == 0
    assert body["department_count"] == 0
    assert body["timezone"] == "America/Chicago"

    # Update
    r = client.put(
        "/api/v1/sites/WHS-TEST", headers=_h(token), json={"city": "Renamed"}
    )
    assert r.status_code == 200
    assert r.json()["city"] == "Renamed"

    # Toggle online
    r = client.post("/api/v1/sites/WHS-TEST/toggle-online", headers=_h(token))
    assert r.status_code == 200
    assert r.json()["is_online"] is False

    # Cooldown blocks immediate re-toggle
    r = client.post("/api/v1/sites/WHS-TEST/toggle-online", headers=_h(token))
    assert r.status_code == 429

    # Delete
    r = client.delete("/api/v1/sites/WHS-TEST", headers=_h(token))
    assert r.status_code == 200

    # Gone
    r = client.get("/api/v1/sites/WHS-TEST", headers=_h(token))
    assert r.status_code == 404


# ── Safety rails ────────────────────────────────────────────────────────


def test_cannot_delete_master(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    r = client.delete("/api/v1/sites/MCS", headers=_h(token))
    assert r.status_code == 400


def test_cannot_take_master_offline(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    r = client.post("/api/v1/sites/MCS/toggle-online", headers=_h(token))
    assert r.status_code == 400


def test_delete_refuses_when_users_reference_site(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    # WHS-001 already has users from seeded_db fixture
    r = client.delete("/api/v1/sites/WHS-001", headers=_h(token))
    assert r.status_code == 409
    assert "user(s)" in r.json()["detail"]


def test_delete_refuses_when_only_departments_reference_site(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    # Make a site with no users but a department
    client.post(
        "/api/v1/sites",
        headers=_h(token),
        json={"id": "WHS-ORPHAN", "name": "Has Dept", "city": "X"},
    )
    seeded_db.add(Department(site_id="WHS-ORPHAN", name="Receiving"))
    seeded_db.commit()
    r = client.delete("/api/v1/sites/WHS-ORPHAN", headers=_h(token))
    assert r.status_code == 409
    assert "department(s)" in r.json()["detail"]


def test_id_format_validation(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    for bad in ("1WHS", "whs lowercase ok via upper but space bad", "x"):
        r = client.post(
            "/api/v1/sites",
            headers=_h(token),
            json={"id": bad, "name": "X", "city": "Y"},
        )
        assert r.status_code == 400 or r.status_code == 422


def test_duplicate_id_returns_409(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    payload = {"id": "WHS-DUPE", "name": "First", "city": "City"}
    assert client.post("/api/v1/sites", headers=_h(token), json=payload).status_code == 201
    r = client.post("/api/v1/sites", headers=_h(token), json=payload)
    assert r.status_code == 409


def test_only_one_master_allowed(client, seeded_db):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    r = client.post(
        "/api/v1/sites",
        headers=_h(token),
        json={"id": "WHS-MASTER2", "name": "Second master", "city": "X", "is_master": True},
    )
    assert r.status_code == 409


def test_toggle_cooldown_releases_after_window(client, seeded_db, monkeypatch):
    _mcs_admin(seeded_db)
    token = _login(client, "MCS-ADMIN", "MCS")
    client.post(
        "/api/v1/sites",
        headers=_h(token),
        json={"id": "WHS-TG", "name": "Toggle test", "city": "X"},
    )
    # First toggle ok
    assert client.post("/api/v1/sites/WHS-TG/toggle-online", headers=_h(token)).status_code == 200
    # Within window: 429
    assert client.post("/api/v1/sites/WHS-TG/toggle-online", headers=_h(token)).status_code == 429
    # Fast-forward the monotonic clock past the cooldown by manipulating the
    # last-toggle map directly (faster than waiting 60s in a test).
    _last_toggle_at["WHS-TG"] = time.monotonic() - 120
    assert client.post("/api/v1/sites/WHS-TG/toggle-online", headers=_h(token)).status_code == 200

"""Admin user CRUD + permission gates."""

import pytest

from wms.core.security import hash_password
from wms.models import Site, User

# ── Helpers ─────────────────────────────────────────────────────────────

def _seed_admin(db, *, site_id="WHS-001", code="WHS-001-ADMIN", level=4) -> User:
    u = User(
        site_id=site_id,
        employee_code=code,
        email=f"{code.lower()}@wms.local",
        full_name=f"Admin {code}",
        role="admin",
        permission_level=level,
        hashed_password=hash_password("password123"),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _seed_mcs(db) -> User:
    db.add(Site(id="MCS", name="Master", city="HQ", is_master=True, is_online=True))
    db.commit()
    return _seed_admin(db, site_id="MCS", code="MCS-ADMIN", level=4)


def _login(client, code, password="password123", site="WHS-001"):
    return client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": password, "site_id": site},
    ).json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Permission gates ────────────────────────────────────────────────────

def test_operator_cannot_access_admin_users(client, auth_headers):
    """Default seeded user is Level 1 — must be denied at every entry point."""
    assert client.get("/api/v1/admin/users", headers=auth_headers).status_code == 403
    assert client.post("/api/v1/admin/users", json={
        "employee_code": "XX", "email": "x@y.z", "full_name": "X", "password": "abcd",
    }, headers=auth_headers).status_code == 403


def test_level3_can_list_own_site_only(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    other_site = Site(id="WHS-002", name="HOU", city="Houston")
    seeded_db.add(other_site)
    seeded_db.commit()
    seeded_db.add(User(
        site_id="WHS-002", employee_code="WHS-002-001", email="o2@wms.local",
        full_name="Other", role="operator", permission_level=1,
        hashed_password=hash_password("password123"),
    ))
    seeded_db.commit()

    token = _login(client, "WHS-001-LEAD")
    r = client.get("/api/v1/admin/users", headers=_headers(token))
    assert r.status_code == 200
    codes = [u["employee_code"] for u in r.json()["items"]]
    assert "WHS-002-001" not in codes  # cross-site invisible
    assert "WHS-001-001" in codes


# ── Create ──────────────────────────────────────────────────────────────

def test_admin_creates_user(client, seeded_db):
    _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-099",
            "email": "new@wms.local",
            "full_name": "New Op",
            "role": "operator",
            "permission_level": 1,
            "password": "tempPass1!",
        },
        headers=_headers(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["employee_code"] == "WHS-001-099"
    assert body["site_id"] == "WHS-001"
    assert body["is_active"] is True


def test_cannot_create_user_at_or_above_own_level(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-100",
            "email": "p@wms.local",
            "full_name": "Peer",
            "permission_level": 3,
            "password": "pw1234",
        },
        headers=_headers(token),
    )
    assert r.status_code == 403


def test_duplicate_employee_code_rejected(client, seeded_db):
    _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    body = {
        "employee_code": "WHS-001-001",  # already taken by seeded operator
        "email": "dup@wms.local",
        "full_name": "Dup",
        "permission_level": 1,
        "password": "pw1234",
    }
    r = client.post("/api/v1/admin/users", json=body, headers=_headers(token))
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"].lower()


def test_cross_site_create_blocked_for_non_mcs(client, seeded_db):
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-002-099",
            "email": "x@wms.local",
            "full_name": "X",
            "permission_level": 1,
            "password": "pw1234",
            "site_id": "WHS-002",
        },
        headers=_headers(token),
    )
    assert r.status_code == 403


def test_mcs_admin_can_create_cross_site(client, seeded_db):
    _seed_mcs(seeded_db)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-002-001",
            "email": "ops@wms.local",
            "full_name": "Houston Op",
            "permission_level": 1,
            "password": "pw1234",
            "site_id": "WHS-002",
        },
        headers=_headers(token),
    )
    assert r.status_code == 201
    assert r.json()["site_id"] == "WHS-002"


# ── Update ──────────────────────────────────────────────────────────────

def test_update_user_fields(client, seeded_db):
    _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    target = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = client.put(
        f"/api/v1/admin/users/{target.id}",
        json={"department": "Receiving", "shift": "1st"},
        headers=_headers(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["department"] == "Receiving"
    assert body["shift"] == "1st"


def test_cannot_update_peer_or_superior(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD-A", level=3)
    other_lead = _seed_admin(seeded_db, code="WHS-001-LEAD-B", level=3)
    token = _login(client, "WHS-001-LEAD-A")
    r = client.put(
        f"/api/v1/admin/users/{other_lead.id}",
        json={"department": "Hijack"},
        headers=_headers(token),
    )
    assert r.status_code == 403


def test_promote_blocked_at_or_above_own_level(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    token = _login(client, "WHS-001-LEAD")
    target = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = client.put(
        f"/api/v1/admin/users/{target.id}",
        json={"permission_level": 3},
        headers=_headers(token),
    )
    assert r.status_code == 403


# ── Soft delete + reactivate ───────────────────────────────────────────

def test_soft_delete_sets_inactive(client, seeded_db):
    _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    target = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = client.delete(f"/api/v1/admin/users/{target.id}", headers=_headers(token))
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    listing = client.get("/api/v1/admin/users", headers=_headers(token)).json()
    codes = [u["employee_code"] for u in listing["items"]]
    assert "WHS-001-001" not in codes  # excluded by default

    listing_all = client.get(
        "/api/v1/admin/users?include_inactive=true", headers=_headers(token)
    ).json()
    codes_all = [u["employee_code"] for u in listing_all["items"]]
    assert "WHS-001-001" in codes_all


def test_cannot_delete_self(client, seeded_db):
    admin = _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    r = client.delete(f"/api/v1/admin/users/{admin.id}", headers=_headers(token))
    assert r.status_code == 403
    assert "yourself" in r.json()["detail"].lower()


def test_reactivate_restores_user(client, seeded_db):
    _seed_admin(seeded_db)
    token = _login(client, "WHS-001-ADMIN")
    target = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    client.delete(f"/api/v1/admin/users/{target.id}", headers=_headers(token))
    r = client.post(
        f"/api/v1/admin/users/{target.id}/reactivate", headers=_headers(token)
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True


# ── List filters + pagination ──────────────────────────────────────────

@pytest.fixture
def populated_site(seeded_db):
    """Seed extra operators for filter/pagination tests."""
    for i in range(2, 12):
        seeded_db.add(User(
            site_id="WHS-001",
            employee_code=f"WHS-001-{i:03d}",
            email=f"op{i}@wms.local",
            full_name=f"Operator {i}",
            role="operator" if i % 2 == 0 else "lead",
            permission_level=1 if i % 2 == 0 else 2,
            hashed_password=hash_password("password123"),
        ))
    seeded_db.commit()
    return seeded_db


def test_list_filters_by_role(client, populated_site):
    _seed_admin(populated_site)
    token = _login(client, "WHS-001-ADMIN")
    r = client.get("/api/v1/admin/users?role=lead", headers=_headers(token))
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and all(u["role"] == "lead" for u in items)


def test_list_search_matches_code_or_name(client, populated_site):
    _seed_admin(populated_site)
    token = _login(client, "WHS-001-ADMIN")
    r = client.get("/api/v1/admin/users?q=Operator+5", headers=_headers(token))
    items = r.json()["items"]
    assert any("Operator 5" in u["full_name"] for u in items)


def test_list_pagination(client, populated_site):
    _seed_admin(populated_site)
    token = _login(client, "WHS-001-ADMIN")
    page1 = client.get("/api/v1/admin/users?limit=3&offset=0", headers=_headers(token)).json()
    page2 = client.get("/api/v1/admin/users?limit=3&offset=3", headers=_headers(token)).json()
    assert len(page1["items"]) == 3
    assert len(page2["items"]) == 3
    ids1 = {u["id"] for u in page1["items"]}
    ids2 = {u["id"] for u in page2["items"]}
    assert ids1.isdisjoint(ids2)
    assert page1["total"] == page2["total"] >= 11

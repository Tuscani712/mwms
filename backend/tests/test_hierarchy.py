"""Org hierarchy + supervisor invariants + assignment endpoints."""

import pytest

from wms.core.security import hash_password
from wms.models import Site, User


def _add_user(db, *, code, level, site_id="WHS-001", supervisor_id=None):
    u = User(
        site_id=site_id,
        employee_code=code,
        email=f"{code.lower()}@wms.local",
        full_name=f"User {code}",
        role="staff",
        permission_level=level,
        hashed_password=hash_password("password123"),
        supervisor_id=supervisor_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, code, site="WHS-001"):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": "password123", "site_id": site},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── tier_labels ─────────────────────────────────────────────────────────


def test_tier_labels_endpoint(client, auth_headers):
    r = client.get("/api/v1/admin/users/tiers/labels", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    # JSON keys come back as strings
    assert body["5"] == "Corporate"
    assert body["1"] == "Operator"


# ── Supervisor assignment ──────────────────────────────────────────────


@pytest.fixture
def admin_and_targets(seeded_db):
    """Admin (lvl 4) + a manager (lvl 4 cross-site separated below if needed) + ops."""
    admin = _add_user(seeded_db, code="WHS-001-ADMIN", level=4)
    mgr = _add_user(seeded_db, code="WHS-001-MGR", level=3)
    op = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    return admin, mgr, op


def test_assign_supervisor_happy_path(client, seeded_db, admin_and_targets):
    _admin, mgr, op = admin_and_targets
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/supervisor",
        json={"supervisor_id": mgr.id},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supervisor_id"] == mgr.id
    assert body["tier_label"] == "Operator"


def test_clear_supervisor_with_null(client, seeded_db, admin_and_targets):
    _admin, mgr, op = admin_and_targets
    op.supervisor_id = mgr.id
    seeded_db.commit()
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/supervisor",
        json={"supervisor_id": None},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["supervisor_id"] is None


def test_supervisor_must_outrank_subordinate(client, seeded_db, admin_and_targets):
    _admin, mgr, op = admin_and_targets
    # mgr (lvl 3) trying to be supervised by op (lvl 1) — backwards
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{mgr.id}/supervisor",
        json={"supervisor_id": op.id},
        headers=h,
    )
    assert r.status_code == 400
    assert "outrank" in r.json()["detail"].lower()


def test_supervisor_same_level_rejected(client, seeded_db):
    admin = _add_user(seeded_db, code="WHS-001-ADMIN", level=4)
    peer1 = _add_user(seeded_db, code="WHS-001-LEAD-A", level=3)
    peer2 = _add_user(seeded_db, code="WHS-001-LEAD-B", level=3)
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{peer1.id}/supervisor",
        json={"supervisor_id": peer2.id},
        headers=h,
    )
    assert r.status_code == 400
    assert admin.id  # silence unused


def test_self_supervisor_rejected(client, seeded_db, admin_and_targets):
    _admin, _mgr, op = admin_and_targets
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/supervisor",
        json={"supervisor_id": op.id},
        headers=h,
    )
    assert r.status_code == 400
    assert "themselves" in r.json()["detail"].lower() or "own" in r.json()["detail"].lower()


def test_cycle_detection(client, seeded_db):
    """A → B → C → A must fail at the closing edge."""
    _add_user(seeded_db, code="WHS-001-ADMIN", level=5)
    a = _add_user(seeded_db, code="WHS-001-AA", level=4)
    b = _add_user(seeded_db, code="WHS-001-BB", level=3)
    c = _add_user(seeded_db, code="WHS-001-CC", level=2)

    h = _login(client, "WHS-001-ADMIN")
    # B reports to A
    assert client.put(f"/api/v1/admin/users/{b.id}/supervisor",
                      json={"supervisor_id": a.id}, headers=h).status_code == 200
    # C reports to B
    assert client.put(f"/api/v1/admin/users/{c.id}/supervisor",
                      json={"supervisor_id": b.id}, headers=h).status_code == 200
    # Now try to make A report to C — closes the cycle. Must fail.
    # But note: A is lvl 4, C is lvl 2 → outrank check fires first. Re-rank to test cycle:
    a.permission_level = 1
    c.permission_level = 2
    seeded_db.commit()
    r = client.put(f"/api/v1/admin/users/{a.id}/supervisor",
                   json={"supervisor_id": c.id}, headers=h)
    assert r.status_code == 400
    assert "cycle" in r.json()["detail"].lower()


def test_cross_site_supervisor_rejected_unless_mcs(client, seeded_db, admin_and_targets):
    _admin, _mgr, op = admin_and_targets
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    other_mgr = _add_user(seeded_db, code="WHS-002-MGR", level=4, site_id="WHS-002")

    seeded_db.add(Site(id="MCS", name="Master", city="HQ", is_master=True))
    seeded_db.commit()
    mcs_admin = _add_user(seeded_db, code="MCS-ADMIN", level=5, site_id="MCS")

    h = _login(client, "MCS-ADMIN", site="MCS")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/supervisor",
        json={"supervisor_id": other_mgr.id},
        headers=h,
    )
    # Cross-site, non-MCS supervisor → reject
    assert r.status_code == 400
    assert "same site" in r.json()["detail"].lower() or "mcs" in r.json()["detail"].lower()
    assert mcs_admin.id  # quiet linter


def test_mcs_supervisor_can_supervise_any_site(client, seeded_db, admin_and_targets):
    _admin, _mgr, op = admin_and_targets
    seeded_db.add(Site(id="MCS", name="Master", city="HQ", is_master=True))
    seeded_db.commit()
    mcs_admin = _add_user(seeded_db, code="MCS-ADMIN", level=5, site_id="MCS")

    h = _login(client, "MCS-ADMIN", site="MCS")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/supervisor",
        json={"supervisor_id": mcs_admin.id},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["supervisor_id"] == mcs_admin.id


# ── Transfer department / change shift ─────────────────────────────────


def test_transfer_department(client, seeded_db, admin_and_targets):
    _admin, _mgr, op = admin_and_targets
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/department",
        json={"department": "Receiving"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["department"] == "Receiving"


def test_change_shift(client, seeded_db, admin_and_targets):
    _admin, _mgr, op = admin_and_targets
    h = _login(client, "WHS-001-ADMIN")
    r = client.put(
        f"/api/v1/admin/users/{op.id}/shift",
        json={"shift": "Graveyard"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["shift"] == "Graveyard"


def test_assignment_endpoints_respect_permission_gates(client, auth_headers, seeded_db):
    """A Level-1 operator must be denied at the assignment endpoints, too."""
    op = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r1 = client.put(f"/api/v1/admin/users/{op.id}/supervisor",
                    json={"supervisor_id": None}, headers=auth_headers)
    r2 = client.put(f"/api/v1/admin/users/{op.id}/department",
                    json={"department": "X"}, headers=auth_headers)
    r3 = client.put(f"/api/v1/admin/users/{op.id}/shift",
                    json={"shift": "X"}, headers=auth_headers)
    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403


# ── Subordinates ───────────────────────────────────────────────────────


def test_list_subordinates_returns_only_direct_reports(client, seeded_db, admin_and_targets):
    _admin, mgr, op = admin_and_targets
    op.supervisor_id = mgr.id
    other = _add_user(seeded_db, code="WHS-001-002", level=1)
    other.supervisor_id = mgr.id
    seeded_db.commit()

    h = _login(client, "WHS-001-ADMIN")
    r = client.get(f"/api/v1/admin/users/{mgr.id}/subordinates", headers=h)
    assert r.status_code == 200
    codes = {s["employee_code"] for s in r.json()}
    assert codes == {"WHS-001-001", "WHS-001-002"}


def test_subordinates_excludes_inactive(client, seeded_db, admin_and_targets):
    _admin, mgr, op = admin_and_targets
    op.supervisor_id = mgr.id
    op.is_active = False
    seeded_db.commit()

    h = _login(client, "WHS-001-ADMIN")
    r = client.get(f"/api/v1/admin/users/{mgr.id}/subordinates", headers=h)
    assert r.status_code == 200
    assert r.json() == []

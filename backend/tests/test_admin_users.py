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


# ── Top-down hierarchy chain ────────────────────────────────────────────
# Verifies that the creation invariant holds at every level: a caller at
# level N can create a subordinate at level N-1 (and below), but NEVER a
# peer (level N) or superior (level > N). Mirrors the UI flow where a
# Lvl 5 admin onboards a Lvl 4 manager, who then onboards a Lvl 3 lead, etc.


def test_top_down_hierarchy_chain_creates_full_org(client, seeded_db):
    """Walk the 5→4→3→{2,1} chain, each tier creating the one below it.

    Design invariant: user management requires permission_level >= 3
    (see wms/services/users_admin.py). Lvl 1 operators and Lvl 2 supervisors
    are read-only consumers of the org — they cannot mint users. The chain
    therefore branches at Lvl 3, which onboards both supervisors (Lvl 2)
    and operators (Lvl 1) directly.

    Each link asserts:
      (1) the create succeeds with the correct level
      (2) the freshly-created caller can log in
      (3) attempting to create at-or-above own level returns 403
    """
    # Bootstrap: Lvl 5 super-admin. Lvl 5 cannot be self-promoted to —
    # it must be seeded (initial deployment) or created by another Lvl 5+.
    _seed_admin(seeded_db, code="WHS-001-L5", level=5)

    chain = [
        # (caller_code, new_code, new_level, new_role)
        ("WHS-001-L5", "WHS-001-L4", 4, "manager"),
        ("WHS-001-L4", "WHS-001-L3", 3, "lead"),
        ("WHS-001-L3", "WHS-001-L2", 2, "supervisor"),
        ("WHS-001-L3", "WHS-001-L1", 1, "operator"),
    ]

    for caller_code, new_code, new_level, new_role in chain:
        token = _login(client, caller_code)

        # (3) Reject creating a peer (at the caller's own level)
        # NOTE: a Lvl 3 caller's "peer level" is 3 itself. We can't probe
        # the at-own-level rule for callers below Lvl 4 here because the
        # Lvl 3+ gate fires first (peer would be Lvl 3, which the caller IS).
        # That edge is covered by test_cannot_create_user_at_or_above_own_level.
        # Here we only probe peer-rejection where it's distinguishable:
        if new_level >= 3:
            caller_level = new_level + 1
            r_peer = client.post(
                "/api/v1/admin/users",
                json={
                    "employee_code": f"{new_code}-PEER",
                    "email": f"{new_code.lower()}-peer@wms.local",
                    "full_name": "Peer",
                    "permission_level": caller_level,
                    "password": "pw1234",
                },
                headers=_headers(token),
            )
            assert r_peer.status_code == 403, (
                f"caller {caller_code} should NOT create a peer at lvl {caller_level}"
            )

        # (1) Create the next subordinate
        r = client.post(
            "/api/v1/admin/users",
            json={
                "employee_code": new_code,
                "email": f"{new_code.lower()}@wms.local",
                "full_name": f"Tier {new_level}",
                "role": new_role,
                "permission_level": new_level,
                "password": "password123",
            },
            headers=_headers(token),
        )
        assert r.status_code == 201, (
            f"caller {caller_code} (lvl > {new_level}) should create lvl {new_level}: {r.text}"
        )
        body = r.json()
        assert body["employee_code"] == new_code
        assert body["permission_level"] == new_level
        assert body["role"] == new_role

        # (2) The newly-created user can log in
        new_token = _login(client, new_code)
        assert new_token, f"{new_code} could not log in after creation"

        # SCO-99: admin-created users land with must_change_password=True,
        # which would 403 their subsequent admin/list calls in this chain.
        # The test is about hierarchy, not password rotation — clear the
        # flag directly so the next iteration can use this user as a caller.
        new_user = (
            seeded_db.query(User).filter(User.employee_code == new_code).first()
        )
        new_user.must_change_password = False
        seeded_db.commit()

    # Final assertion: full org tree is in place
    final_codes = {
        u.employee_code
        for u in seeded_db.query(User)
        .filter(User.employee_code.in_(
            ["WHS-001-L5", "WHS-001-L4", "WHS-001-L3", "WHS-001-L2", "WHS-001-L1"]
        ))
        .all()
    }
    assert final_codes == {
        "WHS-001-L5", "WHS-001-L4", "WHS-001-L3", "WHS-001-L2", "WHS-001-L1"
    }


def test_lvl2_supervisor_blocked_from_user_management(client, seeded_db):
    """Lvl 2 supervisors are non-admin: they cannot list, create, or modify users.

    This is the explicit boundary: even though Lvl 2 is "above" Lvl 1, the
    admin endpoints require Lvl 3+ (see users_admin.assert_can_admin).
    """
    _seed_admin(seeded_db, code="WHS-001-SUP", level=2)
    token = _login(client, "WHS-001-SUP")
    # Cannot list
    assert client.get("/api/v1/admin/users", headers=_headers(token)).status_code == 403
    # Cannot create
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-NEW",
            "email": "n@wms.local",
            "full_name": "New",
            "permission_level": 1,
            "password": "pw1234",
        },
        headers=_headers(token),
    )
    assert r.status_code == 403


def test_lvl1_operator_cannot_create_anyone(client, seeded_db):
    """The bottom of the chain — Lvl 1 must be blocked from any admin call."""
    # The default seeded user is already Lvl 1 (WHS-001-001).
    token = _login(client, "WHS-001-001")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-IMPOSTER",
            "email": "i@wms.local",
            "full_name": "Imposter",
            "permission_level": 1,
            "password": "pw1234",
        },
        headers=_headers(token),
    )
    assert r.status_code == 403


def test_lvl4_cannot_create_lvl5_or_above(client, seeded_db):
    """Promotion ceiling: a Lvl 4 manager cannot mint a Lvl 5 super-admin."""
    _seed_admin(seeded_db, code="WHS-001-L4", level=4)
    token = _login(client, "WHS-001-L4")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-ROGUE",
            "email": "r@wms.local",
            "full_name": "Rogue Super",
            "permission_level": 5,
            "password": "pw1234",
        },
        headers=_headers(token),
    )
    assert r.status_code == 403


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


# ── SCO-80: org-metadata FKs on user create/update ──────────────────────


def _seed_role(db, *, name="supervisor-test", default_level=3, site_id=None):
    from wms.models import Role
    r = Role(name=name, default_permission_level=default_level, site_id=site_id)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _seed_dept(db, *, name="Receiving-Test", site_id="WHS-001"):
    from wms.models import Department
    d = Department(name=name, site_id=site_id)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _seed_shift(db, *, name="Morning-Test", site_id="WHS-001"):
    from datetime import time

    from wms.models import Shift
    s = Shift(name=name, site_id=site_id, start_time=time(6, 0), end_time=time(14, 0))
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_create_user_auto_fills_permission_level_from_role(client, seeded_db):
    """When role_id is given but permission_level is omitted, derive from Role.default_permission_level."""
    _seed_admin(seeded_db, level=5)
    role = _seed_role(seeded_db, name="lead-auto", default_level=2)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-AUTO",
            "email": "auto@wms.local",
            "full_name": "Auto Fill",
            "password": "pw1234",
            "role_id": role.id,
        },
        headers=_headers(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["permission_level"] == 2
    assert body["role_id"] == role.id
    assert body["role"] == "lead-auto"  # legacy string backfilled


def test_create_user_explicit_level_overrides_role_default(client, seeded_db):
    """Interim leadership: admin can bump an Operator into a Supervisor role at level 4."""
    _seed_admin(seeded_db, level=5)
    role = _seed_role(seeded_db, name="supervisor-auto", default_level=3)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-OVR",
            "email": "ovr@wms.local",
            "full_name": "Override",
            "password": "pw1234",
            "role_id": role.id,
            "permission_level": 4,
        },
        headers=_headers(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["permission_level"] == 4  # explicit wins
    assert body["role_id"] == role.id


def test_create_user_refuses_cross_site_role(client, seeded_db):
    """Site-specific role on WHS-002 cannot be assigned to a WHS-001 user."""
    _seed_admin(seeded_db, level=4)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    foreign = _seed_role(seeded_db, name="foreign", default_level=2, site_id="WHS-002")
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-X",
            "email": "x@wms.local",
            "full_name": "X",
            "password": "pw1234",
            "role_id": foreign.id,
        },
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "WHS-002" in r.json()["detail"]


def test_create_user_refuses_cross_site_department(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    foreign_dept = _seed_dept(seeded_db, name="ForeignDept", site_id="WHS-002")
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-XD",
            "email": "xd@wms.local",
            "full_name": "XD",
            "password": "pw1234",
            "department_id": foreign_dept.id,
        },
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "WHS-002" in r.json()["detail"]


def test_create_user_global_role_works_anywhere(client, seeded_db):
    """Global role (site_id IS NULL) is assignable from any site."""
    _seed_admin(seeded_db, level=4)
    global_role = _seed_role(seeded_db, name="global-op", default_level=1, site_id=None)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-G",
            "email": "g@wms.local",
            "full_name": "G",
            "password": "pw1234",
            "role_id": global_role.id,
        },
        headers=_headers(token),
    )
    assert r.status_code == 201
    assert r.json()["permission_level"] == 1


def test_update_user_sets_dept_id_and_backfills_string(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    dept = _seed_dept(seeded_db, name="QA-Updated")
    token = _login(client, "WHS-001-ADMIN")
    # Get the seeded operator
    list_resp = client.get("/api/v1/admin/users", headers=_headers(token)).json()
    operator_id = next(u["id"] for u in list_resp["items"] if u["employee_code"] == "WHS-001-001")
    r = client.put(
        f"/api/v1/admin/users/{operator_id}",
        json={"department_id": dept.id},
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["department_id"] == dept.id
    assert r.json()["department"] == "QA-Updated"


def test_update_user_refuses_cross_site_shift(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    foreign_shift = _seed_shift(seeded_db, name="FShift", site_id="WHS-002")
    token = _login(client, "WHS-001-ADMIN")
    list_resp = client.get("/api/v1/admin/users", headers=_headers(token)).json()
    operator_id = next(u["id"] for u in list_resp["items"] if u["employee_code"] == "WHS-001-001")
    r = client.put(
        f"/api/v1/admin/users/{operator_id}",
        json={"shift_id": foreign_shift.id},
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "WHS-002" in r.json()["detail"]


# ── SCO-104: title_id + custom_title on user create/update ──────────────


def _seed_title(db, *, name="Plant Supervisor", site_id=None):
    from wms.models import Title
    t = Title(name=name, site_id=site_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_create_user_with_title_id(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    title = _seed_title(seeded_db, name="Plant Supervisor", site_id=None)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-T01",
            "email": "t01@wms.local",
            "full_name": "Titled User",
            "permission_level": 1,
            "password": "tempPass1!",
            "title_id": title.id,
        },
        headers=_headers(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title_id"] == title.id
    assert body["custom_title"] is None


def test_create_user_with_custom_title(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-T02",
            "email": "t02@wms.local",
            "full_name": "Custom Titled",
            "permission_level": 1,
            "password": "tempPass1!",
            "custom_title": "  Forklift Captain  ",
        },
        headers=_headers(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title_id"] is None
    assert body["custom_title"] == "Forklift Captain"


def test_create_user_refuses_cross_site_title(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    foreign = _seed_title(seeded_db, name="Foreign Title", site_id="WHS-002")
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-T03",
            "email": "t03@wms.local",
            "full_name": "Cross Site Title",
            "permission_level": 1,
            "password": "tempPass1!",
            "title_id": foreign.id,
        },
        headers=_headers(token),
    )
    assert r.status_code == 400
    assert "WHS-002" in r.json()["detail"]


def test_update_user_swap_title_to_custom(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    title = _seed_title(seeded_db, name="Manager")
    token = _login(client, "WHS-001-ADMIN")
    list_resp = client.get("/api/v1/admin/users", headers=_headers(token)).json()
    op_id = next(u["id"] for u in list_resp["items"] if u["employee_code"] == "WHS-001-001")
    r1 = client.put(
        f"/api/v1/admin/users/{op_id}",
        json={"title_id": title.id},
        headers=_headers(token),
    )
    assert r1.status_code == 200 and r1.json()["title_id"] == title.id
    r2 = client.put(
        f"/api/v1/admin/users/{op_id}",
        json={"title_id": None, "custom_title": "Acting Lead"},
        headers=_headers(token),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["title_id"] is None
    assert r2.json()["custom_title"] == "Acting Lead"

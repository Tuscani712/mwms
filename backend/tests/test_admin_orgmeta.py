"""Admin org-metadata: /admin/roles, /admin/departments, /admin/shifts (SCO-79).

Covers happy-path CRUD plus the permission gates that are easy to regress:
- Lvl 1 operator denied at every entry point
- Lvl 3+ can manage own-site dept/shift but NOT global roles
- MCS Lvl 4+ can manage globals + any site
- Cross-site mutation refused unless caller is MCS Lvl 4+
- Uniqueness within (site_id, name) enforced
"""

from __future__ import annotations

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


def _login(client, code, site="WHS-001"):
    return client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": "password123", "site_id": site},
    ).json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ── Roles ───────────────────────────────────────────────────────────────

def test_operator_denied_everywhere(client, auth_headers):
    """Lvl 1 user can't even list, let alone create."""
    assert client.get("/api/v1/admin/roles", headers=auth_headers).status_code == 403
    assert client.get("/api/v1/admin/departments", headers=auth_headers).status_code == 403
    assert client.get("/api/v1/admin/shifts", headers=auth_headers).status_code == 403


def test_lvl3_cannot_create_global_role(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/roles",
        json={"name": "rogue-global", "default_permission_level": 2, "site_id": None},
        headers=_h(token),
    )
    assert r.status_code == 403
    assert "MCS" in r.json()["detail"]


def test_mcs_admin_creates_global_role(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/roles",
        json={"name": "intern", "default_permission_level": 1, "site_id": None},
        headers=_h(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["site_id"] is None
    assert body["default_permission_level"] == 1


def test_lvl3_creates_site_specific_role(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/roles",
        json={"name": "Forklift Operator", "default_permission_level": 1,
              "site_id": "WHS-001"},
        headers=_h(token),
    )
    assert r.status_code == 201
    assert r.json()["site_id"] == "WHS-001"


def test_cross_site_role_create_refused_without_mcs(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/roles",
        json={"name": "Foreign", "default_permission_level": 1, "site_id": "WHS-002"},
        headers=_h(token),
    )
    assert r.status_code == 403


def test_role_name_uniqueness_per_scope(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    payload = {"name": "dup", "default_permission_level": 1, "site_id": "WHS-001"}
    assert client.post("/api/v1/admin/roles", json=payload, headers=_h(token)).status_code == 201
    r2 = client.post("/api/v1/admin/roles", json=payload, headers=_h(token))
    assert r2.status_code == 400
    assert "already exists" in r2.json()["detail"]


def test_role_list_filters_to_own_site_plus_globals(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    other = Site(id="WHS-002", name="HOU", city="Houston")
    seeded_db.add(other)
    seeded_db.commit()
    # Pre-seed: 1 global, 1 own-site, 1 other-site
    from wms.models import Role
    seeded_db.add(Role(name="global-only", default_permission_level=1, site_id=None))
    seeded_db.add(Role(name="own", default_permission_level=2, site_id="WHS-001"))
    seeded_db.add(Role(name="foreign", default_permission_level=2, site_id="WHS-002"))
    seeded_db.commit()

    token = _login(client, "WHS-001-LEAD")
    r = client.get("/api/v1/admin/roles", headers=_h(token))
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert "global-only" in names
    assert "own" in names
    assert "foreign" not in names  # cross-site invisible to non-MCS


def test_role_update_changes_default_level(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/roles",
        json={"name": "trainee", "default_permission_level": 1, "site_id": "WHS-001"},
        headers=_h(token),
    )
    role_id = r.json()["id"]
    r2 = client.put(
        f"/api/v1/admin/roles/{role_id}",
        json={"default_permission_level": 2},
        headers=_h(token),
    )
    assert r2.status_code == 200
    assert r2.json()["default_permission_level"] == 2


# ── Departments ─────────────────────────────────────────────────────────

def test_lvl3_creates_own_site_department(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/departments",
        json={"name": "Night Receiving"},
        headers=_h(token),
    )
    assert r.status_code == 201
    assert r.json()["site_id"] == "WHS-001"


def test_dept_cross_site_refused(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    seeded_db.add(Site(id="WHS-002", name="HOU", city="Houston"))
    seeded_db.commit()
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/departments",
        json={"name": "Foreign Dept", "site_id": "WHS-002"},
        headers=_h(token),
    )
    assert r.status_code == 403


def test_dept_list_isolation(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    other = Site(id="WHS-002", name="HOU", city="Houston")
    seeded_db.add(other)
    seeded_db.commit()
    from wms.models import Department
    seeded_db.add(Department(name="Local", site_id="WHS-001"))
    seeded_db.add(Department(name="Foreign", site_id="WHS-002"))
    seeded_db.commit()
    token = _login(client, "WHS-001-LEAD")
    r = client.get("/api/v1/admin/departments", headers=_h(token))
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert "Local" in names
    assert "Foreign" not in names


def test_dept_deactivate(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/departments", json={"name": "Doomed"}, headers=_h(token),
    )
    did = r.json()["id"]
    r2 = client.delete(f"/api/v1/admin/departments/{did}", headers=_h(token))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False


# ── Shifts ──────────────────────────────────────────────────────────────

def test_shift_create_with_times(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    r = client.post(
        "/api/v1/admin/shifts",
        json={"name": "Swing", "start_time": "10:00:00", "end_time": "18:00:00"},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["start_time"].startswith("10:00")
    assert body["end_time"].startswith("18:00")


def test_shift_uniqueness_within_site(client, seeded_db):
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    payload = {"name": "Morning", "start_time": "06:00:00", "end_time": "14:00:00"}
    assert client.post("/api/v1/admin/shifts", json=payload, headers=_h(token)).status_code == 201
    r2 = client.post("/api/v1/admin/shifts", json=payload, headers=_h(token))
    assert r2.status_code == 400


# ── SCO-115: MCS cross-site authoring + default-hardening ───────────────

def test_mcs_dept_missing_site_id_returns_400(client, seeded_db):
    """MCS admin must specify site_id — silent fallback to MCS would have masked the bug."""
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/departments",
        json={"name": "Orphan"},
        headers=_h(token),
    )
    assert r.status_code == 400
    assert "site_id" in r.json()["detail"]


def test_mcs_shift_missing_site_id_returns_400(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/shifts",
        json={"name": "Graveyard", "start_time": "22:00:00", "end_time": "06:00:00"},
        headers=_h(token),
    )
    assert r.status_code == 400


def test_mcs_creates_department_at_other_site(client, seeded_db):
    """The whole point of SCO-115 — MCS authoring per-site entries for WHS-001."""
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/departments",
        json={"name": "Receiving", "site_id": "WHS-001"},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["site_id"] == "WHS-001"


def test_mcs_creates_shift_at_other_site(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/shifts",
        json={"name": "Day", "start_time": "06:00:00", "end_time": "14:00:00",
              "site_id": "WHS-001"},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["site_id"] == "WHS-001"


def test_mcs_creates_title_at_other_site(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/titles",
        json={"name": "Plant Supervisor", "site_id": "WHS-001"},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["site_id"] == "WHS-001"


def test_mcs_dept_list_filter_by_site_id(client, seeded_db):
    """MCS admin can list dept at any site via ?site_id=."""
    _seed_mcs(seeded_db)
    from wms.models import Department
    seeded_db.add(Department(name="Local-MCS", site_id="MCS"))
    seeded_db.add(Department(name="Local-WHS", site_id="WHS-001"))
    seeded_db.commit()
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.get("/api/v1/admin/departments?site_id=WHS-001", headers=_h(token))
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert names == {"Local-WHS"}


def test_mcs_dept_list_returns_all_sites_without_filter(client, seeded_db):
    """User-create modal: MCS admin's blanket list_departments() must return
    WHS-001 entries so the modal can populate when target site = WHS-001."""
    _seed_mcs(seeded_db)
    from wms.models import Department, Shift
    from datetime import time
    seeded_db.add(Department(name="MCS-Office", site_id="MCS"))
    seeded_db.add(Department(name="WHS-Receiving", site_id="WHS-001"))
    seeded_db.add(Shift(name="MCS-Day", site_id="MCS",
                        start_time=time(8, 0), end_time=time(17, 0)))
    seeded_db.add(Shift(name="WHS-Day", site_id="WHS-001",
                        start_time=time(6, 0), end_time=time(14, 0)))
    seeded_db.commit()
    token = _login(client, "MCS-ADMIN", site="MCS")

    r1 = client.get("/api/v1/admin/departments", headers=_h(token))
    assert r1.status_code == 200
    names = {row["name"] for row in r1.json()}
    assert names == {"MCS-Office", "WHS-Receiving"}

    r2 = client.get("/api/v1/admin/shifts", headers=_h(token))
    assert r2.status_code == 200
    shift_names = {row["name"] for row in r2.json()}
    assert shift_names == {"MCS-Day", "WHS-Day"}


def test_non_mcs_dept_create_still_defaults_to_own_site(client, seeded_db):
    """Back-compat: non-MCS callers without site_id continue defaulting to own site."""
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    token = _login(client, "WHS-001-LEAD")
    r = client.post(
        "/api/v1/admin/departments",
        json={"name": "Quality"},
        headers=_h(token),
    )
    assert r.status_code == 201
    assert r.json()["site_id"] == "WHS-001"

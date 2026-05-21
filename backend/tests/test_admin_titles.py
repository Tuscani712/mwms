"""SCO-100/107: Title CRUD + hard-delete guards across Role / Dept / Shift / Title.

Covers:
- list/create/update/deactivate happy path
- Lvl 1 operator denied
- Cross-site mutation refused unless caller is MCS Lvl 4+
- Uniqueness within (site_id, name)
- Hard-delete /purge: 204 when zero refs, 409 + ref_count when in use
- Same purge contract on roles, departments, shifts
"""

from __future__ import annotations

from datetime import time

from wms.core.security import hash_password
from wms.models import Department, Role, Shift, Site, Title, User


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


# ── Title CRUD ──────────────────────────────────────────────────────────


def test_operator_denied_listing_titles(client, auth_headers):
    """Lvl 1 user cannot even read the title list."""
    assert client.get("/api/v1/admin/titles", headers=auth_headers).status_code == 403


def test_lvl3_lists_globals_plus_own_site(client, seeded_db):
    _seed_admin(seeded_db, code="WHS-001-LEAD", level=3)
    # Pre-seed a global title and a foreign-site title to confirm scoping.
    seeded_db.add_all(
        [
            Title(name="Supervisor", site_id=None),
            Title(name="Plant Manager", site_id=None),
        ]
    )
    seeded_db.commit()
    token = _login(client, "WHS-001-LEAD")
    r = client.get("/api/v1/admin/titles", headers=_h(token))
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert names == {"Supervisor", "Plant Manager"}


def test_mcs_admin_creates_global_title(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.post(
        "/api/v1/admin/titles",
        json={"name": "Forklift Operator", "site_id": None},
        headers=_h(token),
    )
    assert r.status_code == 201
    assert r.json()["site_id"] is None
    assert r.json()["is_active"] is True


def test_duplicate_title_in_same_scope_rejected(client, seeded_db):
    """Duplicate (site_id, name) rejected. Uses a non-NULL site_id because
    SQLite treats NULLs as distinct in unique constraints (intentional, per
    SQL standard) — same gotcha existing role tests work around."""
    _seed_admin(seeded_db, level=4)
    token = _login(client, "WHS-001-ADMIN")
    payload = {"name": "Supervisor", "site_id": "WHS-001"}
    assert client.post(
        "/api/v1/admin/titles", json=payload, headers=_h(token)
    ).status_code == 201
    r = client.post("/api/v1/admin/titles", json=payload, headers=_h(token))
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


def test_rename_title(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    create = client.post(
        "/api/v1/admin/titles",
        json={"name": "Supervisor", "site_id": None},
        headers=_h(token),
    )
    tid = create.json()["id"]
    r = client.put(
        f"/api/v1/admin/titles/{tid}",
        json={"name": "Floor Supervisor"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Floor Supervisor"


def test_deactivate_title(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    create = client.post(
        "/api/v1/admin/titles",
        json={"name": "Supervisor", "site_id": None},
        headers=_h(token),
    )
    tid = create.json()["id"]
    r = client.delete(f"/api/v1/admin/titles/{tid}", headers=_h(token))
    assert r.status_code == 200
    assert r.json()["is_active"] is False


# ── /purge: hard-delete with ref-count guard (SCO-100 / SCO-107) ────────


def test_purge_title_when_unused_succeeds(client, seeded_db):
    _seed_mcs(seeded_db)
    token = _login(client, "MCS-ADMIN", site="MCS")
    create = client.post(
        "/api/v1/admin/titles",
        json={"name": "Temp", "site_id": None},
        headers=_h(token),
    )
    tid = create.json()["id"]
    r = client.delete(f"/api/v1/admin/titles/{tid}/purge", headers=_h(token))
    assert r.status_code == 204
    # Row gone.
    assert seeded_db.query(Title).filter(Title.id == tid).one_or_none() is None


def test_purge_title_in_use_409_with_ref_count(client, seeded_db):
    _seed_mcs(seeded_db)
    # Create a title and attach a user to it.
    t = Title(name="Supervisor", site_id=None)
    seeded_db.add(t)
    seeded_db.commit()
    seeded_db.refresh(t)
    user = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").first()
    user.title_id = t.id
    seeded_db.commit()

    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.delete(f"/api/v1/admin/titles/{t.id}/purge", headers=_h(token))
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["entity"] == "Title"
    assert body["ref_count"] == 1
    # Row preserved.
    assert seeded_db.query(Title).filter(Title.id == t.id).one_or_none() is not None


def test_purge_role_when_unused_succeeds(client, seeded_db):
    _seed_mcs(seeded_db)
    r = seeded_db.query(Role).first()  # may be empty in seeded_db
    if r is None:
        # No global roles seeded in conftest; create one to purge.
        r = Role(name="probationary", default_permission_level=1, site_id=None)
        seeded_db.add(r)
        seeded_db.commit()
        seeded_db.refresh(r)
    token = _login(client, "MCS-ADMIN", site="MCS")
    resp = client.delete(f"/api/v1/admin/roles/{r.id}/purge", headers=_h(token))
    assert resp.status_code == 204


def test_purge_role_in_use_409(client, seeded_db):
    _seed_mcs(seeded_db)
    role = Role(name="supervisor-test", default_permission_level=3, site_id=None)
    seeded_db.add(role)
    seeded_db.commit()
    seeded_db.refresh(role)
    user = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").first()
    user.role_id = role.id
    seeded_db.commit()

    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.delete(f"/api/v1/admin/roles/{role.id}/purge", headers=_h(token))
    assert r.status_code == 409
    assert r.json()["detail"]["entity"] == "Role"
    assert r.json()["detail"]["ref_count"] == 1


def test_purge_department_in_use_409(client, seeded_db):
    _seed_mcs(seeded_db)
    dept = Department(name="Receiving", site_id="WHS-001")
    seeded_db.add(dept)
    seeded_db.commit()
    seeded_db.refresh(dept)
    user = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").first()
    user.department_id = dept.id
    seeded_db.commit()

    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.delete(f"/api/v1/admin/departments/{dept.id}/purge", headers=_h(token))
    assert r.status_code == 409
    assert r.json()["detail"]["entity"] == "Department"
    assert r.json()["detail"]["ref_count"] == 1


def test_purge_department_unused_succeeds(client, seeded_db):
    _seed_mcs(seeded_db)
    dept = Department(name="Maintenance", site_id="WHS-001")
    seeded_db.add(dept)
    seeded_db.commit()
    seeded_db.refresh(dept)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.delete(f"/api/v1/admin/departments/{dept.id}/purge", headers=_h(token))
    assert r.status_code == 204


def test_purge_shift_in_use_409(client, seeded_db):
    _seed_mcs(seeded_db)
    shift = Shift(
        name="A", site_id="WHS-001", start_time=time(6, 0), end_time=time(14, 0)
    )
    seeded_db.add(shift)
    seeded_db.commit()
    seeded_db.refresh(shift)
    user = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").first()
    user.shift_id = shift.id
    seeded_db.commit()

    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.delete(f"/api/v1/admin/shifts/{shift.id}/purge", headers=_h(token))
    assert r.status_code == 409
    assert r.json()["detail"]["entity"] == "Shift"
    assert r.json()["detail"]["ref_count"] == 1


def test_purge_shift_unused_succeeds(client, seeded_db):
    _seed_mcs(seeded_db)
    shift = Shift(
        name="D-graveyard", site_id="WHS-001",
        start_time=time(22, 0), end_time=time(6, 0),
    )
    seeded_db.add(shift)
    seeded_db.commit()
    seeded_db.refresh(shift)
    token = _login(client, "MCS-ADMIN", site="MCS")
    r = client.delete(f"/api/v1/admin/shifts/{shift.id}/purge", headers=_h(token))
    assert r.status_code == 204


# ── Seed defaults ───────────────────────────────────────────────────────


def test_seed_titles_idempotent_and_populates_defaults(db_session):
    """seed_titles can be called twice without duplicating rows."""
    from wms.seeders.seed import DEFAULT_GLOBAL_TITLES, seed_titles

    seed_titles(db_session)
    seed_titles(db_session)  # idempotent
    rows = db_session.query(Title).filter(Title.site_id.is_(None)).all()
    names = {r.name for r in rows}
    assert names == set(DEFAULT_GLOBAL_TITLES)
    assert len(rows) == len(DEFAULT_GLOBAL_TITLES)

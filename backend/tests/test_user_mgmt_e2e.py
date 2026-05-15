"""End-to-end: full admin user-management lifecycle in one flow.

Exercises SCO-35 + SCO-36 together as the frontend will: create → list → edit →
assign supervisor → deactivate → reactivate → list with filters.
"""

from wms.core.security import hash_password
from wms.models import User


def _seed_admin(db, *, code="WHS-001-ADMIN", level=4):
    u = User(
        site_id="WHS-001",
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


def _login_admin(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-ADMIN", "password": "password123", "site_id": "WHS-001"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_user_management_lifecycle(client, seeded_db):
    _seed_admin(seeded_db)
    h = _login_admin(client)

    # 1. Tier labels available
    tiers = client.get("/api/v1/admin/users/tiers/labels", headers=h).json()
    assert tiers["1"] == "Operator"

    # 2. Create a mid-level lead
    created = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-200",
            "email": "lead@wms.local",
            "full_name": "Pat Lead",
            "role": "lead",
            "permission_level": 2,
            "password": "pw1234",
            "department": "Receiving",
            "shift": "1st",
        },
        headers=h,
    )
    assert created.status_code == 201
    lead_id = created.json()["id"]

    # 3. Create a level-3 supervisor
    sup = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-300",
            "email": "sup@wms.local",
            "full_name": "Sam Super",
            "role": "supervisor",
            "permission_level": 3,
            "password": "pw1234",
        },
        headers=h,
    )
    sup_id = sup.json()["id"]

    # 4. Assign supervisor to the lead
    r = client.put(
        f"/api/v1/admin/users/{lead_id}/supervisor",
        json={"supervisor_id": sup_id},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["supervisor_id"] == sup_id

    # 5. Listing the supervisor's subordinates includes our lead
    subs = client.get(f"/api/v1/admin/users/{sup_id}/subordinates", headers=h).json()
    assert any(s["employee_code"] == "WHS-001-200" for s in subs)

    # 6. Filter list by role=lead → only the lead, no supervisor
    lst = client.get("/api/v1/admin/users?role=lead", headers=h).json()
    codes = [u["employee_code"] for u in lst["items"]]
    assert "WHS-001-200" in codes
    assert "WHS-001-300" not in codes

    # 7. Edit the lead — change department + shift
    upd = client.put(
        f"/api/v1/admin/users/{lead_id}",
        json={"department": "Shipping", "shift": "2nd"},
        headers=h,
    )
    assert upd.status_code == 200
    assert upd.json()["department"] == "Shipping"

    # 8. Deactivate the lead — list excludes by default, reappears with include_inactive
    assert client.delete(f"/api/v1/admin/users/{lead_id}", headers=h).status_code == 200
    default = client.get("/api/v1/admin/users", headers=h).json()
    assert "WHS-001-200" not in {u["employee_code"] for u in default["items"]}
    incl = client.get("/api/v1/admin/users?include_inactive=true", headers=h).json()
    assert "WHS-001-200" in {u["employee_code"] for u in incl["items"]}

    # 9. Subordinates list excludes inactive users
    subs_after = client.get(f"/api/v1/admin/users/{sup_id}/subordinates", headers=h).json()
    assert not any(s["employee_code"] == "WHS-001-200" for s in subs_after)

    # 10. Reactivate
    re = client.post(f"/api/v1/admin/users/{lead_id}/reactivate", headers=h)
    assert re.status_code == 200
    assert re.json()["is_active"] is True


def test_paginated_search_then_supervisor_swap(client, seeded_db):
    """A realistic admin-UI scenario: search → pick a user → reassign supervisor."""
    _seed_admin(seeded_db)
    # Seed 8 operators
    for i in range(2, 10):
        seeded_db.add(User(
            site_id="WHS-001",
            employee_code=f"WHS-001-{i:03d}",
            email=f"op{i}@wms.local",
            full_name=f"Operator {i}",
            role="operator",
            permission_level=1,
            hashed_password=hash_password("password123"),
        ))
    seeded_db.commit()

    h = _login_admin(client)

    # Two supervisors
    sup_a = client.post("/api/v1/admin/users", json={
        "employee_code": "WHS-001-S-A", "email": "sa@wms.local", "full_name": "Sup A",
        "role": "supervisor", "permission_level": 3, "password": "pw1234",
    }, headers=h).json()
    sup_b = client.post("/api/v1/admin/users", json={
        "employee_code": "WHS-001-S-B", "email": "sb@wms.local", "full_name": "Sup B",
        "role": "supervisor", "permission_level": 3, "password": "pw1234",
    }, headers=h).json()

    # Search picks the right operator
    found = client.get("/api/v1/admin/users?q=Operator+5", headers=h).json()
    op5 = next(u for u in found["items"] if u["full_name"] == "Operator 5")

    # Assign to A, then swap to B
    client.put(f"/api/v1/admin/users/{op5['id']}/supervisor",
               json={"supervisor_id": sup_a["id"]}, headers=h)
    client.put(f"/api/v1/admin/users/{op5['id']}/supervisor",
               json={"supervisor_id": sup_b["id"]}, headers=h)

    # A has none, B has one
    a_subs = client.get(f"/api/v1/admin/users/{sup_a['id']}/subordinates", headers=h).json()
    b_subs = client.get(f"/api/v1/admin/users/{sup_b['id']}/subordinates", headers=h).json()
    assert not any(s["employee_code"] == op5["employee_code"] for s in a_subs)
    assert any(s["employee_code"] == op5["employee_code"] for s in b_subs)

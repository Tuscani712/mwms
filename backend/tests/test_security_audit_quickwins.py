"""Regression tests for SCO-39/40/41 — the three audit quick-wins (L-4, L-7, M-6)."""

from wms.core.security import hash_password
from wms.models import Site, User


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


# ── L-4: Site.is_online enforced at auth ───────────────────────────────


def test_offline_site_token_is_rejected(client, seeded_db):
    """A user whose site is toggled offline cannot continue using their token."""
    login = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-001"},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    # Sanity — token works while site is online
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # Operator toggles the site offline (simulating maintenance / incident)
    site = seeded_db.query(Site).filter(Site.id == "WHS-001").one()
    site.is_online = False
    seeded_db.commit()

    # Same token, same request — must now be rejected
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401
    assert "site" in r.json()["detail"].lower()


def test_online_site_still_works(client, seeded_db):
    """Sanity-check the negative — explicitly online sites are unaffected."""
    site = seeded_db.query(Site).filter(Site.id == "WHS-001").one()
    site.is_online = True
    seeded_db.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-001"},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


# ── L-7: User.__repr__ never leaks hashed_password ─────────────────────


def test_user_repr_omits_hashed_password(seeded_db):
    user = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = repr(user)
    assert "hashed_password" not in r
    # bcrypt hashes start with $2b$ / $2a$ — make sure no fragment leaks either.
    assert "$2b$" not in r and "$2a$" not in r
    # Useful info IS still there for debugging
    assert "WHS-001-001" in r
    assert "WHS-001" in r


def test_user_repr_format_is_stable(seeded_db):
    user = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = repr(user)
    assert r.startswith("<User id=") and r.endswith(">")


# ── M-6: Email format validation on admin user payloads ───────────────


def test_admin_create_rejects_malformed_email(client, seeded_db):
    _seed_admin(seeded_db)
    token = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-ADMIN", "password": "password123", "site_id": "WHS-001"},
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    # Missing @ — must be 422 (pydantic rejects before route runs)
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-200",
            "email": "no-at-sign-here",
            "full_name": "X",
            "permission_level": 1,
            "password": "pw1234",
        },
        headers=h,
    )
    assert r.status_code == 422


def test_admin_create_rejects_script_tag_email(client, seeded_db):
    """Stops the XSS-via-stored-email vector even before HTML escaping catches it."""
    _seed_admin(seeded_db)
    token = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-ADMIN", "password": "password123", "site_id": "WHS-001"},
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-201",
            "email": "<script>alert(1)</script>@x.y",
            "full_name": "X",
            "permission_level": 1,
            "password": "pw1234",
        },
        headers=h,
    )
    assert r.status_code == 422


def test_admin_create_accepts_local_tld(client, seeded_db):
    """Dev-style .local emails (which we use throughout) must still pass."""
    _seed_admin(seeded_db)
    token = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-ADMIN", "password": "password123", "site_id": "WHS-001"},
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/api/v1/admin/users",
        json={
            "employee_code": "WHS-001-202",
            "email": "valid.user@wms.local",
            "full_name": "Valid",
            "permission_level": 1,
            "password": "pw1234",
        },
        headers=h,
    )
    assert r.status_code == 201


def test_admin_update_rejects_malformed_email(client, seeded_db):
    _seed_admin(seeded_db)
    token = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-ADMIN", "password": "password123", "site_id": "WHS-001"},
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    target = seeded_db.query(User).filter(User.employee_code == "WHS-001-001").one()
    r = client.put(
        f"/api/v1/admin/users/{target.id}",
        json={"email": "broken"},
        headers=h,
    )
    assert r.status_code == 422

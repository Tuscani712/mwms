"""Auth: login + JWT + per-site enforcement."""


def test_login_success(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-001"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["site_id"] == "WHS-001"
    assert data["role"] == "operator"
    assert data["access_token"]


def test_login_wrong_password(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "wrong", "site_id": "WHS-001"},
    )
    assert r.status_code == 401


def test_login_wrong_site(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-002"},
    )
    assert r.status_code == 401


def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["employee_code"] == "WHS-001-001"

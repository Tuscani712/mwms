def test_ping(client):
    r = client.get("/api/v1/health/ping")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["build"].startswith("v")
    assert body["uptime_seconds"] >= 0

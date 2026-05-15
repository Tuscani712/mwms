"""Receiving flow tests."""


def test_inbound_list(client, auth_headers):
    r = client.get("/api/v1/receiving/inbound", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["asn_code"] == "ASN-TEST-001"
    assert len(data[0]["lines"]) == 2


def test_check_in_flow(client, auth_headers):
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    asn_id = inbound[0]["id"]

    r = client.post(
        "/api/v1/receiving/check-in",
        json={"asn_id": asn_id, "dock_door": "D2"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "receiving"
    assert r.json()["dock_door"] == "D2"


def test_receipt_creates_lots_with_variance(client, auth_headers):
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    asn = inbound[0]
    client.post(
        "/api/v1/receiving/check-in",
        json={"asn_id": asn["id"], "dock_door": "D1"},
        headers=auth_headers,
    )
    payload = {
        "asn_id": asn["id"],
        "lines": [
            {"asn_line_id": asn["lines"][0]["id"], "qty_received": 195, "qc_passed": True},
            {"asn_line_id": asn["lines"][1]["id"], "qty_received": 150, "qc_passed": True},
        ],
        "variance_notes": "Short 5 on FLR-001 — pallet damage",
    }
    r = client.post("/api/v1/receiving/receipts", json=payload, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_variance"] == -5
    assert len(body["lot_ids"]) == 2


def test_putaway_suggestions(client, auth_headers):
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    asn_id = inbound[0]["id"]
    r = client.get(f"/api/v1/receiving/putaway-suggestions/{asn_id}", headers=auth_headers)
    assert r.status_code == 200
    suggestions = r.json()
    assert len(suggestions) == 2
    for s in suggestions:
        assert s["primary_location"] is not None
        assert s["overflow_location"] is not None

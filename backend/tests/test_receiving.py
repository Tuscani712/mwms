"""Receiving flow tests."""

from wms.models import SKU


def test_inbound_list(client, auth_headers):
    r = client.get("/api/v1/receiving/inbound", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["asn_code"] == "ASN-TEST-001"
    assert len(data[0]["lines"]) == 2


def test_inbound_line_propagates_requires_qc(client, auth_headers, seeded_db):
    # Flip one seeded SKU to requires_qc=True; the other stays False.
    flr = seeded_db.query(SKU).filter(SKU.code == "FLR-001").one()
    flr.requires_qc = True
    seeded_db.commit()

    data = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    lines = data[0]["lines"]
    by_sku = {ln["sku_code"]: ln for ln in lines}
    assert by_sku["FLR-001"]["requires_qc"] is True
    assert by_sku["SGR-001"]["requires_qc"] is False


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


# ── Cancel check-in (SCO-139 Phase 1) ───────────────────────────────────────


def test_cancel_check_in_reverts_receiving_to_scheduled(client, auth_headers):
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    asn = inbound[0]
    # Check in first.
    r = client.post(
        "/api/v1/receiving/check-in",
        json={"asn_id": asn["id"], "dock_door": "D1"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "receiving"
    # Cancel.
    r = client.post(
        f"/api/v1/receiving/asns/{asn['id']}/cancel-check-in", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "scheduled"
    assert body["dock_door"] is None
    assert body["arrived_at"] is None


def test_cancel_check_in_rejects_when_not_receiving(client, auth_headers):
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    asn_id = inbound[0]["id"]
    # ASN is 'scheduled' — never checked in. Cancel should refuse.
    r = client.post(
        f"/api/v1/receiving/asns/{asn_id}/cancel-check-in", headers=auth_headers
    )
    assert r.status_code == 400


def test_cancel_check_in_refuses_after_receipt_committed(client, auth_headers):
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    asn = inbound[0]
    # Check in.
    client.post(
        "/api/v1/receiving/check-in",
        json={"asn_id": asn["id"], "dock_door": "D1"},
        headers=auth_headers,
    )
    # Commit a receipt.
    client.post(
        "/api/v1/receiving/receipts",
        json={
            "asn_id": asn["id"],
            "lines": [
                {"asn_line_id": asn["lines"][0]["id"], "qty_received": 200, "qc_passed": True},
                {"asn_line_id": asn["lines"][1]["id"], "qty_received": 150, "qc_passed": True},
            ],
        },
        headers=auth_headers,
    )
    # Now try to cancel — should 409 because receipt exists.
    r = client.post(
        f"/api/v1/receiving/asns/{asn['id']}/cancel-check-in", headers=auth_headers
    )
    assert r.status_code == 409
    assert "admin reversal" in r.json()["detail"]

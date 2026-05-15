"""Shipping flow tests."""


def test_orders_list(client, auth_headers):
    r = client.get("/api/v1/shipping/orders", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["order_code"] == "SO-TEST-001"


def test_consolidation_plan(client, auth_headers):
    orders = client.get("/api/v1/shipping/orders", headers=auth_headers).json()
    order = orders[0]
    line = order["lines"][0]
    r = client.get(
        f"/api/v1/shipping/consolidation/{order['id']}/{line['id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200
    plan = r.json()
    assert plan["sku_code"] == "FLR-001"
    assert plan["qty_required"] == 50


def test_pick_assignment(client, auth_headers):
    orders = client.get("/api/v1/shipping/orders", headers=auth_headers).json()
    order = orders[0]
    line = order["lines"][0]
    r = client.post(
        "/api/v1/shipping/picks",
        json={"order_id": order["id"], "order_line_id": line["id"], "qty": 50, "strategy": "FIFO"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    picks = r.json()
    assert sum(p["qty_picked"] for p in picks) == 50


def test_pick_insufficient_inventory(client, auth_headers):
    orders = client.get("/api/v1/shipping/orders", headers=auth_headers).json()
    order = orders[0]
    line = order["lines"][0]
    r = client.post(
        "/api/v1/shipping/picks",
        json={"order_id": order["id"], "order_line_id": line["id"], "qty": 9999, "strategy": "FIFO"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "Insufficient" in r.json()["detail"] or "short" in r.json()["detail"].lower()


def test_truck_load_and_packing_slip(client, auth_headers):
    orders = client.get("/api/v1/shipping/orders", headers=auth_headers).json()
    order = orders[0]
    line = order["lines"][0]
    client.post(
        "/api/v1/shipping/picks",
        json={"order_id": order["id"], "order_line_id": line["id"], "qty": 50, "strategy": "FIFO"},
        headers=auth_headers,
    )
    r = client.post(
        "/api/v1/shipping/truck-load",
        json={"shipment_id": 1, "order_id": order["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    status = r.json()
    assert status["loaded_kg"] > 0
    assert status["over_budget"] is False

    r = client.get(f"/api/v1/shipping/packing-slip/{order['id']}", headers=auth_headers)
    assert r.status_code == 200
    slip = r.json()
    assert slip["order_code"] == "SO-TEST-001"
    assert len(slip["lines"]) >= 1

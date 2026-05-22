"""End-to-end workflow driven entirely by the new create endpoints (Option B).

Starts from an EMPTY site (no seeded ASN / Order / PROD-001 SKU) and exercises:
  - POST /api/v1/inventory/skus      → create 3 SKUs
  - POST /api/v1/receiving/asns      → create the inbound ASN with two ingredient lines
  - existing /receiving/check-in + /receiving/receipts → ingredient lots
  - POST /api/v1/production/recipes  → BOM
  - POST /api/v1/production/work-orders + preflight/start/complete → child lot
  - POST /api/v1/shipping/orders     → sales order for the produced SKU
  - existing /shipping/picks + /shipping/truck-load + /shipping/packing-slip

This is the manual walk-through Meatbag asked for, asserted programmatically.
"""

from wms.models import Lot, LotGenealogy, Shipment


def test_full_workflow_via_create_endpoints(client, auth_headers, seeded_db):
    db = seeded_db

    # ── Pre-clean: nuke the seeded ASN + Order so we drive everything via POST.
    from wms.models import ASN, SKU, ASNLine, Order, OrderLine
    db.query(ASNLine).delete()
    db.query(ASN).delete()
    db.query(OrderLine).delete()
    db.query(Order).delete()
    # Also drop seeded SKUs so /inventory/skus starts empty.
    db.query(SKU).delete()
    db.commit()

    # ── 1. CREATE SKUs ─────────────────────────────────────────────
    def post_sku(body):
        r = client.post("/api/v1/inventory/skus", json=body, headers=auth_headers)
        assert r.status_code == 201, r.text
        return r.json()

    flour = post_sku({"code": "FLR-001", "description": "Flour", "uom": "KG", "unit_weight_kg": 1.0})
    sugar = post_sku({"code": "SGR-001", "description": "Sugar", "uom": "KG", "unit_weight_kg": 1.0})
    product = post_sku({"code": "PROD-001", "description": "Finished product", "uom": "KG", "unit_weight_kg": 1.0})

    # Verify they appear via GET.
    listed = client.get("/api/v1/inventory/skus", headers=auth_headers).json()
    assert {s["code"] for s in listed} == {"FLR-001", "SGR-001", "PROD-001"}

    # ── 2. CREATE ASN with two ingredient lines ────────────────────
    asn = client.post(
        "/api/v1/receiving/asns",
        json={
            "asn_code": "ASN-WALK-001",
            "supplier": "Cascade Mills",
            "lines": [
                {"sku_id": flour["id"], "expected_qty": 200},
                {"sku_id": sugar["id"], "expected_qty": 150},
            ],
        },
        headers=auth_headers,
    )
    assert asn.status_code == 201, asn.text
    asn = asn.json()
    assert len(asn["lines"]) == 2

    # ── 3. RECEIVE (check-in + receipt) ────────────────────────────
    client.post(
        "/api/v1/receiving/check-in",
        json={"asn_id": asn["id"], "dock_door": "D1"},
        headers=auth_headers,
    )
    receipt = client.post(
        "/api/v1/receiving/receipts",
        json={
            "asn_id": asn["id"],
            "lines": [
                {"asn_line_id": asn["lines"][0]["id"], "qty_received": 200, "qc_passed": True},
                {"asn_line_id": asn["lines"][1]["id"], "qty_received": 150, "qc_passed": True},
            ],
        },
        headers=auth_headers,
    ).json()
    assert len(receipt["lot_ids"]) == 2

    # ── 4. CREATE recipe + WO + run through ─────────────────────────
    recipe = client.post(
        "/api/v1/production/recipes",
        json={
            "sku_id": product["id"],
            "lines": [
                {"ingredient_sku_id": flour["id"], "qty_per_unit": 2.0, "uom": "KG"},
                {"ingredient_sku_id": sugar["id"], "qty_per_unit": 1.0, "uom": "KG"},
            ],
        },
        headers=auth_headers,
    ).json()

    wo = client.post(
        "/api/v1/production/work-orders",
        json={"recipe_id": recipe["id"], "target_qty": 10},
        headers=auth_headers,
    ).json()

    pf = client.post(
        f"/api/v1/production/work-orders/{wo['id']}/preflight", headers=auth_headers,
    ).json()
    assert pf["status"] == "reserved"
    assert pf["shortages"] == []

    client.post(f"/api/v1/production/work-orders/{wo['id']}/start", headers=auth_headers)
    completed = client.post(
        f"/api/v1/production/work-orders/{wo['id']}/complete",
        json={"actual_qty": 10, "output_lot_code": "LOT-PROD-WALK-001"},
        headers=auth_headers,
    ).json()
    assert completed["status"] == "completed"

    db.expire_all()
    child = db.query(Lot).filter_by(lot_code="LOT-PROD-WALK-001").one()
    assert child.quantity == 10
    edges = db.query(LotGenealogy).filter_by(child_lot_id=child.id).all()
    assert len(edges) == 2

    # ── 5. CREATE sales order for the produced SKU ─────────────────
    order = client.post(
        "/api/v1/shipping/orders",
        json={
            "order_code": "SO-WALK-001",
            "customer": "Heartland Grocers",
            "priority": "normal",
            "lines": [{"sku_id": product["id"], "qty_ordered": 10, "fefo_required": False}],
        },
        headers=auth_headers,
    )
    assert order.status_code == 201, order.text
    order = order.json()
    order_line = order["lines"][0]

    picks = client.post(
        "/api/v1/shipping/picks",
        json={
            "order_id": order["id"],
            "order_line_id": order_line["id"],
            "qty": 10,
            "strategy": "FIFO",
        },
        headers=auth_headers,
    ).json()
    assert sum(p["qty_picked"] for p in picks) == 10

    # Seeded shipment is fine to reuse.
    shipment = db.query(Shipment).first()
    load = client.post(
        "/api/v1/shipping/truck-load",
        json={"shipment_id": shipment.id, "order_id": order["id"]},
        headers=auth_headers,
    ).json()
    assert load["over_budget"] is False
    assert load["loaded_kg"] > 0

    slip = client.get(
        f"/api/v1/shipping/packing-slip/{order['id']}", headers=auth_headers,
    ).json()
    assert slip["order_code"] == "SO-WALK-001"
    assert sum(line["qty"] for line in slip["lines"]) == 10


def test_create_sku_duplicate_code_409(client, auth_headers):
    body = {"code": "DUP-001", "description": "Dup", "uom": "EA"}
    r1 = client.post("/api/v1/inventory/skus", json=body, headers=auth_headers)
    assert r1.status_code == 201
    r2 = client.post("/api/v1/inventory/skus", json=body, headers=auth_headers)
    assert r2.status_code == 409


def test_create_asn_duplicate_code_409(client, auth_headers, seeded_db):
    # Use one of the seeded SKUs as the line item.
    skus = client.get("/api/v1/inventory/skus", headers=auth_headers).json()
    assert skus
    body = {
        "asn_code": "ASN-DUP-001",
        "supplier": "Test",
        "lines": [{"sku_id": skus[0]["id"], "expected_qty": 1}],
    }
    r1 = client.post("/api/v1/receiving/asns", json=body, headers=auth_headers)
    assert r1.status_code == 201
    r2 = client.post("/api/v1/receiving/asns", json=body, headers=auth_headers)
    assert r2.status_code == 409


def test_create_order_duplicate_code_409(client, auth_headers):
    skus = client.get("/api/v1/inventory/skus", headers=auth_headers).json()
    assert skus
    body = {
        "order_code": "SO-DUP-001",
        "customer": "Test",
        "lines": [{"sku_id": skus[0]["id"], "qty_ordered": 1}],
    }
    r1 = client.post("/api/v1/shipping/orders", json=body, headers=auth_headers)
    assert r1.status_code == 201
    r2 = client.post("/api/v1/shipping/orders", json=body, headers=auth_headers)
    assert r2.status_code == 409

"""End-to-end workflow smoke: Receive → Store → Produce → Ship (SCO-130).

Exercises every module in sequence on a single in-memory DB:
 1. Receive an ASN → ingredient lots created (FLR-001 + SGR-001).
 2. Storage is implicit in receipt (the lots get a default location via
    putaway suggestion).
 3. Create a recipe for PROD-001 consuming FLR-001 + SGR-001.
 4. Create a work order, preflight (FIFO lot reservation), start, complete →
    child lot for PROD-001 with genealogy edges.
 5. Create a sales order for PROD-001 → pick FIFO → truck-load → packing slip.

Asserts:
 * Receipt creates two new ingredient lots (one per ASN line).
 * Production preflight returns 'reserved' (no shortages).
 * Complete writes a child Lot with the produced qty AND two LotGenealogy
   edges (one per ingredient reservation).
 * Ingredient lots are decremented by their reserved qty.
 * Shipment final qty matches ordered qty.
"""

from wms.models import Lot, LotGenealogy, Order, OrderLine, SKU, Shipment


def _add_product_sku_and_order(db_session):
    """Inject PROD-001 + a sales order for it. Returns (product_sku_id, order_id)."""
    prod = SKU(
        site_id="WHS-001",
        code="PROD-001",
        description="Finished product",
        uom="KG",
        unit_weight_kg=1.0,
        requires_qc=False,
    )
    db_session.add(prod)
    db_session.flush()

    order = Order(
        site_id="WHS-001",
        order_code="SO-PROD-001",
        customer="Test Customer",
        priority="normal",
        status="open",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(OrderLine(order_id=order.id, sku_id=prod.id, qty_ordered=10))

    # Add a second shipment for this order so we don't collide with the
    # seeded shipment used by other tests.
    db_session.add(
        Shipment(
            site_id="WHS-001",
            shipment_code="SHP-PROD-001",
            truck_id="TRK-202",
            truck_capacity_kg=20000.0,
        )
    )
    db_session.commit()
    return prod.id, order.id


def test_full_workflow_receive_store_produce_ship(client, auth_headers, seeded_db):
    db = seeded_db
    product_sku_id, prod_order_id = _add_product_sku_and_order(db)

    # ── 1. RECEIVE ──────────────────────────────────────────────────
    inbound = client.get("/api/v1/receiving/inbound", headers=auth_headers).json()
    assert len(inbound) == 1
    asn = inbound[0]

    r = client.post(
        "/api/v1/receiving/check-in",
        json={"asn_id": asn["id"], "dock_door": "D1"},
        headers=auth_headers,
    )
    assert r.status_code == 200

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

    # Sanity: lots persisted with expected qty.
    flr_lots_qty = sum(
        l.quantity for l in db.query(Lot).filter_by(site_id="WHS-001").all()
        if l.sku_id != product_sku_id and db.get(SKU, l.sku_id).code == "FLR-001"
    )
    sgr_lots_qty = sum(
        l.quantity for l in db.query(Lot).filter_by(site_id="WHS-001").all()
        if l.sku_id != product_sku_id and db.get(SKU, l.sku_id).code == "SGR-001"
    )
    # Seeded fixture pre-creates L-FLR-001 with qty=100. The receipt adds 200
    # FLR + 150 SGR. So FLR total = 300, SGR total = 150.
    assert flr_lots_qty == 300
    assert sgr_lots_qty == 150

    # ── 2. STORE is implicit in receive (lots already have site_id and
    #         are queryable by /inventory/lots). Verify the new lots
    #         show up. ────────────────────────────────────────────────
    lots = client.get("/api/v1/inventory/lots", headers=auth_headers).json()
    assert lots["total"] >= 2

    # ── 3. PRODUCE ──────────────────────────────────────────────────
    # Resolve SKU ids via the new /inventory/skus endpoint.
    skus = client.get("/api/v1/inventory/skus", headers=auth_headers).json()
    sku_by_code = {s["code"]: s["id"] for s in skus}
    assert {"FLR-001", "SGR-001", "PROD-001"} <= sku_by_code.keys()

    recipe = client.post(
        "/api/v1/production/recipes",
        json={
            "sku_id": sku_by_code["PROD-001"],
            "lines": [
                {"ingredient_sku_id": sku_by_code["FLR-001"], "qty_per_unit": 2.0, "uom": "KG"},
                {"ingredient_sku_id": sku_by_code["SGR-001"], "qty_per_unit": 1.0, "uom": "KG"},
            ],
        },
        headers=auth_headers,
    )
    assert recipe.status_code == 201, recipe.text
    recipe = recipe.json()
    assert recipe["version"] == 1

    wo = client.post(
        "/api/v1/production/work-orders",
        json={"recipe_id": recipe["id"], "target_qty": 10},
        headers=auth_headers,
    ).json()
    assert wo["status"] == "draft"

    pf = client.post(
        f"/api/v1/production/work-orders/{wo['id']}/preflight",
        headers=auth_headers,
    ).json()
    assert pf["status"] == "reserved", pf
    assert pf["shortages"] == []
    # 10 units * 2 KG flour = 20 KG; 10 * 1 KG sugar = 10 KG.
    total_reserved = sum(r["qty_reserved"] for r in pf["reservations"])
    assert total_reserved == 30

    started = client.post(
        f"/api/v1/production/work-orders/{wo['id']}/start", headers=auth_headers
    ).json()
    assert started["status"] == "running"

    completed = client.post(
        f"/api/v1/production/work-orders/{wo['id']}/complete",
        json={"actual_qty": 10, "output_lot_code": "LOT-PROD-001-RUN1"},
        headers=auth_headers,
    ).json()
    assert completed["status"] == "completed"

    # Child lot should exist with qty 10 of PROD-001.
    db.expire_all()
    child = (
        db.query(Lot)
        .filter_by(site_id="WHS-001", lot_code="LOT-PROD-001-RUN1")
        .one()
    )
    assert child.sku_id == sku_by_code["PROD-001"]
    assert child.quantity == 10

    # Genealogy edges: one per reservation (FLR + SGR).
    edges = db.query(LotGenealogy).filter_by(child_lot_id=child.id).all()
    assert len(edges) == 2
    assert sum(e.quantity_consumed for e in edges) == 30

    # Ingredient lots decremented. FLR: had 300 → consumed 20 → 280.
    # SGR: had 150 → consumed 10 → 140.
    flr_after = sum(
        l.quantity for l in db.query(Lot).all()
        if l.sku_id != product_sku_id and db.get(SKU, l.sku_id).code == "FLR-001"
    )
    sgr_after = sum(
        l.quantity for l in db.query(Lot).all()
        if l.sku_id != product_sku_id and db.get(SKU, l.sku_id).code == "SGR-001"
    )
    assert flr_after == 280
    assert sgr_after == 140

    # ── 4. SHIP ─────────────────────────────────────────────────────
    # Pick from the PROD-001 sales order we injected above.
    orders = client.get("/api/v1/shipping/orders", headers=auth_headers).json()
    prod_order = next(o for o in orders if o["order_code"] == "SO-PROD-001")
    line = prod_order["lines"][0]

    picks = client.post(
        "/api/v1/shipping/picks",
        json={
            "order_id": prod_order["id"],
            "order_line_id": line["id"],
            "qty": 10,
            "strategy": "FIFO",
        },
        headers=auth_headers,
    ).json()
    assert sum(p["qty_picked"] for p in picks) == 10

    # Truck-load against the PROD-001 shipment (id=2 since seeded shipment is id=1).
    prod_shipment = (
        db.query(Shipment).filter_by(shipment_code="SHP-PROD-001").one()
    )
    load = client.post(
        "/api/v1/shipping/truck-load",
        json={"shipment_id": prod_shipment.id, "order_id": prod_order["id"]},
        headers=auth_headers,
    ).json()
    assert load["over_budget"] is False
    assert load["loaded_kg"] > 0

    slip = client.get(
        f"/api/v1/shipping/packing-slip/{prod_order['id']}", headers=auth_headers
    ).json()
    assert slip["order_code"] == "SO-PROD-001"
    total_shipped = sum(l["qty"] for l in slip["lines"])
    assert total_shipped == 10

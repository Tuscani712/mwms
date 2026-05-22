"""Inventory module tests — SCO-49."""

from datetime import UTC, datetime, timedelta

import pytest

from wms.core.security import hash_password
from wms.models import SKU, AuditLog, Lot, Site, User
from wms.services import inventory as svc


@pytest.fixture(autouse=True)
def _clear_kpi_cache():
    svc._cache_clear()
    yield
    svc._cache_clear()


def _today():
    return datetime.now(UTC).date()


# ── /lots search ────────────────────────────────────────────────────────────


def test_lots_default_returns_seeded_lot(client, auth_headers):
    r = client.get("/api/v1/inventory/lots", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["lot_code"] == "L-FLR-001"
    assert body["items"][0]["aging_bucket"] == "0-30"


def test_lots_filter_by_sku(client, auth_headers):
    r = client.get("/api/v1/inventory/lots?sku_code=FLR-001", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.get("/api/v1/inventory/lots?sku_code=SGR-001", headers=auth_headers)
    assert r.json()["total"] == 0


def test_lots_qa_hold_filter(client, auth_headers, seeded_db):
    # Flip the seeded lot to qa_hold
    lot = seeded_db.query(Lot).first()
    lot.qa_hold = True
    seeded_db.commit()

    r = client.get("/api/v1/inventory/lots?qa_hold=true", headers=auth_headers)
    assert r.json()["total"] == 1

    r = client.get("/api/v1/inventory/lots?qa_hold=false", headers=auth_headers)
    assert r.json()["total"] == 0


def test_lots_expiring_within(client, auth_headers, seeded_db):
    lot = seeded_db.query(Lot).first()
    lot.expires_at = _today() + timedelta(days=3)
    seeded_db.commit()

    r = client.get("/api/v1/inventory/lots?expiring_within_days=7", headers=auth_headers)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["expiring_soon"] is True

    r = client.get("/api/v1/inventory/lots?expiring_within_days=1", headers=auth_headers)
    assert r.json()["total"] == 0


def test_lots_search_q_is_like_injection_safe(client, auth_headers):
    # Wildcard chars should not broaden the match
    r = client.get("/api/v1/inventory/lots?q=%25", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_lots_limit_clamp(client, auth_headers):
    r = client.get(
        f"/api/v1/inventory/lots?limit={svc.SEARCH_LIMIT_MAX + 500}", headers=auth_headers
    )
    # FastAPI validates against the ge/le bounds → 422
    assert r.status_code == 422


def test_lots_aging_bucket(client, auth_headers, seeded_db):
    lot = seeded_db.query(Lot).first()
    lot.received_at = datetime.now(UTC) - timedelta(days=45)
    seeded_db.commit()
    r = client.get("/api/v1/inventory/lots?aging_bucket=31-60", headers=auth_headers)
    assert r.json()["total"] == 1


# ── /sku/{code} ─────────────────────────────────────────────────────────────


def test_sku_detail_excludes_qa_hold_and_expired(client, auth_headers, seeded_db):
    # Add another lot for the same SKU that is qa_held, and a third that is expired
    sku = seeded_db.query(SKU).filter(SKU.code == "FLR-001").one()
    seeded_db.add(
        Lot(
            site_id="WHS-001",
            lot_code="L-FLR-HOLD",
            sku_id=sku.id,
            quantity=40,
            qa_hold=True,
        )
    )
    seeded_db.add(
        Lot(
            site_id="WHS-001",
            lot_code="L-FLR-EXPIRED",
            sku_id=sku.id,
            quantity=25,
            expires_at=_today() - timedelta(days=1),
        )
    )
    seeded_db.commit()

    r = client.get("/api/v1/inventory/sku/FLR-001", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["on_hand_total"] == 100 + 40 + 25
    assert body["available"] == 100  # only the original lot
    assert body["qa_hold_qty"] == 40
    assert body["expired_qty"] == 25
    assert body["lot_count"] == 3


def test_sku_detail_not_found(client, auth_headers):
    r = client.get("/api/v1/inventory/sku/DOES-NOT-EXIST", headers=auth_headers)
    assert r.status_code == 404


# ── /kpis ───────────────────────────────────────────────────────────────────


def test_kpis_shape_and_cache(client, auth_headers, seeded_db):
    r = client.get("/api/v1/inventory/kpis", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_on_hand"] == 100
    assert body["available"] == 100
    assert body["qa_hold_qty"] == 0
    first_ts = body["cached_at"]

    # Mutate underlying data but expect cache hit (no refresh)
    lot = seeded_db.query(Lot).first()
    lot.quantity = 500
    seeded_db.commit()

    body2 = client.get("/api/v1/inventory/kpis", headers=auth_headers).json()
    assert body2["total_on_hand"] == 100  # cache served
    assert body2["cached_at"] == first_ts

    # refresh=1 bypasses cache
    body3 = client.get("/api/v1/inventory/kpis?refresh=true", headers=auth_headers).json()
    assert body3["total_on_hand"] == 500
    assert body3["cached_at"] != first_ts


def test_kpis_zeros_on_empty_site(client, auth_headers, seeded_db):
    seeded_db.query(Lot).delete()
    seeded_db.commit()
    body = client.get("/api/v1/inventory/kpis", headers=auth_headers).json()
    assert body["total_on_hand"] == 0
    assert body["available"] == 0


# ── /adjust ─────────────────────────────────────────────────────────────────


def test_adjust_requires_level_3(client, auth_headers):
    # Default seeded user is permission_level=1
    r = client.post(
        "/api/v1/inventory/adjust",
        json={"lot_id": 1, "delta": -5, "reason": "spillage"},
        headers=auth_headers,
    )
    assert r.status_code == 403


def _login_lvl(client, seeded_db, *, level: int, code_suffix: str) -> dict:
    code = f"WHS-001-{code_suffix}"
    seeded_db.add(
        User(
            site_id="WHS-001",
            employee_code=code,
            email=f"{code_suffix}@wms.local",
            full_name=f"Lvl{level}",
            role="manager",
            permission_level=level,
            hashed_password=hash_password("password123"),
        )
    )
    seeded_db.commit()
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": "password123", "site_id": "WHS-001"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_adjust_lvl3_decrement(client, seeded_db):
    headers = _login_lvl(client, seeded_db, level=3, code_suffix="003")
    r = client.post(
        "/api/v1/inventory/adjust",
        json={"lot_id": 1, "delta": -10, "reason": "shrink"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["was"] == 100
    assert body["now"] == 90
    # audit row written
    audit = (
        seeded_db.query(AuditLog).filter(AuditLog.event_type == "inventory.adjusted").all()
    )
    assert len(audit) == 1


def test_adjust_below_zero_rejected(client, seeded_db):
    headers = _login_lvl(client, seeded_db, level=3, code_suffix="003")
    r = client.post(
        "/api/v1/inventory/adjust",
        json={"lot_id": 1, "delta": -500, "reason": "miscount"},
        headers=headers,
    )
    assert r.status_code == 400


def test_adjust_large_delta_requires_lvl4(client, seeded_db):
    headers = _login_lvl(client, seeded_db, level=3, code_suffix="003")
    r = client.post(
        "/api/v1/inventory/adjust",
        json={"lot_id": 1, "delta": 1000, "reason": "found pallet"},
        headers=headers,
    )
    assert r.status_code == 403

    headers4 = _login_lvl(client, seeded_db, level=4, code_suffix="004")
    r = client.post(
        "/api/v1/inventory/adjust",
        json={"lot_id": 1, "delta": 1000, "reason": "found pallet"},
        headers=headers4,
    )
    assert r.status_code == 200
    assert r.json()["now"] == 1100


def test_adjust_multi_site_isolation(client, seeded_db):
    # Create a second site + lot belonging to it; existing user (WHS-001) cannot touch it
    seeded_db.add(Site(id="WHS-002", name="Other", city="Phoenix"))
    seeded_db.commit()
    seeded_db.add(
        Lot(site_id="WHS-002", lot_code="L-OTHER", sku_id=1, quantity=50)
    )
    seeded_db.commit()
    other_lot = (
        seeded_db.query(Lot).filter(Lot.lot_code == "L-OTHER").one()
    )
    headers = _login_lvl(client, seeded_db, level=3, code_suffix="003")
    r = client.post(
        "/api/v1/inventory/adjust",
        json={"lot_id": other_lot.id, "delta": -1, "reason": "x"},
        headers=headers,
    )
    assert r.status_code == 404


# ── /below-safety-stock ─────────────────────────────────────────────────────


def test_below_safety_stock(client, auth_headers, seeded_db):
    sku = seeded_db.query(SKU).filter(SKU.code == "FLR-001").one()
    sku.safety_stock = 200  # available = 100, breach by 100
    sku.reorder_point = 150
    seeded_db.commit()

    r = client.get("/api/v1/inventory/below-safety-stock", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["sku_code"] == "FLR-001"
    assert rows[0]["shortfall"] == 100


def test_below_safety_stock_excludes_qa_hold(client, auth_headers, seeded_db):
    sku = seeded_db.query(SKU).filter(SKU.code == "FLR-001").one()
    sku.safety_stock = 50
    seeded_db.commit()
    # Currently available=100, safety=50 → not breached
    rows = client.get("/api/v1/inventory/below-safety-stock", headers=auth_headers).json()
    assert rows == []

    # Flip the lot to qa_hold → available drops to 0 → breach
    lot = seeded_db.query(Lot).first()
    lot.qa_hold = True
    seeded_db.commit()
    rows = client.get("/api/v1/inventory/below-safety-stock", headers=auth_headers).json()
    assert len(rows) == 1


# ── /skus search + on_hand aggregation ──────────────────────────────────────


def test_skus_returns_on_hand_qty_summed_across_lots(client, auth_headers, seeded_db):
    # Seeded fixture: FLR-001 with one lot qty=100 (no QA hold).
    rows = client.get("/api/v1/inventory/skus", headers=auth_headers).json()
    flr = next(s for s in rows if s["code"] == "FLR-001")
    assert flr["on_hand_qty"] == 100
    # SGR-001 has no lots in the seeded fixture.
    sgr = next(s for s in rows if s["code"] == "SGR-001")
    assert sgr["on_hand_qty"] == 0


def test_skus_on_hand_excludes_qa_hold_lots(client, auth_headers, seeded_db):
    lot = seeded_db.query(Lot).first()
    lot.qa_hold = True
    seeded_db.commit()
    rows = client.get("/api/v1/inventory/skus", headers=auth_headers).json()
    flr = next(s for s in rows if s["code"] == "FLR-001")
    assert flr["on_hand_qty"] == 0


def test_skus_q_matches_code_or_description(client, auth_headers):
    # Match by code substring (case-insensitive).
    rows = client.get("/api/v1/inventory/skus?q=flr", headers=auth_headers).json()
    assert [s["code"] for s in rows] == ["FLR-001"]
    # Match by description substring.
    rows = client.get("/api/v1/inventory/skus?q=Sugar", headers=auth_headers).json()
    assert [s["code"] for s in rows] == ["SGR-001"]
    # No match → empty list, not 404.
    rows = client.get("/api/v1/inventory/skus?q=zzzz", headers=auth_headers).json()
    assert rows == []


def test_skus_q_is_like_injection_safe(client, auth_headers):
    # Wildcards in user input must be treated literally, not as SQL LIKE wildcards.
    r = client.get("/api/v1/inventory/skus?q=%25", headers=auth_headers)
    assert r.status_code == 200
    # The literal "%" should match nothing — no SKU codes contain it.
    assert r.json() == []


def test_skus_limit_clamps_to_max(client, auth_headers):
    # limit > 1000 must be rejected (422 from query validator).
    r = client.get("/api/v1/inventory/skus?limit=5000", headers=auth_headers)
    assert r.status_code == 422

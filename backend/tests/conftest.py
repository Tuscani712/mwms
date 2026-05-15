"""Shared pytest fixtures — in-memory SQLite per test for full isolation."""

import os

os.environ["WMS_DB_URL"] = "sqlite:///:memory:"
os.environ["WMS_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from wms.core.deps import get_session  # noqa: E402
from wms.core.security import hash_password  # noqa: E402
from wms.db.base import Base  # noqa: E402
from wms.db.session import get_db  # noqa: E402
from wms.main import app  # noqa: E402
from wms.models import (  # noqa: E402
    ASN,
    SKU,
    ASNLine,
    Location,
    Lot,
    Order,
    OrderLine,
    Shipment,
    Site,
    User,
)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    session_factory = sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False, future=True
    )
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_db(db_session):
    """Minimal seed: 1 site, 1 user, 2 SKUs, 1 location, 1 lot, 1 ASN, 1 order."""
    site = Site(id="WHS-001", name="Test Dallas", city="Dallas", is_master=False, is_online=True)
    db_session.add(site)
    db_session.flush()

    user = User(
        site_id="WHS-001",
        employee_code="WHS-001-001",
        email="op1@wms.local",
        full_name="Test Operator",
        role="operator",
        permission_level=1,
        hashed_password=hash_password("password123"),
    )
    db_session.add(user)

    sku1 = SKU(site_id="WHS-001", code="FLR-001", description="Flour", uom="KG", unit_weight_kg=25.0)
    sku2 = SKU(site_id="WHS-001", code="SGR-001", description="Sugar", uom="KG", unit_weight_kg=25.0)
    db_session.add_all([sku1, sku2])
    db_session.flush()

    loc = Location(site_id="WHS-001", code="A-01", capacity=500)
    overflow = Location(site_id="WHS-001", code="OVR-01", capacity=200, is_overflow=True)
    db_session.add_all([loc, overflow])
    db_session.flush()

    lot = Lot(site_id="WHS-001", lot_code="L-FLR-001", sku_id=sku1.id, location_id=loc.id, quantity=100)
    db_session.add(lot)

    asn = ASN(site_id="WHS-001", asn_code="ASN-TEST-001", supplier="Cascade Mills", status="scheduled")
    db_session.add(asn)
    db_session.flush()
    db_session.add(ASNLine(asn_id=asn.id, sku_id=sku1.id, expected_qty=200))
    db_session.add(ASNLine(asn_id=asn.id, sku_id=sku2.id, expected_qty=150))

    order = Order(
        site_id="WHS-001",
        order_code="SO-TEST-001",
        customer="Heartland Grocers",
        priority="normal",
        status="open",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(OrderLine(order_id=order.id, sku_id=sku1.id, qty_ordered=50))

    shipment = Shipment(
        site_id="WHS-001",
        shipment_code="SHP-TEST-001",
        truck_id="TRK-101",
        truck_capacity_kg=20000.0,
    )
    db_session.add(shipment)

    db_session.commit()
    return db_session


@pytest.fixture
def client(seeded_db):
    def _override():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_token(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-001"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}

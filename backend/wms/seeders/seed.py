"""Idempotent mock data seeder. Drops + recreates tables, then populates.

Run: python -m wms.seeders.seed
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from wms.core.security import hash_password
from wms.db.base import Base
from wms.db.session import SessionLocal, engine
from wms.models import (
    ASN,
    SKU,
    ASNLine,
    Location,
    Lot,
    Order,
    OrderLine,
    QCHold,
    Shipment,
    Site,
    User,
    UserProfileField,
)

random.seed(42)

# ── SITES ──────────────────────────────────────────────────────────
SITES = [
    {"id": "MCS", "name": "Master Control · Corporate", "city": "Austin, TX", "is_master": True, "is_online": True},
    {"id": "WHS-001", "name": "Dallas Distribution", "city": "Dallas, TX", "is_master": False, "is_online": True},
    {"id": "WHS-002", "name": "Houston Plant", "city": "Houston, TX", "is_master": False, "is_online": True},
    {"id": "WHS-003", "name": "LA Cold Storage", "city": "Los Angeles, CA", "is_master": False, "is_online": True},
    {"id": "WHS-004", "name": "NYC Reverse Logistics", "city": "New York, NY", "is_master": False, "is_online": False},
]

ROLES = [
    ("operator", 1, 20),
    ("lead", 2, 8),
    ("supervisor", 3, 4),
    ("manager", 4, 2),
    ("admin", 5, 1),
]

SUPPLIERS = [
    "Cascade Mills",
    "Northwind Logistics",
    "Pacific Foods Co.",
    "Atlas Packaging",
    "Sunridge Farms",
    "Veridian Pharma",
    "BlueOcean Distributors",
]

CUSTOMERS = [
    "Heartland Grocers",
    "Metro Wholesale",
    "Coastline Retail",
    "Summit Stores",
    "GoldenHarvest Markets",
    "Brightway Foods",
    "Halcyon Distributors",
]

SKU_TEMPLATES = [
    ("FLR", "Flour, all-purpose", "KG", 25.0, True, 365),
    ("SGR", "Sugar, granulated", "KG", 25.0, False, 730),
    ("OIL", "Oil, canola", "L", 18.0, True, 540),
    ("YST", "Yeast, active dry", "KG", 1.0, True, 365),
    ("SLT", "Salt, fine", "KG", 25.0, False, 1825),
    ("BTR", "Butter, unsalted", "KG", 0.5, True, 90),
    ("EGG", "Eggs, grade A", "DZ", 0.7, True, 30),
    ("MLK", "Milk, whole", "L", 1.0, True, 14),
    ("CHO", "Chocolate chips", "KG", 5.0, False, 365),
    ("VAN", "Vanilla extract", "L", 1.0, False, 1095),
    ("BAG", "Packaging bag, 1kg", "EA", 0.02, False, None),
    ("BOX", "Shipping box, M", "EA", 0.15, False, None),
]


def _now() -> datetime:
    return datetime.now(UTC)


def reset_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_sites(db: Session) -> None:
    for s in SITES:
        db.add(Site(**s, timezone="America/Chicago", build_version="v0.1.0"))
    db.commit()


DEPARTMENTS = {
    "operator": ["Receiving", "Shipping", "Production", "Quality", "Inventory"],
    "lead": ["Receiving", "Shipping", "Production", "Quality"],
    "supervisor": ["Operations", "Quality"],
    "manager": ["Operations"],
    "admin": ["Administration"],
}
SHIFTS = ["A · 06:00-14:00", "B · 14:00-22:00", "C · 22:00-06:00"]


def seed_users(db: Session) -> None:
    for site in db.query(Site).all():
        if site.id == "MCS":
            db.add(
                User(
                    site_id=site.id,
                    employee_code="MCS-ADMIN",
                    email="admin@mcs.wms",
                    full_name="Corporate Admin",
                    role="admin",
                    permission_level=5,
                    department="Administration",
                    shift="A · 06:00-14:00",
                    hashed_password=hash_password("admin1234"),
                )
            )
            continue
        idx = 1
        for role, level, count in ROLES:
            for _ in range(count):
                code = f"{site.id}-{idx:03d}"
                db.add(
                    User(
                        site_id=site.id,
                        employee_code=code,
                        email=f"{code.lower()}@wms.local",
                        full_name=f"{role.title()} {idx}",
                        role=role,
                        permission_level=level,
                        department=random.choice(DEPARTMENTS[role]),
                        shift=random.choice(SHIFTS),
                        hashed_password=hash_password("password123"),
                    )
                )
                idx += 1
    db.commit()


def seed_profile_field_policy(db: Session) -> None:
    """Baseline field visibility rules. Defaults allow everything; explicit rows override."""
    # Global: theme is visible but not editable (Coming Soon)
    db.add(UserProfileField(scope_type="global", scope_value=None, field_name="theme",
                            visible=True, editable=False))
    # Example role override: operators can't change their email (must go through supervisor)
    db.add(UserProfileField(scope_type="role", scope_value="operator", field_name="email",
                            visible=True, editable=False))
    db.commit()


def seed_skus_locations(db: Session) -> None:
    for site in db.query(Site).filter(Site.is_master.is_(False)).all():
        for _i, (code, desc, uom, weight, qc, shelf) in enumerate(SKU_TEMPLATES):
            db.add(
                SKU(
                    site_id=site.id,
                    code=f"{code}-{site.id[-3:]}",
                    description=desc,
                    uom=uom,
                    unit_weight_kg=weight,
                    requires_qc=qc,
                    shelf_life_days=shelf,
                    reorder_point=random.randint(50, 200),
                    safety_stock=random.randint(20, 80),
                )
            )
        # Add a wide SKU spread per site (~20 extra SKUs)
        for i in range(20):
            db.add(
                SKU(
                    site_id=site.id,
                    code=f"GEN-{site.id[-3:]}-{i:03d}",
                    description=f"Generic item {i}",
                    uom="EA",
                    unit_weight_kg=round(random.uniform(0.1, 5.0), 2),
                    requires_qc=random.random() < 0.3,
                    shelf_life_days=random.choice([None, 180, 365, 540]),
                    reorder_point=random.randint(20, 100),
                    safety_stock=random.randint(10, 50),
                )
            )

        # Locations: primary aisle + overflow + QA hold
        for aisle in ["A", "B", "C"]:
            for slot in range(1, 9):
                db.add(
                    Location(
                        site_id=site.id,
                        code=f"{aisle}-{slot:02d}",
                        zone="MAIN",
                        capacity=500,
                    )
                )
        for i in range(1, 5):
            db.add(
                Location(
                    site_id=site.id, code=f"OVR-{i:02d}", zone="OVERFLOW", capacity=300, is_overflow=True
                )
            )
        db.add(Location(site_id=site.id, code="QA-HOLD", zone="QUARANTINE", capacity=200, is_qa_hold=True))
    db.commit()


def seed_lots(db: Session) -> None:
    for site in db.query(Site).filter(Site.is_master.is_(False)).all():
        skus = db.query(SKU).filter(SKU.site_id == site.id).all()
        locations = db.query(Location).filter(Location.site_id == site.id, Location.is_qa_hold.is_(False)).all()
        for sku in skus:
            n_lots = random.randint(2, 6)
            for j in range(n_lots):
                received = _now() - timedelta(days=random.randint(0, 60))
                expires = None
                if sku.shelf_life_days:
                    expires = (received + timedelta(days=sku.shelf_life_days)).date()
                db.add(
                    Lot(
                        site_id=site.id,
                        lot_code=f"L-{sku.code}-{j:03d}",
                        sku_id=sku.id,
                        location_id=random.choice(locations).id,
                        quantity=random.randint(50, 400),
                        qa_hold=random.random() < 0.05,
                        received_at=received,
                        expires_at=expires,
                        supplier=random.choice(SUPPLIERS),
                    )
                )
    db.commit()


def seed_asns(db: Session) -> None:
    for site in db.query(Site).filter(Site.is_master.is_(False)).all():
        skus = db.query(SKU).filter(SKU.site_id == site.id).all()
        for i in range(12):
            status = random.choice(["scheduled", "arrived", "receiving", "received"])
            eta = _now() + timedelta(hours=random.randint(-6, 24))
            asn = ASN(
                site_id=site.id,
                asn_code=f"ASN-{site.id[-3:]}-{i+1:04d}",
                supplier=random.choice(SUPPLIERS),
                dock_door=f"D{random.randint(1, 4)}" if status != "scheduled" else None,
                status=status,
                eta=eta,
                arrived_at=eta - timedelta(minutes=5) if status != "scheduled" else None,
                received_at=_now() if status == "received" else None,
            )
            db.add(asn)
            db.flush()
            for sku in random.sample(skus, k=min(4, len(skus))):
                db.add(
                    ASNLine(
                        asn_id=asn.id,
                        sku_id=sku.id,
                        expected_qty=random.randint(50, 300),
                        received_qty=random.randint(50, 300) if status == "received" else 0,
                        qc_status="passed" if status == "received" else "pending",
                    )
                )
    db.commit()


def seed_orders(db: Session) -> None:
    for site in db.query(Site).filter(Site.is_master.is_(False)).all():
        skus = db.query(SKU).filter(SKU.site_id == site.id).all()
        for i in range(15):
            status = random.choice(["open", "open", "picking", "picked", "loaded"])
            order = Order(
                site_id=site.id,
                order_code=f"SO-{site.id[-3:]}-{i+1:05d}",
                customer=random.choice(CUSTOMERS),
                priority=random.choice(["normal", "normal", "rush"]),
                status=status,
                ship_by=date.today() + timedelta(days=random.randint(0, 7)),
            )
            db.add(order)
            db.flush()
            for sku in random.sample(skus, k=min(3, len(skus))):
                ordered = random.randint(20, 100)
                db.add(
                    OrderLine(
                        order_id=order.id,
                        sku_id=sku.id,
                        qty_ordered=ordered,
                        qty_picked=ordered if status in {"picked", "loaded"} else 0,
                        fefo_required=sku.shelf_life_days is not None and sku.shelf_life_days < 90,
                    )
                )
    db.commit()


def seed_shipments(db: Session) -> None:
    for site in db.query(Site).filter(Site.is_master.is_(False)).all():
        for i in range(3):
            db.add(
                Shipment(
                    site_id=site.id,
                    shipment_code=f"SHP-{site.id[-3:]}-{i+1:04d}",
                    truck_id=f"TRK-{random.randint(100, 999)}",
                    truck_capacity_kg=20000.0,
                    loaded_weight_kg=random.uniform(0, 15000),
                    status=random.choice(["staging", "loading", "ready"]),
                )
            )
    db.commit()


def seed_qc_holds(db: Session) -> None:
    for site in db.query(Site).filter(Site.is_master.is_(False)).all():
        lots = db.query(Lot).filter(Lot.site_id == site.id, Lot.qa_hold.is_(True)).all()
        for lot in lots[:6]:
            db.add(
                QCHold(
                    site_id=site.id,
                    lot_id=lot.id,
                    reason=random.choice(
                        [
                            "Visible contamination on outer packaging",
                            "Temperature excursion during transit",
                            "Supplier C-of-A pending",
                            "Damaged units exceed 2% threshold",
                        ]
                    ),
                    severity=random.choice(["low", "medium", "high"]),
                )
            )
    db.commit()


def run() -> None:
    reset_schema()
    db = SessionLocal()
    try:
        seed_sites(db)
        seed_users(db)
        seed_profile_field_policy(db)
        seed_skus_locations(db)
        seed_lots(db)
        seed_asns(db)
        seed_orders(db)
        seed_shipments(db)
        seed_qc_holds(db)

        users_count = db.query(User).count()
        skus_count = db.query(SKU).count()
        lots_count = db.query(Lot).count()
        asns_count = db.query(ASN).count()
        orders_count = db.query(Order).count()
        print(
            f"✓ Seed complete · {users_count} users · {skus_count} SKUs · "
            f"{lots_count} lots · {asns_count} ASNs · {orders_count} orders"
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()

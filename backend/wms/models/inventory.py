"""Inventory models: SKU, Lot, Location, LotGenealogy."""

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from wms.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SKU(Base):
    __tablename__ = "skus"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(180), nullable=False)
    # SCO-143: `uom` is the BASE unit — smallest discrete consumable unit
    # (e.g., LB for garlic, EA for buns). Recipes + inventory + reservations
    # all denominate in this unit. `purchase_uom` is what the SKU is bought
    # in (BAG, PACK, CASE); blank/equal-to-uom means "purchased as base."
    # `base_per_purchase_unit` is the conversion factor — e.g., a 50 lb bag
    # of garlic has base=LB, purchase=BAG, base_per_purchase=50.0.
    uom: Mapped[str] = mapped_column(String(10), default="EA")
    purchase_uom: Mapped[str] = mapped_column(String(10), default="")
    base_per_purchase_unit: Mapped[float] = mapped_column(Float, default=1.0)
    unit_weight_kg: Mapped[float] = mapped_column(Float, default=1.0)
    requires_qc: Mapped[bool] = mapped_column(Boolean, default=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SCO-143: reorder/safety thresholds are in base UoM, so decimal.
    reorder_point: Mapped[float] = mapped_column(Float, default=0.0)
    safety_stock: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    zone: Mapped[str] = mapped_column(String(20), default="MAIN")
    capacity: Mapped[int] = mapped_column(default=100)
    is_overflow: Mapped[bool] = mapped_column(Boolean, default=False)
    is_qa_hold: Mapped[bool] = mapped_column(Boolean, default=False)


class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    lot_code: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    # SCO-143: quantity is always in the SKU's base UoM (e.g., LB, EA).
    # Float instead of Int so partial consumption (1 lb out of a 50-lb bag,
    # 0.25 cup of yeast) is representable. Stored as REAL in SQLite, DOUBLE
    # in Postgres. Migration to Numeric(12, 3) on Postgres cutover noted in
    # the commit message — _ensure_columns only handles ADD, not ALTER.
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    qa_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(120), nullable=True)


class LotGenealogy(Base):
    __tablename__ = "lot_genealogy"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), nullable=False)
    child_lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), nullable=False)
    # SCO-143: decimal-capable so genealogy walks reconstruct exact qtys.
    quantity_consumed: Mapped[float] = mapped_column(Float, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

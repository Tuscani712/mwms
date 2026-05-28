"""Operational models: ASN, Receipt, Order, Shipment, Pick, QCHold."""

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wms.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── INBOUND ────────────────────────────────────────────────────────


class ASN(Base):
    __tablename__ = "asns"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    asn_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    supplier: Mapped[str] = mapped_column(String(120), nullable=False)
    dock_door: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    eta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    lines: Mapped[list["ASNLine"]] = relationship(back_populates="asn", cascade="all, delete-orphan")


class ASNLine(Base):
    __tablename__ = "asn_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    asn_id: Mapped[int] = mapped_column(ForeignKey("asns.id"), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    # SCO-143: expected/received quantities are in the SKU's PURCHASE UoM
    # (the truck-driver-facing unit — bags, packs, cases). Service-side
    # multiplies by sku.base_per_purchase_unit to derive Lot.quantity in
    # base UoM at receipt time.
    expected_qty: Mapped[float] = mapped_column(Float, default=0.0)
    received_qty: Mapped[float] = mapped_column(Float, default=0.0)
    qc_status: Mapped[str] = mapped_column(String(20), default="pending")

    asn: Mapped[ASN] = relationship(back_populates="lines")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    asn_id: Mapped[int] = mapped_column(ForeignKey("asns.id"), nullable=False)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    variance_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ReceiptLine(Base):
    __tablename__ = "receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), nullable=False)
    asn_line_id: Mapped[int] = mapped_column(ForeignKey("asn_lines.id"), nullable=False)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), nullable=True)
    # SCO-143: qty_received is in PURCHASE UoM (mirrors ASNLine.expected_qty).
    # Lot.quantity is the base-unit derivative computed in the service.
    qty_received: Mapped[float] = mapped_column(Float, default=0.0)
    qty_variance: Mapped[float] = mapped_column(Float, default=0.0)
    qc_passed: Mapped[bool] = mapped_column(Boolean, default=True)


# ── OUTBOUND ───────────────────────────────────────────────────────


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    order_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    customer: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="open")
    ship_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    truck_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    picks: Mapped[list["Pick"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    # SCO-143: order/pick quantities in base UoM, decimal-capable.
    qty_ordered: Mapped[float] = mapped_column(Float, default=0.0)
    qty_picked: Mapped[float] = mapped_column(Float, default=0.0)
    fefo_required: Mapped[bool] = mapped_column(Boolean, default=False)

    order: Mapped[Order] = relationship(back_populates="lines")


class Pick(Base):
    __tablename__ = "picks"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), nullable=False)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), nullable=False)
    # SCO-143: qty in base UoM.
    qty_picked: Mapped[float] = mapped_column(Float, default=0.0)
    picker_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    picked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    strategy: Mapped[str] = mapped_column(String(10), default="FIFO")

    order: Mapped[Order] = relationship(back_populates="picks")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    shipment_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    truck_id: Mapped[str] = mapped_column(String(20), nullable=False)
    truck_capacity_kg: Mapped[float] = mapped_column(Float, default=20000.0)
    loaded_weight_kg: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="staging")
    departed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── QUALITY ────────────────────────────────────────────────────────


class QCHold(Base):
    __tablename__ = "qc_holds"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opened_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

"""Production models — recipes, recipe lines, work orders, reservations.

SCO-51 (MVP).
Reuses existing wms.models.inventory.LotGenealogy for parent→child edges
written by complete_work_order().

MVP scope notes (each TODO is intentionally left here for future iteration):
  - `version` column on recipes is present but version-bump-on-edit is NOT
    implemented in the MVP service. PUT /recipes/{id} currently performs an
    in-place edit. When versioning is wired, edits must INSERT a new row
    (same sku_id, version+1, locked_by=editor) and running WOs keep their
    `recipe_version_snapshot` so old versions stay queryable.
  - Atomic reservation: MVP uses sequential SELECT-then-INSERT inside one
    SQLAlchemy transaction. Future: SQLite `BEGIN IMMEDIATE` / Postgres
    `SELECT ... FOR UPDATE` so two concurrent preflights on the same scarce
    lot serialize instead of double-allocating.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from wms.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    locked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RecipeLine(Base):
    __tablename__ = "recipe_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), index=True, nullable=False)
    ingredient_sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), nullable=False)
    qty_per_unit: Mapped[float] = mapped_column(default=1.0, nullable=False)
    uom: Mapped[str] = mapped_column(String(10), default="EA")


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), index=True, nullable=False)
    # Snapshot of the recipe version at WO creation. When versioning lands,
    # this field is what protects a running WO from a mid-flight recipe edit.
    recipe_version_snapshot: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    target_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    # State machine: draft → reserved → running → completed.
    # `cancel` is the only exit from reserved/running short of completed.
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class WorkOrderReservation(Base):
    __tablename__ = "work_order_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), index=True, nullable=False)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), index=True, nullable=False)
    qty_reserved: Mapped[int] = mapped_column(Integer, nullable=False)

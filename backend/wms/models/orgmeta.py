"""Org-metadata: Role, Department, Shift.

Promotes the free-string User.role / department / shift fields to first-class
entities so admins can curate the picker lists during user creation.

Design (SCO-76):
- Role.site_id is NULLABLE: NULL = global template (operator/lead/...), non-NULL
  = site-specific role. User-create pre-fills User.permission_level from
  Role.default_permission_level; the admin can override (interim leadership).
- Department + Shift are per-site (site_id NOT NULL). "Department" is WHERE
  within a site the user works; "Shift" is when. Per-site because timezones
  and operational hours differ.
- User.role_id / department_id / shift_id are nullable soft FKs alongside the
  existing string columns. Backfill is a later one-shot migration.
"""

from datetime import UTC, datetime, time

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from wms.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_roles_site_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    default_permission_level: Mapped[int] = mapped_column(nullable=False, default=1)
    site_id: Mapped[str | None] = mapped_column(
        ForeignKey("sites.id"), index=True, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_departments_site_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Title(Base):
    """Curated job title (SCO-100).

    Distinct from Role (which carries permission_level + drives RBAC). Title is
    purely descriptive ("Plant Supervisor", "Forklift Operator") and feeds the
    user-creation dropdown. site_id is NULLABLE: NULL = global / cross-site
    title template; non-NULL = site-specific. User.title_id points here for the
    curated path; User.custom_title holds the free-text override when the admin
    selects "Custom..." instead.
    """

    __tablename__ = "titles"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_titles_site_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    site_id: Mapped[str | None] = mapped_column(
        ForeignKey("sites.id"), index=True, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_shifts_site_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

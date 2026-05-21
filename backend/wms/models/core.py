"""Core models: Site, User. Multi-site scoping is the foundation everything else builds on."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wms.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    timezone: Mapped[str] = mapped_column(String(40), default="America/Chicago")
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    build_version: Mapped[str] = mapped_column(String(20), default="v0.1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="site")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True, nullable=False)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="operator")
    permission_level: Mapped[int] = mapped_column(default=1)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # SCO-99: forces a password change on next login. Admin-created accounts
    # land with this true (one-time temp password); cleared when the user
    # rotates via PUT /profile/password.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Profile fields
    department: Mapped[str | None] = mapped_column(String(60), nullable=True)
    shift: Mapped[str | None] = mapped_column(String(20), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    display_picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    theme: Mapped[str] = mapped_column(String(20), default="dark")

    # Soft FKs to org-metadata entities (SCO-76). Nullable alongside the legacy
    # string fields above; populated by new user-create flow, backfilled later.
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id"), index=True, nullable=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), index=True, nullable=True
    )
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("shifts.id"), index=True, nullable=True
    )
    # SCO-100: curated job title FK + free-text override. Mutually exclusive in
    # practice (UI sends one or the other); render precedence is custom_title
    # when present, else the joined Title.name.
    title_id: Mapped[int | None] = mapped_column(
        ForeignKey("titles.id"), index=True, nullable=True
    )
    custom_title: Mapped[str | None] = mapped_column(String(60), nullable=True)

    site: Mapped[Site] = relationship(back_populates="users")

    def __repr__(self) -> str:
        # SECURITY_AUDIT.md L-7: defensive — scrub hashed_password so an
        # accidental f"got {user}" in a log line cannot leak the bcrypt hash.
        return (
            f"<User id={self.id} code={self.employee_code!r} site={self.site_id!r} "
            f"level={self.permission_level} active={self.is_active}>"
        )


class UserProfileField(Base):
    """Field visibility/editability rules — resolves per (user, role, site, global)."""

    __tablename__ = "user_profile_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_value: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    field_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PasswordPolicy(Base):
    """Password complexity + MFA rules — resolved per (user, role, site, global)."""

    __tablename__ = "password_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_value: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    min_length: Mapped[int] = mapped_column(default=4)
    require_uppercase: Mapped[bool] = mapped_column(Boolean, default=False)
    require_lowercase: Mapped[bool] = mapped_column(Boolean, default=False)
    require_digit: Mapped[bool] = mapped_column(Boolean, default=False)
    require_special: Mapped[bool] = mapped_column(Boolean, default=False)
    require_mfa: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class UserMFA(Base):
    """Per-user TOTP enrollment + hashed backup codes."""

    __tablename__ = "user_mfa"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_codes_json: Mapped[str] = mapped_column(String(1200), default="[]")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class LoginAttempt(Base):
    """Audit trail for authentication attempts — feeds rate-limiting + lockout.

    SECURITY_AUDIT.md H-4: schema pre-staged so the rate-limit rollout in SEC-1
    doesn't require a second migration. Writes will be added with that ticket.
    """

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    site_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6-safe
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AuditLog(Base):
    """Security-relevant event trail — login, MFA changes, password changes, admin user ops.

    SECURITY_AUDIT.md L-1: schema + writer scaffolded so SEC-6 (full audit-log
    rollout, log shipping, alerting) doesn't need a second migration. No
    alerting or external sink yet — just the durable trail.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    site_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class ProfileChangeRequest(Base):
    """Pending approval for display_name / display_picture changes (Level 3+ or supervisor)."""

    __tablename__ = "profile_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_value: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

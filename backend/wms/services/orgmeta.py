"""Org-metadata CRUD + permission gating (SCO-79).

Permission model:
- Roles: site_id NULLABLE.
    * Global roles (site_id IS NULL): MCS admin (Lvl 4+) to manage.
    * Site-specific roles: own-site Lvl 3+ OR MCS Lvl 4+ for cross-site.
- Departments + Shifts: per-site (site_id NOT NULL).
    * Own-site Lvl 3+ OR MCS Lvl 4+ for cross-site.
- Read: any Lvl 3+ admin (own-site only); MCS Lvl 4+ for cross-site.
"""

from __future__ import annotations

from datetime import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wms.models import Department, Role, Shift, Site, Title, User

MCS_SITE_ID = "MCS"


class OrgMetaAuthorizationError(PermissionError):
    """Raised when caller lacks permission to manage role/department/shift/title."""


class OrgMetaInUseError(ValueError):
    """Raised on hard-delete attempt when references still exist.

    Carries `ref_count` so the API layer can surface it in the response payload
    and the UI can render "In use by N users" without a separate count call.
    """

    def __init__(self, entity: str, ref_count: int):
        self.entity = entity
        self.ref_count = ref_count
        super().__init__(
            f"{entity} is in use by {ref_count} user(s); deactivate instead"
        )


def _require_admin(caller: User) -> None:
    """Lvl 3+ at any site, or any MCS user."""
    if caller.permission_level >= 3 or caller.site_id == MCS_SITE_ID:
        return
    raise OrgMetaAuthorizationError("Level 3+ required for org-metadata management")


def _require_site_access(caller: User, target_site_id: str | None) -> None:
    """Caller must work at target_site_id, or be MCS Lvl 4+ for cross-site / global ops."""
    _require_admin(caller)
    if target_site_id is None:  # global role
        if caller.site_id != MCS_SITE_ID or caller.permission_level < 4:
            raise OrgMetaAuthorizationError(
                "Managing global roles requires MCS admin (Level 4+)"
            )
        return
    if caller.site_id == target_site_id:
        return
    if caller.site_id == MCS_SITE_ID and caller.permission_level >= 4:
        return
    raise OrgMetaAuthorizationError(
        f"Cross-site org-metadata management requires MCS admin (Level 4+); "
        f"caller site={caller.site_id}, target site={target_site_id}"
    )


def _site_exists(db: Session, site_id: str) -> None:
    if db.query(Site).filter(Site.id == site_id).one_or_none() is None:
        raise ValueError(f"Site '{site_id}' does not exist")


# ── Roles ─────────────────────────────────────────────────────────────────

def list_roles(db: Session, caller: User, *, site_id: str | None = None,
               include_globals: bool = True) -> list[Role]:
    _require_admin(caller)
    q = db.query(Role)
    if site_id is None:
        # Default: caller's own-site + globals; MCS sees everything.
        if caller.site_id == MCS_SITE_ID and caller.permission_level >= 4:
            pass  # all roles
        else:
            scope = [caller.site_id]
            if include_globals:
                q = q.filter((Role.site_id.in_(scope)) | (Role.site_id.is_(None)))
            else:
                q = q.filter(Role.site_id.in_(scope))
    else:
        _require_site_access(caller, site_id)
        q = q.filter(Role.site_id == site_id)
    return q.order_by(Role.site_id.is_(None).desc(), Role.name).all()


def create_role(db: Session, caller: User, *, name: str,
                default_permission_level: int, site_id: str | None) -> Role:
    _require_site_access(caller, site_id)
    if site_id is not None:
        _site_exists(db, site_id)
    if not 1 <= default_permission_level <= 5:
        raise ValueError("default_permission_level must be 1-5")
    role = Role(name=name, default_permission_level=default_permission_level, site_id=site_id)
    db.add(role)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError(f"Role '{name}' already exists for this scope") from e
    db.refresh(role)
    return role


def update_role(db: Session, caller: User, role: Role, payload: dict) -> Role:
    _require_site_access(caller, role.site_id)
    if "name" in payload and payload["name"]:
        role.name = payload["name"]
    if "default_permission_level" in payload and payload["default_permission_level"] is not None:
        lvl = int(payload["default_permission_level"])
        if not 1 <= lvl <= 5:
            raise ValueError("default_permission_level must be 1-5")
        role.default_permission_level = lvl
    if "is_active" in payload and payload["is_active"] is not None:
        role.is_active = bool(payload["is_active"])
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError("Role name conflict in scope") from e
    db.refresh(role)
    return role


def deactivate_role(db: Session, caller: User, role: Role) -> Role:
    _require_site_access(caller, role.site_id)
    role.is_active = False
    db.commit()
    db.refresh(role)
    return role


def role_ref_count(db: Session, role: Role) -> int:
    """Count users currently referencing this role via the FK."""
    return db.query(User).filter(User.role_id == role.id).count()


def purge_role(db: Session, caller: User, role: Role) -> None:
    """Hard-delete; refuses if any user still references the role (SCO-107)."""
    _require_site_access(caller, role.site_id)
    refs = role_ref_count(db, role)
    if refs > 0:
        raise OrgMetaInUseError("Role", refs)
    db.delete(role)
    db.commit()


# ── Departments ───────────────────────────────────────────────────────────

def list_departments(db: Session, caller: User, *, site_id: str | None = None) -> list[Department]:
    _require_admin(caller)
    target = site_id or caller.site_id
    _require_site_access(caller, target)
    return (
        db.query(Department).filter(Department.site_id == target).order_by(Department.name).all()
    )


def create_department(db: Session, caller: User, *, name: str, site_id: str) -> Department:
    _require_site_access(caller, site_id)
    _site_exists(db, site_id)
    dept = Department(name=name, site_id=site_id)
    db.add(dept)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError(f"Department '{name}' already exists for site {site_id}") from e
    db.refresh(dept)
    return dept


def update_department(db: Session, caller: User, dept: Department, payload: dict) -> Department:
    _require_site_access(caller, dept.site_id)
    if "name" in payload and payload["name"]:
        dept.name = payload["name"]
    if "is_active" in payload and payload["is_active"] is not None:
        dept.is_active = bool(payload["is_active"])
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError("Department name conflict at site") from e
    db.refresh(dept)
    return dept


def deactivate_department(db: Session, caller: User, dept: Department) -> Department:
    _require_site_access(caller, dept.site_id)
    dept.is_active = False
    db.commit()
    db.refresh(dept)
    return dept


def department_ref_count(db: Session, dept: Department) -> int:
    return db.query(User).filter(User.department_id == dept.id).count()


def purge_department(db: Session, caller: User, dept: Department) -> None:
    _require_site_access(caller, dept.site_id)
    refs = department_ref_count(db, dept)
    if refs > 0:
        raise OrgMetaInUseError("Department", refs)
    db.delete(dept)
    db.commit()


# ── Shifts ────────────────────────────────────────────────────────────────

def list_shifts(db: Session, caller: User, *, site_id: str | None = None) -> list[Shift]:
    _require_admin(caller)
    target = site_id or caller.site_id
    _require_site_access(caller, target)
    return (
        db.query(Shift).filter(Shift.site_id == target).order_by(Shift.start_time).all()
    )


def create_shift(db: Session, caller: User, *, name: str, site_id: str,
                 start_time: time, end_time: time) -> Shift:
    _require_site_access(caller, site_id)
    _site_exists(db, site_id)
    shift = Shift(name=name, site_id=site_id, start_time=start_time, end_time=end_time)
    db.add(shift)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError(f"Shift '{name}' already exists for site {site_id}") from e
    db.refresh(shift)
    return shift


def update_shift(db: Session, caller: User, shift: Shift, payload: dict) -> Shift:
    _require_site_access(caller, shift.site_id)
    if "name" in payload and payload["name"]:
        shift.name = payload["name"]
    if "start_time" in payload and payload["start_time"] is not None:
        shift.start_time = payload["start_time"]
    if "end_time" in payload and payload["end_time"] is not None:
        shift.end_time = payload["end_time"]
    if "is_active" in payload and payload["is_active"] is not None:
        shift.is_active = bool(payload["is_active"])
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError("Shift name conflict at site") from e
    db.refresh(shift)
    return shift


def deactivate_shift(db: Session, caller: User, shift: Shift) -> Shift:
    _require_site_access(caller, shift.site_id)
    shift.is_active = False
    db.commit()
    db.refresh(shift)
    return shift


def shift_ref_count(db: Session, shift: Shift) -> int:
    return db.query(User).filter(User.shift_id == shift.id).count()


def purge_shift(db: Session, caller: User, shift: Shift) -> None:
    _require_site_access(caller, shift.site_id)
    refs = shift_ref_count(db, shift)
    if refs > 0:
        raise OrgMetaInUseError("Shift", refs)
    db.delete(shift)
    db.commit()


# ── Titles (SCO-100) ──────────────────────────────────────────────────────

def list_titles(db: Session, caller: User, *, site_id: str | None = None,
                include_globals: bool = True) -> list[Title]:
    """Mirror of list_roles: globals + own-site, MCS sees all."""
    _require_admin(caller)
    q = db.query(Title)
    if site_id is None:
        if caller.site_id == MCS_SITE_ID and caller.permission_level >= 4:
            pass
        else:
            scope = [caller.site_id]
            if include_globals:
                q = q.filter((Title.site_id.in_(scope)) | (Title.site_id.is_(None)))
            else:
                q = q.filter(Title.site_id.in_(scope))
    else:
        _require_site_access(caller, site_id)
        q = q.filter(Title.site_id == site_id)
    return q.order_by(Title.site_id.is_(None).desc(), Title.name).all()


def create_title(db: Session, caller: User, *, name: str,
                 site_id: str | None) -> Title:
    _require_site_access(caller, site_id)
    if site_id is not None:
        _site_exists(db, site_id)
    title = Title(name=name, site_id=site_id)
    db.add(title)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError(f"Title '{name}' already exists for this scope") from e
    db.refresh(title)
    return title


def update_title(db: Session, caller: User, title: Title, payload: dict) -> Title:
    _require_site_access(caller, title.site_id)
    if "name" in payload and payload["name"]:
        title.name = payload["name"]
    if "is_active" in payload and payload["is_active"] is not None:
        title.is_active = bool(payload["is_active"])
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ValueError("Title name conflict in scope") from e
    db.refresh(title)
    return title


def deactivate_title(db: Session, caller: User, title: Title) -> Title:
    _require_site_access(caller, title.site_id)
    title.is_active = False
    db.commit()
    db.refresh(title)
    return title


def title_ref_count(db: Session, title: Title) -> int:
    return db.query(User).filter(User.title_id == title.id).count()


def purge_title(db: Session, caller: User, title: Title) -> None:
    _require_site_access(caller, title.site_id)
    refs = title_ref_count(db, title)
    if refs > 0:
        raise OrgMetaInUseError("Title", refs)
    db.delete(title)
    db.commit()

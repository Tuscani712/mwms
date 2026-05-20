"""Admin user management — CRUD + permission gating.

Permission model (read top-down, first match wins):

1. Caller must have permission_level >= 3 OR be an MCS admin.
2. Cross-site operations (acting on a user whose site != caller's site) require
   caller at MCS site with permission_level >= 4.
3. A caller can only act on users *strictly below* their own permission_level.
   (Level 3 cannot edit another Level 3; Level 4 can edit any Level 3.)
4. A user cannot deactivate themselves — prevents lockout footguns.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wms.core.security import hash_password
from wms.models import Department, Role, Shift, User

MCS_SITE_ID = "MCS"


class AdminAuthorizationError(PermissionError):
    """Raised when caller lacks permission to act on a target user."""


def require_admin(caller: User) -> None:
    """Caller must be Level 3+ (or any MCS user) to access /admin/users at all."""
    if caller.permission_level >= 3:
        return
    if caller.site_id == MCS_SITE_ID:
        return
    raise AdminAuthorizationError("Level 3+ required to access user management")


def assert_can_manage(caller: User, target: User) -> None:
    """Caller may manage `target` only if both conditions hold."""
    require_admin(caller)

    # Cross-site requires MCS Lvl 4+
    if caller.site_id != target.site_id and (
        caller.site_id != MCS_SITE_ID or caller.permission_level < 4
    ):
        raise AdminAuthorizationError(
            "Cross-site user management requires MCS admin (Level 4+)"
        )

    # Caller must outrank target
    if target.permission_level >= caller.permission_level:
        raise AdminAuthorizationError(
            f"Cannot manage a user at permission level {target.permission_level} "
            f"— your level is {caller.permission_level}"
        )


def _resolve_role(db: Session, role_id: int | None, site_id: str) -> Role | None:
    """Validate role_id exists and is usable at site_id (global or matches)."""
    if role_id is None:
        return None
    role = db.query(Role).filter(Role.id == role_id).one_or_none()
    if role is None:
        raise ValueError(f"Role {role_id} not found")
    if role.site_id is not None and role.site_id != site_id:
        raise ValueError(
            f"Role '{role.name}' belongs to site {role.site_id}, "
            f"cannot assign to user at site {site_id}"
        )
    return role


def _resolve_department(db: Session, dept_id: int | None, site_id: str) -> Department | None:
    if dept_id is None:
        return None
    dept = db.query(Department).filter(Department.id == dept_id).one_or_none()
    if dept is None:
        raise ValueError(f"Department {dept_id} not found")
    if dept.site_id != site_id:
        raise ValueError(
            f"Department '{dept.name}' belongs to site {dept.site_id}, "
            f"cannot assign to user at site {site_id}"
        )
    return dept


def _resolve_shift(db: Session, shift_id: int | None, site_id: str) -> Shift | None:
    if shift_id is None:
        return None
    shift = db.query(Shift).filter(Shift.id == shift_id).one_or_none()
    if shift is None:
        raise ValueError(f"Shift {shift_id} not found")
    if shift.site_id != site_id:
        raise ValueError(
            f"Shift '{shift.name}' belongs to site {shift.site_id}, "
            f"cannot assign to user at site {site_id}"
        )
    return shift


def create_user(db: Session, caller: User, *, payload: dict) -> User:
    require_admin(caller)

    site_id = payload.get("site_id") or caller.site_id
    if site_id != caller.site_id and (
        caller.site_id != MCS_SITE_ID or caller.permission_level < 4
    ):
        raise AdminAuthorizationError(
            "Cross-site user creation requires MCS admin (Level 4+)"
        )

    # SCO-80: resolve FK entities first so we can derive permission_level from
    # Role.default_permission_level when caller doesn't pass it explicitly.
    role_obj = _resolve_role(db, payload.get("role_id"), site_id)
    dept_obj = _resolve_department(db, payload.get("department_id"), site_id)
    shift_obj = _resolve_shift(db, payload.get("shift_id"), site_id)

    explicit_level = payload.get("permission_level")
    if explicit_level is not None:
        new_level = int(explicit_level)
    elif role_obj is not None:
        new_level = role_obj.default_permission_level
    else:
        new_level = 1  # legacy default when neither role_id nor level provided

    if new_level >= caller.permission_level:
        raise AdminAuthorizationError(
            f"Cannot create a user at level {new_level} — must be below your "
            f"own level ({caller.permission_level})"
        )

    if db.query(User).filter(User.employee_code == payload["employee_code"]).first():
        raise ValueError(f"Employee code '{payload['employee_code']}' already exists")

    # Backfill legacy string fields from resolved entities so callers consuming
    # User.role / User.department / User.shift keep working during the soft-FK
    # transition (SCO-77/80).
    role_str = role_obj.name if role_obj else payload.get("role", "operator")
    dept_str = dept_obj.name if dept_obj else payload.get("department")
    shift_str = shift_obj.name if shift_obj else payload.get("shift")

    user = User(
        site_id=site_id,
        employee_code=payload["employee_code"],
        email=payload["email"],
        full_name=payload["full_name"],
        role=role_str,
        role_id=role_obj.id if role_obj else None,
        permission_level=new_level,
        hashed_password=hash_password(payload["password"]),
        department=dept_str,
        department_id=dept_obj.id if dept_obj else None,
        shift=shift_str,
        shift_id=shift_obj.id if shift_obj else None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# Fields that can be updated through PUT /admin/users/{id}. Permission level
# and supervisor are deliberately excluded — those move via dedicated endpoints
# in SCO-36's hierarchy layer.
UPDATABLE_FIELDS = {"email", "full_name", "role", "department", "shift"}


def update_user(db: Session, caller: User, target: User, payload: dict) -> User:
    assert_can_manage(caller, target)
    changed = False
    for field in UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(target, field, payload[field])
            changed = True

    # SCO-80: FK updates with site-match validation + legacy-string backfill.
    if "role_id" in payload:
        role_obj = _resolve_role(db, payload["role_id"], target.site_id)
        target.role_id = role_obj.id if role_obj else None
        if role_obj is not None:
            target.role = role_obj.name
        changed = True
    if "department_id" in payload:
        dept_obj = _resolve_department(db, payload["department_id"], target.site_id)
        target.department_id = dept_obj.id if dept_obj else None
        if dept_obj is not None:
            target.department = dept_obj.name
        changed = True
    if "shift_id" in payload:
        shift_obj = _resolve_shift(db, payload["shift_id"], target.site_id)
        target.shift_id = shift_obj.id if shift_obj else None
        if shift_obj is not None:
            target.shift = shift_obj.name
        changed = True

    if "permission_level" in payload and payload["permission_level"] is not None:
        new_level = int(payload["permission_level"])
        if new_level >= caller.permission_level:
            raise AdminAuthorizationError(
                f"Cannot promote to level {new_level} (your level is {caller.permission_level})"
            )
        target.permission_level = new_level
        changed = True
    if changed:
        db.commit()
        db.refresh(target)
    return target


def deactivate_user(db: Session, caller: User, target: User) -> User:
    if caller.id == target.id:
        raise AdminAuthorizationError("You cannot deactivate yourself")
    assert_can_manage(caller, target)
    target.is_active = False
    db.commit()
    db.refresh(target)
    return target


def reactivate_user(db: Session, caller: User, target: User) -> User:
    assert_can_manage(caller, target)
    target.is_active = True
    db.commit()
    db.refresh(target)
    return target


def list_users(
    db: Session,
    caller: User,
    *,
    site_id: str | None = None,
    role: str | None = None,
    level_min: int | None = None,
    level_max: int | None = None,
    search: str | None = None,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    """Returns (page, total_count). Non-MCS callers are scoped to their site."""
    require_admin(caller)

    q = db.query(User)

    # Scope: non-MCS callers only see their own site
    if caller.site_id != MCS_SITE_ID:
        q = q.filter(User.site_id == caller.site_id)
    elif site_id:
        q = q.filter(User.site_id == site_id)

    if role:
        q = q.filter(User.role == role)
    if level_min is not None:
        q = q.filter(User.permission_level >= level_min)
    if level_max is not None:
        q = q.filter(User.permission_level <= level_max)
    if not include_inactive:
        q = q.filter(User.is_active.is_(True))
    if search:
        like = f"%{search}%"
        q = q.filter(
            (User.employee_code.ilike(like))
            | (User.full_name.ilike(like))
            | (User.email.ilike(like))
        )

    total = q.count()
    page = q.order_by(User.permission_level.desc(), User.full_name.asc()).limit(limit).offset(offset).all()
    return page, total

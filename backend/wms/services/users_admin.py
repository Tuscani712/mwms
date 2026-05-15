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
from wms.models import User

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


def create_user(db: Session, caller: User, *, payload: dict) -> User:
    require_admin(caller)

    site_id = payload.get("site_id") or caller.site_id
    if site_id != caller.site_id and (
        caller.site_id != MCS_SITE_ID or caller.permission_level < 4
    ):
        raise AdminAuthorizationError(
            "Cross-site user creation requires MCS admin (Level 4+)"
        )

    new_level = int(payload.get("permission_level", 1))
    if new_level >= caller.permission_level:
        raise AdminAuthorizationError(
            f"Cannot create a user at level {new_level} — must be below your "
            f"own level ({caller.permission_level})"
        )

    if db.query(User).filter(User.employee_code == payload["employee_code"]).first():
        raise ValueError(f"Employee code '{payload['employee_code']}' already exists")

    user = User(
        site_id=site_id,
        employee_code=payload["employee_code"],
        email=payload["email"],
        full_name=payload["full_name"],
        role=payload.get("role", "operator"),
        permission_level=new_level,
        hashed_password=hash_password(payload["password"]),
        department=payload.get("department"),
        shift=payload.get("shift"),
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

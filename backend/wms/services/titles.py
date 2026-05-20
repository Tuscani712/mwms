"""User Title service — list / create / rename / soft-delete (SCO-70).

Soft-delete only. Existing `User.title` values are free-text strings (SCO-72),
so hard-deleting a title row would not break referential integrity, but it
would silently invalidate the historical label. Keeping the row with
`is_active=false` preserves the audit trail and lets admins restore.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from wms.models import User, UserTitle

# Minimum permission level required for write operations.
TITLES_WRITE_MIN_LEVEL = 3


def assert_can_write(caller: User) -> None:
    if caller.permission_level < TITLES_WRITE_MIN_LEVEL:
        raise PermissionError(
            f"Title management requires permission_level >= {TITLES_WRITE_MIN_LEVEL}"
        )


def list_titles(db: Session, *, include_inactive: bool = False) -> list[UserTitle]:
    q = db.query(UserTitle)
    if not include_inactive:
        q = q.filter(UserTitle.is_active.is_(True))
    return q.order_by(UserTitle.name.asc()).all()


def _find_by_name_ci(db: Session, name: str) -> UserTitle | None:
    return (
        db.query(UserTitle)
        .filter(func.lower(UserTitle.name) == name.lower())
        .one_or_none()
    )


def create_title(db: Session, caller: User, *, name: str) -> UserTitle:
    assert_can_write(caller)
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    existing = _find_by_name_ci(db, name)
    if existing is not None:
        raise FileExistsError(f"Title '{existing.name}' already exists")
    row = UserTitle(name=name, is_active=True, created_by=caller.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_title(
    db: Session,
    caller: User,
    *,
    title_id: int,
    name: str | None = None,
    is_active: bool | None = None,
) -> UserTitle:
    assert_can_write(caller)
    row = db.query(UserTitle).filter(UserTitle.id == title_id).one_or_none()
    if row is None:
        raise LookupError(f"Title {title_id} not found")
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        clash = _find_by_name_ci(db, name)
        if clash is not None and clash.id != row.id:
            raise FileExistsError(f"Title '{clash.name}' already exists")
        row.name = name
    if is_active is not None:
        row.is_active = bool(is_active)
    db.commit()
    db.refresh(row)
    return row


def soft_delete_title(db: Session, caller: User, *, title_id: int) -> UserTitle:
    return update_title(db, caller, title_id=title_id, is_active=False)

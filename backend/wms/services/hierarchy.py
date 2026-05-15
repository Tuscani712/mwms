"""Org hierarchy + assignment invariants.

5-tier ladder, top-down:
    5  Corporate (Corp)
    4  Site Manager
    3  Site / Department Supervisor
    2  Department / Position Leader
    1  Operator

Supervisor rules (enforced when a supervisor is assigned):
1. Supervisor must outrank the subordinate (strictly higher permission_level).
2. Supervisor must be at the same site, unless the supervisor is an MCS user
   (corporate can manage anyone).
3. No cycles in the chain — walking supervisor_id repeatedly must never come
   back to the same user.
4. A user cannot be their own supervisor.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wms.models import User
from wms.services.users_admin import MCS_SITE_ID, AdminAuthorizationError, assert_can_manage

TIER_LABELS: dict[int, str] = {
    5: "Corporate",
    4: "Site Manager",
    3: "Site/Department Supervisor",
    2: "Department/Position Leader",
    1: "Operator",
}


def tier_label(level: int) -> str:
    return TIER_LABELS.get(level, f"Level {level}")


def _detect_cycle(db: Session, *, candidate_supervisor_id: int, subject_id: int) -> bool:
    """True if making candidate_supervisor_id the supervisor of subject_id would
    create a cycle (i.e., subject is already an ancestor of candidate)."""
    seen: set[int] = set()
    current_id: int | None = candidate_supervisor_id
    while current_id is not None:
        if current_id == subject_id:
            return True
        if current_id in seen:
            # Defensive: hit a pre-existing cycle (shouldn't happen, but bail)
            return True
        seen.add(current_id)
        row = db.query(User.supervisor_id).filter(User.id == current_id).one_or_none()
        if row is None:
            return False
        current_id = row[0]
    return False


def assign_supervisor(
    db: Session, caller: User, target: User, supervisor_id: int | None
) -> User:
    """Set or clear `target`'s supervisor. Returns the refreshed target."""
    assert_can_manage(caller, target)

    if supervisor_id is None:
        target.supervisor_id = None
        db.commit()
        db.refresh(target)
        return target

    if supervisor_id == target.id:
        raise ValueError("A user cannot be their own supervisor")

    supervisor = db.query(User).filter(User.id == supervisor_id).one_or_none()
    if supervisor is None:
        raise ValueError(f"Supervisor {supervisor_id} not found")

    if supervisor.permission_level <= target.permission_level:
        raise ValueError(
            f"Supervisor must outrank the subordinate "
            f"(supervisor lvl {supervisor.permission_level} ≤ subordinate lvl {target.permission_level})"
        )

    if supervisor.site_id != target.site_id and supervisor.site_id != MCS_SITE_ID:
        raise ValueError(
            "Supervisor must be at the same site, or be a corporate (MCS) user"
        )

    if _detect_cycle(db, candidate_supervisor_id=supervisor_id, subject_id=target.id):
        raise ValueError("Assignment would create a cycle in the supervisor chain")

    target.supervisor_id = supervisor_id
    db.commit()
    db.refresh(target)
    return target


def transfer_department(
    db: Session, caller: User, target: User, department: str | None
) -> User:
    assert_can_manage(caller, target)
    target.department = department
    db.commit()
    db.refresh(target)
    return target


def change_shift(db: Session, caller: User, target: User, shift: str | None) -> User:
    assert_can_manage(caller, target)
    target.shift = shift
    db.commit()
    db.refresh(target)
    return target


def list_subordinates(db: Session, caller: User, target: User) -> list[User]:
    """All users whose supervisor_id == target.id. Caller must be allowed to read target."""
    if caller.permission_level < 3 and caller.site_id != MCS_SITE_ID:
        raise AdminAuthorizationError("Level 3+ required")
    if caller.site_id != MCS_SITE_ID and target.site_id != caller.site_id:
        raise AdminAuthorizationError("Cross-site read requires MCS admin")
    return (
        db.query(User)
        .filter(User.supervisor_id == target.id, User.is_active.is_(True))
        .order_by(User.permission_level.desc(), User.full_name.asc())
        .all()
    )

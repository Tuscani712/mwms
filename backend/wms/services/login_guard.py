"""Login throttling: per-account lockout + per-IP rate limit (SEC-1).

Lockout progression (per-fail escalation, resets on any successful login):
    fails 1..3       → no lockout, plain 401
    fail 4           →   60 s lockout
    fail 5           →  120 s lockout
    fail 6           →  180 s lockout
    fail 7+          → 3600 s lockout (sticky)

State is derived from `login_attempts` rows since the most recent reset event
(success or admin_unlock marker). No new columns on `users` — the audit table
is authoritative, queries are bounded (≤ ~12 rows per user in window).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc
from sqlalchemy.orm import Session

from wms.models import LoginAttempt

LOCKOUT_SCHEDULE_SECONDS: tuple[int, ...] = (60, 120, 180, 3600)
# Three failures are absorbed without lockout. The 4th attempt — i.e. the
# request that arrives with 3 prior failures already on record — is the first
# blocked one. `GRACE_FAILS = 2` reads as "still unlocked when count_so_far
# is 0, 1, or 2; locked the moment a 3rd failure is on record."
GRACE_FAILS = 2
ADMIN_UNLOCK_REASON = "admin_unlock"
IP_MIN_INTERVAL_SECONDS = 1.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LockoutState:
    locked: bool
    retry_after_seconds: int
    fail_count: int
    locked_until: datetime | None


def _lockout_seconds_for_fail_count(fail_count: int) -> int:
    """fails 1..3 → 0, fail 4 → 60, fail 5 → 120, fail 6 → 180, fail 7+ → 3600."""
    if fail_count <= GRACE_FAILS:
        return 0
    idx = min(fail_count - GRACE_FAILS - 1, len(LOCKOUT_SCHEDULE_SECONDS) - 1)
    return LOCKOUT_SCHEDULE_SECONDS[idx]


def _failures_since_reset(db: Session, employee_code: str, site_id: str) -> list[LoginAttempt]:
    """All failure rows since the latest reset event (success or admin_unlock)."""
    last_reset = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.employee_code == employee_code,
            LoginAttempt.site_id == site_id,
            LoginAttempt.success.is_(True),
        )
        .order_by(desc(LoginAttempt.attempted_at), desc(LoginAttempt.id))
        .first()
    )
    q = db.query(LoginAttempt).filter(
        LoginAttempt.employee_code == employee_code,
        LoginAttempt.site_id == site_id,
        LoginAttempt.success.is_(False),
    )
    if last_reset is not None:
        q = q.filter(LoginAttempt.attempted_at > last_reset.attempted_at)
    return q.order_by(LoginAttempt.attempted_at.asc(), LoginAttempt.id.asc()).all()


def evaluate_lockout(db: Session, employee_code: str, site_id: str) -> LockoutState:
    """Compute current lockout state for an account, *before* this attempt is recorded."""
    fails = _failures_since_reset(db, employee_code, site_id)
    fail_count = len(fails)
    if fail_count <= GRACE_FAILS or not fails:
        return LockoutState(False, 0, fail_count, None)
    last_fail_at = fails[-1].attempted_at
    if last_fail_at.tzinfo is None:
        last_fail_at = last_fail_at.replace(tzinfo=UTC)
    lock_seconds = _lockout_seconds_for_fail_count(fail_count)
    locked_until = last_fail_at + timedelta(seconds=lock_seconds)
    remaining = (locked_until - _utcnow()).total_seconds()
    if remaining <= 0:
        return LockoutState(False, 0, fail_count, None)
    return LockoutState(True, int(remaining) + 1, fail_count, locked_until)


def record_attempt(
    db: Session,
    *,
    employee_code: str,
    site_id: str | None,
    success: bool,
    failure_reason: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> LoginAttempt:
    """Insert one row into login_attempts. Caller decides commit semantics."""
    row = LoginAttempt(
        employee_code=employee_code,
        site_id=site_id,
        attempted_at=_utcnow(),
        success=success,
        failure_reason=failure_reason,
        ip=ip[:45] if ip else None,
        user_agent=user_agent[:255] if user_agent else None,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def record_admin_unlock(
    db: Session, *, employee_code: str, site_id: str, ip: str | None = None
) -> LoginAttempt:
    """Insert an admin-unlock reset marker so future lockout queries see a clean slate."""
    return record_attempt(
        db,
        employee_code=employee_code,
        site_id=site_id,
        success=True,
        failure_reason=ADMIN_UNLOCK_REASON,
        ip=ip,
        commit=True,
    )


# ── Per-IP rate limit ────────────────────────────────────────────────
# In-process token bucket: one slot per IP, minimum interval between calls.
# Single-node dev/staging only; for multi-node prod swap for Redis/INCR.

_IP_LOCK = threading.Lock()
_IP_LAST_SEEN: dict[str, datetime] = {}
_IP_TABLE_CAP = 4096  # bound memory; LRU-style eviction on overflow


def check_ip_rate_limit(ip: str | None) -> tuple[bool, float]:
    """Return (allowed, retry_after_seconds). Allowed=True on missing IP (trusted local)."""
    if not ip:
        return True, 0.0
    now = _utcnow()
    with _IP_LOCK:
        last = _IP_LAST_SEEN.get(ip)
        if last is not None:
            delta = (now - last).total_seconds()
            if delta < IP_MIN_INTERVAL_SECONDS:
                return False, IP_MIN_INTERVAL_SECONDS - delta
        if len(_IP_LAST_SEEN) >= _IP_TABLE_CAP:
            # crude eviction: drop the oldest 25% to amortize
            cutoff = sorted(_IP_LAST_SEEN.values())[_IP_TABLE_CAP // 4]
            for k, v in list(_IP_LAST_SEEN.items()):
                if v <= cutoff:
                    _IP_LAST_SEEN.pop(k, None)
        _IP_LAST_SEEN[ip] = now
    return True, 0.0


def reset_ip_rate_limit() -> None:
    """Test hook — clears the in-memory bucket between cases."""
    with _IP_LOCK:
        _IP_LAST_SEEN.clear()

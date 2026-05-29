"""SEC-1: per-account lockout progression + per-IP rate limit + admin reset/unlock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wms.core.security import hash_password
from wms.models import LoginAttempt, User
from wms.services import login_guard as guard

LOGIN_URL = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
def _clear_ip_bucket():
    guard.reset_ip_rate_limit()
    yield
    guard.reset_ip_rate_limit()


def _login(client, code="WHS-001-001", password="password123", site="WHS-001"):
    # Reset the in-process IP bucket so per-account lockout tests aren't
    # interleaved with per-IP throttling. test_ip_rate_limit_blocks_burst
    # exercises that path separately.
    guard.reset_ip_rate_limit()
    return client.post(
        LOGIN_URL,
        json={"employee_code": code, "password": password, "site_id": site},
    )


def _backdate_failures(db, employee_code: str, site_id: str, seconds_ago: int) -> None:
    """Move every failure row's attempted_at back in time so lockout windows expire."""
    cutoff = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    rows = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.employee_code == employee_code,
            LoginAttempt.site_id == site_id,
            LoginAttempt.success.is_(False),
        )
        .all()
    )
    for r in rows:
        r.attempted_at = cutoff
    db.commit()


# ── Stage math (pure unit, no HTTP) ───────────────────────────────────


def test_no_lockout_below_grace(db_session):
    state = guard.evaluate_lockout(db_session, "ghost", "WHS-001")
    assert state.locked is False
    assert state.fail_count == 0


def test_fail_3_locks_60s(db_session, seeded_db):
    """3 failures on record → 4th attempt is the first locked one, 60s."""
    for _ in range(3):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert state.locked is True
    assert 55 <= state.retry_after_seconds <= 61
    assert state.fail_count == 3


def test_fail_4_locks_120s(db_session, seeded_db):
    for _ in range(4):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert state.locked is True
    assert 115 <= state.retry_after_seconds <= 121


def test_fail_5_locks_180s(db_session, seeded_db):
    for _ in range(5):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert 175 <= state.retry_after_seconds <= 181


def test_fail_6_locks_1hr(db_session, seeded_db):
    for _ in range(6):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert 3595 <= state.retry_after_seconds <= 3601


def test_fail_10_still_1hr(db_session, seeded_db):
    for _ in range(10):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert state.fail_count == 10
    assert 3595 <= state.retry_after_seconds <= 3601


def test_three_fails_no_lock_yet(db_session, seeded_db):
    """Two failures still allow the third (final grace) attempt."""
    for _ in range(2):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert state.locked is False


def test_success_resets_stage(db_session, seeded_db):
    for _ in range(5):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    guard.record_attempt(
        db_session, employee_code="WHS-001-001", site_id="WHS-001", success=True,
    )
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert state.locked is False
    assert state.fail_count == 0


def test_admin_unlock_resets_stage(db_session, seeded_db):
    for _ in range(6):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    assert guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001").locked
    guard.record_admin_unlock(
        db_session, employee_code="WHS-001-001", site_id="WHS-001",
    )
    assert guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001").locked is False


def test_expired_lockout_window_unlocks(db_session, seeded_db):
    for _ in range(3):
        guard.record_attempt(
            db_session, employee_code="WHS-001-001", site_id="WHS-001",
            success=False, failure_reason="bad_credentials",
        )
    _backdate_failures(db_session, "WHS-001-001", "WHS-001", seconds_ago=120)
    state = guard.evaluate_lockout(db_session, "WHS-001-001", "WHS-001")
    assert state.locked is False


# ── HTTP integration ──────────────────────────────────────────────────


def test_three_bad_logins_no_lockout(client, db_session):
    for _ in range(3):
        r = _login(client, password="wrong")
        assert r.status_code == 401, r.text


def test_fourth_bad_login_returns_423(client):
    """Per spec: 3 attempts are allowed; the 4th is the first 423."""
    for i in range(4):
        r = _login(client, password="wrong")
        if i < 3:
            assert r.status_code == 401, f"attempt {i+1} should still 401"
    assert r.status_code == 423
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) >= 1


def test_correct_password_during_lockout_still_blocked(client, db_session):
    for _ in range(3):
        _login(client, password="wrong")
    r = _login(client, password="password123")
    assert r.status_code == 423


def test_admin_unlock_restores_login(client, db_session, seeded_db):
    for _ in range(3):
        _login(client, password="wrong")
    assert _login(client, password="password123").status_code == 423
    guard.record_admin_unlock(
        db_session, employee_code="WHS-001-001", site_id="WHS-001",
    )
    assert _login(client, password="password123").status_code == 200


def test_unknown_user_can_still_lock(client):
    """Brute force on a nonexistent account still consumes the lockout budget,
    so attackers can't enumerate users by lockout behaviour."""
    for _ in range(4):
        guard.reset_ip_rate_limit()
        r = client.post(
            LOGIN_URL,
            json={"employee_code": "GHOST", "password": "x", "site_id": "WHS-001"},
        )
    assert r.status_code == 423


def test_ip_rate_limit_blocks_burst(client, monkeypatch):
    """Two requests in the same instant should trip the 1/sec IP limit."""
    # conftest disables the bucket; re-enable just for this test.
    monkeypatch.setattr(guard, "IP_MIN_INTERVAL_SECONDS", 1.0)
    guard.reset_ip_rate_limit()
    raw = lambda: client.post(  # noqa: E731
        LOGIN_URL,
        json={"employee_code": "WHS-001-001", "password": "wrong", "site_id": "WHS-001"},
    )
    r1 = raw()
    r2 = raw()
    assert r1.status_code == 401
    assert r2.status_code == 429
    assert "Retry-After" in r2.headers


# ── Admin endpoints ───────────────────────────────────────────────────


def _make_admin(db_session) -> User:
    admin = User(
        site_id="WHS-001",
        employee_code="ADM-001",
        email="adm@wms.local",
        full_name="Test Admin",
        role="admin",
        permission_level=4,
        hashed_password=hash_password("adminpass"),
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def _bearer_for(client, code: str, password: str, site: str = "WHS-001") -> dict:
    guard.reset_ip_rate_limit()
    r = client.post(LOGIN_URL, json={"employee_code": code, "password": password, "site_id": site})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_admin_reset_password_changes_login(client, db_session):
    _make_admin(db_session)
    headers = _bearer_for(client, "ADM-001", "adminpass")
    target = db_session.query(User).filter(User.employee_code == "WHS-001-001").one()
    guard.reset_ip_rate_limit()
    r = client.post(
        f"/api/v1/admin/users/{target.id}/reset-password",
        json={"new_password": "newpass99", "force_change_on_next_login": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    # old password no longer works
    guard.reset_ip_rate_limit()
    assert _login(client, password="password123").status_code == 401
    # new password works
    guard.reset_ip_rate_limit()
    assert _login(client, password="newpass99").status_code == 200


def test_admin_unlock_endpoint(client, db_session):
    _make_admin(db_session)
    for _ in range(3):
        _login(client, password="wrong")
    assert _login(client, password="password123").status_code == 423
    headers = _bearer_for(client, "ADM-001", "adminpass")
    target = db_session.query(User).filter(User.employee_code == "WHS-001-001").one()
    guard.reset_ip_rate_limit()
    r = client.post(f"/api/v1/admin/users/{target.id}/unlock", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] is True
    guard.reset_ip_rate_limit()
    assert _login(client, password="password123").status_code == 200


def test_admin_reset_requires_outranking_target(client, db_session):
    """A peer-level admin cannot reset another peer's password."""
    peer = User(
        site_id="WHS-001",
        employee_code="ADM-002",
        email="adm2@wms.local",
        full_name="Peer Admin",
        role="admin",
        permission_level=4,
        hashed_password=hash_password("peerpass"),
    )
    target_peer = User(
        site_id="WHS-001",
        employee_code="ADM-003",
        email="adm3@wms.local",
        full_name="Peer Target",
        role="admin",
        permission_level=4,
        hashed_password=hash_password("peer3pass"),
    )
    db_session.add_all([peer, target_peer])
    db_session.commit()
    headers = _bearer_for(client, "ADM-002", "peerpass")
    guard.reset_ip_rate_limit()
    r = client.post(
        f"/api/v1/admin/users/{target_peer.id}/reset-password",
        json={"new_password": "hackmenot"},
        headers=headers,
    )
    assert r.status_code == 403

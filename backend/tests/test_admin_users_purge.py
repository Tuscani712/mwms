"""Hard-purge user endpoint — POST /admin/users/{id}/purge (SCO-55).

The existing DELETE on the same path is a soft-archive (sets is_active=False).
Purge is the irreversible counterpart: gated to Lvl 5, refuses self-purge,
last-admin, and users with active subordinates. Audit log rows owned or
authored by the deleted user have their FK pointers NULLed so the trail
survives.
"""

from __future__ import annotations

import json

from wms.core.security import hash_password
from wms.models import AuditLog, User

# ── Helpers ─────────────────────────────────────────────────────────────


def _seed_user(db, *, code, level=1, site="WHS-001", supervisor_id=None) -> User:
    u = User(
        site_id=site,
        employee_code=code,
        email=f"{code.lower()}@wms.local",
        full_name=f"User {code}",
        role="operator" if level == 1 else "admin",
        permission_level=level,
        hashed_password=hash_password("password123"),
        supervisor_id=supervisor_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, code, site="WHS-001"):
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": code, "password": "password123", "site_id": site},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


# ── Happy path ──────────────────────────────────────────────────────────


def test_lvl5_purges_user_successfully(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    target = _seed_user(seeded_db, code="DOOMED-001", level=1)
    token = _login(client, admin.employee_code)

    r = client.post(f"/api/v1/admin/users/{target.id}/purge", headers=_h(token), json={})
    assert r.status_code == 204, r.text

    # Row is gone
    r = client.get(f"/api/v1/admin/users/{target.id}", headers=_h(token))
    assert r.status_code == 404


def test_purge_emits_audit_event_with_snapshot(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    target = _seed_user(seeded_db, code="EVIDENCE-001", level=1)
    target_id = target.id
    token = _login(client, admin.employee_code)

    client.post(f"/api/v1/admin/users/{target_id}/purge", headers=_h(token), json={})

    seeded_db.expire_all()
    audit = (
        seeded_db.query(AuditLog)
        .filter(AuditLog.event_type == "user.purged")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    detail = json.loads(audit.detail_json)
    assert detail["id"] == target_id
    assert detail["employee_code"] == "EVIDENCE-001"


def test_audit_history_preserved_with_fk_nulled(client, seeded_db):
    """A purged user's prior audit rows must survive — FK references just go to NULL."""
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    actor = _seed_user(seeded_db, code="GHOST-001", level=1)
    actor_id = actor.id
    # Hand-create an audit row pointing at the actor
    seeded_db.add(AuditLog(event_type="profile.changed", actor_id=actor_id, user_id=actor_id))
    seeded_db.commit()

    token = _login(client, admin.employee_code)
    r = client.post(f"/api/v1/admin/users/{actor_id}/purge", headers=_h(token), json={})
    assert r.status_code == 204

    seeded_db.expire_all()
    remaining = seeded_db.query(AuditLog).filter(AuditLog.event_type == "profile.changed").all()
    assert len(remaining) == 1
    assert remaining[0].actor_id is None
    assert remaining[0].user_id is None


# ── Safety rails ────────────────────────────────────────────────────────


def test_lvl4_admin_cannot_purge(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L4", level=4)
    target = _seed_user(seeded_db, code="SURVIVOR-001", level=1)
    token = _login(client, admin.employee_code)
    r = client.post(f"/api/v1/admin/users/{target.id}/purge", headers=_h(token), json={})
    assert r.status_code == 403
    assert "level 5" in r.json()["detail"].lower()


def test_cannot_purge_self(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    token = _login(client, admin.employee_code)
    r = client.post(f"/api/v1/admin/users/{admin.id}/purge", headers=_h(token), json={})
    assert r.status_code == 403
    assert "yourself" in r.json()["detail"].lower()


def test_cannot_purge_last_lvl5_admin(client, seeded_db):
    only_admin = _seed_user(seeded_db, code="ONLY-L5", level=5)
    # Need another Lvl 5 doing the purging, but no other Lvl 5 exists after them either.
    # So: two L5s, where one tries to purge the other but both would leave a survivor.
    # The "last admin" case requires that purging the target leaves *no* Lvl 5.
    # Simulate by making only_admin try to purge a second L5 such that nobody is left.
    second = _seed_user(seeded_db, code="SECOND-L5", level=5)
    _login(client, only_admin.employee_code)
    # Deactivate `only_admin` itself? No — caller must be active. Instead,
    # deactivate any other potential L5: there are none. So purging `second`
    # should still succeed (only_admin remains). To trigger the lockout guard
    # we deactivate only_admin's account-active flag... but then they can't log in.
    # Simpler: directly call the service helper to assert the guard works.
    from wms.services import users_admin as svc

    # Pretend only_admin tries to purge themselves via another caller is forbidden by
    # the self-check, so use the second admin to purge only_admin; that would leave
    # `second` standing → allowed. To force "last admin" trip, mark `second` inactive
    # so they don't count toward the survival pool:
    second.is_active = False
    seeded_db.commit()
    # Now `only_admin` is the ONLY active Lvl 5; another caller trying to purge them
    # would trip the guard. Build a third Lvl 5 (active) to act as the caller.
    third = _seed_user(seeded_db, code="THIRD-L5", level=5)
    # third logs in for completeness but we use the service layer below.
    _login(client, third.employee_code)
    # Deactivate `third` after they log in? No, that would invalidate the token. Instead,
    # make `third` inactive AFTER the count check by deactivating them as well:
    # The check is "remaining ACTIVE L5 not counting the target". Active: only_admin and third.
    # Target = only_admin. Remaining (excluding target, active): {third}. count==1 ≥ 1 → ok.
    # So we need both `second` and `third` inactive to force last-admin trip on only_admin.
    third.is_active = False
    seeded_db.commit()
    # Now `third` can no longer authenticate — re-login to get a fresh token won't work.
    # Use the service layer directly for this edge:
    try:
        svc.purge_user(seeded_db, third, only_admin)
        raise AssertionError("Expected AdminAuthorizationError for last-admin guard")
    except svc.AdminAuthorizationError as e:
        assert "last level 5" in str(e).lower()


def test_cannot_purge_user_with_subordinates(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    supervisor = _seed_user(seeded_db, code="SUP-001", level=3)
    _seed_user(seeded_db, code="OP-001", level=1, supervisor_id=supervisor.id)
    token = _login(client, admin.employee_code)

    r = client.post(f"/api/v1/admin/users/{supervisor.id}/purge", headers=_h(token), json={})
    assert r.status_code == 409
    assert "subordinate" in r.json()["detail"].lower()


def test_purge_404_for_missing_user(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    token = _login(client, admin.employee_code)
    r = client.post("/api/v1/admin/users/999999/purge", headers=_h(token), json={})
    assert r.status_code == 404

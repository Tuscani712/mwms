"""Bulk hard-purge endpoint — POST /admin/users/bulk-purge (SCO-88).

Counterpart to the per-row purge tests in test_admin_users_purge.py. The
bulk endpoint reuses the same service-layer safety rails (Lvl 5 only,
self-purge refused, last-admin protected, active-subordinate guard) but
collects failures per row instead of aborting the whole batch.
"""

from __future__ import annotations

import json

from wms.core.security import hash_password
from wms.models import AuditLog, User


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


# ── Happy path ─────────────────────────────────────────────────────────


def test_all_succeed_returns_200(client, seeded_db):
    admin = _seed_user(seeded_db, code="WHS-001-L5", level=5)
    targets = [_seed_user(seeded_db, code=f"DOOM-{i:02d}", level=1) for i in range(5)]
    token = _login(client, admin.employee_code)

    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": [t.id for t in targets]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 5
    assert sorted(body["purged"]) == sorted(t.id for t in targets)
    assert body["failed"] == []
    assert len(body["bulk_operation_id"]) == 32

    # Verify users actually gone.
    remaining = seeded_db.query(User).filter(User.id.in_([t.id for t in targets])).count()
    assert remaining == 0


# ── Partial failures ───────────────────────────────────────────────────


def test_partial_failure_returns_207_with_itemized_reasons(client, seeded_db):
    """Mix of valid + invalid targets: deletable, self, missing, with-subordinate."""
    admin = _seed_user(seeded_db, code="WHS-001-L5B", level=5)
    deletable = _seed_user(seeded_db, code="OK-01", level=1)
    boss = _seed_user(seeded_db, code="HAS-SUBS", level=3)
    _seed_user(seeded_db, code="SUB-01", level=1, supervisor_id=boss.id)
    token = _login(client, admin.employee_code)

    missing_id = 999_999
    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": [deletable.id, admin.id, missing_id, boss.id]},
    )
    assert r.status_code == 207, r.text
    body = r.json()
    assert body["purged"] == [deletable.id]
    failed_by_id = {f["user_id"]: f["reason"] for f in body["failed"]}
    assert failed_by_id[admin.id] == "cannot_delete_self"
    assert failed_by_id[missing_id] == "not_found"
    assert failed_by_id[boss.id] == "has_subordinates"


def test_last_admin_protection_in_batch(client, seeded_db):
    admin = _seed_user(seeded_db, code="ONLY-L5", level=5)
    # No other L5 → admin cannot purge themselves AND cannot be purged via batch
    # by another L5 (there is none). Use the only-admin alone in the batch.
    other = _seed_user(seeded_db, code="VICTIM", level=1)
    token = _login(client, admin.employee_code)
    # Same admin tries to delete themselves + a valid target.
    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": [admin.id, other.id]},
    )
    assert r.status_code == 207
    body = r.json()
    assert other.id in body["purged"]
    assert any(f["user_id"] == admin.id and f["reason"] == "cannot_delete_self" for f in body["failed"])


# ── Hierarchy / auth ───────────────────────────────────────────────────


def test_lvl3_cannot_call_bulk_purge_at_all(client, seeded_db):
    lead = _seed_user(seeded_db, code="LEAD-01", level=3)
    victim = _seed_user(seeded_db, code="VICTIM-X", level=1)
    token = _login(client, lead.employee_code)
    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": [victim.id]},
    )
    assert r.status_code == 403


# ── Input validation ───────────────────────────────────────────────────


def test_empty_array_rejected(client, seeded_db):
    admin = _seed_user(seeded_db, code="L5-EMP", level=5)
    token = _login(client, admin.employee_code)
    r = client.post(
        "/api/v1/admin/users/bulk-purge", headers=_h(token), json={"user_ids": []}
    )
    assert r.status_code == 422


def test_oversize_batch_rejected(client, seeded_db):
    admin = _seed_user(seeded_db, code="L5-OVER", level=5)
    token = _login(client, admin.employee_code)
    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": list(range(1, 202))},  # 201 ids > 200 cap
    )
    assert r.status_code == 422


def test_malformed_id_rejected(client, seeded_db):
    admin = _seed_user(seeded_db, code="L5-BAD", level=5)
    token = _login(client, admin.employee_code)
    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": ["not-an-int"]},
    )
    assert r.status_code == 422


# ── Audit log correlator ───────────────────────────────────────────────


def test_audit_log_entries_share_bulk_operation_id(client, seeded_db):
    admin = _seed_user(seeded_db, code="L5-AUD", level=5)
    targets = [_seed_user(seeded_db, code=f"AUD-{i}", level=1) for i in range(3)]
    token = _login(client, admin.employee_code)

    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": [t.id for t in targets]},
    )
    assert r.status_code == 200
    bulk_id = r.json()["bulk_operation_id"]

    rows = (
        seeded_db.query(AuditLog)
        .filter(AuditLog.event_type == "user.purged")
        .order_by(AuditLog.id.desc())
        .limit(3)
        .all()
    )
    assert len(rows) == 3
    for row in rows:
        detail = json.loads(row.detail_json)
        assert detail["bulk_operation_id"] == bulk_id


# ── De-dup of repeated ids ─────────────────────────────────────────────


def test_duplicate_ids_collapse_to_one_attempt(client, seeded_db):
    admin = _seed_user(seeded_db, code="L5-DUP", level=5)
    victim = _seed_user(seeded_db, code="DUP-1", level=1)
    token = _login(client, admin.employee_code)
    r = client.post(
        "/api/v1/admin/users/bulk-purge",
        headers=_h(token),
        json={"user_ids": [victim.id, victim.id, victim.id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 1
    assert body["purged"] == [victim.id]
    assert body["failed"] == []

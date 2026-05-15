"""Regression tests for SCO-45/46/47/48 (M-7, M-8, I-4, L-1 pre-stage)."""

import pytest
from pydantic import ValidationError

from wms.models import AuditLog, UserMFA
from wms.schemas.profile import ApprovalDecision
from wms.services import audit_log as audit_svc
from wms.services import mfa as mfa_svc
from wms.services import profile as profile_svc

# ── M-7: display_picture URL allowlist ────────────────────────────────────


def test_picture_url_accepts_uploads_path(seeded_db):
    user = seeded_db.query(__import__("wms.models", fromlist=["User"]).User).first()
    req = profile_svc.submit_change_request(
        seeded_db, user, "display_picture", "/uploads/avatars/1-abc123.png"
    )
    assert req.id is not None


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://evil.example.com/x.png",
        "https://evil.example.com/x.png",
        "data:image/png;base64,iVBORw0KGgo=",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "/etc/passwd",
        "/uploads/avatars/../../etc/passwd",
        "//uploads/avatars/x.png",
        "",
    ],
)
def test_picture_url_rejects_unsafe(seeded_db, bad_url):
    from wms.models import User

    user = seeded_db.query(User).first()
    with pytest.raises(ValueError):
        profile_svc.submit_change_request(seeded_db, user, "display_picture", bad_url)


def test_picture_url_endpoint_returns_400_on_external(client, auth_headers):
    r = client.post(
        "/api/v1/profile/display-picture-request",
        json={"requested_value": "http://evil.example.com/a.png"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "/uploads/avatars/" in r.json()["detail"]


# ── M-8: MFA backup-code regeneration ─────────────────────────────────────


def _enroll_mfa(client, auth_headers):
    r = client.post("/api/v1/profile/mfa/setup", headers=auth_headers)
    assert r.status_code == 200, r.text
    enrollment = r.json()
    code = mfa_svc.totp_now(enrollment["secret"])
    verify = client.post("/api/v1/profile/mfa/verify", json={"code": code}, headers=auth_headers)
    assert verify.status_code == 200, verify.text
    return enrollment["backup_codes"]


def test_regenerate_codes_rejects_wrong_password(client, auth_headers):
    _enroll_mfa(client, auth_headers)
    r = client.post(
        "/api/v1/profile/mfa/regenerate-codes",
        json={"current_password": "WRONG"},
        headers=auth_headers,
    )
    assert r.status_code == 401


def test_regenerate_codes_rotates_codes(client, auth_headers, seeded_db):
    old_codes = _enroll_mfa(client, auth_headers)
    r = client.post(
        "/api/v1/profile/mfa/regenerate-codes",
        json={"current_password": "password123"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    new_codes = r.json()["backup_codes"]
    assert len(new_codes) == len(old_codes)
    assert set(new_codes).isdisjoint(set(old_codes))


def test_regenerate_codes_invalidates_old_codes(client, auth_headers, seeded_db):
    from wms.models import User

    old_codes = _enroll_mfa(client, auth_headers)
    client.post(
        "/api/v1/profile/mfa/regenerate-codes",
        json={"current_password": "password123"},
        headers=auth_headers,
    )
    # An old backup code should no longer verify
    user = seeded_db.query(User).first()
    assert mfa_svc.verify_user_code(seeded_db, user, old_codes[0]) is False


def test_regenerate_codes_requires_mfa_enabled(client, auth_headers):
    r = client.post(
        "/api/v1/profile/mfa/regenerate-codes",
        json={"current_password": "password123"},
        headers=auth_headers,
    )
    assert r.status_code == 400


# ── I-4: decision_notes max_length ────────────────────────────────────────


def test_approval_decision_accepts_500_chars():
    ApprovalDecision(approve=True, notes="x" * 500)


def test_approval_decision_rejects_501_chars():
    with pytest.raises(ValidationError):
        ApprovalDecision(approve=True, notes="x" * 501)


# ── L-1: AuditLog writer + key call sites ─────────────────────────────────


def test_audit_writer_inserts_row(seeded_db):
    audit_svc.record(seeded_db, event_type="test.event", detail={"k": "v"})
    rows = seeded_db.query(AuditLog).all()
    assert len(rows) == 1
    assert rows[0].event_type == "test.event"
    assert "k" in (rows[0].detail_json or "")


def test_login_success_emits_audit_event(client, seeded_db):
    seeded_db.query(AuditLog).delete()
    seeded_db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "password123", "site_id": "WHS-001"},
    )
    assert r.status_code == 200
    events = [e.event_type for e in seeded_db.query(AuditLog).all()]
    assert audit_svc.EVT_LOGIN_SUCCESS in events


def test_login_failure_emits_audit_event(client, seeded_db):
    seeded_db.query(AuditLog).delete()
    seeded_db.commit()
    r = client.post(
        "/api/v1/auth/login",
        json={"employee_code": "WHS-001-001", "password": "WRONG", "site_id": "WHS-001"},
    )
    assert r.status_code == 401
    events = [e.event_type for e in seeded_db.query(AuditLog).all()]
    assert audit_svc.EVT_LOGIN_FAILURE in events


def test_password_change_emits_audit_event(client, auth_headers, seeded_db):
    seeded_db.query(AuditLog).delete()
    seeded_db.commit()
    r = client.put(
        "/api/v1/profile/password",
        json={"current_password": "password123", "new_password": "newpass1!"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    events = [e.event_type for e in seeded_db.query(AuditLog).all()]
    assert audit_svc.EVT_PASSWORD_CHANGED in events


def test_mfa_disable_emits_audit_event(client, auth_headers, seeded_db):
    _enroll_mfa(client, auth_headers)
    seeded_db.query(AuditLog).delete()
    seeded_db.commit()
    r = client.post(
        "/api/v1/profile/mfa/disable",
        json={"current_password": "password123"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    events = [e.event_type for e in seeded_db.query(AuditLog).all()]
    assert audit_svc.EVT_MFA_DISABLED in events
    # UserMFA row removed
    assert seeded_db.query(UserMFA).count() == 0

"""Audit-log writer — security-relevant events go here.

SECURITY_AUDIT.md L-1 (pre-stage). Schema + writer ship together so the
SEC-6 follow-up (alerting, log shipping, dashboards) can light up without
touching the call sites again.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from wms.models import AuditLog

# Stable event-type constants. Adding new ones is fine; renaming existing
# ones is a breaking change for any downstream consumer of the log.
EVT_LOGIN_SUCCESS = "auth.login.success"
EVT_LOGIN_FAILURE = "auth.login.failure"
EVT_PASSWORD_CHANGED = "auth.password.changed"
EVT_MFA_DISABLED = "auth.mfa.disabled"
EVT_MFA_CODES_REGENERATED = "auth.mfa.backup_codes_regenerated"
EVT_ADMIN_PASSWORD_RESET = "auth.admin.password_reset"
EVT_ADMIN_LOCKOUT_CLEARED = "auth.admin.lockout_cleared"


def _client_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    if ua and len(ua) > 255:
        ua = ua[:255]
    return ip, ua


def record(
    db: Session,
    *,
    event_type: str,
    user_id: int | None = None,
    actor_id: int | None = None,
    site_id: str | None = None,
    request: Request | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    """Insert one audit row. `commit=False` lets callers piggy-back on an
    in-flight transaction without an extra round-trip — they own the commit."""
    ip, ua = _client_meta(request)
    row = AuditLog(
        event_type=event_type,
        user_id=user_id,
        actor_id=actor_id,
        site_id=site_id,
        ip=ip,
        user_agent=ua,
        detail_json=json.dumps(detail) if detail else None,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row

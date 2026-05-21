"""Profile business logic — visibility resolution + edits + approval workflow."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from wms.core.security import hash_password, verify_password
from wms.models import ProfileChangeRequest, User, UserProfileField
from wms.schemas.profile import PROFILE_FIELDS, FieldPolicy

# SECURITY_AUDIT.md M-7: conservative allowlist for display_picture URLs.
# Only accept relative paths produced by our sanitized upload pipeline.
# External http(s) / data: / javascript: / file: are all rejected — Referer
# leakage and inline-script vectors are off the table until product decides
# whether external avatars should be reopened (and with which allowlist).
_ALLOWED_PICTURE_PREFIXES = ("/uploads/avatars/",)


def _validate_picture_url(value: str) -> None:
    v = value.strip()
    if not v.startswith(_ALLOWED_PICTURE_PREFIXES):
        raise ValueError(
            "display_picture URL must be a relative /uploads/avatars/ path "
            "produced by the upload endpoint"
        )
    # Defense-in-depth: even within /uploads/, forbid traversal-style segments.
    if ".." in v or "//" in v[1:]:
        raise ValueError("display_picture URL contains invalid path segments")

DEFAULT_POLICY = {
    "email": FieldPolicy(visible=True, editable=True),
    "password": FieldPolicy(visible=True, editable=True),
    "display_name": FieldPolicy(visible=True, editable=True),
    "display_picture": FieldPolicy(visible=True, editable=True),
    "theme": FieldPolicy(visible=True, editable=False),
}

# Fields that require Level 3+ or direct-supervisor approval before applying.
APPROVAL_REQUIRED = {"display_name", "display_picture"}


def resolve_field_policy(db: Session, user: User) -> dict[str, FieldPolicy]:
    """Resolve effective policy per field by walking user → role → site → global. First match wins."""
    rows = (
        db.query(UserProfileField)
        .filter(UserProfileField.field_name.in_(PROFILE_FIELDS))
        .all()
    )

    # Index rows by (scope_type, scope_value, field_name)
    by_key: dict[tuple[str, str | None, str], UserProfileField] = {}
    for r in rows:
        by_key[(r.scope_type, r.scope_value, r.field_name)] = r

    precedence = [
        ("user", user.employee_code),
        ("role", user.role),
        ("site", user.site_id),
        ("global", None),
    ]

    policy: dict[str, FieldPolicy] = {}
    for field in PROFILE_FIELDS:
        chosen: UserProfileField | None = None
        for scope_type, scope_value in precedence:
            chosen = by_key.get((scope_type, scope_value, field))
            if chosen is not None:
                break
        if chosen is not None:
            policy[field] = FieldPolicy(visible=chosen.visible, editable=chosen.editable)
        else:
            policy[field] = DEFAULT_POLICY[field]
    return policy


def pending_request_fields(db: Session, user_id: int) -> list[str]:
    rows = (
        db.query(ProfileChangeRequest.field_name)
        .filter(ProfileChangeRequest.user_id == user_id, ProfileChangeRequest.status == "pending")
        .all()
    )
    return [r[0] for r in rows]


def update_email(db: Session, user: User, new_email: str) -> User:
    user.email = new_email
    db.commit()
    db.refresh(user)
    return user


def update_password(db: Session, user: User, current: str, new: str) -> User:
    if not verify_password(current, user.hashed_password):
        raise ValueError("Current password is incorrect")
    if current == new:
        # SCO-99: prevents trivially "rotating" the temp password to itself.
        raise ValueError("New password must differ from the current one")
    user.hashed_password = hash_password(new)
    # SCO-99: any successful self-service password change clears the
    # force-change flag, releasing the rest of the app to the user.
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    return user


def submit_change_request(
    db: Session, user: User, field_name: str, requested_value: str
) -> ProfileChangeRequest:
    if field_name not in APPROVAL_REQUIRED:
        raise ValueError(f"{field_name} does not require approval — update directly")
    if field_name == "display_picture":
        _validate_picture_url(requested_value)
    req = ProfileChangeRequest(
        user_id=user.id, field_name=field_name, requested_value=requested_value
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def list_my_requests(db: Session, user: User) -> list[ProfileChangeRequest]:
    return (
        db.query(ProfileChangeRequest)
        .filter(ProfileChangeRequest.user_id == user.id)
        .order_by(ProfileChangeRequest.requested_at.desc())
        .all()
    )


def list_pending_for_approver(db: Session, approver: User) -> list[ProfileChangeRequest]:
    """Approver sees all pending requests at their site (or all sites if MCS admin)."""
    q = db.query(ProfileChangeRequest).filter(ProfileChangeRequest.status == "pending")
    if approver.site_id != "MCS":
        # Filter to requests by users at the same site
        q = q.join(User, User.id == ProfileChangeRequest.user_id).filter(User.site_id == approver.site_id)
    return q.order_by(ProfileChangeRequest.requested_at.asc()).all()


def decide_request(
    db: Session, approver: User, request_id: int, approve: bool, notes: str | None
) -> ProfileChangeRequest:
    if approver.permission_level < 3:
        raise PermissionError("Decision requires permission level 3 or higher")

    req = db.query(ProfileChangeRequest).filter(ProfileChangeRequest.id == request_id).one()
    if req.status != "pending":
        raise ValueError(f"Request already {req.status}")

    requester = db.query(User).filter(User.id == req.user_id).one()
    # Supervisors are also allowed even at lower levels (future: check supervisor_id link)
    if approver.site_id != "MCS" and requester.site_id != approver.site_id:
        raise PermissionError("Approver must be at the same site")

    req.status = "approved" if approve else "rejected"
    req.decided_by = approver.id
    req.decided_at = datetime.now(UTC)
    req.decision_notes = notes

    if approve:
        if req.field_name == "display_name":
            requester.display_name = req.requested_value
        elif req.field_name == "display_picture":
            requester.display_picture_url = req.requested_value

    db.commit()
    db.refresh(req)
    return req

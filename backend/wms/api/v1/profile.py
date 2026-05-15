"""Profile router — read identity + edit settings + approval workflow."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import User, UserProfileField
from wms.schemas.profile import (
    PROFILE_FIELDS,
    ApprovalDecision,
    ChangeRequestOut,
    DisplayChangeRequest,
    EmailUpdate,
    FieldVisibilityRule,
    PasswordUpdate,
    ProfileOut,
)
from wms.services import profile as svc

router = APIRouter(prefix="/profile", tags=["profile"])
admin_router = APIRouter(prefix="/admin/profile", tags=["admin-profile"])


@router.get("", response_model=ProfileOut)
def get_profile(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> ProfileOut:
    policy = svc.resolve_field_policy(db, user)
    pending = svc.pending_request_fields(db, user.id)
    return ProfileOut(
        id=user.id,
        employee_code=user.employee_code,
        full_name=user.full_name,
        site_id=user.site_id,
        department=user.department,
        role=user.role,
        shift=user.shift,
        permission_level=user.permission_level,
        email=user.email,
        display_name=user.display_name,
        display_picture_url=user.display_picture_url,
        theme=user.theme,
        field_policy=policy,
        pending_requests=pending,
    )


def _ensure_editable(db: Session, user: User, field: str) -> None:
    policy = svc.resolve_field_policy(db, user)
    f = policy.get(field)
    if f is None or not f.editable:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Field '{field}' is not editable for you")


@router.put("/email", response_model=ProfileOut)
def update_email(
    payload: EmailUpdate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProfileOut:
    _ensure_editable(db, user, "email")
    svc.update_email(db, user, payload.email)
    return get_profile(db, user)


@router.put("/password")
def update_password(
    payload: PasswordUpdate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    _ensure_editable(db, user, "password")
    try:
        svc.update_password(db, user, payload.current_password, payload.new_password)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"ok": True}


@router.post("/display-name-request", response_model=ChangeRequestOut)
def request_display_name(
    payload: DisplayChangeRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChangeRequestOut:
    _ensure_editable(db, user, "display_name")
    req = svc.submit_change_request(db, user, "display_name", payload.requested_value)
    return req


@router.post("/display-picture-request", response_model=ChangeRequestOut)
def request_display_picture(
    payload: DisplayChangeRequest,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChangeRequestOut:
    _ensure_editable(db, user, "display_picture")
    req = svc.submit_change_request(db, user, "display_picture", payload.requested_value)
    return req


@router.get("/requests", response_model=list[ChangeRequestOut])
def list_my_requests(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[ChangeRequestOut]:
    return svc.list_my_requests(db, user)


# ── ADMIN / APPROVER ENDPOINTS ────────────────────────────────────────────


@admin_router.get("/requests", response_model=list[ChangeRequestOut])
def list_pending_requests(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[ChangeRequestOut]:
    if user.permission_level < 3:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Level 3+ required")
    return svc.list_pending_for_approver(db, user)


@admin_router.post("/requests/{request_id}/decide", response_model=ChangeRequestOut)
def decide_request(
    request_id: int,
    payload: ApprovalDecision,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ChangeRequestOut:
    try:
        return svc.decide_request(db, user, request_id, payload.approve, payload.notes)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@admin_router.get("/field-visibility", response_model=list[FieldVisibilityRule])
def list_field_visibility(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[FieldVisibilityRule]:
    if user.permission_level < 3:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Level 3+ required")
    return db.query(UserProfileField).order_by(UserProfileField.field_name).all()


@admin_router.put("/field-visibility", response_model=FieldVisibilityRule)
def upsert_field_visibility(
    payload: FieldVisibilityRule,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> UserProfileField:
    if user.permission_level < 3:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Level 3+ required")
    if payload.field_name not in PROFILE_FIELDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown field: {payload.field_name}")

    existing = (
        db.query(UserProfileField)
        .filter(
            UserProfileField.scope_type == payload.scope_type,
            UserProfileField.scope_value == payload.scope_value,
            UserProfileField.field_name == payload.field_name,
        )
        .first()
    )
    if existing:
        existing.visible = payload.visible
        existing.editable = payload.editable
        db.commit()
        db.refresh(existing)
        return existing
    row = UserProfileField(
        scope_type=payload.scope_type,
        scope_value=payload.scope_value,
        field_name=payload.field_name,
        visible=payload.visible,
        editable=payload.editable,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

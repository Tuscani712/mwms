"""Admin user-management endpoints — CRUD + listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.core.security import assert_password_bcrypt_safe, hash_password
from wms.models import User
from wms.services import audit_log as audit
from wms.services import hierarchy as hier_svc
from wms.services import login_guard as guard
from wms.services import users_admin as svc

# SECURITY_AUDIT.md M-6: permissive but real format check — rejects obvious
# garbage and script-tag payloads without inheriting EmailStr's TLD strictness
# (which previously broke our .local dev domains).
EMAIL_PATTERN = r"^[^\s<>\"']+@[^\s<>\"']+\.[^\s<>\"']+$"

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class UserCreate(BaseModel):
    employee_code: str = Field(min_length=2, max_length=20)
    email: str = Field(min_length=3, max_length=180, pattern=EMAIL_PATTERN)
    full_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="operator", max_length=40)
    # SCO-80: permission_level is now optional. When omitted, the service
    # derives it from the linked Role's default_permission_level. Admin can
    # still pass an explicit value to override (interim leadership case).
    permission_level: int | None = Field(default=None, ge=1, le=5)
    password: str = Field(min_length=4, max_length=128)
    site_id: str | None = None  # defaults to caller's site
    department: str | None = None
    shift: str | None = None
    # SCO-80: org-metadata FKs (preferred over the free strings above).
    role_id: int | None = None
    department_id: int | None = None
    shift_id: int | None = None
    # SCO-104: job title — either curated (title_id) or free-text (custom_title).
    # UI enforces mutual exclusion; backend renders custom_title with precedence.
    title_id: int | None = None
    custom_title: str | None = Field(default=None, max_length=60)

    @field_validator("password")
    @classmethod
    def _bcrypt_byte_limit(cls, v: str) -> str:
        # SECURITY_AUDIT.md M-1: reject UTF-8 > 72 bytes instead of silent truncation.
        assert_password_bcrypt_safe(v)
        return v


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=180, pattern=EMAIL_PATTERN)
    full_name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=40)
    permission_level: int | None = Field(default=None, ge=1, le=5)
    department: str | None = None
    shift: str | None = None
    role_id: int | None = None
    department_id: int | None = None
    shift_id: int | None = None
    title_id: int | None = None
    custom_title: str | None = Field(default=None, max_length=60)


class UserAdminOut(BaseModel):
    id: int
    site_id: str
    employee_code: str
    email: str
    full_name: str
    role: str
    permission_level: int
    department: str | None
    shift: str | None
    role_id: int | None = None
    department_id: int | None = None
    shift_id: int | None = None
    title_id: int | None = None
    custom_title: str | None = None
    is_active: bool
    supervisor_id: int | None
    # Resolved supervisor full_name. Frontend renders this directly in the
    # table; supervisor_id is still useful for hierarchy logic and form prefill.
    supervisor_name: str | None = None
    display_name: str | None

    model_config = {"from_attributes": True}


def _serialize_one(db: Session, user: User) -> UserAdminOut:
    """Build a UserAdminOut for a single user, resolving supervisor_name."""
    out = UserAdminOut.model_validate(user)
    if user.supervisor_id is not None:
        sup = db.query(User.full_name).filter(User.id == user.supervisor_id).first()
        out.supervisor_name = sup[0] if sup else None
    return out


def _serialize_many(db: Session, users: list[User]) -> list[UserAdminOut]:
    """Batch-resolve supervisor names for a page of users — one IN() query."""
    ids = {u.supervisor_id for u in users if u.supervisor_id is not None}
    name_by_id: dict[int, str] = {}
    if ids:
        rows = db.query(User.id, User.full_name).filter(User.id.in_(ids)).all()
        name_by_id = {row[0]: row[1] for row in rows}
    out_list: list[UserAdminOut] = []
    for u in users:
        out = UserAdminOut.model_validate(u)
        if u.supervisor_id is not None:
            out.supervisor_name = name_by_id.get(u.supervisor_id)
        out_list.append(out)
    return out_list


class UserListResponse(BaseModel):
    items: list[UserAdminOut]
    total: int
    limit: int
    offset: int


def _load_target(db: Session, user_id: int) -> User:
    target = db.query(User).filter(User.id == user_id).one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return target


@router.get("", response_model=UserListResponse)
def list_users(
    site_id: str | None = Query(default=None),
    role: str | None = Query(default=None),
    level_min: int | None = Query(default=None, ge=1, le=5),
    level_max: int | None = Query(default=None, ge=1, le=5),
    q: str | None = Query(default=None, description="Search by code, name, or email"),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UserListResponse:
    try:
        items, total = svc.list_users(
            db,
            caller,
            site_id=site_id,
            role=role,
            level_min=level_min,
            level_max=level_max,
            search=q,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return UserListResponse(
        items=_serialize_many(db, items), total=total, limit=limit, offset=offset
    )


@router.post("", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UserAdminOut:
    try:
        created = svc.create_user(db, caller, payload=payload.model_dump())
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _serialize_one(db, created)


@router.get("/{user_id}", response_model=UserAdminOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UserAdminOut:
    target = _load_target(db, user_id)
    # Visibility: same rules as list. Reuse assert_can_manage for the read gate
    # except we don't require strict outranking for a *read*.
    try:
        svc.require_admin(caller)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    if caller.site_id != svc.MCS_SITE_ID and target.site_id != caller.site_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-site read requires MCS admin")
    return _serialize_one(db, target)


@router.put("/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UserAdminOut:
    target = _load_target(db, user_id)
    try:
        updated = svc.update_user(db, caller, target, payload.model_dump(exclude_unset=True))
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        # SCO-80: FK validation errors (cross-site dept/shift, missing entity)
        # propagate as 400 — same shape as create_user's wrapper.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _serialize_one(db, updated)


@router.delete("/{user_id}", response_model=UserAdminOut)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UserAdminOut:
    target = _load_target(db, user_id)
    try:
        deactivated = svc.deactivate_user(db, caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return _serialize_one(db, deactivated)


@router.post("/{user_id}/reactivate", response_model=UserAdminOut)
def reactivate_user(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UserAdminOut:
    target = _load_target(db, user_id)
    try:
        reactivated = svc.reactivate_user(db, caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return _serialize_one(db, reactivated)


# ── SEC-1: admin password reset + lockout clear ───────────────────────


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)
    force_change_on_next_login: bool = True

    @field_validator("new_password")
    @classmethod
    def _bcrypt_byte_limit(cls, v: str) -> str:
        assert_password_bcrypt_safe(v)
        return v


class ResetPasswordResponse(BaseModel):
    user_id: int
    employee_code: str
    must_change_password: bool


class UnlockResponse(BaseModel):
    user_id: int
    employee_code: str
    cleared: bool


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
def admin_reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> ResetPasswordResponse:
    """Admin sets a new password for a user. Defaults to forcing change on next login."""
    target = _load_target(db, user_id)
    try:
        svc.assert_can_manage(caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e

    target.hashed_password = hash_password(payload.new_password)
    target.must_change_password = payload.force_change_on_next_login
    audit.record(
        db,
        event_type=audit.EVT_ADMIN_PASSWORD_RESET,
        user_id=target.id,
        actor_id=caller.id,
        site_id=target.site_id,
        request=request,
        detail={"force_change": payload.force_change_on_next_login},
        commit=False,
    )
    # Also drop a lockout-reset marker so the user isn't immediately bounced.
    guard.record_admin_unlock(
        db,
        employee_code=target.employee_code,
        site_id=target.site_id,
        ip=request.client.host if request.client else None,
    )
    return ResetPasswordResponse(
        user_id=target.id,
        employee_code=target.employee_code,
        must_change_password=target.must_change_password,
    )


@router.post("/{user_id}/unlock", response_model=UnlockResponse)
def admin_unlock_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> UnlockResponse:
    """Clear the per-account lockout for a user. Idempotent."""
    target = _load_target(db, user_id)
    try:
        svc.assert_can_manage(caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e

    guard.record_admin_unlock(
        db,
        employee_code=target.employee_code,
        site_id=target.site_id,
        ip=request.client.host if request.client else None,
    )
    audit.record(
        db,
        event_type=audit.EVT_ADMIN_LOCKOUT_CLEARED,
        user_id=target.id,
        actor_id=caller.id,
        site_id=target.site_id,
        request=request,
        commit=True,
    )
    return UnlockResponse(
        user_id=target.id, employee_code=target.employee_code, cleared=True
    )


# ── Bulk purge (SCO-89/90) ────────────────────────────────────────────
#
# Declared BEFORE /{user_id}/purge so /admin/users/bulk-purge matches this
# route. FastAPI would still skip the int-typed /{user_id} on a string
# segment, but ordering by specificity is clearer.

BULK_PURGE_MAX = 200


class BulkPurgeRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=BULK_PURGE_MAX)


class BulkPurgeFailure(BaseModel):
    user_id: int
    reason: str


class BulkPurgeResponse(BaseModel):
    bulk_operation_id: str
    requested: int
    purged: list[int]
    failed: list[BulkPurgeFailure]


@router.post(
    "/bulk-purge",
    response_model=BulkPurgeResponse,
    summary="Permanently delete a batch of users (Lvl 5 only) — IRREVERSIBLE",
    description=(
        "Bulk counterpart of POST /admin/users/{id}/purge. Iterates the given "
        "ids, applying the same per-row safety rails (self-purge, last-admin, "
        "active subordinates, hierarchy). Partial failures are itemized in "
        "the `failed` array instead of aborting the batch.\n\n"
        "Returns 200 if every id purged, 207 Multi-Status if any failed. "
        "Batch capped at 200 ids; over that returns 422. Each successful "
        "purge emits a `user.purged` audit event tagged with a shared "
        "`bulk_operation_id` so the batch is queryable as one action."
    ),
    responses={
        200: {"description": "All requested users purged"},
        207: {"description": "Some users purged, others failed — see `failed`"},
        403: {"description": "Caller is not Lvl 5"},
        422: {"description": "Invalid payload (empty, > 200 ids, malformed)"},
    },
)
def bulk_purge_users(
    payload: BulkPurgeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> BulkPurgeResponse:
    """Bulk hard-delete. Lvl 5 only, per-row enforcement, partial-failure tolerant.

    Frontend gates this behind ONE typed-DELETE confirmation for the entire
    batch (the per-row safety rails are still enforced server-side).
    """
    if caller.permission_level < 5:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Level 5 required to permanently delete users"
        )

    import uuid

    from wms.services import audit_log

    bulk_id = uuid.uuid4().hex
    purged: list[int] = []
    failed: list[BulkPurgeFailure] = []
    # De-dupe input so a repeated id can't claim two slots in the response.
    seen: set[int] = set()
    ordered_ids = [i for i in payload.user_ids if not (i in seen or seen.add(i))]

    for uid in ordered_ids:
        target = db.query(User).filter(User.id == uid).one_or_none()
        if target is None:
            failed.append(BulkPurgeFailure(user_id=uid, reason="not_found"))
            continue
        try:
            snapshot = svc.purge_user(db, caller, target)
        except svc.AdminAuthorizationError as e:
            msg = str(e)
            # Map service-layer messages to stable machine codes for the UI.
            if "yourself" in msg:
                reason = "cannot_delete_self"
            elif "last Level 5" in msg:
                reason = "last_admin_protection"
            else:
                reason = "hierarchy_violation"
            failed.append(BulkPurgeFailure(user_id=uid, reason=reason))
            continue
        except ValueError as e:
            reason = "has_subordinates" if "subordinate" in str(e) else "conflict"
            failed.append(BulkPurgeFailure(user_id=uid, reason=reason))
            continue
        snapshot["bulk_operation_id"] = bulk_id
        audit_log.record(
            db,
            event_type="user.purged",
            actor_id=caller.id,
            site_id=snapshot["site_id"],
            request=request,
            detail=snapshot,
        )
        purged.append(uid)

    if failed:
        response.status_code = status.HTTP_207_MULTI_STATUS
    return BulkPurgeResponse(
        bulk_operation_id=bulk_id,
        requested=len(ordered_ids),
        purged=purged,
        failed=failed,
    )


@router.post(
    "/{user_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete a user (Lvl 5 only) — IRREVERSIBLE",
    description=(
        "Hard-delete a user row. Distinct from DELETE /admin/users/{id} which is a soft-archive.\n\n"
        "Refuses self-purge, the last active Lvl 5 admin (system-lockout protection), and "
        "users with active subordinates (must be reassigned first). Audit log rows owned or "
        "authored by the target have their FK pointers NULLed so the trail survives. UserMFA "
        "and ProfileChangeRequest rows owned by the user cascade-delete.\n\n"
        "Emits the `user.purged` audit event with full snapshot in detail_json before the "
        "row is removed."
    ),
    responses={
        204: {"description": "User permanently deleted"},
        403: {"description": "Caller is not Lvl 5, or is attempting to delete themselves"},
        409: {"description": "User has active subordinates — reassign them first"},
        404: {"description": "User not found"},
    },
)
def purge_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    """Hard-delete a user. Irreversible. Lvl 5 only.

    The frontend gates this behind a typed-DELETE confirmation modal; the
    server still enforces all the safety rails independently.
    """
    target = _load_target(db, user_id)
    try:
        snapshot = svc.purge_user(db, caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    from wms.services import audit_log

    audit_log.record(
        db,
        event_type="user.purged",
        actor_id=caller.id,
        site_id=snapshot["site_id"],
        request=request,
        detail=snapshot,
    )
    return None


# ── Hierarchy + assignment endpoints (SCO-36) ──────────────────────────


class SupervisorAssign(BaseModel):
    supervisor_id: int | None = None  # None clears the link


class DepartmentTransfer(BaseModel):
    department: str | None = Field(default=None, max_length=60)


class ShiftChange(BaseModel):
    shift: str | None = Field(default=None, max_length=20)


class SiteChange(BaseModel):
    site_id: str = Field(min_length=1, max_length=20)


class SiteChangeResponse(BaseModel):
    user: UserAdminOut
    cleared_fields: list[str]


class HierarchyInfo(BaseModel):
    id: int
    employee_code: str
    full_name: str
    role: str
    permission_level: int
    tier_label: str
    supervisor_id: int | None
    site_id: str

    model_config = {"from_attributes": True}


def _to_hier(u: User) -> HierarchyInfo:
    return HierarchyInfo(
        id=u.id,
        employee_code=u.employee_code,
        full_name=u.full_name,
        role=u.role,
        permission_level=u.permission_level,
        tier_label=hier_svc.tier_label(u.permission_level),
        supervisor_id=u.supervisor_id,
        site_id=u.site_id,
    )


@router.put("/{user_id}/supervisor", response_model=HierarchyInfo)
def assign_supervisor(
    user_id: int,
    payload: SupervisorAssign,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> HierarchyInfo:
    target = _load_target(db, user_id)
    try:
        updated = hier_svc.assign_supervisor(db, caller, target, payload.supervisor_id)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _to_hier(updated)


@router.put("/{user_id}/department", response_model=UserAdminOut)
def transfer_department(
    user_id: int,
    payload: DepartmentTransfer,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    target = _load_target(db, user_id)
    try:
        return hier_svc.transfer_department(db, caller, target, payload.department)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e


@router.put("/{user_id}/shift", response_model=UserAdminOut)
def change_shift(
    user_id: int,
    payload: ShiftChange,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    target = _load_target(db, user_id)
    try:
        return hier_svc.change_shift(db, caller, target, payload.shift)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e


# SCO-113: dedicated endpoint for moving a user across sites. Distinct from
# PUT /admin/users/{id} so the destructive nature (clears site-scoped FKs) is
# explicit at the route level. MCS-Lvl4+ only — see svc.change_user_site.
@router.put("/{user_id}/site", response_model=SiteChangeResponse)
def change_user_site(
    user_id: int,
    payload: SiteChange,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> SiteChangeResponse:
    target = _load_target(db, user_id)
    try:
        updated, cleared = svc.change_user_site(db, caller, target, payload.site_id)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return SiteChangeResponse(user=UserAdminOut.model_validate(updated), cleared_fields=cleared)


@router.get("/{user_id}/subordinates", response_model=list[HierarchyInfo])
def list_subordinates(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> list[HierarchyInfo]:
    target = _load_target(db, user_id)
    try:
        rows = hier_svc.list_subordinates(db, caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return [_to_hier(u) for u in rows]


@router.get("/tiers/labels")
def tier_labels(_: User = Depends(get_current_user)) -> dict[int, str]:
    """Static reference data for the admin UI's role/level picker."""
    return hier_svc.TIER_LABELS

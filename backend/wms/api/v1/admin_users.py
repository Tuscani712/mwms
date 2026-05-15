"""Admin user-management endpoints — CRUD + listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import User
from wms.services import users_admin as svc

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class UserCreate(BaseModel):
    employee_code: str = Field(min_length=2, max_length=20)
    email: str = Field(min_length=3, max_length=180)
    full_name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="operator", max_length=40)
    permission_level: int = Field(ge=1, le=5, default=1)
    password: str = Field(min_length=4, max_length=128)
    site_id: str | None = None  # defaults to caller's site
    department: str | None = None
    shift: str | None = None


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=40)
    permission_level: int | None = Field(default=None, ge=1, le=5)
    department: str | None = None
    shift: str | None = None


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
    is_active: bool
    supervisor_id: int | None
    display_name: str | None

    model_config = {"from_attributes": True}


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
    return UserListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    try:
        return svc.create_user(db, caller, payload=payload.model_dump())
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/{user_id}", response_model=UserAdminOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    target = _load_target(db, user_id)
    # Visibility: same rules as list. Reuse assert_can_manage for the read gate
    # except we don't require strict outranking for a *read*.
    try:
        svc.require_admin(caller)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    if caller.site_id != svc.MCS_SITE_ID and target.site_id != caller.site_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-site read requires MCS admin")
    return target


@router.put("/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    target = _load_target(db, user_id)
    try:
        return svc.update_user(db, caller, target, payload.model_dump(exclude_unset=True))
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e


@router.delete("/{user_id}", response_model=UserAdminOut)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    target = _load_target(db, user_id)
    try:
        return svc.deactivate_user(db, caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e


@router.post("/{user_id}/reactivate", response_model=UserAdminOut)
def reactivate_user(
    user_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> User:
    target = _load_target(db, user_id)
    try:
        return svc.reactivate_user(db, caller, target)
    except svc.AdminAuthorizationError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e

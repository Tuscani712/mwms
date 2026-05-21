"""Admin org-metadata endpoints: /admin/roles, /admin/departments, /admin/shifts (SCO-79)."""

from __future__ import annotations

from datetime import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import Department, Role, Shift, Title, User
from wms.services import orgmeta as svc


# ── Schemas ───────────────────────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    default_permission_level: int = Field(ge=1, le=5)
    site_id: str | None = None  # null = global template


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    default_permission_level: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None


class RoleOut(BaseModel):
    id: int
    name: str
    default_permission_level: int
    site_id: str | None
    is_active: bool
    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    site_id: str | None = None  # defaults to caller's site


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    site_id: str
    is_active: bool
    model_config = {"from_attributes": True}


class ShiftCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    start_time: time
    end_time: time
    site_id: str | None = None


class ShiftUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    start_time: time | None = None
    end_time: time | None = None
    is_active: bool | None = None


class ShiftOut(BaseModel):
    id: int
    name: str
    site_id: str
    start_time: time
    end_time: time
    is_active: bool
    model_config = {"from_attributes": True}


# SCO-100: Titles.
class TitleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    site_id: str | None = None  # null = global title


class TitleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None


class TitleOut(BaseModel):
    id: int
    name: str
    site_id: str | None
    is_active: bool
    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────

def _load_role(db: Session, role_id: int) -> Role:
    role = db.query(Role).filter(Role.id == role_id).one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


def _load_dept(db: Session, dept_id: int) -> Department:
    dept = db.query(Department).filter(Department.id == dept_id).one_or_none()
    if dept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    return dept


def _load_shift(db: Session, shift_id: int) -> Shift:
    shift = db.query(Shift).filter(Shift.id == shift_id).one_or_none()
    if shift is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shift not found")
    return shift


def _load_title(db: Session, title_id: int) -> Title:
    title = db.query(Title).filter(Title.id == title_id).one_or_none()
    if title is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Title not found")
    return title


def _gate(e: Exception) -> HTTPException:
    if isinstance(e, svc.OrgMetaAuthorizationError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    # SCO-107: in-use hard-delete attempts surface as 409 with ref_count so
    # the UI can render "In use by N users" without a separate count call.
    if isinstance(e, svc.OrgMetaInUseError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"detail": str(e), "ref_count": e.ref_count, "entity": e.entity},
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


# ── /admin/roles ──────────────────────────────────────────────────────────

roles_router = APIRouter(prefix="/admin/roles", tags=["admin-roles"])


@roles_router.get("", response_model=list[RoleOut])
def list_roles(
    site_id: str | None = Query(default=None),
    include_globals: bool = Query(default=True),
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    try:
        return svc.list_roles(db, caller, site_id=site_id, include_globals=include_globals)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@roles_router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    try:
        return svc.create_role(db, caller, **payload.model_dump())
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@roles_router.put("/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    role = _load_role(db, role_id)
    try:
        return svc.update_role(db, caller, role, payload.model_dump(exclude_unset=True))
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@roles_router.delete("/{role_id}", response_model=RoleOut)
def deactivate_role(
    role_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    role = _load_role(db, role_id)
    try:
        return svc.deactivate_role(db, caller, role)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@roles_router.delete("/{role_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_role(
    role_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    """Hard-delete the role. 409 if any user still references it (SCO-107)."""
    role = _load_role(db, role_id)
    try:
        svc.purge_role(db, caller, role)
    except (svc.OrgMetaAuthorizationError, svc.OrgMetaInUseError) as e:
        raise _gate(e) from e


# ── /admin/departments ────────────────────────────────────────────────────

departments_router = APIRouter(prefix="/admin/departments", tags=["admin-departments"])


@departments_router.get("", response_model=list[DepartmentOut])
def list_departments(
    site_id: str | None = Query(default=None),
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    try:
        return svc.list_departments(db, caller, site_id=site_id)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@departments_router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    site_id = payload.site_id or caller.site_id
    try:
        return svc.create_department(db, caller, name=payload.name, site_id=site_id)
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@departments_router.put("/{dept_id}", response_model=DepartmentOut)
def update_department(
    dept_id: int,
    payload: DepartmentUpdate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    dept = _load_dept(db, dept_id)
    try:
        return svc.update_department(db, caller, dept, payload.model_dump(exclude_unset=True))
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@departments_router.delete("/{dept_id}", response_model=DepartmentOut)
def deactivate_department(
    dept_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    dept = _load_dept(db, dept_id)
    try:
        return svc.deactivate_department(db, caller, dept)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@departments_router.delete("/{dept_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_department(
    dept_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    dept = _load_dept(db, dept_id)
    try:
        svc.purge_department(db, caller, dept)
    except (svc.OrgMetaAuthorizationError, svc.OrgMetaInUseError) as e:
        raise _gate(e) from e


# ── /admin/shifts ─────────────────────────────────────────────────────────

shifts_router = APIRouter(prefix="/admin/shifts", tags=["admin-shifts"])


@shifts_router.get("", response_model=list[ShiftOut])
def list_shifts(
    site_id: str | None = Query(default=None),
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    try:
        return svc.list_shifts(db, caller, site_id=site_id)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@shifts_router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(
    payload: ShiftCreate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    site_id = payload.site_id or caller.site_id
    try:
        return svc.create_shift(
            db, caller,
            name=payload.name,
            site_id=site_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@shifts_router.put("/{shift_id}", response_model=ShiftOut)
def update_shift(
    shift_id: int,
    payload: ShiftUpdate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    shift = _load_shift(db, shift_id)
    try:
        return svc.update_shift(db, caller, shift, payload.model_dump(exclude_unset=True))
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@shifts_router.delete("/{shift_id}", response_model=ShiftOut)
def deactivate_shift(
    shift_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    shift = _load_shift(db, shift_id)
    try:
        return svc.deactivate_shift(db, caller, shift)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@shifts_router.delete("/{shift_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_shift(
    shift_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    shift = _load_shift(db, shift_id)
    try:
        svc.purge_shift(db, caller, shift)
    except (svc.OrgMetaAuthorizationError, svc.OrgMetaInUseError) as e:
        raise _gate(e) from e


# ── /admin/titles (SCO-100) ───────────────────────────────────────────────

titles_router = APIRouter(prefix="/admin/titles", tags=["admin-titles"])


@titles_router.get("", response_model=list[TitleOut])
def list_titles(
    site_id: str | None = Query(default=None),
    include_globals: bool = Query(default=True),
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    try:
        return svc.list_titles(db, caller, site_id=site_id, include_globals=include_globals)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@titles_router.post("", response_model=TitleOut, status_code=status.HTTP_201_CREATED)
def create_title(
    payload: TitleCreate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    try:
        return svc.create_title(db, caller, name=payload.name, site_id=payload.site_id)
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@titles_router.put("/{title_id}", response_model=TitleOut)
def update_title(
    title_id: int,
    payload: TitleUpdate,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    title = _load_title(db, title_id)
    try:
        return svc.update_title(db, caller, title, payload.model_dump(exclude_unset=True))
    except (svc.OrgMetaAuthorizationError, ValueError) as e:
        raise _gate(e) from e


@titles_router.delete("/{title_id}", response_model=TitleOut)
def deactivate_title(
    title_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    """Soft-deactivate. Use /{title_id}/purge for hard-delete."""
    title = _load_title(db, title_id)
    try:
        return svc.deactivate_title(db, caller, title)
    except svc.OrgMetaAuthorizationError as e:
        raise _gate(e) from e


@titles_router.delete("/{title_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_title(
    title_id: int,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
):
    """Hard-delete. 409 if any user still references the title (SCO-100)."""
    title = _load_title(db, title_id)
    try:
        svc.purge_title(db, caller, title)
    except (svc.OrgMetaAuthorizationError, svc.OrgMetaInUseError) as e:
        raise _gate(e) from e

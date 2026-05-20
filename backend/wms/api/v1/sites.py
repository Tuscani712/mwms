"""Sites router — list + manage sites.

Read endpoints stay open to any authenticated session (login picker, header
status ticker). Write endpoints are gated to a caller that is (a) on the
master site and (b) has the required permission level. Audit events are
emitted for every state-mutating call.
"""

from __future__ import annotations

import re
import time as _time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import Site, User
from wms.models.orgmeta import Department
from wms.services import audit_log

router = APIRouter(prefix="/sites", tags=["sites"])

# Site IDs are short codes like "WHS-001", "MCS". Strict enough to keep them
# URL-safe and grep-friendly without locking us out of legitimate corporate
# naming schemes.
SITE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{1,31}$")

# Per PAGES_WORKFLOW §SCO-53: flipping `is_online` invalidates tokens for that
# site, which is destabilizing if abused. A minimum interval between toggles
# protects against flap. Last-toggle timestamps live in-process — multi-worker
# deployments need a shared store, flagged but not pre-built.
TOGGLE_COOLDOWN_SECONDS = 60
_last_toggle_at: dict[str, float] = {}


# ── Schemas ──────────────────────────────────────────────────────────────

class SiteOut(BaseModel):
    id: str
    name: str
    city: str
    is_master: bool
    is_online: bool
    build_version: str

    model_config = {"from_attributes": True}


class SiteCreate(BaseModel):
    id: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=80)
    timezone: str = Field(default="America/Chicago", max_length=40)
    is_master: bool = False
    is_online: bool = True
    build_version: str = Field(default="v0.1.0", max_length=20)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=40)
    build_version: str | None = Field(default=None, max_length=20)


class SiteDetail(SiteOut):
    timezone: str
    created_at: datetime
    user_count: int
    department_count: int


# ── Authorization ────────────────────────────────────────────────────────

def _require_master_admin(db: Session, caller: User, *, min_level: int = 5) -> None:
    """Master-site admin gate. Mutating sites is a corporate operation."""
    if caller.permission_level < min_level:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Level {min_level}+ required to manage sites",
        )
    master = db.scalar(select(Site).where(Site.is_master.is_(True)))
    if master is None or caller.site_id != master.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Site management is only available from the master site",
        )


def _load(db: Session, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    return site


def _counts(db: Session, site_id: str) -> tuple[int, int]:
    user_count = db.scalar(select(func.count(User.id)).where(User.site_id == site_id)) or 0
    dept_count = db.scalar(select(func.count(Department.id)).where(Department.site_id == site_id)) or 0
    return int(user_count), int(dept_count)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[SiteOut],
    summary="List all sites",
    description="Open to unauthenticated callers — used by the login picker and the header status ticker. Returns master site first, then alphabetical by id.",
)
def list_sites(db: Session = Depends(get_session)) -> list[Site]:
    return db.query(Site).order_by(Site.is_master.desc(), Site.id).all()


@router.get(
    "/{site_id}",
    response_model=SiteDetail,
    summary="Get site detail with reference counts",
    description="Returns a single site plus user_count and department_count, used by the admin Sites page to surface which sites have dependent records.",
)
def get_site(
    site_id: str,
    db: Session = Depends(get_session),
    _caller: User = Depends(get_current_user),
) -> SiteDetail:
    site = _load(db, site_id)
    users, depts = _counts(db, site_id)
    return SiteDetail(
        id=site.id,
        name=site.name,
        city=site.city,
        timezone=site.timezone,
        is_master=site.is_master,
        is_online=site.is_online,
        build_version=site.build_version,
        created_at=site.created_at,
        user_count=users,
        department_count=depts,
    )


@router.post(
    "",
    response_model=SiteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new site (MCS Lvl 5 only)",
    description="Provision a new warehouse/plant/DC. Caller must be on the master site with permission_level=5. Site id must match `^[A-Z][A-Z0-9-]{1,31}$` and be unique. Only one master site is permitted.",
    responses={
        409: {"description": "Site id already exists, or a master site already exists when is_master=true"},
        400: {"description": "Site id fails the format regex"},
        403: {"description": "Caller is not on the master site or has insufficient permissions"},
    },
)
def create_site(
    payload: SiteCreate,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> Site:
    _require_master_admin(db, caller, min_level=5)
    sid = payload.id.upper()
    if not SITE_ID_PATTERN.match(sid):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Site id must start with a letter and contain only A-Z, 0-9, and '-' (max 32)",
        )
    if db.get(Site, sid) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Site '{sid}' already exists")
    if payload.is_master and db.scalar(select(Site).where(Site.is_master.is_(True))) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A master site already exists. Only one master site is permitted.",
        )
    site = Site(
        id=sid,
        name=payload.name,
        city=payload.city,
        timezone=payload.timezone,
        is_master=payload.is_master,
        is_online=payload.is_online,
        build_version=payload.build_version,
    )
    db.add(site)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Site id conflict") from e
    db.refresh(site)
    audit_log.record(
        db,
        event_type="site.created",
        actor_id=caller.id,
        site_id=sid,
        request=request,
        detail={"name": site.name, "city": site.city, "is_master": site.is_master},
    )
    return site


@router.put(
    "/{site_id}",
    response_model=SiteOut,
    summary="Update a site (MCS Lvl 4+)",
    description="Partial update of name/city/timezone/build_version. The site `id` field is immutable. Audit detail captures only the diffed fields with was/now values.",
    responses={
        403: {"description": "Caller is not on the master site or has insufficient permissions"},
        404: {"description": "Site not found"},
    },
)
def update_site(
    site_id: str,
    payload: SiteUpdate,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> Site:
    _require_master_admin(db, caller, min_level=4)
    site = _load(db, site_id)
    before = {"name": site.name, "city": site.city, "timezone": site.timezone, "build_version": site.build_version}
    changed: dict[str, object] = {}
    for field in ("name", "city", "timezone", "build_version"):
        new_val = getattr(payload, field)
        if new_val is not None and new_val != getattr(site, field):
            setattr(site, field, new_val)
            changed[field] = {"was": before[field], "now": new_val}
    if not changed:
        return site
    db.commit()
    db.refresh(site)
    audit_log.record(
        db,
        event_type="site.updated",
        actor_id=caller.id,
        site_id=site.id,
        request=request,
        detail={"changes": changed},
    )
    return site


@router.delete(
    "/{site_id}",
    response_model=SiteOut,
    summary="Delete a site (MCS Lvl 5 only)",
    description="Permanently remove a site. Refuses if the site is the master, is the caller's signed-in site, or has any users/departments still referencing it. Returns the deleted record's snapshot.",
    responses={
        400: {"description": "Cannot delete master site or own site"},
        409: {"description": "Site has dependent users or departments"},
        403: {"description": "Caller is not on the master site or has insufficient permissions"},
    },
)
def delete_site(
    site_id: str,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> Site:
    _require_master_admin(db, caller, min_level=5)
    site = _load(db, site_id)
    if site.is_master:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the master site")
    if site.id == caller.site_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete the site you are signed in to")
    users, depts = _counts(db, site_id)
    if users or depts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Site has {users} user(s) and {depts} department(s). Reassign or remove them before deleting.",
        )
    snapshot = SiteOut.model_validate(site)
    db.delete(site)
    db.commit()
    audit_log.record(
        db,
        event_type="site.deleted",
        actor_id=caller.id,
        site_id=site_id,
        request=request,
        detail={"name": snapshot.name, "city": snapshot.city},
    )
    return snapshot


@router.post(
    "/{site_id}/toggle-online",
    response_model=SiteOut,
    summary="Toggle a site's is_online flag (MCS Lvl 4+)",
    description="Flip the site's online/offline state. 60s cooldown between toggles prevents flap. Master site cannot be taken offline. Returns the updated site record.",
    responses={
        429: {"description": "Cooldown still in effect (≤60s since last toggle on this site)"},
        400: {"description": "Cannot take master site offline"},
        403: {"description": "Caller is not on the master site or has insufficient permissions"},
    },
)
def toggle_site_online(
    site_id: str,
    request: Request,
    db: Session = Depends(get_session),
    caller: User = Depends(get_current_user),
) -> Site:
    _require_master_admin(db, caller, min_level=4)
    site = _load(db, site_id)
    if site.is_master and site.is_online:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot take the master site offline")
    now = _time.monotonic()
    last = _last_toggle_at.get(site_id, 0.0)
    if now - last < TOGGLE_COOLDOWN_SECONDS:
        retry_in = int(TOGGLE_COOLDOWN_SECONDS - (now - last))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Toggle cooldown in effect. Try again in {retry_in}s.",
        )
    site.is_online = not site.is_online
    db.commit()
    db.refresh(site)
    _last_toggle_at[site_id] = now
    audit_log.record(
        db,
        event_type="site.online_toggled",
        actor_id=caller.id,
        site_id=site.id,
        request=request,
        detail={"is_online": site.is_online, "at": datetime.now(UTC).isoformat()},
    )
    return site

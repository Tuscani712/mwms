"""Reports router — read-only metrics (SCO-52 MVP).

All endpoints are scoped to the caller's site via get_current_user.site_id.
Multi-site rollup (MCS-only) deferred to v2.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import User
from wms.services import metrics as svc

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return svc.dashboard(db, user.site_id)


@router.get("/inventory-aging")
def inventory_aging(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return svc.inventory_aging(db, user.site_id)


@router.get("/production")
def production(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return svc.production_yield(db, user.site_id)


@router.get("/shipping")
def shipping(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return svc.shipping_summary(db, user.site_id)

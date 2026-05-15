"""Admin endpoints for managing password / MFA policy rows."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import PasswordPolicy, User
from wms.schemas.auth import MFAResetRequest
from wms.services import mfa as mfa_svc

router = APIRouter(prefix="/admin/policy", tags=["admin-policy"])


class PolicyRule(BaseModel):
    id: int | None = None
    scope_type: str = Field(pattern="^(global|site|role|user)$")
    scope_value: str | None = None
    min_length: int = Field(ge=4, le=128, default=4)
    require_uppercase: bool = False
    require_lowercase: bool = False
    require_digit: bool = False
    require_special: bool = False
    require_mfa: bool = False

    model_config = {"from_attributes": True}


def _require_admin(user: User) -> None:
    if user.permission_level < 3:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Level 3+ required")


@router.get("/password", response_model=list[PolicyRule])
def list_password_policies(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[PasswordPolicy]:
    _require_admin(user)
    return db.query(PasswordPolicy).order_by(PasswordPolicy.scope_type).all()


@router.put("/password", response_model=PolicyRule)
def upsert_password_policy(
    payload: PolicyRule,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PasswordPolicy:
    _require_admin(user)
    existing = (
        db.query(PasswordPolicy)
        .filter(
            PasswordPolicy.scope_type == payload.scope_type,
            PasswordPolicy.scope_value == payload.scope_value,
        )
        .first()
    )
    if existing:
        for f in ("min_length", "require_uppercase", "require_lowercase",
                  "require_digit", "require_special", "require_mfa"):
            setattr(existing, f, getattr(payload, f))
        db.commit()
        db.refresh(existing)
        return existing
    row = PasswordPolicy(**payload.model_dump(exclude={"id"}))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/mfa-reset")
def reset_user_mfa(
    payload: MFAResetRequest,
    db: Session = Depends(get_session),
    actor: User = Depends(get_current_user),
) -> dict:
    """Admin (Level 4+) clears a user's MFA enrollment — for lost-device recovery."""
    if actor.permission_level < 4:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Level 4+ required for MFA reset")
    target = db.query(User).filter(User.id == payload.user_id).one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if actor.site_id != "MCS" and target.site_id != actor.site_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin must be at the same site")
    mfa_svc.disable_mfa(db, target.id)
    return {"ok": True, "user_id": target.id, "message": "MFA reset — user must re-enroll on next login"}

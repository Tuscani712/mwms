"""Sites router — list sites for the login picker."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wms.core.deps import get_session
from wms.models import Site

router = APIRouter(prefix="/sites", tags=["sites"])


class SiteOut(BaseModel):
    id: str
    name: str
    city: str
    is_master: bool
    is_online: bool
    build_version: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_session)) -> list[Site]:
    return db.query(Site).order_by(Site.is_master.desc(), Site.id).all()

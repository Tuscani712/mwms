"""Health endpoints — ping + status (for the login strip ping pill)."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from wms import __version__

router = APIRouter(prefix="/health", tags=["health"])

_BOOT_TIME = datetime.now(UTC)


class HealthOut(BaseModel):
    ok: bool
    status: str
    build: str
    boot_time: datetime
    uptime_seconds: int


@router.get("/ping")
def ping() -> dict[str, bool]:
    return {"ok": True}


@router.get("", response_model=HealthOut)
def health() -> HealthOut:
    now = datetime.now(UTC)
    return HealthOut(
        ok=True,
        status="online",
        build=f"v{__version__}",
        boot_time=_BOOT_TIME,
        uptime_seconds=int((now - _BOOT_TIME).total_seconds()),
    )

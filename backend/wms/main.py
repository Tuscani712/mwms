"""FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Import models so all tables register on Base.metadata before create_all.
import wms.models  # noqa: F401
from wms import __version__
from wms.api.v1 import auth, health, mfa, policy, profile, receiving, shipping, sites
from wms.core.config import get_settings
from wms.db.base import Base
from wms.db.session import engine

settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(
        title="WMS API",
        version=__version__,
        description="Warehouse Management System backend",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Create tables for dev convenience. In prod, use Alembic migrations.
    Base.metadata.create_all(bind=engine)

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(sites.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(receiving.router, prefix=api_prefix)
    app.include_router(shipping.router, prefix=api_prefix)
    app.include_router(profile.router, prefix=api_prefix)
    app.include_router(profile.admin_router, prefix=api_prefix)
    app.include_router(policy.router, prefix=api_prefix)
    app.include_router(mfa.router, prefix=api_prefix)
    app.include_router(mfa.auth_router, prefix=api_prefix)

    upload_root = Path(settings.upload_dir)
    (upload_root / "avatars").mkdir(parents=True, exist_ok=True)

    class NoSniffMiddleware(BaseHTTPMiddleware):
        """Defense-in-depth: prevent browsers from MIME-sniffing uploads
        into something executable (e.g., a crafted image being treated as HTML)."""

        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/uploads/"):
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Content-Security-Policy"] = "default-src 'none'"
            return response

    app.add_middleware(NoSniffMiddleware)
    app.mount("/uploads", StaticFiles(directory=str(upload_root)), name="uploads")

    return app


app = create_app()

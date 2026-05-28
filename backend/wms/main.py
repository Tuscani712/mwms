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
from wms.api.v1 import (
    admin_orgmeta,
    admin_users,
    auth,
    health,
    inventory,
    mfa,
    policy,
    production,
    profile,
    quality,
    receiving,
    reports,
    shipping,
    sites,
)
from wms.core.config import get_settings
from wms.db.base import Base
from wms.db.session import engine

settings = get_settings()
# C-1: fail-fast if production was started with the dev sentinel key.
settings.assert_secure_for_env()


def _ensure_columns(engine, table: str, columns: dict[str, str]) -> None:
    """Idempotent additive migration for new columns on an existing table.

    SQLAlchemy's create_all() creates tables but never ALTERs them, so adding
    a column to a model leaves pre-existing dev DBs missing the column. We
    inspect `table` and ALTER for each missing entry. SQLite ignores complex
    DEFAULT/NOT NULL combinations on ADD COLUMN if the table is empty, but for
    our small-data dev DBs the simple form works fine.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    with engine.begin() as conn:
        for name, ddl in columns.items():
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


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
    # SCO-99: lightweight runtime migration for the must_change_password
    # column. create_all() never ALTERs existing tables, so we add the column
    # by hand if it's missing on a pre-existing dev DB.
    _ensure_columns(engine, "users", {"must_change_password": "BOOLEAN NOT NULL DEFAULT 0"})
    # SCO-100: title_id FK + custom_title free-text override on User.
    _ensure_columns(
        engine,
        "users",
        {
            "title_id": "INTEGER NULL REFERENCES titles(id)",
            "custom_title": "VARCHAR(60) NULL",
        },
    )

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(sites.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(receiving.router, prefix=api_prefix)
    app.include_router(shipping.router, prefix=api_prefix)
    app.include_router(inventory.router, prefix=api_prefix)
    app.include_router(production.router, prefix=api_prefix)
    app.include_router(quality.router, prefix=api_prefix)
    app.include_router(reports.router, prefix=api_prefix)
    app.include_router(profile.router, prefix=api_prefix)
    app.include_router(profile.admin_router, prefix=api_prefix)
    app.include_router(policy.router, prefix=api_prefix)
    app.include_router(mfa.router, prefix=api_prefix)
    app.include_router(mfa.auth_router, prefix=api_prefix)
    app.include_router(admin_users.router, prefix=api_prefix)
    app.include_router(admin_orgmeta.roles_router, prefix=api_prefix)
    app.include_router(admin_orgmeta.departments_router, prefix=api_prefix)
    app.include_router(admin_orgmeta.shifts_router, prefix=api_prefix)
    app.include_router(admin_orgmeta.titles_router, prefix=api_prefix)
    # TODO(SCO-53): when the System Settings backend lands, mount its router:
    #     from .api.v1 import settings as system_settings  # noqa
    #     app.include_router(system_settings.router, prefix=api_prefix)
    # The router file at wms/api/v1/settings.py is a dormant stub today —
    # full contract documented at the top of that file. Frontend already
    # ships at /admin-settings.html and gracefully degrades to the local
    # registry fallback while the backend is unmounted.

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

    class BodySizeLimitMiddleware(BaseHTTPMiddleware):
        """SECURITY_AUDIT.md M-5: cap JSON bodies. Multipart uploads bypass
        this — they're capped separately by `max_upload_bytes` after the
        sanitizer parses the leading bytes."""

        async def dispatch(self, request: Request, call_next):
            # Don't double-cap the upload endpoint; it has stricter, content-aware
            # limits and may legitimately receive bodies up to max_upload_bytes.
            path = request.url.path
            if path.startswith("/uploads/") or path.endswith("/picture/upload"):
                return await call_next(request)

            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > settings.max_json_body_bytes:
                        from fastapi.responses import JSONResponse

                        return JSONResponse(
                            status_code=413,
                            content={
                                "detail": (
                                    f"Request body exceeds {settings.max_json_body_bytes} bytes"
                                )
                            },
                        )
                except ValueError:
                    pass  # malformed header — let downstream handle it
            return await call_next(request)

    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(NoSniffMiddleware)
    app.mount("/uploads", StaticFiles(directory=str(upload_root)), name="uploads")

    return app


app = create_app()

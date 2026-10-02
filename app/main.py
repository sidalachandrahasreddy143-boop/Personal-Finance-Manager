"""FastAPI application factory and ASGI entry point.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import models  # noqa: F401 - registers every ORM model on Base.metadata
from app.api.openapi import _API_DESCRIPTION, TAGS_METADATA
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import RateLimitExceededError, problem_response, register_exception_handlers
from app.core.logging import configure_logging, get_request_id, new_request_id, set_request_id
from app.core.rate_limit import enforce_rate_limit
from app.db.base import Base
from app.db.session import engine

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/app",
    "/api/v1/health",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks."""
    configure_logging("DEBUG" if settings.debug else "INFO", json_logs=settings.is_production)
    logger.info(
        "Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment
    )

    # Auto-create tables outside production (and always for SQLite, where the
    # bundled Docker demo runs without a migration step). Postgres in production
    # is migrated explicitly with `alembic upgrade head`.
    if settings.environment != "test" and (not settings.is_production or settings.is_sqlite):
        Base.metadata.create_all(bind=engine)

    if settings.seed_demo_user:
        from app.scripts.seed_demo import seed_demo_data

        seed_demo_data()

    yield

    logger.info("Shutting down")
    if settings.environment != "test":
        # Tests keep the engine alive: disposing an in-memory SQLite engine
        # would throw the (already created) schema away between tests.
        engine.dispose()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, time the request and emit one access log line."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or new_request_id()
        set_request_id(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:  # pragma: no cover - handled by the global handler
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request failed",
                extra={"path": request.url.path, "duration_ms": round(duration_ms, 2)},
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
        if not request.url.path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client": request.client.host if request.client else None,
                },
            )
        return response


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Cheap global throttle; auth routes have their own stricter bucket.

    Exceptions are converted here because middleware runs *outside* Starlette's
    exception-handling middleware, so a raised domain error would become a 500.
    """
    if not request.url.path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
        try:
            enforce_rate_limit(request)
        except RateLimitExceededError as exc:
            return problem_response(
                status_code=exc.status_code,
                title=exc.title,
                detail=exc.detail,
                code=exc.code,
                instance=str(request.url.path),
                extra=exc.extra,
            )
    return await call_next(request)


def create_app() -> FastAPI:
    """Build and configure the application (importable for tests)."""
    application = FastAPI(
        title=settings.app_name,
        description=_API_DESCRIPTION,
        version=settings.app_version,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        contact={
            "name": "Chandra Has Reddy Sida",
            "url": "https://github.com/sidalachandrahasreddy143-boop",
        },
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        openapi_url="/openapi.json",
    )

    application.add_middleware(GZipMiddleware, minimum_size=1000)
    application.add_middleware(RequestContextMiddleware)
    application.middleware("http")(rate_limit_middleware)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time-ms"],
    )

    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    # ---- Bundled single-page dashboard (no build step, no CDN) -----------
    if STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @application.get("/app", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

        @application.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/app")

        @application.get("/favicon.ico", include_in_schema=False)
        def favicon() -> Response:
            icon = STATIC_DIR / "favicon.svg"
            return FileResponse(icon) if icon.exists() else Response(status_code=204)

    @application.get("/api", include_in_schema=False)
    def api_hint() -> JSONResponse:
        return JSONResponse(
            {
                "message": f"{settings.app_name} v{settings.app_version}",
                "docs": "/docs",
                "dashboard": "/app",
                "health": "/api/v1/health",
            }
        )

    return application


app = create_app()

__all__ = ["app", "create_app", "get_request_id"]

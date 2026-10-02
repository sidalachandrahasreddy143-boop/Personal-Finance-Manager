"""Operational endpoints: liveness, readiness and capability discovery."""

from __future__ import annotations

import datetime as dt
import time

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.core.deps import DbSession
from app.db.session import engine
from app.schemas.common import HealthStatus

router = APIRouter(tags=["meta"])

_STARTED_AT = time.monotonic()


@router.get("/health", response_model=HealthStatus, summary="Liveness + database check")
def health(db: DbSession, response: Response) -> HealthStatus:
    """Returns 503 when the database is unreachable so load balancers can react."""
    database_state = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_state = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthStatus(
        status="ok" if database_state == "ok" else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        database=database_state,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 2),
        checked_at=dt.datetime.now(dt.UTC),
    )


@router.get("/health/live", summary="Liveness probe only (no dependencies)")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta", summary="API capabilities and defaults")
def meta() -> dict[str, object]:
    """Discovery endpoint - lets clients adapt to server configuration."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "api_prefix": settings.api_v1_prefix,
        "default_currency": settings.default_currency,
        "default_timezone": settings.default_timezone,
        "database_dialect": engine.dialect.name,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "features": {
            "csv_import": True,
            "csv_export": True,
            "insights": True,
            "recurring_rules": True,
            "budget_rollover": True,
            "refresh_tokens": False,
        },
        "docs": {"swagger": "/docs", "redoc": "/redoc", "openapi": "/openapi.json"},
    }

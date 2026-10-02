"""Domain exceptions and RFC 7807 (``application/problem+json``) handlers.

Centralising error shaping means every endpoint - including 422 validation
failures and unhandled crashes - returns the *same* envelope, which clients can
parse once and trust.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
_ERROR_BASE = "https://github.com/sidalachandrahasreddy143-boop/Personal-Finance-Manager/blob/main/docs/ERRORS.md"


class DomainError(Exception):
    """Base class for expected, business-level failures."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    title: str = "Bad request"
    code: str = "bad-request"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Resource not found"
    code = "not-found"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    title = "Conflict"
    code = "conflict"


class AuthenticationError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Authentication failed"
    code = "unauthorized"


class PermissionDeniedError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Permission denied"
    code = "forbidden"


class RateLimitExceededError(DomainError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    title = "Too many requests"
    code = "rate-limited"


class BusinessRuleError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    title = "Business rule violated"
    code = "business-rule"


def problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{_ERROR_BASE}#{code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "code": code,
        "request_id": get_request_id(),
    }
    if instance:
        body["instance"] = instance
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status_code, content=body, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the application."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return problem_response(
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            code=exc.code,
            instance=str(request.url.path),
            extra=exc.extra,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ())[1:]) or "body",
                "message": err.get("msg", "invalid value"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        return problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Request validation failed",
            detail=f"{len(fields)} field(s) failed validation.",
            code="validation-error",
            instance=str(request.url.path),
            extra={"errors": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = dict(getattr(exc, "headers", None) or {}) or None
        return problem_response(
            status_code=exc.status_code,
            title=str(exc.detail),
            detail=str(exc.detail),
            code=f"http-{exc.status_code}",
            instance=str(request.url.path),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return problem_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal server error",
            detail="An unexpected error occurred. The incident has been logged.",
            code="internal-error",
            instance=str(request.url.path),
        )

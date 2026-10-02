"""Tiny in-process rate limiter.

A fixed-window counter keyed by ``client ip + route``. It is intentionally
dependency-free and good enough to stop credential stuffing on a single
instance; in a multi-replica deployment swap the store for Redis
(``PFM_RATE_LIMIT_ENABLED=false`` disables it entirely).
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request

from app.core.config import settings
from app.core.errors import RateLimitExceededError


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def check(self, key: str) -> tuple[bool, int]:
        """Register a hit. Returns ``(allowed, remaining)``."""
        now = time.monotonic()
        count, window_started = self._hits[key]
        if now - window_started >= self.window_seconds:
            count, window_started = 0, now
        count += 1
        self._hits[key] = (count, window_started)
        return count <= self.limit, max(0, self.limit - count)

    def reset(self) -> None:
        """Clear all counters (used between tests)."""
        self._hits.clear()


general_limiter = FixedWindowRateLimiter(settings.rate_limit_per_minute)
auth_limiter = FixedWindowRateLimiter(settings.auth_rate_limit_per_minute)


def client_key(request: Request, bucket: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"{bucket}:{ip}"


def enforce_rate_limit(request: Request, *, bucket: str = "general") -> None:
    if not settings.rate_limit_enabled:
        return
    limiter = auth_limiter if bucket == "auth" else general_limiter
    allowed, remaining = limiter.check(client_key(request, bucket))
    if not allowed:
        raise RateLimitExceededError(
            "Rate limit exceeded. Please slow down and retry in a minute.",
            extra={"limit_per_minute": limiter.limit},
        )
    request.state.rate_limit_remaining = remaining

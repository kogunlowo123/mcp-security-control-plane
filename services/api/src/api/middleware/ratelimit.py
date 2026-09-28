"""
In-memory sliding-window rate limiter middleware.

Limits each authenticated agent to ``settings.rate_limit_requests`` requests
within a rolling ``settings.rate_limit_window_seconds`` window.

Key: ``request.state.agent_id`` set by AuthMiddleware.  If agent_id is None
(public / unauthenticated path) the limiter uses the client IP address as the
key so that health probes from the same host are still throttled in extreme
edge cases, but the limit is applied much more generously.

Thread / async safety notes:
- asyncio is single-threaded within a worker process; dict operations are
  effectively atomic for our purposes.
- For multi-worker deployments replace this with a Redis-backed limiter.
"""

from __future__ import annotations

import logging
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from api.config import settings

logger = logging.getLogger(__name__)

_ANONYMOUS_LIMIT = 300


class InMemoryRateLimiter:
    """Sliding-window rate limiter backed by an in-process dict.

    For multi-worker deployments replace with a Redis-backed implementation.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, deque[float]] = {}

    def check_and_increment(self, key: str) -> bool:
        """Return True if request is allowed, False if rate limit exceeded."""
        now = time.monotonic()
        cutoff = now - self.window_seconds

        if key not in self._windows:
            self._windows[key] = deque()

        window = self._windows[key]
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= self.max_requests:
            return False

        window.append(now)
        return True

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest request in the window expires."""
        window = self._windows.get(key)
        if not window:
            return 0
        cutoff = time.monotonic() - self.window_seconds
        return max(0, int(window[0] - cutoff) + 1)


_default_limiter: InMemoryRateLimiter | None = None


def _get_default_limiter() -> InMemoryRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = InMemoryRateLimiter(
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    return _default_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed on agent_id (or client IP for public paths)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        agent_id: str | None = getattr(request.state, "agent_id", None)

        if not agent_id:
            key = f"ip:{request.client.host if request.client else 'unknown'}"
            limiter = InMemoryRateLimiter(
                max_requests=_ANONYMOUS_LIMIT,
                window_seconds=settings.rate_limit_window_seconds,
            )
        else:
            key = agent_id
            limiter = _get_default_limiter()

        allowed = limiter.check_and_increment(key)
        if not allowed:
            retry_after = limiter.retry_after(key)
            logger.warning("Rate limit exceeded for key=%s", key)
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": "Rate limit exceeded.",
                    "retry_after_seconds": retry_after,
                    "limit": limiter.max_requests,
                    "window_seconds": limiter.window_seconds,
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limiter.max_requests)
        response.headers["X-RateLimit-Window"] = str(limiter.window_seconds)
        return response

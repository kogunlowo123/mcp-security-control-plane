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

# Generous limit applied to anonymous / public requests (per IP)
_ANONYMOUS_LIMIT = 300
# Mapping of key -> deque of request timestamps (float, monotonic seconds)
_windows: dict[str, deque[float]] = {}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter keyed on agent_id (or client IP for public paths).

    Returns HTTP 429 with a ``Retry-After`` header when the limit is exceeded.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # agent_id is set by AuthMiddleware; may be None on public paths
        agent_id: str | None = getattr(request.state, "agent_id", None)
        is_anonymous = not agent_id

        if is_anonymous:
            key: str = f"ip:{request.client.host if request.client else 'unknown'}"
            limit = _ANONYMOUS_LIMIT
        else:
            key = f"agent:{agent_id}"
            limit = settings.rate_limit_requests

        window_seconds = settings.rate_limit_window_seconds
        now = time.monotonic()
        cutoff = now - window_seconds

        # Lazily initialise the deque for this key
        if key not in _windows:
            _windows[key] = deque()

        window: deque[float] = _windows[key]

        # Evict timestamps that have fallen outside the current window
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= limit:
            retry_after = int(window[0] - cutoff) + 1
            logger.warning("Rate limit exceeded for key=%s count=%d", key, len(window))
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": "Rate limit exceeded.",
                    "retry_after_seconds": retry_after,
                    "limit": limit,
                    "window_seconds": window_seconds,
                },
            )

        window.append(now)
        response = await call_next(request)
        # Expose current usage to callers for observability
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(window)))
        response.headers["X-RateLimit-Window"] = str(window_seconds)
        return response

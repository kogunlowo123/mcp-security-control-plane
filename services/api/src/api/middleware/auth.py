"""
JWT authentication middleware.

Extracts the Bearer token from the Authorization header, validates it with
PyJWT, and stores the decoded claims on request.state so that route handlers
and downstream middleware can access them without re-decoding.

Public paths (see PUBLIC_PATHS) bypass JWT validation entirely so that health
probes, OpenAPI docs, and the OpenAPI schema are always accessible.
"""

from __future__ import annotations

import logging

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from api.config import settings

logger = logging.getLogger(__name__)

PUBLIC_PATHS: frozenset[str] = frozenset(
    ["/health", "/readiness", "/docs", "/redoc", "/openapi.json"]
)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT, supporting both RS256 (broker-issued) and HS256."""
    unverified = jwt.get_unverified_header(token)
    algorithm = unverified.get("alg", "HS256")

    if algorithm == "RS256":
        try:
            from identity.issuance.broker.broker import _PUBLIC_KEY_PEM  # noqa: PLC0415
            return jwt.decode(
                token,
                _PUBLIC_KEY_PEM,
                algorithms=["RS256"],
                options={"require": ["sub", "exp"]},
            )
        except ImportError:
            pass

    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience if settings.jwt_algorithm != "RS256" else None,
        options={"require": ["sub", "exp"]},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette BaseHTTPMiddleware that validates JWT Bearer tokens.

    On success: sets ``request.state.agent_id``, ``request.state.tier``,
    and ``request.state.grants``.

    On failure: returns HTTP 401 with a JSON body.

    On public path: sets ``request.state.agent_id = None`` and continues.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Normalise the path so trailing slashes do not confuse matching
        path = request.url.path.rstrip("/") or "/"

        # Allow public paths through without authentication
        if path in PUBLIC_PATHS:
            # Ensure downstream middleware / handlers never KeyError on these
            request.state.agent_id = None
            request.state.tier = "anonymous"
            request.state.grants = []
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authorization header missing or not a Bearer token."
                },
            )

        token = auth_header[len("Bearer "):]

        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Token has expired."},
            )
        except jwt.InvalidAudienceError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Token audience is invalid."},
            )
        except jwt.PyJWTError as exc:
            logger.debug("JWT validation failed: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": f"Token validation failed: {exc}"},
            )

        # Populate request.state from JWT claims
        request.state.agent_id = payload.get("sub", "")
        request.state.tier = payload.get("tier", "standard")
        # 'grants' is expected to be a space-separated scope string or a list
        raw_grants = payload.get("grants", payload.get("scope", ""))
        if isinstance(raw_grants, str):
            request.state.grants = raw_grants.split() if raw_grants else []
        elif isinstance(raw_grants, list):
            request.state.grants = raw_grants
        else:
            request.state.grants = []

        return await call_next(request)

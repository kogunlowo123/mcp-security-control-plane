"""
Health and readiness endpoints.

GET /health    – liveness probe; always returns 200 if the process is alive.
GET /readiness – readiness probe; checks downstream dependencies (PostgreSQL
                 and OPA) before returning 200.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
import psycopg2
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    """Return a simple liveness payload.  No dependency checks."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/readiness", summary="Readiness probe")
async def readiness(request: Request) -> JSONResponse:
    """
    Check whether the service is ready to accept traffic.

    Performs:
    - PostgreSQL connectivity test (quick SELECT 1)
    - OPA health endpoint check (GET <OPA_URL>/health)
    """
    checks: dict[str, dict] = {}
    overall_ready = True

    # --- PostgreSQL check ---
    db_conn = getattr(request.app.state, "db_conn", None)
    if db_conn is None:
        # Try a fresh connection in case it failed at startup
        try:
            conn = psycopg2.connect(settings.postgres_dsn, connect_timeout=3)
            conn.close()
            checks["postgres"] = {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Readiness: postgres check failed: %s", exc)
            checks["postgres"] = {"status": "error", "detail": str(exc)}
            overall_ready = False
    else:
        try:
            with db_conn.cursor() as cur:
                cur.execute("SELECT 1")
            checks["postgres"] = {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Readiness: postgres ping failed: %s", exc)
            checks["postgres"] = {"status": "error", "detail": str(exc)}
            overall_ready = False

    # --- OPA check ---
    http_client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)
    try:
        if http_client is not None:
            resp = await http_client.get("/health")
        else:
            async with httpx.AsyncClient(timeout=2.0) as tmp:
                resp = await tmp.get(f"{settings.opa_url}/health")

        if resp.status_code == 200:
            checks["opa"] = {"status": "ok"}
        else:
            checks["opa"] = {"status": "error", "detail": f"HTTP {resp.status_code}"}
            overall_ready = False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Readiness: OPA check failed: %s", exc)
        checks["opa"] = {"status": "error", "detail": str(exc)}
        overall_ready = False

    status_code = 200 if overall_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if overall_ready else "not_ready",
            "checks": checks,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
    )

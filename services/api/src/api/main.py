"""
MCP Security Control Plane – FastAPI application entry point.

Startup order:
    1. OpenTelemetry SDK (must run before importing instrumented libraries)
    2. App construction with middleware stack
    3. Router registration
    4. DB connection pool (lifespan)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import psycopg2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.middleware.auth import AuthMiddleware
from api.middleware.ratelimit import RateLimitMiddleware
from api.middleware.tenant import TenantMiddleware
from api.middleware.tracing import TracingMiddleware
from api.routes.v1 import health as health_router
from api.routes.v1 import mcp as mcp_router
from api.routes.v1 import tools as tools_router
from api.telemetry import init_telemetry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenTelemetry – must initialise before FastAPI instrumentor runs
# ---------------------------------------------------------------------------
if settings.tracing_enabled:
    init_telemetry()


# ---------------------------------------------------------------------------
# Lifespan – manages resources that span the entire process life
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open DB pool and HTTP client on startup; close them on shutdown."""
    # Shared async HTTP client (used by OPA calls in route handlers)
    app.state.http_client = httpx.AsyncClient(
        timeout=settings.opa_timeout_seconds,
        base_url=settings.opa_url,
    )

    # Synchronous PostgreSQL connection (psycopg2; adequate for low-volume control-plane)
    try:
        app.state.db_conn = psycopg2.connect(settings.postgres_dsn)
        app.state.db_conn.autocommit = True
        logger.info("PostgreSQL connection established")
    except Exception as exc:  # noqa: BLE001
        logger.warning("PostgreSQL connection failed at startup: %s", exc)
        app.state.db_conn = None

    yield

    # Shutdown
    await app.state.http_client.aclose()
    if app.state.db_conn is not None:
        app.state.db_conn.close()
    logger.info("Application shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Enterprise AI security governance platform for Model Context Protocol "
            "tool calls: policy enforcement, audit logging, and violation tracking."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware – added in reverse order of execution (last-added = outermost
    # wrapper = first to process the *request*).  We want the execution order:
    #   CORS → Tracing → Tenant → Auth → RateLimit → route handler
    # So we add them in the reverse of that order.
    # ------------------------------------------------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    # TracingMiddleware wraps every request with an OTel span and sets
    # request.state.trace_id so downstream middleware / handlers can read it.
    application.add_middleware(TracingMiddleware)
    # TenantMiddleware extracts X-Tenant-ID header.
    application.add_middleware(TenantMiddleware)
    # AuthMiddleware validates the JWT Bearer token and populates
    # request.state.agent_id / tier / grants.  Must run before RateLimit
    # so that the rate-limiter can key on agent_id.
    application.add_middleware(AuthMiddleware)
    # RateLimitMiddleware enforces per-agent request quotas.
    application.add_middleware(RateLimitMiddleware)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    # Health / readiness – mounted at the root so /health and /readiness
    # resolve without any additional prefix.
    application.include_router(health_router.router)

    # MCP security endpoints – all live under /api/v1/mcp
    application.include_router(mcp_router.router, prefix="/api/v1/mcp")

    # Tool catalog – the spec requires GET /api/v1/mcp/tools, so the tools
    # router is also mounted under /api/v1/mcp.
    application.include_router(tools_router.router, prefix="/api/v1/mcp")

    return application


app = create_app()

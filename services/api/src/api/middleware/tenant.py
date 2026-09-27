"""
Tenant isolation middleware.

Extracts the ``X-Tenant-ID`` HTTP header and stores the value on
``request.state.tenant_id``.  Defaults to ``"default"`` when the header is
absent so that single-tenant deployments work without modification.

This middleware is intentionally simple: multi-tenant data isolation is
enforced at the repository / database layer, not here.  This middleware only
surfaces the tenant identity so that lower layers can consume it.
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

TENANT_HEADER = "X-Tenant-ID"
DEFAULT_TENANT = "default"


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that reads the ``X-Tenant-ID`` header.

    Sets ``request.state.tenant_id`` for use by downstream handlers.
    Never rejects a request – an absent header defaults to ``"default"``.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        tenant_id: str = request.headers.get(TENANT_HEADER, DEFAULT_TENANT).strip()
        # Guard against blank or whitespace-only values
        if not tenant_id:
            tenant_id = DEFAULT_TENANT
        request.state.tenant_id = tenant_id
        return await call_next(request)

"""Gateway router: routes MCP tool calls through the authorization pipeline."""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx


_OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
_API_URL = os.getenv("API_INTERNAL_URL", "http://api:8000")


class GatewayRouter:
    """Routes incoming MCP tool calls through the security control plane."""

    async def route(
        self,
        agent_id: str,
        tool_name: str,
        tool_parameters: dict[str, Any],
        scope: str,
        token: str,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Authorize and route a tool call.

        Returns the AuthorizationDecision from the control plane API.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_API_URL}/api/v1/mcp/authorize",
                json={
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "tool_parameters": tool_parameters,
                    "scope": scope,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Tenant-ID": tenant_id,
                    "X-Request-ID": str(uuid.uuid4()),
                },
            )
            response.raise_for_status()
            return response.json()

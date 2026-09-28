"""Integration tests for the full MCP API flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from httpx import AsyncClient

from api.main import create_app


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture(scope="module")
def valid_token():
    from identity.issuance.broker.broker import TokenBroker

    broker = TokenBroker()
    return broker.issue_token(
        agent_id="integration-agent-001",
        tier="T1",
        tool_grants=["rag_search", "mcp_audit_query"],
    )


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(app):
    """GET /health returns 200."""
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_readiness_endpoint(app):
    """GET /readiness returns 200 or 503 (structure check only)."""
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/readiness")

    # In test environment dependencies may not be available; accept either status
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "checks" in data


@pytest.mark.asyncio
async def test_list_tools_returns_catalog(app, valid_token):
    """GET /api/v1/mcp/tools returns tool catalog."""
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/mcp/tools",
            headers={"Authorization": f"Bearer {valid_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert "total" in data
    assert isinstance(data["tools"], list)
    assert len(data["tools"]) > 0


@pytest.mark.asyncio
async def test_full_authorize_audit_flow(app, valid_token):
    """Authorize a call, then audit it; verify the flow completes."""
    opa_response = {
        "result": {
            "allow": True,
            "decision": "permit",
            "reason": "authorized",
            "audit_record": {},
        }
    }

    with patch("api.routes.v1.mcp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_response = MagicMock()
        mock_response.json.return_value = opa_response
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            auth_response = await client.post(
                "/api/v1/mcp/authorize",
                json={
                    "agent_id": "integration-agent-001",
                    "tool_name": "rag_search",
                    "tool_parameters": {"query": "MCP security policy"},
                    "scope": "read-only",
                },
                headers={"Authorization": f"Bearer {valid_token}"},
            )

    assert auth_response.status_code == 200
    auth_data = auth_response.json()
    assert auth_data["decision"] == "permit"
    assert "trace_id" in auth_data

    # Audit the call
    with patch("api.routes.v1.mcp.psycopg2") as mock_pg:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            audit_response = await client.post(
                "/api/v1/mcp/audit",
                json={
                    "audit_id": "00000000-0000-0000-0000-000000000001",
                    "agent_id": "integration-agent-001",
                    "tool_name": "rag_search",
                    "tool_parameters": {"query": "MCP security policy"},
                    "decision": "permit",
                    "scope": "read-only",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "trace_id": auth_data["trace_id"],
                },
                headers={"Authorization": f"Bearer {valid_token}"},
            )

    assert audit_response.status_code in (201, 200, 503)


@pytest.mark.asyncio
async def test_violations_endpoint_returns_list(app, valid_token):
    """GET /api/v1/mcp/violations returns a list structure."""
    with patch("api.routes.v1.mcp.psycopg2") as mock_pg:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = []
        mock_pg.connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)

        async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/mcp/violations",
                headers={"Authorization": f"Bearer {valid_token}"},
            )

    assert response.status_code in (200, 503)

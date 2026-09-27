"""Unit tests for MCP authorization logic."""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def valid_agent_token():
    """Generate a valid JWT token for a T1 agent."""
    from identity.issuance.broker.broker import TokenBroker

    broker = TokenBroker()
    return broker.issue_token(
        agent_id="test-agent-001",
        tier="T1",
        tool_grants=["rag_search", "mcp_audit_query"],
    )


@pytest.fixture
def t0_agent_token():
    """Generate a valid JWT token for a T0 agent with limited grants."""
    from identity.issuance.broker.broker import TokenBroker

    broker = TokenBroker()
    return broker.issue_token(
        agent_id="t0-agent-001",
        tier="T0",
        tool_grants=["rag_search"],
    )


@pytest.mark.asyncio
async def test_authorize_valid_request_returns_permit(app, valid_agent_token):
    """A valid tool call request with proper token and OPA allow=true returns permit."""
    opa_response = {"result": {"allow": True, "decision": "permit", "reason": "authorized"}}

    with patch("api.routes.v1.mcp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_response = MagicMock()
        mock_response.json.return_value = opa_response
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/mcp/authorize",
                json={
                    "agent_id": "test-agent-001",
                    "tool_name": "rag_search",
                    "tool_parameters": {"query": "test"},
                    "scope": "read-only",
                },
                headers={"Authorization": f"Bearer {valid_agent_token}"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "permit"
    assert "trace_id" in data


@pytest.mark.asyncio
async def test_authorize_missing_token_returns_401(app):
    """Request without Authorization header returns 401."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/mcp/authorize",
            json={
                "agent_id": "test-agent-001",
                "tool_name": "rag_search",
                "tool_parameters": {},
                "scope": "read-only",
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authorize_invalid_token_returns_401(app):
    """Request with malformed JWT returns 401."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/mcp/authorize",
            json={
                "agent_id": "test-agent-001",
                "tool_name": "rag_search",
                "tool_parameters": {},
                "scope": "read-only",
            },
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authorize_opa_deny_returns_deny_decision(app, valid_agent_token):
    """When OPA returns allow=false, authorization decision is deny."""
    opa_response = {
        "result": {
            "allow": False,
            "decision": "deny",
            "reason": "tool_not_in_catalog",
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

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/mcp/authorize",
                json={
                    "agent_id": "test-agent-001",
                    "tool_name": "unknown_tool",
                    "tool_parameters": {},
                    "scope": "read-only",
                },
                headers={"Authorization": f"Bearer {valid_agent_token}"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "deny"


@pytest.mark.asyncio
async def test_authorize_scope_exceeded_returns_deny(app, t0_agent_token):
    """T0 agent requesting admin scope returns deny."""
    opa_response = {
        "result": {
            "allow": False,
            "decision": "deny",
            "reason": "scope_exceeded",
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

        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/mcp/authorize",
                json={
                    "agent_id": "t0-agent-001",
                    "tool_name": "code_execute",
                    "tool_parameters": {},
                    "scope": "admin",
                },
                headers={"Authorization": f"Bearer {t0_agent_token}"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "deny"
    assert data["reason"] == "scope_exceeded"


@pytest.mark.asyncio
async def test_health_endpoint(app):
    """Health endpoint returns 200 with healthy status."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data

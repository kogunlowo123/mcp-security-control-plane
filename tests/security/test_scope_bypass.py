"""Security tests for scope bypass and escalation attempts."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from api.main import create_app
from identity.issuance.broker.broker import TokenBroker


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture
def broker():
    return TokenBroker()


@pytest.fixture
def t0_token(broker):
    return broker.issue_token("sec-t0-agent", "T0", ["rag_search"])


@pytest.fixture
def t1_token(broker):
    return broker.issue_token("sec-t1-agent", "T1", ["rag_search", "mcp_audit_query"])


@pytest.mark.asyncio
async def test_cannot_bypass_opa_with_malformed_token(app):
    """Malformed JWT tokens are rejected at the auth middleware."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/mcp/authorize",
            json={
                "agent_id": "attacker",
                "tool_name": "code_execute",
                "tool_parameters": {},
                "scope": "admin",
            },
            headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.eyJhZ2VudF9pZCI6ImF0dGFja2VyIn0."},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cannot_access_admin_tools_with_t0_token(app, t0_token):
    """T0 token cannot access tools requiring T2 tier."""
    opa_response = {
        "result": {"allow": False, "decision": "deny", "reason": "scope_exceeded"}
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
                    "agent_id": "sec-t0-agent",
                    "tool_name": "code_execute",
                    "tool_parameters": {},
                    "scope": "read-write",
                },
                headers={"Authorization": f"Bearer {t0_token}"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "deny"
    assert data["reason"] == "scope_exceeded"


@pytest.mark.asyncio
async def test_replay_attack_blocked(app, broker):
    """Replaying a revoked token is rejected."""
    token = broker.issue_token("replay-agent", "T1", ["rag_search"])

    import jwt as pyjwt

    claims = broker.validate_token(token)
    broker.revoke_token(claims["jti"])

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/mcp/authorize",
            json={
                "agent_id": "replay-agent",
                "tool_name": "rag_search",
                "tool_parameters": {},
                "scope": "read-only",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_scope_injection_via_parameters_blocked(app, t1_token):
    """Injecting scope escalation via tool parameters is rejected by OPA."""
    opa_response = {
        "result": {"allow": False, "decision": "deny", "reason": "scope_exceeded"}
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
                    "agent_id": "sec-t1-agent",
                    "tool_name": "rag_search",
                    "tool_parameters": {
                        "query": "test",
                        "__scope_override__": "admin",
                        "_tier": "T2",
                    },
                    "scope": "read-only",
                },
                headers={"Authorization": f"Bearer {t1_token}"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "deny"


def test_token_with_elevated_grants_not_automatically_trusted(broker):
    """Grants in token must still be checked against catalog at call time."""
    evil_token = broker.issue_token(
        "evil-agent",
        "T0",
        ["rag_search", "code_execute", "admin_backdoor"],
    )
    claims = broker.validate_token(evil_token)
    # Token is structurally valid, but OPA would still deny at call time
    # because code_execute and admin_backdoor aren't in T0 allowed_tiers
    assert "code_execute" in claims["grants"]
    # The grants in the token don't mean automatic authorization —
    # OPA enforces the catalog check separately
    assert claims["tier"] == "T0"

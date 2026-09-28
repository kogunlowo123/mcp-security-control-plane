"""Unit tests for rate limiting middleware."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
import httpx
from httpx import AsyncClient

from api.main import create_app
from api.middleware.ratelimit import InMemoryRateLimiter


@pytest.fixture
def limiter():
    return InMemoryRateLimiter(max_requests=5, window_seconds=60)


def test_requests_within_limit_pass(limiter):
    """Requests within the limit are allowed."""
    agent_id = "agent-rate-test-001"
    for _ in range(5):
        allowed = limiter.check_and_increment(agent_id)
        assert allowed is True


def test_requests_exceeding_limit_blocked(limiter):
    """The (limit+1)th request within the window is blocked."""
    agent_id = "agent-rate-test-002"
    for _ in range(5):
        limiter.check_and_increment(agent_id)

    blocked = limiter.check_and_increment(agent_id)
    assert blocked is False


def test_rate_limit_window_reset(limiter):
    """After the window expires, the counter resets."""
    fast_limiter = InMemoryRateLimiter(max_requests=2, window_seconds=1)
    agent_id = "agent-rate-window-001"

    fast_limiter.check_and_increment(agent_id)
    fast_limiter.check_and_increment(agent_id)
    assert fast_limiter.check_and_increment(agent_id) is False

    time.sleep(1.1)

    # After window reset, requests should pass again
    assert fast_limiter.check_and_increment(agent_id) is True


def test_different_agents_have_independent_limits(limiter):
    """Rate limits are tracked independently per agent."""
    agent_a = "agent-a"
    agent_b = "agent-b"

    for _ in range(5):
        limiter.check_and_increment(agent_a)

    # agent_a is blocked
    assert limiter.check_and_increment(agent_a) is False
    # agent_b is still allowed
    assert limiter.check_and_increment(agent_b) is True


@pytest.mark.asyncio
async def test_api_returns_429_when_rate_limited():
    """The API returns 429 when an agent exceeds its rate limit."""
    app = create_app()

    from identity.issuance.broker.broker import TokenBroker

    broker = TokenBroker()
    token = broker.issue_token("rl-agent-001", "T0", ["rag_search"])

    with patch("api.middleware.ratelimit.InMemoryRateLimiter.check_and_increment", return_value=False):
        async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/mcp/tools",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 429

"""Unit tests for tool scope enforcement."""

from __future__ import annotations

import pytest

from identity.issuance.broker.broker import TokenBroker


@pytest.fixture
def broker():
    return TokenBroker()


@pytest.fixture
def t0_token(broker):
    return broker.issue_token("agent-t0", "T0", ["rag_search"])


@pytest.fixture
def t1_token(broker):
    return broker.issue_token("agent-t1", "T1", ["rag_search", "mcp_audit_query"])


@pytest.fixture
def t2_token(broker):
    return broker.issue_token("agent-t2", "T2", ["rag_search", "mcp_audit_query", "code_execute"])


def test_valid_token_claims(broker, t1_token):
    """Token claims include expected fields."""
    claims = broker.validate_token(t1_token)
    assert claims["agent_id"] == "agent-t1"
    assert claims["tier"] == "T1"
    assert "rag_search" in claims["grants"]
    assert "jti" in claims


def test_t0_token_has_limited_grants(broker, t0_token):
    """T0 tokens only carry their declared grants."""
    claims = broker.validate_token(t0_token)
    assert claims["tier"] == "T0"
    assert "code_execute" not in claims["grants"]


def test_t2_token_has_full_grants(broker, t2_token):
    """T2 tokens carry all declared grants."""
    claims = broker.validate_token(t2_token)
    assert claims["tier"] == "T2"
    assert "code_execute" in claims["grants"]


def test_token_revocation_blocks_reuse(broker, t1_token):
    """Revoked token raises ValueError on validation."""
    claims = broker.validate_token(t1_token)
    jti = claims["jti"]
    broker.revoke_token(jti)
    with pytest.raises(ValueError, match="revoked"):
        broker.validate_token(t1_token)


def test_invalid_tier_raises_value_error(broker):
    """Issuing a token with an unknown tier raises ValueError."""
    with pytest.raises(ValueError, match="Unknown tier"):
        broker.issue_token("agent-x", "T9", [])


def test_token_ttl_respected(broker):
    """Token issued with 1-second TTL expires quickly."""
    import time

    token = broker.issue_token("agent-ttl", "T0", [], ttl_seconds=1)
    claims = broker.validate_token(token)
    assert claims["agent_id"] == "agent-ttl"

    time.sleep(2)

    import jwt

    with pytest.raises(jwt.ExpiredSignatureError):
        broker.validate_token(token)


def test_is_revoked_returns_false_for_active_token(broker, t1_token):
    """is_revoked returns False for tokens that have not been revoked."""
    claims = broker.validate_token(t1_token)
    assert broker.is_revoked(claims["jti"]) is False


def test_is_revoked_returns_true_after_revocation(broker, t0_token):
    """is_revoked returns True after explicit revocation."""
    claims = broker.validate_token(t0_token)
    jti = claims["jti"]
    broker.revoke_token(jti)
    assert broker.is_revoked(jti) is True

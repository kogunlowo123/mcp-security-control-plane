"""Shared pytest fixtures for all test suites."""

from __future__ import annotations

import pytest

from identity.issuance.broker.broker import TokenBroker


@pytest.fixture(scope="session")
def token_broker():
    """Shared TokenBroker instance for tests."""
    return TokenBroker()


@pytest.fixture
def t0_token(token_broker):
    return token_broker.issue_token("test-t0-agent", "T0", ["rag_search"])


@pytest.fixture
def t1_token(token_broker):
    return token_broker.issue_token(
        "test-t1-agent", "T1", ["rag_search", "mcp_audit_query"]
    )


@pytest.fixture
def t2_token(token_broker):
    return token_broker.issue_token(
        "test-t2-agent", "T2", ["rag_search", "mcp_audit_query", "code_execute"]
    )

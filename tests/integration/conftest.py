"""Integration test fixtures."""

from __future__ import annotations

import pytest

from api.main import create_app
from identity.issuance.broker.broker import TokenBroker


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture(scope="module")
def broker():
    return TokenBroker()


@pytest.fixture(scope="module")
def integration_token(broker):
    return broker.issue_token(
        "integration-agent-001",
        "T1",
        ["rag_search", "mcp_audit_query"],
    )

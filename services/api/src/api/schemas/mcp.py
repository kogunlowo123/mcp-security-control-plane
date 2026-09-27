"""
Pydantic v2 schemas for MCP security control-plane messages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """Incoming request asking whether an agent may call a tool."""

    agent_id: str = Field(..., description="Unique identifier of the calling agent")
    tool_name: str = Field(..., description="Name of the MCP tool being invoked")
    tool_parameters: dict = Field(
        default_factory=dict,
        description="Parameters supplied to the tool call",
    )
    scope: str = Field(..., description="OAuth-style scope the agent is operating under")
    context: Optional[dict] = Field(
        default=None,
        description="Optional ambient context (session ID, user claims, etc.)",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "agent_id": "agent-abc123",
            "tool_name": "file-read",
            "tool_parameters": {"path": "/data/report.csv"},
            "scope": "read:files",
            "context": {"session_id": "sess-xyz"},
        }
    }}


class AuthorizationDecision(BaseModel):
    """Policy evaluation result returned to the caller."""

    decision: Literal["permit", "deny"] = Field(
        ..., description="Whether the tool call is permitted"
    )
    reason: str = Field(..., description="Human-readable explanation of the decision")
    policy_version: str = Field(
        ..., description="Version string of the OPA policy bundle that was evaluated"
    )
    trace_id: str = Field(
        ..., description="Distributed trace ID for correlating logs and spans"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the decision",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "decision": "permit",
            "reason": "Agent tier and scope satisfy policy rule mcp.control.allow",
            "policy_version": "v1.2.0",
            "trace_id": "abc123def456",
            "timestamp": "2024-01-15T10:30:00Z",
        }
    }}


class AuditRecord(BaseModel):
    """Single entry written to the persistent audit log."""

    audit_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="UUID that uniquely identifies this audit entry",
    )
    agent_id: str = Field(..., description="Agent that attempted the tool call")
    tool_name: str = Field(..., description="Tool that was requested")
    tool_parameters: dict = Field(
        default_factory=dict,
        description="Parameters supplied to the tool call",
    )
    decision: str = Field(..., description="Authorization decision: 'permit' or 'deny'")
    scope: str = Field(..., description="Scope active at the time of the call")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the tool call",
    )
    trace_id: str = Field(..., description="Distributed trace ID")

    model_config = {"json_schema_extra": {
        "example": {
            "audit_id": "550e8400-e29b-41d4-a716-446655440000",
            "agent_id": "agent-abc123",
            "tool_name": "file-read",
            "tool_parameters": {"path": "/data/report.csv"},
            "decision": "permit",
            "scope": "read:files",
            "timestamp": "2024-01-15T10:30:00Z",
            "trace_id": "abc123def456",
        }
    }}


class ViolationRecord(BaseModel):
    """Security violation detected during policy evaluation."""

    violation_id: str = Field(..., description="Unique identifier of the violation")
    agent_id: str = Field(..., description="Agent responsible for the violation")
    tool_name: str = Field(..., description="Tool call that triggered the violation")
    violation_type: str = Field(
        ..., description="Machine-readable violation category (e.g. scope_exceeded)"
    )
    description: str = Field(..., description="Human-readable description of the violation")
    severity: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Severity classification"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the violation was detected",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "violation_id": "viol-001",
            "agent_id": "agent-abc123",
            "tool_name": "code-execute",
            "violation_type": "scope_exceeded",
            "description": "Agent attempted code-execute without the required execute:code scope",
            "severity": "high",
            "timestamp": "2024-01-15T10:30:00Z",
        }
    }}

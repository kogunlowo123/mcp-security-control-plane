"""ApprovalGate — human-in-the-loop approval for T1 agents on sensitive operations."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import aioboto3
import structlog

logger = structlog.get_logger(__name__)

_SQS_APPROVAL_QUEUE_URL = os.environ.get("APPROVAL_SQS_QUEUE_URL", "")
_SQS_RESPONSE_QUEUE_URL = os.environ.get("APPROVAL_RESPONSE_SQS_QUEUE_URL", "")
_APPROVAL_TIMEOUT_SECONDS = int(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "300"))
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"


@dataclass
class ApprovalRequest:
    """Represents a pending human approval request."""

    request_id: str
    agent_id: str
    session_id: str
    operation: str
    tool_name: str
    parameters: dict[str, Any]
    risk_level: str  # CRITICAL | HIGH | MEDIUM
    justification: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_seconds: int = _APPROVAL_TIMEOUT_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "operation": self.operation,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
            "justification": self.justification,
            "created_at": self.created_at.isoformat(),
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass
class ApprovalResult:
    """The resolved result of an approval request."""

    request_id: str
    decision: ApprovalDecision
    reviewer: str | None
    reason: str
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def approved(self) -> bool:
        return self.decision == ApprovalDecision.APPROVED


class ApprovalGate:
    """Human-in-the-loop approval gate for T1 agents performing sensitive operations.

    When an agent (tier T1) attempts a sensitive tool call or operation, it
    should call :meth:`request_approval` and await the result before proceeding.
    Approval requests are published to SQS; responses are polled from a
    response queue. In environments where SQS is unavailable (e.g. local dev),
    the gate auto-approves if ``APPROVAL_AUTO_APPROVE=true`` is set.

    Args:
        agent_id: Registry ID of the agent requesting approval.
        session_id: Current session identifier (for correlation).
        timeout_seconds: How long to wait for a human decision before timing out.
    """

    _AUTO_APPROVE = os.environ.get("APPROVAL_AUTO_APPROVE", "false").lower() == "true"

    def __init__(
        self,
        agent_id: str,
        session_id: str,
        timeout_seconds: int = _APPROVAL_TIMEOUT_SECONDS,
    ) -> None:
        self._agent_id = agent_id
        self._session_id = session_id
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, ApprovalRequest] = {}

    async def request_approval(
        self,
        operation: str,
        tool_name: str,
        parameters: dict[str, Any],
        risk_level: str = "HIGH",
        justification: str = "",
    ) -> ApprovalResult:
        """Submit an approval request and wait for a human decision.

        Args:
            operation: Short label for the operation (e.g. ``"scope_revocation"``).
            tool_name: The tool being invoked (for display in the approval UI).
            parameters: Proposed call parameters shown to the reviewer.
            risk_level: ``"CRITICAL"``, ``"HIGH"``, or ``"MEDIUM"``.
            justification: Why this operation is necessary (shown to reviewer).

        Returns:
            An :class:`ApprovalResult` with the reviewer's decision.
        """
        request_id = str(uuid.uuid4())
        request = ApprovalRequest(
            request_id=request_id,
            agent_id=self._agent_id,
            session_id=self._session_id,
            operation=operation,
            tool_name=tool_name,
            parameters=parameters,
            risk_level=risk_level,
            justification=justification,
            timeout_seconds=self._timeout_seconds,
        )
        self._pending[request_id] = request

        log = logger.bind(
            request_id=request_id,
            agent=self._agent_id,
            operation=operation,
            risk=risk_level,
        )
        log.info("approval.request_submitted")

        if self._AUTO_APPROVE:
            log.warning("approval.auto_approved", reason="APPROVAL_AUTO_APPROVE=true")
            return ApprovalResult(
                request_id=request_id,
                decision=ApprovalDecision.APPROVED,
                reviewer="system_auto",
                reason="Auto-approved (dev mode)",
            )

        if not _SQS_APPROVAL_QUEUE_URL:
            log.error("approval.no_sqs_queue_configured")
            return ApprovalResult(
                request_id=request_id,
                decision=ApprovalDecision.ERROR,
                reviewer=None,
                reason="Approval SQS queue not configured; cannot proceed.",
            )

        # Publish to approval request queue
        try:
            await self._publish_request(request)
        except Exception as exc:
            log.error("approval.publish_failed", error=str(exc))
            return ApprovalResult(
                request_id=request_id,
                decision=ApprovalDecision.ERROR,
                reviewer=None,
                reason=f"Failed to publish approval request: {exc}",
            )

        # Poll for response
        try:
            result = await asyncio.wait_for(
                self._poll_for_response(request_id),
                timeout=float(self._timeout_seconds),
            )
        except asyncio.TimeoutError:
            log.warning("approval.timed_out", timeout=self._timeout_seconds)
            result = ApprovalResult(
                request_id=request_id,
                decision=ApprovalDecision.TIMED_OUT,
                reviewer=None,
                reason=f"No human response within {self._timeout_seconds} seconds.",
            )

        log.info("approval.resolved", decision=result.decision.value)
        self._pending.pop(request_id, None)
        return result

    async def _publish_request(self, request: ApprovalRequest) -> None:
        """Publish approval request to SQS."""
        import json

        session = aioboto3.Session()
        async with session.client("sqs", region_name=_AWS_REGION) as sqs:
            await sqs.send_message(
                QueueUrl=_SQS_APPROVAL_QUEUE_URL,
                MessageBody=json.dumps(request.to_dict()),
                MessageAttributes={
                    "request_id": {"StringValue": request.request_id, "DataType": "String"},
                    "agent_id": {"StringValue": request.agent_id, "DataType": "String"},
                    "risk_level": {"StringValue": request.risk_level, "DataType": "String"},
                },
            )

    async def _poll_for_response(self, request_id: str) -> ApprovalResult:
        """Long-poll SQS response queue for a human decision."""
        import json

        session = aioboto3.Session()
        async with session.client("sqs", region_name=_AWS_REGION) as sqs:
            while True:
                response = await sqs.receive_message(
                    QueueUrl=_SQS_RESPONSE_QUEUE_URL,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=20,
                    MessageAttributeNames=["All"],
                )
                for message in response.get("Messages", []):
                    body = json.loads(message["Body"])
                    if body.get("request_id") == request_id:
                        # Delete from queue
                        await sqs.delete_message(
                            QueueUrl=_SQS_RESPONSE_QUEUE_URL,
                            ReceiptHandle=message["ReceiptHandle"],
                        )
                        decision_str = body.get("decision", "ERROR")
                        try:
                            decision = ApprovalDecision(decision_str)
                        except ValueError:
                            decision = ApprovalDecision.ERROR

                        return ApprovalResult(
                            request_id=request_id,
                            decision=decision,
                            reviewer=body.get("reviewer"),
                            reason=body.get("reason", ""),
                        )
                # No matching message yet — yield and retry
                await asyncio.sleep(1)

    def get_pending_requests(self) -> list[ApprovalRequest]:
        """Return all currently pending approval requests for this gate."""
        return list(self._pending.values())

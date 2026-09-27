"""Session events — SessionEvent dataclass and SQS publishing."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import aioboto3
import structlog

logger = structlog.get_logger(__name__)

_SQS_EVENTS_QUEUE_URL = os.environ.get("SESSION_EVENTS_SQS_QUEUE_URL", "")
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class SessionEventType(str, Enum):
    SESSION_CREATED = "session.created"
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"
    SESSION_EXPIRED = "session.expired"
    STATE_UPDATED = "session.state_updated"
    APPROVAL_REQUESTED = "session.approval_requested"
    APPROVAL_RESOLVED = "session.approval_resolved"
    VIOLATION_DETECTED = "session.violation_detected"
    REPORT_GENERATED = "session.report_generated"


@dataclass
class SessionEvent:
    """Represents a publishable session lifecycle event.

    Events are published to SQS for downstream processing by:
    - Observability pipelines (OpenTelemetry / CloudWatch)
    - Audit log enrichment services
    - Alert routing systems
    - Dashboard real-time updates
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: SessionEventType = SessionEventType.SESSION_CREATED
    session_id: str = ""
    agent_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def session_created(
        cls,
        session_id: str,
        agent_id: str,
        task: str | None = None,
        trace_id: str | None = None,
    ) -> "SessionEvent":
        return cls(
            event_type=SessionEventType.SESSION_CREATED,
            session_id=session_id,
            agent_id=agent_id,
            payload={"task": task},
            trace_id=trace_id,
        )

    @classmethod
    def session_completed(
        cls,
        session_id: str,
        agent_id: str,
        violations_found: int = 0,
        report_generated: bool = False,
        trace_id: str | None = None,
    ) -> "SessionEvent":
        return cls(
            event_type=SessionEventType.SESSION_COMPLETED,
            session_id=session_id,
            agent_id=agent_id,
            payload={
                "violations_found": violations_found,
                "report_generated": report_generated,
            },
            trace_id=trace_id,
        )

    @classmethod
    def session_failed(
        cls,
        session_id: str,
        agent_id: str,
        error: str,
        trace_id: str | None = None,
    ) -> "SessionEvent":
        return cls(
            event_type=SessionEventType.SESSION_FAILED,
            session_id=session_id,
            agent_id=agent_id,
            payload={"error": error},
            trace_id=trace_id,
        )

    @classmethod
    def violation_detected(
        cls,
        session_id: str,
        agent_id: str,
        violation: dict[str, Any],
        trace_id: str | None = None,
    ) -> "SessionEvent":
        return cls(
            event_type=SessionEventType.VIOLATION_DETECTED,
            session_id=session_id,
            agent_id=agent_id,
            payload={"violation": violation},
            trace_id=trace_id,
        )


class SessionEventPublisher:
    """Publishes :class:`SessionEvent` instances to an SQS queue.

    If the queue URL is not configured, events are logged locally and
    silently dropped (no error raised). This allows the agent runtime to
    function in development / CI environments without AWS.

    Args:
        queue_url: SQS queue URL. Defaults to ``SESSION_EVENTS_SQS_QUEUE_URL`` env.
        region: AWS region. Defaults to ``AWS_REGION`` env.
    """

    def __init__(
        self,
        queue_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self._queue_url = queue_url or _SQS_EVENTS_QUEUE_URL
        self._region = region or _AWS_REGION

    async def publish(self, event: SessionEvent) -> bool:
        """Publish a single event to SQS.

        Args:
            event: The :class:`SessionEvent` to publish.

        Returns:
            True if published successfully, False if the queue is not configured
            or the publish failed.
        """
        log = logger.bind(
            event_id=event.event_id,
            event_type=event.event_type.value,
            session_id=event.session_id,
            agent_id=event.agent_id,
        )

        if not self._queue_url:
            log.debug("session_event.no_queue_configured", event=event.to_dict())
            return False

        try:
            session = aioboto3.Session()
            async with session.client("sqs", region_name=self._region) as sqs:
                await sqs.send_message(
                    QueueUrl=self._queue_url,
                    MessageBody=event.to_json(),
                    MessageAttributes={
                        "event_type": {
                            "StringValue": event.event_type.value,
                            "DataType": "String",
                        },
                        "agent_id": {
                            "StringValue": event.agent_id,
                            "DataType": "String",
                        },
                        "session_id": {
                            "StringValue": event.session_id,
                            "DataType": "String",
                        },
                    },
                )
            log.info("session_event.published")
            return True

        except Exception as exc:
            log.error("session_event.publish_failed", error=str(exc))
            return False

    async def publish_many(self, events: list[SessionEvent]) -> int:
        """Publish multiple events. Returns count of successfully published events."""
        results = [await self.publish(event) for event in events]
        return sum(1 for r in results if r)

"""Gateway-level audit logging."""

from __future__ import annotations

import json
import logging
import time
from typing import Any


logger = logging.getLogger(__name__)


class AuditLogger:
    """Writes structured audit events to stdout/CloudWatch."""

    def log_gateway_event(
        self,
        event_type: str,
        agent_id: str,
        tool_name: str,
        decision: str,
        trace_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured audit log entry."""
        entry = {
            "event": event_type,
            "timestamp": time.time(),
            "agent_id": agent_id,
            "tool_name": tool_name,
            "decision": decision,
            "trace_id": trace_id,
        }
        if extra:
            entry.update(extra)
        logger.info(json.dumps(entry))

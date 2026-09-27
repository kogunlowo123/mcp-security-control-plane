"""MCPAuditQueryTool — read-only query interface to the PostgreSQL audit_log table.

Available to T0+ agents. Returns paginated audit log records matching the
supplied filters.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import asyncpg
import structlog

from agent_runtime.tools.base import MCPTool

logger = structlog.get_logger(__name__)

_DB_DSN = os.environ.get(
    "AUDIT_DB_DSN",
    "postgresql://agentruntime:agentruntime@localhost:5432/mcpsecurity",
)
_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string into a timezone-aware datetime."""
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class MCPAuditQueryTool(MCPTool):
    """Query the PostgreSQL ``audit_log`` table for MCP tool call records.

    Accepts optional filters for agent_id, tool_name, time range, and
    decision. Returns paginated results with total count metadata.

    Available to T0 and above (read-only operation, no mutations).
    """

    tool_id = "mcp_audit_query"
    display_name = "MCP Audit Log Query"
    description = (
        "Queries the PostgreSQL audit_log table for MCP tool call records. "
        "Supports filtering by agent, tool name, time range, and decision. "
        "Read-only, paginated. Available to T0+ agents."
    )
    min_tier = "T0"
    read_only = True
    input_schema = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string"},
            "tool_name": {"type": "string"},
            "start_time": {"type": "string", "format": "date-time"},
            "end_time": {"type": "string", "format": "date-time"},
            "decision": {"type": "string", "enum": ["ALLOW", "BLOCK", "PENDING"]},
            "page": {"type": "integer", "minimum": 1, "default": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
    }

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a filtered query against the audit_log table.

        Args:
            params: Optional filter keys: ``agent_id``, ``tool_name``,
                ``start_time``, ``end_time``, ``decision``, ``page``,
                ``page_size``.

        Returns:
            ``{"success": True, "data": {"records": [...], "total": N,
            "page": N, "page_size": N, "pages": N}}``.
            Each record mirrors the ``audit_log`` table columns.
        """
        agent_id_filter: str | None = params.get("agent_id")
        tool_name_filter: str | None = params.get("tool_name")
        start_time: datetime | None = _parse_dt(params.get("start_time"))
        end_time: datetime | None = _parse_dt(params.get("end_time"))
        decision_filter: str | None = params.get("decision")
        page: int = max(1, int(params.get("page", 1)))
        page_size: int = min(_MAX_PAGE_SIZE, max(1, int(params.get("page_size", _DEFAULT_PAGE_SIZE))))
        offset = (page - 1) * page_size

        log = logger.bind(
            tool=self.tool_id,
            caller=self._caller_agent_id,
            filters={
                "agent_id": agent_id_filter,
                "tool_name": tool_name_filter,
                "decision": decision_filter,
                "start_time": str(start_time) if start_time else None,
                "end_time": str(end_time) if end_time else None,
            },
        )
        log.info("mcp_audit_query.execute")

        # Build WHERE clause dynamically
        conditions: list[str] = []
        args: list[Any] = []
        idx = 1

        if agent_id_filter:
            conditions.append(f"agent_id = ${idx}")
            args.append(agent_id_filter)
            idx += 1
        if tool_name_filter:
            conditions.append(f"tool_name = ${idx}")
            args.append(tool_name_filter)
            idx += 1
        if start_time:
            conditions.append(f"created_at >= ${idx}")
            args.append(start_time)
            idx += 1
        if end_time:
            conditions.append(f"created_at <= ${idx}")
            args.append(end_time)
            idx += 1
        if decision_filter:
            conditions.append(f"decision = ${idx}")
            args.append(decision_filter)
            idx += 1

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        count_query = f"SELECT COUNT(*) FROM audit_log {where_clause}"
        data_query = (
            f"SELECT id, agent_id, tool_name, parameters, decision, "
            f"decision_reason, created_at, session_id, trace_id "
            f"FROM audit_log {where_clause} "
            f"ORDER BY created_at DESC "
            f"LIMIT {page_size} OFFSET {offset}"
        )

        try:
            conn: asyncpg.Connection = await asyncpg.connect(dsn=_DB_DSN)
            try:
                total: int = await conn.fetchval(count_query, *args)
                rows: list[asyncpg.Record] = await conn.fetch(data_query, *args)
            finally:
                await conn.close()

        except asyncpg.PostgresConnectionFailureError as exc:
            log.error("mcp_audit_query.db_connection_error", error=str(exc))
            return self._err(f"Database connection failed: {exc}", code="DB_CONNECTION_ERROR")
        except asyncpg.PostgresError as exc:
            log.error("mcp_audit_query.db_error", error=str(exc))
            return self._err(f"Database query failed: {exc}", code="DB_QUERY_ERROR")

        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            # Serialise datetime to ISO string for JSON safety
            if isinstance(record.get("created_at"), datetime):
                record["created_at"] = record["created_at"].isoformat()
            records.append(record)

        total_pages = max(1, (total + page_size - 1) // page_size)
        log.info("mcp_audit_query.complete", records=len(records), total=total)

        return self._ok(
            data={
                "records": records,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": total_pages,
            }
        )

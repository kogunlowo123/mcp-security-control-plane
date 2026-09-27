"""
MCP security routes.

POST /api/v1/mcp/authorize  – policy-enforcement point for tool calls
POST /api/v1/mcp/audit      – write a pre-built audit record to PostgreSQL
GET  /api/v1/mcp/violations – paginated violation log from PostgreSQL
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg2
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace

from api.schemas.mcp import (
    AuditRecord,
    AuthorizationDecision,
    ToolCallRequest,
    ViolationRecord,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["MCP Security"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOL_CATALOG_NAMES: set[str] = {
    "file-read",
    "web-search",
    "code-execute",
    "db-query",
    "api-call",
}

# Required scope per tool name (mirrors the tool catalog in tools.py)
_TOOL_SCOPE_MAP: dict[str, str] = {
    "file-read": "read:files",
    "web-search": "read:web",
    "code-execute": "execute:code",
    "db-query": "read:database",
    "api-call": "call:external-api",
}

# Minimum agent tier per tool (standard < privileged < admin)
_TIER_ORDER = {"standard": 0, "privileged": 1, "admin": 2}
_TOOL_MIN_TIER: dict[str, str] = {
    "file-read": "standard",
    "web-search": "standard",
    "code-execute": "privileged",
    "db-query": "privileged",
    "api-call": "admin",
}


def _get_trace_id(request: Request) -> str:
    """
    Return the trace_id that TracingMiddleware set on request.state, or fall
    back to a freshly generated hex string so audit records are never empty.
    """
    return getattr(request.state, "trace_id", uuid.uuid4().hex)


def _build_cloud_event(
    event_type: str,
    source: str,
    data: dict[str, Any],
    trace_id: str,
) -> dict[str, Any]:
    """
    Construct a CloudEvents 1.0-compatible envelope as a plain dict.
    No external 'cloudevents' package is required.
    """
    return {
        "specversion": "1.0",
        "type": event_type,
        "source": source,
        "id": str(uuid.uuid4()),
        "time": datetime.now(tz=timezone.utc).isoformat(),
        "datacontenttype": "application/json",
        "traceid": trace_id,
        "data": data,
    }


def _emit_cloud_event(event: dict[str, Any]) -> None:
    """
    Emit a CloudEvent.  In a full deployment this would publish to Kafka /
    EventBridge / Pub-Sub.  Here we log at INFO level so the event appears in
    the structured log stream and can be forwarded by a log-shipper.
    """
    logger.info(
        "cloud_event type=%s id=%s",
        event.get("type"),
        event.get("id"),
        extra={"cloud_event": event},
    )


def _write_audit_record(conn: Any, record: AuditRecord) -> None:
    """Persist an AuditRecord to the audit_log table."""
    sql = """
        INSERT INTO audit_log (
            audit_id, agent_id, tool_name, tool_parameters,
            decision, scope, timestamp, trace_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (audit_id) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record.audit_id,
                record.agent_id,
                record.tool_name,
                json.dumps(record.tool_parameters),
                record.decision,
                record.scope,
                record.timestamp,
                record.trace_id,
            ),
        )


# ---------------------------------------------------------------------------
# POST /api/v1/mcp/authorize
# ---------------------------------------------------------------------------
@router.post(
    "/authorize",
    response_model=AuthorizationDecision,
    summary="Authorize an MCP tool call",
    status_code=200,
)
async def authorize_tool_call(
    payload: ToolCallRequest,
    request: Request,
) -> AuthorizationDecision:
    """
    Policy-enforcement point for MCP tool calls.

    1. Extracts agent identity set by AuthMiddleware from request.state.
    2. Validates the requested tool exists in the catalog.
    3. Calls OPA to evaluate the mcp.control.allow policy.
    4. Emits a CloudEvent (mcp.tool.called or mcp.violation).
    5. Writes an audit record to PostgreSQL.
    6. Returns an AuthorizationDecision.
    """
    tracer = trace.get_tracer(__name__)
    trace_id = _get_trace_id(request)

    # Agent identity is set by AuthMiddleware; default to payload value if
    # middleware skipped (e.g. JWT disabled in dev).
    agent_id: str = getattr(request.state, "agent_id", payload.agent_id)
    agent_tier: str = getattr(request.state, "tier", "standard")
    agent_grants: list[str] = getattr(request.state, "grants", [])

    with tracer.start_as_current_span("mcp.authorize") as span:
        span.set_attribute("agent.id", agent_id)
        span.set_attribute("mcp.tool", payload.tool_name)
        span.set_attribute("mcp.scope", payload.scope)

        # --- Tool catalog lookup ---
        if payload.tool_name not in _TOOL_CATALOG_NAMES:
            raise HTTPException(
                status_code=404,
                detail=f"Tool '{payload.tool_name}' is not registered in the catalog.",
            )

        # --- OPA policy evaluation ---
        opa_input: dict[str, Any] = {
            "agent_id": agent_id,
            "agent_tier": agent_tier,
            "agent_grants": agent_grants,
            "tool_name": payload.tool_name,
            "scope": payload.scope,
            "tool_parameters": payload.tool_parameters,
            "context": payload.context or {},
        }

        policy_version = "unknown"
        opa_allowed = False
        opa_reason = "OPA evaluation did not return a result"

        http_client: httpx.AsyncClient | None = getattr(
            request.app.state, "http_client", None
        )

        try:
            if http_client is not None:
                opa_resp = await http_client.post(
                    "/v1/data/mcp/control/allow",
                    json={"input": opa_input},
                )
            else:
                from api.config import settings as _s  # lazy import
                async with httpx.AsyncClient(timeout=_s.opa_timeout_seconds) as tmp:
                    opa_resp = await tmp.post(
                        f"{_s.opa_url}/v1/data/mcp/control/allow",
                        json={"input": opa_input},
                    )

            opa_body = opa_resp.json()
            opa_allowed = bool(opa_body.get("result", False))
            policy_version = opa_body.get("policy_version", "v1.0.0")
            if opa_allowed:
                opa_reason = "Policy rule mcp.control.allow evaluated to true"
            else:
                opa_reason = opa_body.get(
                    "reason",
                    "Policy rule mcp.control.allow evaluated to false",
                )

        except httpx.TimeoutException:
            logger.error("OPA request timed out for agent=%s tool=%s", agent_id, payload.tool_name)
            # Fail closed – deny on OPA unavailability
            opa_allowed = False
            opa_reason = "Policy engine unavailable – request denied for safety"
        except Exception as exc:  # noqa: BLE001
            logger.error("OPA request failed: %s", exc)
            opa_allowed = False
            opa_reason = f"Policy evaluation error: {exc}"

        decision: str = "permit" if opa_allowed else "deny"
        span.set_attribute("mcp.decision", decision)

        # --- CloudEvent emission ---
        event_type = "mcp.tool.called" if opa_allowed else "mcp.violation"
        cloud_event = _build_cloud_event(
            event_type=event_type,
            source=f"/api/v1/mcp/authorize/{agent_id}",
            data={
                "agent_id": agent_id,
                "tool_name": payload.tool_name,
                "scope": payload.scope,
                "decision": decision,
                "reason": opa_reason,
            },
            trace_id=trace_id,
        )
        _emit_cloud_event(cloud_event)

        # --- Audit log ---
        audit_record = AuditRecord(
            agent_id=agent_id,
            tool_name=payload.tool_name,
            tool_parameters=payload.tool_parameters,
            decision=decision,
            scope=payload.scope,
            timestamp=datetime.now(tz=timezone.utc),
            trace_id=trace_id,
        )

        db_conn = getattr(request.app.state, "db_conn", None)
        if db_conn is not None:
            try:
                _write_audit_record(db_conn, audit_record)
            except psycopg2.Error as db_err:
                # Non-fatal: log and continue; audit failures should not block
                # the authorization response.
                logger.error("Failed to write audit record: %s", db_err)

        # --- Violation record (if denied) ---
        if not opa_allowed and db_conn is not None:
            try:
                sql_viol = """
                    INSERT INTO violations (
                        violation_id, agent_id, tool_name, violation_type,
                        description, severity, timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (violation_id) DO NOTHING
                """
                # Determine severity heuristically from tier vs. tool requirements
                required_tier = _TOOL_MIN_TIER.get(payload.tool_name, "standard")
                agent_tier_val = _TIER_ORDER.get(agent_tier, 0)
                req_tier_val = _TIER_ORDER.get(required_tier, 0)

                if agent_tier_val < req_tier_val:
                    violation_type = "insufficient_tier"
                    severity = "high"
                elif payload.scope not in (agent_grants or [payload.scope]):
                    violation_type = "scope_exceeded"
                    severity = "medium"
                else:
                    violation_type = "policy_denied"
                    severity = "low"

                with db_conn.cursor() as cur:
                    cur.execute(
                        sql_viol,
                        (
                            str(uuid.uuid4()),
                            agent_id,
                            payload.tool_name,
                            violation_type,
                            opa_reason,
                            severity,
                            datetime.now(tz=timezone.utc),
                        ),
                    )
            except psycopg2.Error as db_err:
                logger.error("Failed to write violation record: %s", db_err)

        return AuthorizationDecision(
            decision=decision,  # type: ignore[arg-type]
            reason=opa_reason,
            policy_version=policy_version,
            trace_id=trace_id,
            timestamp=datetime.now(tz=timezone.utc),
        )


# ---------------------------------------------------------------------------
# POST /api/v1/mcp/audit
# ---------------------------------------------------------------------------
@router.post(
    "/audit",
    summary="Persist an audit record",
    status_code=201,
)
async def write_audit(
    record: AuditRecord,
    request: Request,
) -> JSONResponse:
    """
    Accept a pre-built AuditRecord and persist it to the PostgreSQL audit_log
    table.  Callers are responsible for constructing the record (e.g. edge
    nodes that cannot reach the authorize endpoint synchronously).
    """
    db_conn = getattr(request.app.state, "db_conn", None)
    if db_conn is None:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable – audit record not persisted.",
        )

    try:
        _write_audit_record(db_conn, record)
    except psycopg2.Error as exc:
        logger.error("audit write failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to persist audit record: {exc}",
        ) from exc

    return JSONResponse(
        status_code=201,
        content={"audit_id": record.audit_id, "status": "persisted"},
    )


# ---------------------------------------------------------------------------
# GET /api/v1/mcp/violations
# ---------------------------------------------------------------------------
@router.get(
    "/violations",
    summary="List recent security violations",
    status_code=200,
)
async def list_violations(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    agent_id: str | None = Query(default=None, description="Filter by agent ID"),
    severity: str | None = Query(default=None, description="Filter by severity"),
) -> dict:
    """
    Return a paginated list of recent security violations from PostgreSQL.
    Returns an empty list (not 503) when the database is unavailable so
    dashboards remain functional during DB maintenance.
    """
    db_conn = getattr(request.app.state, "db_conn", None)
    if db_conn is None:
        return {
            "violations": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "warning": "Database unavailable – results may be incomplete",
        }

    offset = (page - 1) * page_size
    filters: list[str] = []
    params: list[Any] = []

    if agent_id:
        filters.append("agent_id = %s")
        params.append(agent_id)
    if severity:
        filters.append("severity = %s")
        params.append(severity)

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    count_sql = f"SELECT COUNT(*) FROM violations {where_clause}"
    data_sql = f"""
        SELECT violation_id, agent_id, tool_name, violation_type,
               description, severity, timestamp
        FROM violations
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """

    try:
        with db_conn.cursor() as cur:
            cur.execute(count_sql, params)
            row = cur.fetchone()
            total: int = row[0] if row else 0

            cur.execute(data_sql, params + [page_size, offset])
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        logger.error("violations query failed: %s", exc)
        return {
            "violations": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "error": str(exc),
        }

    violations = [
        ViolationRecord(
            violation_id=str(r[0]),
            agent_id=str(r[1]),
            tool_name=str(r[2]),
            violation_type=str(r[3]),
            description=str(r[4]),
            severity=r[5],
            timestamp=r[6],
        ).model_dump(mode="json")
        for r in rows
    ]

    return {
        "violations": violations,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

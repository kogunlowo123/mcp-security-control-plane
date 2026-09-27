"""
Tool catalog endpoint.

GET /api/v1/mcp/tools – return a paginated list of registered MCP tools.

The catalog is held in-memory for the control-plane service.  In production
this would be backed by a database, but the schema and behaviour are identical.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.schemas.tool import ToolCatalogResponse, ToolDefinition

router = APIRouter(tags=["Tools"])

# ---------------------------------------------------------------------------
# In-memory tool catalog – 5 real MCP tools with different scopes/tiers
# ---------------------------------------------------------------------------
_TOOL_CATALOG: list[ToolDefinition] = [
    ToolDefinition(
        tool_id="tool-file-read-v1",
        name="file-read",
        description=(
            "Read the contents of a file within the agent's permitted filesystem "
            "namespace.  The path must resolve within the allowed root."
        ),
        allowed_scopes=["read:files"],
        allowed_agent_tiers=["standard", "privileged", "admin"],
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "encoding": {
                    "type": "string",
                    "enum": ["utf-8", "latin-1", "binary"],
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        },
        is_active=True,
    ),
    ToolDefinition(
        tool_id="tool-web-search-v1",
        name="web-search",
        description=(
            "Execute a web search query and return a list of result summaries.  "
            "Results are fetched from an approved search API and do not expose "
            "raw HTML or scripts."
        ),
        allowed_scopes=["read:web"],
        allowed_agent_tiers=["standard", "privileged", "admin"],
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        is_active=True,
    ),
    ToolDefinition(
        tool_id="tool-code-execute-v1",
        name="code-execute",
        description=(
            "Execute a sandboxed code snippet in an isolated container.  "
            "Network access is blocked.  CPU and memory are strictly limited.  "
            "Restricted to privileged and admin tiers."
        ),
        allowed_scopes=["execute:code"],
        allowed_agent_tiers=["privileged", "admin"],
        parameters_schema={
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "bash"],
                    "description": "Runtime language for the snippet",
                },
                "code": {
                    "type": "string",
                    "description": "Source code to execute",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 10,
                },
            },
            "required": ["language", "code"],
        },
        is_active=True,
    ),
    ToolDefinition(
        tool_id="tool-db-query-v1",
        name="db-query",
        description=(
            "Run a parameterised read-only SQL query against the agent's assigned "
            "database workspace.  Only SELECT statements are permitted; DDL/DML "
            "is rejected at parse time."
        ),
        allowed_scopes=["read:database"],
        allowed_agent_tiers=["privileged", "admin"],
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Parameterised SELECT statement",
                },
                "params": {
                    "type": "array",
                    "items": {},
                    "description": "Positional parameters for the query",
                    "default": [],
                },
                "database": {
                    "type": "string",
                    "description": "Target database name within the workspace",
                },
            },
            "required": ["query", "database"],
        },
        is_active=True,
    ),
    ToolDefinition(
        tool_id="tool-api-call-v1",
        name="api-call",
        description=(
            "Make an outbound HTTP request to a pre-approved external API endpoint.  "
            "The target URL must appear in the agent's allowlisted API registry.  "
            "Admin tier only."
        ),
        allowed_scopes=["call:external-api"],
        allowed_agent_tiers=["admin"],
        parameters_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Target URL (must be allowlisted)",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "GET",
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Request headers",
                },
                "body": {
                    "description": "Request body (JSON-serialisable)",
                },
            },
            "required": ["url"],
        },
        is_active=True,
    ),
]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@router.get(
    "/tools",
    response_model=ToolCatalogResponse,
    summary="List available MCP tools",
)
async def list_tools(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    active_only: bool = Query(default=True, description="Return only active tools"),
) -> ToolCatalogResponse:
    """Return a paginated list of registered MCP tools."""
    catalog = [t for t in _TOOL_CATALOG if t.is_active] if active_only else list(_TOOL_CATALOG)
    total = len(catalog)
    start = (page - 1) * page_size
    end = start + page_size
    page_tools = catalog[start:end]

    return ToolCatalogResponse(
        tools=page_tools,
        total=total,
        page=page,
        page_size=page_size,
    )

"""ToolCatalogTool — lists and inspects approved tools from the control plane catalog.

Available to T0+ agents. Reads tool definitions from the loaded scopes.yaml
and profiles.yaml to return a structured catalog of approved tools.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
import structlog

from agent_runtime.tools.base import MCPTool

logger = structlog.get_logger(__name__)

_SCOPES_YAML = Path(__file__).parent / "scopes.yaml"
_PROFILES_YAML = Path(__file__).parent.parent / "registry" / "profiles.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class ToolCatalogTool(MCPTool):
    """Return a filtered view of approved MCP tools from the catalog.

    Reads tool definitions from ``scopes.yaml`` and ``profiles.yaml`` at
    instantiation time and exposes them via :meth:`execute`. Results can be
    filtered by tier or scope level.

    Available to T0 and above (read-only).
    """

    tool_id = "tool_catalog"
    display_name = "Tool Catalog"
    description = (
        "Lists and inspects approved MCP tools registered in the control plane "
        "catalog. Supports filtering by tier and scope. Read-only, T0+."
    )
    min_tier = "T0"
    read_only = True
    input_schema = {
        "type": "object",
        "properties": {
            "tier_filter": {"type": "string", "enum": ["T0", "T1"]},
            "scope_filter": {
                "type": "string",
                "enum": ["read-only", "read-write", "admin"],
            },
            "name_contains": {"type": "string"},
        },
    }

    def __init__(self, caller_tier: str, caller_agent_id: str) -> None:
        super().__init__(caller_tier, caller_agent_id)
        self._scopes: dict[str, Any] = _load_yaml(_SCOPES_YAML)
        self._profiles: dict[str, Any] = _load_yaml(_PROFILES_YAML)

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return catalog entries for approved tools, optionally filtered.

        Args:
            params: Optional ``tier_filter`` (``"T0"``|``"T1"``),
                ``scope_filter``, ``name_contains`` (substring match on tool_id).

        Returns:
            ``{"success": True, "data": {"tools": [...], "total": N}}``.
        """
        tier_filter: str | None = params.get("tier_filter")
        scope_filter: str | None = params.get("scope_filter")
        name_contains: str | None = params.get("name_contains", "").lower() or None

        log = logger.bind(
            tool=self.tool_id,
            caller=self._caller_agent_id,
            tier_filter=tier_filter,
            scope_filter=scope_filter,
        )
        log.info("tool_catalog.execute")

        raw_tools: dict[str, Any] = self._scopes.get("tools", {})
        profile_tools: dict[str, Any] = self._profiles.get("tools", {})

        results: list[dict[str, Any]] = []
        for tool_id, tool_def in raw_tools.items():
            min_tier: str = tool_def.get("tier_minimum", "T0")
            allowed_scopes: list[str] = tool_def.get("allowed_scopes", [])

            # Apply filters
            if tier_filter and min_tier != tier_filter:
                continue
            if scope_filter and scope_filter not in allowed_scopes:
                continue
            if name_contains and name_contains not in tool_id.lower():
                continue

            # Merge with profile metadata
            profile_entry = profile_tools.get(tool_id, {})
            entry: dict[str, Any] = {
                "tool_id": tool_id,
                "display_name": profile_entry.get("display_name", tool_id),
                "description": tool_def.get("description", profile_entry.get("description", "")),
                "tier_minimum": min_tier,
                "allowed_scopes": allowed_scopes,
                "default_scope": tool_def.get("default_scope", allowed_scopes[0] if allowed_scopes else "read-only"),
                "read_only": tool_def.get("read_only", True),
                "parameters": tool_def.get("parameters", {}),
            }
            results.append(entry)

        log.info("tool_catalog.complete", tools_returned=len(results))
        return self._ok(data={"tools": results, "total": len(results)})

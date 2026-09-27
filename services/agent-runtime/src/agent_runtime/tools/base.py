"""Abstract base class for all MCP tool implementations."""

from __future__ import annotations

import abc
from typing import Any, ClassVar


class MCPTool(abc.ABC):
    """Abstract base for every tool callable from a LangGraph agent.

    Concrete tools must implement :meth:`execute` and declare the
    class-level metadata attributes so the tool catalog can introspect
    them without instantiation.

    Tier enforcement is performed by :class:`agent_runtime.tools.ToolCatalogTool`
    and the scope-enforcer agent before ``execute`` is ever called; tools
    themselves do a secondary check to guard against bypass.
    """

    # ── Class-level metadata (must be overridden) ─────────────────────────────
    tool_id: ClassVar[str]
    """Unique snake_case identifier matching the registry key, e.g. ``rag_search``."""

    display_name: ClassVar[str]
    """Human-readable name shown in audit logs and the UI."""

    description: ClassVar[str]
    """One-paragraph description of what the tool does and what it returns."""

    min_tier: ClassVar[str]
    """Minimum agent tier required: ``"T0"`` or ``"T1"``."""

    read_only: ClassVar[bool] = True
    """True if the tool never mutates external state. Enforced by scope checks."""

    input_schema: ClassVar[dict[str, Any]] = {}
    """JSON Schema describing the expected ``params`` dict for :meth:`execute`."""

    # ── Tier ordering ─────────────────────────────────────────────────────────
    _TIER_ORDER: ClassVar[dict[str, int]] = {"T0": 0, "T1": 1}

    # ── Constructor ───────────────────────────────────────────────────────────
    def __init__(self, caller_tier: str, caller_agent_id: str) -> None:
        """Instantiate a tool with the calling agent's identity context.

        Args:
            caller_tier: Tier of the calling agent (``"T0"`` or ``"T1"``).
            caller_agent_id: Registry ID of the calling agent for audit logging.

        Raises:
            PermissionError: If the caller's tier is below ``min_tier``.
        """
        if self._TIER_ORDER.get(caller_tier, -1) < self._TIER_ORDER.get(self.min_tier, 99):
            raise PermissionError(
                f"Agent '{caller_agent_id}' (tier={caller_tier}) is not authorised "
                f"to call tool '{self.tool_id}' which requires tier={self.min_tier}."
            )
        self._caller_tier = caller_tier
        self._caller_agent_id = caller_agent_id

    # ── Abstract interface ────────────────────────────────────────────────────
    @abc.abstractmethod
    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with the given parameters.

        Args:
            params: Tool-specific input parameters. Must conform to
                :attr:`input_schema` — validated by the caller before dispatch.

        Returns:
            A dictionary with at minimum:
            ``{"success": bool, "data": Any, "error": str | None}``.

        Raises:
            ValueError: On invalid parameter values that pass schema validation.
            RuntimeError: On unrecoverable backend errors.
        """

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _ok(self, data: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build a successful result envelope."""
        result: dict[str, Any] = {"success": True, "data": data, "error": None}
        if metadata:
            result["metadata"] = metadata
        return result

    def _err(self, message: str, code: str = "TOOL_ERROR") -> dict[str, Any]:
        """Build an error result envelope."""
        return {
            "success": False,
            "data": None,
            "error": message,
            "error_code": code,
        }

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} tool_id={self.tool_id!r} "
            f"caller={self._caller_agent_id!r} tier={self._caller_tier!r}>"
        )

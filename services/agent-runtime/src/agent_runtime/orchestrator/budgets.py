"""BudgetEnforcer — tracks token usage per agent and enforces per-call limits."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TokenUsageRecord:
    """A single token usage event for a tool/LLM call."""

    agent_id: str
    session_id: str
    call_type: str  # "llm" | "tool"
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        """Rough USD cost estimate. Adjust rates per model."""
        rates: dict[str, tuple[float, float]] = {
            "anthropic.claude-3-5-sonnet-20241022-v2:0": (3.0e-6, 15.0e-6),
            "anthropic.claude-3-haiku-20240307-v1:0": (0.25e-6, 1.25e-6),
        }
        if self.model and self.model in rates:
            input_rate, output_rate = rates[self.model]
            return self.prompt_tokens * input_rate + self.completion_tokens * output_rate
        # Default estimate
        return (self.prompt_tokens + self.completion_tokens) * 5e-6


@dataclass
class AgentBudgetState:
    """Running budget state for a single agent session."""

    agent_id: str
    session_id: str
    max_tokens_per_call: int
    max_total_tokens: int
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    call_count: int = 0
    records: list[TokenUsageRecord] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_total_tokens - self.total_tokens)

    @property
    def is_exhausted(self) -> bool:
        return self.total_tokens >= self.max_total_tokens


class BudgetEnforcer:
    """Tracks and enforces token budgets for agents across a session.

    Provides both per-call limits (from the agent's max_tokens profile field)
    and an optional session-level ceiling. Thread-safe via asyncio.Lock.

    Args:
        default_max_tokens_per_call: Fallback per-call token limit if not
            set on the agent profile.
        default_max_total_tokens: Session-level token ceiling. Default 100k.
    """

    def __init__(
        self,
        default_max_tokens_per_call: int = 8192,
        default_max_total_tokens: int = 100_000,
    ) -> None:
        self._default_per_call = default_max_tokens_per_call
        self._default_total = default_max_total_tokens
        self._states: dict[str, AgentBudgetState] = {}
        self._lock = asyncio.Lock()

    async def register_session(
        self,
        agent_id: str,
        session_id: str,
        max_tokens_per_call: int | None = None,
        max_total_tokens: int | None = None,
    ) -> None:
        """Register a new agent session with its budget parameters.

        Args:
            agent_id: Registry ID of the agent.
            session_id: Unique session identifier.
            max_tokens_per_call: Per-call output token limit (from agent profile).
            max_total_tokens: Session-level ceiling across all calls.
        """
        async with self._lock:
            key = f"{agent_id}:{session_id}"
            self._states[key] = AgentBudgetState(
                agent_id=agent_id,
                session_id=session_id,
                max_tokens_per_call=max_tokens_per_call or self._default_per_call,
                max_total_tokens=max_total_tokens or self._default_total,
            )
            logger.info(
                "budget.session_registered",
                agent=agent_id,
                session=session_id,
                per_call=max_tokens_per_call or self._default_per_call,
                total=max_total_tokens or self._default_total,
            )

    async def check_pre_call(
        self,
        agent_id: str,
        session_id: str,
        requested_max_tokens: int,
    ) -> tuple[bool, str]:
        """Check whether an LLM call is within budget before making it.

        Args:
            agent_id: Registry ID of the agent.
            session_id: Session identifier.
            requested_max_tokens: The ``max_tokens`` the caller wants to pass.

        Returns:
            ``(allowed, reason)`` — if ``allowed`` is False the call should be
            blocked and ``reason`` describes the constraint violated.
        """
        async with self._lock:
            key = f"{agent_id}:{session_id}"
            state = self._states.get(key)
            if state is None:
                # Auto-register with defaults if not pre-registered
                self._states[key] = AgentBudgetState(
                    agent_id=agent_id,
                    session_id=session_id,
                    max_tokens_per_call=self._default_per_call,
                    max_total_tokens=self._default_total,
                )
                state = self._states[key]

            if state.is_exhausted:
                return False, (
                    f"Session token budget exhausted: "
                    f"{state.total_tokens}/{state.max_total_tokens} tokens used."
                )

            if requested_max_tokens > state.max_tokens_per_call:
                return False, (
                    f"Requested max_tokens={requested_max_tokens} exceeds per-call "
                    f"limit of {state.max_tokens_per_call} for agent '{agent_id}'."
                )

            remaining = state.remaining_tokens
            if requested_max_tokens > remaining:
                return False, (
                    f"Requested max_tokens={requested_max_tokens} exceeds remaining "
                    f"session budget of {remaining} tokens."
                )

        return True, "ok"

    async def record_usage(
        self,
        agent_id: str,
        session_id: str,
        call_type: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        metadata: dict[str, Any] | None = None,
    ) -> TokenUsageRecord:
        """Record token usage after an LLM or tool call completes.

        Args:
            agent_id: Registry ID of the agent.
            session_id: Session identifier.
            call_type: ``"llm"`` or ``"tool"``.
            model: Model ID string (may be None for tool calls).
            prompt_tokens: Input token count from the response usage object.
            completion_tokens: Output token count.
            metadata: Optional extra data stored with the record.

        Returns:
            The created :class:`TokenUsageRecord`.
        """
        record = TokenUsageRecord(
            agent_id=agent_id,
            session_id=session_id,
            call_type=call_type,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            metadata=metadata or {},
        )

        async with self._lock:
            key = f"{agent_id}:{session_id}"
            state = self._states.get(key)
            if state:
                state.total_prompt_tokens += prompt_tokens
                state.total_completion_tokens += completion_tokens
                state.call_count += 1
                state.records.append(record)

        logger.info(
            "budget.usage_recorded",
            agent=agent_id,
            session=session_id,
            call_type=call_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=f"{record.cost_usd:.6f}",
        )
        return record

    async def get_session_summary(
        self, agent_id: str, session_id: str
    ) -> dict[str, Any] | None:
        """Return a summary of token usage for an agent session.

        Returns:
            Dict with ``total_tokens``, ``prompt_tokens``, ``completion_tokens``,
            ``call_count``, ``remaining``, ``exhausted``, and ``estimated_cost_usd``.
            Returns ``None`` if the session is not registered.
        """
        async with self._lock:
            key = f"{agent_id}:{session_id}"
            state = self._states.get(key)
            if not state:
                return None

            total_cost = sum(r.cost_usd for r in state.records)
            return {
                "agent_id": state.agent_id,
                "session_id": state.session_id,
                "total_tokens": state.total_tokens,
                "prompt_tokens": state.total_prompt_tokens,
                "completion_tokens": state.total_completion_tokens,
                "call_count": state.call_count,
                "max_total_tokens": state.max_total_tokens,
                "remaining_tokens": state.remaining_tokens,
                "exhausted": state.is_exhausted,
                "estimated_cost_usd": round(total_cost, 6),
            }

"""Budget enforcer: tracks and limits token spending per agent."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class AgentBudget:
    agent_id: str
    max_tokens: int
    used_tokens: int = 0
    window_start: float = field(default_factory=time.time)
    window_seconds: int = 3600  # 1 hour rolling window


class BudgetEnforcer:
    """In-memory budget tracker for LLM token usage per agent."""

    def __init__(self, default_max_tokens: int = 100_000, window_seconds: int = 3600) -> None:
        self._default_max = default_max_tokens
        self._window_seconds = window_seconds
        self._budgets: dict[str, AgentBudget] = {}
        self._lock = threading.Lock()

    def check_budget(self, agent_id: str, estimated_tokens: int) -> bool:
        """Check if an agent has budget remaining.

        Returns True if the call is within budget, False otherwise.
        """
        with self._lock:
            budget = self._get_or_create(agent_id)
            self._maybe_reset_window(budget)
            return (budget.used_tokens + estimated_tokens) <= budget.max_tokens

    def record_usage(self, agent_id: str, tokens_used: int) -> None:
        """Record actual token usage after a call completes."""
        with self._lock:
            budget = self._get_or_create(agent_id)
            self._maybe_reset_window(budget)
            budget.used_tokens += tokens_used

    def get_remaining(self, agent_id: str) -> int:
        """Return the number of tokens remaining in the current window."""
        with self._lock:
            budget = self._get_or_create(agent_id)
            self._maybe_reset_window(budget)
            return max(0, budget.max_tokens - budget.used_tokens)

    def _get_or_create(self, agent_id: str) -> AgentBudget:
        if agent_id not in self._budgets:
            self._budgets[agent_id] = AgentBudget(
                agent_id=agent_id,
                max_tokens=self._default_max,
                window_seconds=self._window_seconds,
            )
        return self._budgets[agent_id]

    def _maybe_reset_window(self, budget: AgentBudget) -> None:
        now = time.time()
        if (now - budget.window_start) >= budget.window_seconds:
            budget.used_tokens = 0
            budget.window_start = now

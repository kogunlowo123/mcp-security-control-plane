"""TurnBuffer — manages conversation history with a configurable max_turns limit."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Turn:
    """A single conversation turn (request + response pair)."""

    turn_id: int
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "token_count": self.token_count,
        }


class TurnBuffer:
    """Fixed-capacity conversation history buffer.

    Stores the most recent ``max_turns`` conversation turns. When the buffer
    is full, the oldest turn is evicted. Provides serialisation helpers for
    feeding the conversation history into LLM prompts.

    Args:
        max_turns: Maximum number of turns to retain. Default 20.
        agent_id: Agent identifier for structured logging.
        session_id: Session identifier for structured logging.
    """

    def __init__(
        self,
        max_turns: int = 20,
        agent_id: str = "unknown",
        session_id: str = "unknown",
    ) -> None:
        if max_turns < 1:
            raise ValueError(f"max_turns must be >= 1, got {max_turns}")
        self._max_turns = max_turns
        self._agent_id = agent_id
        self._session_id = session_id
        self._buffer: deque[Turn] = deque(maxlen=max_turns)
        self._turn_counter = 0

    def add(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        token_count: int | None = None,
    ) -> Turn:
        """Append a new turn to the buffer.

        Args:
            role: ``"user"``, ``"assistant"``, or ``"system"``.
            content: The turn text.
            metadata: Optional key-value metadata (model, tool call info, etc.).
            token_count: Estimated token count for budget tracking.

        Returns:
            The newly created :class:`Turn`.
        """
        if role not in ("user", "assistant", "system"):
            raise ValueError(f"Invalid role '{role}'. Must be user/assistant/system.")

        self._turn_counter += 1
        turn = Turn(
            turn_id=self._turn_counter,
            role=role,
            content=content,
            metadata=metadata or {},
            token_count=token_count,
        )
        evicted = len(self._buffer) >= self._max_turns
        self._buffer.append(turn)

        logger.debug(
            "turn_buffer.added",
            agent=self._agent_id,
            session=self._session_id,
            turn_id=self._turn_counter,
            role=role,
            evicted=evicted,
            buffer_size=len(self._buffer),
        )
        return turn

    def get_all(self) -> list[Turn]:
        """Return all turns currently in the buffer, oldest first."""
        return list(self._buffer)

    def get_recent(self, n: int) -> list[Turn]:
        """Return the most recent ``n`` turns."""
        return list(self._buffer)[-n:]

    def to_messages(self) -> list[dict[str, str]]:
        """Serialise the buffer to a list of ``{"role": ..., "content": ...}`` dicts.

        Suitable for passing directly to LiteLLM / LangChain as the ``messages``
        argument. System turns are included first if present.
        """
        return [{"role": t.role, "content": t.content} for t in self._buffer]

    def to_messages_excluding_system(self) -> list[dict[str, str]]:
        """Same as :meth:`to_messages` but excludes system turns."""
        return [
            {"role": t.role, "content": t.content}
            for t in self._buffer
            if t.role != "system"
        ]

    def clear(self) -> None:
        """Clear all turns from the buffer."""
        self._buffer.clear()
        logger.info(
            "turn_buffer.cleared",
            agent=self._agent_id,
            session=self._session_id,
        )

    @property
    def size(self) -> int:
        """Current number of turns in the buffer."""
        return len(self._buffer)

    @property
    def max_turns(self) -> int:
        """Maximum capacity of the buffer."""
        return self._max_turns

    @property
    def total_tokens(self) -> int:
        """Sum of token_count for all turns that have it set."""
        return sum(t.token_count for t in self._buffer if t.token_count is not None)

    def __repr__(self) -> str:
        return (
            f"<TurnBuffer agent={self._agent_id!r} session={self._session_id!r} "
            f"size={self.size}/{self._max_turns}>"
        )

"""EpisodicMemory — stores and retrieves significant past agent interactions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Episode:
    """A stored memory of a significant past interaction."""

    episode_id: str
    agent_id: str
    session_id: str
    summary: str
    outcome: str  # "success" | "failure" | "partial" | "escalated"
    task: str
    key_findings: list[str] = field(default_factory=list)
    violations_found: int = 0
    tools_used: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "summary": self.summary,
            "outcome": self.outcome,
            "task": self.task,
            "key_findings": self.key_findings,
            "violations_found": self.violations_found,
            "tools_used": self.tools_used,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Episode":
        data = dict(data)
        created_at_raw = data.pop("created_at", None)
        created_at = (
            datetime.fromisoformat(created_at_raw)
            if created_at_raw
            else datetime.now(timezone.utc)
        )
        return cls(**data, created_at=created_at)


def _make_episode_id(agent_id: str, session_id: str, task: str) -> str:
    """Deterministic episode ID from agent, session and task."""
    payload = f"{agent_id}:{session_id}:{task}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class EpisodicMemory:
    """In-process episodic memory store for significant agent interactions.

    Episodes are stored in memory with optional persistence hooks. Provides
    simple relevance-based retrieval to inject past context into new tasks.

    In production, this store should be backed by a vector database or
    PostgreSQL with pgvector for semantic search. This implementation provides
    keyword-based retrieval as the default.

    Args:
        agent_id: Registry ID of the owning agent.
        max_episodes: Maximum episodes to retain in memory. Default 1000.
    """

    def __init__(self, agent_id: str, max_episodes: int = 1000) -> None:
        self._agent_id = agent_id
        self._max_episodes = max_episodes
        self._store: dict[str, Episode] = {}
        self._lock = asyncio.Lock()

    async def store(
        self,
        session_id: str,
        summary: str,
        outcome: str,
        task: str,
        key_findings: list[str] | None = None,
        violations_found: int = 0,
        tools_used: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Episode:
        """Store a new episode.

        Args:
            session_id: The session this episode came from.
            summary: Free-text summary of what happened.
            outcome: One of ``"success"``, ``"failure"``, ``"partial"``, ``"escalated"``.
            task: The original task description.
            key_findings: Notable findings from the interaction.
            violations_found: Count of policy violations detected.
            tools_used: Tool IDs that were called.
            tags: Searchable tags for this episode.
            metadata: Arbitrary extra data.

        Returns:
            The stored :class:`Episode`.
        """
        episode_id = _make_episode_id(self._agent_id, session_id, task)
        episode = Episode(
            episode_id=episode_id,
            agent_id=self._agent_id,
            session_id=session_id,
            summary=summary,
            outcome=outcome,
            task=task,
            key_findings=key_findings or [],
            violations_found=violations_found,
            tools_used=tools_used or [],
            tags=tags or [],
            metadata=metadata or {},
        )

        async with self._lock:
            self._store[episode_id] = episode
            # Evict oldest if over capacity
            if len(self._store) > self._max_episodes:
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]
                logger.debug("episodic_memory.evicted", agent=self._agent_id)

        logger.info(
            "episodic_memory.stored",
            agent=self._agent_id,
            episode_id=episode_id,
            outcome=outcome,
            violations=violations_found,
        )
        return episode

    async def retrieve(
        self,
        query: str,
        limit: int = 5,
        outcome_filter: str | None = None,
    ) -> list[Episode]:
        """Retrieve episodes relevant to ``query`` by keyword matching.

        Args:
            query: Task or topic text to match against stored episode fields.
            limit: Maximum episodes to return.
            outcome_filter: If set, only return episodes with this outcome.

        Returns:
            List of :class:`Episode` sorted by relevance (keyword overlap).
        """
        query_tokens = set(query.lower().split())

        async with self._lock:
            candidates = list(self._store.values())

        if outcome_filter:
            candidates = [e for e in candidates if e.outcome == outcome_filter]

        # Score by token overlap with task + summary + findings
        def score(episode: Episode) -> int:
            text = (
                episode.task + " " + episode.summary + " " + " ".join(episode.key_findings)
            ).lower()
            tokens = set(text.split())
            return len(query_tokens & tokens)

        scored = sorted(candidates, key=score, reverse=True)
        top = [e for e in scored if score(e) > 0][:limit]

        logger.info(
            "episodic_memory.retrieved",
            agent=self._agent_id,
            query_tokens=len(query_tokens),
            total_candidates=len(candidates),
            returned=len(top),
        )
        return top

    async def get_by_id(self, episode_id: str) -> Episode | None:
        """Return a specific episode by its ID."""
        async with self._lock:
            return self._store.get(episode_id)

    async def list_all(self) -> list[Episode]:
        """Return all stored episodes, newest first."""
        async with self._lock:
            episodes = list(self._store.values())
        return sorted(episodes, key=lambda e: e.created_at, reverse=True)

    async def export_json(self) -> str:
        """Export all episodes to a JSON string (for persistence)."""
        episodes = await self.list_all()
        return json.dumps([e.to_dict() for e in episodes], indent=2)

    async def import_json(self, data: str) -> int:
        """Import episodes from a JSON string (for restore from persistence).

        Returns:
            Number of episodes imported.
        """
        raw: list[dict[str, Any]] = json.loads(data)
        imported = 0
        async with self._lock:
            for item in raw:
                try:
                    episode = Episode.from_dict(item)
                    self._store[episode.episode_id] = episode
                    imported += 1
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("episodic_memory.import_error", error=str(exc))
        logger.info("episodic_memory.imported", count=imported, agent=self._agent_id)
        return imported

    @property
    def size(self) -> int:
        """Current number of stored episodes."""
        return len(self._store)

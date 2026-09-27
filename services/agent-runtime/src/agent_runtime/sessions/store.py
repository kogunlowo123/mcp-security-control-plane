"""SessionStore — PostgreSQL-backed agent session persistence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

_DB_DSN = os.environ.get(
    "SESSION_DB_DSN",
    "postgresql://agentruntime:agentruntime@localhost:5432/mcpsecurity",
)

# DDL for sessions table — executed once at startup via ensure_schema()
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id      TEXT        PRIMARY KEY,
    agent_id        TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'active',
    task            TEXT,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    state_snapshot  JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_id  ON agent_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status    ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_created_at ON agent_sessions(created_at DESC);
"""


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class AgentSession:
    """Represents a stored agent session record."""

    session_id: str
    agent_id: str
    status: SessionStatus
    task: str | None
    metadata: dict[str, Any]
    state_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "task": self.task,
            "metadata": self.metadata,
            "state_snapshot": self.state_snapshot,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


class SessionStore:
    """Persist and query agent sessions in PostgreSQL.

    Provides CRUD operations for session records and state snapshots.
    Uses a connection-per-operation pattern via asyncpg.connect for
    simplicity; replace with a pool for high-throughput production use.

    Args:
        dsn: PostgreSQL connection string. Defaults to ``SESSION_DB_DSN`` env var.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _DB_DSN

    async def ensure_schema(self) -> None:
        """Create the sessions table if it does not exist.

        Should be called once at application startup.
        """
        conn: asyncpg.Connection = await asyncpg.connect(dsn=self._dsn)
        try:
            await conn.execute(_CREATE_TABLE_SQL)
            logger.info("session_store.schema_ensured")
        finally:
            await conn.close()

    async def create(
        self,
        session_id: str,
        agent_id: str,
        task: str | None = None,
        metadata: dict[str, Any] | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> AgentSession:
        """Create a new session record.

        Args:
            session_id: Unique session identifier (typically a UUID).
            agent_id: Registry ID of the agent running this session.
            task: Task description text.
            metadata: Arbitrary metadata to store alongside the session.
            initial_state: Initial LangGraph state snapshot to persist.

        Returns:
            The created :class:`AgentSession`.

        Raises:
            asyncpg.UniqueViolationError: If a session with this ID already exists.
        """
        now = datetime.now(timezone.utc)
        conn: asyncpg.Connection = await asyncpg.connect(dsn=self._dsn)
        try:
            await conn.execute(
                """
                INSERT INTO agent_sessions
                    (session_id, agent_id, status, task, metadata, state_snapshot,
                     created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                """,
                session_id,
                agent_id,
                SessionStatus.ACTIVE.value,
                task,
                json.dumps(metadata or {}),
                json.dumps(initial_state or {}),
                now,
            )
        finally:
            await conn.close()

        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            status=SessionStatus.ACTIVE,
            task=task,
            metadata=metadata or {},
            state_snapshot=initial_state or {},
            created_at=now,
            updated_at=now,
        )
        logger.info(
            "session_store.created",
            session_id=session_id,
            agent_id=agent_id,
        )
        return session

    async def get(self, session_id: str) -> AgentSession | None:
        """Retrieve a session by ID. Returns None if not found."""
        conn: asyncpg.Connection = await asyncpg.connect(dsn=self._dsn)
        try:
            row = await conn.fetchrow(
                "SELECT * FROM agent_sessions WHERE session_id = $1",
                session_id,
            )
        finally:
            await conn.close()

        if row is None:
            return None
        return self._row_to_session(row)

    async def update_state(
        self,
        session_id: str,
        state_snapshot: dict[str, Any],
        status: SessionStatus | None = None,
    ) -> bool:
        """Persist an updated state snapshot for the session.

        Args:
            session_id: Session to update.
            state_snapshot: The new LangGraph state to store.
            status: Optionally update the session status at the same time.

        Returns:
            True if the session was found and updated, False otherwise.
        """
        now = datetime.now(timezone.utc)
        status_val = status.value if status else None

        conn: asyncpg.Connection = await asyncpg.connect(dsn=self._dsn)
        try:
            if status_val:
                result = await conn.execute(
                    """
                    UPDATE agent_sessions
                    SET state_snapshot = $2, status = $3, updated_at = $4
                    WHERE session_id = $1
                    """,
                    session_id,
                    json.dumps(state_snapshot),
                    status_val,
                    now,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE agent_sessions
                    SET state_snapshot = $2, updated_at = $3
                    WHERE session_id = $1
                    """,
                    session_id,
                    json.dumps(state_snapshot),
                    now,
                )
        finally:
            await conn.close()

        updated = result == "UPDATE 1"
        if updated:
            logger.debug("session_store.state_updated", session_id=session_id)
        return updated

    async def complete(
        self,
        session_id: str,
        final_state: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        """Mark a session as completed or failed.

        Args:
            session_id: Session to finalise.
            final_state: Optional final state snapshot.
            error: If set, marks the session as FAILED with this error message.

        Returns:
            True if updated, False if not found.
        """
        now = datetime.now(timezone.utc)
        status = SessionStatus.FAILED if error else SessionStatus.COMPLETED

        conn: asyncpg.Connection = await asyncpg.connect(dsn=self._dsn)
        try:
            result = await conn.execute(
                """
                UPDATE agent_sessions
                SET status = $2, completed_at = $3, updated_at = $3,
                    error = $4,
                    state_snapshot = CASE WHEN $5::text IS NOT NULL
                                    THEN $5::jsonb
                                    ELSE state_snapshot END
                WHERE session_id = $1
                """,
                session_id,
                status.value,
                now,
                error,
                json.dumps(final_state) if final_state is not None else None,
            )
        finally:
            await conn.close()

        updated = result == "UPDATE 1"
        if updated:
            logger.info(
                "session_store.completed",
                session_id=session_id,
                status=status.value,
                error=error,
            )
        return updated

    async def list_by_agent(
        self,
        agent_id: str,
        status: SessionStatus | None = None,
        limit: int = 50,
    ) -> list[AgentSession]:
        """List sessions for a given agent, newest first.

        Args:
            agent_id: Filter by this agent.
            status: Optional status filter.
            limit: Maximum records to return.
        """
        conn: asyncpg.Connection = await asyncpg.connect(dsn=self._dsn)
        try:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_sessions
                    WHERE agent_id = $1 AND status = $2
                    ORDER BY created_at DESC LIMIT $3
                    """,
                    agent_id,
                    status.value,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_sessions
                    WHERE agent_id = $1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    agent_id,
                    limit,
                )
        finally:
            await conn.close()

        return [self._row_to_session(r) for r in rows]

    @staticmethod
    def _row_to_session(row: asyncpg.Record) -> AgentSession:
        """Convert an asyncpg record to an :class:`AgentSession`."""
        meta = row["metadata"]
        state = row["state_snapshot"]
        return AgentSession(
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            status=SessionStatus(row["status"]),
            task=row["task"],
            metadata=meta if isinstance(meta, dict) else json.loads(meta or "{}"),
            state_snapshot=state if isinstance(state, dict) else json.loads(state or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )

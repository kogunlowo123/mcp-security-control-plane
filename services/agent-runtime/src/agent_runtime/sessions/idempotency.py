"""IdempotencyChecker — prevents duplicate session processing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# In-process store as fallback (single-instance only)
# In production, replace with Redis or PostgreSQL for distributed deployments.
_DEFAULT_IDEMPOTENCY_TTL = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400"))  # 24h


class IdempotencyStatus(str, Enum):
    """Status of an idempotency key."""
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IdempotencyRecord:
    """A stored idempotency record."""

    key: str
    status: IdempotencyStatus
    session_id: str
    agent_id: str
    result_summary: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None
    expires_at: float = field(
        default_factory=lambda: time.monotonic() + _DEFAULT_IDEMPOTENCY_TTL
    )

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def is_terminal(self) -> bool:
        return self.status in (IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED)


def make_idempotency_key(agent_id: str, task: str, params: dict[str, Any] | None = None) -> str:
    """Generate a stable idempotency key from agent identity, task and parameters.

    The key is a SHA-256 digest of the canonical JSON representation of the
    inputs, truncated to 32 hex characters.

    Args:
        agent_id: Registry ID of the agent.
        task: Task description string.
        params: Optional parameter dict included in the key.

    Returns:
        A 32-character hex string suitable for use as an idempotency key.
    """
    payload = {
        "agent_id": agent_id,
        "task": task,
        "params": params or {},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


class IdempotencyChecker:
    """Prevents duplicate processing of the same session request.

    Uses a keyed record store to detect when an identical request has already
    been processed or is currently in-flight. Callers should:

    1. Call :meth:`check_and_reserve` before starting processing.
       - If it returns ``(False, existing_record)``, the request is a duplicate
         and the caller should return the stored result.
       - If it returns ``(True, None)``, proceed and own the key.

    2. Call :meth:`complete` on success or :meth:`fail` on failure to release
       the key to its terminal state.

    This implementation uses an in-process dict protected by asyncio.Lock.
    For multi-instance deployments, replace the backing store with Redis using
    atomic SETNX/GETSET semantics.

    Args:
        ttl_seconds: How long completed records are retained. Default 24h.
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_IDEMPOTENCY_TTL) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def check_and_reserve(
        self,
        key: str,
        session_id: str,
        agent_id: str,
    ) -> tuple[bool, IdempotencyRecord | None]:
        """Atomically check for an existing record and reserve the key if new.

        Args:
            key: The idempotency key (from :func:`make_idempotency_key`).
            session_id: The new session ID that wants to own this key.
            agent_id: Agent ID for logging context.

        Returns:
            ``(True, None)`` — key is new; caller owns it and must call
            :meth:`complete` or :meth:`fail` when done.

            ``(False, record)`` — key already exists; ``record.status`` indicates
            whether it is still PROCESSING, COMPLETED, or FAILED.
        """
        async with self._lock:
            existing = self._store.get(key)

            if existing is not None:
                if existing.is_expired:
                    # Expired record — treat as if it never existed
                    del self._store[key]
                    logger.info(
                        "idempotency.expired_key_cleared",
                        key=key,
                        agent=agent_id,
                    )
                else:
                    logger.info(
                        "idempotency.duplicate_detected",
                        key=key,
                        status=existing.status.value,
                        original_session=existing.session_id,
                        agent=agent_id,
                    )
                    return False, existing

            # Reserve the key
            record = IdempotencyRecord(
                key=key,
                status=IdempotencyStatus.PROCESSING,
                session_id=session_id,
                agent_id=agent_id,
                expires_at=time.monotonic() + self._ttl,
            )
            self._store[key] = record
            logger.info(
                "idempotency.key_reserved",
                key=key,
                session_id=session_id,
                agent=agent_id,
            )
            return True, None

    async def complete(
        self,
        key: str,
        result_summary: dict[str, Any] | None = None,
    ) -> bool:
        """Mark the key as successfully completed.

        Args:
            key: The idempotency key.
            result_summary: Lightweight summary of the result stored for
                subsequent duplicate requests.

        Returns:
            True if the key was found and updated, False if not found.
        """
        async with self._lock:
            record = self._store.get(key)
            if record is None:
                return False
            record.status = IdempotencyStatus.COMPLETED
            record.result_summary = result_summary
            record.completed_at = time.monotonic()

        logger.info("idempotency.completed", key=key)
        return True

    async def fail(self, key: str, error: str | None = None) -> bool:
        """Mark the key as failed, allowing future retries.

        Args:
            key: The idempotency key.
            error: Optional error message stored for diagnostics.

        Returns:
            True if the key was found and updated, False if not found.
        """
        async with self._lock:
            record = self._store.get(key)
            if record is None:
                return False
            record.status = IdempotencyStatus.FAILED
            record.result_summary = {"error": error} if error else None
            record.completed_at = time.monotonic()

        logger.info("idempotency.failed", key=key, error=error)
        return True

    async def get(self, key: str) -> IdempotencyRecord | None:
        """Return the record for a key, or None if absent or expired."""
        async with self._lock:
            record = self._store.get(key)
            if record is not None and record.is_expired:
                del self._store[key]
                return None
            return record

    async def cleanup_expired(self) -> int:
        """Remove all expired records. Returns count of removed entries."""
        async with self._lock:
            expired = [k for k, r in self._store.items() if r.is_expired]
            for key in expired:
                del self._store[key]
        if expired:
            logger.info("idempotency.cleanup", removed=len(expired))
        return len(expired)

    @property
    def size(self) -> int:
        """Current number of stored idempotency records."""
        return len(self._store)

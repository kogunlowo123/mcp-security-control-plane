"""TTLCache — time-limited memory storage for agent runtime state."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import structlog

logger = structlog.get_logger(__name__)

V = TypeVar("V")


@dataclass
class CacheEntry(Generic[V]):
    """A single cache entry with an expiry timestamp."""

    key: str
    value: V
    expires_at: float  # monotonic time
    created_at: float = field(default_factory=time.monotonic)
    access_count: int = 0
    last_accessed_at: float = field(default_factory=time.monotonic)

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        """Seconds until expiry. Returns 0.0 if already expired."""
        return max(0.0, self.expires_at - time.monotonic())


class TTLCache(Generic[V]):
    """Thread-safe in-memory cache with per-entry TTL (Time-To-Live).

    Entries are lazily evicted on access and periodically during background
    cleanup. Suitable for caching short-lived agent runtime state such as
    retrieved documents, resolved scope grants, or session tokens.

    Args:
        default_ttl_seconds: Default TTL applied when no explicit TTL is given.
            Default: 300 seconds (5 minutes).
        max_size: Maximum number of entries. On overflow, the entry closest to
            expiry is evicted first. Default: 10,000.
        cleanup_interval_seconds: How often the background cleanup task runs.
            Default: 60 seconds.
        name: Optional name for structured logging.
    """

    def __init__(
        self,
        default_ttl_seconds: float = 300.0,
        max_size: int = 10_000,
        cleanup_interval_seconds: float = 60.0,
        name: str = "default",
    ) -> None:
        if default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be > 0")
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval_seconds
        self._name = name
        self._store: dict[str, CacheEntry[V]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start_cleanup(self) -> None:
        """Start the background cleanup task.

        Call this after the event loop is running (e.g. from an async context
        or ``asyncio.run``). Idempotent — safe to call multiple times.
        """
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.debug(
                "ttl_cache.cleanup_started",
                name=self._name,
                interval=self._cleanup_interval,
            )

    def stop_cleanup(self) -> None:
        """Cancel the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            self._cleanup_task = None

    # ── Core operations ───────────────────────────────────────────────────────

    async def set(
        self,
        key: str,
        value: V,
        ttl_seconds: float | None = None,
    ) -> None:
        """Store a value with the given key and TTL.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: TTL in seconds. Defaults to ``default_ttl_seconds``.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = time.monotonic()
        entry: CacheEntry[V] = CacheEntry(
            key=key,
            value=value,
            expires_at=now + ttl,
            created_at=now,
        )

        async with self._lock:
            self._store[key] = entry
            # Enforce max size
            if len(self._store) > self._max_size:
                self._evict_one()

    async def get(self, key: str) -> V | None:
        """Retrieve a value by key, returning None if absent or expired.

        Expired entries are lazily removed on access.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._store[key]
                return None
            entry.access_count += 1
            entry.last_accessed_at = time.monotonic()
            return entry.value

    async def get_or_set(
        self,
        key: str,
        factory: Any,  # Callable[[], Awaitable[V]]
        ttl_seconds: float | None = None,
    ) -> V:
        """Return cached value or call ``factory()`` to populate it.

        Args:
            key: Cache key.
            factory: An async callable with no arguments that produces the value.
            ttl_seconds: TTL for the newly created entry.

        Returns:
            The cached or freshly produced value.
        """
        existing = await self.get(key)
        if existing is not None:
            return existing
        value: V = await factory()
        await self.set(key, value, ttl_seconds=ttl_seconds)
        return value

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        async with self._lock:
            existed = key in self._store
            self._store.pop(key, None)
        return existed

    async def exists(self, key: str) -> bool:
        """Return True if the key exists and has not expired."""
        value = await self.get(key)
        return value is not None

    async def ttl(self, key: str) -> float | None:
        """Return remaining TTL in seconds for a key, or None if absent/expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.is_expired:
                return None
            return entry.ttl_remaining

    async def clear(self) -> int:
        """Delete all entries. Returns the number of entries removed."""
        async with self._lock:
            count = len(self._store)
            self._store.clear()
        logger.info("ttl_cache.cleared", name=self._name, removed=count)
        return count

    # ── Stats ──────────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        async with self._lock:
            total = len(self._store)
            expired = sum(1 for e in self._store.values() if e.is_expired)
            live = total - expired
        return {
            "name": self._name,
            "total_entries": total,
            "live_entries": live,
            "expired_entries": expired,
            "max_size": self._max_size,
            "default_ttl_seconds": self._default_ttl,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _evict_one(self) -> None:
        """Evict the entry closest to expiry (called under lock)."""
        if not self._store:
            return
        victim_key = min(self._store, key=lambda k: self._store[k].expires_at)
        del self._store[victim_key]
        logger.debug("ttl_cache.evicted_by_overflow", name=self._name, key=victim_key)

    async def _cleanup_loop(self) -> None:
        """Background task that periodically removes expired entries."""
        while True:
            await asyncio.sleep(self._cleanup_interval)
            async with self._lock:
                expired_keys = [k for k, e in self._store.items() if e.is_expired]
                for key in expired_keys:
                    del self._store[key]
            if expired_keys:
                logger.debug(
                    "ttl_cache.cleanup_run",
                    name=self._name,
                    evicted=len(expired_keys),
                )

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return (
            f"<TTLCache name={self._name!r} size={len(self._store)} "
            f"max={self._max_size} default_ttl={self._default_ttl}s>"
        )

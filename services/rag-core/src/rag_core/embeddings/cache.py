"""CachedEmbedder — wraps any BaseEmbedder with a two-layer SHA-256 cache."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, List, Optional

from .base import BaseEmbedder

logger = logging.getLogger(__name__)


class CachedEmbedder(BaseEmbedder):
    """Wraps any :class:`BaseEmbedder` with a transparent embedding cache.

    Cache layers (checked in order):

    1. **In-process dict** — zero-latency hits within the same process.
    2. **Redis** — shared across replicas (optional; skipped if *redis_url*
       is empty or the connection fails).

    Cache keys are the SHA-256 hex digest of the UTF-8 encoded text prefixed
    with *namespace*, e.g. ``embed:9a3bc...``.  On a miss the delegate
    embedder is called and the result is stored in both layers.

    Args:
        embedder:   The underlying :class:`BaseEmbedder` to call on a miss.
        redis_url:  Redis connection URL (e.g. ``redis://localhost:6379/0``).
                    Omit or leave empty to use the in-memory cache only.
        ttl:        Redis key TTL in seconds (default 86 400 = 24 hours).
        namespace:  Cache key prefix string (default ``"embed"``).
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        redis_url: Optional[str] = None,
        ttl: int = 86_400,
        namespace: str = "embed",
    ) -> None:
        self.embedder = embedder
        self.ttl = ttl
        self.namespace = namespace
        self._mem: Dict[str, List[float]] = {}
        self._redis = None

        if redis_url:
            try:
                import redis  # type: ignore[import-untyped]

                client = redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis = client
                logger.info("CachedEmbedder connected to Redis at %s", redis_url)
            except Exception as exc:
                logger.warning(
                    "Redis connection failed (%s) — using in-memory cache only.", exc
                )

    # ── Cache key ────────────────────────────────────────────────────────

    def _key(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self.namespace}:{digest}"

    # ── Read / write helpers ─────────────────────────────────────────────

    def _get(self, key: str) -> Optional[List[float]]:
        hit = self._mem.get(key)
        if hit is not None:
            return hit

        if self._redis:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    vec: List[float] = json.loads(raw)
                    self._mem[key] = vec  # Warm the in-process cache
                    return vec
            except Exception as exc:
                logger.warning("Redis GET failed for %s: %s", key, exc)

        return None

    def _set(self, key: str, vector: List[float]) -> None:
        self._mem[key] = vector
        if self._redis:
            try:
                self._redis.setex(key, self.ttl, json.dumps(vector))
            except Exception as exc:
                logger.warning("Redis SET failed for %s: %s", key, exc)

    # ── BaseEmbedder interface ────────────────────────────────────────────

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Return embeddings, serving cache hits without calling the delegate.

        Raises:
            ValueError: If *texts* is empty.
        """
        if not texts:
            raise ValueError("embed() requires a non-empty list of texts.")

        results: List[Optional[List[float]]] = []
        miss_indices: List[int] = []
        miss_texts: List[str] = []

        for i, text in enumerate(texts):
            vec = self._get(self._key(text))
            results.append(vec)
            if vec is None:
                miss_indices.append(i)
                miss_texts.append(text)

        if miss_texts:
            logger.debug(
                "CachedEmbedder: %d cache miss(es) out of %d", len(miss_texts), len(texts)
            )
            fresh = self.embedder.embed(miss_texts)
            for idx, text, vec in zip(miss_indices, miss_texts, fresh):
                self._set(self._key(text), vec)
                results[idx] = vec

        # All slots should be filled now
        return results  # type: ignore[return-value]

    # ── Convenience: pass-through for embed_query if delegate supports it ─

    def embed_query(self, query: str) -> List[float]:
        """Cache-aware single-query embedding."""
        key = self._key(query)
        cached = self._get(key)
        if cached is not None:
            return cached

        # Try delegate's embed_query first (may add a model-specific prefix)
        if hasattr(self.embedder, "embed_query"):
            vec = self.embedder.embed_query(query)  # type: ignore[attr-defined]
        else:
            vec = self.embedder.embed([query])[0]

        self._set(key, vec)
        return vec

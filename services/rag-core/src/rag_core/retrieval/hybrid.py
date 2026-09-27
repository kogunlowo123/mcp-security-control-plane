"""Hybrid retriever combining dense vector search and sparse BM25 via RRF."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rag_core.retrieval.rrf import reciprocal_rank_fusion
from rag_core.retrieval.reranker import CrossEncoderReranker


logger = logging.getLogger(__name__)


class Document:
    """Lightweight document wrapper for retrieval results."""

    def __init__(self, page_content: str, metadata: dict[str, Any]) -> None:
        self.page_content = page_content
        self.metadata = metadata

    def __repr__(self) -> str:
        return f"Document(doc_id={self.metadata.get('doc_id')!r}, score={self.metadata.get('score')})"


class HybridRetriever:
    """Combines pgvector dense retrieval and OpenSearch BM25 via RRF fusion.

    Architecture:
        1. Embed the query with the local BGE embedder.
        2. Fire dense (pgvector) and sparse (OpenSearch) queries in parallel.
        3. Fuse ranked lists with Reciprocal Rank Fusion (k=60).
        4. Apply ACL filter so agents only see authorised documents.
        5. Rerank with a cross-encoder to maximise relevance in the top-K.
    """

    def __init__(
        self,
        pgvector_store: Any | None = None,
        opensearch_store: Any | None = None,
        embedder: Any | None = None,
        reranker: CrossEncoderReranker | None = None,
        rrf_k: int = 60,
    ) -> None:
        self._pgvector = pgvector_store
        self._opensearch = opensearch_store
        self._embedder = embedder
        self._reranker = reranker or CrossEncoderReranker()
        self._rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        acl_filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Retrieve and fuse documents for a query.

        Args:
            query: Natural language query string.
            top_k: Number of documents to return after reranking.
            acl_filter: Optional dict with 'tier' and/or 'roles' keys for ACL filtering.

        Returns:
            Ordered list of Document objects, most relevant first.
        """
        # Embed the query
        query_embedding = await self._embed_query(query)

        # Run dense and sparse retrieval in parallel
        dense_docs, sparse_docs = await asyncio.gather(
            self._dense_retrieve(query_embedding, top_k=top_k * 2),
            self._sparse_retrieve(query, top_k=top_k * 2),
        )

        # Fuse rankings
        fused = reciprocal_rank_fusion(
            [dense_docs, sparse_docs],
            k=self._rrf_k,
        )

        # Extract Document objects from (Document, score) tuples
        candidates = [doc for doc, _score in fused]

        # Apply ACL filter
        if acl_filter:
            candidates = self._apply_acl_filter(candidates, acl_filter)

        if not candidates:
            return []

        # Rerank
        reranked = self._reranker.rerank(query, candidates, top_k=top_k)
        return reranked

    async def _embed_query(self, query: str) -> list[float]:
        """Embed the query, falling back to a zero vector if no embedder configured."""
        if self._embedder is None:
            logger.warning("No embedder configured; returning zero vector for query embedding")
            return [0.0] * 1536

        try:
            embeddings = self._embedder.embed([query])
            return embeddings[0]
        except Exception as exc:
            logger.error("Embedding failed: %s", exc)
            return [0.0] * 1536

    async def _dense_retrieve(
        self, query_embedding: list[float], top_k: int
    ) -> list[Document]:
        """Query pgvector for nearest-neighbour documents."""
        if self._pgvector is None:
            return []
        try:
            return await asyncio.to_thread(
                self._pgvector.search, query_embedding, top_k=top_k, filter={}
            )
        except Exception as exc:
            logger.error("pgvector retrieval failed: %s", exc)
            return []

    async def _sparse_retrieve(self, query: str, top_k: int) -> list[Document]:
        """Query OpenSearch for BM25-ranked documents."""
        if self._opensearch is None:
            return []
        try:
            return await asyncio.to_thread(
                self._opensearch.search_bm25, query, top_k=top_k
            )
        except Exception as exc:
            logger.error("OpenSearch retrieval failed: %s", exc)
            return []

    def _apply_acl_filter(
        self, docs: list[Document], acl_filter: dict[str, Any]
    ) -> list[Document]:
        """Filter documents that the requesting agent is not permitted to see."""
        agent_tier = acl_filter.get("tier", "T0")
        tier_order = {"T0": 0, "T1": 1, "T2": 2}
        agent_tier_rank = tier_order.get(agent_tier, 0)

        filtered: list[Document] = []
        for doc in docs:
            acl_tiers: list[str] = doc.metadata.get("acl_tiers", ["T0", "T1", "T2"])
            # Allow if ANY of the doc's permitted tiers is <= agent's tier
            allowed = any(
                tier_order.get(t, 99) <= agent_tier_rank for t in acl_tiers
            )
            if allowed:
                filtered.append(doc)
        return filtered

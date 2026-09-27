"""HybridRetriever — dense + sparse retrieval with RRF fusion and reranking."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from ..config.settings import Settings
from ..embeddings.local_bge import LocalBGEEmbedder
from ..stores.opensearch_store import OpenSearchStore
from ..stores.pgvector_store import PgVectorStore
from .acl_filter import ACLFilter
from .reranker import CrossEncoderReranker
from .rrf import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Enterprise-grade hybrid retriever for the MCP security RAG pipeline.

    Retrieval pipeline (executed per query):

    1. **Embed query** — :class:`LocalBGEEmbedder` with BGE query prefix.
    2. **Dense retrieval** — cosine ANN search via :class:`PgVectorStore`.
    3. **Sparse retrieval** — BM25 full-text search via :class:`OpenSearchStore`.
    4. **RRF fusion** — :func:`reciprocal_rank_fusion` merges both ranked
       lists into a single score-ordered list.
    5. **ACL filter** — :class:`ACLFilter` removes documents the agent is
       not permitted to read.
    6. **Cross-encoder reranking** — :class:`CrossEncoderReranker` selects the
       best *top_k* results from the fused candidate pool.

    All blocking I/O and model inference is offloaded to the default thread
    pool via :func:`asyncio.get_event_loop().run_in_executor` so the method
    is safe to ``await`` from an async web handler.

    Args:
        settings: Application settings instance.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder = LocalBGEEmbedder(model_name=settings.EMBEDDING_MODEL)
        self.pgvector = PgVectorStore(
            settings.POSTGRES_URL, dim=settings.EMBEDDING_DIM
        )
        self.opensearch = OpenSearchStore(
            settings.OPENSEARCH_URL, dim=settings.EMBEDDING_DIM
        )
        self.reranker = CrossEncoderReranker()
        self.acl_filter = ACLFilter()

    # ── Public API ────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        acl_context: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Retrieve the most relevant documents for *query*.

        Args:
            query:       Natural language query string.
            top_k:       Number of documents to return after reranking.
            acl_context: Optional ACL context dict.  Recognised keys:

                         * ``agent_tier``  (``str``)       — e.g. ``"internal"``
                         * ``agent_roles`` (``List[str]``) — e.g. ``["developer"]``
                         * ``agent_id``   (``str``)        — agent identifier

        Returns:
            List of :class:`Document` objects sorted by relevance, at most
            *top_k* entries.  Returns an empty list when the query is empty or
            no documents survive filtering.
        """
        if not query or not query.strip():
            logger.warning("HybridRetriever.retrieve called with empty query.")
            return []

        loop = asyncio.get_event_loop()
        candidate_multiplier = 3  # Fetch extra candidates for reranking headroom

        # ── Step 1: Embed query ──────────────────────────────────────────
        query_embedding: List[float] = await loop.run_in_executor(
            None, self.embedder.embed_query, query
        )

        # ── Step 2: Dense retrieval (pgvector cosine ANN) ───────────────
        pg_filter = self._acl_to_pg_filter(acl_context)
        pg_results: List[Tuple[Document, float]] = await loop.run_in_executor(
            None,
            lambda: self.pgvector.search(
                query_embedding,
                top_k=top_k * candidate_multiplier,
                filter=pg_filter,
            ),
        )
        pg_docs: List[Document] = [doc for doc, _ in pg_results]
        logger.debug("HybridRetriever: pgvector returned %d results.", len(pg_docs))

        # ── Step 3: Sparse BM25 retrieval (OpenSearch) ──────────────────
        os_filter = self._acl_to_os_filter(acl_context)
        os_results: List[Tuple[Document, float]] = await loop.run_in_executor(
            None,
            lambda: self.opensearch.bm25_search(
                query,
                top_k=top_k * candidate_multiplier,
                filter=os_filter,
            ),
        )
        os_docs: List[Document] = [doc for doc, _ in os_results]
        logger.debug("HybridRetriever: OpenSearch BM25 returned %d results.", len(os_docs))

        if not pg_docs and not os_docs:
            logger.info("HybridRetriever: no results from either store.")
            return []

        # ── Step 4: RRF fusion ───────────────────────────────────────────
        fused: List[Tuple[Document, float]] = reciprocal_rank_fusion(
            [pg_docs, os_docs], k=60
        )
        logger.debug("HybridRetriever: RRF fused to %d unique candidates.", len(fused))

        # ── Step 5: ACL filter ───────────────────────────────────────────
        if acl_context:
            fused_docs = [doc for doc, _ in fused]
            allowed = self.acl_filter.filter(fused_docs, acl_context)
            # Reconstruct (doc, score) list preserving RRF scores
            allowed_set = {id(doc) for doc in allowed}
            fused = [
                (doc, score)
                for doc, score in fused
                if id(doc) in allowed_set
            ]
            logger.debug(
                "HybridRetriever: %d documents remain after ACL filter.", len(fused)
            )

        # ── Step 6: Cross-encoder reranking ─────────────────────────────
        candidate_docs = [doc for doc, _ in fused[: top_k * candidate_multiplier]]

        if not candidate_docs:
            return []

        reranked: List[Tuple[Document, float]] = await loop.run_in_executor(
            None,
            lambda: self.reranker.rerank(query, candidate_docs, top_k=top_k),
        )

        return [doc for doc, _ in reranked]

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _acl_to_pg_filter(
        acl_context: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Translate ACL context into a pgvector metadata filter."""
        if not acl_context:
            return None
        agent_tier = acl_context.get("agent_tier")
        if agent_tier:
            return {"acl_tiers": agent_tier}
        return None

    @staticmethod
    def _acl_to_os_filter(
        acl_context: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Translate ACL context into an OpenSearch filter."""
        if not acl_context:
            return None
        agent_tier = acl_context.get("agent_tier")
        if agent_tier:
            return {"acl_tiers": agent_tier}
        return None

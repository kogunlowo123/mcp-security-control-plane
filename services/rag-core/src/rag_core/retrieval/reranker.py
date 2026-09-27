"""Cross-encoder reranker using sentence-transformers."""

from __future__ import annotations

import logging
from typing import List, Tuple

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    """Reranks candidate documents against a query using a cross-encoder model.

    Unlike bi-encoder models (which embed query and document independently),
    a cross-encoder jointly processes the query and each candidate, producing
    more accurate relevance scores at the cost of higher latency.

    This reranker is used as the final stage of :class:`HybridRetriever` to
    select the best *top_k* results from the RRF-fused candidate pool.

    The model is loaded lazily on first call.

    Args:
        model_name: HuggingFace cross-encoder model identifier.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
            logger.info("Loaded CrossEncoder: %s", self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int = 5,
    ) -> List[Tuple[Document, float]]:
        """Score (query, document) pairs and return the top-*k* results.

        The cross-encoder score is stored in ``doc.metadata["rerank_score"]``
        so that callers can inspect it without re-computing.

        Args:
            query:     The user query string.
            documents: Candidate documents to score.
            top_k:     Maximum number of results to return.

        Returns:
            List of ``(Document, score)`` tuples sorted by **descending** score,
            truncated to *top_k* entries.  Returns an empty list when
            *documents* is empty.
        """
        if not documents:
            return []

        model = self._get_model()
        pairs = [(query, doc.page_content) for doc in documents]
        raw_scores = model.predict(pairs)

        # raw_scores is a numpy array; convert to Python floats
        scored: List[Tuple[Document, float]] = []
        for doc, score in zip(documents, raw_scores.tolist()):
            doc.metadata["rerank_score"] = round(float(score), 4)
            scored.append((doc, float(score)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

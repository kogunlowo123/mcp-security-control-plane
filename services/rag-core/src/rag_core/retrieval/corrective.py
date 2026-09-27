"""CorrectiveRAG — validates retrieved documents for query relevance."""

from __future__ import annotations

import logging
from typing import List, Tuple

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_DEFAULT_THRESHOLD = 0.1


class CorrectiveRAG:
    """Post-retrieval relevance filter that removes off-topic documents.

    Irrelevant context passed to an LLM is one of the primary causes of
    hallucinated answers in RAG pipelines.  This component scores each
    candidate document against the query using a cross-encoder and discards
    those whose relevance score falls below a configurable threshold.

    Documents that are filtered out are returned separately so callers can
    log them for debugging or trigger a fallback retrieval path.

    Args:
        model_name:          Cross-encoder model for relevance scoring.
        relevance_threshold: Minimum score to keep a document (default 0.1).
                             The ms-marco family returns logits (unbounded);
                             adjust based on empirical calibration for your
                             corpus.  Negative scores indicate irrelevance.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        relevance_threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        self.model_name = model_name
        self.relevance_threshold = relevance_threshold
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def validate(
        self,
        query: str,
        documents: List[Document],
    ) -> Tuple[List[Document], List[Document]]:
        """Split documents into relevant and irrelevant sets.

        Stores the relevance score in ``doc.metadata["corrective_score"]``
        for observability.

        Args:
            query:     The user query string.
            documents: Candidate documents to evaluate.

        Returns:
            ``(relevant, filtered)`` — two lists partitioned by threshold.
        """
        if not documents:
            return [], []

        model = self._get_model()
        pairs = [(query, doc.page_content) for doc in documents]
        raw_scores = model.predict(pairs)

        relevant: List[Document] = []
        filtered_out: List[Document] = []

        for doc, score in zip(documents, raw_scores.tolist()):
            score_f = float(score)
            doc.metadata["corrective_score"] = round(score_f, 4)
            if score_f >= self.relevance_threshold:
                relevant.append(doc)
            else:
                filtered_out.append(doc)
                logger.debug(
                    "CorrectiveRAG: filtered doc (score=%.3f) from source=%s",
                    score_f,
                    doc.metadata.get("source", "unknown"),
                )

        logger.info(
            "CorrectiveRAG: %d relevant / %d filtered (threshold=%.3f).",
            len(relevant),
            len(filtered_out),
            self.relevance_threshold,
        )
        return relevant, filtered_out

    def filter(self, query: str, documents: List[Document]) -> List[Document]:
        """Return only the documents that pass the relevance threshold.

        Convenience wrapper around :meth:`validate`.
        """
        relevant, _ = self.validate(query, documents)
        return relevant

    # Alias used by older callers that call filter_relevant
    def filter_relevant(
        self,
        query: str,
        documents: List[Document],
        fast_mode: bool = False,
    ) -> List[Document]:
        """Return relevant documents, optionally via a fast keyword-overlap heuristic.

        Args:
            query:     The user query.
            documents: Candidate documents.
            fast_mode: When ``True``, use keyword overlap instead of the
                       cross-encoder (cheaper but less accurate).
        """
        if fast_mode:
            return self._keyword_filter(query, documents)
        return self.filter(query, documents)

    def _keyword_filter(self, query: str, documents: List[Document]) -> List[Document]:
        """Lightweight keyword overlap filter for fast-mode / CI use."""
        query_terms = set(query.lower().split())
        relevant: List[Document] = []
        for doc in documents:
            content_terms = set(doc.page_content.lower().split())
            overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
            if overlap >= 0.1:
                relevant.append(doc)
        return relevant

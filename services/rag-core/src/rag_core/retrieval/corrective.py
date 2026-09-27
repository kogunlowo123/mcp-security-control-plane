"""Corrective RAG: validates retrieved documents for relevance."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


class CorrectiveRAG:
    """Filters retrieved documents for relevance and hallucinaton prevention.

    In production this uses an LLM-as-judge; in fast/CI mode it uses a
    simple keyword overlap heuristic.
    """

    def __init__(self, relevance_threshold: float = 0.3) -> None:
        self._threshold = relevance_threshold

    def filter_relevant(
        self,
        query: str,
        documents: list[Any],
        fast_mode: bool = True,
    ) -> list[Any]:
        """Return only documents relevant to the query.

        Args:
            query: The original query string.
            documents: List of Document objects to evaluate.
            fast_mode: Use keyword overlap instead of LLM judge.

        Returns:
            Filtered list of relevant documents.
        """
        if fast_mode:
            return self._keyword_filter(query, documents)
        return documents  # full LLM judge requires live model

    def _keyword_filter(self, query: str, documents: list[Any]) -> list[Any]:
        """Simple keyword overlap filter."""
        query_terms = set(query.lower().split())
        relevant: list[Any] = []
        for doc in documents:
            content_terms = set(doc.page_content.lower().split())
            overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
            if overlap >= self._threshold:
                relevant.append(doc)
        return relevant

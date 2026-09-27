"""Reciprocal Rank Fusion (RRF) — fuses multiple ranked result lists."""

from __future__ import annotations

from typing import List, Tuple

from langchain_core.documents import Document


def reciprocal_rank_fusion(
    rankings: List[List[Document]],
    k: int = 60,
) -> List[Tuple[Document, float]]:
    """Combine multiple ranked document lists using Reciprocal Rank Fusion.

    Each document's RRF score is the sum of ``1 / (k + rank)`` across all
    lists it appears in.  Documents that appear near the top of multiple lists
    receive the highest combined scores.

    The algorithm is parameter-light: the only tunable is *k*, which dampens
    the contribution of top-ranked documents.  The value 60 is the canonical
    default from the original paper (Cormack et al., 2009) and works well in
    practice for combining dense and sparse retrieval.

    Args:
        rankings: One or more lists of :class:`Document` objects, each sorted
                  best-first.  Lists may overlap in their contents.
        k:        Rank constant (default 60).  Higher values reduce the
                  advantage of being ranked first.

    Returns:
        Sorted list of ``(Document, rrf_score)`` tuples, best-first.
        Returns an empty list when *rankings* is empty or contains no
        documents.
    """
    if not rankings:
        return []

    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            key = _doc_key(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in doc_map:
                doc_map[key] = doc

    sorted_keys = sorted(scores, key=lambda k_: scores[k_], reverse=True)
    return [(doc_map[key], scores[key]) for key in sorted_keys]


def _doc_key(doc: Document) -> str:
    """Derive a stable identity key for *doc*.

    Preference order:
    1. ``metadata["id"]`` — explicit UUID assigned during ingestion.
    2. ``"{source}:{chunk_index}"`` — deterministic for re-ingested content.
    3. Hash of the first 200 characters of content — last resort.
    """
    doc_id: str = doc.metadata.get("id", "")
    if doc_id:
        return f"id:{doc_id}"

    source: str = doc.metadata.get("source", "")
    chunk_index: Any = doc.metadata.get("chunk_index", "")
    if source:
        return f"{source}:{chunk_index}"

    return f"content:{hash(doc.page_content[:200])}"


# Allow the type annotation to resolve at module level
from typing import Any  # noqa: E402  (needed only for the annotation in _doc_key)

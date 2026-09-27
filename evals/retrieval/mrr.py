"""Mean Reciprocal Rank (MRR) evaluation for the RAG retrieval pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    """Compute Reciprocal Rank for a single query.

    Returns 1/rank of first relevant hit, or 0 if none found.
    """
    relevant_set = set(relevant_ids)
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_set:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(
    queries: list[dict[str, Any]],
    retriever: Any,
    top_k: int = 10,
) -> dict[str, Any]:
    """Compute MRR over a set of queries.

    Args:
        queries: List of dicts with 'question' and 'relevant_ids'.
        retriever: Object with retrieve(query, top_k) returning Documents.
        top_k: Number of results to retrieve per query.

    Returns:
        Dict with mrr score, per-query results.
    """
    rr_scores: list[float] = []
    per_query: list[dict[str, Any]] = []

    for example in queries:
        query = example["question"]
        relevant_ids: list[str] = example.get("relevant_ids", [])

        try:
            results = retriever.retrieve(query, top_k=top_k)
            retrieved_ids = [str(doc.metadata.get("doc_id", i)) for i, doc in enumerate(results)]
        except Exception as exc:
            print(f"Retrieval error for '{query[:60]}': {exc}", file=sys.stderr)
            retrieved_ids = []

        rr = reciprocal_rank(retrieved_ids, relevant_ids)
        rr_scores.append(rr)
        per_query.append({
            "id": example.get("id", "unknown"),
            "rr": rr,
            "query": query[:80],
        })

    mrr = sum(rr_scores) / len(rr_scores) if rr_scores else 0.0

    return {
        "mrr": mrr,
        "num_queries": len(rr_scores),
        "top_k": top_k,
        "per_query": per_query,
    }


def main() -> int:
    dataset_path = (
        Path(__file__).parent.parent / "datasets" / "golden" / "mcp-security-qa-pairs.jsonl"
    )
    with dataset_path.open() as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    class MockRetriever:
        def retrieve(self, query: str, top_k: int = 10) -> list:
            return []

    results = mean_reciprocal_rank(dataset, MockRetriever(), top_k=10)
    print(json.dumps(results, indent=2))

    threshold = 0.7
    if results["mrr"] < threshold:
        print(
            f"\nFAIL: MRR={results['mrr']:.3f} < threshold={threshold}",
            file=sys.stderr,
        )
        return 1

    print(f"\nPASS: MRR={results['mrr']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

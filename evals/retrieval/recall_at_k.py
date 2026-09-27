"""Recall@K evaluation for the RAG retrieval pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def calculate_recall_at_k(
    retrieved_ids: list[str],
    relevant_ids: list[str],
    k: int,
) -> float:
    """Compute recall at K.

    Args:
        retrieved_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of relevant document IDs for the query.
        k: Cutoff rank.

    Returns:
        Recall@K score in [0, 1].
    """
    if not relevant_ids:
        return 0.0

    top_k = set(retrieved_ids[:k])
    relevant_set = set(relevant_ids)
    hits = len(top_k & relevant_set)
    return hits / len(relevant_set)


def evaluate_dataset(
    dataset: list[dict[str, Any]],
    retriever: Any,
    k: int = 5,
) -> dict[str, float]:
    """Evaluate recall@k across a full dataset.

    Args:
        dataset: List of evaluation examples with 'question' and 'relevant_ids'.
        retriever: Object with a retrieve(query, top_k) method returning Documents.
        k: Cutoff rank.

    Returns:
        Dict with mean recall@k and per-query scores.
    """
    scores: list[float] = []
    per_query: list[dict[str, Any]] = []

    for example in dataset:
        query = example["question"]
        relevant_ids: list[str] = example.get("relevant_ids", [])

        try:
            results = retriever.retrieve(query, top_k=k)
            retrieved_ids = [str(doc.metadata.get("doc_id", i)) for i, doc in enumerate(results)]
        except Exception as exc:
            print(f"Retrieval error for query '{query[:60]}...': {exc}", file=sys.stderr)
            retrieved_ids = []

        score = calculate_recall_at_k(retrieved_ids, relevant_ids, k)
        scores.append(score)
        per_query.append({
            "id": example.get("id", "unknown"),
            "recall_at_k": score,
            "query": query[:80],
        })

    mean_recall = sum(scores) / len(scores) if scores else 0.0

    return {
        "mean_recall_at_k": mean_recall,
        "k": k,
        "num_queries": len(scores),
        "per_query": per_query,
    }


def main() -> int:
    dataset_path = (
        Path(__file__).parent.parent / "datasets" / "golden" / "mcp-security-qa-pairs.jsonl"
    )

    with dataset_path.open() as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    # In CI, use a mock retriever; in production, instantiate HybridRetriever
    class MockRetriever:
        def retrieve(self, query: str, top_k: int = 5) -> list:
            return []

    results = evaluate_dataset(dataset, MockRetriever(), k=5)
    print(json.dumps(results, indent=2))

    threshold = 0.8
    if results["mean_recall_at_k"] < threshold:
        print(
            f"\nFAIL: recall@5={results['mean_recall_at_k']:.3f} < threshold={threshold}",
            file=sys.stderr,
        )
        return 1

    print(f"\nPASS: recall@5={results['mean_recall_at_k']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

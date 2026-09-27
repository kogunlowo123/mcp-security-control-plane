"""Citation accuracy evaluation: checks that cited sources are real and relevant."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


def extract_citations(text: str) -> list[str]:
    """Extract citation references from generated text.

    Looks for patterns like [Source: doc_id], [1], [doc-name], etc.
    """
    patterns = [
        r"\[Source:\s*([^\]]+)\]",
        r"\[(\d+)\]",
        r"\[([a-zA-Z0-9_-]+)\]",
    ]
    citations: list[str] = []
    for pattern in patterns:
        citations.extend(re.findall(pattern, text))
    return list(set(citations))


def score_citation_accuracy(
    generated_answer: str,
    retrieved_docs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score citation accuracy for a single answer.

    Args:
        generated_answer: Generated text potentially containing citations.
        retrieved_docs: List of retrieved documents with 'doc_id' and 'title'.

    Returns:
        Dict with precision, recall, and matched citations.
    """
    cited = extract_citations(generated_answer)
    available_ids = {str(doc.get("doc_id", "")) for doc in retrieved_docs}
    available_titles = {doc.get("title", "").lower() for doc in retrieved_docs}

    correct_citations: list[str] = []
    for cite in cited:
        if cite in available_ids or cite.lower() in available_titles:
            correct_citations.append(cite)

    precision = len(correct_citations) / len(cited) if cited else 1.0
    recall = len(correct_citations) / len(retrieved_docs) if retrieved_docs else 1.0

    return {
        "precision": precision,
        "recall": recall,
        "cited": cited,
        "correct": correct_citations,
        "total_available": len(retrieved_docs),
    }


def evaluate_dataset(
    dataset: list[dict[str, Any]],
    generated_answers: list[str],
    retrieved_docs_per_query: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evaluate citation accuracy across the golden dataset."""
    precisions: list[float] = []
    recalls: list[float] = []
    per_query: list[dict[str, Any]] = []

    docs_per_query = retrieved_docs_per_query or [[] for _ in dataset]

    for example, answer, docs in zip(dataset, generated_answers, docs_per_query):
        result = score_citation_accuracy(answer, docs)
        precisions.append(result["precision"])
        recalls.append(result["recall"])
        per_query.append({
            "id": example.get("id", "unknown"),
            "citation_precision": result["precision"],
            "citation_recall": result["recall"],
        })

    return {
        "mean_citation_precision": sum(precisions) / len(precisions) if precisions else 0.0,
        "mean_citation_recall": sum(recalls) / len(recalls) if recalls else 0.0,
        "num_queries": len(per_query),
        "per_query": per_query,
    }


def main() -> int:
    dataset_path = (
        Path(__file__).parent.parent / "datasets" / "golden" / "mcp-security-qa-pairs.jsonl"
    )
    with dataset_path.open() as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    generated_answers = [ex["expected_answer"] for ex in dataset]
    results = evaluate_dataset(dataset, generated_answers)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

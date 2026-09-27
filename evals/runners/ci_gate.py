"""CI evaluation gate: runs all evals and enforces thresholds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

THRESHOLDS = {
    "recall_at_5": 0.8,
    "mrr": 0.7,
    "faithfulness": 0.85,
    "citation_precision": 0.75,
}

DATASET_PATH = Path(__file__).parent.parent / "datasets" / "golden" / "mcp-security-qa-pairs.jsonl"


def load_dataset() -> list[dict]:
    with DATASET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def run_recall_eval(dataset: list[dict]) -> dict:
    from evals.retrieval.recall_at_k import evaluate_dataset

    class MockRetriever:
        def retrieve(self, query: str, top_k: int = 5) -> list:
            return []

    return evaluate_dataset(dataset, MockRetriever(), k=5)


def run_mrr_eval(dataset: list[dict]) -> dict:
    from evals.retrieval.mrr import mean_reciprocal_rank

    class MockRetriever:
        def retrieve(self, query: str, top_k: int = 10) -> list:
            return []

    return mean_reciprocal_rank(dataset, MockRetriever(), top_k=10)


def run_faithfulness_eval(dataset: list[dict]) -> dict:
    from evals.generation.faithfulness import evaluate_dataset

    generated_answers = [ex["expected_answer"] for ex in dataset]
    return evaluate_dataset(dataset, generated_answers, llm_client=None)


def run_citation_eval(dataset: list[dict]) -> dict:
    from evals.generation.citation_accuracy import evaluate_dataset

    generated_answers = [ex["expected_answer"] for ex in dataset]
    return evaluate_dataset(dataset, generated_answers)


def main() -> int:
    dataset = load_dataset()
    print(f"Loaded {len(dataset)} evaluation examples\n")

    results: dict[str, dict] = {}
    failures: list[str] = []

    # Recall@5
    recall_results = run_recall_eval(dataset)
    results["recall"] = recall_results
    print(f"Recall@5:         {recall_results['mean_recall_at_k']:.3f} (threshold={THRESHOLDS['recall_at_5']})")
    if recall_results["mean_recall_at_k"] < THRESHOLDS["recall_at_5"]:
        failures.append(f"recall_at_5={recall_results['mean_recall_at_k']:.3f} < {THRESHOLDS['recall_at_5']}")

    # MRR
    mrr_results = run_mrr_eval(dataset)
    results["mrr"] = mrr_results
    print(f"MRR:              {mrr_results['mrr']:.3f} (threshold={THRESHOLDS['mrr']})")
    if mrr_results["mrr"] < THRESHOLDS["mrr"]:
        failures.append(f"mrr={mrr_results['mrr']:.3f} < {THRESHOLDS['mrr']}")

    # Faithfulness
    faith_results = run_faithfulness_eval(dataset)
    results["faithfulness"] = faith_results
    print(f"Faithfulness:     {faith_results['mean_faithfulness']:.3f} (threshold={THRESHOLDS['faithfulness']})")
    if faith_results["mean_faithfulness"] < THRESHOLDS["faithfulness"]:
        failures.append(f"faithfulness={faith_results['mean_faithfulness']:.3f} < {THRESHOLDS['faithfulness']}")

    # Citation Precision
    cite_results = run_citation_eval(dataset)
    results["citation"] = cite_results
    print(f"Citation Prec.:   {cite_results['mean_citation_precision']:.3f} (threshold={THRESHOLDS['citation_precision']})")
    if cite_results["mean_citation_precision"] < THRESHOLDS["citation_precision"]:
        failures.append(
            f"citation_precision={cite_results['mean_citation_precision']:.3f} < {THRESHOLDS['citation_precision']}"
        )

    print("\n" + "=" * 60)
    if failures:
        print(f"EVAL GATE FAILED: {len(failures)} metric(s) below threshold:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("EVAL GATE PASSED: all metrics above thresholds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

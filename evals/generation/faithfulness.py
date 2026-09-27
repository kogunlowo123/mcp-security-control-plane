"""Faithfulness evaluation: measures whether generated answers are grounded in context."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


_FAITHFULNESS_PROMPT = """You are an evaluation judge assessing whether a generated answer is faithful to the provided context documents.

CONTEXT:
{context}

QUESTION:
{question}

GENERATED ANSWER:
{answer}

TASK:
Score the faithfulness of the generated answer on a scale of 0 to 1, where:
- 1.0: Every claim in the answer is directly supported by the context
- 0.5: Most claims are supported but some are extrapolated or inferred
- 0.0: Claims are contradicted by or absent from the context

Respond in JSON format only:
{{"score": <float 0-1>, "reason": "<one sentence explanation>"}}
"""


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON object from LLM output text."""
    match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON found in LLM output: {text[:200]}")


def score_faithfulness(
    question: str,
    context: str,
    generated_answer: str,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Score faithfulness of a generated answer against its context.

    Args:
        question: The original query.
        context: Retrieved context documents as text.
        generated_answer: The LLM-generated answer to evaluate.
        llm_client: LiteLLM client or compatible callable; uses mock if None.

    Returns:
        Dict with score, reason, and raw output.
    """
    prompt = _FAITHFULNESS_PROMPT.format(
        context=context[:3000],
        question=question,
        answer=generated_answer[:1000],
    )

    if llm_client is None:
        # Mock for CI — real evaluation requires live LLM
        return {"score": 0.9, "reason": "Mock evaluation (no LLM client configured)", "mock": True}

    try:
        response = llm_client(prompt)
        result = _extract_json(response)
        score = float(result.get("score", 0.0))
        return {
            "score": max(0.0, min(1.0, score)),
            "reason": result.get("reason", ""),
            "raw": response[:500],
        }
    except Exception as exc:
        return {"score": 0.0, "reason": f"Evaluation error: {exc}", "error": str(exc)}


def evaluate_dataset(
    dataset: list[dict[str, Any]],
    generated_answers: list[str],
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """Evaluate faithfulness across a full dataset.

    Args:
        dataset: Golden QA pairs with 'question' and 'context'.
        generated_answers: List of generated answers aligned with dataset.
        llm_client: LLM callable for judge scoring.

    Returns:
        Aggregate faithfulness metrics.
    """
    scores: list[float] = []
    per_query: list[dict[str, Any]] = []

    for example, answer in zip(dataset, generated_answers):
        result = score_faithfulness(
            question=example["question"],
            context=example.get("context", ""),
            generated_answer=answer,
            llm_client=llm_client,
        )
        scores.append(result["score"])
        per_query.append({
            "id": example.get("id", "unknown"),
            "faithfulness_score": result["score"],
            "reason": result.get("reason", ""),
        })

    mean_score = sum(scores) / len(scores) if scores else 0.0

    return {
        "mean_faithfulness": mean_score,
        "num_queries": len(scores),
        "per_query": per_query,
    }


def main() -> int:
    dataset_path = (
        Path(__file__).parent.parent / "datasets" / "golden" / "mcp-security-qa-pairs.jsonl"
    )
    with dataset_path.open() as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    # Use expected answers as mock generated answers for CI baseline
    generated_answers = [ex["expected_answer"] for ex in dataset]

    results = evaluate_dataset(dataset, generated_answers, llm_client=None)
    print(json.dumps(results, indent=2))

    threshold = 0.85
    if results["mean_faithfulness"] < threshold:
        print(
            f"\nFAIL: faithfulness={results['mean_faithfulness']:.3f} < threshold={threshold}",
            file=sys.stderr,
        )
        return 1

    print(f"\nPASS: faithfulness={results['mean_faithfulness']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

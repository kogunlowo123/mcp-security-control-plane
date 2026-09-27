"""GroundingChecker — verifies LLM outputs are grounded in retrieved documents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import structlog

logger = structlog.get_logger(__name__)

_POLICY_YAML = Path(__file__).parent / "policy.yaml"


def _load_grounding_config() -> dict[str, Any]:
    with _POLICY_YAML.open("r", encoding="utf-8") as fh:
        policy = yaml.safe_load(fh) or {}
    return policy.get("grounding", {})


@dataclass
class GroundingCheckResult:
    """Result of a grounding verification pass."""

    passed: bool
    citation_count: int
    sentence_count: int
    grounded_sentence_count: int
    citation_fraction: float
    ungrounded_sentences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    action: str = "ALLOW"  # "ALLOW" | "WARN" | "BLOCK"


class GroundingChecker:
    """Verifies that LLM-generated output is grounded in retrieved documents.

    Checks that:
    1. The output contains citations that reference the retrieved documents.
    2. The fraction of sentences with citations meets the policy minimum.
    3. Compliance reports meet the minimum citation count.

    Policy thresholds are loaded from ``guardrails/policy.yaml``.

    Args:
        retrieved_docs: The list of documents retrieved during the RAG step.
            Each element must have at least ``"citation"`` or ``"source"`` keys.
        config_override: Optional grounding config dict overriding the YAML.
    """

    def __init__(
        self,
        retrieved_docs: list[dict[str, Any]],
        config_override: dict[str, Any] | None = None,
    ) -> None:
        self._retrieved_docs = retrieved_docs
        self._config = config_override or _load_grounding_config()
        self._min_citation_fraction: float = float(
            self._config.get("min_citation_fraction", 0.25)
        )
        self._action_on_failure: str = self._config.get("action_on_failure", "WARN").upper()
        self._compliance_min_citations: int = int(
            self._config.get("compliance_report_min_citations", 3)
        )
        # Build a set of known citation labels for fast lookup
        self._known_citations: set[str] = self._build_known_citations()

    def _build_known_citations(self) -> set[str]:
        """Collect all citation strings and source names from retrieved docs."""
        known: set[str] = set()
        for doc in self._retrieved_docs:
            citation = doc.get("citation", "")
            source = doc.get("source", "")
            section = doc.get("section", "")
            if citation:
                known.add(citation.lower())
            if source:
                known.add(source.lower())
                # Also add base filename without path
                base = source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                known.add(base.lower())
            if section:
                known.add(section.lower())
        return known

    def check(
        self,
        output_text: str,
        is_compliance_report: bool = False,
    ) -> GroundingCheckResult:
        """Check whether ``output_text`` is grounded in the retrieved docs.

        Args:
            output_text: The LLM-generated text to verify.
            is_compliance_report: If True, applies the stricter
                ``compliance_report_min_citations`` threshold.

        Returns:
            A :class:`GroundingCheckResult` describing the grounding level.
        """
        if not output_text.strip():
            return GroundingCheckResult(
                passed=False,
                citation_count=0,
                sentence_count=0,
                grounded_sentence_count=0,
                citation_fraction=0.0,
                warnings=["Empty output — cannot assess grounding."],
                action="WARN",
            )

        if not self._retrieved_docs:
            # No docs were retrieved; grounding check is not meaningful
            return GroundingCheckResult(
                passed=True,
                citation_count=0,
                sentence_count=0,
                grounded_sentence_count=0,
                citation_fraction=0.0,
                warnings=["No retrieved docs available — grounding check skipped."],
                action="ALLOW",
            )

        # Split into sentences (naive but effective for English markdown)
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", output_text)
            if len(s.strip()) > 20
        ]
        sentence_count = len(sentences)
        if sentence_count == 0:
            return GroundingCheckResult(
                passed=True,
                citation_count=0,
                sentence_count=0,
                grounded_sentence_count=0,
                citation_fraction=1.0,
                action="ALLOW",
            )

        # Count explicit citations (markdown-style [Source] or §Section)
        citation_pattern = re.compile(r"\[([^\]]+)\]|\§\s*\S+", re.IGNORECASE)
        all_citations_raw = citation_pattern.findall(output_text)
        citation_count = len(all_citations_raw)

        # Count grounded sentences (sentences that contain a known citation)
        grounded: list[str] = []
        ungrounded: list[str] = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            is_grounded = any(known in sentence_lower for known in self._known_citations)
            # Also treat any markdown citation bracket as grounded
            if not is_grounded and citation_pattern.search(sentence):
                is_grounded = True
            if is_grounded:
                grounded.append(sentence)
            else:
                ungrounded.append(sentence)

        grounded_count = len(grounded)
        fraction = grounded_count / sentence_count if sentence_count else 0.0

        warnings: list[str] = []
        passed = True

        if fraction < self._min_citation_fraction:
            passed = False
            warnings.append(
                f"Grounding fraction {fraction:.2%} is below policy minimum "
                f"{self._min_citation_fraction:.2%} "
                f"({grounded_count}/{sentence_count} sentences grounded)."
            )

        if is_compliance_report and citation_count < self._compliance_min_citations:
            passed = False
            warnings.append(
                f"Compliance report has only {citation_count} citations; "
                f"minimum required is {self._compliance_min_citations}."
            )

        action = self._action_on_failure if not passed else "ALLOW"

        log = logger.bind(
            checker="grounding",
            sentences=sentence_count,
            grounded=grounded_count,
            fraction=f"{fraction:.2%}",
            citations=citation_count,
        )
        if passed:
            log.info("grounding_check.passed")
        else:
            log.warning("grounding_check.failed", warnings=warnings)

        return GroundingCheckResult(
            passed=passed,
            citation_count=citation_count,
            sentence_count=sentence_count,
            grounded_sentence_count=grounded_count,
            citation_fraction=fraction,
            ungrounded_sentences=ungrounded[:10],  # Limit to 10 examples
            warnings=warnings,
            action=action,
        )

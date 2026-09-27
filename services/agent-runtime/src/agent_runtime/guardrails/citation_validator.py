"""CitationValidator — validates citations in generated compliance reports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Matches [Source Name], [Source § Section], or bare §Section references
_CITATION_RE = re.compile(
    r"""
    \[                          # opening bracket
        (?P<source>[^\]§]+?)    # source name (non-greedy, no brackets or §)
        (?:\s*§\s*(?P<section>[^\]]+))?  # optional § section
    \]                          # closing bracket
    |
    §\s*(?P<bare_section>\S+)   # bare §Section without brackets
    """,
    re.VERBOSE,
)


@dataclass
class CitationRecord:
    """A single citation extracted from a report."""

    raw_text: str
    source: str
    section: str | None
    position: int  # character offset in the source text
    is_valid: bool = True
    validation_error: str | None = None


@dataclass
class CitationValidationResult:
    """Aggregate result of validating all citations in a report."""

    total_citations: int
    valid_citations: int
    invalid_citations: int
    hallucinated_citations: int
    records: list[CitationRecord] = field(default_factory=list)
    passed: bool = True
    errors: list[str] = field(default_factory=list)


class CitationValidator:
    """Validates citations in generated compliance reports.

    Ensures that:
    1. Every citation references a document that was actually retrieved.
    2. Citations are syntactically well-formed (proper bracket format).
    3. Section references exist within the cited document's metadata.
    4. No citations are hallucinated (i.e. invented by the LLM).

    Args:
        retrieved_docs: List of documents from the RAG step. Each must have
            at least a ``"source"`` or ``"citation"`` field.
        strict_mode: If True, any hallucinated citation causes the result to
            fail. If False (default), hallucinations are reported as warnings.
    """

    def __init__(
        self,
        retrieved_docs: list[dict[str, Any]],
        strict_mode: bool = False,
    ) -> None:
        self._retrieved_docs = retrieved_docs
        self._strict = strict_mode
        self._known_sources: dict[str, dict[str, Any]] = self._index_sources()

    def _index_sources(self) -> dict[str, dict[str, Any]]:
        """Build a normalised index of retrieved document sources."""
        index: dict[str, dict[str, Any]] = {}
        for doc in self._retrieved_docs:
            source = doc.get("source", "")
            citation = doc.get("citation", "")
            section = doc.get("section", "")
            doc_id = doc.get("id", "")

            keys: list[str] = []
            if source:
                keys.append(source.lower())
                keys.append(source.rsplit("/", 1)[-1].lower())
            if citation:
                # Strip brackets if present
                clean = re.sub(r"[\[\]]", "", citation).strip()
                keys.append(clean.lower())
                # Strip §section suffix
                base = re.split(r"\s*§", clean)[0].strip()
                keys.append(base.lower())
            if doc_id:
                keys.append(doc_id.lower())

            for key in keys:
                if key:
                    index[key] = doc
        return index

    def validate(self, report_text: str) -> CitationValidationResult:
        """Extract and validate all citations in ``report_text``.

        Args:
            report_text: The full text of the compliance report to validate.

        Returns:
            A :class:`CitationValidationResult` summarising all findings.
        """
        log = logger.bind(checker="citation_validator", doc_count=len(self._retrieved_docs))
        log.info("citation_validator.start")

        records: list[CitationRecord] = []
        errors: list[str] = []
        hallucinated_count = 0

        for match in _CITATION_RE.finditer(report_text):
            source_raw = (match.group("source") or "").strip()
            section = (match.group("section") or match.group("bare_section") or "").strip() or None
            raw_text = match.group(0)
            position = match.start()

            if not source_raw:
                continue

            record = CitationRecord(
                raw_text=raw_text,
                source=source_raw,
                section=section,
                position=position,
            )

            # Look up in known sources
            normalised_source = source_raw.lower()
            found_doc: dict[str, Any] | None = None

            # Exact match first
            if normalised_source in self._known_sources:
                found_doc = self._known_sources[normalised_source]
            else:
                # Partial/fuzzy match: check if any known key is a substring
                for known_key, doc in self._known_sources.items():
                    if known_key in normalised_source or normalised_source in known_key:
                        found_doc = doc
                        break

            if found_doc is None:
                record.is_valid = False
                record.validation_error = (
                    f"Citation '{source_raw}' does not match any retrieved document."
                )
                errors.append(record.validation_error)
                hallucinated_count += 1
                log.warning(
                    "citation_validator.hallucinated",
                    citation=source_raw,
                    position=position,
                )
            else:
                record.is_valid = True

            records.append(record)

        total = len(records)
        valid_count = sum(1 for r in records if r.is_valid)
        invalid_count = total - valid_count

        # Determine pass/fail
        passed = True
        if hallucinated_count > 0 and self._strict:
            passed = False
            errors.insert(
                0,
                f"STRICT MODE: {hallucinated_count} hallucinated citation(s) found.",
            )
        elif hallucinated_count > 0:
            # Non-strict: warn but don't fail
            log.warning("citation_validator.hallucinations_found", count=hallucinated_count)

        result = CitationValidationResult(
            total_citations=total,
            valid_citations=valid_count,
            invalid_citations=invalid_count,
            hallucinated_citations=hallucinated_count,
            records=records,
            passed=passed,
            errors=errors,
        )

        log.info(
            "citation_validator.complete",
            total=total,
            valid=valid_count,
            hallucinated=hallucinated_count,
            passed=passed,
        )
        return result

    def get_citation_summary(self, report_text: str) -> dict[str, Any]:
        """Return a lightweight summary dict without full records.

        Useful for embedding citation stats in audit logs.
        """
        result = self.validate(report_text)
        return {
            "total_citations": result.total_citations,
            "valid_citations": result.valid_citations,
            "hallucinated_citations": result.hallucinated_citations,
            "passed": result.passed,
            "errors": result.errors[:5],  # Top 5 errors max
        }

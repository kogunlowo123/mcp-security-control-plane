"""PIITagger — detects and tags personally identifiable information in documents."""

from __future__ import annotations

import re
from typing import List, Pattern, Tuple

from langchain_core.documents import Document

# ---------------------------------------------------------------------------
# PII pattern registry
# Each entry is (pii_type_name, compiled_regex).
# ---------------------------------------------------------------------------
_PII_PATTERNS: List[Tuple[str, Pattern]] = [
    # US Social Security Number — avoids all-zero groups
    (
        "SSN",
        re.compile(
            r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
        ),
    ),
    # Credit card numbers: Visa, Mastercard, Amex, Discover
    (
        "CREDIT_CARD",
        re.compile(
            r"\b(?:"
            r"4[0-9]{12}(?:[0-9]{3})?"          # Visa 13/16
            r"|5[1-5][0-9]{14}"                  # Mastercard
            r"|3[47][0-9]{13}"                   # Amex
            r"|6(?:011|5[0-9]{2})[0-9]{12}"      # Discover
            r")\b"
        ),
    ),
    # Email address
    (
        "EMAIL",
        re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
        ),
    ),
    # US phone: +1 (555) 123-4567, 555.123.4567, etc.
    (
        "PHONE",
        re.compile(
            r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
        ),
    ),
    # IPv4 address (avoids 255.255.255.255 edge case but catches most)
    (
        "IP_ADDRESS",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
    ),
    # AWS access key IDs (AKIA…, ASIA…, etc.)
    (
        "AWS_ACCESS_KEY",
        re.compile(r"\b(?:AKIA|ASIA|AROA|AIPA|AIDA|AGPA|AIZA)[A-Z0-9]{16}\b"),
    ),
    # Generic API key / token assignment
    (
        "API_KEY",
        re.compile(
            r'(?:api[_\-]?key|api[_\-]?secret|access[_\-]?token|bearer|secret[_\-]?key)'
            r'[\s"\']*[=:]+[\s"\']*'
            r"[A-Za-z0-9_/+\-]{20,}",
            re.IGNORECASE,
        ),
    ),
    # Private key / certificate blocks
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    ),
    # US driver's licence (heuristic: "DL#" or "driver's license" followed by ID)
    (
        "DRIVERS_LICENSE",
        re.compile(
            r"\b(?:DL|driver'?s?\s+licen[sc]e)[:\s#]+[A-Z0-9\-]{5,15}\b",
            re.IGNORECASE,
        ),
    ),
    # Date of birth explicit label
    (
        "DOB",
        re.compile(
            r"\b(?:DOB|date[\s_]of[\s_]birth)[\s:]+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
            re.IGNORECASE,
        ),
    ),
    # US passport (letter(s) + 6-9 digits)
    (
        "PASSPORT",
        re.compile(r"\b[A-Z]{1,2}[0-9]{6,9}\b"),
    ),
    # IBAN (basic structure check)
    (
        "IBAN",
        re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}(?:[A-Z0-9]?){0,16}\b"),
    ),
]


class PIITagger:
    """Detects PII in document text and records the findings in metadata.

    This component adds ``pii_detected`` (bool) and ``pii_types`` (list of
    PII category names) to ``doc.metadata``.  It does **not** redact content;
    use a dedicated redactor for that.

    The patterns cover:
    SSN, credit card, email, phone, IPv4, AWS keys, API keys/tokens, private
    key blocks, driver's licences, dates of birth, passport numbers, and IBANs.

    Usage::

        tagger = PIITagger()
        doc = tagger.tag(doc)
        if doc.metadata["pii_detected"]:
            print("PII found:", doc.metadata["pii_types"])
    """

    def __init__(
        self,
        patterns: List[Tuple[str, Pattern]] = None,  # type: ignore[assignment]
    ) -> None:
        self._patterns: List[Tuple[str, Pattern]] = patterns or _PII_PATTERNS

    def detect(self, text: str) -> List[str]:
        """Scan *text* and return a sorted list of PII type names found.

        Args:
            text: Text to scan.

        Returns:
            Sorted, de-duplicated list of PII category names.
        """
        found: set = set()
        for pii_type, pattern in self._patterns:
            if pattern.search(text):
                found.add(pii_type)
        return sorted(found)

    def tag(self, doc: Document) -> Document:
        """Return *doc* with PII detection results added to metadata.

        Added fields:
        * ``pii_detected`` — ``True`` when any PII was found.
        * ``pii_types``    — sorted list of PII category names.

        Existing ``pii_types`` metadata is **replaced** on each call.
        """
        pii_types = self.detect(doc.page_content)
        metadata = dict(doc.metadata)
        metadata["pii_detected"] = bool(pii_types)
        metadata["pii_types"] = pii_types
        return Document(page_content=doc.page_content, metadata=metadata)

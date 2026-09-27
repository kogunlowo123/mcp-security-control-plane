"""PII tagger for detecting and flagging sensitive data in documents."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PIIMatch:
    pii_type: str
    start: int
    end: int
    value: str


_PATTERNS: dict[str, str] = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "aws_secret_key": r"[a-zA-Z0-9+/]{40}",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}


class PIITagger:
    """Detects PII patterns in text and returns match metadata."""

    def detect(self, text: str) -> list[PIIMatch]:
        """Find all PII matches in the given text."""
        matches: list[PIIMatch] = []
        for pii_type, pattern in _PATTERNS.items():
            for m in re.finditer(pattern, text):
                matches.append(PIIMatch(
                    pii_type=pii_type,
                    start=m.start(),
                    end=m.end(),
                    value=m.group(),
                ))
        return matches

    def has_pii(self, text: str) -> bool:
        """Return True if any PII is detected."""
        return bool(self.detect(text))

    def redact(self, text: str) -> str:
        """Replace PII with redaction markers."""
        result = text
        for pii_type, pattern in _PATTERNS.items():
            result = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", result)
        return result

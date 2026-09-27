"""Auto-tagger: generates keyword tags for documents based on content."""

from __future__ import annotations

import re
from collections import Counter


_SECURITY_TERMS = {
    "authorization", "authentication", "policy", "scope", "violation",
    "audit", "compliance", "token", "jwt", "opa", "mcp", "tool",
    "agent", "bedrock", "aws", "iam", "kms", "encryption", "tls",
    "rate-limit", "anomaly", "detection", "incident", "breach",
}


class AutoTagger:
    """Generates tags for documents using keyword extraction."""

    def tag(self, content: str, top_n: int = 10) -> list[str]:
        """Extract the top-N relevant tags from document content.

        Args:
            content: Document text.
            top_n: Maximum number of tags to return.

        Returns:
            List of tag strings.
        """
        words = re.findall(r"\b[a-z][a-z-]{2,}\b", content.lower())
        counts = Counter(words)

        # Prioritise domain-specific security terms
        domain_tags = [w for w in counts if w in _SECURITY_TERMS]
        domain_tags.sort(key=lambda w: -counts[w])

        # Fill with most-frequent other terms
        other_tags = [
            w for w in counts
            if w not in _SECURITY_TERMS and len(w) > 4
        ]
        other_tags.sort(key=lambda w: -counts[w])

        combined = domain_tags + other_tags
        return combined[:top_n]

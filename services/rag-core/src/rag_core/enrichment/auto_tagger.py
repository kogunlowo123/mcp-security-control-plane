"""AutoTagger — generates content-based tags from domain vocabulary matching."""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Set

from langchain_core.documents import Document

# ---------------------------------------------------------------------------
# Domain vocabulary
# ---------------------------------------------------------------------------
_TAG_VOCAB: Dict[str, List[str]] = {
    "authentication": [
        "authentication", "oauth", "jwt", "login", "credential", "password",
        "mfa", "2fa", "sso", "saml", "oidc", "identity", "session", "token",
        "passkey", "webauthn",
    ],
    "authorization": [
        "authorization", "rbac", "abac", "permission", "role", "access control",
        "privilege", "acl", "policy", "grant", "deny", "scope", "entitlement",
    ],
    "audit-logging": [
        "audit", "log", "trace", "monitoring", "event", "activity", "record",
        "compliance", "siem", "trail", "observability",
    ],
    "data-protection": [
        "encryption", "data protection", "privacy", "gdpr", "pii", "sensitive",
        "redaction", "masking", "tokenization", "data residency", "dpa",
    ],
    "threat-detection": [
        "threat", "attack", "anomaly", "intrusion", "detection", "malware",
        "prompt injection", "jailbreak", "exploitation", "adversarial", "ttp",
    ],
    "mcp-tools": [
        "tool", "function call", "capability", "integration", "plugin",
        "mcp tool", "tool invocation", "tool access", "tool approval",
    ],
    "agent-governance": [
        "agent", "autonomous", "orchestration", "multi-agent", "agentic",
        "llm agent", "agent policy", "agent tier", "human-in-the-loop",
    ],
    "network-security": [
        "network", "firewall", "tls", "ssl", "certificate", "endpoint",
        "api gateway", "rate limit", "ip allowlist", "vpn",
    ],
    "incident-response": [
        "incident", "breach", "response", "remediation", "recovery",
        "forensics", "containment", "runbook", "playbook",
    ],
    "compliance": [
        "compliance", "regulation", "gdpr", "hipaa", "sox", "pci", "dss",
        "nist", "iso 27001", "framework", "cis", "fedramp",
    ],
    "vulnerability-management": [
        "vulnerability", "patch", "cve", "cvss", "remediation", "scanning",
        "pentest", "penetration test", "disclosure",
    ],
    "secrets-management": [
        "secret", "api key", "vault", "hsm", "rotation", "revocation",
        "credential store", "key management",
    ],
}

_STOP_WORDS: Set[str] = frozenset(
    "the a an and or but in on at to for of with by is are was were be been "
    "being have has had do does did this that these those it its will would "
    "shall should may might can could".split()
)


class AutoTagger:
    """Auto-generates content-based tags for MCP security policy documents.

    Tags are matched by keyword co-occurrence between the document text and a
    domain vocabulary.  Both exact-token and sub-string matches are counted,
    with sub-string matches weighted at half a point to reduce noise.

    Usage::

        tagger = AutoTagger()
        doc = tagger.tag(doc)
        print(doc.metadata["tags"])
    """

    def __init__(
        self,
        tag_vocabulary: Optional[Dict[str, List[str]]] = None,
        max_tags: int = 10,
        min_score: float = 1.0,
    ) -> None:
        self._vocab: Dict[str, List[str]] = tag_vocabulary or _TAG_VOCAB
        self._max_tags = max_tags
        self._min_score = min_score

    # ── Private helpers ───────────────────────────────────────────────────

    def _tokenise(self, text: str) -> Counter:
        tokens = re.sub(r"[^\w\s]", " ", text.lower()).split()
        return Counter(t for t in tokens if t not in _STOP_WORDS and len(t) > 2)

    def _score_tag(self, keywords: List[str], freq: Counter) -> float:
        score = 0.0
        for kw in keywords:
            kw_tokens = kw.lower().split()
            if len(kw_tokens) == 1:
                # Single-token keyword: exact match
                score += freq.get(kw_tokens[0], 0) * 1.0
            else:
                # Multi-token phrase: check if all tokens appear near each other
                # by checking each token's frequency
                if all(freq.get(t, 0) > 0 for t in kw_tokens):
                    score += 2.0  # Bonus for phrase match
                else:
                    score += sum(freq.get(t, 0) * 0.5 for t in kw_tokens)
        return score

    # ── Public API ────────────────────────────────────────────────────────

    def generate_tags(self, text: str) -> List[str]:
        """Generate ordered tag list from document content.

        Args:
            text: Raw document text.

        Returns:
            Up to *max_tags* tag strings, sorted by relevance score descending.
        """
        freq = self._tokenise(text)
        tag_scores: Dict[str, float] = {}

        for tag, keywords in self._vocab.items():
            score = self._score_tag(keywords, freq)
            if score >= self._min_score:
                tag_scores[tag] = score

        sorted_tags = sorted(tag_scores, key=lambda t: tag_scores[t], reverse=True)
        return sorted_tags[: self._max_tags]

    def tag(self, doc: Document) -> Document:
        """Add auto-generated tags to *doc*'s metadata.

        Merges auto-generated tags with any existing ``metadata["tags"]``,
        preserving pre-existing tags and appending new ones up to *max_tags*.

        Args:
            doc: Document to tag.

        Returns:
            New :class:`Document` with ``tags`` metadata field updated.
        """
        existing: List[str] = list(doc.metadata.get("tags", []))
        auto = self.generate_tags(doc.page_content)

        merged = list(existing)
        for tag in auto:
            if tag not in merged:
                merged.append(tag)

        metadata = dict(doc.metadata)
        metadata["tags"] = merged[: self._max_tags]
        return Document(page_content=doc.page_content, metadata=metadata)

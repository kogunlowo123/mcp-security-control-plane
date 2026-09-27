"""QueryRewriter — expands and rewrites queries for improved retrieval."""

from __future__ import annotations

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


class QueryRewriter:
    """Provides multiple query expansion and rewriting strategies.

    Strategies available:

    * :meth:`expand`              — synonym expansion using a domain vocabulary.
    * :meth:`decompose`           — split compound queries into sub-questions.
    * :meth:`rewrite_for_bm25`    — optimise for sparse BM25 retrieval.
    * :meth:`generate_hyde_prompt` — build a HyDE hypothetical-document prompt.

    These methods are intentionally stateless and CPU-only.  They can be
    composed freely and do not require model loading.
    """

    # Domain-specific synonym expansions for MCP security policy retrieval
    _SYNONYMS: Dict[str, List[str]] = {
        "mcp": ["model context protocol", "ai agent protocol"],
        "policy": ["rule", "governance", "control", "regulation", "directive"],
        "authentication": ["auth", "authn", "login", "identity verification", "sign-in"],
        "authorization": ["authz", "access control", "permission", "privilege", "rbac"],
        "threat": ["attack", "vulnerability", "risk", "exploit", "adversarial"],
        "audit": ["log", "trace", "monitoring", "compliance check", "oversight"],
        "agent": ["llm agent", "ai agent", "autonomous agent", "agentic"],
        "tool": ["function", "capability", "api endpoint", "integration", "plugin"],
        "sandbox": ["isolation", "containment", "security boundary", "jailbreak"],
        "token": ["api key", "credential", "secret", "jwt", "bearer"],
        "data": ["information", "content", "payload", "record"],
        "security": ["protection", "safeguard", "control", "defence"],
    }

    # Patterns that often signal compound queries
    _COMPOUND_RE = re.compile(
        r"\s+(?:and|also|as well as|furthermore|additionally|plus|along with)\s+",
        re.IGNORECASE,
    )

    _STOP_WORDS = frozenset(
        "a an the is are was were be been being have has had do does did "
        "will would shall should may might can could what how why when "
        "where which who".split()
    )

    # ── Public API ────────────────────────────────────────────────────────

    def expand(self, query: str) -> str:
        """Append domain synonyms for keywords found in *query*.

        Args:
            query: Original query string.

        Returns:
            Extended query string.  Returns *query* unchanged when no
            expansions apply.
        """
        lower = query.lower()
        extras: List[str] = []
        for term, synonyms in self._SYNONYMS.items():
            if re.search(r"\b" + re.escape(term) + r"\b", lower):
                extras.extend(synonyms)

        if not extras:
            return query

        # De-duplicate while preserving order
        seen: set = set()
        unique_extras: List[str] = []
        for e in extras:
            if e not in seen:
                seen.add(e)
                unique_extras.append(e)

        expanded = query + " " + " ".join(unique_extras)
        logger.debug("QueryRewriter.expand: %r -> %r", query, expanded)
        return expanded

    def decompose(self, query: str) -> List[str]:
        """Split a compound query into independent sub-questions.

        Args:
            query: Original query string.

        Returns:
            List of sub-question strings.  Returns ``[query]`` when no
            compound connectors are detected.
        """
        parts = self._COMPOUND_RE.split(query)
        if len(parts) <= 1:
            return [query]

        sub_questions = []
        for part in parts:
            part = part.strip().rstrip(",.?")
            if part:
                # Ensure each sub-question ends with a question mark
                sq = part if part.endswith("?") else part + "?"
                sub_questions.append(sq)

        logger.debug("QueryRewriter.decompose: split into %d sub-questions.", len(sub_questions))
        return sub_questions

    def rewrite_for_bm25(self, query: str) -> str:
        """Produce a BM25-optimised query by removing stop words.

        Stripping stop words from the query reduces noise in BM25 scoring and
        lets the important content terms drive matching.

        Args:
            query: Original query string.

        Returns:
            Stop-word-stripped query string, falling back to *query* when
            all tokens are stop words.
        """
        tokens = re.sub(r"[^\w\s]", " ", query).split()
        filtered = [t for t in tokens if t.lower() not in self._STOP_WORDS and len(t) > 1]
        result = " ".join(filtered)
        return result if result else query

    def generate_hyde_prompt(self, query: str) -> str:
        """Generate a HyDE (Hypothetical Document Embedding) prompt string.

        HyDE embeds a *hypothetical answer* to the query rather than the query
        itself.  When the query vocabulary differs significantly from the
        document corpus (e.g. short question vs. long policy text), this
        technique improves retrieval recall by bridging the gap.

        The returned string is intended to be embedded and used as the dense
        query vector instead of embedding the raw query.

        Args:
            query: The user query.

        Returns:
            A prompt that asks an LLM to write a passage answering *query*.
        """
        return (
            "Please write a concise paragraph from an MCP security policy document "
            f"that directly answers the following question: {query}"
        )

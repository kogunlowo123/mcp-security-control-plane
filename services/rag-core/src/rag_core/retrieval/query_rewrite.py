"""Query rewriter for improved RAG retrieval coverage."""

from __future__ import annotations

import re


class QueryRewriter:
    """Expands and rewrites queries for better retrieval performance.

    Applies heuristic expansions without requiring a live LLM in fast mode.
    """

    _ABBREVIATIONS: dict[str, str] = {
        "mcp": "model context protocol MCP",
        "opa": "open policy agent OPA",
        "rag": "retrieval augmented generation RAG",
        "jwt": "json web token JWT",
        "rbac": "role based access control RBAC",
        "irsa": "IAM roles for service accounts IRSA",
    }

    def rewrite(self, query: str, n_variants: int = 3) -> list[str]:
        """Return the original query plus rewritten variants.

        Args:
            query: Original user query.
            n_variants: Maximum number of variants to return (including original).

        Returns:
            List of query strings to use for retrieval.
        """
        variants: list[str] = [query]

        # Expand abbreviations
        expanded = query.lower()
        for abbr, expansion in self._ABBREVIATIONS.items():
            expanded = re.sub(rf"\b{abbr}\b", expansion, expanded)
        if expanded != query.lower():
            variants.append(expanded)

        # Add question form if statement
        if not query.strip().endswith("?") and len(variants) < n_variants:
            variants.append(f"What is {query}?")

        return variants[:n_variants]

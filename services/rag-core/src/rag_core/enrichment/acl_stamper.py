"""ACLStamper — stamps access control tier and role labels onto documents."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from langchain_core.documents import Document

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------
# Ordered from lowest to highest privilege.
_TIER_ORDER: List[str] = [
    "public",
    "internal",
    "confidential",
    "restricted",
    "top-secret",
]

# Keywords that, when found in the document text, signal a classification level.
# Checked in REVERSE tier order (highest first) so the strongest match wins.
_CLASSIFICATION_KEYWORDS: Dict[str, List[str]] = {
    "top-secret": [
        "top secret",
        "ts/sci",
        "compartmented",
        "eyes only",
        "codeword",
    ],
    "restricted": [
        "restricted",
        "confidential - restricted",
        "internal only",
        "not for distribution",
        "do not share",
        "need to know",
    ],
    "confidential": [
        "confidential",
        "proprietary",
        "private",
        "sensitive",
        "for internal use",
        "not for public release",
    ],
    "internal": [
        "internal",
        "staff only",
        "employee only",
        "for company use",
    ],
    "public": [
        "public",
        "open source",
        "publicly available",
        "freely available",
    ],
}

# Default tiers applied when nothing else determines classification.
_DEFAULT_TIERS: List[str] = ["internal", "confidential", "restricted", "top-secret"]


class ACLStamper:
    """Stamps ``acl_tiers`` and ``acl_roles`` onto document metadata.

    Decision priority (first match wins):

    1. **Explicit arguments** — ``acl_tiers`` / ``acl_roles`` passed to
       :meth:`stamp`.
    2. **Existing metadata** — values already present in the document.
    3. **Keyword inference** — content is scanned for classification keywords;
       the resulting classification expands to all tiers at that level or above
       (e.g. ``"confidential"`` → ``["confidential", "restricted", "top-secret"]``).
    4. **Default tiers** — configurable fallback (default: internal and above).

    Usage::

        stamper = ACLStamper()
        doc = stamper.stamp(doc)
        print(doc.metadata["acl_tiers"])   # e.g. ["confidential", "restricted", "top-secret"]
    """

    def __init__(
        self,
        default_tiers: Optional[List[str]] = None,
        default_roles: Optional[List[str]] = None,
    ) -> None:
        self._default_tiers: List[str] = default_tiers if default_tiers is not None else list(_DEFAULT_TIERS)
        self._default_roles: List[str] = default_roles if default_roles is not None else []

    # ── Private helpers ───────────────────────────────────────────────────

    def _infer_classification(self, text: str) -> Optional[str]:
        """Scan *text* for classification keywords.

        Returns the highest-sensitivity tier name found, or ``None``.
        """
        text_lower = text.lower()
        for tier in reversed(_TIER_ORDER):  # highest first
            for keyword in _CLASSIFICATION_KEYWORDS.get(tier, []):
                if re.search(r"\b" + re.escape(keyword) + r"\b", text_lower):
                    return tier
        return None

    @staticmethod
    def _expand_tiers(classification: str) -> List[str]:
        """Return all tiers at or above *classification*.

        A document classified as 'internal' can be read by agents with tier
        'internal', 'confidential', 'restricted', or 'top-secret'.
        """
        try:
            index = _TIER_ORDER.index(classification)
        except ValueError:
            return list(_DEFAULT_TIERS)
        return _TIER_ORDER[index:]

    # ── Public API ────────────────────────────────────────────────────────

    def stamp(
        self,
        doc: Document,
        acl_tiers: Optional[List[str]] = None,
        acl_roles: Optional[List[str]] = None,
    ) -> Document:
        """Apply ACL labels to *doc* and return the annotated document.

        Args:
            doc:       Document to stamp.
            acl_tiers: Override list of allowed tiers.  When provided, this
                       takes precedence over all other sources.
            acl_roles: Override list of allowed roles.

        Returns:
            New :class:`Document` with ``acl_tiers`` and ``acl_roles`` metadata
            fields set.
        """
        metadata = dict(doc.metadata)

        # ── Determine tiers ───────────────────────────────────────────────
        if acl_tiers is not None:
            final_tiers = list(acl_tiers)
        elif metadata.get("acl_tiers"):
            final_tiers = list(metadata["acl_tiers"])
        else:
            inferred = self._infer_classification(doc.page_content)
            if inferred:
                final_tiers = self._expand_tiers(inferred)
            else:
                final_tiers = list(self._default_tiers)

        # ── Determine roles ───────────────────────────────────────────────
        if acl_roles is not None:
            final_roles = list(acl_roles)
        elif metadata.get("acl_roles"):
            final_roles = list(metadata["acl_roles"])
        else:
            final_roles = list(self._default_roles)

        metadata["acl_tiers"] = final_tiers
        metadata["acl_roles"] = final_roles

        return Document(page_content=doc.page_content, metadata=metadata)

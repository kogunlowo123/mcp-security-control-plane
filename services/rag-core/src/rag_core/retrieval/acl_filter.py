"""ACLFilter — enforces access control on retrieved documents."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Ordered from lowest to highest privilege.
# An agent with tier 'confidential' can read documents stamped
# with 'public', 'internal', or 'confidential' but NOT 'restricted' or
# 'top-secret'.
_TIER_ORDER: List[str] = [
    "public",
    "internal",
    "confidential",
    "restricted",
    "top-secret",
]

_TIER_LEVEL: Dict[str, int] = {t: i for i, t in enumerate(_TIER_ORDER)}

# Default role -> minimum tier mapping
_ROLE_MIN_TIER: Dict[str, str] = {
    "anonymous": "public",
    "user": "internal",
    "developer": "confidential",
    "operator": "restricted",
    "admin": "top-secret",
}


class ACLFilter:
    """Filters a list of documents to those accessible by the requesting agent.

    Access decision logic:

    1. **Explicit deny** — if ``metadata["acl_denied_agents"]`` contains the
       agent's ``agent_id``, the document is denied regardless of tier/role.
    2. **Tier check** — the agent's tier must be at least as privileged as
       the document's minimum required tier.  A document with
       ``acl_tiers = ["internal", "confidential"]`` sets a minimum tier of
       ``internal`` (lowest in its list); an ``anonymous`` agent cannot read
       it.
    3. **Role check** — when the document has ``acl_roles`` set, the agent
       must supply at least one matching role.  Documents without ``acl_roles``
       pass this check unconditionally.

    All three checks must pass.  Failing any one denies access.

    Args:
        tier_hierarchy:  Custom ``{tier_name: level}`` dict (higher = more
                         privileged).  Defaults to :data:`_TIER_LEVEL`.
        role_min_tier:   Mapping from role name to the minimum tier it grants.
                         Used when deriving an agent's tier from its roles.
    """

    def __init__(
        self,
        tier_hierarchy: Optional[Dict[str, int]] = None,
        role_min_tier: Optional[Dict[str, str]] = None,
    ) -> None:
        self._tier_level: Dict[str, int] = tier_hierarchy or dict(_TIER_LEVEL)
        self._role_min_tier: Dict[str, str] = role_min_tier or dict(_ROLE_MIN_TIER)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _tier_level_of(self, tier: str) -> int:
        return self._tier_level.get(tier.lower(), -1)

    def _effective_agent_tier_level(self, acl_context: Dict[str, Any]) -> int:
        """Return the numeric tier level for the agent.

        Uses ``agent_tier`` if present; otherwise derives it from the highest
        privilege role in ``agent_roles``.
        """
        explicit_tier: str = acl_context.get("agent_tier", "")
        if explicit_tier:
            lvl = self._tier_level_of(explicit_tier)
            return lvl if lvl >= 0 else 0

        agent_roles: List[str] = acl_context.get("agent_roles", [])
        best = 0
        for role in agent_roles:
            min_tier = self._role_min_tier.get(role.lower(), "public")
            best = max(best, self._tier_level_of(min_tier))
        return best

    def _doc_min_tier_level(self, doc: Document) -> int:
        """Return the minimum tier level required to read *doc*."""
        acl_tiers: List[str] = doc.metadata.get("acl_tiers", [])
        if not acl_tiers:
            return 0  # No restriction — public by default
        levels = [self._tier_level_of(t) for t in acl_tiers if t]
        valid = [lvl for lvl in levels if lvl >= 0]
        return min(valid) if valid else 0

    def _agent_has_role(self, agent_roles: List[str], doc: Document) -> bool:
        """Return True if the agent's roles satisfy the document's role ACL."""
        acl_roles: List[str] = doc.metadata.get("acl_roles", [])
        if not acl_roles:
            return True  # No role restriction
        agent_set: Set[str] = {r.lower() for r in agent_roles}
        doc_set: Set[str] = {r.lower() for r in acl_roles}
        return bool(agent_set & doc_set)

    # ── Public API ─────────────────────────────────────────────────────────

    def is_allowed(self, doc: Document, acl_context: Dict[str, Any]) -> bool:
        """Return ``True`` if the agent described by *acl_context* may read *doc*.

        Args:
            doc:         Document to evaluate.
            acl_context: Dict with the following optional keys:

                         * ``agent_id``    (``str``)  — agent identifier.
                         * ``agent_tier``  (``str``)  — tier name.
                         * ``agent_roles`` (``List[str]``) — role names.
        """
        # 1. Explicit deny list
        agent_id: str = acl_context.get("agent_id", "")
        denied: List[str] = doc.metadata.get("acl_denied_agents", [])
        if agent_id and agent_id in denied:
            logger.debug("Document denied: agent_id=%s is on deny list.", agent_id)
            return False

        # 2. Tier check
        agent_level = self._effective_agent_tier_level(acl_context)
        required_level = self._doc_min_tier_level(doc)
        if agent_level < required_level:
            logger.debug(
                "Document denied: agent tier level %d < required %d (agent_tier=%s).",
                agent_level,
                required_level,
                acl_context.get("agent_tier"),
            )
            return False

        # 3. Role check
        agent_roles: List[str] = acl_context.get("agent_roles", [])
        if not self._agent_has_role(agent_roles, doc):
            logger.debug(
                "Document denied: agent roles %s do not satisfy acl_roles=%s.",
                agent_roles,
                doc.metadata.get("acl_roles"),
            )
            return False

        return True

    def filter(
        self, documents: List[Document], acl_context: Dict[str, Any]
    ) -> List[Document]:
        """Return only the documents the agent is allowed to read.

        Args:
            documents:   Candidate documents.
            acl_context: ACL context for the requesting agent.

        Returns:
            Sub-list of *documents* for which :meth:`is_allowed` returns
            ``True``.  Ordering is preserved.
        """
        allowed: List[Document] = []
        denied_count = 0

        for doc in documents:
            if self.is_allowed(doc, acl_context):
                allowed.append(doc)
            else:
                denied_count += 1

        if denied_count:
            logger.info(
                "ACLFilter: denied %d/%d documents for agent (tier=%s, id=%s).",
                denied_count,
                len(documents),
                acl_context.get("agent_tier", "?"),
                acl_context.get("agent_id", "?"),
            )

        return allowed

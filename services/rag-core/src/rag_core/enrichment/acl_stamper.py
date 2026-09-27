"""ACL stamper: applies access control labels to documents."""

from __future__ import annotations


_TIER_HIERARCHY = {"T0": 0, "T1": 1, "T2": 2}


class ACLStamper:
    """Stamps access control tier labels onto document metadata."""

    def stamp(
        self,
        metadata: dict,
        min_tier: str = "T0",
        roles: list[str] | None = None,
    ) -> dict:
        """Add ACL fields to a metadata dictionary.

        Args:
            metadata: Existing document metadata dict (mutated in place).
            min_tier: Minimum agent tier required to access this document.
            roles: Optional list of role names allowed to access this doc.

        Returns:
            Updated metadata dict.
        """
        min_rank = _TIER_HIERARCHY.get(min_tier, 0)
        allowed_tiers = [
            tier for tier, rank in _TIER_HIERARCHY.items()
            if rank >= min_rank
        ]
        metadata["acl_tiers"] = allowed_tiers
        metadata["acl_min_tier"] = min_tier
        if roles:
            metadata["acl_roles"] = roles
        return metadata

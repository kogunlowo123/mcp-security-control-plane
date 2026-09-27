"""Token broker for issuing and validating JWT tokens for MCP agents."""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


_REVOKED_JTIS: set[str] = set()
_ISSUER = "mcp-security-control-plane"

# TTL policies per tier in seconds
_TTL_BY_TIER: dict[str, int] = {
    "T0": 3600,
    "T1": 1800,
    "T2": 900,
}


def _generate_rsa_key_pair() -> tuple[bytes, bytes]:
    """Generate an RSA-2048 key pair for token signing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


# Module-level keys; in production these are loaded from AWS Secrets Manager.
_PRIVATE_KEY_PEM, _PUBLIC_KEY_PEM = _generate_rsa_key_pair()


class TokenBroker:
    """Issues, validates, and revokes JWT tokens for MCP agents."""

    def __init__(
        self,
        private_key_pem: bytes | None = None,
        public_key_pem: bytes | None = None,
        issuer: str = _ISSUER,
    ) -> None:
        self._private_key_pem = private_key_pem or _PRIVATE_KEY_PEM
        self._public_key_pem = public_key_pem or _PUBLIC_KEY_PEM
        self._issuer = issuer

    def issue_token(
        self,
        agent_id: str,
        tier: str,
        tool_grants: list[str],
        ttl_seconds: int | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """Issue a signed JWT for the given agent.

        Args:
            agent_id: Unique identifier of the agent.
            tier: Agent tier (T0, T1, T2).
            tool_grants: List of tool names the agent is granted.
            ttl_seconds: Token lifetime; defaults to tier policy.
            extra_claims: Additional claims to embed.

        Returns:
            Signed JWT string.
        """
        if tier not in _TTL_BY_TIER:
            raise ValueError(f"Unknown tier: {tier}")

        ttl = ttl_seconds if ttl_seconds is not None else _TTL_BY_TIER[tier]
        now = int(time.time())
        jti = str(uuid.uuid4())

        payload: dict[str, Any] = {
            "iss": self._issuer,
            "sub": agent_id,
            "agent_id": agent_id,
            "tier": tier,
            "grants": tool_grants,
            "iat": now,
            "exp": now + ttl,
            "jti": jti,
        }
        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(payload, self._private_key_pem, algorithm="RS256")

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a JWT and return its decoded claims.

        Args:
            token: JWT string to validate.

        Returns:
            Decoded token claims.

        Raises:
            jwt.InvalidTokenError: If the token is invalid or expired.
            ValueError: If the token has been revoked.
        """
        claims = jwt.decode(
            token,
            self._public_key_pem,
            algorithms=["RS256"],
            options={"require": ["exp", "iat", "iss", "jti", "agent_id"]},
        )

        jti = claims.get("jti", "")
        if jti in _REVOKED_JTIS:
            raise ValueError(f"Token with jti={jti} has been revoked")

        if claims.get("iss") != self._issuer:
            raise jwt.InvalidIssuerError(f"Unexpected issuer: {claims.get('iss')}")

        return claims

    def revoke_token(self, jti: str) -> None:
        """Revoke a token by its JTI.

        Args:
            jti: JWT ID to revoke.
        """
        _REVOKED_JTIS.add(jti)

    def is_revoked(self, jti: str) -> bool:
        """Check whether a JTI has been revoked."""
        return jti in _REVOKED_JTIS

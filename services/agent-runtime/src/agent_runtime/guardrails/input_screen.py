"""InputScreener — screens agent inputs against guardrail policies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import structlog

logger = structlog.get_logger(__name__)

_POLICY_YAML = Path(__file__).parent / "policy.yaml"


def _load_policy() -> dict[str, Any]:
    with _POLICY_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class ScreeningViolation:
    """A guardrail violation found during input screening."""

    rule_name: str
    severity: str
    action: str  # "BLOCK" | "WARN" | "REDACT"
    matched_text: str
    description: str


@dataclass
class ScreeningResult:
    """The result of screening an agent input."""

    allowed: bool
    violations: list[ScreeningViolation] = field(default_factory=list)
    redacted_text: str | None = None
    block_reason: str | None = None

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    @property
    def has_blocking_violations(self) -> bool:
        return any(v.action == "BLOCK" for v in self.violations)


class InputScreener:
    """Screens agent input text against the guardrail policy.

    Checks for:
    - Blocked topics (prompt injection, credential extraction, etc.)
    - PII patterns (applies redaction rather than blocking)

    Policy is loaded from ``guardrails/policy.yaml`` at instantiation.

    Args:
        policy_override: Optional policy dict to use instead of loading from YAML.
            Useful for testing.
    """

    def __init__(self, policy_override: dict[str, Any] | None = None) -> None:
        self._policy = policy_override or _load_policy()
        self._blocked_topic_patterns: list[tuple[str, str, str, list[re.Pattern[str]]]] = []
        self._pii_patterns: list[tuple[str, str, list[int], re.Pattern[str]]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile all regex patterns from the policy."""
        for topic in self._policy.get("blocked_topics", []):
            name = topic["name"]
            severity = topic.get("severity", "HIGH")
            action = topic.get("action", "BLOCK")
            compiled = [
                re.compile(p, re.IGNORECASE | re.DOTALL)
                for p in topic.get("patterns", [])
            ]
            self._blocked_topic_patterns.append((name, severity, action, compiled))

        pii_config = self._policy.get("pii_detection", {})
        if pii_config.get("enabled", False):
            for pii_name, pii_def in pii_config.get("patterns", {}).items():
                raw_regex: str = pii_def["regex"]
                label: str = pii_def.get("label", "[REDACTED]")
                flags_str: str = pii_def.get("flags", "")
                flags = 0
                if "IGNORECASE" in flags_str:
                    flags |= re.IGNORECASE
                compiled_pii = re.compile(raw_regex, flags)
                self._pii_patterns.append((pii_name, label, [], compiled_pii))

    def screen(self, text: str, context: dict[str, Any] | None = None) -> ScreeningResult:
        """Screen the given text against all guardrail policies.

        Args:
            text: The input text to screen (prompt, tool parameter, etc.).
            context: Optional extra context (e.g. agent_id, tier) for logging.

        Returns:
            A :class:`ScreeningResult`. If ``result.allowed`` is False, the
            caller MUST NOT proceed with the operation.
        """
        log = logger.bind(
            screener="input",
            text_len=len(text),
            **(context or {}),
        )

        violations: list[ScreeningViolation] = []
        working_text = text

        # 1. Check blocked topics
        for topic_name, severity, action, patterns in self._blocked_topic_patterns:
            for pattern in patterns:
                match = pattern.search(working_text)
                if match:
                    violations.append(
                        ScreeningViolation(
                            rule_name=topic_name,
                            severity=severity,
                            action=action,
                            matched_text=match.group(0)[:100],
                            description=f"Blocked topic '{topic_name}' matched pattern '{pattern.pattern}'",
                        )
                    )
                    break  # One violation per topic is sufficient

        # 2. Apply PII redaction
        for pii_name, label, _, pattern in self._pii_patterns:
            matches_found = pattern.findall(working_text)
            if matches_found:
                working_text = pattern.sub(label, working_text)
                violations.append(
                    ScreeningViolation(
                        rule_name=f"pii_{pii_name}",
                        severity="MEDIUM",
                        action="REDACT",
                        matched_text=f"{len(matches_found)} instance(s) redacted",
                        description=f"PII pattern '{pii_name}' found and redacted",
                    )
                )

        # Determine overall result
        blocking = [v for v in violations if v.action == "BLOCK"]
        if blocking:
            block_reason = "; ".join(v.description for v in blocking)
            log.warning("input_screener.blocked", violations=len(blocking), reason=block_reason)
            return ScreeningResult(
                allowed=False,
                violations=violations,
                block_reason=block_reason,
            )

        if violations:
            log.info("input_screener.redacted", redactions=len(violations))
            return ScreeningResult(
                allowed=True,
                violations=violations,
                redacted_text=working_text if working_text != text else None,
            )

        return ScreeningResult(allowed=True)

    def screen_tool_params(
        self, tool_id: str, params: dict[str, Any], agent_id: str
    ) -> ScreeningResult:
        """Screen all string values within a tool parameter dict.

        Args:
            tool_id: The tool being called (for log context).
            params: The parameter dict to screen.
            agent_id: The calling agent (for log context).

        Returns:
            Aggregate :class:`ScreeningResult`. Redacted text is the JSON
            serialisation of the sanitised params dict.
        """
        import json

        flat_text = json.dumps(params, default=str)
        return self.screen(flat_text, context={"tool": tool_id, "agent": agent_id})

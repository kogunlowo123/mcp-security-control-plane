"""AgentPlanner — creates structured task plans for LangGraph agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import litellm
import structlog

logger = structlog.get_logger(__name__)

_BEDROCK_MODEL = "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"

_PLANNER_SYSTEM_PROMPT = (
    "You are a task planner for MCP security agents. "
    "Given a high-level task description and an agent profile, "
    "decompose the task into concrete, ordered steps the agent should execute. "
    "Each step must reference a specific tool or action. "
    "Output ONLY valid JSON — a list of step objects."
)


@dataclass
class PlanStep:
    """A single step in an agent task plan."""

    step_number: int
    action: str
    tool: str | None
    description: str
    expected_output: str
    depends_on: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "tool": self.tool,
            "description": self.description,
            "expected_output": self.expected_output,
            "depends_on": self.depends_on,
        }


@dataclass
class AgentPlan:
    """A complete task plan for an agent."""

    plan_id: str
    agent_id: str
    task: str
    steps: list[PlanStep]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "agent_id": self.agent_id,
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    def __len__(self) -> int:
        return len(self.steps)


class AgentPlanner:
    """Creates structured task plans for LangGraph agents using an LLM.

    Decomposes high-level task descriptions into ordered, tool-grounded steps.
    Plans are used to guide agent iteration and to pre-validate that the
    required tools are available to the agent.

    Args:
        agent_id: Registry identifier of the agent being planned for.
        available_tools: List of tool_ids the agent has grants for.
        max_steps: Maximum number of steps to generate. Default 10.
    """

    def __init__(
        self,
        agent_id: str,
        available_tools: list[str],
        max_steps: int = 10,
    ) -> None:
        self._agent_id = agent_id
        self._available_tools = available_tools
        self._max_steps = max_steps

    async def create_plan(self, task: str, context: dict[str, Any] | None = None) -> AgentPlan:
        """Generate a task plan for the given task description.

        Args:
            task: Free-text description of what the agent needs to accomplish.
            context: Optional additional context (e.g. filters, time ranges).

        Returns:
            An :class:`AgentPlan` with ordered :class:`PlanStep` objects.

        Raises:
            RuntimeError: If the LLM fails to return a parseable plan.
        """
        log = logger.bind(agent=self._agent_id, task_len=len(task))
        log.info("planner.create_plan.start")

        tools_str = ", ".join(self._available_tools) if self._available_tools else "none"
        context_str = json.dumps(context, indent=2) if context else "{}"

        prompt = (
            f"Agent ID: {self._agent_id}\n"
            f"Available tools: {tools_str}\n"
            f"Max plan steps: {self._max_steps}\n"
            f"Context: {context_str}\n\n"
            f"Task: {task}\n\n"
            f"Decompose this task into at most {self._max_steps} ordered steps. "
            f"Each step must use one of the available tools or be a reasoning step (tool=null). "
            f"Return a JSON array of objects with fields: "
            f"step_number (int), action (string), tool (string or null), "
            f"description (string), expected_output (string), depends_on (array of ints)."
        )

        try:
            response = await litellm.acompletion(
                model=_BEDROCK_MODEL,
                messages=[
                    {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.0,
            )
        except Exception as exc:
            log.error("planner.llm_error", error=str(exc))
            raise RuntimeError(f"Planner LLM call failed: {exc}") from exc

        raw: str = response.choices[0].message.content or "[]"
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else "[]"

        try:
            parsed: list[dict[str, Any]] = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error("planner.json_parse_error", error=str(exc), raw=raw[:300])
            raise RuntimeError(f"Planner returned non-JSON: {exc}") from exc

        steps: list[PlanStep] = []
        for raw_step in parsed[: self._max_steps]:
            steps.append(
                PlanStep(
                    step_number=int(raw_step.get("step_number", len(steps) + 1)),
                    action=str(raw_step.get("action", "")),
                    tool=raw_step.get("tool"),
                    description=str(raw_step.get("description", "")),
                    expected_output=str(raw_step.get("expected_output", "")),
                    depends_on=list(raw_step.get("depends_on", [])),
                )
            )

        import uuid

        plan = AgentPlan(
            plan_id=str(uuid.uuid4()),
            agent_id=self._agent_id,
            task=task,
            steps=steps,
            metadata={"context": context or {}},
        )

        log.info("planner.create_plan.complete", steps=len(plan))
        return plan

    def validate_plan(self, plan: AgentPlan) -> list[str]:
        """Validate that a plan's tool references are within the agent's grants.

        Args:
            plan: The plan to validate.

        Returns:
            A list of validation error strings. Empty list means the plan is valid.
        """
        errors: list[str] = []
        for step in plan.steps:
            if step.tool and step.tool not in self._available_tools:
                errors.append(
                    f"Step {step.step_number}: tool '{step.tool}' not in agent grants "
                    f"{self._available_tools}"
                )
        return errors

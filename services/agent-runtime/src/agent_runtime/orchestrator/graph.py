"""LangGraph agent graph for the mcp-auditor agent.

Implements a multi-step audit workflow:
    START
      -> retrieve_policies
      -> analyze_tool_calls
      -> detect_violations
      -> [should_continue] -> generate_report -> END
                          \\-> analyze_tool_calls (loop back, max iterations)
"""

from __future__ import annotations

import json
from typing import Any, Literal

import litellm
import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agent_runtime.orchestrator.state import AgentState
from agent_runtime.tools.mcp_audit_query import MCPAuditQueryTool
from agent_runtime.tools.rag_search import RAGSearchTool

logger = structlog.get_logger(__name__)

_BEDROCK_MODEL = "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
_CALLER_AGENT_ID = "mcp-auditor"
_CALLER_TIER = "T1"

_SYSTEM_PROMPT = (
    "You are an MCP security auditor. Your role is to analyze tool call logs "
    "for compliance violations, anomalous patterns, and security risks. "
    "Ground all findings in retrieved security policies."
)


# ── Node: retrieve_policies ───────────────────────────────────────────────────

async def retrieve_policies(state: AgentState) -> AgentState:
    """Retrieve relevant MCP security policies from the RAG corpus.

    Uses the task description to build a targeted retrieval query.
    Populates ``state["retrieved_docs"]``.
    """
    log = logger.bind(node="retrieve_policies", agent=_CALLER_AGENT_ID)
    task: str = state.get("task", "")
    log.info("retrieve_policies.start", task_len=len(task))

    if state.get("error"):
        log.warning("retrieve_policies.skipped_due_to_error")
        return state  # type: ignore[return-value]

    rag = RAGSearchTool(caller_tier=_CALLER_TIER, caller_agent_id=_CALLER_AGENT_ID)
    result = await rag.execute(
        {
            "query": f"MCP security policy compliance audit: {task}",
            "top_k": 8,
            "min_score": 0.3,
        }
    )

    if not result["success"]:
        log.error("retrieve_policies.rag_failed", error=result["error"])
        return {**state, "error": f"RAG retrieval failed: {result['error']}"}  # type: ignore[return-value]

    docs: list[dict[str, Any]] = result["data"]["documents"]
    log.info("retrieve_policies.complete", docs_retrieved=len(docs))
    return {**state, "retrieved_docs": docs}  # type: ignore[return-value]


# ── Node: analyze_tool_calls ──────────────────────────────────────────────────

async def analyze_tool_calls(state: AgentState) -> AgentState:
    """Analyse tool call logs against retrieved policies using LiteLLM/Bedrock.

    Builds a prompt that includes the retrieved policy excerpts and the raw
    tool call logs, then calls the LLM provider via litellm.acompletion.
    Appends the analysis result to ``state["messages"]``.
    """
    log = logger.bind(node="analyze_tool_calls", agent=_CALLER_AGENT_ID)

    if state.get("error"):
        log.warning("analyze_tool_calls.skipped_due_to_error")
        return state  # type: ignore[return-value]

    retrieved_docs: list[dict[str, Any]] = state.get("retrieved_docs", [])
    tool_call_logs: list[dict[str, Any]] = state.get("tool_call_logs", [])
    task: str = state.get("task", "")
    iteration: int = state.get("iteration_count", 0)

    log.info(
        "analyze_tool_calls.start",
        iteration=iteration,
        docs=len(retrieved_docs),
        logs=len(tool_call_logs),
    )

    # Build policy context block
    policy_context_parts: list[str] = []
    for doc in retrieved_docs:
        citation = doc.get("citation", doc.get("source", "unknown"))
        content = doc.get("content", "")
        policy_context_parts.append(f"[{citation}]\n{content}")
    policy_context = "\n\n---\n\n".join(policy_context_parts) if policy_context_parts else "No policies retrieved."

    # Build tool call logs block (limit to 50 records to stay within context)
    logs_sample = tool_call_logs[:50]
    logs_json = json.dumps(logs_sample, indent=2, default=str) if logs_sample else "[]"

    user_content = (
        f"Task: {task}\n\n"
        f"## Retrieved Security Policies\n\n{policy_context}\n\n"
        f"## Tool Call Logs (showing {len(logs_sample)} of {len(tool_call_logs)})\n\n"
        f"```json\n{logs_json}\n```\n\n"
        f"Analyse these tool call logs against the retrieved policies. "
        f"Identify any compliance violations, anomalous patterns, or security risks. "
        f"For each finding, cite the specific policy. "
        f"This is analysis iteration {iteration + 1}."
    )

    messages_for_llm = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # Add prior conversation messages if this is a continuation loop
    prior_messages: list[Any] = state.get("messages", [])
    if iteration > 0 and prior_messages:
        # Insert prior AI analysis messages for context
        for msg in prior_messages[-4:]:  # last 2 turns
            if isinstance(msg, AIMessage):
                messages_for_llm.insert(-1, {"role": "assistant", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                messages_for_llm.insert(-1, {"role": "user", "content": msg.content})

    try:
        response = await litellm.acompletion(
            model=_BEDROCK_MODEL,
            messages=messages_for_llm,
            max_tokens=4096,
            temperature=0.0,
        )
    except litellm.exceptions.APIConnectionError as exc:
        log.error("analyze_tool_calls.api_connection_error", error=str(exc))
        return {**state, "error": f"LLM API connection error: {exc}"}  # type: ignore[return-value]
    except litellm.exceptions.RateLimitError as exc:
        log.error("analyze_tool_calls.rate_limit", error=str(exc))
        return {**state, "error": f"LLM rate limit exceeded: {exc}"}  # type: ignore[return-value]
    except Exception as exc:
        log.error("analyze_tool_calls.unexpected_error", error=str(exc))
        return {**state, "error": f"LLM call failed: {exc}"}  # type: ignore[return-value]

    analysis_text: str = response.choices[0].message.content or ""
    log.info("analyze_tool_calls.complete", response_len=len(analysis_text))

    new_message = AIMessage(content=analysis_text)
    return {  # type: ignore[return-value]
        **state,
        "messages": state.get("messages", []) + [new_message],
        "iteration_count": iteration + 1,
    }


# ── Node: detect_violations ───────────────────────────────────────────────────

async def detect_violations(state: AgentState) -> AgentState:
    """Extract structured violation records from the LLM analysis output.

    Calls LiteLLM/Bedrock with a structured extraction prompt to parse
    violations from the natural-language analysis in state["messages"].
    Populates ``state["violations"]``.
    """
    log = logger.bind(node="detect_violations", agent=_CALLER_AGENT_ID)

    if state.get("error"):
        log.warning("detect_violations.skipped_due_to_error")
        return state  # type: ignore[return-value]

    messages: list[Any] = state.get("messages", [])
    if not messages:
        log.warning("detect_violations.no_messages")
        return {**state, "violations": []}  # type: ignore[return-value]

    # Take the last AI message (the analysis)
    analysis_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            analysis_text = msg.content
            break

    if not analysis_text:
        return {**state, "violations": []}  # type: ignore[return-value]

    extraction_prompt = (
        "You are a structured data extractor. Given the following security analysis text, "
        "extract all policy violations into a JSON array. "
        "Each violation must have these fields: "
        "tool (string), agent_id (string or null), timestamp (string or null), "
        "severity (CRITICAL|HIGH|MEDIUM|LOW|INFO), code (string), "
        "description (string), policy_citation (string), raw_log_ref (string or null). "
        "Return ONLY a valid JSON array, no explanation text.\n\n"
        f"Analysis text:\n\n{analysis_text}"
    )

    try:
        response = await litellm.acompletion(
            model=_BEDROCK_MODEL,
            messages=[
                {"role": "system", "content": "You extract structured JSON from security analysis text."},
                {"role": "user", "content": extraction_prompt},
            ],
            max_tokens=2048,
            temperature=0.0,
        )
    except Exception as exc:
        log.error("detect_violations.llm_error", error=str(exc))
        # Non-fatal: return empty violations rather than failing the whole graph
        return {**state, "violations": []}  # type: ignore[return-value]

    raw_json: str = response.choices[0].message.content or "[]"

    # Strip potential markdown fences
    raw_json = raw_json.strip()
    if raw_json.startswith("```"):
        lines = raw_json.splitlines()
        raw_json = "\n".join(lines[1:-1]) if len(lines) > 2 else "[]"

    violations: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw_json)
        if isinstance(parsed, list):
            violations = parsed
        elif isinstance(parsed, dict) and "violations" in parsed:
            violations = parsed["violations"]
    except json.JSONDecodeError as exc:
        log.warning("detect_violations.json_parse_error", error=str(exc), raw=raw_json[:200])

    log.info("detect_violations.complete", violations_found=len(violations))
    return {**state, "violations": violations}  # type: ignore[return-value]


# ── Node: generate_report ─────────────────────────────────────────────────────

async def generate_report(state: AgentState) -> AgentState:
    """Generate a Markdown compliance report with policy citations.

    Uses the violations list, retrieved documents, and analysis messages
    to produce a structured, citable compliance report.
    Populates ``state["compliance_report"]``.
    """
    log = logger.bind(node="generate_report", agent=_CALLER_AGENT_ID)

    if state.get("error"):
        log.warning("generate_report.skipped_due_to_error")
        return state  # type: ignore[return-value]

    violations: list[dict[str, Any]] = state.get("violations", [])
    retrieved_docs: list[dict[str, Any]] = state.get("retrieved_docs", [])
    task: str = state.get("task", "")
    tool_call_logs: list[dict[str, Any]] = state.get("tool_call_logs", [])

    # Severity counts
    severity_counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for v in violations:
        sev = v.get("severity", "INFO").upper()
        if sev in severity_counts:
            severity_counts[sev] += 1

    # Citations summary
    citations_used: list[str] = list({
        v.get("policy_citation", "") for v in violations if v.get("policy_citation")
    })

    report_prompt = (
        f"Generate a professional compliance audit report in Markdown format.\n\n"
        f"**Audit Task:** {task}\n\n"
        f"**Scope:** {len(tool_call_logs)} tool call log records analysed\n\n"
        f"**Violations Found:** {len(violations)} "
        f"({severity_counts['CRITICAL']} CRITICAL, {severity_counts['HIGH']} HIGH, "
        f"{severity_counts['MEDIUM']} MEDIUM, {severity_counts['LOW']} LOW)\n\n"
        f"**Violations Detail (JSON):**\n```json\n"
        f"{json.dumps(violations, indent=2, default=str)}\n```\n\n"
        f"**Policy Citations Used:** {', '.join(citations_used) or 'None'}\n\n"
        f"**Retrieved Policy Excerpts:**\n"
        + "\n\n".join(
            f"- **{d.get('citation', d.get('source', 'unknown'))}**: {d.get('content', '')[:300]}..."
            for d in retrieved_docs[:5]
        )
        + "\n\nGenerate a report with these sections:\n"
        "1. Executive Summary\n"
        "2. Audit Scope and Methodology\n"
        "3. Findings Table (tool | agent | timestamp | severity | description | policy citation)\n"
        "4. Detailed Findings (one subsection per CRITICAL/HIGH violation)\n"
        "5. Risk Assessment\n"
        "6. Recommended Remediation Steps\n"
        "7. Appendix: Policy References\n\n"
        "Cite every finding with the exact policy document. Use Markdown tables and headings."
    )

    try:
        response = await litellm.acompletion(
            model=_BEDROCK_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": report_prompt},
            ],
            max_tokens=8192,
            temperature=0.0,
        )
    except Exception as exc:
        log.error("generate_report.llm_error", error=str(exc))
        return {**state, "error": f"Report generation failed: {exc}"}  # type: ignore[return-value]

    report: str = response.choices[0].message.content or ""
    log.info("generate_report.complete", report_len=len(report))
    return {**state, "compliance_report": report}  # type: ignore[return-value]


# ── Conditional edge: should_continue ─────────────────────────────────────────

def should_continue(state: AgentState) -> Literal["generate_report", "analyze_tool_calls"]:
    """Decide whether to loop back for deeper analysis or proceed to report generation.

    Returns:
        ``"generate_report"`` if the iteration limit is reached, no violations
        require deeper analysis, or an error has occurred.
        ``"analyze_tool_calls"`` to run another analysis iteration.
    """
    if state.get("error"):
        return "generate_report"

    iteration: int = state.get("iteration_count", 0)
    max_iterations: int = state.get("max_iterations", 5)

    if iteration >= max_iterations:
        return "generate_report"

    # Check if there are CRITICAL/HIGH violations that might warrant deeper analysis
    violations: list[dict[str, Any]] = state.get("violations", [])
    critical_high = [
        v for v in violations if v.get("severity", "").upper() in ("CRITICAL", "HIGH")
    ]

    # Only loop if we found high-severity violations and haven't hit the cap
    if critical_high and iteration < max_iterations:
        return "analyze_tool_calls"

    return "generate_report"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_mcp_auditor_graph() -> StateGraph:
    """Assemble and compile the mcp-auditor LangGraph StateGraph.

    Graph topology::

        START
          -> retrieve_policies
          -> analyze_tool_calls
          -> detect_violations
          -> [should_continue]
               "generate_report"    -> generate_report -> END
               "analyze_tool_calls" -> analyze_tool_calls (loop)

    Returns:
        A compiled LangGraph :class:`StateGraph` ready for ``.ainvoke()``.
    """
    builder: StateGraph = StateGraph(AgentState)

    # Register nodes
    builder.add_node("retrieve_policies", retrieve_policies)
    builder.add_node("analyze_tool_calls", analyze_tool_calls)
    builder.add_node("detect_violations", detect_violations)
    builder.add_node("generate_report", generate_report)

    # Static edges
    builder.add_edge(START, "retrieve_policies")
    builder.add_edge("retrieve_policies", "analyze_tool_calls")
    builder.add_edge("analyze_tool_calls", "detect_violations")

    # Conditional edge from detect_violations
    builder.add_conditional_edges(
        "detect_violations",
        should_continue,
        {
            "generate_report": "generate_report",
            "analyze_tool_calls": "analyze_tool_calls",
        },
    )

    builder.add_edge("generate_report", END)

    return builder.compile()


# Module-level compiled graph instance
mcp_auditor_graph = build_mcp_auditor_graph()

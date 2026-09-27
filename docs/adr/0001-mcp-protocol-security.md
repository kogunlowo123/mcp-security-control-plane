# ADR-0001: MCP Protocol Security Architecture

**Status:** Accepted  
**Date:** 2026-09-27  
**Deciders:** @kogunlowo123  
**Superseded by:** N/A  
**Supersedes:** N/A

---

## Context and Problem Statement

The Model Context Protocol (MCP) is an open protocol that standardizes how AI agents communicate with external tools and data sources. An MCP server exposes a set of "tools" — callable functions that an AI agent can invoke to read files, query databases, call APIs, execute shell commands, and more. The agent sends a JSON-RPC request with a tool name and arguments; the server executes the operation and returns a result.

The protocol itself does not define authorization, auditing, rate limiting, or anomaly detection. In its base form, any client that can reach an MCP server can call any tool with any arguments. This creates a significant security surface for enterprise deployments where:

- Multiple agents with different trust levels and task scopes share MCP server infrastructure
- MCP tool calls can cause real-world side effects (file writes, database mutations, API calls that cost money or trigger downstream business processes)
- Compromised or misconfigured agents can exploit MCP servers to exfiltrate data, escalate privileges, or cause service disruptions
- Compliance requirements (SOC 2, ISO 27001, NIST AI RMF) mandate auditability of all actions taken by automated systems on enterprise resources

We need an architectural approach that adds comprehensive security controls to MCP without requiring changes to existing MCP servers or agent implementations.

---

## Decision Drivers

1. **Transparency:** Security controls must not require modifications to existing MCP servers. Servers should remain unaware of the control plane.
2. **Completeness:** Every tool call — whether allowed, denied, or rate-limited — must produce an audit record.
3. **Latency:** The control plane must add less than 20ms (p99) of overhead to tool-call authorization in the steady state.
4. **Separation of concerns:** Policy definition, policy evaluation, and policy enforcement must be independently deployable and versioned.
5. **Auditability:** Audit records must be tamper-evident, long-lived (7 years), and queryable by compliance tooling.
6. **Operator autonomy:** Operators must be able to modify policies without code changes or deployments.

---

## Considered Options

### Option A: Sidecar proxy per MCP server

Deploy a sidecar container next to each MCP server. The sidecar intercepts MCP JSON-RPC requests on the wire, evaluates them against a local policy cache, and either forwards them to the MCP server or returns a denial.

**Pros:**
- Zero changes to MCP server code
- Low latency (sidecar is co-located with the MCP server)
- Failure of the sidecar can be configured to fail-open or fail-closed per server

**Cons:**
- Operational complexity scales with the number of MCP servers (N sidecars to manage)
- Policy consistency is harder to guarantee when policy caches can diverge
- No central view of cross-server call patterns needed for anomaly detection
- Audit records must be aggregated from N independent sidecars

### Option B: Centralized control plane with agent-side SDK

Agents use a thin SDK wrapper around their MCP client. Before every tool call, the SDK calls the central control plane's `/v1/authorize` endpoint. If authorized, the SDK proceeds with the actual MCP call; otherwise it raises a controlled exception.

**Pros:**
- Single operational unit to manage and scale
- All audit records naturally land in one place, enabling cross-server anomaly detection
- Policy changes take effect immediately for all agents
- No changes required to MCP servers

**Cons:**
- Requires agents to use the SDK; non-SDK agents can bypass the control plane
- Single point of failure (mitigated by multi-AZ deployment and circuit breakers)
- Adds a network hop for every tool call

### Option C: Network-layer transparent proxy

A transparent proxy (e.g., Envoy with Lua filters) intercepts all TCP traffic to MCP server endpoints. Policy evaluation runs inside the filter chain.

**Pros:**
- Completely transparent to both agents and MCP servers
- Impossible to bypass (at the network level) with correct routing rules

**Cons:**
- Extremely complex to operate at enterprise scale
- Envoy Lua filter limitations make complex policy logic (embedding-based anomaly detection, multi-hop call analysis) impractical
- Deep packet inspection of MCP JSON-RPC streams is fragile against protocol evolution
- Network-layer controls do not have access to agent identity context that lives above the transport layer

---

## Decision

**Option B — Centralized control plane with agent-side SDK** is selected as the primary architecture.

Option A (sidecar proxy) is retained as a defense-in-depth layer for MCP servers that cannot be reached through the SDK path (legacy integrations, third-party servers). When deployed in sidecar mode, the sidecar forwards all requests to the central control plane for policy evaluation and uses a local allow-cache for sub-10ms enforcement in the common case.

Option C is rejected. The operational complexity and fragility of deep packet inspection outweigh the bypass-prevention benefit, especially since the SDK path combined with network-layer controls (security groups, VPC routing) provides adequate coverage for the enterprise deployment model.

---

## Consequences

### Positive

- A single, auditable code path handles all MCP security decisions
- Cross-server and cross-session anomaly detection is possible because all events flow through one system
- Policy updates are atomic: all agents see the new policy on the next cache refresh (default: 60 seconds)
- The SDK provides structured hooks for observability (traces, metrics, logs) at the call site

### Negative

- Agents must integrate the SDK. This is a migration cost for existing agent implementations.
- The control plane is on the critical path for every tool call. Multi-AZ deployment and circuit breakers are mandatory, not optional.
- The 60-second policy cache refresh window means newly denied capabilities may be exercised for up to 60 seconds after a policy change. Emergency policy changes must be accompanied by a cache invalidation signal.

### Neutral

- The SDK is thin by design (< 500 lines of Python). It is not a framework and imposes no opinions on agent architecture.
- The centralized architecture creates a natural integration point for future capabilities (cross-agent session correlation, automated policy generation from behavioral baselines).

---

## Compliance Notes

This architecture directly addresses the following control requirements:

- **SOC 2 CC6.1** — Logical and physical access controls: the control plane enforces access authorization for every tool call
- **SOC 2 CC7.2** — Monitoring for unauthorized access: anomaly detection and audit log fulfill this requirement
- **NIST AI RMF GOVERN 1.3** — Organizational risk tolerances for AI: policies express organizational tolerance as code
- **NIST AI RMF MEASURE 2.5** — AI risks and impacts are measured: the audit log and anomaly scoring provide the measurement substrate

---

## References

- [Model Context Protocol Specification](https://spec.modelcontextprotocol.io/)
- [Open Policy Agent Documentation](https://www.openpolicyagent.org/docs/latest/)
- [NIST AI Risk Management Framework](https://airc.nist.gov/RMF_Overview)
- ADR-0002: Per-Call Authorization Design

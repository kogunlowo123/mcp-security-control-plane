# ADR-0002: Per-Call Authorization Design

**Status:** Accepted  
**Date:** 2026-09-27  
**Deciders:** @kogunlowo123  
**Superseded by:** N/A  
**Supersedes:** N/A  
**Related:** ADR-0001 (MCP Protocol Security Architecture)

---

## Context and Problem Statement

ADR-0001 established that the MCP Security Control Plane will use a centralized control plane with an agent-side SDK. This ADR addresses the specific design of the authorization model that the control plane enforces.

The central question is: **what is the unit of authorization, and what information must be present at decision time?**

Several approaches are possible:

- **Session-level authorization:** The agent authenticates once at session start and is permitted to use a fixed set of tools for the duration of the session
- **Per-call authorization:** Every individual tool call is evaluated against current policies at the moment it is made
- **Task-level authorization:** The agent declares its intended task at session start; the control plane pre-approves a set of call patterns consistent with that task

These approaches have different security postures, latency characteristics, and operational complexity.

A secondary question is: **how are authorization policies expressed?** The options range from simple ACLs to full Rego policies, and the choice affects both expressiveness and operational overhead.

---

## Decision Drivers

1. **Defense depth:** Authorization decisions must be resistant to session token theft, replay attacks, and gradual privilege escalation over a long session
2. **Real-time policy enforcement:** A policy change (e.g., revoking an agent's access to a database tool following an incident) must take effect within 60 seconds for all in-flight sessions
3. **Expressiveness:** Policies must support conditions beyond simple tool-name ACLs: argument value patterns, time-of-day restrictions, resource-level permissions, and cross-call context
4. **Latency budget:** Per-call authorization must complete in under 20ms at the p99 (see ADR-0001)
5. **Auditability:** Every authorization decision — the input, the matched rule, and the outcome — must be recorded
6. **Operator usability:** Policy authors should not need to learn a Turing-complete language to write common authorization rules

---

## Considered Options

### Option A: Session-level authorization only

The agent authenticates once, receives a session token listing permitted tools, and that list is checked (locally, without a network call) on every tool invocation for the session lifetime.

**Pros:**
- Zero latency overhead after session creation
- No single-point-of-failure concern for the authorization path

**Cons:**
- Revocations require session termination; there is no way to revoke a specific tool within an active session
- No per-call context available for conditional policies (e.g., "allow database reads but not writes after 18:00")
- Compromised session tokens give attackers the full tool list for the session lifetime
- Argument-level controls are impossible

### Option B: Per-call authorization with OPA

Every tool call request is forwarded to an Open Policy Agent (OPA) instance. OPA evaluates the request against the current policy bundle and returns `allow` or `deny`. The control plane records the decision and its rationale.

**Pros:**
- Policies can incorporate any attribute of the request: agent identity, tool name, arguments, time, session history
- Policy changes take effect on the next OPA bundle refresh (60-second default)
- OPA is an industry-standard, well-audited policy engine with first-class enterprise tooling
- Rego policies are version-controlled, testable, and composable
- Deny decisions are recorded with the matched rule, providing fine-grained audit evidence

**Cons:**
- Every call requires a network round-trip to OPA (or an in-process OPA library call)
- Rego has a learning curve; complex policies require experience with the language

**Mitigation for latency:** OPA is deployed as a sidecar in the same ECS task as the control plane service. In-process OPA evaluation (via `opa-python-client`'s embedded evaluation path) eliminates the network hop for the common case, keeping the authorization overhead under 5ms p99.

### Option C: Task-declaration authorization

At session creation, the agent provides a natural-language description of its intended task. The control plane uses an LLM (Bedrock Claude) to translate this into a set of permitted call patterns, which are stored and checked against actual calls.

**Pros:**
- Natural-language policies are accessible to non-technical operators
- The LLM can infer implicit permissions from task descriptions

**Cons:**
- LLM-generated policies are non-deterministic; the same task description may produce different allowed call sets across runs
- LLM latency (1–5 seconds) makes this unsuitable for the real-time authorization path
- Auditors cannot rely on human-readable policies when LLM-generated permissions are used; compliance evidence is weaker
- LLM jailbreaking could be used to obtain overly permissive policy interpretations at session creation time

### Option D: Hybrid (session pre-authorization + per-call OPA check)

At session creation, a coarse-grained allowlist of tool names is established from the agent's declared scope. On each call, OPA performs a fine-grained check within the scope of the pre-authorized tools. Calls to tools outside the session allowlist are rejected without an OPA evaluation.

**Pros:**
- The session-level check acts as a fast pre-filter, reducing OPA evaluations for clearly out-of-scope calls
- Provides two independent layers of defense

**Cons:**
- Adds complexity without proportional security benefit: OPA evaluations are already fast (< 5ms in-process)
- Two authorization layers can create inconsistency if their models diverge (e.g., session allowlist grants tool X, OPA policy denies it — which takes precedence?)

---

## Decision

**Option B — Per-call authorization with OPA** is the primary authorization mechanism.

**Option D** is adopted as an optimization layer only: the session scope token acts as a fast pre-filter (reject calls to tools not in the session scope without calling OPA), but all calls within the session scope undergo a full OPA evaluation. The session scope is a strict subset of the agent's maximum configured scope; it does not add permissions, it only narrows them.

This means the authorization path for every tool call is:

```
1. Validate scope token (cryptographic signature check, expiry check, tool-name membership check)
   → If invalid or tool not in scope: deny immediately, record to audit log
   → If valid and tool in scope: continue

2. Evaluate OPA policy bundle against full request context
   (agent_id, session_id, tool_name, arguments, timestamp, session_history_summary)
   → If deny: record denial with matched rule to audit log, return deny
   → If allow: continue

3. Evaluate rate limits (Redis token bucket)
   → If over limit: record rate-limit event to audit log, return deny with retry-after
   → If within limits: continue

4. Score anomaly (async, non-blocking — does not gate the authorization decision)
   → If score exceeds threshold: emit anomaly alert (SNS), record score to audit log

5. Return allow decision with request_id and audit_record_id
```

Steps 1–3 are synchronous and on the critical path. Step 4 is fire-and-forget; a high anomaly score does not block the current call but may trigger a quarantine for subsequent calls.

---

## Policy Expression

Authorization policies are written in OPA Rego. The control plane ships with a baseline policy bundle in `security/policies/` that covers the most common cases. Operators extend or override the baseline using their own policy files.

Policy structure:

```
security/policies/
├── baseline/
│   ├── filesystem.rego         # Controls for filesystem MCP server tools
│   ├── database.rego           # Controls for database MCP server tools
│   ├── shell.rego              # Controls for shell execution tools (high-risk default: deny-all)
│   └── rate_limits.rego        # Rate limit policy definitions
├── agents/
│   ├── data-analyst.rego       # Policy for data-analyst agent family
│   └── report-writer.rego      # Policy for report-writer agent family
└── overrides/
    └── README.md               # Operator override instructions
```

Policies are versioned in git and deployed to OPA via an S3 bundle. The control plane polls for bundle updates every 60 seconds. Emergency policy changes can be force-pushed and cache-invalidated via `POST /v1/admin/policies/refresh`.

---

## Consequences

### Positive

- Every authorization decision is backed by a named, version-controlled policy rule, enabling precise compliance reporting
- Policies can reference any request attribute, enabling rich conditional controls without code changes
- OPA policy testing (via `opa test`) can be run in CI, making policy correctness checkable before deployment
- The two-layer model (scope token + OPA) provides defense in depth: compromising one layer does not compromise the other

### Negative

- Teams must learn Rego to write custom policies. The baseline bundle and operator guide reduce this burden, but it remains a learning investment.
- In-process OPA evaluation requires bundling the OPA library into the control plane container, adding ~50MB to the image size.
- The 60-second bundle refresh window creates a policy propagation delay. For emergency revocations, operators must use the `/v1/admin/policies/refresh` endpoint and verify effect.

### Neutral

- Argument-level policy conditions (e.g., "deny filesystem.read_file if path starts with /etc/") require the MCP SDK to forward argument values to the control plane. By default, arguments are hashed before storage. Policies that inspect argument values operate on pre-hash argument values in-memory during OPA evaluation; they are never stored in plain text.

---

## References

- [Open Policy Agent — The Rego Language](https://www.openpolicyagent.org/docs/latest/policy-language/)
- [OPA Bundle API](https://www.openpolicyagent.org/docs/latest/management-bundles/)
- [NIST SP 800-162 — Guide to Attribute-Based Access Control](https://csrc.nist.gov/publications/detail/sp/800-162/final)
- ADR-0001: MCP Protocol Security Architecture

# Runbook: MCP Security Violation Response

**Version:** 1.0  
**Last Updated:** 2026-09-27  
**Owner:** @kogunlowo123  
**Review Cycle:** Quarterly  
**Severity Levels Covered:** P1 (Critical), P2 (High), P3 (Medium)

---

## Overview

This runbook covers the response procedure when the MCP Security Control Plane detects or reports a security violation involving MCP tool calls made by AI agents. Violations include:

- Policy denials indicating an agent attempted an unauthorized tool call
- Anomaly alerts indicating behavioral deviation from an established baseline
- Scope violations: an agent presenting a forged, replayed, or out-of-scope token
- Rate limit exhaustion indicating possible denial-of-service or runaway agents
- Quarantine triggers: automatic quarantine of agents exceeding burst limits

This runbook does **not** cover:
- Vulnerabilities in the control plane itself (see [SECURITY.md](../../SECURITY.md))
- AWS infrastructure incidents (see the infrastructure runbooks in `docs/runbooks/aws/`)
- General on-call escalation procedures (see the on-call guide in the team wiki)

---

## Severity Classification

| Severity | Description | Response Time | Example |
|----------|-------------|---------------|---------|
| P1 Critical | Active exploitation or confirmed data exfiltration attempt | Immediate (< 15 min) | Agent successfully reading `/etc/` files, high-volume data query to production DB |
| P2 High | Strong indicator of compromise; automatic quarantine triggered | < 30 minutes | Anomaly score > 0.80 on a privileged agent, scope token replay detected |
| P3 Medium | Anomalous activity requiring investigation; no active harm confirmed | < 4 hours | Anomaly score 0.35–0.80, repeated policy denials from a single agent |
| P4 Low | Expected policy denials, informational alerts, baseline drift | Next business day | New agent below baseline threshold, first-time policy denial |

---

## Contacts

| Role | Contact | When to Involve |
|------|---------|----------------|
| On-call engineer | PagerDuty rotation | All P1 and P2 |
| Platform owner | @kogunlowo123 | All P1; P2 if on-call cannot resolve in 30 min |
| Security team | Internal security channel | All P1; P2 involving data exfiltration |
| Legal / compliance | Per internal escalation matrix | P1 involving PII or regulated data |
| Agent team owner | Per agent family registry | All violations involving their agent family |

---

## Step 1: Initial Triage

### 1.1 Confirm the Alert

Alerts arrive via PagerDuty (anomaly threshold exceeded, quarantine triggered) or CloudWatch Alarm (policy denial rate spike, rate-limit exhaustion). Before acting, confirm the alert is real and not a false positive from a monitoring glitch.

```bash
# Retrieve the anomaly alert details
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/anomalies/$ALERT_ID

# Sample response fields to check:
# anomaly_score: float (0.0 – 1.0; higher = more anomalous)
# agent_id: the agent that triggered the alert
# tool_name: the tool call that was flagged
# session_id: the active session
# bedrock_explanation: LLM-generated explanation of the anomaly
# first_seen_at, last_seen_at: alert time range
```

```bash
# Check recent policy denials for the agent
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://mcp-security.internal/v1/audit?agent_id=$AGENT_ID&policy_decision=deny&limit=50"
```

### 1.2 Assign Initial Severity

Use the table in [Severity Classification](#severity-classification). When in doubt, assign the higher severity and downgrade after investigation.

Record the following in the incident tracking system before proceeding:
- Alert ID and source (anomaly / policy denial spike / quarantine trigger)
- Agent ID and agent family
- Time of first alert
- Initial severity assessment
- On-call engineer name

---

## Step 2: Contain the Threat

Containment steps depend on severity. **Do not skip containment to investigate first** — stopping active harm takes priority over understanding it.

### P1: Quarantine the agent immediately

```bash
# Quarantine the agent — all subsequent tool calls will be blocked
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "P1 security violation — runbook mcp-violation-response", "incident_id": "$INCIDENT_ID"}' \
  https://mcp-security.internal/v1/admin/agents/$AGENT_ID/quarantine

# Verify quarantine is in effect
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/sessions/$SESSION_ID
# "status" should be "quarantined"
```

Notify the agent team owner that their agent has been quarantined. Provide the incident ID. Do not share raw audit log details outside the security team until the investigation is complete.

### P2: Quarantine the agent and terminate the session

```bash
# Quarantine the agent
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "P2 anomaly alert — pending investigation", "incident_id": "$INCIDENT_ID"}' \
  https://mcp-security.internal/v1/admin/agents/$AGENT_ID/quarantine

# Terminate the active session to revoke the scope token
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/sessions/$SESSION_ID
```

### P3: Monitor without quarantine

For P3, containment is optional. If the anomaly pattern suggests active escalation attempt (repeated denials on high-privilege tools, argument patterns indicating path traversal), quarantine pre-emptively. Otherwise, increase monitoring:

```bash
# Lower the anomaly alert threshold for this specific agent to ensure
# any further deviation triggers an immediate P2 alert
# (This is a configuration change — update .env or SSM Parameter Store)
# ANOMALY_ALERT_THRESHOLD_OVERRIDE_<AGENT_ID>=0.20
```

---

## Step 3: Investigate

### 3.1 Retrieve Full Call History for the Session

```bash
# Get all tool calls for the session (most recent first)
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://mcp-security.internal/v1/audit?session_id=$SESSION_ID&limit=500&order=desc"
```

For each suspicious call, record:
- `request_id` and `timestamp`
- `tool_name` and `tool_server`
- `policy_decision` (allow / deny / rate_limited)
- `anomaly_score`
- `arguments_sha256` (if raw arguments were captured, see 3.2)

### 3.2 Retrieve Raw Arguments (if argument capture is enabled)

If `AUDIT_ARGUMENT_CAPTURE=true` is configured for this environment, raw arguments are stored in the audit record. Access them only if needed for the investigation, and only through the admin API. All access to raw arguments is itself audited.

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/audit/$RECORD_ID
# "arguments" field will be present if capture was enabled
```

If argument capture is not enabled, hash comparison can be used:
```bash
# Compute SHA-256 of a suspected argument string
echo -n '{"path": "/etc/passwd"}' | sha256sum
# Compare against the arguments_sha256 in the audit record
```

### 3.3 Run the Tool Call Inspector Agent

The `tool-call-inspector` agent family performs automated forensic analysis:

```bash
# From a secure workstation with the agent SDK installed
python -m services.agents.tool_call_inspector \
  --session-id $SESSION_ID \
  --focus-request-id $SUSPICIOUS_REQUEST_ID \
  --incident-id $INCIDENT_ID \
  --output-format markdown > /tmp/inspector-report-$INCIDENT_ID.md
```

The inspector will:
1. Reconstruct the conversation context around the suspicious call
2. Perform semantic analysis of argument patterns
3. Analyze the full call chain for privilege escalation indicators
4. Produce a verdict with confidence score and recommended action

Review the report and add it to the incident record.

### 3.4 Examine the Bedrock Anomaly Explanation

The anomaly alert record contains a `bedrock_explanation` field with a natural-language explanation generated by Amazon Bedrock Claude claude-sonnet-4-6. This explanation describes what made the flagged call deviate from the agent's baseline.

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/anomalies/$ALERT_ID \
  | jq '.bedrock_explanation'
```

Treat this as an analysis aid, not a definitive verdict. It may miss context the human investigator has.

### 3.5 Check for Lateral Movement

If the investigation suggests the agent may have been compromised, check whether the same scope token or agent identity was used across other sessions:

```bash
# List all sessions for the agent
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://mcp-security.internal/v1/audit?agent_id=$AGENT_ID&limit=1000&order=desc" \
  | jq '[.records[] | select(.session_id != "$SESSION_ID") | .session_id] | unique'

# For each other session ID, check for anomaly alerts
for SID in $OTHER_SESSION_IDS; do
  curl -H "Authorization: Bearer $ADMIN_TOKEN" \
    "https://mcp-security.internal/v1/anomalies?session_id=$SID"
done
```

---

## Step 4: Assess Impact

Document the following in the incident record:

1. **What tools were successfully called** (policy_decision = allow) during the suspicious activity window
2. **What data was potentially accessed or exfiltrated** — cross-reference tool names against the MCP server's data classification registry
3. **Whether any MCP servers with write capabilities were called** — file writes, database writes, API calls with side effects
4. **Whether any other agents or sessions share a common orchestrator** that could have been used as an entry point
5. **Timeline:** first suspicious call, first anomaly alert, containment action, time between alert and containment

If any regulated data (PII, PHI, financial records) may have been accessed, escalate to legal and compliance immediately per the data breach notification procedure.

---

## Step 5: Remediate

### 5.1 Rotate Credentials and Tokens

If agent credentials were potentially compromised:

```bash
# Revoke all active sessions for the agent (terminates all scope tokens)
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/admin/agents/$AGENT_ID/revoke-all-sessions

# Rotate the agent's identity credentials
# (Procedure depends on how agent credentials are issued — see identity/README.md)
```

### 5.2 Update Policies to Prevent Recurrence

If the investigation reveals a policy gap (the agent was able to make calls that should have been denied by policy), draft a policy fix:

```bash
# In a local dev environment, write the new Rego policy rule
# Then test it against the audit records from the incident:
opa test security/policies/ -v

# Submit as a PR with the incident ID in the PR description
# The PR must include: the new policy rule, the test cases, and the incident ID
```

For urgent fixes, policies can be pushed to OPA without a full deployment:

```bash
# Force-refresh the OPA bundle after pushing to S3
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/admin/policies/refresh
```

### 5.3 Lift Quarantine (if appropriate)

Quarantine should be lifted only after:
- The root cause is understood
- Policy gaps are fixed
- Agent credentials are rotated (if compromise is suspected)
- The agent team owner has reviewed and acknowledged the findings

```bash
# Lift quarantine
curl -X DELETE \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Investigation complete, root cause addressed", "incident_id": "$INCIDENT_ID"}' \
  https://mcp-security.internal/v1/admin/agents/$AGENT_ID/quarantine
```

---

## Step 6: Post-Incident Actions

### 6.1 Mark Alert as Resolved

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resolution": "contained", "incident_id": "$INCIDENT_ID"}' \
  https://mcp-security.internal/v1/anomalies/$ALERT_ID/acknowledge
```

If the alert was a false positive:
```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Explained by legitimate task change — agent onboarded new data source", "incident_id": "$INCIDENT_ID"}' \
  https://mcp-security.internal/v1/anomalies/$ALERT_ID/false-positive
```

Marking as false positive triggers a baseline recalibration for the agent; the flagged behavior will be incorporated into the baseline.

### 6.2 Write a Post-Incident Review

For P1 and P2 incidents, a post-incident review (PIR) is required within 5 business days. The PIR must cover:
- Incident timeline (detection to containment to resolution)
- Root cause analysis
- Impact assessment
- Actions taken and their effectiveness
- Preventive measures to avoid recurrence
- Runbook improvements (update this document if a step was missing or unclear)

### 6.3 Update the Runbook

If this runbook was missing a step, contained an error, or could be improved based on this incident, submit a PR with the improvement. Tag the PR with `docs` and reference the incident ID.

---

## Appendix: Quick Reference Commands

```bash
# Set environment variables for the commands in this runbook
export ADMIN_TOKEN="<your admin token>"
export AGENT_ID="agent-abc123"
export SESSION_ID="sess-xyz789"
export ALERT_ID="alert-001"
export RECORD_ID="aud-9z8y7x6w"
export INCIDENT_ID="INC-20260927-001"

# Quarantine agent
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"reason\": \"Security incident $INCIDENT_ID\"}" \
  https://mcp-security.internal/v1/admin/agents/$AGENT_ID/quarantine

# Lift quarantine
curl -X DELETE -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/admin/agents/$AGENT_ID/quarantine

# Get agent's recent audit records
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://mcp-security.internal/v1/audit?agent_id=$AGENT_ID&limit=100&order=desc"

# Get anomaly alert with Bedrock explanation
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/anomalies/$ALERT_ID

# Force OPA policy refresh
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://mcp-security.internal/v1/admin/policies/refresh

# Reset rate-limit counters for an agent
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"$AGENT_ID\"}" \
  https://mcp-security.internal/v1/admin/rate-limits/reset
```

---

*This runbook is a living document. When you use it, improve it.*

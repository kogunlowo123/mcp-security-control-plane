# Changelog

All notable changes to the MCP Security Control Plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions are tagged in git. Security fixes are marked with **[SECURITY]** and always include a CVE or internal advisory reference.

---

## [Unreleased]

Changes that are merged to `main` but not yet released will appear here until a release is cut.

---

## [0.1.0] — 2026-09-27

Initial release of the MCP Security Control Plane. This release establishes the foundational security governance layer for MCP tool calls made by AI agents.

### Added

#### Core Platform
- FastAPI 0.111 application with async request handling, structured logging middleware, and OpenTelemetry tracing
- Health (`/health`) and readiness (`/readiness`) endpoints verifying connectivity to Aurora, Redis, and OPA
- Request ID propagation across all service calls for end-to-end traceability
- Graceful shutdown with in-flight request draining

#### Authorization Engine
- Per-call authorization via Open Policy Agent (OPA) with policies expressed in Rego
- Policy bundle loader that pulls from S3 on startup and refreshes on configurable interval (default: 60 seconds)
- Principal resolution: agent ID, session ID, and user context extracted from signed JWT claims
- `POST /v1/authorize` endpoint returning `allow`/`deny` with the matched policy rule name and reason
- `POST /v1/authorize/dry-run` endpoint for policy testing without audit log side effects
- `POST /v1/policies/evaluate` endpoint for hypothesis evaluation without a live session

#### Scope Token Service
- Ed25519 scope tokens issued at session creation with configurable expiry (minimum 60 seconds, maximum 8 hours)
- Scope claims bound to agent identity, declared task description, and a set of permitted tool names
- Scope inheritance model: orchestrator agents may delegate a subset of their scope to sub-agents
- Token signing keys stored in AWS Secrets Manager; signing performed via KMS Sign API
- `POST /v1/sessions` — create session and issue scope token
- `DELETE /v1/sessions/{session_id}` — terminate session and revoke scope token
- `GET /v1/sessions/{session_id}` — retrieve session metadata

#### Rate Limiting
- Token-bucket rate limiting implemented in Redis with microsecond precision using Lua scripts for atomicity
- Limits configurable at four levels: agent, session, tool name, and target resource (evaluated in order; most restrictive wins)
- Burst allowance with configurable replenishment rate (`RATE_LIMIT_BURST_MULTIPLIER`, default 2.0)
- Automatic quarantine: agents exceeding burst limits three times within a rolling 5-minute window are quarantined and all subsequent calls are blocked pending human review
- Rate-limit headers returned on all `/v1/authorize` responses: `X-RateLimit-Remaining`, `X-RateLimit-Reset`

#### Audit Logging
- Immutable append-only audit log in Aurora PostgreSQL with database-level triggers blocking UPDATE and DELETE
- Structured record format: `request_id`, `timestamp`, `agent_id`, `session_id`, `tool_name`, `tool_server`, `arguments_sha256`, `policy_decision`, `matched_rule`, `anomaly_score`, `latency_ms`, `rate_limit_remaining`
- Full argument capture disabled by default; enabled via `AUDIT_ARGUMENT_CAPTURE=true` with highest data classification tier applied automatically
- Real-time forwarding of audit records to Amazon Kinesis Data Streams for downstream SIEM integration
- Asynchronous S3 archive job: records older than 90 days are exported to S3 in NDJSON format and removed from Aurora
- `GET /v1/audit` — query with filter, pagination, and time range
- `GET /v1/audit/{record_id}` — retrieve single record
- `GET /v1/audit/export` — streaming NDJSON export

#### Anomaly Detection
- Behavioral baseline per agent using Aurora pgvector: tool-call sequences are embedded via Amazon Bedrock Titan Embeddings V2 and stored as 1536-dimensional vectors
- Cosine similarity scoring on every authorized call against the agent's baseline (rolling 30-day window)
- Configurable alert threshold (`ANOMALY_ALERT_THRESHOLD`, default 0.35)
- Secondary semantic analysis for anomaly alerts using Amazon Bedrock Claude claude-sonnet-4-6: produces a natural-language explanation of why the call was flagged
- Alert delivery via Amazon SNS with PagerDuty and Slack webhook integrations
- `GET /v1/anomalies` — list recent alerts with pagination
- `GET /v1/anomalies/{alert_id}` — retrieve alert with Bedrock-generated explanation
- `POST /v1/anomalies/{alert_id}/acknowledge` — acknowledge alert
- `POST /v1/anomalies/{alert_id}/false-positive` — mark as false positive and trigger baseline recalibration

#### Agent Families (LangGraph)
- `mcp-auditor`: AuditCollector → PatternAnalyzer → ReportWriter; produces Markdown compliance reports from audit log data
- `tool-call-inspector`: ContextReconstructor → ArgumentSemanticAnalyzer → CallChainAnalyzer → VerdictWriter; performs forensic analysis of individual tool calls
- `scope-enforcer`: ScopeTokenIssuer → ScopeViolationDetector → ScopeDriftAnalyzer; manages scope token lifecycle and monitors for violations

#### Admin API (admin scope required)
- `POST /v1/admin/agents/{agent_id}/quarantine` — quarantine agent
- `DELETE /v1/admin/agents/{agent_id}/quarantine` — lift quarantine
- `POST /v1/admin/rate-limits/reset` — reset rate-limit counters
- `GET /v1/admin/metrics` — Prometheus-format operational metrics

#### Infrastructure (AWS CDK)
- `McpControlPlaneStack`: VPC with public/private/data subnet tiers across two AZs, ECS Fargate cluster, Application Load Balancer with WAF and Shield Standard
- `McpDataStack`: Aurora PostgreSQL 15 cluster with pgvector extension, ElastiCache Redis 7 cluster mode, automated backups with 35-day retention
- `McpObservabilityStack`: CloudWatch dashboards, X-Ray tracing, Kinesis Data Stream, SNS topic for anomaly alerts
- All AWS service calls via VPC endpoints (no public internet egress)
- KMS customer-managed key per data classification tier
- IAM roles following least-privilege principle with resource-level permissions

#### Documentation
- Architecture Decision Records: ADR-0001 (MCP Protocol Security), ADR-0002 (Per-Call Authorization)
- Runbook: MCP Security Violation Response
- Full API reference in README

### Known Limitations in 0.1.0

- Anomaly detection requires a minimum of 100 tool calls per agent before a meaningful baseline is established; new agents receive a grace period with elevated alert thresholds during baseline warm-up
- Scope inheritance is limited to one level of delegation (orchestrator → sub-agent); deeper chains are not yet supported and will be blocked by the scope enforcer
- The audit export endpoint does not yet support filtering; it exports all records in the specified time range
- Multi-tenancy (multiple organizations within one deployment) is not yet supported; each organization should deploy its own instance

[Unreleased]: https://github.com/kogunlowo123/mcp-security-control-plane/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kogunlowo123/mcp-security-control-plane/releases/tag/v0.1.0

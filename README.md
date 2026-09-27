# MCP Security Control Plane

> Enterprise-grade security governance, auditing, and enforcement for Model Context Protocol (MCP) tool calls made by AI agents.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Security Policy](https://img.shields.io/badge/Security-Policy-red.svg)](SECURITY.md)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Agent Families](#agent-families)
- [AWS Architecture](#aws-architecture)
- [Development Guide](#development-guide)
- [License](#license)

---

## Overview

The MCP Security Control Plane is an enterprise AI security platform that sits between AI agents and the MCP servers they call. Every tool invocation — file reads, database queries, API calls, shell commands — passes through the control plane for authorization, scope verification, rate limiting, and anomaly detection before it reaches the target MCP server.

The platform is designed for organizations deploying AI agents at scale who need:

- A centralized audit log of every tool call made by every agent
- Fine-grained authorization policies enforced at the per-call level
- Real-time anomaly detection to catch compromised or misbehaving agents
- Scope enforcement to prevent privilege escalation through chained tool calls
- Compliance artifacts for SOC 2, ISO 27001, and NIST AI RMF

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Agents / LLM Clients                  │
│  (LangGraph agents, AutoGen agents, custom LLM applications)    │
└───────────────────────────┬─────────────────────────────────────┘
                            │  MCP Tool Call Request
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MCP Security Control Plane                     │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │  Authorization  │  │  Scope Enforcer  │  │  Rate Limiter  │ │
│  │     Engine      │  │                  │  │                │ │
│  └────────┬────────┘  └────────┬─────────┘  └───────┬────────┘ │
│           │                    │                     │          │
│  ┌────────▼────────────────────▼─────────────────────▼────────┐ │
│  │                    Policy Decision Point                    │ │
│  └────────────────────────────┬────────────────────────────── ┘ │
│                               │                                  │
│  ┌────────────────────────────▼──────────────────────────────┐  │
│  │                   Audit & Anomaly Engine                   │  │
│  │  (Aurora pgvector · LiteLLM embeddings · Bedrock)         │  │
│  └────────────────────────────┬───────────────────────────── ┘  │
└───────────────────────────────┼─────────────────────────────────┘
                                │  Authorized + Audited Request
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       MCP Servers                               │
│  (filesystem, database, API gateways, shell, custom tools)      │
└─────────────────────────────────────────────────────────────────┘
```

The control plane is stateless at the request-handling tier. State — policy definitions, audit records, rate-limit counters, anomaly baselines — lives in Aurora PostgreSQL (with pgvector for embedding-based anomaly detection), Amazon ElastiCache for Redis (rate-limit counters and session state), and Amazon S3 (long-term audit archive).

---

## Key Features

### MCP Tool Call Authorization
- Per-call policy evaluation using Open Policy Agent (OPA) expressions
- Principal identity resolution (agent ID, session ID, user context)
- Resource-level permissions: allow/deny specific tool names, argument patterns, and target resources
- Policy-as-code: all authorization rules live in version-controlled YAML and are deployed through CI/CD
- Dry-run mode for policy testing without affecting live traffic

### Audit Logging
- Immutable, append-only audit log for every tool call (allowed, denied, and rate-limited)
- Structured log format: `{timestamp, request_id, agent_id, session_id, tool_name, arguments_hash, policy_decision, latency_ms, anomaly_score}`
- Arguments are hashed before storage; raw argument capture is opt-in and subject to data classification rules
- Real-time streaming to Amazon Kinesis Data Streams for SIEM integration
- 90-day hot storage in Aurora, 7-year cold archive in S3 Glacier

### Scope Enforcement
- Declarative scope definitions per agent family
- Scope tokens issued at session initialization and verified on every call
- Prevents scope creep from chained tool calls: agent A cannot pass elevated scope to agent B
- Scope inheritance model supports hierarchical agent topologies (orchestrator → sub-agents)

### Rate Limiting
- Token-bucket algorithm implemented in Redis with microsecond precision
- Limits configurable at the agent, session, tool, and resource levels
- Burst allowances with configurable replenishment rates
- Automatic circuit-breaker: agents exceeding burst limits are quarantined pending human review

### Anomaly Detection
- Embedding-based behavioral baseline using Aurora pgvector
- Each agent builds a behavioral profile from its historical tool-call sequence
- Cosine similarity scoring against the baseline detects deviations in real time
- AWS Bedrock (Claude claude-sonnet-4-6 / Titan) used for semantic analysis of suspicious argument patterns
- Configurable alert thresholds with PagerDuty / SNS integration

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.111+ |
| Language | Python 3.12 |
| Agent Orchestration | LangGraph 0.2+ |
| LLM Gateway | LiteLLM 1.40+ |
| Foundation Models | AWS Bedrock (Claude, Titan Embeddings) |
| Policy Engine | Open Policy Agent (OPA) via `opa-python-client` |
| Primary Database | Amazon Aurora PostgreSQL 15 + pgvector |
| Cache / Rate Limit | Amazon ElastiCache for Redis 7 |
| Audit Stream | Amazon Kinesis Data Streams |
| Long-term Archive | Amazon S3 + S3 Glacier |
| Secret Management | AWS Secrets Manager |
| Identity | AWS IAM + custom agent identity tokens |
| Infrastructure | AWS CDK (Python) |
| Container Runtime | AWS ECS Fargate |
| Service Mesh | AWS App Mesh |
| Observability | AWS X-Ray, CloudWatch, OpenTelemetry |
| CI/CD | GitHub Actions + AWS CodePipeline |

---

## Getting Started

### Prerequisites

- Python 3.12 or higher
- Docker 24+
- AWS CLI v2 configured with appropriate credentials
- An AWS account with Bedrock model access enabled (Claude claude-sonnet-4-6 and Titan Embeddings V2)
- PostgreSQL 15 client tools (for local development)
- Redis 7 (Docker image acceptable for local development)

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/kogunlowo123/mcp-security-control-plane.git
   cd mcp-security-control-plane
   ```

2. **Create and activate a virtual environment**

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .\.venv\Scripts\Activate.ps1  # Windows PowerShell
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # for local development
   ```

4. **Copy and configure environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your AWS region, database URL, Redis URL, and Bedrock model IDs
   ```

5. **Run database migrations**

   ```bash
   alembic upgrade head
   ```

6. **Start the control plane (local development)**

   ```bash
   uvicorn platform.main:app --reload --port 8080
   ```

7. **Verify startup**

   ```bash
   curl http://localhost:8080/health
   # {"status": "ok", "version": "0.1.0"}
   ```

---

## Configuration

All configuration is driven by environment variables. The full reference is in `.env.example`. Critical variables:

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | Aurora PostgreSQL DSN (`postgresql+asyncpg://...`) | Yes |
| `REDIS_URL` | ElastiCache / Redis connection string | Yes |
| `AWS_REGION` | AWS region for Bedrock and other services | Yes |
| `BEDROCK_CLAUDE_MODEL_ID` | Bedrock model ID for anomaly analysis | Yes |
| `BEDROCK_EMBEDDING_MODEL_ID` | Titan Embeddings model ID | Yes |
| `KINESIS_STREAM_NAME` | Audit log Kinesis stream name | Yes |
| `OPA_URL` | Open Policy Agent server URL | Yes |
| `SECRET_SIGNING_KEY_ARN` | Secrets Manager ARN for JWT signing key | Yes |
| `AUDIT_ARGUMENT_CAPTURE` | `true` to capture raw arguments (default: `false`) | No |
| `ANOMALY_ALERT_THRESHOLD` | Cosine similarity threshold for anomaly alerts (0–1, default: `0.35`) | No |
| `RATE_LIMIT_BURST_MULTIPLIER` | Burst allowance multiplier (default: `2.0`) | No |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | No |

---

## API Endpoints

All endpoints require a valid `Authorization: Bearer <agent-token>` header unless noted.

### Health and Status

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/health` | Liveness check | None |
| `GET` | `/readiness` | Readiness check (DB + Redis + OPA connectivity) | None |
| `GET` | `/version` | Service version and build metadata | None |

### Tool Call Authorization

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/authorize` | Evaluate a tool call against policies; returns `allow`/`deny` with reason |
| `POST` | `/v1/authorize/dry-run` | Policy dry run — evaluates without recording to the audit log |

**Request body for `/v1/authorize`:**

```json
{
  "agent_id": "agent-abc123",
  "session_id": "sess-xyz789",
  "tool_name": "filesystem.read_file",
  "tool_server": "filesystem-mcp",
  "arguments": {
    "path": "/data/reports/q3.csv"
  },
  "scope_token": "eyJ..."
}
```

**Response:**

```json
{
  "request_id": "req-01j3k4m5n6",
  "decision": "allow",
  "policy_rule": "filesystem.read_file:allowed_paths",
  "anomaly_score": 0.12,
  "rate_limit_remaining": 98,
  "audit_record_id": "aud-9z8y7x6w"
}
```

### Session Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/sessions` | Create a new agent session and issue a scope token |
| `DELETE` | `/v1/sessions/{session_id}` | Terminate a session and revoke its scope token |
| `GET` | `/v1/sessions/{session_id}` | Get session metadata and current status |

### Audit Log

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/audit` | Query audit records (supports filter, pagination, and time range) |
| `GET` | `/v1/audit/{record_id}` | Retrieve a single audit record by ID |
| `GET` | `/v1/audit/export` | Export audit records as NDJSON (streams response) |

### Policy Management

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/policies` | List all active policies |
| `GET` | `/v1/policies/{policy_id}` | Get a specific policy definition |
| `POST` | `/v1/policies/evaluate` | Evaluate a hypothetical call against policies without creating a session |

### Anomaly Detection

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/anomalies` | List recent anomaly alerts |
| `GET` | `/v1/anomalies/{alert_id}` | Get a specific anomaly alert with explanation |
| `POST` | `/v1/anomalies/{alert_id}/acknowledge` | Acknowledge an alert |
| `POST` | `/v1/anomalies/{alert_id}/false-positive` | Mark as false positive and adjust baseline |

### Admin (requires admin scope)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/admin/agents/{agent_id}/quarantine` | Quarantine an agent (all calls blocked) |
| `DELETE` | `/v1/admin/agents/{agent_id}/quarantine` | Lift quarantine |
| `POST` | `/v1/admin/rate-limits/reset` | Reset rate-limit counters for an agent or session |
| `GET` | `/v1/admin/metrics` | Operational metrics (Prometheus format) |

---

## Agent Families

The control plane ships with three built-in LangGraph agent families. Each family is a set of cooperating agents that perform a specific security function.

### `mcp-auditor`

The `mcp-auditor` family handles structured audit analysis. When triggered by a compliance query or a scheduled audit run, it:

1. **AuditCollector** — queries the audit log API to retrieve tool-call records matching the specified time range and filters
2. **PatternAnalyzer** — uses Bedrock to identify unusual patterns, repeated denials, and anomalous argument structures in the collected records
3. **ReportWriter** — produces a structured compliance report in Markdown with findings, risk ratings, and remediation recommendations

Invocation:
```python
from services.agents.mcp_auditor import MCPAuditorGraph

graph = MCPAuditorGraph()
result = await graph.run(
    query="Produce a SOC 2 audit summary for the last 30 days",
    agent_filter=["agent-abc123", "agent-def456"],
    date_range=("2026-08-28", "2026-09-27"),
)
```

### `tool-call-inspector`

The `tool-call-inspector` family performs deep forensic analysis of individual tool calls or call sequences. It is invoked when an anomaly alert fires or a human analyst requests investigation.

1. **ContextReconstructor** — retrieves the full conversation context around a suspicious tool call using session history
2. **ArgumentSemanticAnalyzer** — uses Bedrock to determine whether argument values are consistent with the agent's stated task
3. **CallChainAnalyzer** — examines the sequence of tool calls before and after the suspicious call for signs of privilege escalation or data exfiltration
4. **VerdictWriter** — produces a structured incident assessment with confidence score and recommended action (allow/block/escalate)

### `scope-enforcer`

The `scope-enforcer` family manages the lifecycle of scope tokens and detects scope violations.

1. **ScopeTokenIssuer** — validates agent identity, applies least-privilege scope based on the agent's declared task, and issues a signed scope token
2. **ScopeViolationDetector** — monitors live traffic for scope token misuse (replay attacks, token sharing between agents, scope creep)
3. **ScopeDriftAnalyzer** — runs periodically to identify agents whose actual tool-call patterns have drifted from their declared scope, triggering a policy review

---

## AWS Architecture

The production deployment uses a multi-AZ, defense-in-depth AWS architecture.

```
┌────────────────────────────────────────────────────────────────────┐
│  AWS Account: mcp-security-control-plane-prod                       │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  VPC: 10.0.0.0/16                                            │   │
│  │                                                              │   │
│  │  Public Subnets (10.0.1.0/24, 10.0.2.0/24)                  │   │
│  │  └── Application Load Balancer (WAF + Shield Advanced)       │   │
│  │                                                              │   │
│  │  Private App Subnets (10.0.11.0/24, 10.0.12.0/24)           │   │
│  │  └── ECS Fargate Cluster                                     │   │
│  │      ├── control-plane service (2–20 tasks, auto-scale)      │   │
│  │      ├── opa-sidecar service (1 per task)                    │   │
│  │      └── agent-runner service (1–10 tasks, auto-scale)       │   │
│  │                                                              │   │
│  │  Private Data Subnets (10.0.21.0/24, 10.0.22.0/24)          │   │
│  │  ├── Aurora PostgreSQL 15 (Multi-AZ, pgvector enabled)       │   │
│  │  └── ElastiCache Redis 7 (cluster mode, Multi-AZ)            │   │
│  │                                                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  AWS Services (all endpoints via VPC endpoints)                      │
│  ├── Bedrock (Claude claude-sonnet-4-6, Titan Embeddings V2)                │
│  ├── Kinesis Data Streams (audit log)                                │
│  ├── S3 (audit archive, policy bundle)                               │
│  ├── Secrets Manager (signing keys, DB credentials)                  │
│  ├── CloudWatch (metrics, logs, alarms)                              │
│  ├── X-Ray (distributed tracing)                                     │
│  └── SNS (anomaly alert notifications)                               │
└────────────────────────────────────────────────────────────────────┘
```

All inter-service communication is encrypted in transit (TLS 1.3). Data at rest is encrypted with AWS KMS customer-managed keys. VPC endpoints eliminate public internet egress for all AWS service calls.

---

## Development Guide

### Project Structure

```
mcp-security-control-plane/
├── platform/               # FastAPI application
│   ├── api/                # Route handlers
│   ├── core/               # Settings, dependencies, middleware
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic request/response schemas
│   └── main.py             # Application entry point
├── services/               # Domain services
│   ├── agents/             # LangGraph agent families
│   ├── authorization/      # Policy evaluation engine
│   ├── audit/              # Audit log service
│   ├── anomaly/            # Anomaly detection service
│   ├── rate_limit/         # Rate limiting service
│   └── scope/              # Scope token service
├── security/               # Security utilities
│   ├── identity/           # Agent identity resolution
│   └── crypto/             # Token signing and verification
├── identity/               # Identity provider integrations
├── infra/                  # AWS CDK infrastructure
├── deploy/                 # Deployment scripts and configurations
├── observability/          # OpenTelemetry configuration
├── tests/                  # Test suite
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── evals/                  # Agent evaluation suite
├── docs/                   # Documentation
│   ├── adr/                # Architecture Decision Records
│   └── runbooks/           # Operational runbooks
└── .github/
    └── workflows/          # CI/CD pipelines
```

### Running Tests

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests (requires local Docker services)
docker compose -f docker-compose.test.yml up -d
pytest tests/integration/ -v
docker compose -f docker-compose.test.yml down

# Full test suite with coverage
pytest --cov=platform --cov=services --cov-report=html
```

### Code Style

This project uses:
- **Ruff** for linting and formatting (replaces Black + Flake8)
- **mypy** for static type checking (strict mode)
- **isort** for import ordering (handled by Ruff)

```bash
ruff check .
ruff format .
mypy platform/ services/ security/
```

Pre-commit hooks enforce these checks automatically. Install them with:
```bash
pre-commit install
```

### Infrastructure Deployment

```bash
cd infra/
cdk synth                          # Synthesize CloudFormation templates
cdk diff --app "python app.py"     # Preview changes
cdk deploy McpControlPlaneStack    # Deploy to your configured AWS account
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

*Built with care for the organizations trusting AI agents with real enterprise systems.*

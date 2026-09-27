# STRIDE Threat Model: MCP Security Control Plane

## System Overview

The MCP Security Control Plane is an enterprise platform that governs, audits, and enforces security controls on MCP (Model Context Protocol) tool calls made by AI agents.

## Data Flow Diagram Components

- **AI Agents** → Gateway → API Service → OPA Policy Engine
- **API Service** → PostgreSQL (Aurora pgvector)
- **API Service** → OpenSearch
- **API Service** → SQS (event emission)
- **Token Broker** → Agent JWT issuance
- **RAG Core** → S3 Corpus → pgvector/OpenSearch

---

## STRIDE Analysis

### S — Spoofing

| ID | Threat | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| S1 | Agent impersonation via stolen JWT | Medium | Critical | RS256 signed JWTs, short TTL (30 min T1), JTI revocation list |
| S2 | Token replay after revocation | Low | High | JTI blacklist checked on every request |
| S3 | OPA endpoint spoofing | Low | Critical | TLS mutual auth between API and OPA, VPC-internal traffic only |
| S4 | Fake Bedrock endpoint | Very Low | High | AWS SDK uses HTTPS + AWS SigV4; VPC endpoint enforces AWS origin |

### T — Tampering

| ID | Threat | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| T1 | Tool parameter injection to escalate scope | Medium | High | OPA evaluates declared scope, not extracted from params |
| T2 | Audit log tampering | Low | High | Append-only PostgreSQL table, no UPDATE/DELETE grants to API role |
| T3 | Policy bundle modification | Low | Critical | OPA policies loaded from signed S3 objects; hash verified on load |
| T4 | Embedding poisoning in RAG corpus | Medium | High | ACL stamps, checksum stored per document, re-embed on change |

### R — Repudiation

| ID | Threat | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| R1 | Agent denies making a tool call | Low | High | Immutable audit_log with agent_id, jti, trace_id, timestamp |
| R2 | Gateway log deletion | Very Low | High | CloudTrail + S3 bucket versioning on audit-logs bucket |
| R3 | OPA decision not recorded | Low | Medium | audit_record emitted in every OPA policy evaluation |

### I — Information Disclosure

| ID | Threat | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| I1 | JWT private key exposure | Very Low | Critical | Private key in Secrets Manager; ExternalSecrets rotates daily |
| I2 | RAG returning documents above agent tier | Medium | High | ACL filter in HybridRetriever enforces tier before returning results |
| I3 | Audit log containing PII | Medium | Medium | PII scrubbing processor in OTel collector; PII tagger on ingest |
| I4 | Tool parameters logged in plain text | Low | Medium | tool_parameters stored as JSONB; no sensitive field logging |
| I5 | OpenSearch documents exposed without auth | Low | High | Fine-grained access control; IRSA-based auth |

### D — Denial of Service

| ID | Threat | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| D1 | Rate limit bypass via multiple tokens | Medium | Medium | Rate limiting tied to agent_id, not token; same agent_id shares limit |
| D2 | OPA bundle fetch DDoS | Very Low | High | OPA bundles cached locally; API fails closed on OPA unavailability |
| D3 | Bedrock token budget exhaustion | Low | Medium | BudgetEnforcer tracks tokens/hour per agent |
| D4 | PostgreSQL connection pool exhaustion | Low | High | pgbouncer connection pooling; circuit breaker in API |

### E — Elevation of Privilege

| ID | Threat | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| E1 | T0 agent attempting T2 tool calls | High | High | OPA checks allowed_tiers for every tool; deny with reason scope_exceeded |
| E2 | Karpenter node claiming privileged role | Very Low | Critical | IRSA scoped to service account; Kyverno blocks privileged containers |
| E3 | Scope escalation via JWT grant manipulation | Low | High | JWT signed with RS256; grants verified against catalog at OPA layer |
| E4 | Admin API endpoint accessed without RBAC | Low | Critical | No admin endpoint exposed; all mutations require T2 + OPA approval |
| E5 | RDS superuser credential leakage | Very Low | Critical | Aurora master creds in Secrets Manager; app uses least-privilege role |

---

## Risk Register Summary

| Risk | Residual Likelihood | Residual Impact | Risk Score |
|------|-------------------|-----------------|------------|
| JWT compromise (S1) | Low | Critical | High |
| Scope escalation (E1) | Very Low | High | Medium |
| RAG ACL bypass (I2) | Very Low | High | Medium |
| Audit log integrity (R1) | Very Low | High | Low |
| Bedrock abuse (D3) | Low | Medium | Low |

## Review Schedule

This threat model is reviewed quarterly or when significant architectural changes occur.

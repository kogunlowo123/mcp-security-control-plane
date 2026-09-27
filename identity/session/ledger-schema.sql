-- MCP Security Control Plane - Session Ledger Schema
-- PostgreSQL 16 with pgvector extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Sessions table for agent session tracking
CREATE TABLE IF NOT EXISTS sessions (
    session_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        VARCHAR(255) NOT NULL,
    tier            VARCHAR(10) NOT NULL CHECK (tier IN ('T0', 'T1', 'T2')),
    jti             VARCHAR(255) UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at      TIMESTAMPTZ,
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions (agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_jti ON sessions (jti);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_id ON sessions (tenant_id);

-- Audit log - append-only table for all tool invocations
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        VARCHAR(255) NOT NULL,
    tool_name       VARCHAR(255) NOT NULL,
    tool_parameters JSONB NOT NULL DEFAULT '{}',
    decision        VARCHAR(10) NOT NULL CHECK (decision IN ('permit', 'deny')),
    scope           VARCHAR(255) NOT NULL,
    deny_reason     VARCHAR(255),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trace_id        VARCHAR(255),
    span_id         VARCHAR(255),
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',
    policy_version  VARCHAR(50),
    duration_ms     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_audit_log_agent_id ON audit_log (agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_tool_name ON audit_log (tool_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_decision ON audit_log (decision);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_id ON audit_log (tenant_id);

-- Violations table for security violations
CREATE TABLE IF NOT EXISTS violations (
    violation_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        VARCHAR(255) NOT NULL,
    tool_name       VARCHAR(255) NOT NULL,
    violation_type  VARCHAR(100) NOT NULL,
    description     TEXT NOT NULL,
    severity        VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(255),
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',
    context         JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_violations_agent_id ON violations (agent_id);
CREATE INDEX IF NOT EXISTS idx_violations_severity ON violations (severity);
CREATE INDEX IF NOT EXISTS idx_violations_timestamp ON violations (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_violations_resolved ON violations (resolved);
CREATE INDEX IF NOT EXISTS idx_violations_tenant_id ON violations (tenant_id);

-- Rate limit counters for per-agent rate limiting
CREATE TABLE IF NOT EXISTS rate_limit_counters (
    agent_id        VARCHAR(255) NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    count           INTEGER NOT NULL DEFAULT 0,
    limit_val       INTEGER NOT NULL DEFAULT 100,
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',
    PRIMARY KEY (agent_id, window_start, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_agent_window ON rate_limit_counters (agent_id, window_start DESC);

-- Revoked token JTIs for preventing replay attacks
CREATE TABLE IF NOT EXISTS revoked_jtis (
    jti             VARCHAR(255) PRIMARY KEY,
    agent_id        VARCHAR(255) NOT NULL,
    revoked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revoked_jtis_expires_at ON revoked_jtis (expires_at);

-- Document store for RAG corpus
CREATE TABLE IF NOT EXISTS documents (
    doc_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_url      TEXT,
    doc_type        VARCHAR(100),
    title           TEXT,
    content         TEXT NOT NULL,
    chunk_index     INTEGER,
    embedding       VECTOR(1536),
    metadata        JSONB NOT NULL DEFAULT '{}',
    acl_tiers       TEXT[] NOT NULL DEFAULT '{"T0","T1","T2"}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_documents_embedding ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents (created_at);
CREATE INDEX IF NOT EXISTS idx_documents_acl_tiers ON documents USING GIN (acl_tiers);

-- Tool catalog
CREATE TABLE IF NOT EXISTS tool_catalog (
    tool_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) UNIQUE NOT NULL,
    description     TEXT,
    allowed_scopes  TEXT[] NOT NULL,
    allowed_tiers   TEXT[] NOT NULL,
    parameters_schema JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version         VARCHAR(50) NOT NULL DEFAULT '1.0.0'
);

CREATE INDEX IF NOT EXISTS idx_tool_catalog_name ON tool_catalog (name);
CREATE INDEX IF NOT EXISTS idx_tool_catalog_is_active ON tool_catalog (is_active);

-- Seed approved tool catalog
INSERT INTO tool_catalog (name, description, allowed_scopes, allowed_tiers, parameters_schema) VALUES
    ('rag_search', 'Search MCP security policy documents', ARRAY['read-only'], ARRAY['T0','T1','T2'], '{"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer","default":5}}}'),
    ('mcp_audit_query', 'Query MCP audit logs', ARRAY['read-only'], ARRAY['T0','T1','T2'], '{"type":"object","properties":{"agent_id":{"type":"string"},"tool_name":{"type":"string"},"start_time":{"type":"string"},"end_time":{"type":"string"}}}'),
    ('tool_catalog', 'List approved MCP tools', ARRAY['read-only'], ARRAY['T0','T1','T2'], '{"type":"object","properties":{}}'),
    ('api_call', 'Make external API calls', ARRAY['read-only','read-write'], ARRAY['T1','T2'], '{"type":"object","properties":{"url":{"type":"string"},"method":{"type":"string"}}}'),
    ('code_execute', 'Execute code in sandbox', ARRAY['read-write'], ARRAY['T2'], '{"type":"object","properties":{"code":{"type":"string"},"language":{"type":"string"}}}')
ON CONFLICT (name) DO NOTHING;

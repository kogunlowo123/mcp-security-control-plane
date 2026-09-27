package mcp.control

import future.keywords.if
import future.keywords.in

default allow := false
default deny_reason := "unauthorized"

# Allow tool call if all conditions are met
allow if {
	valid_token
	tool_in_catalog
	agent_has_grant
	not rate_limited
	not scope_exceeded
}

# Deny reason selectors
deny_reason := "invalid_token" if {
	not valid_token
}

deny_reason := "tool_not_in_catalog" if {
	valid_token
	not tool_in_catalog
}

deny_reason := "grant_missing" if {
	valid_token
	tool_in_catalog
	not agent_has_grant
}

deny_reason := "rate_limited" if {
	valid_token
	tool_in_catalog
	agent_has_grant
	rate_limited
}

deny_reason := "scope_exceeded" if {
	valid_token
	tool_in_catalog
	agent_has_grant
	not rate_limited
	scope_exceeded
}

# Token must not be expired and must be from a trusted issuer
valid_token if {
	input.token.exp > time.now_ns() / 1000000000
	input.token.iss == "mcp-security-control-plane"
	count(input.token.agent_id) > 0
	not revoked_token
}

revoked_token if {
	some jti in data.revoked_jtis
	jti == input.token.jti
}

# Tool must exist in the approved catalog and be active
tool_in_catalog if {
	some tool in data.catalog.approved_tools
	tool.name == input.tool_name
	tool.is_active == true
}

# Agent must have an explicit grant for the requested tool
agent_has_grant if {
	some grant in input.token.grants
	grant == input.tool_name
}

# Rate limiting check against stored counters
rate_limited if {
	data.rate_limits[input.token.agent_id].count >= data.rate_limits[input.token.agent_id].limit
}

# Requested scope must be in the tool's allowed scopes
scope_exceeded if {
	some tool in data.catalog.approved_tools
	tool.name == input.tool_name
	not input.scope in tool.allowed_scopes
}

# Agent tier must meet the tool's minimum tier requirement
scope_exceeded if {
	some tool in data.catalog.approved_tools
	tool.name == input.tool_name
	not input.token.tier in tool.allowed_tiers
}

# Compute final decision string
decision := "permit" if {
	allow
}

decision := "deny" if {
	not allow
}

# Audit record emitted with every policy evaluation
audit_record := {
	"agent_id": input.token.agent_id,
	"tool_name": input.tool_name,
	"scope": input.scope,
	"decision": decision,
	"reason": deny_reason,
	"tier": input.token.tier,
	"request_id": input.request_id,
	"timestamp": time.now_ns(),
}

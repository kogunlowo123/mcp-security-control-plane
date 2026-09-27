package mcp.tool_scope

import future.keywords.if
import future.keywords.in

default scope_allowed := false
default escalation_detected := false

# Scope is allowed if it matches an approved scope for the tool
scope_allowed if {
	some tool in data.catalog.approved_tools
	tool.name == input.tool_name
	input.requested_scope in tool.allowed_scopes
	tier_allowed
}

# Tier must be sufficient for the requested scope
tier_allowed if {
	some tool in data.catalog.approved_tools
	tool.name == input.tool_name
	input.agent_tier in tool.allowed_tiers
}

# Detect scope escalation attempts
escalation_detected if {
	input.requested_scope in {"admin", "write", "delete"}
	input.agent_tier == "T0"
}

escalation_detected if {
	input.requested_scope == "admin"
	input.agent_tier in {"T0", "T1"}
}

# Validation response
response := {
	"allowed": scope_allowed,
	"escalation_detected": escalation_detected,
	"tool_name": input.tool_name,
	"requested_scope": input.requested_scope,
	"agent_tier": input.agent_tier,
}

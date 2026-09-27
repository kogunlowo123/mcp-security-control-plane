"""
Pydantic v2 schemas for the MCP tool catalog.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """Full definition of a registered MCP tool."""

    tool_id: str = Field(..., description="Unique stable identifier for the tool")
    name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="What the tool does")
    allowed_scopes: List[str] = Field(
        ...,
        description="OAuth-style scopes that authorise use of this tool",
    )
    allowed_agent_tiers: List[str] = Field(
        ...,
        description="Agent trust tiers permitted to invoke this tool (e.g. 'standard', 'privileged')",
    )
    parameters_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema describing the tool's input parameters",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the tool is currently available for invocation",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "tool_id": "tool-file-read-v1",
            "name": "file-read",
            "description": "Read a file from the allowed filesystem namespace",
            "allowed_scopes": ["read:files"],
            "allowed_agent_tiers": ["standard", "privileged", "admin"],
            "parameters_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "is_active": True,
        }
    }}


class ToolCatalogResponse(BaseModel):
    """Paginated response wrapping a list of tool definitions."""

    tools: List[ToolDefinition] = Field(..., description="Tools on this page")
    total: int = Field(..., description="Total number of registered tools")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Maximum items per page")

    model_config = {"json_schema_extra": {
        "example": {
            "tools": [],
            "total": 5,
            "page": 1,
            "page_size": 20,
        }
    }}

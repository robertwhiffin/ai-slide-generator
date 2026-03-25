"""Pydantic models for agent_config JSON stored on sessions and profiles."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class GenieTool(BaseModel):
    """Native Genie space tool — registered directly as a LangChain tool."""
    type: Literal["genie"]
    space_id: str = Field(..., min_length=1)
    space_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    conversation_id: Optional[str] = None


class MCPTool(BaseModel):
    """MCP server tool — tools discovered via MCP protocol."""
    type: Literal["mcp"]
    server_uri: str = Field(..., min_length=1)
    server_name: str = Field(..., min_length=1)
    config: dict = Field(default_factory=dict)


ToolEntry = Annotated[Union[GenieTool, MCPTool], Field(discriminator="type")]


class AgentConfig(BaseModel):
    """Agent configuration stored as JSON on sessions and profiles.

    When all fields are None/empty, the system uses backend defaults.
    """
    tools: list[ToolEntry] = Field(default_factory=list)
    slide_style_id: Optional[int] = None
    deck_prompt_id: Optional[int] = None
    system_prompt: Optional[str] = None
    slide_editing_instructions: Optional[str] = None

    @field_validator("system_prompt", "slide_editing_instructions")
    @classmethod
    def must_be_nonempty_if_set(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() == "":
            raise ValueError("Must be non-empty if provided")
        return v

    @model_validator(mode="after")
    def no_duplicate_tools(self) -> "AgentConfig":
        seen: set[str] = set()
        for tool in self.tools:
            if isinstance(tool, GenieTool):
                key = f"genie:{tool.space_id}"
            elif isinstance(tool, MCPTool):
                key = f"mcp:{tool.server_uri}"
            else:
                continue
            if key in seen:
                raise ValueError(f"Duplicate tool: {key}")
            seen.add(key)
        return self


def resolve_agent_config(raw: Optional[dict]) -> AgentConfig:
    """Parse agent_config JSON from DB, returning defaults if None."""
    if raw is None:
        return AgentConfig()
    return AgentConfig.model_validate(raw)

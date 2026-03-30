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
    """MCP server tool — tools discovered via UC HTTP connections."""
    type: Literal["mcp"]
    connection_name: str = Field(..., min_length=1)
    server_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    config: dict = Field(default_factory=dict)


class VectorIndexTool(BaseModel):
    """Vector search index tool — similarity search over embeddings."""
    type: Literal["vector_index"]
    endpoint_name: str = Field(..., min_length=1)
    index_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    columns: Optional[list[str]] = None
    num_results: int = Field(default=5, ge=1, le=50)


class ModelEndpointTool(BaseModel):
    """Model serving endpoint tool — foundation models and custom ML."""
    type: Literal["model_endpoint"]
    endpoint_name: str = Field(..., min_length=1)
    endpoint_type: Optional[str] = None
    description: Optional[str] = None


class AgentBricksTool(BaseModel):
    """Agent Bricks tool — knowledge assistants and supervisor agents."""
    type: Literal["agent_bricks"]
    endpoint_name: str = Field(..., min_length=1)
    description: Optional[str] = None


ToolEntry = Annotated[
    Union[GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool],
    Field(discriminator="type"),
]


class AgentConfig(BaseModel):
    """Agent configuration stored as JSON on sessions and profiles."""
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
                key = f"mcp:{tool.connection_name}"
            elif isinstance(tool, VectorIndexTool):
                key = f"vector_index:{tool.endpoint_name}:{tool.index_name}"
            elif isinstance(tool, ModelEndpointTool):
                key = f"model_endpoint:{tool.endpoint_name}"
            elif isinstance(tool, AgentBricksTool):
                key = f"agent_bricks:{tool.endpoint_name}"
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

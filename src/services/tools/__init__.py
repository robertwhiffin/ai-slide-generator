"""Tool execution modules for the slide generator agent.

Re-exports all tool builders and helper functions so consumers
can import from ``src.services.tools`` without knowing the internal
module structure.
"""

from src.services.tools.agent_bricks_tool import build_agent_bricks_tool
from src.services.tools.genie_tool import (
    GenieQueryInput,
    GenieToolError,
    build_genie_tool,
    initialize_genie_conversation,
    query_genie_space,
)
from src.services.tools.mcp_tool import build_mcp_tools
from src.services.tools.model_endpoint_tool import build_model_endpoint_tool
from src.services.tools.vector_tool import build_vector_tool

__all__ = [
    # Genie
    "initialize_genie_conversation",
    "query_genie_space",
    "build_genie_tool",
    "GenieToolError",
    "GenieQueryInput",
    # Vector search
    "build_vector_tool",
    # MCP
    "build_mcp_tools",
    # Model endpoint
    "build_model_endpoint_tool",
    # Agent Bricks
    "build_agent_bricks_tool",
]

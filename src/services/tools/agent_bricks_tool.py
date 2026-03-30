"""
Agent Bricks tool execution module.

Creates LangChain tools for querying Databricks Agent Bricks endpoints
(knowledge assistants and supervisor agents) using the user's OAuth
token (OBO authentication).

Always uses the agent input format::

    {"input": [{"role": "user", "content": "..."}]}

Response parsing expects::

    {"output": [{"type": "message", "content": [{"text": "..."}]}]}
"""

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.api.schemas.agent_config import AgentBricksTool
from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)


class AgentBricksError(Exception):
    """Raised when Agent Bricks query fails."""

    pass


class AgentBricksInput(BaseModel):
    """Input schema for agent bricks tool."""

    query: str = Field(description="Question or request to send to the agent")


def _extract_agent_response(result: dict) -> str:
    """Extract text from an Agent Bricks endpoint response.

    Expected structure::

        {"output": [{"type": "message",
                      "content": [{"type": "output_text", "text": "..."}]}]}
    """
    output = result.get("output", [])

    if isinstance(output, list):
        texts = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("text"):
                        texts.append(content["text"])
        if texts:
            return "\n\n".join(texts)

    if isinstance(output, str):
        return output

    # Fallback: return the raw JSON
    return json.dumps(result)


def _query_agent_bricks(endpoint_name: str, query: str) -> str:
    """
    Query a Databricks Agent Bricks endpoint.

    Uses the agent input format and extracts text from the response.

    Args:
        endpoint_name: Name of the serving endpoint
        query: The query text to send

    Returns:
        Text string with agent response

    Raises:
        AgentBricksError: If query fails
    """
    logger.info(
        "Querying agent bricks endpoint",
        extra={"endpoint": endpoint_name, "query": query[:100]},
    )

    try:
        client = get_user_client()
        path = f"/serving-endpoints/{endpoint_name}/invocations"
        message = [{"role": "user", "content": query}]

        result = client.api_client.do("POST", path, body={"input": message})
        text = _extract_agent_response(result)

        logger.info(
            "Agent bricks query completed",
            extra={
                "endpoint": endpoint_name,
                "response_length": len(text),
            },
        )

        return text

    except Exception as e:
        logger.error("Agent bricks query failed: %s", e, exc_info=True)
        raise AgentBricksError(
            f"Failed to query agent endpoint {endpoint_name}: {e}"
        ) from e


def build_agent_bricks_tool(
    config: AgentBricksTool, index: int = 1,
) -> StructuredTool:
    """
    Build a LangChain StructuredTool for an Agent Bricks endpoint.

    Args:
        config: AgentBricksTool config with endpoint_name, etc.
        index: 1-based index for unique tool naming

    Returns:
        LangChain StructuredTool instance
    """
    endpoint_name = config.endpoint_name

    def _wrapper(query: str) -> str:
        return _query_agent_bricks(
            endpoint_name=endpoint_name,
            query=query,
        )

    tool_name = "query_agent" if index == 1 else f"query_agent_{index}"

    description = config.description or f"Query the {endpoint_name} agent"
    description += (
        f"\n\nThis queries the Databricks Agent endpoint: {endpoint_name}. "
        "Send a natural language question and get a response from the agent."
    )

    return StructuredTool.from_function(
        func=_wrapper,
        name=tool_name,
        description=description,
        args_schema=AgentBricksInput,
    )

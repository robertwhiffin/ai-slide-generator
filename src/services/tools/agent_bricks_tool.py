"""
Agent Bricks tool execution module.

Creates LangChain tools for querying Databricks Agent Bricks endpoints
(knowledge assistants and supervisor agents) using the user's OAuth
token (OBO authentication).

Uses the Databricks SDK's ``serving_endpoints.query()`` method which
handles the correct request/response format for all agent endpoint
versions (agent/v1/responses, agent/v2/chat).

Request format::

    messages=[{"role": "user", "content": "..."}]

Response format::

    {"choices": [{"message": {"content": "..."}}]}
"""

import json
import logging

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


def _query_agent_bricks(endpoint_name: str, query: str) -> str:
    """
    Query a Databricks Agent Bricks endpoint using the SDK.

    Uses ``client.serving_endpoints.query()`` which handles the correct
    format for all agent endpoint versions.

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

        # Use the SDK's query method — handles all agent formats correctly
        response = client.serving_endpoints.query(
            name=endpoint_name,
            messages=[{"role": "user", "content": query}],
        )

        # Extract text from response
        text = None

        # Standard response: response.choices[0].message.content
        if hasattr(response, "choices") and response.choices:
            for choice in response.choices:
                msg = getattr(choice, "message", None)
                if msg and getattr(msg, "content", None):
                    text = msg.content
                    break

        # If choices didn't work, try as_dict() fallback
        if not text and hasattr(response, "as_dict"):
            result = response.as_dict()
            choices = result.get("choices", [])
            if choices:
                for choice in choices:
                    if isinstance(choice, dict):
                        msg = choice.get("message", {})
                        if isinstance(msg, dict) and msg.get("content"):
                            text = msg["content"]
                            break

            # Try output field (legacy format)
            if not text:
                output = result.get("output", [])
                if isinstance(output, str) and output:
                    text = output
                elif isinstance(output, list):
                    texts = []
                    for item in output:
                        if isinstance(item, dict) and item.get("type") == "message":
                            for content in item.get("content", []):
                                if isinstance(content, dict) and content.get("text"):
                                    texts.append(content["text"])
                    if texts:
                        text = "\n\n".join(texts)

            # Last resort: raw JSON
            if not text and result:
                text = json.dumps(result)

        if not text:
            text = "Agent returned no content."

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

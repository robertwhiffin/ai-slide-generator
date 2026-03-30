"""
Agent Bricks tool execution module.

Creates LangChain tools for querying Databricks Agent Bricks endpoints
(knowledge assistants and supervisor agents) using the user's OAuth
token (OBO authentication).

Uses the SDK's ``api_client.do()`` for direct HTTP calls to serving
endpoints. Agent endpoints use the ``input`` format::

    {"input": [{"role": "user", "content": "..."}]}

Response parsing handles both ``output`` (agent/v1/responses) and
``choices`` (agent/v2/chat) formats.
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


def _extract_text_from_response(result: dict) -> str:
    """Extract text from an agent endpoint response dict.

    Handles multiple response formats:
    - output list: {"output": [{"type": "message", "content": [{"text": "..."}]}]}
    - choices: {"choices": [{"message": {"content": "..."}}]}
    - output string: {"output": "plain text"}
    """
    # output list format (agent/v1/responses — most common for KA/MAS)
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

    # choices format (agent/v2/chat)
    choices = result.get("choices", [])
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                msg = choice.get("message") or choice.get("delta") or {}
                if isinstance(msg, dict) and msg.get("content"):
                    return msg["content"]

    # output string format
    if isinstance(output, str) and output:
        return output

    return ""


def _query_agent_bricks(endpoint_name: str, query: str) -> str:
    """
    Query a Databricks Agent Bricks endpoint.

    Uses the ``input`` format which is required by agent endpoints.
    Extracts text from the response using format-aware parsing.

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
        messages = [{"role": "user", "content": query}]

        result = client.api_client.do("POST", path, body={"input": messages})

        # Handle empty responses — some endpoints return 200 with empty body
        if not result or result == {}:
            logger.warning(
                "Agent endpoint returned empty response",
                extra={"endpoint": endpoint_name},
            )
            return (
                "Agent endpoint returned an empty response. "
                "The agent may not be configured correctly or may not "
                "have data to answer this query."
            )

        text = _extract_text_from_response(result)

        if not text:
            # Return raw JSON so the LLM can still use whatever came back
            return json.dumps(result)

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

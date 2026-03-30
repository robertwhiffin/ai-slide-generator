"""
Agent Bricks tool execution module.

Creates LangChain tools for querying Databricks Agent Bricks endpoints
(knowledge assistants and supervisor agents) using the user's OAuth
token (OBO authentication).

Uses ``api_client.do()`` for direct HTTP calls to serving endpoints,
matching the proven pattern from the original tools implementation.
Tries multiple input formats to handle different agent endpoint versions.
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

    Tries multiple response formats:
    - choices format: {"choices": [{"message": {"content": "..."}}]}
    - output list format: {"output": [{"type": "message", "content": [{"text": "..."}]}]}
    - output string format: {"output": "plain text"}
    """
    # choices format (standard for chat/agent endpoints)
    choices = result.get("choices", [])
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                msg = choice.get("message") or choice.get("delta") or {}
                if isinstance(msg, dict) and msg.get("content"):
                    return msg["content"]

    # output list format (agent/v1/responses)
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

    # output string format
    if isinstance(output, str) and output:
        return output

    return ""


def _query_agent_bricks(endpoint_name: str, query: str) -> str:
    """
    Query a Databricks Agent Bricks endpoint.

    Tries multiple input formats since agent endpoints vary by version:
    - {"messages": [...]} — agent/v2/chat and standard chat format
    - {"input": {"messages": [...]}} — agent/v1/responses format

    Uses api_client.do() for direct HTTP (returns plain dict, no
    deserialization issues).

    Args:
        endpoint_name: Name of the serving endpoint
        query: The query text to send

    Returns:
        Text string with agent response

    Raises:
        AgentBricksError: If all formats fail
    """
    logger.info(
        "Querying agent bricks endpoint",
        extra={"endpoint": endpoint_name, "query": query[:100]},
    )

    try:
        client = get_user_client()
        path = f"/serving-endpoints/{endpoint_name}/invocations"
        messages = [{"role": "user", "content": query}]

        # Try formats in order of likelihood
        formats = [
            ("messages", {"messages": messages}),
            ("input_messages", {"input": {"messages": messages}}),
            ("input_array", {"input": messages}),
        ]

        last_error = None
        for label, body in formats:
            try:
                result = client.api_client.do("POST", path, body=body)
                text = _extract_text_from_response(result)
                if text:
                    logger.info(
                        "Agent bricks query completed (%s format)",
                        label,
                        extra={
                            "endpoint": endpoint_name,
                            "response_length": len(text),
                        },
                    )
                    return text
                else:
                    logger.debug(
                        "Agent bricks %s format returned empty for %s",
                        label, endpoint_name,
                    )
            except Exception as e:
                last_error = e
                logger.debug(
                    "Agent bricks %s format failed for %s: %s",
                    label, endpoint_name, e,
                )
                continue

        # All formats returned empty or failed
        if last_error:
            raise last_error
        return "Agent returned no content."

    except AgentBricksError:
        raise
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

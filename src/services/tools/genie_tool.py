"""
Genie tool for the slide generator agent.

This module implements tools for querying Databricks Genie spaces.
Includes the low-level query functions and the LangChain tool builder.
"""

import logging
import time
from typing import Any, Optional

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.api.schemas.agent_config import GenieTool
from src.core.databricks_client import get_user_client
from src.core.settings_db import get_settings

logger = logging.getLogger(__name__)


class GenieToolError(Exception):
    """Raised when Genie tool execution fails."""

    pass


class GenieQueryInput(BaseModel):
    """Input schema for Genie query tool."""

    query: str = Field(description="Natural language question")


def initialize_genie_conversation(space_id: Optional[str] = None) -> str:
    """
    Initialize a Genie conversation with a placeholder message.

    This function creates a new Genie conversation that can be reused
    across multiple queries within a session, eliminating the need for
    the LLM to track conversation IDs.

    Args:
        space_id: Genie space ID. If not provided, reads from global settings.
    Returns:
        Genie conversation ID string

    Raises:
        GenieToolError: If conversation initialization fails

    Example:
        >>> conv_id = initialize_genie_conversation("space123")
        >>> result = query_genie_space("show me data", conv_id, space_id="space123")
    """
    logger.warning("Genie tool: initialize_genie_conversation called")
    client = get_user_client()
    logger.warning(
        "Genie tool: got client for conversation init",
        extra={"client_config_host": client.config.host},
    )
    if not space_id:
        settings = get_settings()
        if not settings.genie:
            raise GenieToolError("Genie space not configured for this profile")
        space_id = settings.genie.space_id

    logger.info("Initializing Genie conversation", extra={"space_id": space_id})

    conversation_start_message: str = """
    You are a data analyst agent for an AI slide generation system.
    Unless explicitly instructed otherwise, convert datetimes to dates and always round numeric columns to the nearest whole number.
    Provide an informative explanation of your query results.
    """

    try:
        response = client.genie.start_conversation_and_wait(
            space_id=space_id, content=conversation_start_message
        )
        conversation_id = response.conversation_id

        logger.info(
            "Initialized Genie conversation",
            extra={
                "conversation_id": conversation_id,
                "space_id": space_id,
            },
        )

        return conversation_id

    except Exception as e:
        raise GenieToolError(f"Failed to initialize Genie conversation: {e}") from e




def query_genie_space(
    query: str,
    conversation_id: Optional[str] = None,
    max_retries: int = 2,
    space_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Query Databricks Genie space for data using natural language or SQL.

    This tool connects to a Databricks Genie space and executes queries to retrieve data.
    Genie can respond with plain text messages, data attachments, or both.

    Args:
        query: Natural language question
        conversation_id: Optional conversation ID (not currently used with start_conversation_and_wait)
        max_retries: Maximum number of retries if query fails (default: 2)

    Returns:
        Dictionary containing:
            - message: Plain text message from Genie (may be empty string)
            - data: JSON string of the data (None if no attachment)
            - conversation_id: ID for the conversation

    Raises:
        GenieToolError: If query execution fails after all retries

    Example:
        >>> result = query_genie_space("show me a sample of data")
        >>> print(result['message'])
        >>> print(result['data'])
    """
    logger.warning("Genie tool: query_genie_space called")
    client = get_user_client()
    logger.warning(
        "Genie tool: got client for query",
        extra={"client_config_host": client.config.host},
    )
    # Use explicitly provided space_id (from agent_factory per-space tools),
    # falling back to global settings for legacy single-Genie path.
    if not space_id:
        settings = get_settings()
        if not settings.genie:
            raise GenieToolError("Genie space not configured for this profile")
        space_id = settings.genie.space_id

    # Log with safe attribute access
    extra_info = {
        "space_id": space_id,
        "query": query[:100],  # First 100 chars
        "cache_info": str(get_settings.cache_info()),
    }

    logger.info("Querying Genie space", extra=extra_info)

    attempt = 0
    last_error = None

    while attempt <= max_retries:
        try:
            if conversation_id is None:
                # Start conversation and wait for completion
                response = client.genie.start_conversation_and_wait(
                    space_id=space_id, content=query
                )
                conversation_id = response.conversation_id
            else:
                response = client.genie.create_message_and_wait(
                    space_id=space_id, conversation_id=conversation_id, content=query
                )

            message_id = response.message_id


            # Extract attachments (data results)
            attachments = response.attachments
            data = ''
            message_content = ''
            for attachment in attachments:
                if attachment.query:
                    attachment_response = client.genie.get_message_attachment_query_result(
                        space_id=space_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        attachment_id=attachment.attachment_id,
                    )
                    # Extract data and columns from response
                    response_dict = attachment_response.as_dict()["statement_response"]
                    columns = [_["name"] for _ in response_dict["manifest"]["schema"]["columns"]]
                    data_array = response_dict.get("result", {}).get("data_array", [])
                    # Create DataFrame and convert to records
                    df = pd.DataFrame(data_array, columns=columns)
                    data = df.to_csv(index=False)
                if attachment.text:
                    message_content = attachment.text


            if attempt > 0:
                logger.info(
                    "Genie query succeeded after retries",
                    extra={
                        "attempt": attempt + 1,
                        "conversation_id": conversation_id,
                    },
                )

            logger.info(
                "Genie query completed",
                extra={
                    "has_message": bool(message_content),
                    "has_data": bool(data),
                    "conversation_id": conversation_id,
                },
            )

            return {
                "message": message_content,
                "data": data,
                "conversation_id": conversation_id
            }

        except Exception as e:
            last_error = e
            attempt += 1
            if attempt <= max_retries:
                logger.warning(
                    f"Genie query failed, retrying: {e}",
                    extra={
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "query": query,
                    },
                )
                time.sleep(1)  # Wait 1 second before retry
            else:
                raise GenieToolError(
                    f"Failed to query Genie space after {max_retries + 1} attempts: {e}"
                ) from last_error


def build_genie_tool(
    genie_config: GenieTool,
    session_data: dict[str, Any],
    index: int = 1,
) -> StructuredTool:
    """Build a LangChain StructuredTool for a Genie space.

    The tool wraps query_genie_space with automatic conversation_id
    management via closure over session_data. Each Genie space gets
    its own conversation_id tracked under a per-space key.

    Args:
        genie_config: GenieTool config with space_id and space_name
        session_data: Mutable session dict (conversation_ids updated in place)
        index: 1-based index for unique tool naming when multiple Genie spaces

    Returns:
        StructuredTool for querying Genie
    """
    # Per-space conversation ID key
    conv_key = f"genie_conversation_id:{genie_config.space_id}"

    # Seed from the persisted conversation_id on the GenieTool config first
    if genie_config.conversation_id:
        session_data[conv_key] = genie_config.conversation_id
    # Fall back to the legacy single key if this is the first/only Genie space
    elif conv_key not in session_data and index == 1:
        legacy_id = session_data.get("genie_conversation_id")
        if legacy_id:
            session_data[conv_key] = legacy_id

    def _query_genie_wrapper(query: str) -> str:
        """Query Genie with auto-injected conversation_id from session."""
        conversation_id = session_data.get(conv_key)

        if conversation_id is None:
            logger.info(
                "Initializing Genie conversation for factory-built agent",
                extra={"space_id": genie_config.space_id},
            )
            try:
                new_conv_id = initialize_genie_conversation(space_id=genie_config.space_id)
                session_data[conv_key] = new_conv_id
                # Also update the legacy key for backward compat
                session_data["genie_conversation_id"] = new_conv_id
                conversation_id = new_conv_id
            except Exception as e:
                logger.error(f"Failed to initialize Genie conversation: {e}")
                raise

        result = query_genie_space(query, conversation_id, space_id=genie_config.space_id)

        response_parts = []
        if result.get("message"):
            response_parts.append(f"Genie response: {result['message']}")
        if result.get("data"):
            response_parts.append(f"Data retrieved:\n\n{result['data']}")
        if not response_parts:
            return "Query completed but no data or message was returned."
        return "\n\n".join(response_parts)

    description = (
        "Query Databricks Genie for data using natural language questions. "
        "Genie understands natural language and converts it to SQL - do not write SQL yourself.\n\n"
        "USAGE GUIDELINES:\n"
        "- Make multiple queries to gather comprehensive data (typically 5-8 strategic queries)\n"
        "- Use follow-up queries to drill deeper into interesting findings\n"
        "- Conversation context is automatically maintained across queries\n"
        "- If initial data is insufficient, query for more specific information\n\n"
        "WHEN TO STOP:\n"
        "- Once you have sufficient data, STOP calling this tool\n"
        "- Transition immediately to generating the HTML presentation\n"
        "- Do NOT make additional queries once you have enough information\n\n"
    )
    if genie_config.description:
        description += f"DATA AVAILABLE:\n{genie_config.description}"
    else:
        description += f"DATA AVAILABLE:\nGenie space '{genie_config.space_name}'"

    tool_name = "query_genie_space" if index == 1 else f"query_genie_space_{index}"

    return StructuredTool.from_function(
        func=_query_genie_wrapper,
        name=tool_name,
        description=description,
        args_schema=GenieQueryInput,
    )

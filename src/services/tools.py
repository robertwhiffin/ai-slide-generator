"""
Tools for the slide generator agent.

This module implements tools that the agent can use to gather data and perform tasks.
"""

import logging
import time
from typing import Any, Optional

import pandas as pd

from src.core.databricks_client import get_user_client
from src.core.settings_db import get_settings

logger = logging.getLogger(__name__)


class GenieToolError(Exception):
    """Raised when Genie tool execution fails."""

    pass


def initialize_genie_conversation() -> str:
    """
    Initialize a Genie conversation with a placeholder message.

    This function creates a new Genie conversation that can be reused
    across multiple queries within a session, eliminating the need for
    the LLM to track conversation IDs.

    Args: None
    Returns:
        Genie conversation ID string

    Raises:
        GenieToolError: If conversation initialization fails

    Example:
        >>> conv_id = initialize_genie_conversation()
        >>> result = query_genie_space("show me data", conv_id)
    """
    client = get_user_client()
    settings = get_settings()
    space_id = settings.genie.space_id

    # Log with safe attribute access
    extra_info = {
        "space_id": space_id,
        "cache_info": str(get_settings.cache_info()),
    }
    # Safely add profile info if available
    if hasattr(settings, 'profile_id'):
        extra_info['profile_id'] = settings.profile_id
    if hasattr(settings, 'profile_name'):
        extra_info['profile_name'] = settings.profile_name

    logger.info("Initializing Genie conversation", extra=extra_info)

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
    client = get_user_client()
    settings = get_settings()
    space_id = settings.genie.space_id

    # Log with safe attribute access
    extra_info = {
        "space_id": space_id,
        "query": query[:100],  # First 100 chars
        "cache_info": str(get_settings.cache_info()),
    }
    # Safely add profile info if available
    if hasattr(settings, 'profile_id'):
        extra_info['profile_id'] = settings.profile_id
    if hasattr(settings, 'profile_name'):
        extra_info['profile_name'] = settings.profile_name

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
                    data_array = response_dict["result"]["data_array"]
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

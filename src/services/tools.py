"""
Tools for the slide generator agent.

This module implements tools that the agent can use to gather data and perform tasks.
"""

from typing import Any, Optional

import pandas as pd
from databricks.sdk import WorkspaceClient

from src.config.client import get_databricks_client
from src.config.settings import get_settings


class GenieToolError(Exception):
    """Raised when Genie tool execution fails."""

    pass




def query_genie_space(
    query: str,
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Query Databricks Genie space for data using natural language or SQL.

    This tool connects to a Databricks Genie space and executes queries to retrieve data.

    Args:
        query: Natural language question
        conversation_id: Optional conversation ID (not currently used with start_conversation_and_wait)

    Returns:
        Dictionary containing:
            - data: JSON string of the data
            - conversation_id: ID for the conversation

    Raises:
        GenieToolError: If query execution fails

    Example:
        >>> result = query_genie_space("show me a sample of data")
        >>> print(result['data'])
    """
    client = get_databricks_client()
    settings = get_settings()
    space_id = settings.genie.space_id



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
        attachment_ids = [_.attachment_id for _ in response.attachments]

        # Get query result from first attachment
        if not attachment_ids:
            raise GenieToolError("No attachments in response")

        attachment_response = client.genie.get_message_attachment_query_result(
            space_id=space_id,
            conversation_id=conversation_id,
            message_id=message_id,
            attachment_id=attachment_ids[0],
        )

        # Extract data and columns from response
        response_dict = attachment_response.as_dict()["statement_response"]
        columns = [_["name"] for _ in response_dict["manifest"]["schema"]["columns"]]
        data_array = response_dict["result"]["data_array"]

        # Create DataFrame and convert to records
        df = pd.DataFrame(data_array, columns=columns)
        data = df.to_json(orient="records")


        return {
            "data": data,
            "conversation_id": conversation_id
        }

    except Exception as e:
        raise GenieToolError(f"Failed to query Genie space: {e}") from e


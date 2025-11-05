"""
Tools for the slide generator agent.

This module implements tools that the agent can use to gather data and perform tasks.
All tools are instrumented with MLFlow tracing for observability.
"""

import time
from typing import Any, Optional

import mlflow
import pandas as pd
from databricks.sdk import WorkspaceClient

from src.config.client import get_databricks_client
from src.config.settings import get_settings


class GenieToolError(Exception):
    """Raised when Genie tool execution fails."""

    pass


@mlflow.trace(name="query_genie_space", span_type="TOOL")
def query_genie_space(
    query: str,
    conversation_id: Optional[str] = None,
    genie_space_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Query Databricks Genie space for data using natural language or SQL.

    This tool connects to a Databricks Genie space and executes queries to retrieve data.

    Args:
        query: Natural language question or SQL query to execute
        conversation_id: Optional conversation ID (not currently used with start_conversation_and_wait)
        genie_space_id: Optional Genie space ID (defaults to config value)

    Returns:
        Dictionary containing:
            - data: List of data dictionaries returned by the query
            - conversation_id: ID for the conversation
            - row_count: Number of rows returned
            - columns: List of column names
            - json_output: JSON string of the data
            - execution_time_seconds: Time taken to execute the query

    Raises:
        GenieToolError: If query execution fails

    Example:
        >>> result = query_genie_space("What were Q4 2023 sales?")
        >>> print(f"Retrieved {result['row_count']} rows")
        >>> print(result['data'])
    """
    client = get_databricks_client()
    settings = get_settings()
    space_id = genie_space_id or settings.genie.space_id

    start_time = time.time()

    # Set span attributes for tracing
    mlflow.set_span_attribute("genie.space_id", space_id)
    mlflow.set_span_attribute("genie.query", query[:200])  # Truncate for logging

    try:
        # Start conversation and wait for completion
        response = client.genie.start_conversation_and_wait(
            space_id=space_id, content=query
        )

        conversation_id = response.conversation_id
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
        json_output = df.to_json(orient="records")
        data = df.to_dict(orient="records")

        execution_time = time.time() - start_time
        row_count = len(data)

        # Log metrics to MLFlow
        mlflow.log_metrics(
            {
                "genie.result_row_count": row_count,
                "genie.execution_time_seconds": execution_time,
                "genie.success": 1,
            }
        )

        # Set additional span attributes
        mlflow.set_span_attribute("genie.row_count", row_count)
        mlflow.set_span_attribute("genie.execution_time_seconds", execution_time)
        mlflow.set_span_attribute("genie.column_count", len(columns))

        return {
            "data": data,
            "conversation_id": conversation_id,
            "row_count": row_count,
            "columns": columns,
            "json_output": json_output,
            "execution_time_seconds": execution_time,
        }

    except Exception as e:
        execution_time = time.time() - start_time

        # Log failure to MLFlow
        mlflow.log_metrics(
            {
                "genie.success": 0,
                "genie.execution_time_seconds": execution_time,
            }
        )
        mlflow.set_span_attribute("genie.error", str(e))
        mlflow.set_span_attribute("genie.error_type", type(e).__name__)

        raise GenieToolError(f"Failed to query Genie space: {e}") from e


def get_tool_schema() -> dict[str, Any]:
    """
    Get the tool schema for function calling.

    This schema is used by LLMs that support function/tool calling to understand
    what tools are available and how to call them.

    Returns:
        Dictionary containing tool schema in OpenAI function calling format
    """
    return {
        "type": "function",
        "function": {
            "name": "query_genie_space",
            "description": (
                "Query Databricks Genie space for data. Genie can understand natural language "
                "questions and convert them to SQL queries against the configured data sources. "
                "Use this tool whenever you need to retrieve data to answer the user's question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural language question or SQL query to execute. "
                            "Examples: 'What were sales in Q4 2023?', "
                            "'Show me top 10 customers by revenue'"
                        ),
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": (
                            "Optional conversation ID to continue an existing Genie conversation. "
                            "Use this to ask follow-up questions in the same context."
                        ),
                    },
                    "genie_space_id": {
                        "type": "string",
                        "description": (
                            "Optional Genie space ID. If not provided, uses the default "
                            "space configured in settings."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    }


def format_tool_result_for_llm(result: dict[str, Any]) -> str:
    """
    Format tool result for LLM consumption.

    Converts the raw tool result into a human-readable format that the LLM
    can easily understand and incorporate into its response.

    Args:
        result: Tool result dictionary from query_genie_space

    Returns:
        Formatted string representation of the result

    Example:
        >>> result = query_genie_space("What were Q4 sales?")
        >>> formatted = format_tool_result_for_llm(result)
        >>> print(formatted)
        Retrieved 5 rows in 2.3 seconds.
        SQL: SELECT * FROM sales WHERE quarter = 'Q4'
        Data:
        [...]
    """
    lines = []

    # Summary
    lines.append(
        f"Retrieved {result['row_count']} rows in "
        f"{result['execution_time_seconds']:.2f} seconds."
    )

    # SQL (if available)
    if result.get("sql"):
        lines.append(f"\nSQL: {result['sql']}")

    # Data
    if result["data"]:
        lines.append("\nData:")
        # Format data nicely (limit to first 100 rows for context window)
        data_preview = result["data"][:100]
        for i, row in enumerate(data_preview, 1):
            lines.append(f"{i}. {row}")

        if result["row_count"] > 100:
            lines.append(f"\n... and {result['row_count'] - 100} more rows")
    else:
        lines.append("\nNo data returned.")

    return "\n".join(lines)


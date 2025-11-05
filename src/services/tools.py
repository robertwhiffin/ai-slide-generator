"""
Tools for the slide generator agent.

This module implements tools that the agent can use to gather data and perform tasks.
All tools are instrumented with MLFlow tracing for observability.
"""

import time
from typing import Any, Optional

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.genie import MessageQuery

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
    It supports both starting new conversations and continuing existing ones.

    Args:
        query: Natural language question or SQL query to execute
        conversation_id: Optional conversation ID to continue an existing conversation
        genie_space_id: Optional Genie space ID (defaults to config value)

    Returns:
        Dictionary containing:
            - data: List of data rows returned by the query
            - conversation_id: ID for continuing the conversation
            - row_count: Number of rows returned
            - query_type: "natural_language" or "sql"
            - sql: The SQL statement that was executed (if available)
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
    mlflow.set_span_attribute("genie.has_conversation_id", conversation_id is not None)

    try:
        # Create or continue conversation
        if conversation_id is None:
            # Start new conversation
            conversation = client.genie.start_conversation(space_id=space_id)
            conversation_id = conversation.conversation_id
            mlflow.set_span_attribute("genie.new_conversation", True)
        else:
            mlflow.set_span_attribute("genie.new_conversation", False)

        # Execute query
        message = client.genie.execute_message_query(
            space_id=space_id,
            conversation_id=conversation_id,
            content=MessageQuery(query=query),
        )

        # Wait for completion (with timeout from settings)
        result = client.genie.wait_for_message_query(
            space_id=space_id,
            conversation_id=conversation_id,
            message_id=message.message_id,
            timeout=settings.genie.timeout if hasattr(settings.genie, "timeout") else 60,
        )

        # Extract data from result
        data = []
        sql_statement = None

        if result.attachments and len(result.attachments) > 0:
            attachment = result.attachments[0]
            if hasattr(attachment, "query_result") and attachment.query_result:
                # Extract data array
                if hasattr(attachment.query_result, "data_array"):
                    data = attachment.query_result.data_array or []

                # Extract SQL statement
                if hasattr(attachment.query_result, "statement_text"):
                    sql_statement = attachment.query_result.statement_text

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
        mlflow.set_span_attribute("genie.has_sql", sql_statement is not None)

        return {
            "data": data,
            "conversation_id": conversation_id,
            "row_count": row_count,
            "query_type": "natural_language",
            "sql": sql_statement,
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


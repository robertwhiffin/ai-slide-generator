"""
Unit tests for tools module with MLFlow tracing.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.services.tools import (
    GenieToolError,
    format_tool_result_for_llm,
    get_tool_schema,
    query_genie_space,
)


@pytest.fixture
def mock_databricks_client():
    """Mock Databricks client for testing."""
    with patch("src.services.tools.get_databricks_client") as mock_client:
        client = Mock()
        mock_client.return_value = client
        yield client


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch("src.services.tools.get_settings") as mock_settings_fn:
        settings = Mock()
        settings.genie.space_id = "test-space-id"
        settings.genie.timeout = 60
        mock_settings_fn.return_value = settings
        yield settings


@pytest.fixture
def mock_mlflow():
    """Mock MLFlow functions for testing."""
    with patch("src.services.tools.mlflow") as mock_mlflow:
        # Mock tracing decorator
        def trace_decorator(*args, **kwargs):
            def wrapper(func):
                return func

            return wrapper

        mock_mlflow.trace = trace_decorator
        mock_mlflow.set_span_attribute = Mock()
        mock_mlflow.log_metrics = Mock()
        yield mock_mlflow


def test_query_genie_space_success(mock_databricks_client, mock_settings, mock_mlflow):
    """Test successful Genie query."""
    # Setup mock conversation
    conversation = Mock()
    conversation.conversation_id = "conv-123"
    mock_databricks_client.genie.start_conversation.return_value = conversation

    # Setup mock message
    message = Mock()
    message.message_id = "msg-456"
    mock_databricks_client.genie.execute_message_query.return_value = message

    # Setup mock result with data
    result = Mock()
    attachment = Mock()
    query_result = Mock()
    query_result.data_array = [
        {"region": "APAC", "sales": 1000000},
        {"region": "EMEA", "sales": 800000},
    ]
    query_result.statement_text = "SELECT * FROM sales"
    attachment.query_result = query_result
    result.attachments = [attachment]

    mock_databricks_client.genie.wait_for_message_query.return_value = result

    # Execute query
    response = query_genie_space(query="What were Q4 sales?")

    # Verify response
    assert response["row_count"] == 2
    assert response["conversation_id"] == "conv-123"
    assert response["query_type"] == "natural_language"
    assert response["sql"] == "SELECT * FROM sales"
    assert len(response["data"]) == 2
    assert response["data"][0]["region"] == "APAC"

    # Verify client calls
    mock_databricks_client.genie.start_conversation.assert_called_once()
    mock_databricks_client.genie.execute_message_query.assert_called_once()
    mock_databricks_client.genie.wait_for_message_query.assert_called_once()


def test_query_genie_space_with_conversation_id(
    mock_databricks_client, mock_settings, mock_mlflow
):
    """Test Genie query continuing existing conversation."""
    # Setup mock message
    message = Mock()
    message.message_id = "msg-789"
    mock_databricks_client.genie.execute_message_query.return_value = message

    # Setup mock result
    result = Mock()
    result.attachments = []
    mock_databricks_client.genie.wait_for_message_query.return_value = result

    # Execute query with existing conversation ID
    response = query_genie_space(query="Show more details", conversation_id="existing-conv-id")

    # Verify conversation was not started (reused existing)
    mock_databricks_client.genie.start_conversation.assert_not_called()

    # Verify execute was called with existing conversation
    assert response["conversation_id"] == "existing-conv-id"


def test_query_genie_space_no_data(mock_databricks_client, mock_settings, mock_mlflow):
    """Test Genie query returning no data."""
    # Setup mock conversation
    conversation = Mock()
    conversation.conversation_id = "conv-empty"
    mock_databricks_client.genie.start_conversation.return_value = conversation

    # Setup mock message
    message = Mock()
    message.message_id = "msg-empty"
    mock_databricks_client.genie.execute_message_query.return_value = message

    # Setup mock result with no data
    result = Mock()
    result.attachments = []
    mock_databricks_client.genie.wait_for_message_query.return_value = result

    # Execute query
    response = query_genie_space(query="Non-existent data")

    # Verify response
    assert response["row_count"] == 0
    assert len(response["data"]) == 0


def test_query_genie_space_error(mock_databricks_client, mock_settings, mock_mlflow):
    """Test Genie query with error."""
    # Setup mock to raise exception
    mock_databricks_client.genie.start_conversation.side_effect = Exception("Connection error")

    # Execute query and expect error
    with pytest.raises(GenieToolError) as exc_info:
        query_genie_space(query="Test query")

    assert "Failed to query Genie space" in str(exc_info.value)


def test_get_tool_schema():
    """Test tool schema generation."""
    schema = get_tool_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "query_genie_space"
    assert "description" in schema["function"]
    assert "parameters" in schema["function"]

    params = schema["function"]["parameters"]
    assert params["type"] == "object"
    assert "query" in params["properties"]
    assert "conversation_id" in params["properties"]
    assert "genie_space_id" in params["properties"]
    assert params["required"] == ["query"]


def test_format_tool_result_for_llm():
    """Test formatting tool result for LLM."""
    result = {
        "data": [
            {"region": "APAC", "sales": 1000000},
            {"region": "EMEA", "sales": 800000},
        ],
        "row_count": 2,
        "sql": "SELECT * FROM sales",
        "execution_time_seconds": 2.5,
    }

    formatted = format_tool_result_for_llm(result)

    assert "Retrieved 2 rows" in formatted
    assert "2.50 seconds" in formatted
    assert "SELECT * FROM sales" in formatted
    assert "APAC" in formatted
    assert "EMEA" in formatted


def test_format_tool_result_no_data():
    """Test formatting empty tool result."""
    result = {
        "data": [],
        "row_count": 0,
        "sql": None,
        "execution_time_seconds": 1.0,
    }

    formatted = format_tool_result_for_llm(result)

    assert "Retrieved 0 rows" in formatted
    assert "No data returned" in formatted


def test_format_tool_result_truncation():
    """Test formatting tool result with many rows (should truncate)."""
    # Create result with > 100 rows
    data = [{"id": i, "value": f"val_{i}"} for i in range(150)]
    result = {
        "data": data,
        "row_count": 150,
        "sql": "SELECT * FROM large_table",
        "execution_time_seconds": 5.0,
    }

    formatted = format_tool_result_for_llm(result)

    assert "Retrieved 150 rows" in formatted
    assert "and 50 more rows" in formatted  # Should show truncation message


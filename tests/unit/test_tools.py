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
    # Setup mock conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-123"
    conversation_response.message_id = "msg-456"
    
    # Setup mock attachment
    attachment = Mock()
    attachment.attachment_id = "attach-789"
    conversation_response.attachments = [attachment]
    
    mock_databricks_client.genie.start_conversation_and_wait.return_value = conversation_response

    # Setup mock attachment query result
    attachment_result = Mock()
    attachment_result.as_dict.return_value = {
        "statement_response": {
            "manifest": {
                "schema": {
                    "columns": [
                        {"name": "region"},
                        {"name": "sales"}
                    ]
                }
            },
            "result": {
                "data_array": [
                    ["APAC", 1000000],
                    ["EMEA", 800000],
                ]
            }
        }
    }
    
    mock_databricks_client.genie.get_message_attachment_query_result.return_value = attachment_result

    # Execute query
    response = query_genie_space(query="What were Q4 sales?")

    # Verify response
    assert response["row_count"] == 2
    assert response["conversation_id"] == "conv-123"
    assert "columns" in response
    assert response["columns"] == ["region", "sales"]
    assert len(response["data"]) == 2
    assert response["data"][0]["region"] == "APAC"
    assert response["data"][0]["sales"] == 1000000
    assert "json_output" in response

    # Verify client calls
    mock_databricks_client.genie.start_conversation_and_wait.assert_called_once()
    mock_databricks_client.genie.get_message_attachment_query_result.assert_called_once()


def test_query_genie_space_no_attachments(
    mock_databricks_client, mock_settings, mock_mlflow
):
    """Test Genie query with no attachments (error case)."""
    # Setup mock conversation response with no attachments
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-123"
    conversation_response.message_id = "msg-456"
    conversation_response.attachments = []
    
    mock_databricks_client.genie.start_conversation_and_wait.return_value = conversation_response

    # Execute query and expect error
    with pytest.raises(GenieToolError) as exc_info:
        query_genie_space(query="Test query")

    assert "No attachments in response" in str(exc_info.value)


def test_query_genie_space_no_data(mock_databricks_client, mock_settings, mock_mlflow):
    """Test Genie query returning no data."""
    # Setup mock conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-empty"
    conversation_response.message_id = "msg-empty"
    
    attachment = Mock()
    attachment.attachment_id = "attach-empty"
    conversation_response.attachments = [attachment]
    
    mock_databricks_client.genie.start_conversation_and_wait.return_value = conversation_response

    # Setup mock attachment result with empty data
    attachment_result = Mock()
    attachment_result.as_dict.return_value = {
        "statement_response": {
            "manifest": {
                "schema": {
                    "columns": [
                        {"name": "col1"}
                    ]
                }
            },
            "result": {
                "data_array": []
            }
        }
    }
    
    mock_databricks_client.genie.get_message_attachment_query_result.return_value = attachment_result

    # Execute query
    response = query_genie_space(query="Non-existent data")

    # Verify response
    assert response["row_count"] == 0
    assert len(response["data"]) == 0


def test_query_genie_space_error(mock_databricks_client, mock_settings, mock_mlflow):
    """Test Genie query with error."""
    # Setup mock to raise exception
    mock_databricks_client.genie.start_conversation_and_wait.side_effect = Exception("Connection error")

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


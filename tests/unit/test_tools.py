"""
Unit tests for tools module with MLFlow tracing.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.services.tools import (
    GenieToolError,
    initialize_genie_conversation,
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


def test_query_genie_space_success(mock_databricks_client, mock_settings):
    """Test successful Genie query with both message and data."""
    # Setup mock conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-123"
    conversation_response.message_id = "msg-456"
    conversation_response.content = "Here are the Q4 sales results"
    
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

    # Verify response has all expected fields
    assert response["conversation_id"] == "conv-123"
    assert response["message"] == "Here are the Q4 sales results"
    assert "data" in response
    assert response["data"] is not None
    
    # Verify CSV format (should have header + 2 data rows)
    lines = response["data"].strip().split('\n')
    assert len(lines) == 3  # header + 2 data rows
    assert "region" in lines[0]
    assert "sales" in lines[0]

    # Verify client calls
    mock_databricks_client.genie.start_conversation_and_wait.assert_called_once()
    mock_databricks_client.genie.get_message_attachment_query_result.assert_called_once()


def test_query_genie_space_message_only(
    mock_databricks_client, mock_settings
):
    """Test Genie query with message only (no data attachment)."""
    # Setup mock conversation response with message but no attachments
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-123"
    conversation_response.message_id = "msg-456"
    conversation_response.content = "I understand your question about the data."
    conversation_response.attachments = []
    
    mock_databricks_client.genie.start_conversation_and_wait.return_value = conversation_response

    # Execute query - should succeed with message only
    response = query_genie_space(query="Test query")

    # Verify response has message but no data
    assert response["conversation_id"] == "conv-123"
    assert response["message"] == "I understand your question about the data."
    assert response["data"] is None
    
    # Verify no retry occurred (message-only is valid)
    assert mock_databricks_client.genie.start_conversation_and_wait.call_count == 1


def test_query_genie_space_retry_success(
    mock_databricks_client, mock_settings
):
    """Test Genie query succeeds after retry on error."""
    # First attempt: raise exception
    mock_databricks_client.genie.start_conversation_and_wait.side_effect = [
        Exception("Temporary error"),
        None  # Second attempt will use the next setup
    ]
    
    # Second response: success with data
    success_response = Mock()
    success_response.conversation_id = "conv-123"
    success_response.message_id = "msg-success"
    success_response.content = "Query successful"
    attachment = Mock()
    attachment.attachment_id = "attach-789"
    success_response.attachments = [attachment]
    
    # After first exception, second call succeeds
    mock_databricks_client.genie.start_conversation_and_wait.side_effect = [
        Exception("Temporary error"),
        success_response
    ]
    
    # Setup mock attachment result for successful attempt
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
                ]
            }
        }
    }
    mock_databricks_client.genie.get_message_attachment_query_result.return_value = attachment_result
    
    # Execute query
    response = query_genie_space(query="Test query")
    
    # Verify success after retry
    assert response["conversation_id"] == "conv-123"
    assert response["message"] == "Query successful"
    assert "data" in response
    assert response["data"] is not None
    
    # Verify CSV format
    lines = response["data"].strip().split('\n')
    assert len(lines) == 2  # header + 1 data row
    
    # Verify retry occurred (2 calls to start_conversation)
    assert mock_databricks_client.genie.start_conversation_and_wait.call_count == 2


def test_query_genie_space_empty_data(mock_databricks_client, mock_settings):
    """Test Genie query returning empty data array."""
    # Setup mock conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-empty"
    conversation_response.message_id = "msg-empty"
    conversation_response.content = "No data found for your query"
    
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

    # Verify response has message and data (empty CSV with just header)
    assert response["conversation_id"] == "conv-empty"
    assert response["message"] == "No data found for your query"
    assert "data" in response
    
    # CSV with empty data should just have header
    lines = response["data"].strip().split('\n')
    assert len(lines) == 1  # Only header, no data rows
    assert "col1" in lines[0]


def test_query_genie_space_error(mock_databricks_client, mock_settings):
    """Test Genie query with error."""
    # Setup mock to raise exception
    mock_databricks_client.genie.start_conversation_and_wait.side_effect = Exception("Connection error")

    # Execute query and expect error
    with pytest.raises(GenieToolError) as exc_info:
        query_genie_space(query="Test query")

    assert "Failed to query Genie space" in str(exc_info.value)


def test_initialize_genie_conversation_success(mock_databricks_client, mock_settings):
    """Test successful Genie conversation initialization."""
    # Setup mock conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-init-123"
    conversation_response.message_id = "msg-init-456"
    
    mock_databricks_client.genie.start_conversation_and_wait.return_value = conversation_response

    # Initialize conversation
    conversation_id = initialize_genie_conversation()

    # Verify conversation_id returned
    assert conversation_id == "conv-init-123"

    # Verify client called with correct parameters
    mock_databricks_client.genie.start_conversation_and_wait.assert_called_once_with(
        space_id="test-space-id",
        content="This is a system message to start a conversation."
    )


def test_initialize_genie_conversation_custom_message(mock_databricks_client, mock_settings):
    """Test Genie conversation initialization with custom message."""
    # Setup mock conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-custom-123"
    
    mock_databricks_client.genie.start_conversation_and_wait.return_value = conversation_response

    # Initialize conversation with custom message
    custom_message = "Custom initialization message"
    conversation_id = initialize_genie_conversation(placeholder_message=custom_message)

    # Verify conversation_id returned
    assert conversation_id == "conv-custom-123"

    # Verify client called with custom message
    mock_databricks_client.genie.start_conversation_and_wait.assert_called_once_with(
        space_id="test-space-id",
        content=custom_message
    )


def test_initialize_genie_conversation_error(mock_databricks_client, mock_settings):
    """Test Genie conversation initialization with error."""
    # Setup mock to raise exception
    mock_databricks_client.genie.start_conversation_and_wait.side_effect = Exception("Init error")

    # Execute and expect error
    with pytest.raises(GenieToolError) as exc_info:
        initialize_genie_conversation()

    assert "Failed to initialize Genie conversation" in str(exc_info.value)


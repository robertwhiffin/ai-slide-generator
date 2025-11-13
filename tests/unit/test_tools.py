"""
Unit tests for tools module with MLFlow tracing.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.services.tools import (
    GenieToolError,
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
    assert response["conversation_id"] == "conv-123"
    assert "data" in response
    
    # Parse JSON data
    data = json.loads(response["data"])
    assert len(data) == 2
    assert data[0]["region"] == "APAC"
    assert data[0]["sales"] == 1000000

    # Verify client calls
    mock_databricks_client.genie.start_conversation_and_wait.assert_called_once()
    mock_databricks_client.genie.get_message_attachment_query_result.assert_called_once()


def test_query_genie_space_no_attachments(
    mock_databricks_client, mock_settings
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


def test_query_genie_space_no_data(mock_databricks_client, mock_settings):
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
    assert "data" in response
    assert response["conversation_id"] == "conv-empty"
    
    # Parse JSON data
    data = json.loads(response["data"])
    assert len(data) == 0


def test_query_genie_space_error(mock_databricks_client, mock_settings):
    """Test Genie query with error."""
    # Setup mock to raise exception
    mock_databricks_client.genie.start_conversation_and_wait.side_effect = Exception("Connection error")

    # Execute query and expect error
    with pytest.raises(GenieToolError) as exc_info:
        query_genie_space(query="Test query")

    assert "Failed to query Genie space" in str(exc_info.value)


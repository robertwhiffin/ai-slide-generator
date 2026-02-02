"""
Integration tests for Genie tool.

These tests verify that the Genie tool works with a real Databricks Genie space.
Requires DATABRICKS_HOST and DATABRICKS_TOKEN environment variables.
"""

import os

import pytest

from src.core.databricks_client import get_databricks_client
from src.services.tools import GenieToolError, query_genie_space

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def check_databricks_connection():
    """
    Check if Databricks credentials are available via environment variables.
    Skip tests if not configured.
    """
    # Check for environment variables
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    
    if not host or not token:
        pytest.skip(
            "Databricks credentials not configured.\n"
            "Set DATABRICKS_HOST and DATABRICKS_TOKEN environment variables"
        )
    
    # Test connection
    try:
        ws = get_databricks_client()
        ws.current_user.me()  # Verify connection works
        print(f"✅ Connected to Databricks")
        return True
    except Exception as e:
        pytest.skip(f"Failed to connect to Databricks: {e}")


@pytest.fixture(scope="module")
def check_genie_config():
    """
    Check if Genie space is configured.
    Skip tests if not configured properly.
    """
    from src.core.settings_db import get_settings

    try:
        settings = get_settings()
        if not settings.genie or not settings.genie.space_id:
            pytest.skip("Genie space not configured. Create a profile with Genie space.")

        space_id = settings.genie.space_id
        if space_id == "01234567-89ab-cdef-0123-456789abcdef":
            pytest.skip("Genie space not configured. Set a real Genie space ID.")

        return space_id

    except Exception as e:
        pytest.skip(f"Failed to load Genie configuration: {e}")


def test_genie_conversation_continuation(check_databricks_connection, check_genie_config):
    """
    Test Genie conversation continuation.

    This tests that you can continue a conversation using the conversation_id.
    """
    # First query
    result1 = query_genie_space(query="show me a sample of data")
    conversation_id = result1["conversation_id"]

    print(f"   First query conversation ID: {conversation_id}")

    # Continue conversation with follow-up query
    result2 = query_genie_space(
        query="show a sample of data", conversation_id=conversation_id
    )

    # Both queries should have the same conversation ID
    assert result2["conversation_id"] == conversation_id

    # Both should have data or message
    assert result1.get("data") or result1.get("message")
    assert result2.get("data") or result2.get("message")
    
    if result1.get("data"):
        assert len(result1["data"]) > 0
    if result2.get("data"):
        assert len(result2["data"]) > 0

    print(f"✅ Conversation continuation test passed")
    print(f"   Same conversation ID: {result2['conversation_id']}")
    print(f"   Result 1 has: {'message' if result1.get('message') else ''} {'data' if result1.get('data') else ''}")
    print(f"   Result 2 has: {'message' if result2.get('message') else ''} {'data' if result2.get('data') else ''}")


def test_genie_natural_language_query(check_databricks_connection, check_genie_config):
    """
    Test Genie with a natural language query.

    This tests Genie's ability to understand natural language and convert to SQL.
    Note: This may fail if your Genie space doesn't have appropriate tables/data.
    """
    try:
        result = query_genie_space(query="Show me a sample of data")

        # Verify we got some result (message and/or data)
        assert "conversation_id" in result
        assert result.get("data") or result.get("message")

        print(f"✅ Natural language query test passed")
        print(f"   Query understood by Genie")
        if result.get("message"):
            print(f"   Message: {result['message'][:100]}")
        if result.get("data"):
            print(f"   Data returned: {len(result['data'])} characters")

    except GenieToolError as e:
        # If Genie can't understand the query or has no data, that's OK for this test
        if "no data" in str(e).lower() or "not found" in str(e).lower():
            pytest.skip(f"Genie space has no data or couldn't understand query: {e}")
        else:
            raise



if __name__ == "__main__":
    """
    Run Genie integration tests directly.

    Usage:
        python tests/integration/test_genie_integration.py
    """
    pytest.main([__file__, "-v", "-s", "-m", "integration"])


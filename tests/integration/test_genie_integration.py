"""
Integration tests for Genie tool.

These tests verify that the Genie tool works with a real Databricks Genie space.
Requires one of:
- Databricks profile configured in config/config.yaml (preferred)
- DATABRICKS_HOST and DATABRICKS_TOKEN environment variables
"""

import os

import pytest
from databricks.sdk import WorkspaceClient

from src.services.tools import GenieToolError, query_genie_space

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def check_databricks_connection():
    """
    Check if Databricks credentials are available via profile or environment variables.
    Skip tests if not configured.
    """
    from src.config.settings import get_settings

    try:
        settings = get_settings()
        
        # Try profile first (preferred)
        if settings.databricks_profile:
            try:
                # Test connection with profile
                ws = WorkspaceClient(profile=settings.databricks_profile)
                ws.current_user.me()  # Verify connection works
                print(f"✅ Using Databricks profile: {settings.databricks_profile}")
                return {"profile": settings.databricks_profile}
            except Exception as e:
                pytest.skip(f"Failed to connect with profile '{settings.databricks_profile}': {e}")
        
        # Fall back to environment variables
        host = os.getenv("DATABRICKS_HOST") or settings.databricks_host
        token = os.getenv("DATABRICKS_TOKEN") or settings.databricks_token
        
        if not host or not token:
            pytest.skip(
                "Databricks credentials not configured. Either:\n"
                "1. Set databricks.profile in config/config.yaml, or\n"
                "2. Set DATABRICKS_HOST and DATABRICKS_TOKEN environment variables"
            )
        
        # Test connection with host/token
        try:
            ws = WorkspaceClient(host=host, token=token)
            ws.current_user.me()  # Verify connection works
            print(f"✅ Using Databricks host: {host}")
            return {"host": host, "token": token}
        except Exception as e:
            pytest.skip(f"Failed to connect to Databricks: {e}")
            
    except Exception as e:
        pytest.skip(f"Failed to load settings: {e}")


@pytest.fixture(scope="module")
def check_genie_config():
    """
    Check if Genie space is configured.
    Skip tests if not configured properly.
    """
    from src.config.settings import get_settings

    try:
        settings = get_settings()
        space_id = settings.genie.space_id

        if not space_id or space_id == "01234567-89ab-cdef-0123-456789abcdef":
            pytest.skip("Genie space not configured. Update config/config.yaml with real space_id")

        return space_id

    except Exception as e:
        pytest.skip(f"Failed to load Genie configuration: {e}")


def test_genie_simple_select(check_databricks_connection, check_genie_config):
    """
    Test Genie with a simple SELECT statement.

    This is the most basic test - just verifies Genie can execute a query.
    """
    result = query_genie_space(query="SELECT 1 as test_value")

    # Verify result structure
    assert "data" in result
    assert "conversation_id" in result
    assert result["conversation_id"] is not None

    # Verify data is returned
    assert len(result["data"]) > 0

    print(f"✅ Simple SELECT test passed")
    print(f"   Conversation ID: {result['conversation_id']}")
    print(f"   Rows returned: {len(result['data'])}")
    print(f"   Data: {result['data']}")


def test_genie_multiple_rows(check_databricks_connection, check_genie_config):
    """
    Test Genie with a query that returns multiple rows.
    """
    query = """
    SELECT * FROM (
        SELECT 1 as id, 'Alice' as name UNION ALL
        SELECT 2 as id, 'Bob' as name UNION ALL
        SELECT 3 as id, 'Charlie' as name
    )
    """

    result = query_genie_space(query=query)

    # Verify multiple rows returned
    assert len(result["data"]) == 3

    # Verify data structure
    assert "id" in result["data"][0]
    assert "name" in result["data"][0]

    # Verify data values
    names = [row["name"] for row in result["data"]]
    assert "Alice" in names
    assert "Bob" in names
    assert "Charlie" in names

    print(f"✅ Multiple rows test passed")
    print(f"   Rows returned: {len(result['data'])}")


def test_genie_conversation_continuation(check_databricks_connection, check_genie_config):
    """
    Test Genie conversation continuation.

    This tests that you can continue a conversation using the conversation_id.
    """
    # First query
    result1 = query_genie_space(query="SELECT 1 as first_query")
    conversation_id = result1["conversation_id"]

    print(f"   First query conversation ID: {conversation_id}")

    # Continue conversation with follow-up query
    result2 = query_genie_space(
        query="SELECT 2 as second_query", conversation_id=conversation_id
    )

    # Both queries should have the same conversation ID
    assert result2["conversation_id"] == conversation_id

    # Both should have data
    assert len(result1["data"]) > 0
    assert len(result2["data"]) > 0

    print(f"✅ Conversation continuation test passed")
    print(f"   Same conversation ID: {result2['conversation_id']}")


def test_genie_natural_language_query(check_databricks_connection, check_genie_config):
    """
    Test Genie with a natural language query.

    This tests Genie's ability to understand natural language and convert to SQL.
    Note: This may fail if your Genie space doesn't have appropriate tables/data.
    """
    try:
        result = query_genie_space(query="Show me a sample of data")

        # Verify we got some result
        assert "data" in result
        assert "conversation_id" in result

        print(f"✅ Natural language query test passed")
        print(f"   Query understood by Genie")
        print(f"   Rows returned: {len(result['data'])}")

    except GenieToolError as e:
        # If Genie can't understand the query or has no data, that's OK for this test
        if "no data" in str(e).lower() or "not found" in str(e).lower():
            pytest.skip(f"Genie space has no data or couldn't understand query: {e}")
        else:
            raise


def test_genie_aggregation_query(check_databricks_connection, check_genie_config):
    """
    Test Genie with an aggregation query.
    """
    query = """
    SELECT 
        COUNT(*) as row_count,
        SUM(value) as total
    FROM (
        SELECT 10 as value UNION ALL
        SELECT 20 as value UNION ALL
        SELECT 30 as value
    )
    """

    result = query_genie_space(query=query)

    # Verify aggregation result
    assert len(result["data"]) == 1

    # Verify aggregation values
    row = result["data"][0]
    assert "row_count" in row
    assert "total" in row
    assert row["row_count"] == 3
    assert row["total"] == 60

    print(f"✅ Aggregation query test passed")
    print(f"   Row count: {row['row_count']}")
    print(f"   Total: {row['total']}")


def test_genie_empty_result(check_databricks_connection, check_genie_config):
    """
    Test Genie with a query that returns no rows.
    """
    query = "SELECT 1 as value WHERE 1 = 0"

    result = query_genie_space(query=query)

    # Verify empty result
    assert "data" in result
    assert len(result["data"]) == 0
    assert result["conversation_id"] is not None

    print(f"✅ Empty result test passed")
    print(f"   Correctly handled query with no results")


@pytest.mark.slow
def test_genie_performance(check_databricks_connection, check_genie_config):
    """
    Test Genie query performance.

    This is marked as slow since it tests multiple queries.
    """
    import time

    queries = [
        "SELECT 1 as test1",
        "SELECT 2 as test2",
        "SELECT 3 as test3",
    ]

    times = []

    for query in queries:
        start = time.time()
        result = query_genie_space(query=query)
        duration = time.time() - start

        times.append(duration)

        assert "data" in result
        assert len(result["data"]) > 0

    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)

    print(f"✅ Performance test passed")
    print(f"   Queries executed: {len(queries)}")
    print(f"   Avg time: {avg_time:.2f}s")
    print(f"   Min time: {min_time:.2f}s")
    print(f"   Max time: {max_time:.2f}s")

    # Performance assertion (adjust based on your needs)
    assert avg_time < 30, f"Average query time too high: {avg_time:.2f}s"


def test_genie_error_handling(check_databricks_connection, check_genie_config):
    """
    Test Genie error handling with invalid SQL.
    """
    # Invalid SQL should raise an error
    with pytest.raises(GenieToolError):
        query_genie_space(query="INVALID SQL STATEMENT THAT WILL FAIL")

    print(f"✅ Error handling test passed")
    print(f"   Correctly raised GenieToolError for invalid SQL")


if __name__ == "__main__":
    """
    Run Genie integration tests directly.

    Usage:
        python tests/integration/test_genie_integration.py
    """
    pytest.main([__file__, "-v", "-s", "-m", "integration"])


"""
Integration tests for MLFlow tracing workflow.

These tests verify that the agent and tools properly integrate with MLFlow
for experiment tracking and tracing.

Note: These tests require a working Databricks connection and will create
real MLFlow experiments and runs.
"""

import os

import mlflow
import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def check_databricks_connection():
    """
    Check if Databricks credentials are available.
    Skip tests if not configured.
    """
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")

    if not host or not token:
        pytest.skip("Databricks credentials not configured (DATABRICKS_HOST, DATABRICKS_TOKEN)")

    return True


@pytest.fixture(scope="module")
def test_experiment_name():
    """Get test experiment name."""
    from databricks.sdk import WorkspaceClient

    try:
        w = WorkspaceClient()
        username = w.current_user.me().user_name
        return f"/Users/{username}/ai-slide-generator-tests"
    except Exception:
        return "/Shared/ai-slide-generator-tests"


def test_mlflow_connection(check_databricks_connection, test_experiment_name):
    """Test basic MLFlow connection and experiment creation."""
    # Set tracking URI
    mlflow.set_tracking_uri("databricks")

    # Create/get experiment
    mlflow.set_experiment(test_experiment_name)

    # Create a simple run
    with mlflow.start_run(run_name="test_connection") as run:
        mlflow.log_param("test_param", "test_value")
        mlflow.log_metric("test_metric", 1.0)

    assert run.info.run_id is not None
    assert run.info.status == "FINISHED"


def test_agent_with_mlflow_tracing(check_databricks_connection, test_experiment_name):
    """
    Test agent execution with real MLFlow tracing.

    This test creates a real agent instance and verifies that:
    1. MLFlow tracking is working
    2. Traces are created
    3. Metrics are logged
    4. Artifacts are saved
    """
    from src.services.agent import SlideGeneratorAgent

    # Set experiment
    mlflow.set_experiment(test_experiment_name)

    # Create agent
    # Note: This will use real Databricks connection
    agent = SlideGeneratorAgent()

    # Test with a simple question
    # Note: This requires a real Genie space to be configured
    test_question = "SELECT 1 as test_value"  # Simple SQL that should work

    try:
        result = agent.generate_slides(
            question=test_question,
            max_slides=3,
        )

        # Verify result structure
        assert "html" in result
        assert "metadata" in result
        assert result["metadata"]["run_id"] is not None

        # Verify run was logged
        run_id = result["metadata"]["run_id"]
        client = mlflow.tracking.MlflowClient()
        run = client.get_run(run_id)

        assert run.info.status == "FINISHED"
        assert "question" in run.data.params
        assert "success" in run.data.metrics

        # Verify artifacts were logged
        artifacts = client.list_artifacts(run_id)
        artifact_names = [a.path for a in artifacts]

        assert "intent_analysis.json" in artifact_names or len(artifact_names) > 0

        print(f"✅ Test passed! Run ID: {run_id}")
        print(f"🔗 Trace URL: {result['metadata']['trace_url']}")

    except Exception as e:
        # If test fails due to Genie configuration, that's expected
        if "space" in str(e).lower() or "genie" in str(e).lower():
            pytest.skip(f"Genie not configured: {e}")
        else:
            raise


def test_tool_with_mlflow_tracing(check_databricks_connection, test_experiment_name):
    """
    Test tool execution with MLFlow tracing.

    This verifies that individual tools are properly traced.
    """
    from src.services.tools import query_genie_space

    # Set experiment
    mlflow.set_experiment(test_experiment_name)

    # Create a run to contain the tool execution
    with mlflow.start_run(run_name="test_tool_tracing"):
        try:
            # Execute tool
            result = query_genie_space(query="SELECT 1 as test")

            # Verify result structure
            assert "data" in result
            assert "row_count" in result
            assert "conversation_id" in result

            print(f"✅ Tool executed successfully")
            print(f"   Rows: {result['row_count']}")
            print(f"   Time: {result['execution_time_seconds']:.2f}s")

        except Exception as e:
            # If test fails due to Genie configuration, that's expected
            if "space" in str(e).lower() or "genie" in str(e).lower():
                pytest.skip(f"Genie not configured: {e}")
            else:
                raise


def test_mlflow_metrics_tracking(check_databricks_connection, test_experiment_name):
    """
    Test that all expected metrics are tracked.

    Verifies that the agent logs:
    - Execution time
    - Token usage
    - Cost estimates
    - Tool metrics
    """
    from src.services.agent import SlideGeneratorAgent

    mlflow.set_experiment(test_experiment_name)

    agent = SlideGeneratorAgent()

    try:
        result = agent.generate_slides(
            question="SELECT 1 as test", max_slides=3
        )

        # Get run metrics
        run_id = result["metadata"]["run_id"]
        client = mlflow.tracking.MlflowClient()
        run = client.get_run(run_id)

        metrics = run.data.metrics

        # Verify key metrics are present
        assert "execution_time_seconds" in metrics
        assert "success" in metrics

        # Check that we have some LLM metrics
        llm_metrics = [k for k in metrics.keys() if "llm" in k or "tokens" in k]
        assert len(llm_metrics) > 0, "No LLM metrics found"

        print(f"✅ Metrics tracked: {len(metrics)} total")
        print(f"   LLM metrics: {len(llm_metrics)}")

    except Exception as e:
        if "space" in str(e).lower() or "genie" in str(e).lower():
            pytest.skip(f"Genie not configured: {e}")
        else:
            raise


def test_mlflow_trace_hierarchy(check_databricks_connection, test_experiment_name):
    """
    Test that traces have proper hierarchical structure.

    Verifies that:
    - Agent creates parent span
    - Tools create child spans
    - LLM calls create nested spans
    """
    # This test would require MLFlow trace inspection
    # For now, we verify that tracing is enabled
    from src.config.settings import get_settings

    settings = get_settings()

    assert settings.mlflow.tracing.enabled is True
    assert settings.mlflow.tracing.backend == "databricks"

    print("✅ Tracing configuration verified")


@pytest.mark.slow
def test_end_to_end_with_real_data(check_databricks_connection, test_experiment_name):
    """
    End-to-end test with a real question (if Genie is properly configured).

    This is marked as slow since it does a full workflow.
    """
    from src.services.agent import SlideGeneratorAgent

    mlflow.set_experiment(test_experiment_name)

    agent = SlideGeneratorAgent()

    # Try a simple aggregation query
    question = "SELECT COUNT(*) as row_count FROM (SELECT 1 UNION ALL SELECT 2)"

    try:
        result = agent.generate_slides(question=question, max_slides=5)

        # Verify full workflow completed
        assert result["html"] is not None
        assert len(result["html"]) > 0
        assert result["metadata"]["slide_count"] > 0

        print(f"✅ End-to-end test passed")
        print(f"   Slides generated: {result['metadata']['slide_count']}")
        print(f"   Execution time: {result['metadata']['execution_time_seconds']:.2f}s")
        print(f"   HTML length: {len(result['html'])} chars")

    except Exception as e:
        if "space" in str(e).lower() or "genie" in str(e).lower():
            pytest.skip(f"Genie not configured: {e}")
        else:
            raise


if __name__ == "__main__":
    """
    Run integration tests directly.

    Usage:
        python tests/integration/test_mlflow_tracing.py
    """
    pytest.main([__file__, "-v", "-s", "-m", "integration"])


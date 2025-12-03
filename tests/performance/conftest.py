"""
Pytest fixtures for performance testing.

These fixtures provide MLflow integration and generator instances
for token comparison tests.

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

import os
from datetime import datetime
from typing import Generator

import mlflow
import pytest

from src.core.settings_db import get_settings


@pytest.fixture(scope="session")
def mlflow_experiment():
    """
    Set up MLflow experiment for test session.
    
    Uses the existing MLflow configuration from settings.
    Reuses the same experiment (no subfolder to avoid conflicts).
    """
    settings = get_settings()
    
    # Use Databricks tracking URI (same as production)
    mlflow.set_tracking_uri("databricks")
    
    # Use the same experiment as the main app (avoid subfolder issues)
    experiment_name = settings.mlflow.experiment_name
    experiment = mlflow.get_experiment_by_name(experiment_name)
    
    if experiment is None:
        experiment_id = mlflow.create_experiment(experiment_name)
    else:
        experiment_id = experiment.experiment_id
    
    mlflow.set_experiment(experiment_id=experiment_id)
    
    # Enable autologging for LangChain (captures token metrics)
    try:
        mlflow.langchain.autolog(
            log_input_examples=True,
            log_model_signatures=True,
            log_models=False,  # Don't save model artifacts
        )
    except Exception:
        pass  # Autolog may already be enabled
    
    yield experiment_id


@pytest.fixture
def original_agent():
    """
    Create original iterative agent for comparison.
    
    Yields:
        Tuple of (agent, session_id)
    """
    from src.services.agent import SlideGeneratorAgent
    
    agent = SlideGeneratorAgent()
    session_id = agent.create_session()
    
    yield agent, session_id
    
    # Cleanup
    try:
        agent.clear_session(session_id)
    except Exception:
        pass


@pytest.fixture
def two_stage_generator():
    """
    Create two-stage generator for comparison.
    
    Yields:
        Tuple of (generator, session_id)
    """
    from src.services.two_stage_generator import TwoStageGenerator
    
    generator = TwoStageGenerator()
    session_id = generator.create_session()
    
    yield generator, session_id
    
    # Cleanup
    try:
        generator.clear_session(session_id)
    except Exception:
        pass


@pytest.fixture
def test_run_id():
    """Generate unique test run ID for MLflow tagging."""
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


@pytest.fixture
def skip_if_no_databricks():
    """
    Skip test if Databricks credentials are not available.
    
    Useful for running tests in CI/CD environments.
    """
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    
    if not host or not token:
        pytest.skip("Databricks credentials not configured")


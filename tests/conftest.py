"""
Pytest configuration and shared fixtures.

This module provides fixtures that are available to all test modules.
"""

import os
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, Mock, patch

import pytest
from databricks.sdk import WorkspaceClient

from src.core.databricks_client import reset_client


@pytest.fixture(autouse=True)
def reset_singleton_client():
    """
    Reset singleton client before each test.

    This ensures tests don't interfere with each other.
    """
    reset_client()
    yield
    reset_client()


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    Clear settings cache before each test.

    This ensures each test gets fresh settings.
    """
    from src.core.settings_db import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_env_vars() -> Generator[dict[str, str], None, None]:
    """
    Provide mock environment variables for testing.

    Returns:
        Dictionary of environment variables
    """
    env_vars = {
        "DATABRICKS_HOST": "https://test.cloud.databricks.com",
        "DATABRICKS_TOKEN": "test-token-12345",
        "ENVIRONMENT": "test",
    }

    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """
    Create a temporary settings directory for testing.

    Args:
        tmp_path: Pytest-provided temporary directory

    Returns:
        Path to temporary settings directory
    """
    config_dir = tmp_path / "settings"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """
    Provide a sample configuration dictionary for testing.

    Returns:
        Sample configuration
    """
    return {
        "llm": {
            "endpoint": "test-endpoint",
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 0.95,
            "timeout": 120,
        },
        "genie": {
            "default_space_id": "test-space-id",
            "timeout": 60,
            "max_retries": 3,
            "retry_delay": 2,
            "poll_interval": 2,
        },
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "cors_enabled": True,
            "cors_origins": ["http://localhost:3000"],
            "request_timeout": 180,
            "max_concurrent_requests": 10,
        },
        "output": {
            "html_template": "professional",
            "include_metadata": True,
            "include_source_citations": True,
        },
        "logging": {
            "level": "INFO",
            "format": "json",
            "include_request_id": True,
            "log_file": "logs/app.log",
            "max_file_size_mb": 10,
            "backup_count": 5,
        },
        "features": {
            "enable_caching": False,
            "enable_streaming": False,
            "enable_batch_processing": False,
        },
        "environment": "test",
    }


@pytest.fixture
def sample_prompts() -> dict[str, Any]:
    """
    Provide sample prompts for testing.

    Returns:
        Sample prompts dictionary
    """
    return {
        "system_prompt": "You are a test assistant.",
        "intent_analysis": "Analyze this: {question}",
        "data_interpretation": "Interpret this: {data}",
        "narrative_construction": "Create narrative: {insights}",
        "html_generation": "Generate HTML: {narrative}",
        "genie_function_schema": {
            "name": "query_genie",
            "description": "Query Genie",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    }


@pytest.fixture
def mock_workspace_client() -> Generator[Mock, None, None]:
    """
    Provide a mocked Databricks WorkspaceClient.

    Returns:
        Mocked WorkspaceClient instance
    """
    mock_client = MagicMock(spec=WorkspaceClient)

    # Mock current_user.me() response
    mock_user = Mock()
    mock_user.user_name = "test@example.com"
    mock_user.id = "test-user-id"
    mock_client.current_user.me.return_value = mock_user

    with patch("src.core.databricks_client.WorkspaceClient", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_databricks_client(mock_workspace_client: Mock) -> Mock:
    """
    Alias for mock_workspace_client for convenience.

    Args:
        mock_workspace_client: Mocked workspace client

    Returns:
        Same mocked client
    """
    return mock_workspace_client


@pytest.fixture
def write_config_file(temp_config_dir: Path, sample_config: dict) -> Path:
    """
    Write a sample settings.yaml file.

    Args:
        temp_config_dir: Temporary settings directory
        sample_config: Configuration to write

    Returns:
        Path to written settings file
    """
    import yaml

    config_file = temp_config_dir / "settings.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config, f)

    return config_file


@pytest.fixture
def write_prompts_file(temp_config_dir: Path, sample_prompts: dict) -> Path:
    """
    Write a sample prompts.yaml file.

    Args:
        temp_config_dir: Temporary settings directory
        sample_prompts: Prompts to write

    Returns:
        Path to written prompts file
    """
    import yaml

    prompts_file = temp_config_dir / "prompts.yaml"
    with open(prompts_file, "w") as f:
        yaml.dump(sample_prompts, f)

    return prompts_file


@pytest.fixture
def mock_config_loader(
    sample_config: dict, sample_prompts: dict
) -> Generator[None, None, None]:
    """
    Mock the settings loader to return test data.

    Args:
        sample_config: Configuration to return
        sample_prompts: Prompts to return
    """
    with patch("src.core.config_loader.load_config", return_value=sample_config):
        with patch("src.core.config_loader.load_prompts", return_value=sample_prompts):
            yield


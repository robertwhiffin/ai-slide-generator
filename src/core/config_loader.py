"""
Configuration loader for YAML files.

This module handles loading and parsing YAML configuration files.
"""

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


def get_config_path(filename: str) -> Path:
    """
    Get the path to a configuration file.
    
    Searches for settings files in multiple locations:
    1. Current working directory (for Databricks Apps deployment)
    2. Relative to source file (for local development)

    Args:
        filename: Name of the settings file (e.g., 'settings.yaml')

    Returns:
        Path to the configuration file

    Raises:
        ConfigurationError: If settings file doesn't exist
    """
    # First, try current working directory (Databricks Apps deployment)
    cwd_config_path = Path.cwd() / "settings" / filename
    if cwd_config_path.exists():
        return cwd_config_path

    # Fall back to relative path (local development)
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    config_path = project_root / "settings" / filename

    if not config_path.exists():
        raise ConfigurationError(
            f"Configuration file not found: {config_path}. "
            f"Searched locations: {cwd_config_path}, {config_path}. "
            f"Please create it from settings.example.yaml"
        )

    return config_path


def load_yaml_file(file_path: Path) -> dict[str, Any]:
    """
    Load and parse a YAML file.

    Args:
        file_path: Path to the YAML file

    Returns:
        Parsed YAML content as a dictionary

    Raises:
        ConfigurationError: If file cannot be loaded or parsed
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        if content is None:
            raise ConfigurationError(f"YAML file is empty: {file_path}")

        if not isinstance(content, dict):
            raise ConfigurationError(
                f"YAML file must contain a dictionary at root level: {file_path}"
            )

        return content

    except yaml.YAMLError as e:
        raise ConfigurationError(f"Failed to parse YAML file {file_path}: {e}") from e
    except OSError as e:
        raise ConfigurationError(f"Failed to read file {file_path}: {e}") from e


def load_config() -> dict[str, Any]:
    """
    Load the main configuration file (settings.yaml).

    Returns:
        Configuration dictionary

    Raises:
        ConfigurationError: If settings cannot be loaded
    """
    config_path = get_config_path("settings.yaml")
    config = load_yaml_file(config_path)

    # Validate required top-level keys
    required_keys = ["llm", "genie", "api", "output", "logging"]
    missing_keys = [key for key in required_keys if key not in config]

    if missing_keys:
        raise ConfigurationError(
            f"Missing required configuration sections: {', '.join(missing_keys)}"
        )

    return config


def load_prompts() -> dict[str, Any]:
    """
    Load the prompts configuration file (prompts.yaml).

    Returns:
        Prompts dictionary

    Raises:
        ConfigurationError: If prompts cannot be loaded
    """
    prompts_path = get_config_path("prompts.yaml")
    prompts = load_yaml_file(prompts_path)

    # Validate required prompts
    required_prompts = [
        "system_prompt"
    ]
    missing_prompts = [key for key in required_prompts if key not in prompts]

    if missing_prompts:
        raise ConfigurationError(
            f"Missing required prompts: {', '.join(missing_prompts)}"
        )

    return prompts


def load_mlflow_config() -> dict[str, Any]:
    """
    Load the MLFlow configuration file (mlflow.yaml).

    Returns:
        MLFlow configuration dictionary

    Raises:
        ConfigurationError: If MLFlow settings cannot be loaded
    """
    mlflow_path = get_config_path("mlflow.yaml")
    mlflow_config = load_yaml_file(mlflow_path)

    # Validate required top-level keys
    required_keys = ["tracking", "tracing", "registry", "serving"]
    missing_keys = [key for key in required_keys if key not in mlflow_config]

    if missing_keys:
        raise ConfigurationError(
            f"Missing required MLFlow configuration sections: {', '.join(missing_keys)}"
        )

    return mlflow_config


def merge_with_env(config: dict[str, Any]) -> dict[str, Any]:
    """
    Merge configuration with environment variable overrides.

    Environment variables can override specific settings values:
    - API_PORT -> api.port
    - LOG_LEVEL -> logging.level
    - ENVIRONMENT -> environment

    Args:
        config: Base configuration dictionary

    Returns:
        Configuration with environment overrides applied
    """
    # Create a copy to avoid modifying the original
    merged = config.copy()

    # The following lines use the "walrus operator" (:=), which assigns the value to a variable as part of an expression.
    # This allows checking and assigning an environment variable in a single statement.
    # API overrides
    if port := os.getenv("API_PORT"):
        try:
            merged["api"]["port"] = int(port)
        except (ValueError, KeyError):
            pass

    # Logging overrides
    if log_level := os.getenv("LOG_LEVEL"):
        if "logging" in merged:
            merged["logging"]["level"] = log_level.upper()

    # Environment identifier
    if environment := os.getenv("ENVIRONMENT"):
        merged["environment"] = environment

    # Note: DATABRICKS_HOST and DATABRICKS_TOKEN are used directly by WorkspaceClient
    # and don't need to be stored in settings

    return merged


def reload_config() -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Reload both configuration and prompts files.

    This is useful for hot-reloading during development.

    Returns:
        Tuple of (settings, prompts) dictionaries

    Raises:
        ConfigurationError: If either file cannot be loaded
    """
    config = load_config()
    prompts = load_prompts()
    config = merge_with_env(config)

    return config, prompts


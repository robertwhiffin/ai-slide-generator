"""Load deployment configuration from YAML.

This module provides utilities to load environment-specific deployment
configurations from config/deployment.yaml.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
import yaml
import os


@dataclass
class DeploymentConfig:
    """Deployment configuration for a specific environment."""

    app_name: str
    description: str
    workspace_path: str
    permissions: List[Dict[str, str]]
    compute_size: str  # MEDIUM, LARGE, or LIQUID
    env_vars: Dict[str, str]

    # Common settings
    exclude_patterns: List[str]
    timeout_seconds: int
    poll_interval_seconds: int


def load_deployment_config(env: str) -> DeploymentConfig:
    """
    Load deployment configuration for specified environment.

    Args:
        env: Environment name (development, staging, production)

    Returns:
        DeploymentConfig for the specified environment

    Raises:
        ValueError: If environment not found in config
        FileNotFoundError: If deployment.yaml not found
    """
    # Try deployment.yaml first, fall back to example
    config_path = Path(__file__).parent.parent / "config" / "deployment.yaml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config" / "deployment.example.yaml"
        print(
            f"Warning: deployment.yaml not found, using deployment.example.yaml. "
            f"Copy it to deployment.yaml and customize for your workspace."
        )

    if not config_path.exists():
        raise FileNotFoundError(f"Deployment config not found: {config_path}")

    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)

    if env not in config_data["environments"]:
        available = list(config_data["environments"].keys())
        raise ValueError(f"Unknown environment: {env}. Available: {available}")

    env_config = config_data["environments"][env]
    common_config = config_data["common"]

    config = DeploymentConfig(
        app_name=env_config["app_name"],
        description=env_config.get("description", "AI Slide Generator"),
        workspace_path=env_config["workspace_path"],
        permissions=env_config["permissions"],
        compute_size=env_config.get("compute_size", "MEDIUM"),
        env_vars=env_config["env_vars"],
        exclude_patterns=common_config["build"]["exclude_patterns"],
        timeout_seconds=common_config["deployment"]["timeout_seconds"],
        poll_interval_seconds=common_config["deployment"]["poll_interval_seconds"],
    )

    return config


"""Load deployment configuration from YAML.

This module provides utilities to load environment-specific deployment
configurations from config/deployment.yaml.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
import yaml


@dataclass
class LakebaseConfig:
    """Lakebase OLTP database configuration.

    Attributes:
        database_name: Name of the Lakebase instance
        schema: PostgreSQL schema for application tables
        capacity: Instance capacity units (CU_1, CU_2, CU_4, CU_8)
    """

    database_name: str
    schema: str = "app_data"
    capacity: str = "CU_1"


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

    # Lakebase configuration (required)
    lakebase: LakebaseConfig


def load_deployment_config(env: str) -> DeploymentConfig:
    """Load deployment configuration for specified environment.

    Args:
        env: Environment name (development, staging, production)

    Returns:
        DeploymentConfig for the specified environment

    Raises:
        ValueError: If environment not found or required config missing
        FileNotFoundError: If deployment.yaml not found
    """
    config_path = Path(__file__).parent.parent / "config" / "deployment.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Deployment settings not found: {config_path}")

    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)

    if env not in config_data["environments"]:
        available = list(config_data["environments"].keys())
        raise ValueError(f"Unknown environment: {env}. Available: {available}")

    env_config = config_data["environments"][env]
    common = config_data["common"]

    # Validate lakebase config
    lakebase = env_config.get("lakebase", {})
    if not lakebase.get("database_name"):
        raise ValueError(f"Lakebase 'database_name' not configured for '{env}'")

    return DeploymentConfig(
        app_name=env_config["app_name"],
        description=env_config.get("description", "AI Slide Generator"),
        workspace_path=env_config["workspace_path"],
        permissions=env_config["permissions"],
        compute_size=env_config.get("compute_size", "MEDIUM"),
        env_vars=env_config["env_vars"],
        exclude_patterns=common["build"]["exclude_patterns"],
        timeout_seconds=common["deployment"]["timeout_seconds"],
        poll_interval_seconds=common["deployment"]["poll_interval_seconds"],
        lakebase=LakebaseConfig(
            database_name=lakebase["database_name"],
            schema=lakebase.get("schema", "app_data"),
            capacity=lakebase.get("capacity", "SMALL"),
        ),
    )

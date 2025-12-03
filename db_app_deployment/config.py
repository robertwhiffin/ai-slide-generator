"""Load deployment configuration from YAML.

This module provides utilities to load environment-specific deployment
configurations from config/deployment.yaml and config/lakebase.yaml.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
import yaml


@dataclass
class LakebaseConfig:
    """Lakebase database configuration."""

    catalog: str
    database_name: str
    schema: str = "app_data"


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
    """
    Load deployment configuration for specified environment.

    Args:
        env: Environment name (development, staging, production)

    Returns:
        DeploymentConfig for the specified environment

    Raises:
        ValueError: If environment not found in settings
        FileNotFoundError: If deployment.yaml not found
    """
    config_dir = Path(__file__).parent.parent / "config"

    # Load deployment.yaml (version controlled)
    deployment_path = config_dir / "deployment.yaml"

    if not deployment_path.exists():
        raise FileNotFoundError(f"Deployment settings not found: {deployment_path}")

    with open(deployment_path, "r") as f:
        config_data = yaml.safe_load(f)

    if env not in config_data["environments"]:
        available = list(config_data["environments"].keys())
        raise ValueError(f"Unknown environment: {env}. Available: {available}")

    env_config = config_data["environments"][env]
    common_config = config_data["common"]

    # Load Lakebase configuration
    lakebase_config = _load_lakebase_config(config_dir, env)

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
        lakebase=lakebase_config,
    )

    return config


def _load_lakebase_config(config_dir: Path, env: str) -> LakebaseConfig:
    """
    Load Lakebase configuration for the specified environment.

    Args:
        config_dir: Path to the config directory
        env: Environment name

    Returns:
        LakebaseConfig for the environment

    Raises:
        FileNotFoundError: If lakebase.yaml not found
        ValueError: If required configuration is missing
    """
    lakebase_path = config_dir / "lakebase.yaml"

    if not lakebase_path.exists():
        raise FileNotFoundError(
            f"Lakebase configuration not found: {lakebase_path}. "
            "Lakebase is required for deployment."
        )

    with open(lakebase_path, "r") as f:
        lakebase_data = yaml.safe_load(f)

    # Get base configuration
    base_config = lakebase_data.get("lakebase", {})

    # Check for environment-specific overrides
    env_overrides = lakebase_data.get("environments", {}).get(env, {})

    # Merge base with environment overrides
    catalog = env_overrides.get("catalog", base_config.get("catalog"))
    database_name = env_overrides.get("database_name", base_config.get("database_name"))
    schema = env_overrides.get("schema", base_config.get("schema", "app_data"))

    if not catalog:
        raise ValueError(
            f"Lakebase 'catalog' not configured for environment '{env}'. "
            "Add catalog to config/lakebase.yaml."
        )

    if not database_name:
        raise ValueError(
            f"Lakebase 'database_name' not configured for environment '{env}'. "
            "Add database_name to config/lakebase.yaml."
        )

    return LakebaseConfig(
        catalog=catalog,
        database_name=database_name,
        schema=schema,
    )


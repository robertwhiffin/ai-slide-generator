"""Local development deployment for Databricks Apps.

This script enables deploying the AI Slide Generator to Databricks Apps
using locally-built wheels instead of PyPI packages.

Usage:
    python -m scripts.deploy_local --create --env development --profile my-profile
    python -m scripts.deploy_local --update --env development --profile my-profile
    python -m scripts.deploy_local --update --env development --profile my-profile --reset-db
    python -m scripts.deploy_local --delete --env development --profile my-profile
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment
from databricks.sdk.service.workspace import ImportFormat

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "databricks-tellr"))

from databricks_tellr.deploy import (
    DeploymentError,
    _get_workspace_client,
    _get_or_create_lakebase,
    _write_requirements,
    _write_app_yaml,
    _upload_files,
    _create_app,
    _deploy_app,
    _setup_database_schema,
    _reset_schema,
    _get_app_client_id,
    delete,
)


def load_deployment_config(env: str) -> dict[str, Any]:
    """Load deployment configuration for the specified environment.

    Args:
        env: Environment name (development, staging, production)

    Returns:
        Dictionary with deployment configuration
    """
    config_path = PROJECT_ROOT / "config" / "deployment.yaml"

    if not config_path.exists():
        raise DeploymentError(f"Deployment config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    environments = config.get("environments", {})
    if env not in environments:
        available = ", ".join(environments.keys())
        raise DeploymentError(
            f"Environment '{env}' not found in deployment config. "
            f"Available: {available}"
        )

    env_config = environments[env]
    lakebase_config = env_config.get("lakebase", {})

    return {
        "app_name": env_config.get("app_name"),
        "description": env_config.get("description", "AI Slide Generator"),
        "workspace_path": env_config.get("workspace_path"),
        "compute_size": env_config.get("compute_size", "MEDIUM"),
        "lakebase_name": lakebase_config.get("database_name"),
        "lakebase_capacity": lakebase_config.get("capacity", "CU_1"),
        "schema_name": lakebase_config.get("schema"),
    }


def find_app_wheel() -> Path:
    """Find the built databricks-tellr-app wheel.

    Returns:
        Path to the wheel file

    Raises:
        DeploymentError: If wheel not found
    """
    app_dist = PROJECT_ROOT / "packages" / "databricks-tellr-app" / "dist"

    if not app_dist.exists():
        raise DeploymentError(
            f"No dist directory found at {app_dist}. "
            "Run scripts/build_wheels.sh first."
        )

    wheels = list(app_dist.glob("*.whl"))
    if not wheels:
        raise DeploymentError(
            f"No wheel files found in {app_dist}. "
            "Run scripts/build_wheels.sh first."
        )

    # Return the most recently modified wheel
    return max(wheels, key=lambda p: p.stat().st_mtime)


def upload_wheel(
    ws: WorkspaceClient,
    wheel_path: Path,
    workspace_path: str,
) -> str:
    """Upload wheel to Databricks workspace.

    Args:
        ws: WorkspaceClient
        wheel_path: Local path to the wheel file
        workspace_path: Base workspace path for the app

    Returns:
        Relative path to use in requirements.txt (e.g., "./wheels/package.whl")
    """
    wheels_dir = f"{workspace_path}/wheels"

    # Ensure wheels directory exists
    try:
        ws.workspace.mkdirs(wheels_dir)
    except Exception:
        pass  # May already exist

    # Clean old wheels to ensure only latest version is present
    try:
        objects = ws.workspace.list(wheels_dir)
        for obj in objects:
            if obj.path and obj.path.endswith(".whl"):
                ws.workspace.delete(obj.path)
                print(f"   Removed old wheel: {Path(obj.path).name}")
    except Exception:
        pass  # Directory might not exist yet

    # Upload new wheel
    wheel_dest = f"{wheels_dir}/{wheel_path.name}"
    with open(wheel_path, "rb") as f:
        ws.workspace.upload(
            wheel_dest,
            f,
            format=ImportFormat.AUTO,
            overwrite=True,
        )

    return f"./wheels/{wheel_path.name}"


def create_local(
    env: str,
    profile: str,
    seed_databricks_defaults: bool = True,
) -> dict[str, Any]:
    """Create a new Databricks App using locally-built wheels.

    Args:
        env: Environment name (development, staging, production)
        profile: Databricks CLI profile name
        seed_databricks_defaults: If True, seed Databricks-specific content

    Returns:
        Dictionary with deployment info
    """
    config = load_deployment_config(env)
    ws = _get_workspace_client(profile=profile)

    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
    lakebase_name = config["lakebase_name"]
    schema_name = config["schema_name"]

    print("Deploying AI Slide Generator (local wheels)...")
    print(f"   App name: {app_name}")
    print(f"   Workspace path: {workspace_path}")
    print(f"   Lakebase: {lakebase_name}")
    print(f"   Schema: {schema_name}")
    print()

    try:
        # Find and upload wheel
        print("Finding built wheel...")
        wheel_path = find_app_wheel()
        print(f"   Found: {wheel_path.name}")

        print("Uploading wheel to workspace...")
        local_wheel_ref = upload_wheel(ws, wheel_path, workspace_path)
        print(f"   Uploaded: {local_wheel_ref}")
        print()

        # Create Lakebase instance
        print("Setting up Lakebase database...")
        lakebase_result = _get_or_create_lakebase(
            ws, lakebase_name, config["lakebase_capacity"]
        )
        print(f"   Lakebase: {lakebase_result['name']} ({lakebase_result['status']})")
        print()

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_local_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
            )
            print("   Generated app.yaml")

            print(f"Uploading to: {workspace_path}")
            _upload_files(ws, staging_dir, workspace_path)
            print("   Files uploaded")
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
        print()

        # Create app
        print(f"Creating Databricks App: {app_name}")
        app = _create_app(
            ws,
            app_name=app_name,
            description=config["description"],
            workspace_path=workspace_path,
            compute_size=config["compute_size"],
            lakebase_name=lakebase_name,
        )
        print("   App registered")
        print()

        # Set up database schema
        print("Setting up database schema...")
        _setup_database_schema(ws, app, lakebase_name, schema_name)
        print(f"   Schema '{schema_name}' configured")
        print()

        # Deploy the app
        print("Deploying app...")
        app = _deploy_app(ws, app_name, workspace_path)
        print("   App deployed")
        if app.url:
            print(f"   URL: {app.url}")
        print()

        print("Deployment complete!")
        return {
            "url": app.url,
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "schema_name": schema_name,
            "wheel": wheel_path.name,
            "status": "created",
        }

    except Exception as e:
        raise DeploymentError(f"Deployment failed: {e}") from e


def update_local(
    env: str,
    profile: str,
    reset_database: bool = False,
    seed_databricks_defaults: bool = True,
) -> dict[str, Any]:
    """Update an existing Databricks App using locally-built wheels.

    Args:
        env: Environment name (development, staging, production)
        profile: Databricks CLI profile name
        reset_database: If True, drop and recreate the schema
        seed_databricks_defaults: If True, seed Databricks-specific content

    Returns:
        Dictionary with deployment info
    """
    config = load_deployment_config(env)
    ws = _get_workspace_client(profile=profile)

    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
    lakebase_name = config["lakebase_name"]
    schema_name = config["schema_name"]

    print(f"Updating AI Slide Generator (local wheels): {app_name}")
    print()

    try:
        # Reset database if requested
        if reset_database:
            print("Resetting database schema...")
            app = ws.apps.get(name=app_name)
            _reset_schema(ws, app, lakebase_name, schema_name)
            print(f"   Schema '{schema_name}' reset")
            print()

        # Find and upload wheel
        print("Finding built wheel...")
        wheel_path = find_app_wheel()
        print(f"   Found: {wheel_path.name}")

        print("Uploading wheel to workspace...")
        local_wheel_ref = upload_wheel(ws, wheel_path, workspace_path)
        print(f"   Uploaded: {local_wheel_ref}")
        print()

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_local_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
            )
            print("   Generated app.yaml")

            _upload_files(ws, staging_dir, workspace_path)
            print("   Files updated")
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        # Deploy new version
        print("   Deploying...")
        deployment = AppDeployment(source_code_path=workspace_path)
        result = ws.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)
        print(f"   Deployment completed: {result.deployment_id}")

        app = ws.apps.get(name=app_name)
        if app.url:
            print(f"   URL: {app.url}")

        return {
            "url": app.url,
            "app_name": app_name,
            "deployment_id": result.deployment_id,
            "wheel": wheel_path.name,
            "status": "updated",
            "database_reset": reset_database,
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e


def delete_local(env: str, profile: str, reset_database: bool = False) -> dict[str, Any]:
    """Delete a Databricks App.

    Args:
        env: Environment name (development, staging, production)
        profile: Databricks CLI profile name
        reset_database: If True, drop the schema before deleting

    Returns:
        Dictionary with deletion status
    """
    config = load_deployment_config(env)

    return delete(
        app_name=config["app_name"],
        lakebase_name=config["lakebase_name"],
        schema_name=config["schema_name"],
        reset_database=reset_database,
        profile=profile,
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy AI Slide Generator to Databricks Apps using local wheels"
    )

    parser.add_argument(
        "--env",
        type=str,
        required=True,
        choices=["development", "staging", "production"],
        help="Environment to deploy to",
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--create",
        action="store_const",
        const="create",
        dest="action",
        help="Create new app",
    )
    action_group.add_argument(
        "--update",
        action="store_const",
        const="update",
        dest="action",
        help="Update existing app",
    )
    action_group.add_argument(
        "--delete",
        action="store_const",
        const="delete",
        dest="action",
        help="Delete app",
    )

    parser.add_argument(
        "--profile",
        type=str,
        required=True,
        help="Databricks CLI profile name from ~/.databrickscfg",
    )

    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Drop and recreate database schema (WARNING: deletes all data)",
    )

    parser.add_argument(
        "--include-databricks-prompts",
        action="store_true",
        help="Include Databricks-specific content when seeding (for internal use)",
    )

    args = parser.parse_args()

    # Clear environment variables that would override profile settings
    env_vars_to_clear = [
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
    ]
    for var in env_vars_to_clear:
        if var in os.environ:
            del os.environ[var]

    try:
        if args.action == "create":
            result = create_local(
                env=args.env,
                profile=args.profile,
                seed_databricks_defaults=args.include_databricks_prompts,
            )
        elif args.action == "update":
            result = update_local(
                env=args.env,
                profile=args.profile,
                reset_database=args.reset_db,
                seed_databricks_defaults=args.include_databricks_prompts,
            )
        elif args.action == "delete":
            result = delete_local(
                env=args.env,
                profile=args.profile,
                reset_database=args.reset_db,
            )
        else:
            raise ValueError(f"Unknown action: {args.action}")

        print()
        print(f"Result: {result}")

    except DeploymentError as e:
        print(f"Deployment failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

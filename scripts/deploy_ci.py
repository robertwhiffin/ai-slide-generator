"""CI deployment script for Databricks Apps integration testing.

This script enables create/update/delete lifecycle testing of the AI Slide
Generator on Databricks Apps in CI. Unlike deploy_local.py, this script:
- Takes all config via CLI arguments (no deployment.yaml)
- Authenticates via DATABRICKS_HOST/DATABRICKS_TOKEN env vars (no --profile)
- Includes verification actions to confirm resources are truly deleted
- Deletes Lakebase instances as part of cleanup

Usage:
    python -m scripts.deploy_ci --create --app-name X --workspace-path /path \\
        --lakebase-name X --schema X
    python -m scripts.deploy_ci --update --app-name X --workspace-path /path \\
        --lakebase-name X --schema X
    python -m scripts.deploy_ci --delete --app-name X --lakebase-name X --schema X
    python -m scripts.deploy_ci --verify-deleted --app-name X
    python -m scripts.deploy_ci --verify-lakebase-deleted --lakebase-name X
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment
from databricks.sdk.service.workspace import ImportFormat

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "databricks-tellr"))

from databricks_tellr.deploy import (  # noqa: E402
    DeploymentError,
    _create_app,
    _deploy_app,
    _get_or_create_lakebase,
    _reset_schema,
    _setup_database_schema,
    _upload_files,
    _write_app_yaml,
    _write_requirements,
)


def _get_client() -> WorkspaceClient:
    """Get WorkspaceClient using env vars (DATABRICKS_HOST, DATABRICKS_TOKEN)."""
    return WorkspaceClient()


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
            f"No dist directory found at {app_dist}. Run scripts/build_wheels.sh first."
        )

    wheels = list(app_dist.glob("*.whl"))
    if not wheels:
        raise DeploymentError(
            f"No wheel files found in {app_dist}. Run scripts/build_wheels.sh first."
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


def create_ci(
    app_name: str,
    workspace_path: str,
    lakebase_name: str,
    schema_name: str,
    lakebase_capacity: str = "CU_1",
    compute_size: str = "MEDIUM",
) -> dict[str, Any]:
    """Create a new Databricks App for CI testing.

    Args:
        app_name: Unique app name (includes run ID suffix)
        workspace_path: Databricks workspace path for app files
        lakebase_name: Lakebase instance name (includes run ID suffix)
        schema_name: Schema name (includes run ID suffix)
        lakebase_capacity: Lakebase compute capacity
        compute_size: App compute size

    Returns:
        Dictionary with deployment info
    """
    ws = _get_client()

    print("Deploying AI Slide Generator (CI)...")
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
        lakebase_result = _get_or_create_lakebase(ws, lakebase_name, lakebase_capacity)
        print(f"   Lakebase: {lakebase_result['name']} ({lakebase_result['status']})")
        print()

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_ci_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=False,
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
            description="AI Slide Generator (CI)",
            workspace_path=workspace_path,
            compute_size=compute_size,
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
        raise DeploymentError(f"Create failed: {e}") from e


def update_ci(
    app_name: str,
    workspace_path: str,
    lakebase_name: str,
    schema_name: str,
) -> dict[str, Any]:
    """Update an existing Databricks App for CI testing.

    Args:
        app_name: App name to update
        workspace_path: Databricks workspace path for app files
        lakebase_name: Lakebase instance name
        schema_name: Schema name

    Returns:
        Dictionary with deployment info
    """
    ws = _get_client()

    print(f"Updating AI Slide Generator (CI): {app_name}")
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

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_ci_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=False,
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
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e


def delete_ci(
    app_name: str,
    lakebase_name: str,
    schema_name: str,
) -> dict[str, Any]:
    """Delete a CI Databricks App, its schema, and its Lakebase instance.

    Each step tolerates "not found" errors.

    Args:
        app_name: App name to delete
        lakebase_name: Lakebase instance name to delete
        schema_name: Schema name to drop

    Returns:
        Dictionary with deletion status
    """
    ws = _get_client()

    print(f"Deleting CI app: {app_name}")

    try:
        # Drop the schema
        print("Dropping database schema...")
        try:
            app = ws.apps.get(name=app_name)
            _reset_schema(ws, app, lakebase_name, schema_name, drop_only=True)
            print(f"   Schema '{schema_name}' dropped")
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "does not exist" in error_str:
                print("   Schema drop skipped (app or Lakebase not found)")
            else:
                print(f"   Schema drop skipped: {e}")

        # Delete the app
        print("Deleting app...")
        try:
            ws.apps.delete(name=app_name)
            print("   App deleted")
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "does not exist" in error_str:
                print("   App already deleted")
            else:
                raise

        # Delete the Lakebase instance
        print(f"Deleting Lakebase instance: {lakebase_name}...")
        try:
            ws.database.delete_database_instance(name=lakebase_name, purge=True)
            print("   Lakebase instance deleted")
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "does not exist" in error_str:
                print("   Lakebase instance already deleted")
            else:
                raise

        return {
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "status": "deleted",
        }

    except Exception as e:
        raise DeploymentError(f"Delete failed: {e}") from e


def verify_app_deleted(app_name: str) -> None:
    """Verify that a Databricks App no longer exists.

    Args:
        app_name: App name to verify is deleted

    Raises:
        DeploymentError: If the app still exists
    """
    ws = _get_client()

    print(f"Verifying app deleted: {app_name}")
    try:
        app = ws.apps.get(name=app_name)
        raise DeploymentError(f"App '{app_name}' still exists (status: {app.status})")
    except DeploymentError:
        raise
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            print(f"   Confirmed: app '{app_name}' does not exist")
        else:
            raise DeploymentError(f"Verification failed with unexpected error: {e}") from e


def verify_lakebase_deleted(lakebase_name: str) -> None:
    """Verify that a Lakebase instance no longer exists.

    Args:
        lakebase_name: Lakebase instance name to verify is deleted

    Raises:
        DeploymentError: If the instance still exists
    """
    ws = _get_client()

    print(f"Verifying Lakebase deleted: {lakebase_name}")
    try:
        instance = ws.database.get_database_instance(name=lakebase_name)
        raise DeploymentError(f"Lakebase '{lakebase_name}' still exists (state: {instance.state})")
    except DeploymentError:
        raise
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            print(f"   Confirmed: Lakebase '{lakebase_name}' does not exist")
        else:
            raise DeploymentError(f"Verification failed with unexpected error: {e}") from e


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CI deployment script for Databricks Apps integration testing"
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--create",
        action="store_const",
        const="create",
        dest="action",
        help="Create new app with Lakebase",
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
        help="Delete app, schema, and Lakebase instance",
    )
    action_group.add_argument(
        "--verify-deleted",
        action="store_const",
        const="verify_deleted",
        dest="action",
        help="Verify app is deleted",
    )
    action_group.add_argument(
        "--verify-lakebase-deleted",
        action="store_const",
        const="verify_lakebase_deleted",
        dest="action",
        help="Verify Lakebase instance is deleted",
    )

    parser.add_argument("--app-name", type=str, help="Databricks App name")
    parser.add_argument("--workspace-path", type=str, help="Workspace path for app files")
    parser.add_argument("--lakebase-name", type=str, help="Lakebase instance name")
    parser.add_argument("--schema", type=str, help="Database schema name")
    parser.add_argument(
        "--lakebase-capacity",
        type=str,
        default="CU_1",
        help="Lakebase capacity (default: CU_1)",
    )
    parser.add_argument(
        "--compute-size",
        type=str,
        default="MEDIUM",
        help="App compute size (default: MEDIUM)",
    )

    args = parser.parse_args()

    try:
        if args.action == "create":
            if not all([args.app_name, args.workspace_path, args.lakebase_name, args.schema]):
                parser.error(
                    "--create requires --app-name, --workspace-path, --lakebase-name, and --schema"
                )
            result = create_ci(
                app_name=args.app_name,
                workspace_path=args.workspace_path,
                lakebase_name=args.lakebase_name,
                schema_name=args.schema,
                lakebase_capacity=args.lakebase_capacity,
                compute_size=args.compute_size,
            )
        elif args.action == "update":
            if not all([args.app_name, args.workspace_path, args.lakebase_name, args.schema]):
                parser.error(
                    "--update requires --app-name, --workspace-path, --lakebase-name, and --schema"
                )
            result = update_ci(
                app_name=args.app_name,
                workspace_path=args.workspace_path,
                lakebase_name=args.lakebase_name,
                schema_name=args.schema,
            )
        elif args.action == "delete":
            if not all([args.app_name, args.lakebase_name, args.schema]):
                parser.error("--delete requires --app-name, --lakebase-name, and --schema")
            result = delete_ci(
                app_name=args.app_name,
                lakebase_name=args.lakebase_name,
                schema_name=args.schema,
            )
        elif args.action == "verify_deleted":
            if not args.app_name:
                parser.error("--verify-deleted requires --app-name")
            verify_app_deleted(args.app_name)
            result = {"app_name": args.app_name, "status": "verified_deleted"}
        elif args.action == "verify_lakebase_deleted":
            if not args.lakebase_name:
                parser.error("--verify-lakebase-deleted requires --lakebase-name")
            verify_lakebase_deleted(args.lakebase_name)
            result = {
                "lakebase_name": args.lakebase_name,
                "status": "verified_deleted",
            }
        else:
            raise ValueError(f"Unknown action: {args.action}")

        print()
        print(f"Result: {result}")

    except DeploymentError as e:
        print(f"CI deployment failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

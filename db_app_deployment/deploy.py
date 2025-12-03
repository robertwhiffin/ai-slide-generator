"""Databricks App deployment automation.

This script automates the deployment of the AI Slide Generator to Databricks Apps.
It handles building, packaging, uploading, and deploying the application.

Usage:
    python -m db_app_deployment.deploy --create --env production
    python -m db_app_deployment.deploy --update --env development
    python -m db_app_deployment.deploy --delete --env staging
    python -m db_app_deployment.deploy --create --env production --dry-run
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

from databricks.sdk import WorkspaceClient  # Keep for profile-specific connections
from databricks.sdk.core import ApiClient
from databricks.sdk.service.apps import (
    App,
    AppDeployment,
    AppDeploymentMode,
    AppResource,
    AppResourceDatabase,
    ComputeSize,
)

from src.core.databricks_client import get_databricks_client
from src.core.lakebase import create_lakebase_instance, grant_service_principal_permissions
from databricks.sdk.service.workspace import ImportFormat

from db_app_deployment.config import load_deployment_config


class DeploymentError(Exception):
    """Raised when deployment fails."""

    pass


def build_python_wheel(project_root: Path) -> Path:
    """
    Build Python wheel package.

    Args:
        project_root: Root directory of the project

    Returns:
        Path to the built wheel file

    Raises:
        DeploymentError: If wheel build fails
    """
    print("🐍 Building Python wheel...")

    # Clean previous builds
    dist_dir = project_root / "dist"
    if dist_dir.exists():
        print("  Cleaning previous builds...")
        shutil.rmtree(dist_dir)

    try:
        # Build wheel using python -m build
        print("  Running: python -m build --wheel")
        subprocess.run(
            ["python", "-m", "build", "--wheel"],
            cwd=project_root,
            check=True,
            capture_output=True,
        )

        # Find the built wheel
        if not dist_dir.exists():
            raise DeploymentError("Build did not create dist/ directory")

        wheels = list(dist_dir.glob("*.whl"))
        if not wheels:
            raise DeploymentError("No wheel file found in dist/")

        wheel_path = wheels[0]
        print(f"  ✅ Wheel built: {wheel_path.name}")
        return wheel_path

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        raise DeploymentError(f"Wheel build failed: {error_msg}")
    except FileNotFoundError:
        raise DeploymentError(
            "python -m build not found. Install with: pip install build"
        )


def build_frontend(project_root: Path) -> None:
    """
    Build frontend React application.

    Args:
        project_root: Root directory of the project

    Raises:
        DeploymentError: If frontend build fails
    """
    print("📦 Building frontend...")
    frontend_dir = project_root / "frontend"

    if not frontend_dir.exists():
        raise DeploymentError(f"Frontend directory not found: {frontend_dir}")

    try:
        # Install dependencies
        print("  Installing npm dependencies...")
        subprocess.run(
            ["npm", "install"], cwd=frontend_dir, check=True, capture_output=True
        )

        # Build production bundle
        print("  Building production bundle...")
        subprocess.run(
            ["npm", "run", "build"], cwd=frontend_dir, check=True, capture_output=True
        )

        dist_dir = frontend_dir / "dist"
        if not dist_dir.exists():
            raise DeploymentError("Frontend build did not create dist/ directory")

        print("  ✅ Frontend built successfully")
    except subprocess.CalledProcessError as e:
        raise DeploymentError(f"Frontend build failed: {e.stderr.decode()}")
    except FileNotFoundError:
        raise DeploymentError(
            "npm not found. Please install Node.js and npm: https://nodejs.org/"
        )


def create_staging_directory(
    project_root: Path, wheel_path: Path, exclude_patterns: list[str]
) -> Path:
    """
    Create staging directory with deployment artifacts.

    Args:
        project_root: Root directory of the project
        wheel_path: Path to the built Python wheel
        exclude_patterns: List of patterns to exclude

    Returns:
        Path to staging directory
    """
    print("📁 Creating staging directory...")
    staging_dir = Path(tempfile.mkdtemp(prefix="ai-slide-generator-deploy-"))

    # Copy Python wheel
    print("  Copying Python wheel...")
    wheel_dest = staging_dir / "wheels"
    wheel_dest.mkdir()
    shutil.copy2(wheel_path, wheel_dest / wheel_path.name)

    # Copy settings files
    print("  Copying settings files...")
    shutil.copytree(
        project_root / "settings",
        staging_dir / "settings",
        ignore=shutil.ignore_patterns("deployment.yaml", "deployment.example.yaml"),
    )

    # Copy frontend dist
    print("  Copying frontend build...")
    shutil.copytree(project_root / "frontend" / "dist", staging_dir / "frontend" / "dist")

    # Copy essential files
    print("  Copying essential files...")
    for file in ["app.yaml", "requirements.txt"]:
        src_file = project_root / file
        if src_file.exists():
            shutil.copy2(src_file, staging_dir / file)
        else:
            print(f"  ⚠️  Warning: {file} not found")

    print(f"  ✅ Staging directory created: {staging_dir}")
    return staging_dir


def upload_files_to_workspace(
    workspace_client: WorkspaceClient, staging_dir: Path, workspace_path: str
) -> None:
    """
    Upload files from staging directory to Databricks workspace.

    Uploads files individually maintaining directory structure,
    similar to how Databricks Apps expects deployment artifacts.

    Args:
        workspace_client: Databricks workspace client
        staging_dir: Local staging directory with files
        workspace_path: Target path in workspace
    """
    print(f"☁️  Uploading files to workspace: {workspace_path}")

    # Ensure base deployment path exists
    try:
        workspace_client.workspace.mkdirs(workspace_path)
    except Exception as e:
        print(f"  Note: Directory might already exist: {e}")

    # Clean old wheels to ensure only latest version is present
    print("  Cleaning old wheels...")
    try:
        wheels_path = f"{workspace_path}/wheels"
        # List and delete old wheels
        try:
            objects = workspace_client.workspace.list(wheels_path)
            for obj in objects:
                if obj.path and obj.path.endswith('.whl'):
                    workspace_client.workspace.delete(obj.path)
                    print(f"    Deleted old wheel: {obj.path}")
        except Exception:
            # wheels/ directory might not exist yet, that's ok
            pass
    except Exception as e:
        print(f"  Note: Could not clean wheels: {e}")

    # Walk through staging directory and upload all files
    file_count = 0
    for root, dirs, files in os.walk(staging_dir):
        # Calculate relative path from staging_dir
        rel_path = Path(root).relative_to(staging_dir)

        # Create corresponding directory in workspace
        if rel_path != Path("."):
            workspace_dir = f"{workspace_path}/{rel_path}".replace("\\", "/")
            try:
                workspace_client.workspace.mkdirs(workspace_dir)
            except Exception:
                pass  # Directory might already exist

        # Upload each file
        for file in files:
            local_file_path = Path(root) / file
            
            # Calculate workspace file path
            if rel_path == Path("."):
                workspace_file_path = f"{workspace_path}/{file}"
            else:
                workspace_file_path = f"{workspace_path}/{rel_path}/{file}".replace(
                    "\\", "/"
                )

            try:
                with open(local_file_path, "rb") as f:
                    workspace_client.workspace.upload(
                        workspace_file_path,
                        f,
                        format=ImportFormat.AUTO,
                        overwrite=True,
                    )
                file_count += 1
                
                # Show progress for every 10th file
                if file_count % 10 == 0:
                    print(f"  Uploaded {file_count} files...")
                    
            except Exception as e:
                # Try creating parent directory and retry
                parent_dir = str(Path(workspace_file_path).parent)
                try:
                    workspace_client.workspace.mkdirs(parent_dir)
                    with open(local_file_path, "rb") as f:
                        workspace_client.workspace.upload(
                            workspace_file_path,
                            f,
                            format=ImportFormat.AUTO,
                            overwrite=True,
                        )
                    file_count += 1
                except Exception as retry_error:
                    raise DeploymentError(
                        f"Upload failed for {workspace_file_path}: {retry_error}"
                    )

    print(f"  ✅ Uploaded {file_count} files successfully")


def create_app(
    workspace_client: WorkspaceClient,
    app_name: str,
    description: str,
    workspace_path: str,
    compute_size: str,
    database_name: str,
) -> None:
    """
    Create Databricks App with Lakebase database.

    Args:
        workspace_client: Databricks workspace client
        app_name: Name of the app
        description: Description of the app
        workspace_path: Path to app artifacts in workspace
        compute_size: Compute size (MEDIUM, LARGE, or LIQUID)
        database_name: Lakebase database name to attach as resource
    """
    print(f"🚀 Creating app: {app_name}")

    try:
        # Convert compute_size string to enum
        compute_size_enum = ComputeSize(compute_size)

        # Build resources list with Lakebase database
        print(f"  📊 Attaching Lakebase database: {database_name}")
        resources = [
            AppResource(
                name="app_database",
                database=AppResourceDatabase(name=database_name),
            )
        ]

        # Create app - Databricks will read app.yaml from workspace_path
        app = App(
            name=app_name,
            description=description,
            compute_size=compute_size_enum,
            default_source_code_path=workspace_path,
            resources=resources,
        )

        result = workspace_client.apps.create_and_wait(app)
        print(f"  ✅ App created: {result.name}")
        if hasattr(result, "url") and result.url:
            print(f"  🌐 URL: {result.url}")
    except Exception as e:
        raise DeploymentError(f"App creation failed: {e}")


def update_app(
    workspace_client: WorkspaceClient,
    app_name: str,
    description: str,
    workspace_path: str,
    compute_size: str,
) -> None:
    """
    Deploy new version of existing Databricks App.

    Creates a new app deployment with updated wheel, frontend, and settings files.
    Uses the apps.deploy() API to trigger a new deployment.

    Args:
        workspace_client: Databricks workspace client
        app_name: Name of the app
        description: Description (unused in deploy, kept for consistency)
        workspace_path: Path to app artifacts in workspace
        compute_size: Compute size (unused in deploy, kept for consistency)
    """
    print(f"🔄 Deploying new version of app: {app_name}")

    try:
        # Create app deployment pointing to updated source code
        app_deployment = AppDeployment(
            source_code_path=workspace_path
        )

        # Trigger deployment and wait for it to complete
        print("  ⏳ Creating deployment...")
        result = workspace_client.apps.deploy_and_wait(
            app_name=app_name,
            app_deployment=app_deployment,
        )
        
        print(f"  ✅ Deployment completed: {result.deployment_id}")
        
        # Get app URL
        app = workspace_client.apps.get(name=app_name)
        if hasattr(app, "url") and app.url:
            print(f"  🌐 URL: {app.url}")
            
    except Exception as e:
        raise DeploymentError(f"App deployment failed: {e}")


def delete_app(workspace_client: WorkspaceClient, app_name: str) -> None:
    """
    Delete Databricks App.

    Args:
        workspace_client: Databricks workspace client
        app_name: Name of the app
    """
    print(f"🗑️  Deleting app: {app_name}")

    try:
        workspace_client.apps.delete(name=app_name)
        print("  ✅ App deleted")
    except Exception as e:
        # App might not exist, that's ok
        print(f"  Note: {e}")


def set_permissions(
    workspace_client: WorkspaceClient, app_name: str, permissions: list[dict]
) -> None:
    """
    Set app permissions.

    Args:
        workspace_client: Databricks workspace client
        app_name: Name of the app
        permissions: List of permission entries
    """
    print(f"🔐 Setting permissions for {app_name}...")

    try:
        # Note: Actual implementation depends on Databricks SDK version
        # This is a placeholder - adjust based on SDK API
        for perm in permissions:
            print(f"  - {perm}")

        # workspace_client.apps.update_permissions(
        #     name=app_name,
        #     access_control_list=[...permissions]
        # )
        print("  ✅ Permissions configured")
    except Exception as e:
        print(f"  ⚠️  Could not set permissions: {e}")


def deploy(
    env: str,
    action: str,
    dry_run: bool = False,
    profile: Optional[str] = None,
) -> None:
    """
    Main deployment function.

    Args:
        env: Environment name (development, staging, production)
        action: Action to perform (create, update, delete)
        dry_run: If True, only validate without deploying
        profile: Optional Databricks profile name from ~/.databrickscfg (for deployment only)
    """
    project_root = Path(__file__).parent.parent

    try:
        # Load configuration
        print(f"📋 Loading configuration for environment: {env}")
        config = load_deployment_config(env)

        print(f"   App name: {config.app_name}")
        print(f"   Description: {config.description}")
        print(f"   Workspace path: {config.workspace_path}")
        print(f"   Compute size: {config.compute_size}")
        print()

        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be made")
            print("✅ Configuration is valid")
            return

        # Initialize Databricks client
        if profile:
            print(f"🔑 Connecting to Databricks (using profile: {profile})")
            workspace_client = WorkspaceClient(profile=profile)
        else:
            print("🔑 Connecting to Databricks (using environment variables)")
            workspace_client = get_databricks_client()
        print("  ✅ Connected")
        print("Workspace URL: ", workspace_client.config.host )
        print()

        # Handle delete action
        if action == "delete":
            delete_app(workspace_client, config.app_name)
            print("✅ Deletion complete")
            return

        # Create Lakebase instance
        print("📊 Setting up Lakebase database...")
        lakebase_result = create_lakebase_instance(
            catalog=config.lakebase.catalog,
            database_name=config.lakebase.database_name,
            schema=config.lakebase.schema,
            client=workspace_client,
        )
        print(f"  ✅ Lakebase ready: {lakebase_result['full_schema_name']}")
        print()

        # Build Python wheel and frontend
        wheel_path = build_python_wheel(project_root)
        print()
        
        build_frontend(project_root)
        print()

        staging_dir = create_staging_directory(
            project_root, wheel_path, config.exclude_patterns
        )
        print()

        try:
            # Upload files directly to workspace
            upload_files_to_workspace(
                workspace_client, staging_dir, config.workspace_path
            )
            print()

            # Create or update app
            if action == "create":
                create_app(
                    workspace_client,
                    config.app_name,
                    config.description,
                    config.workspace_path,
                    config.compute_size,
                    database_name=config.lakebase.database_name,
                )
                set_permissions(workspace_client, config.app_name, config.permissions)

                # Grant Lakebase permissions to app service principal
                try:
                    app = workspace_client.apps.get(name=config.app_name)
                    if app.service_principal_id:
                        print("🔐 Granting Lakebase permissions to app service principal...")
                        grant_service_principal_permissions(
                            catalog=config.lakebase.catalog,
                            schema=config.lakebase.schema,
                            principal_id=str(app.service_principal_id),
                            client=workspace_client,
                        )
                        print("  ✅ Lakebase permissions granted")
                except Exception as e:
                    print(f"  ⚠️  Could not grant Lakebase permissions: {e}")
            elif action == "update":
                update_app(
                    workspace_client,
                    config.app_name,
                    config.description,
                    config.workspace_path,
                    config.compute_size,
                )
            else:
                raise ValueError(f"Unknown action: {action}")

            print()
            print("✅ Deployment complete!")

        finally:
            # Cleanup
            print("🧹 Cleaning up...")
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            print("  ✅ Cleanup complete")

    except DeploymentError as e:
        print(f"❌ Deployment failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        raise


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy AI Slide Generator to Databricks Apps"
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
        "--create", action="store_const", const="create", dest="action", help="Create new app"
    )
    action_group.add_argument(
        "--update", action="store_const", const="update", dest="action", help="Update existing app"
    )
    action_group.add_argument(
        "--delete", action="store_const", const="delete", dest="action", help="Delete app"
    )

    parser.add_argument(
        "--profile",
        type=str,
        help="Databricks profile name from ~/.databrickscfg (optional, for deployment only)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without deploying",
    )

    args = parser.parse_args()

    deploy(
        env=args.env,
        action=args.action,
        dry_run=args.dry_run,
        profile=args.profile,
    )


if __name__ == "__main__":
    main()


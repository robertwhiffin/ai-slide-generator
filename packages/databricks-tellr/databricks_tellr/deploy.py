"""Deployment orchestration for Tellr on Databricks Apps.

This module provides the main create/update/delete functions for deploying
the Tellr AI slide generator to Databricks Apps from a notebook.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from importlib import metadata, resources
from pathlib import Path
from string import Template
from typing import Any, Iterator, Optional

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import (
    App,
    AppDeployment,
    AppResource,
    AppResourceDatabase,
    AppResourceDatabaseDatabasePermission,
    ComputeSize,
)
from databricks.sdk.service.database import DatabaseInstance
from databricks.sdk.service.workspace import ImportFormat

# Autoscaling imports (Lakebase next-gen)
try:
    from databricks.sdk.service.postgres import (
        Branch,
        BranchSpec,
        Project,
        ProjectDefaultEndpointSettings,
        ProjectSpec,
    )
    HAS_AUTOSCALING_SDK = True
except ImportError:
    HAS_AUTOSCALING_SDK = False

# Role management imports (requires newer SDK — >=0.91.0 for RoleMembershipRole)
HAS_ROLE_SDK = False
try:
    from databricks.sdk.service.postgres import (
        Role,
        RoleAuthMethod,
        RoleIdentityType,
        RoleMembershipRole,
        RoleRoleSpec,
    )
    HAS_ROLE_SDK = True
except ImportError:
    pass

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """Raised when deployment fails."""

    pass


# -----------------------------------------------------------------------------
# WorkspaceClient Factory
# -----------------------------------------------------------------------------


def _get_workspace_client(
    client: WorkspaceClient | None = None,
    profile: str | None = None,
) -> WorkspaceClient:
    """Get WorkspaceClient with priority: external > profile > env vars.

    Args:
        client: Externally created WorkspaceClient (highest priority)
        profile: Profile name from .databrickscfg file

    Returns:
        WorkspaceClient configured with the appropriate authentication
    """
    if client is not None:
        return client
    if profile:
        return WorkspaceClient(profile=profile)
    return WorkspaceClient()


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def create(
    lakebase_name: str | None = None,
    schema_name: str | None = None,
    app_name: str | None = None,
    app_file_workspace_path: str | None = None,
    lakebase_compute: str = "CU_1",
    app_compute: str = "MEDIUM",
    app_version: Optional[str] = None,
    description: str = "Tellr AI Slide Generator",
    client: WorkspaceClient | None = None,
    profile: str | None = None,
    config_yaml_path: str | None = None,
    encryption_key: str | None = None,
    use_test_pypi: bool = False,
) -> dict[str, Any]:
    """Deploy Tellr to Databricks Apps.

    This function creates all necessary infrastructure and deploys the app:
    1. Creates/gets Lakebase database instance
    2. Generates requirements.txt with pinned app version
    3. Generates app.yaml with environment variables
    4. Uploads files to workspace
    5. Creates Databricks App with database resource
    6. Sets up database schema with permissions

    Authentication priority:
    1. External WorkspaceClient passed via `client` parameter
    2. Profile name from .databrickscfg via `profile` parameter
    3. Environment variables (DATABRICKS_HOST, DATABRICKS_TOKEN, etc.)

    Args:
        lakebase_name: Name for the Lakebase database instance
        schema_name: PostgreSQL schema name for app tables
        app_name: Name for the Databricks App
        app_file_workspace_path: Workspace path to upload app files
        lakebase_compute: Lakebase capacity (CU_1, CU_2, CU_4, CU_8)
        app_compute: App compute size (MEDIUM, LARGE, LIQUID)
        app_version: Specific databricks-tellr-app version (default: latest)
        description: App description
        client: External WorkspaceClient (optional)
        profile: Databricks CLI profile name (optional)
        config_yaml_path: Path to deployment config YAML (mutually exclusive with other args)
        encryption_key: Fernet key for Google OAuth encryption. Auto-generated if not provided.
        use_test_pypi: If True, install app package from Test PyPI instead of real PyPI.

    Returns:
        Dictionary with deployment info:
        - url: App URL
        - app_name: Created app name
        - lakebase_name: Database instance name
        - schema_name: Schema name
        - status: "created"

    Raises:
        DeploymentError: If deployment fails
        ValueError: If required arguments are missing or config_yaml_path used with other args
    """
    return _create_databricks(
        lakebase_name=lakebase_name,
        schema_name=schema_name,
        app_name=app_name,
        app_file_workspace_path=app_file_workspace_path,
        lakebase_compute=lakebase_compute,
        app_compute=app_compute,
        app_version=app_version,
        description=description,
        client=client,
        profile=profile,
        config_yaml_path=config_yaml_path,
        seed_databricks_defaults=False,
        encryption_key=encryption_key,
        use_test_pypi=use_test_pypi,
    )


def update(
    app_name: str,
    app_file_workspace_path: str,
    lakebase_name: str,
    schema_name: str,
    app_version: Optional[str] = None,
    reset_database: bool = False,
    client: WorkspaceClient | None = None,
    profile: str | None = None,
    encryption_key: str | None = None,
    use_test_pypi: bool = False,
) -> dict[str, Any]:
    """Deploy a new version of an existing Tellr app.

    Updates the app files and triggers a new deployment.

    Args:
        app_name: Name of the existing Databricks App
        app_file_workspace_path: Workspace path with app files
        lakebase_name: Lakebase instance name
        schema_name: Schema name
        app_version: Specific databricks-tellr-app version (default: latest)
        reset_database: If True, drop and recreate the schema (tables recreated on app startup)
        client: External WorkspaceClient (optional)
        profile: Databricks CLI profile name (optional)
        encryption_key: Fernet key for Google OAuth encryption. If not provided, the
            existing key is read from the deployed app.yaml to preserve encrypted data.
        use_test_pypi: If True, install app package from Test PyPI instead of real PyPI.

    Returns:
        Dictionary with deployment info

    Raises:
        DeploymentError: If update fails
    """
    return _update_databricks(
        app_name=app_name,
        app_file_workspace_path=app_file_workspace_path,
        lakebase_name=lakebase_name,
        schema_name=schema_name,
        app_version=app_version,
        reset_database=reset_database,
        client=client,
        profile=profile,
        seed_databricks_defaults=False,
        encryption_key=encryption_key,
        use_test_pypi=use_test_pypi,
    )


# -----------------------------------------------------------------------------
# Internal Databricks Functions (full implementations with seeding control)
# -----------------------------------------------------------------------------


def _create_databricks(
    lakebase_name: str | None = None,
    schema_name: str | None = None,
    app_name: str | None = None,
    app_file_workspace_path: str | None = None,
    lakebase_compute: str = "CU_1",
    app_compute: str = "MEDIUM",
    app_version: Optional[str] = None,
    description: str = "Tellr AI Slide Generator",
    client: WorkspaceClient | None = None,
    profile: str | None = None,
    config_yaml_path: str | None = None,
    seed_databricks_defaults: bool = True,
    encryption_key: str | None = None,
    use_test_pypi: bool = False,
) -> dict[str, Any]:
    """Deploy Tellr to Databricks Apps with configurable seeding.
    
    Internal function with full control over seeding behavior.
    
    Args:
        lakebase_name: Name for the Lakebase database instance
        schema_name: PostgreSQL schema name for app tables
        app_name: Name for the Databricks App
        app_file_workspace_path: Workspace path to upload app files
        lakebase_compute: Lakebase capacity (CU_1, CU_2, CU_4, CU_8)
        app_compute: App compute size (MEDIUM, LARGE, LIQUID)
        app_version: Specific databricks-tellr-app version (default: latest)
        description: App description
        client: External WorkspaceClient (optional)
        profile: Databricks CLI profile name (optional)
        config_yaml_path: Path to deployment config YAML (mutually exclusive with other args)
        seed_databricks_defaults: If True, seed Databricks-specific content on startup
        encryption_key: Fernet key for Google OAuth encryption. Auto-generated if not provided.
        use_test_pypi: If True, install app package from Test PyPI instead of real PyPI.

    Returns:
        Dictionary with deployment info

    Raises:
        DeploymentError: If deployment fails
        ValueError: If required arguments are missing or config_yaml_path used with other args
    """
    ws = _get_workspace_client(client, profile)

    # Handle YAML config loading
    if config_yaml_path:
        if any([lakebase_name, schema_name, app_name, app_file_workspace_path]):
            raise ValueError("config_yaml_path cannot be used with other arguments")
        config = _load_deployment_config(config_yaml_path)
        lakebase_name = config.get("lakebase_name")
        schema_name = config.get("schema_name")
        app_name = config.get("app_name")
        app_file_workspace_path = config.get("app_file_workspace_path")
        lakebase_compute = config.get("lakebase_compute", lakebase_compute)
        app_compute = config.get("app_compute", app_compute)

    # Validate required arguments
    if not all([lakebase_name, schema_name, app_name, app_file_workspace_path]):
        raise ValueError(
            "lakebase_name, schema_name, app_name, and app_file_workspace_path are required"
        )

    print("Deploying Tellr to Databricks Apps...")
    print(f"   App name: {app_name}")
    print(f"   Workspace path: {app_file_workspace_path}")
    print(f"   Lakebase: {lakebase_name} (capacity: {lakebase_compute})")
    print(f"   Schema: {schema_name}")
    print()

    try:
        # Step 1: Create/get Lakebase (autoscaling first, fallback to provisioned)
        print("Setting up Lakebase database...")
        lakebase_result = _get_or_create_lakebase(ws, lakebase_name, lakebase_compute)
        lakebase_type = lakebase_result.get("type", "provisioned")
        print(f"   Lakebase: {lakebase_result['name']} ({lakebase_result['status']}, type={lakebase_type})")
        print()

        # Step 2: Generate and upload files
        print("Preparing deployment files...")
        with _staging_dir() as staging:
            _write_requirements(staging, app_version)
            print("   Generated requirements.txt")

            _write_app_yaml(
                staging,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                encryption_key=encryption_key,
                lakebase_result=lakebase_result,
                use_test_pypi=use_test_pypi,
            )
            print("   Generated app.yaml (with encryption key)")

            print(f"Uploading to: {app_file_workspace_path}")
            _upload_files(ws, staging, app_file_workspace_path)
            print("   Files uploaded")
        print()

        # Step 3: Create app (without deploying yet)
        print(f"Creating Databricks App: {app_name}")
        app = _create_app(
            ws,
            app_name=app_name,
            description=description,
            workspace_path=app_file_workspace_path,
            compute_size=app_compute,
            lakebase_name=lakebase_name,
            lakebase_type=lakebase_type,
        )
        print("   App registered")
        print()

        # Step 3b: For autoscaling, create SP role via Postgres API
        if lakebase_type == "autoscaling":
            client_id = _get_app_client_id(app)
            if client_id:
                print("Configuring SP role on autoscaling project...")
                _ensure_sp_autoscaling_role(ws, lakebase_name, client_id)
            else:
                print("   Warning: Could not get SP client ID — role setup skipped")

        # Step 4: Set up database schema (before deployment)
        # This ensures the schema and permissions are ready before the app starts
        print("Setting up database schema...")
        _setup_database_schema(ws, app, lakebase_name, schema_name, lakebase_result=lakebase_result)
        print(f"   Schema '{schema_name}' configured")
        print()

        # Step 5: Deploy the app (now that schema is ready)
        print("Deploying app...")
        app = _deploy_app(ws, app_name, app_file_workspace_path)
        print("   App deployed")
        if app.url:
            print(f"   URL: {app.url}")
        print()

        print("Deployment complete!")
        return {
            "url": app.url,
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "lakebase_type": lakebase_type,
            "schema_name": schema_name,
            "status": "created",
        }

    except Exception as e:
        raise DeploymentError(f"Deployment failed: {e}") from e


def _update_databricks(
    app_name: str,
    app_file_workspace_path: str,
    lakebase_name: str,
    schema_name: str,
    app_version: Optional[str] = None,
    reset_database: bool = False,
    client: WorkspaceClient | None = None,
    profile: str | None = None,
    seed_databricks_defaults: bool = True,
    encryption_key: str | None = None,
    use_test_pypi: bool = False,
) -> dict[str, Any]:
    """Deploy a new version of an existing Tellr app with configurable seeding.
    
    Internal function with full control over seeding behavior.

    Args:
        app_name: Name of the existing Databricks App
        app_file_workspace_path: Workspace path with app files
        lakebase_name: Lakebase instance name
        schema_name: Schema name
        app_version: Specific databricks-tellr-app version (default: latest)
        reset_database: If True, drop and recreate the schema (tables recreated on app startup)
        client: External WorkspaceClient (optional)
        profile: Databricks CLI profile name (optional)
        seed_databricks_defaults: If True, seed Databricks-specific content on startup
        encryption_key: Fernet key for Google OAuth encryption. If not provided, reads
            the existing key from the deployed app.yaml to preserve encrypted data.
        use_test_pypi: If True, install app package from Test PyPI instead of real PyPI.

    Returns:
        Dictionary with deployment info

    Raises:
        DeploymentError: If update fails
    """
    print(f"Updating Tellr app: {app_name}")

    ws = _get_workspace_client(client, profile)

    # Preserve the existing encryption key so we don't invalidate encrypted data
    if not encryption_key:
        encryption_key = _read_existing_encryption_key(ws, app_file_workspace_path)

    try:
        # Read current Lakebase state so app.yaml gets correct env vars
        lakebase_result = _get_or_create_lakebase(ws, lakebase_name, "CU_1")
        lakebase_type = lakebase_result.get("type", "provisioned")

        # Check for breaking migrations and prompt before proceeding
        _check_breaking_migrations(ws, lakebase_name, schema_name, lakebase_result)

        # Reset database if requested
        if reset_database:
            print("Resetting database schema...")
            app = ws.apps.get(name=app_name)
            _reset_schema(ws, app, lakebase_name, schema_name,
                          lakebase_result=lakebase_result)
            print(f"   Schema '{schema_name}' reset (tables will be recreated on app startup)")
            print()

        # Generate and upload updated files
        with _staging_dir() as staging:
            _write_requirements(staging, app_version)
            _write_app_yaml(
                staging,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                encryption_key=encryption_key,
                lakebase_result=lakebase_result,
                use_test_pypi=use_test_pypi,
            )
            _upload_files(ws, staging, app_file_workspace_path)
            print("   Files updated")

        # Trigger new deployment
        print("   Deploying...")
        deployment = AppDeployment(source_code_path=app_file_workspace_path)
        result = ws.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)
        print(f"   Deployment completed: {result.deployment_id}")

        app = ws.apps.get(name=app_name)
        if app.url:
            print(f"   URL: {app.url}")

        return {
            "url": app.url,
            "app_name": app_name,
            "deployment_id": result.deployment_id,
            "lakebase_type": lakebase_type,
            "status": "updated",
            "database_reset": reset_database,
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e


def delete(
    app_name: str,
    lakebase_name: str | None = None,
    schema_name: str | None = None,
    reset_database: bool = False,
    client: WorkspaceClient | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Delete a Tellr app.

    Note: This does not delete the Lakebase instance by default.

    Args:
        app_name: Name of the app to delete
        lakebase_name: Lakebase instance name (required if reset_database=True)
        schema_name: Schema name (required if reset_database=True)
        reset_database: If True, drop the schema before deleting the app
        client: External WorkspaceClient (optional)
        profile: Databricks CLI profile name (optional)

    Returns:
        Dictionary with deletion status

    Raises:
        DeploymentError: If deletion fails
        ValueError: If reset_database=True but lakebase_name or schema_name not provided
    """
    print(f"Deleting app: {app_name}")

    ws = _get_workspace_client(client, profile)

    try:
        # Reset database if requested
        if reset_database:
            if not lakebase_name or not schema_name:
                raise ValueError(
                    "lakebase_name and schema_name are required when reset_database=True"
                )
            print("Dropping database schema...")
            app = ws.apps.get(name=app_name)
            _reset_schema(ws, app, lakebase_name, schema_name, drop_only=True)
            print(f"   Schema '{schema_name}' dropped")

        ws.apps.delete(name=app_name)
        print("   App deleted")

        return {
            "app_name": app_name,
            "status": "deleted",
            "database_reset": reset_database,
        }

    except Exception as e:
        raise DeploymentError(f"Deletion failed: {e}") from e


# -----------------------------------------------------------------------------
# Internal functions
# -----------------------------------------------------------------------------


def _check_breaking_migrations(
    ws: WorkspaceClient,
    lakebase_name: str,
    schema_name: str,
    lakebase_result: dict[str, Any] | None = None,
) -> None:
    """Check if the update requires breaking migrations and prompt for confirmation.

    Connects to the live database, inspects the schema, and warns the user
    if session data will be truncated during the upgrade.

    Raises:
        DeploymentError: If the user declines the migration.
    """
    try:
        conn, _ = _get_lakebase_connection(ws, lakebase_name, lakebase_result=lakebase_result)
    except Exception as e:
        logger.warning("Could not connect to Lakebase for migration check: %s", e)
        print(f"   Warning: Could not check for breaking migrations ({e})")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
                (schema_name, "slide_style_library", "image_guidelines"),
            )
            has_column = cur.fetchone() is not None

            if has_column:
                return

            session_tables = [
                "user_sessions",
                "session_messages",
                "chat_requests",
                "session_slide_decks",
                "slide_deck_versions",
                "export_jobs",
            ]

            row_counts = {}
            for table in session_tables:
                try:
                    cur.execute(
                        f'SELECT COUNT(*) FROM "{schema_name}"."{table}"'
                    )
                    row_counts[table] = cur.fetchone()[0]
                except Exception:
                    row_counts[table] = 0

            total_rows = sum(row_counts.values())

            print()
            print("=" * 60)
            print("  BREAKING MIGRATION DETECTED")
            print("=" * 60)
            print()
            print("  This update adds a new column (image_guidelines) to")
            print("  slide_style_library. Existing chat session data is")
            print("  incompatible and will be permanently deleted:")
            print()
            for table, count in row_counts.items():
                if count > 0:
                    print(f"    {table}: {count} rows")
            if total_rows == 0:
                print("    (all session tables are empty)")
            print()
            print("  Configuration data (profiles, prompts, styles,")
            print("  credentials) will NOT be affected.")
            print("=" * 60)
            print()

            confirm = input("  Continue with update? [yes/no]: ").strip().lower()
            if confirm != "yes":
                raise DeploymentError(
                    "Update aborted by user due to breaking migration."
                )
            print()
    finally:
        conn.close()


def _read_existing_encryption_key(
    ws: WorkspaceClient, workspace_path: str
) -> str | None:
    """Read the GOOGLE_OAUTH_ENCRYPTION_KEY from an existing deployed app.yaml.

    This preserves the encryption key across updates so that previously encrypted
    credentials and tokens remain decryptable.

    Returns:
        The encryption key string, or None if not found.
    """
    try:
        resp = ws.workspace.download(f"{workspace_path}/app.yaml")
        raw = resp.read() if hasattr(resp, "read") else resp
        content = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

        existing = yaml.safe_load(content)
        for env_entry in existing.get("env", []):
            if env_entry.get("name") == "GOOGLE_OAUTH_ENCRYPTION_KEY":
                key = env_entry.get("value")
                if key:
                    print("   Preserved existing encryption key from deployed app.yaml")
                    return key
    except Exception as e:
        logger.warning("Could not read existing encryption key from app.yaml: %s", e)

    return None


def _load_deployment_config(config_yaml_path: str) -> dict[str, str]:
    """Load deployment settings from config/deployment.yaml-style files.

    Expected structure (see config/deployment.yaml):
      environments:
        development:
          app_name: ...
          workspace_path: ...
          compute_size: ...
          lakebase:
            database_name: ...
            schema: ...
            capacity: ...
    """
    with open(config_yaml_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    environments = config.get("environments", {})
    if not environments:
        raise ValueError("No environments found in deployment config")

    env_name = os.getenv("ENVIRONMENT", "development")
    if env_name not in environments:
        raise ValueError(f"Environment '{env_name}' not found in deployment config")

    env_config = environments[env_name]
    lakebase_config = env_config.get("lakebase", {})

    return {
        "app_name": env_config.get("app_name"),
        "app_file_workspace_path": env_config.get("workspace_path"),
        "app_compute": env_config.get("compute_size"),
        "lakebase_name": lakebase_config.get("database_name"),
        "schema_name": lakebase_config.get("schema"),
        "lakebase_compute": lakebase_config.get("capacity"),
    }


def _capacity_to_autoscaling_cu(capacity: str) -> tuple[float, float]:
    """Map provisioned capacity to autoscaling CU range.

    Returns (min_cu, max_cu) tuple, clamped to valid limits.
    """
    mapping = {
        "CU_1": (0.5, 2.0),
        "CU_2": (1.0, 4.0),
        "CU_4": (2.0, 8.0),
        "CU_8": (4.0, 12.0),
    }
    min_cu, max_cu = mapping.get(capacity, (0.5, 2.0))
    # Clamp to product limits: 0.5-112 CU, max-min gap <= 8
    min_cu = max(0.5, min(min_cu, 112.0))
    max_cu = max(min_cu, min(max_cu, 112.0))
    if max_cu - min_cu > 8:
        max_cu = min_cu + 8
        logger.warning(f"Clamped autoscaling CU range to {min_cu}-{max_cu} (max gap is 8)")
    return min_cu, max_cu


# How long to poll for a new branch's endpoint to come up before giving up.
_BRANCH_ENDPOINT_TIMEOUT_S = 120
_BRANCH_ENDPOINT_POLL_INTERVAL_S = 3


def _probe_autoscaling_available(ws: WorkspaceClient) -> bool:
    """Check if Lakebase Autoscaling API is available in this workspace."""
    if not HAS_AUTOSCALING_SDK:
        logger.info("Autoscaling SDK not available (databricks-sdk too old)")
        return False
    try:
        list(ws.postgres.list_projects())
        return True
    except Exception as e:
        logger.info(f"Autoscaling API not available: {type(e).__name__}: {e}")
        return False


def _get_or_create_lakebase_autoscaling(
    ws: WorkspaceClient, database_name: str, capacity: str
) -> dict[str, Any]:
    """Get or create a Lakebase Autoscaling project.

    Returns dict with type, name, status, host, endpoint_name, project_id.
    """
    project_name = f"projects/{database_name}"

    # Try to get existing project
    try:
        project = ws.postgres.get_project(name=project_name)
        logger.info(f"Found existing autoscaling project: {project_name}")
    except Exception:
        # Create new project with CU range from capacity mapping
        min_cu, max_cu = _capacity_to_autoscaling_cu(capacity)
        logger.info(f"Creating autoscaling project: {database_name} ({min_cu}-{max_cu} CU)")
        operation = ws.postgres.create_project(
            project=Project(
                spec=ProjectSpec(
                    display_name=database_name,
                    pg_version="17",
                    default_endpoint_settings=ProjectDefaultEndpointSettings(
                        autoscaling_limit_min_cu=min_cu,
                        autoscaling_limit_max_cu=max_cu,
                    ),
                )
            ),
            project_id=database_name,
        )
        project = operation.wait()
        logger.info(f"Autoscaling project created: {project.name} ({min_cu}-{max_cu} CU)")

    # Get the primary endpoint for connection info
    endpoints = list(ws.postgres.list_endpoints(
        parent=f"projects/{database_name}/branches/production"
    ))
    if not endpoints:
        raise DeploymentError(
            f"No endpoints found for autoscaling project {database_name}"
        )

    endpoint = ws.postgres.get_endpoint(name=endpoints[0].name)
    host = endpoint.status.hosts.host
    endpoint_name = endpoints[0].name

    return {
        "name": database_name,
        "type": "autoscaling",
        "status": "exists" if project else "created",
        "host": host,
        "endpoint_name": endpoint_name,
        "project_id": database_name,
        "instance_name": None,
    }


def _ensure_sp_autoscaling_role(
    ws: WorkspaceClient, project_name: str, client_id: str
) -> None:
    """Create or verify the SP's Postgres role on an autoscaling project.

    For autoscaling Lakebase, we skip AppResourceDatabase so the platform doesn't
    auto-create the SP's Postgres role. We must create it via the ws.postgres API
    with LAKEBASE_OAUTH_V1 auth so the SP can authenticate using minted tokens.

    Requires SDK >=0.91.0 for RoleMembershipRole. Falls back to warning if unavailable.

    Idempotent: skips if the role already exists.

    Args:
        ws: WorkspaceClient
        project_name: Autoscaling project name (e.g. "teller-dev-mohamed")
        client_id: The app service principal's client ID (UUID)
    """
    if not HAS_ROLE_SDK:
        logger.warning(
            "Role SDK not available (databricks-sdk too old for RoleMembershipRole). "
            "SP role must be created manually via Databricks UI or CLI."
        )
        print("   Warning: SDK too old for role API — SP role must be configured manually")
        return

    branch_path = f"projects/{project_name}/branches/production"
    role_id = f"sp-{client_id}"
    role_path = f"{branch_path}/roles/{role_id}"

    # Check if role already exists
    try:
        existing = ws.postgres.get_role(name=role_path)
        logger.info(f"SP role already exists on autoscaling project: {role_path}")
        # Verify auth method is correct
        if existing.status and existing.status.auth_method == RoleAuthMethod.LAKEBASE_OAUTH_V1:
            logger.info("SP role auth_method is LAKEBASE_OAUTH_V1 — OK")
            return
        logger.warning(
            f"SP role exists but auth_method is {existing.status.auth_method if existing.status else 'unknown'} "
            f"(expected LAKEBASE_OAUTH_V1) — will attempt to recreate"
        )
        # Delete the misconfigured role so we can recreate it
        try:
            ws.postgres.delete_role(name=role_path).wait()
            logger.info(f"Deleted misconfigured SP role: {role_path}")
        except Exception as e:
            logger.warning(f"Could not delete misconfigured role: {e}")
            return
    except Exception:
        # Role doesn't exist — create it
        pass

    # Create the role via the Postgres API with correct auth
    logger.info(f"Creating SP role on autoscaling project: {role_path}")
    print(f"   Creating SP Postgres role via API: {client_id}")
    try:
        operation = ws.postgres.create_role(
            parent=branch_path,
            role=Role(
                spec=RoleRoleSpec(
                    postgres_role=client_id,
                    identity_type=RoleIdentityType.SERVICE_PRINCIPAL,
                    auth_method=RoleAuthMethod.LAKEBASE_OAUTH_V1,
                    membership_roles=[RoleMembershipRole.DATABRICKS_SUPERUSER],
                ),
            ),
            # role_id must match ^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$ — prefix UUID
            role_id=f"sp-{client_id}",
        )
        role = operation.wait()
        logger.info(f"SP role created: {role.name}")
        print(f"   SP role configured with LAKEBASE_OAUTH_V1 auth")
    except Exception as e:
        raise DeploymentError(
            f"Failed to create SP role on autoscaling project: {e}"
        ) from e


def _get_or_create_lakebase_provisioned(
    ws: WorkspaceClient, database_name: str, capacity: str
) -> dict[str, Any]:
    """Get or create a Lakebase Provisioned instance.

    Returns dict with type, name, status, instance_name.
    """
    try:
        existing = ws.database.get_database_instance(name=database_name)
        return {
            "name": existing.name,
            "type": "provisioned",
            "status": "exists",
            "state": existing.state.value if existing.state else "UNKNOWN",
            "host": None,
            "endpoint_name": None,
            "project_id": None,
            "instance_name": existing.name,
        }
    except Exception as e:
        error_str = str(e).lower()
        if "not found" not in error_str and "does not exist" not in error_str:
            raise

    instance = ws.database.create_database_instance_and_wait(
        DatabaseInstance(name=database_name, capacity=capacity)
    )
    return {
        "name": instance.name,
        "type": "provisioned",
        "status": "created",
        "state": instance.state.value if instance.state else "RUNNING",
        "host": None,
        "endpoint_name": None,
        "project_id": None,
        "instance_name": instance.name,
    }


def _get_or_create_lakebase(
    ws: WorkspaceClient, database_name: str, capacity: str
) -> dict[str, Any]:
    """Get or create a Lakebase database.

    Detection order for existing databases:
    1. Check provisioned (ws.database) -- fast, definitive
    2. Check autoscaling (ws.postgres) -- only if provisioned not found

    Creation order for new databases:
    1. Try autoscaling first (preferred)
    2. Fall back to provisioned
    """
    # Check if it already exists as provisioned
    try:
        existing = ws.database.get_database_instance(name=database_name)
        logger.info(f"Found existing provisioned Lakebase: {database_name}")
        return {
            "name": existing.name,
            "type": "provisioned",
            "status": "exists",
            "state": existing.state.value if existing.state else "UNKNOWN",
            "host": None,
            "endpoint_name": None,
            "project_id": None,
            "instance_name": existing.name,
        }
    except Exception as e:
        error_str = str(e).lower()
        if "not found" not in error_str and "does not exist" not in error_str:
            raise

    # Check if it exists as autoscaling, or create new (autoscaling preferred)
    if _probe_autoscaling_available(ws):
        try:
            result = _get_or_create_lakebase_autoscaling(ws, database_name, capacity)
            logger.info(f"Using Lakebase Autoscaling: {result['name']}")
            return result
        except Exception as e:
            logger.warning(
                f"Autoscaling failed, falling back to provisioned: "
                f"{type(e).__name__}: {e}"
            )

    # Create new provisioned instance
    result = _get_or_create_lakebase_provisioned(ws, database_name, capacity)
    logger.info(f"Using Lakebase Provisioned: {result['name']}")
    return result


def _branch_exists(
    ws: WorkspaceClient, project_name: str, branch_name: str
) -> bool:
    """Return True if the Lakebase branch exists, False on not-found.

    Any error other than not-found is surfaced.
    """
    try:
        ws.postgres.get_branch(
            name=f"projects/{project_name}/branches/{branch_name}"
        )
        return True
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            return False
        raise


def _delete_branch(
    ws: WorkspaceClient, project_name: str, branch_name: str
) -> None:
    """Delete a Lakebase branch. Idempotent — no-op if the branch is missing.

    Waits on the long-running delete operation. Any error other than
    not-found is surfaced.
    """
    try:
        operation = ws.postgres.delete_branch(
            name=f"projects/{project_name}/branches/{branch_name}"
        )
        operation.wait()
        logger.info(f"Deleted Lakebase branch: {branch_name}")
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            logger.info(f"Branch {branch_name} not found (already deleted)")
            return
        raise


def _create_branch_from(
    ws: WorkspaceClient,
    project_name: str,
    source_branch: str,
    target_branch: str,
) -> dict[str, Any]:
    """Create a new Lakebase branch as a child of `source_branch`.

    Waits on the create operation, then polls list_endpoints on the new
    branch until an endpoint with a populated host appears
    (up to _BRANCH_ENDPOINT_TIMEOUT_S). Raises DeploymentError on timeout.

    Returns a lakebase_result-shaped dict pointing at the new branch.
    """
    if not HAS_AUTOSCALING_SDK:
        raise DeploymentError(
            "Autoscaling SDK not available — cannot create Lakebase branch. "
            "Upgrade databricks-sdk."
        )

    source_path = f"projects/{project_name}/branches/{source_branch}"
    target_parent = f"projects/{project_name}"
    target_path = f"projects/{project_name}/branches/{target_branch}"

    logger.info(f"Creating branch {target_branch} from {source_branch}")
    operation = ws.postgres.create_branch(
        parent=target_parent,
        branch=Branch(spec=BranchSpec(source_branch=source_path)),
        branch_id=target_branch,
    )
    operation.wait()
    logger.info(f"Branch {target_branch} created")

    # Poll for endpoint readiness
    deadline = time.time() + _BRANCH_ENDPOINT_TIMEOUT_S
    endpoint = None
    while time.time() < deadline:
        endpoints = list(ws.postgres.list_endpoints(parent=target_path))
        ready = [
            e for e in endpoints
            if getattr(e, "status", None)
            and getattr(e.status, "hosts", None)
            and getattr(e.status.hosts, "host", None)
        ]
        if ready:
            endpoint = ready[0]
            break
        time.sleep(_BRANCH_ENDPOINT_POLL_INTERVAL_S)

    if endpoint is None:
        raise DeploymentError(
            f"Branch {target_branch} created but no endpoint ready within "
            f"{_BRANCH_ENDPOINT_TIMEOUT_S}s"
        )

    return {
        "name": project_name,
        "type": "autoscaling",
        "status": "created",
        "host": endpoint.status.hosts.host,
        "endpoint_name": endpoint.name,
        "project_id": project_name,
        "instance_name": None,
    }


def _write_requirements(
    staging_dir: Path,
    app_version: Optional[str],
    local_wheel_path: Optional[str] = None,
) -> None:
    """Generate requirements.txt with app package.

    Args:
        staging_dir: Directory to write the requirements.txt file
        app_version: Specific version to pin (e.g., "0.1.18")
        local_wheel_path: If provided, use this relative path to a local wheel
                          (e.g., "./wheels/databricks_tellr_app-0.1.18-py3-none-any.whl")
                          instead of installing from PyPI
    """
    if local_wheel_path:
        # Use local wheel reference - pip will install from uploaded wheel
        package_line = local_wheel_path
    else:
        # Install from PyPI
        resolved_version = app_version or _resolve_installed_app_version()

        if resolved_version and not _is_valid_version(resolved_version):
            raise DeploymentError(
                f"Invalid app version '{resolved_version}'. Expected a PEP 440 version."
            )

        if resolved_version:
            package_line = f"databricks-tellr-app=={resolved_version}"
        else:
            package_line = "databricks-tellr-app"

    content = "\n".join(
        [
            "# Generated by databricks-tellr",
            package_line,
        ]
    )
    (staging_dir / "requirements.txt").write_text(content)


def _resolve_installed_app_version() -> str | None:
    """Try to resolve the installed version of databricks-tellr-app."""
    try:
        return metadata.version("databricks-tellr-app")
    except metadata.PackageNotFoundError:
        return None


def _write_app_yaml(
    staging_dir: Path,
    lakebase_name: str,
    schema_name: str,
    seed_databricks_defaults: bool = False,
    encryption_key: str | None = None,
    lakebase_result: dict[str, Any] | None = None,
    use_test_pypi: bool = False,
) -> None:
    """Generate app.yaml with environment variables.

    Args:
        staging_dir: Directory to write the app.yaml file
        lakebase_name: Lakebase instance name
        schema_name: Schema name
        seed_databricks_defaults: If True, include Databricks-specific content seeding
        encryption_key: Fernet encryption key for Google OAuth credentials/tokens.
            Auto-generated if not provided.
        lakebase_result: Result dict from _get_or_create_lakebase() with type info.
        use_test_pypi: If True, install from Test PyPI instead of real PyPI.
    """
    # Build init_database call - only show seed_databricks_defaults when True
    if seed_databricks_defaults:
        init_call = "init_database(seed_databricks_defaults=True)"
    else:
        init_call = "init_database()"

    if not encryption_key:
        from cryptography.fernet import Fernet

        encryption_key = Fernet.generate_key().decode()
        logger.info("Auto-generated GOOGLE_OAUTH_ENCRYPTION_KEY for deployment")

    # Determine lakebase type info for env vars
    lakebase_type = (lakebase_result or {}).get("type", "provisioned")
    lakebase_pg_host = (lakebase_result or {}).get("host", "")
    lakebase_project_id = (lakebase_result or {}).get("project_id", "")
    lakebase_endpoint_name = (lakebase_result or {}).get("endpoint_name", "")

    pip_index_args = (
        "--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "
        if use_test_pypi else ""
    )

    template_content = _load_template("app.yaml.template")
    content = Template(template_content).substitute(
        LAKEBASE_INSTANCE=lakebase_name,
        LAKEBASE_SCHEMA=schema_name,
        INIT_DATABASE_CALL=init_call,
        GOOGLE_OAUTH_ENCRYPTION_KEY=encryption_key,
        LAKEBASE_TYPE=lakebase_type,
        LAKEBASE_PG_HOST=lakebase_pg_host,
        LAKEBASE_PROJECT_ID=lakebase_project_id,
        LAKEBASE_ENDPOINT_NAME=lakebase_endpoint_name,
        PIP_INDEX_ARGS=pip_index_args,
    )
    (staging_dir / "app.yaml").write_text(content)



def _load_template(template_name: str) -> str:
    """Load a template file from package resources."""
    try:
        files = resources.files("databricks_tellr") / "_templates" / template_name
        return files.read_text()
    except (TypeError, AttributeError):
        with resources.open_text(
            "databricks_tellr._templates", template_name
        ) as f:
            return f.read()


def _is_valid_version(version: str) -> bool:
    """Check if a version string is valid PEP 440."""
    try:
        from packaging.version import Version
    except ImportError:
        return True
    try:
        Version(version)
        return True
    except Exception:
        return False


@contextmanager
def _staging_dir() -> Iterator[Path]:
    """Create a temporary staging directory for deployment files."""
    import tempfile

    staging_dir = Path(tempfile.mkdtemp(prefix="tellr_staging_"))
    try:
        yield staging_dir
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _upload_files(
    ws: WorkspaceClient, staging_dir: Path, workspace_path: str
) -> None:
    """Upload files from staging directory to workspace."""
    try:
        ws.workspace.mkdirs(workspace_path)
    except Exception:
        pass  # May already exist

    for file_path in staging_dir.iterdir():
        if file_path.is_file():
            workspace_file_path = f"{workspace_path}/{file_path.name}"
            with open(file_path, "rb") as f:
                ws.workspace.upload(
                    workspace_file_path,
                    f,
                    format=ImportFormat.AUTO,
                    overwrite=True,
                )


def _create_app(
    ws: WorkspaceClient,
    app_name: str,
    description: str,
    workspace_path: str,
    compute_size: str,
    lakebase_name: str,
    lakebase_type: str = "provisioned",
) -> App:
    """Create Databricks App with database resource (without deploying).

    This creates the app and waits for it to be ready, but does NOT deploy.
    The app's service principal is available after creation, which is needed
    for setting up database schema permissions before deployment.

    For autoscaling, AppResourceDatabase is not supported — connection info
    is passed via env vars instead.
    """
    compute_size_enum = ComputeSize(compute_size)

    # AppResourceDatabase only works with provisioned Lakebase
    if lakebase_type == "provisioned":
        app_resources = [
            AppResource(
                name="app_database",
                database=AppResourceDatabase(
                    instance_name=lakebase_name,
                    database_name="databricks_postgres",
                    permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
                ),
            )
        ]
    else:
        # Autoscaling: no AppResourceDatabase, connection via env vars
        app_resources = []
        logger.info("Autoscaling mode: skipping AppResourceDatabase (using env vars)")

    app = App(
        name=app_name,
        description=description,
        compute_size=compute_size_enum,
        default_source_code_path=workspace_path,
        resources=app_resources,
        user_api_scopes=[
            "sql",
            "dashboards.genie",
            "catalog.tables:read",
            "catalog.schemas:read",
            "catalog.catalogs:read",
            "serving.serving-endpoints",
        ],
    )

    ws.apps.create_and_wait(app)

    return ws.apps.get(name=app_name)


def _deploy_app(ws: WorkspaceClient, app_name: str, workspace_path: str) -> App:
    """Deploy an existing Databricks App.
    
    Args:
        ws: WorkspaceClient
        app_name: Name of the app to deploy
        workspace_path: Source code path in workspace
        
    Returns:
        The updated App object after deployment
    """
    deployment = AppDeployment(source_code_path=workspace_path)
    ws.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)
    return ws.apps.get(name=app_name)


def _get_app_client_id(app: App) -> str | None:
    """Extract the service principal client ID from an app."""
    if hasattr(app, "service_principal_client_id") and app.service_principal_client_id:
        return app.service_principal_client_id
    if hasattr(app, "service_principal_id") and app.service_principal_id:
        return str(app.service_principal_id)
    return None


def _get_lakebase_connection(
    ws: WorkspaceClient, lakebase_name: str, lakebase_result: dict[str, Any] | None = None,
) -> tuple[Any, str]:
    """Get a psycopg2 connection to Lakebase and the current username.

    Supports both provisioned and autoscaling Lakebase.

    Returns:
        Tuple of (connection, username)
    """
    try:
        import psycopg2
    except ImportError as exc:
        raise DeploymentError(
            "psycopg2-binary is required for database operations"
        ) from exc

    lakebase_type = (lakebase_result or {}).get("type", "provisioned")
    user = ws.current_user.me().user_name

    if lakebase_type == "autoscaling":
        endpoint_name = lakebase_result["endpoint_name"]
        host = lakebase_result["host"]
        cred = ws.postgres.generate_database_credential(endpoint=endpoint_name)
        logger.info(f"Connecting to autoscaling Lakebase at {host}")
    else:
        instance = ws.database.get_database_instance(name=lakebase_name)
        host = instance.read_write_dns
        cred = ws.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[lakebase_name],
        )
        logger.info(f"Connecting to provisioned Lakebase at {host}")

    conn = psycopg2.connect(
        host=host,
        port=5432,
        user=user,
        password=cred.token,
        dbname="databricks_postgres",
        sslmode="require",
    )
    conn.autocommit = True

    return conn, user


def _setup_database_schema(
    ws: WorkspaceClient, app: App, lakebase_name: str, schema_name: str,
    lakebase_result: dict[str, Any] | None = None,
) -> None:
    """Set up database schema and grant permissions to app."""
    client_id = _get_app_client_id(app)

    if not client_id:
        print("   Warning: Could not get app client ID - schema setup skipped")
        return

    conn, _ = _get_lakebase_connection(ws, lakebase_name, lakebase_result=lakebase_result)

    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
            _grant_schema_permissions(cur, schema_name, client_id)
    finally:
        conn.close()


def _reset_schema(
    ws: WorkspaceClient,
    app: App,
    lakebase_name: str,
    schema_name: str,
    drop_only: bool = False,
    lakebase_result: dict[str, Any] | None = None,
) -> None:
    """Drop and recreate schema (tables will be recreated by app on startup).

    Args:
        ws: WorkspaceClient
        app: The Databricks App (needed for service principal ID)
        lakebase_name: Lakebase instance name
        schema_name: Schema to reset
        drop_only: If True, only drop the schema without recreating
        lakebase_result: Result dict from _get_or_create_lakebase()
    """
    client_id = _get_app_client_id(app)

    conn, _ = _get_lakebase_connection(ws, lakebase_name, lakebase_result=lakebase_result)

    try:
        with conn.cursor() as cur:
            # Drop schema with CASCADE to remove all objects
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')

            if not drop_only:
                # Recreate schema
                cur.execute(f'CREATE SCHEMA "{schema_name}"')

                # Re-grant permissions if we have the client ID
                if client_id:
                    _grant_schema_permissions(cur, schema_name, client_id)
    finally:
        conn.close()


def _grant_schema_permissions(cur: Any, schema_name: str, client_id: str) -> None:
    """Grant schema permissions to an app's service principal.

    The SP role should already exist:
    - Provisioned: created by AppResourceDatabase (platform-managed)
    - Autoscaling: created by _ensure_sp_autoscaling_role() via ws.postgres API

    This function only grants schema/table permissions — it does NOT create roles.
    """
    # Verify the role exists before granting
    cur.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (client_id,)
    )
    if not cur.fetchone():
        logger.warning(f"SP role {client_id} not found in pg_roles — grants may fail")

    cur.execute(f'GRANT USAGE ON SCHEMA "{schema_name}" TO "{client_id}"')
    cur.execute(f'GRANT CREATE ON SCHEMA "{schema_name}" TO "{client_id}"')
    cur.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema_name}" TO "{client_id}"'
    )
    cur.execute(
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema_name}" TO "{client_id}"'
    )
    cur.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema_name}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{client_id}"'
    )
    cur.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema_name}" '
        f'GRANT USAGE, SELECT ON SEQUENCES TO "{client_id}"'
    )

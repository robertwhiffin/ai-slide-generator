"""Deployment orchestration for Tellr on Databricks Apps.

This module provides the main create/update/delete functions for deploying
the Tellr AI slide generator to Databricks Apps from a notebook.
"""

from __future__ import annotations

import logging
import os
import shutil
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
        # Step 1: Create/get Lakebase instance
        print("Setting up Lakebase database...")
        lakebase_result = _get_or_create_lakebase(ws, lakebase_name, lakebase_compute)
        print(f"   Lakebase: {lakebase_result['name']} ({lakebase_result['status']})")
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
            )
            print("   Generated app.yaml")

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
        )
        print("   App registered")
        print()

        # Step 4: Set up database schema (before deployment)
        # This ensures the schema and permissions are ready before the app starts
        print("Setting up database schema...")
        _setup_database_schema(ws, app, lakebase_name, schema_name)
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

    Returns:
        Dictionary with deployment info

    Raises:
        DeploymentError: If update fails
    """
    print(f"Updating Tellr app: {app_name}")

    ws = _get_workspace_client(client, profile)

    try:
        # Reset database if requested
        if reset_database:
            print("Resetting database schema...")
            app = ws.apps.get(name=app_name)
            _reset_schema(ws, app, lakebase_name, schema_name)
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


def _get_or_create_lakebase(
    ws: WorkspaceClient, database_name: str, capacity: str
) -> dict[str, Any]:
    """Get or create a Lakebase database instance."""
    try:
        existing = ws.database.get_database_instance(name=database_name)
        return {
            "name": existing.name,
            "status": "exists",
            "state": existing.state.value if existing.state else "UNKNOWN",
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
        "status": "created",
        "state": instance.state.value if instance.state else "RUNNING",
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
) -> None:
    """Generate app.yaml with environment variables.
    
    Args:
        staging_dir: Directory to write the app.yaml file
        lakebase_name: Lakebase instance name
        schema_name: Schema name
        seed_databricks_defaults: If True, include Databricks-specific content seeding
    """
    # Build init_database call - only show seed_databricks_defaults when True
    if seed_databricks_defaults:
        init_call = "init_database(seed_databricks_defaults=True)"
    else:
        init_call = "init_database()"
    
    template_content = _load_template("app.yaml.template")
    content = Template(template_content).substitute(
        LAKEBASE_INSTANCE=lakebase_name,
        LAKEBASE_SCHEMA=schema_name,
        INIT_DATABASE_CALL=init_call,
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
) -> App:
    """Create Databricks App with database resource (without deploying).
    
    This creates the app and waits for it to be ready, but does NOT deploy.
    The app's service principal is available after creation, which is needed
    for setting up database schema permissions before deployment.
    """
    compute_size_enum = ComputeSize(compute_size)

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
    ws: WorkspaceClient, lakebase_name: str
) -> tuple[Any, str]:
    """Get a psycopg2 connection to Lakebase and the current username.

    Returns:
        Tuple of (connection, username)
    """
    try:
        import psycopg2
    except ImportError as exc:
        raise DeploymentError(
            "psycopg2-binary is required for database operations"
        ) from exc

    instance = ws.database.get_database_instance(name=lakebase_name)
    user = ws.current_user.me().user_name

    cred = ws.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[lakebase_name],
    )

    conn = psycopg2.connect(
        host=instance.read_write_dns,
        port=5432,
        user=user,
        password=cred.token,
        dbname="databricks_postgres",
        sslmode="require",
    )
    conn.autocommit = True

    return conn, user


def _setup_database_schema(
    ws: WorkspaceClient, app: App, lakebase_name: str, schema_name: str
) -> None:
    """Set up database schema and grant permissions to app."""
    client_id = _get_app_client_id(app)

    if not client_id:
        print("   Warning: Could not get app client ID - schema setup skipped")
        return

    conn, _ = _get_lakebase_connection(ws, lakebase_name)

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
) -> None:
    """Drop and recreate schema (tables will be recreated by app on startup).

    Args:
        ws: WorkspaceClient
        app: The Databricks App (needed for service principal ID)
        lakebase_name: Lakebase instance name
        schema_name: Schema to reset
        drop_only: If True, only drop the schema without recreating
    """
    client_id = _get_app_client_id(app)

    conn, _ = _get_lakebase_connection(ws, lakebase_name)

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
    """Grant schema permissions to an app's service principal."""
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

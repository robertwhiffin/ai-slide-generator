"""Databricks Apps deployment utilities for Tellr."""

from __future__ import annotations

import logging
import os
import uuid
from importlib import metadata
from pathlib import Path
from string import Template
from typing import Any

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


def setup(
    lakebase_name: str | None = None,
    schema_name: str | None = None,
    app_name: str | None = None,
    app_file_workspace_path: str | None = None,
    lakebase_compute: str | None = "CU_1",
    app_compute: str | None = "MEDIUM",
    app_version: str | None = None,
    client: WorkspaceClient | None = None,
    databricks_cfg_profile_name: str | None = None,
    config_yaml_path: str | None = None,
) -> dict[str, Any]:
    """
    Deploy Tellr to Databricks Apps using PyPI-only installs.

    Steps:
      1. Create/get Lakebase instance
      2. Generate requirements.txt with pinned app version
      3. Generate app.yaml with env vars
      4. Upload files to workspace
      5. Create Databricks App with database resource
      6. Return app URL

    Authentication flow;
    - If a Workspace Client is provided, use it
    - If databricks_cfg_profile_name is provided, use it to create a Workspace Client
    - Else, use the default Databricks CLI profile to create a Workspace Client
    """

    # create workspace client if necessary
    if client:
        pass
    elif databricks_cfg_profile_name:
        client = WorkspaceClient(profile=databricks_cfg_profile_name)
    else:
        client = WorkspaceClient()

    # check if config_yaml_path is provided and error if yaml and other args are set
    if config_yaml_path and (lakebase_name or schema_name or app_name or app_file_workspace_path):
        raise ValueError("config_yaml_path cannot be used with other arguments")

    # load config from yaml if provided
    config = None
    if config_yaml_path:
        config = _load_deployment_config(config_yaml_path)

    # set args from config if provided
    if config:
        lakebase_name = config.get("lakebase_name", lakebase_name)
        schema_name = config.get("schema_name", schema_name)
        app_name = config.get("app_name", app_name)
        app_file_workspace_path = config.get("app_file_workspace_path", app_file_workspace_path)
        lakebase_compute = config.get("lakebase_compute", lakebase_compute)
        app_compute = config.get("app_compute", app_compute)

    if not all([lakebase_name, schema_name, app_name, app_file_workspace_path]):
        raise ValueError("lakebase_name, schema_name, app_name, and app_file_workspace_path are required")

    _ensure_lakebase_instance(client, lakebase_name, lakebase_compute or "CU_1")
    requirements_content = _render_requirements(app_version)
    app_yaml_content = _render_app_yaml(lakebase_name, schema_name)

    _upload_artifacts(
        client,
        app_file_workspace_path,
        {
            "requirements.txt": requirements_content,
            "app.yaml": app_yaml_content,
        },
    )

    app = _create_app(
        client,
        app_name,
        app_file_workspace_path,
        app_compute,
        lakebase_name,
    )
    _setup_schema(client, lakebase_name, schema_name, _get_app_client_id(app))

    return {"app_name": app.name, "url": getattr(app, "url", None)}


def _load_deployment_config(config_yaml_path: str) -> dict[str, str]:
    """
    Load deployment settings from config/deployment.yaml-style files.

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


def update(app_name: str, app_file_workspace_path: str, app_version: str | None = None) -> None:
    """Update the app deployment with a new app version."""
    client = WorkspaceClient()
    requirements_content = _render_requirements(app_version)

    _upload_artifacts(
        client,
        app_file_workspace_path,
        {
            "requirements.txt": requirements_content,
        },
    )

    deployment = AppDeployment(source_code_path=app_file_workspace_path)
    client.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)


def delete(app_name: str) -> None:
    """Delete the Databricks App."""
    client = WorkspaceClient()
    client.apps.delete(name=app_name)


def _render_app_yaml(lakebase_name: str, schema_name: str) -> str:
    template_path = Path(__file__).parent / "_templates" / "app.yaml.template"
    template = Template(template_path.read_text())
    return template.substitute(
        LAKEBASE_INSTANCE=lakebase_name,
        LAKEBASE_SCHEMA=schema_name,
    )


def _render_requirements(app_version: str | None) -> str:
    resolved_version = app_version or _resolve_installed_app_version()
    if resolved_version and not _is_valid_version(resolved_version):
        raise DeploymentError(
            f"Invalid app version '{resolved_version}'. Expected a PEP 440 version."
        )

    if resolved_version:
        package_line = f"databricks-tellr-app=={resolved_version}"
    else:
        package_line = "databricks-tellr-app"

    return "\n".join(
        [
            "# Generated by databricks-tellr setup",
            package_line,
        ]
    )


def _resolve_installed_app_version() -> str | None:
    try:
        return metadata.version("databricks-tellr-app")
    except metadata.PackageNotFoundError:
        return None


def _is_valid_version(version: str) -> bool:
    try:
        from packaging.version import Version
    except ImportError:
        return True
    try:
        Version(version)
        return True
    except Exception:
        return False


def _upload_artifacts(
    client: WorkspaceClient,
    workspace_path: str,
    files: dict[str, str],
) -> None:
    client.workspace.mkdirs(workspace_path)
    for name, content in files.items():
        upload_path = f"{workspace_path}/{name}"
        client.workspace.upload(
            upload_path,
            content.encode("utf-8"),
            format=ImportFormat.AUTO,
            overwrite=True,
        )
        logger.info("Uploaded %s to %s", name, upload_path)


def _ensure_lakebase_instance(
    client: WorkspaceClient, instance_name: str, capacity: str
) -> None:
    try:
        client.database.get_database_instance(name=instance_name)
        return
    except Exception:
        pass

    client.database.create_database_instance_and_wait(
        DatabaseInstance(name=instance_name, capacity=capacity)
    )


def _create_app(
    client: WorkspaceClient,
    app_name: str,
    workspace_path: str,
    compute_size: str,
    lakebase_instance: str,
) -> App:
    resources = [
        AppResource(
            name="app_database",
            database=AppResourceDatabase(
                instance_name=lakebase_instance,
                database_name="databricks_postgres",
                permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
            ),
        )
    ]

    app = App(
        name=app_name,
        compute_size=ComputeSize(compute_size),
        default_source_code_path=workspace_path,
        resources=resources,
    )
    result = client.apps.create_and_wait(app)

    deployment = AppDeployment(source_code_path=workspace_path)
    client.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)
    return client.apps.get(name=app_name)


def _get_app_client_id(app: App) -> str:
    if hasattr(app, "service_principal_client_id") and app.service_principal_client_id:
        return app.service_principal_client_id
    if hasattr(app, "service_principal_id") and app.service_principal_id:
        return str(app.service_principal_id)
    raise DeploymentError("Could not determine app service principal client ID")


def _setup_schema(
    client: WorkspaceClient, instance_name: str, schema: str, client_id: str
) -> None:
    try:
        import psycopg2
    except ImportError as exc:
        raise DeploymentError("psycopg2-binary is required for schema setup") from exc

    instance = client.database.get_database_instance(name=instance_name)
    user = client.current_user.me().user_name
    credential = client.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[instance_name],
    )

    conn = psycopg2.connect(
        host=instance.read_write_dns,
        port=5432,
        user=user,
        password=credential.token,
        dbname="databricks_postgres",
        sslmode="require",
    )
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        cur.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{client_id}"')
        cur.execute(f'GRANT CREATE ON SCHEMA "{schema}" TO "{client_id}"')
        cur.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{client_id}"'
        )
        cur.execute(
            f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{client_id}"'
        )
        cur.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{client_id}"'
        )
        cur.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            f'GRANT USAGE, SELECT ON SEQUENCES TO "{client_id}"'
        )

    conn.close()
"""Deployment orchestration for Tellr on Databricks Apps.

This module provides the main setup/update/delete functions for deploying
the Tellr AI slide generator to Databricks Apps from a notebook.
"""

import logging
import os
import shutil
import uuid
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from string import Template
from typing import Iterator, Optional

import psycopg2
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


def setup(
    lakebase_name: str,
    schema_name: str,
    app_name: str,
    app_file_workspace_path: str,
    lakebase_compute: str = "CU_1",
    app_compute: str = "MEDIUM",
    app_version: Optional[str] = None,
    description: str = "Tellr AI Slide Generator",
) -> dict:
    """Deploy Tellr to Databricks Apps.

    This function creates all necessary infrastructure and deploys the app:
    1. Creates/gets Lakebase database instance
    2. Generates requirements.txt with pinned app version
    3. Generates app.yaml with environment variables
    4. Uploads files to workspace
    5. Creates Databricks App with database resource
    6. Sets up database schema and seeds default data

    Args:
        lakebase_name: Name for the Lakebase database instance
        schema_name: PostgreSQL schema name for app tables
        app_name: Name for the Databricks App
        app_file_workspace_path: Workspace path to upload app files
        lakebase_compute: Lakebase capacity (CU_1, CU_2, CU_4, CU_8)
        app_compute: App compute size (MEDIUM, LARGE, LIQUID)
        app_version: Specific databricks-tellr-app version (default: latest)
        description: App description

    Returns:
        Dictionary with deployment info:
        - url: App URL
        - app_name: Created app name
        - lakebase_name: Database instance name
        - schema_name: Schema name
        - status: "created"

    Raises:
        DeploymentError: If deployment fails
    """
    print(f"🚀 Deploying Tellr to Databricks Apps...")
    print(f"   App name: {app_name}")
    print(f"   Workspace path: {app_file_workspace_path}")
    print(f"   Lakebase: {lakebase_name} (capacity: {lakebase_compute})")
    print(f"   Schema: {schema_name}")
    print()

    # Get workspace client (uses notebook auth)
    ws = WorkspaceClient()

    try:
        # Step 1: Create/get Lakebase instance
        print("📊 Setting up Lakebase database...")
        lakebase_result = _get_or_create_lakebase(ws, lakebase_name, lakebase_compute)
        print(f"   ✅ Lakebase: {lakebase_result['name']} ({lakebase_result['status']})")
        print()

        # Step 2: Generate and upload files
        print("📁 Preparing deployment files...")
        with _staging_dir(app_file_workspace_path) as staging:
            # Generate requirements.txt
            _write_requirements(staging, app_version)
            print("   ✓ Generated requirements.txt")

            # Generate app.yaml
            _write_app_yaml(staging, lakebase_name, schema_name)
            print("   ✓ Generated app.yaml")

            # Upload to workspace
            print(f"☁️  Uploading to: {app_file_workspace_path}")
            _upload_files(ws, staging, app_file_workspace_path)
            print("   ✅ Files uploaded")
        print()

        # Step 3: Create app
        print(f"🔧 Creating Databricks App: {app_name}")
        app = _create_app(
            ws,
            app_name=app_name,
            description=description,
            workspace_path=app_file_workspace_path,
            compute_size=app_compute,
            lakebase_name=lakebase_name,
        )
        print(f"   ✅ App created")
        if app.url:
            print(f"   🌐 URL: {app.url}")
        print()

        # Step 4: Set up database schema
        print("📊 Setting up database schema...")
        _setup_database_schema(ws, app, lakebase_name, schema_name)
        print(f"   ✅ Schema '{schema_name}' configured")
        print()

        print("✅ Deployment complete!")
        return {
            "url": app.url,
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "schema_name": schema_name,
            "status": "created",
        }

    except Exception as e:
        raise DeploymentError(f"Deployment failed: {e}") from e


def update(
    app_name: str,
    app_file_workspace_path: str,
    lakebase_name: str,
    schema_name: str,
    app_version: Optional[str] = None,
) -> dict:
    """Deploy a new version of an existing Tellr app.

    Updates the app files and triggers a new deployment.

    Args:
        app_name: Name of the existing Databricks App
        app_file_workspace_path: Workspace path with app files
        lakebase_name: Lakebase instance name
        schema_name: Schema name
        app_version: Specific databricks-tellr-app version (default: latest)

    Returns:
        Dictionary with deployment info

    Raises:
        DeploymentError: If update fails
    """
    print(f"🔄 Updating Tellr app: {app_name}")

    ws = WorkspaceClient()

    try:
        # Generate and upload updated files
        with _staging_dir(app_file_workspace_path) as staging:
            _write_requirements(staging, app_version)
            _write_app_yaml(staging, lakebase_name, schema_name)
            _upload_files(ws, staging, app_file_workspace_path)
            print("   ✅ Files updated")

        # Trigger new deployment
        print("   ⏳ Deploying...")
        deployment = AppDeployment(source_code_path=app_file_workspace_path)
        result = ws.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)
        print(f"   ✅ Deployment completed: {result.deployment_id}")

        app = ws.apps.get(name=app_name)
        if app.url:
            print(f"   🌐 URL: {app.url}")

        return {
            "url": app.url,
            "app_name": app_name,
            "deployment_id": result.deployment_id,
            "status": "updated",
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e


def delete(app_name: str) -> dict:
    """Delete a Tellr app.

    Note: This does not delete the Lakebase instance or data.

    Args:
        app_name: Name of the app to delete

    Returns:
        Dictionary with deletion status

    Raises:
        DeploymentError: If deletion fails
    """
    print(f"🗑️  Deleting app: {app_name}")

    ws = WorkspaceClient()

    try:
        ws.apps.delete(name=app_name)
        print("   ✅ App deleted")
        return {"app_name": app_name, "status": "deleted"}
    except Exception as e:
        raise DeploymentError(f"Deletion failed: {e}") from e


# -----------------------------------------------------------------------------
# Internal functions
# -----------------------------------------------------------------------------


def _get_or_create_lakebase(
    ws: WorkspaceClient, database_name: str, capacity: str
) -> dict:
    """Get or create a Lakebase database instance."""
    try:
        # Check if exists
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

    # Create new instance
    instance = ws.database.create_database_instance_and_wait(
        DatabaseInstance(name=database_name, capacity=capacity)
    )
    return {
        "name": instance.name,
        "status": "created",
        "state": instance.state.value if instance.state else "RUNNING",
    }


def _write_requirements(staging_dir: Path, app_version: Optional[str]) -> None:
    """Generate requirements.txt with app package."""
    if app_version and not _is_valid_version(app_version):
        raise DeploymentError(
            f"Invalid app version '{app_version}'. Expected a PEP 440 version."
        )

    if app_version:
        package_line = f"databricks-tellr-app=={app_version}"
    else:
        package_line = "databricks-tellr-app"

    content = "\n".join(
        [
            "# Generated by databricks-tellr setup",
            package_line,
        ]
    )
    (staging_dir / "requirements.txt").write_text(content)


def _write_app_yaml(staging_dir: Path, lakebase_name: str, schema_name: str) -> None:
    """Generate app.yaml with environment variables."""
    template_content = _load_template("app.yaml.template")
    content = Template(template_content).substitute(
        LAKEBASE_INSTANCE=lakebase_name,
        LAKEBASE_SCHEMA=schema_name,
    )
    (staging_dir / "app.yaml").write_text(content)


def _load_template(template_name: str) -> str:
    """Load a template file from package resources."""
    try:
        # Python 3.9+ style
        files = resources.files("databricks_tellr") / "_templates" / template_name
        return files.read_text()
    except (TypeError, AttributeError):
        # Fallback for older Python
        with resources.open_text(
            "databricks_tellr._templates", template_name
        ) as f:
            return f.read()


def _is_valid_version(version: str) -> bool:
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
def _staging_dir(app_file_workspace_path: str) -> Iterator[Path]:
    base_path = Path(app_file_workspace_path)
    staging_dir = base_path / f".tellr_staging_{uuid.uuid4().hex}"
    try:
        staging_dir.mkdir(parents=True, exist_ok=False)
    except Exception as exc:
        raise DeploymentError(
            f"Failed to create staging directory at {staging_dir}: {exc}"
        ) from exc

    try:
        yield staging_dir
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _upload_files(
    ws: WorkspaceClient, staging_dir: Path, workspace_path: str
) -> None:
    """Upload files from staging directory to workspace."""
    # Ensure directory exists
    try:
        ws.workspace.mkdirs(workspace_path)
    except Exception:
        pass  # May already exist

    # Upload each file
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
    """Create Databricks App with database resource."""
    compute_size_enum = ComputeSize(compute_size)

    # Database resource
    resources = [
        AppResource(
            name="app_database",
            database=AppResourceDatabase(
                instance_name=lakebase_name,
                database_name="databricks_postgres",
                permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
            ),
        )
    ]

    # Create app
    app = App(
        name=app_name,
        description=description,
        compute_size=compute_size_enum,
        default_source_code_path=workspace_path,
        resources=resources,
        user_api_scopes=[
            "sql",
            "dashboards.genie",
            "catalog.tables:read",
            "catalog.schemas:read",
            "catalog.catalogs:read",
            "serving.serving-endpoints",
        ],
    )

    result = ws.apps.create_and_wait(app)

    # Trigger initial deployment
    deployment = AppDeployment(source_code_path=workspace_path)
    ws.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)

    # Refresh to get URL
    return ws.apps.get(name=app_name)


def _setup_database_schema(
    ws: WorkspaceClient, app: App, lakebase_name: str, schema_name: str
) -> None:
    """Set up database schema and grant permissions to app."""
    # Get app's service principal client ID
    client_id = None
    if hasattr(app, "service_principal_client_id") and app.service_principal_client_id:
        client_id = app.service_principal_client_id
    elif hasattr(app, "service_principal_id") and app.service_principal_id:
        client_id = str(app.service_principal_id)

    if not client_id:
        print("   ⚠️  Could not get app client ID - schema setup skipped")
        return

    # Get connection info
    instance = ws.database.get_database_instance(name=lakebase_name)
    user = ws.current_user.me().user_name

    # Generate credential
    cred = ws.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[lakebase_name],
    )

    # Connect and create schema
    conn = psycopg2.connect(
        host=instance.read_write_dns,
        port=5432,
        user=user,
        password=cred.token,
        dbname="databricks_postgres",
        sslmode="require",
    )
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
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

    conn.close()

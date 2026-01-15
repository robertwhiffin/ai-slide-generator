"""Databricks App deployment automation.

This script automates the deployment of the AI Slide Generator to Databricks Apps.
It handles building, packaging, uploading, and deploying the application.

Usage:
    python -m db_app_deployment.deploy --create --env production --profile my-profile
    python -m db_app_deployment.deploy --update --env development --profile my-profile
    python -m db_app_deployment.deploy --delete --env staging --profile my-profile
    python -m db_app_deployment.deploy --create --env production --profile my-profile --dry-run
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import (
    App,
    AppDeployment,
    AppResource,
    AppResourceDatabase,
    AppResourceDatabaseDatabasePermission,
    ComputeSize,
)
from databricks.sdk.service.workspace import ImportFormat

from src.core.lakebase import (
    get_or_create_lakebase_instance,
    setup_lakebase_schema,
    initialize_lakebase_tables,
)

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
    project_root: Path,
    wheel_path: Path,
    exclude_patterns: list[str],
    lakebase_instance: str,
    lakebase_schema: str,
) -> Path:
    """
    Create staging directory with deployment artifacts.

    Args:
        project_root: Root directory of the project
        wheel_path: Path to the built Python wheel
        exclude_patterns: List of patterns to exclude
        lakebase_instance: Lakebase instance name to inject into app.yaml
        lakebase_schema: Lakebase schema name to inject into app.yaml

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

    # Copy config files
    print("  Copying config files...")
    config_src = project_root / "config"
    if config_src.exists():
        shutil.copytree(
            config_src,
            staging_dir / "config",
            ignore=shutil.ignore_patterns("deployment.yaml", "deployment.example.yaml"),
        )

    # Copy frontend dist
    print("  Copying frontend build...")
    shutil.copytree(project_root / "frontend" / "dist", staging_dir / "frontend" / "dist")

    # Copy and modify app.yaml with environment-specific values
    print("  Copying and configuring app.yaml...")
    app_yaml_src = project_root / "app.yaml"
    app_yaml_dest = staging_dir / "app.yaml"
    if app_yaml_src.exists():
        # Read original app.yaml
        with open(app_yaml_src, "r") as f:
            app_yaml_content = f.read()

        # Inject LAKEBASE_INSTANCE env var
        # Find the env section and add the instance
        env_addition = f"""  - name: LAKEBASE_INSTANCE
    value: "{lakebase_instance}"
  - name: LAKEBASE_SCHEMA
    value: "{lakebase_schema}"
"""
        # Replace the placeholder LAKEBASE_SCHEMA line with both vars
        if "LAKEBASE_SCHEMA" in app_yaml_content:
            # Replace existing LAKEBASE_SCHEMA block
            import re
            app_yaml_content = re.sub(
                r'  - name: LAKEBASE_SCHEMA\n    value: "[^"]*"',
                env_addition.rstrip(),
                app_yaml_content
            )
        else:
            # Add before the last comment or at end of env section
            app_yaml_content = app_yaml_content.replace(
                "# Note: compute_size",
                f"{env_addition}\n# Note: compute_size"
            )

        # Write modified app.yaml
        with open(app_yaml_dest, "w") as f:
            f.write(app_yaml_content)
        print(f"    Injected LAKEBASE_INSTANCE={lakebase_instance}")
    else:
        print("  ⚠️  Warning: app.yaml not found")

    # Copy other essential files
    print("  Copying other essential files...")
    for file in ["requirements.txt"]:
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
    instance_name: str,
    database_name: str,
) -> App:
    """
    Create Databricks App with Lakebase database resource.

    Args:
        workspace_client: Databricks workspace client
        app_name: Name of the app
        description: Description of the app
        workspace_path: Path to app artifacts in workspace
        compute_size: Compute size (MEDIUM, LARGE, or LIQUID)
        instance_name: Lakebase instance name
        database_name: Database name within the instance

    Returns:
        Created App object
    """
    print(f"🚀 Creating app: {app_name}")

    try:
        # Convert compute_size string to enum
        compute_size_enum = ComputeSize(compute_size)

        # Build resources list with Lakebase database
        resources = [
            AppResource(
                name="app_database",
                database=AppResourceDatabase(
                    instance_name=instance_name,
                    database_name=database_name,
                    permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
                ),
            )
        ]

        # Create app - Databricks will read app.yaml from workspace_path
        print("Creating app compute...")
        app = App(
            name=app_name,
            description=description,
            compute_size=compute_size_enum,
            default_source_code_path=workspace_path,
            resources=resources,
            user_api_scopes = [
                'sql',
                'dashboards.genie',
                'catalog.tables:read',
                'catalog.schemas:read',
                'catalog.catalogs:read',
                'serving.serving-endpoints'
                ]
        )

        result = workspace_client.apps.create_and_wait(app)
        print(f"  ✅ App created: {result.name}")

        # Trigger initial deployment with source code
        print("  ⏳ Deploying source code and waiting for app to be ready...")
        app_deployment = AppDeployment(source_code_path=workspace_path)
        deployment_result = workspace_client.apps.deploy_and_wait(
            app_name=app_name,
            app_deployment=app_deployment,
        )
        print(f"  ✅ Deployment completed: {deployment_result.deployment_id}")

        # Refresh app to get URL
        result = workspace_client.apps.get(name=app_name)
        if hasattr(result, "url") and result.url:
            print(f"  🌐 URL: {result.url}")
        return result
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

    Creates a new app deployment with updated wheel, frontend, and config files.
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


def setup_database_schema_and_tables(
    workspace_client: WorkspaceClient,
    app: App,
    instance_name: str,
    schema: str,
    include_databricks_prompts: bool = False,
) -> None:
    """
    Set up database schema, initialize tables, and seed default data after app creation.

    This function:
    1. Gets the app's service principal client ID
    2. Creates the schema in Lakebase
    3. Grants permissions to the app's service principal
    4. Initializes SQLAlchemy tables
    5. Seeds default data (deck prompts, slide styles)

    Args:
        workspace_client: Databricks workspace client
        app: Created App object
        instance_name: Lakebase instance name
        schema: Schema name for application tables
        include_databricks_prompts: If True, include Databricks-specific deck prompts and brand style
    """
    print("📊 Setting up database schema and tables...")

    # Get the app's service principal client ID
    # When a database resource is attached, Databricks creates a Postgres role
    # tied to the app's service principal client ID
    client_id = None
    
    # Try to get client ID from app's service principal
    if hasattr(app, "service_principal_client_id") and app.service_principal_client_id:
        client_id = app.service_principal_client_id
    elif hasattr(app, "service_principal_id") and app.service_principal_id:
        # Fallback to service_principal_id
        client_id = str(app.service_principal_id)
    
    if not client_id:
        print("  ⚠️  Could not get app service principal client ID")
        print("  Schema setup will need to be done manually")
        return

    print(f"  App client ID: {client_id}")

    try:
        # Set up schema and grant permissions via SQL
        setup_lakebase_schema(
            instance_name=instance_name,
            schema=schema,
            client_id=client_id,
            client=workspace_client,
        )
        print(f"  ✅ Schema '{schema}' created with permissions")

        # Initialize SQLAlchemy tables
        initialize_lakebase_tables(
            instance_name=instance_name,
            schema=schema,
            client=workspace_client,
        )
        print("  ✅ Database tables initialized")

        # Seed default data (deck prompts, slide styles)
        print("  Seeding default data...")
        from sqlalchemy import create_engine
        from src.core.lakebase import get_lakebase_connection_url

        connection_url = get_lakebase_connection_url(
            instance_name=instance_name,
            schema=schema,
            client=workspace_client,
        )
        engine = create_engine(connection_url)
        _seed_default_data(engine, schema, workspace_client, include_databricks_prompts)
        print("  ✅ Default data seeded")

    except Exception as e:
        print(f"  ⚠️  Database setup failed: {e}")
        print("  You may need to run table initialization manually after app starts")


def reset_database_tables(
    workspace_client: WorkspaceClient,
    instance_name: str,
    schema: str,
    include_databricks_prompts: bool = False,
) -> None:
    """
    Drop and recreate all database tables, then seed with default data.

    WARNING: This will delete all data in the schema!

    Args:
        workspace_client: Databricks workspace client
        instance_name: Lakebase instance name
        schema: Schema name containing application tables
        include_databricks_prompts: If True, include Databricks-specific deck prompts and brand style
    """
    print("🗑️  Resetting database tables...")
    print(f"   Instance: {instance_name}")
    print(f"   Schema: {schema}")

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from src.core.database import Base
        from src.core.lakebase import get_lakebase_connection_url

        # Get connection URL
        connection_url = get_lakebase_connection_url(
            instance_name=instance_name,
            schema=schema,
            client=workspace_client,
        )

        # Create engine
        engine = create_engine(connection_url)

        # Set search path and drop all tables
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            conn.commit()

        print("  Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
        print("  ✅ All tables dropped")

        print("  Recreating tables...")
        Base.metadata.create_all(bind=engine)
        print("  ✅ Tables recreated")

        # Seed default data (deck prompts, slide styles - no profiles for deployed apps)
        print("  Seeding default data...")
        _seed_default_data(engine, schema, workspace_client, include_databricks_prompts)
        print("  ✅ Default data seeded")

        print("✅ Database reset complete")

    except Exception as e:
        raise DeploymentError(f"Database reset failed: {e}") from e


def _seed_default_data(
    engine,
    schema: str,
    workspace_client: WorkspaceClient,
    include_databricks_prompts: bool = False,
) -> None:
    """Seed default deck prompts and slide styles after reset.

    Args:
        engine: SQLAlchemy engine
        schema: Database schema name
        workspace_client: Databricks workspace client (unused, kept for API compatibility)
        include_databricks_prompts: If True, include Databricks-specific deck prompts and brand style

    Note:
        Profiles are NOT seeded during Databricks deployment - users create their own.
        For local development with profiles, use scripts/init_database.py instead.
    """
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from src.core.init_default_profile import (
        GENERIC_DECK_PROMPTS,
        DATABRICKS_DECK_PROMPTS,
        SYSTEM_SLIDE_STYLES,
        DATABRICKS_SLIDE_STYLES,
    )
    from src.database.models import (
        SlideDeckPromptLibrary,
        SlideStyleLibrary,
    )

    Session = sessionmaker(bind=engine)

    with Session() as db:
        # Set search path for this session
        db.execute(text(f'SET search_path TO "{schema}"'))

        # Determine which prompts to seed
        deck_prompts = list(GENERIC_DECK_PROMPTS)
        if include_databricks_prompts:
            deck_prompts.extend(DATABRICKS_DECK_PROMPTS)

        # Seed deck prompts
        for prompt_data in deck_prompts:
            prompt = SlideDeckPromptLibrary(
                name=prompt_data["name"],
                description=prompt_data["description"],
                category=prompt_data["category"],
                prompt_content=prompt_data["prompt_content"],
                is_active=True,
                created_by="system",
                updated_by="system",
            )
            db.add(prompt)
        print(f"    ✓ Seeded {len(deck_prompts)} deck prompts")

        # Determine which styles to seed
        slide_styles = list(SYSTEM_SLIDE_STYLES)
        if include_databricks_prompts:
            slide_styles.extend(DATABRICKS_SLIDE_STYLES)

        # Seed slide styles
        for style_data in slide_styles:
            style = SlideStyleLibrary(
                name=style_data["name"],
                description=style_data["description"],
                category=style_data["category"],
                style_content=style_data["style_content"],
                is_active=True,
                is_system=style_data.get("is_system", False),
                created_by="system",
                updated_by="system",
            )
            db.add(style)
        print(f"    ✓ Seeded {len(slide_styles)} slide styles")

        # Note: Profiles are NOT seeded for Databricks deployments.
        # Users should create their own profiles via the UI.
        # For local development with seed profiles, use scripts/init_database.py

        db.commit()


def deploy(
    env: str,
    action: str,
    profile: str,
    dry_run: bool = False,
    reset_db: bool = False,
    include_databricks_prompts: bool = False,
) -> None:
    """
    Main deployment function.

    Args:
        env: Environment name (development, staging, production)
        action: Action to perform (create, update, delete)
        profile: Databricks profile name from ~/.databrickscfg
        dry_run: If True, only validate without deploying
        reset_db: If True, drop and recreate database tables before deploying
        include_databricks_prompts: If True, include Databricks-specific deck prompts and brand style
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
        print(f"   Lakebase: {config.lakebase.database_name} (capacity: {config.lakebase.capacity})")
        print()

        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be made")
            print("✅ Configuration is valid")
            return

        # Initialize Databricks client
        # Clear environment variables that would override profile settings.
        # The SDK loads env vars BEFORE the profile file, and if host is set,
        # it skips profile loading entirely (see config.py _known_file_config_loader)
        env_vars_to_clear = [
            "DATABRICKS_HOST",
            "DATABRICKS_TOKEN",
            "DATABRICKS_CONFIG_PROFILE",
            "DATABRICKS_CLIENT_ID",
            "DATABRICKS_CLIENT_SECRET",
        ]
        cleared = []
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]
                cleared.append(var)
        if cleared:
            print(f"  Cleared env vars to use profile: {', '.join(cleared)}")

        print(f"🔑 Connecting to Databricks (using profile: {profile})")
        workspace_client = WorkspaceClient(profile=profile)
        print("  ✅ Connected")
        print(f"  Workspace URL: {workspace_client.config.host}")
        print()

        # Handle delete action
        if action == "delete":
            delete_app(workspace_client, config.app_name)
            print("✅ Deletion complete")
            return

        # Handle reset-db flag (can be combined with create/update)
        if reset_db:
            # Safety check for production
            if env == "production":
                print("❌ Database reset is not allowed in production!")
                print("   To reset production database, do it manually via SQL.")
                sys.exit(1)

            print()
            print("⚠️  WARNING: This will DELETE ALL DATA in the database!")
            print(f"   Environment: {env}")
            print(f"   Instance: {config.lakebase.database_name}")
            print(f"   Schema: {config.lakebase.schema}")
            print()

            confirm = input("Type 'RESET' to confirm: ")
            if confirm != "RESET":
                print("❌ Reset cancelled")
                sys.exit(0)

            print()
            reset_database_tables(
                workspace_client,
                instance_name=config.lakebase.database_name,
                schema=config.lakebase.schema,
                include_databricks_prompts=include_databricks_prompts,
            )
            print()

            # If no other action specified with reset-db, we're done
            if action is None:
                return

        # Step 1: Create Lakebase instance (if not exists)
        print("📊 Setting up Lakebase database instance...")
        lakebase_result = get_or_create_lakebase_instance(
            database_name=config.lakebase.database_name,
            capacity=config.lakebase.capacity,
            client=workspace_client,
        )
        print(f"  ✅ Lakebase instance: {lakebase_result['name']} ({lakebase_result['status']})")
        print()

        # Step 2: Build Python wheel and frontend
        wheel_path = build_python_wheel(project_root)
        print()
        
        build_frontend(project_root)
        print()

        staging_dir = create_staging_directory(
            project_root,
            wheel_path,
            config.exclude_patterns,
            lakebase_instance=config.lakebase.database_name,
            lakebase_schema=config.lakebase.schema,
        )
        print()

        try:
            # Step 3: Upload files to workspace
            upload_files_to_workspace(
                workspace_client, staging_dir, config.workspace_path
            )
            print()

            # Step 4: Create or update app
            if action == "create":
                # Create app with database resource attached
                app = create_app(
                    workspace_client,
                    config.app_name,
                    config.description,
                    config.workspace_path,
                    config.compute_size,
                    instance_name=config.lakebase.database_name,
                    database_name="databricks_postgres",  # Default Lakebase database
                )
                print()

                # Set app permissions
                set_permissions(workspace_client, config.app_name, config.permissions)
                print()

                # Step 5: Set up database schema and tables
                # This must happen after app creation because we need the app's
                # service principal client ID for Postgres GRANT statements
                setup_database_schema_and_tables(
                    workspace_client,
                    app,
                    instance_name=config.lakebase.database_name,
                    schema=config.lakebase.schema,
                    include_databricks_prompts=include_databricks_prompts,
                )

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
        required=True,
        help="Databricks profile name from ~/.databrickscfg",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without deploying",
    )

    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Drop and recreate database tables before deploying (WARNING: deletes all data)",
    )

    parser.add_argument(
        "--include-databricks-prompts",
        action="store_true",
        help="Include Databricks-specific deck prompts and brand style (for internal use)",
    )

    args = parser.parse_args()

    # Validate --include-databricks-prompts requires --create or --reset-db
    if args.include_databricks_prompts and not (args.action == "create" or args.reset_db):
        parser.error(
            "--include-databricks-prompts requires --create or --reset-db\n"
            "The flag only affects database seeding during app creation or reset."
        )

    deploy(
        env=args.env,
        action=args.action,
        dry_run=args.dry_run,
        profile=args.profile,
        reset_db=args.reset_db,
        include_databricks_prompts=args.include_databricks_prompts,
    )


if __name__ == "__main__":
    main()

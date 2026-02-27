"""Lakebase instance management for Databricks Apps.

This module provides utilities to create and manage Lakebase OLTP database instances
for persistent storage in Databricks deployments.

Lakebase is a fully managed PostgreSQL-compatible database that integrates with
Databricks Apps for transactional workloads.

See: https://docs.databricks.com/aws/en/oltp/instances/query/notebook#sqlalchemy
"""

import logging
import os
import uuid
from typing import Optional
from urllib.parse import quote_plus

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.database import DatabaseInstance

from src.core.databricks_client import get_databricks_client

# Autoscaling imports (Lakebase next-gen)
try:
    from databricks.sdk.service.postgres import Project, ProjectSpec
    _HAS_AUTOSCALING = True
except ImportError:
    _HAS_AUTOSCALING = False

logger = logging.getLogger(__name__)


class LakebaseError(Exception):
    """Raised when Lakebase operations fail."""

    pass


def get_or_create_lakebase_instance(
    database_name: str,
    capacity: str = "CU_1",
    client: Optional[WorkspaceClient] = None,
) -> dict:
    """
    Get or create a Lakebase OLTP database instance.

    Uses the Database API to create an actual PostgreSQL-compatible database instance.
    If the instance already exists, returns its details without recreating.

    Args:
        database_name: Name for the database instance
        capacity: Instance capacity units (CU_1, CU_2, CU_4, CU_8). Defaults to CU_1.
        client: Optional WorkspaceClient (uses singleton if not provided)

    Returns:
        Dictionary with instance information:
        - name: Instance name
        - status: 'created' or 'exists'
        - state: Current instance state (e.g., 'RUNNING')
        - read_write_dns: The DNS hostname for connections

    Raises:
        LakebaseError: If instance creation fails
    """
    ws = client or get_databricks_client()

    logger.info(
        "Getting or creating Lakebase instance",
        extra={"database_name": database_name, "capacity": capacity},
    )

    try:
        # Check if instance already exists
        try:
            existing = ws.database.get_database_instance(name=database_name)
            logger.info(f"Lakebase instance already exists: {existing.name}")
            return {
                "name": existing.name,
                "status": "exists",
                "state": existing.state.value if existing.state else "UNKNOWN",
                "read_write_dns": existing.read_write_dns,
            }
        except Exception as e:
            # Instance doesn't exist, check if it's a "not found" error
            error_str = str(e).lower()
            if "not found" not in error_str and "does not exist" not in error_str:
                # Re-raise if it's a different error
                raise

        # Create new instance
        logger.info(f"Creating new Lakebase instance: {database_name}")
        instance = ws.database.create_database_instance_and_wait(
            DatabaseInstance(
                name=database_name,
                capacity=capacity,
            )
        )

        logger.info(f"Lakebase instance created: {instance.name}")
        return {
            "name": instance.name,
            "status": "created",
            "state": instance.state.value if instance.state else "RUNNING",
            "read_write_dns": instance.read_write_dns,
        }

    except Exception as e:
        logger.error(f"Failed to get/create Lakebase instance: {e}", exc_info=True)
        raise LakebaseError(f"Lakebase instance operation failed: {e}") from e


def generate_lakebase_credential(
    instance_name: str,
    client: Optional[WorkspaceClient] = None,
    endpoint_name: Optional[str] = None,
    lakebase_type: str = "provisioned",
) -> str:
    """
    Generate a database credential (OAuth token) for Lakebase authentication.

    Supports both provisioned (ws.database) and autoscaling (ws.postgres) APIs.

    Args:
        instance_name: Name of the Lakebase instance (provisioned)
        client: Optional WorkspaceClient (uses singleton if not provided)
        endpoint_name: Full endpoint resource name (autoscaling only)
        lakebase_type: 'autoscaling' or 'provisioned'

    Returns:
        OAuth token string to use as password

    Raises:
        LakebaseError: If credential generation fails
    """
    ws = client or get_databricks_client()

    try:
        if lakebase_type == "autoscaling" and endpoint_name:
            cred = ws.postgres.generate_database_credential(endpoint=endpoint_name)
            return cred.token
        else:
            cred = ws.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[instance_name],
            )
            return cred.token
    except Exception as e:
        logger.error(f"Failed to generate database credential: {e}", exc_info=True)
        raise LakebaseError(f"Credential generation failed: {e}") from e


def get_lakebase_connection_info(
    instance_name: str,
    user: Optional[str] = None,
    client: Optional[WorkspaceClient] = None,
    endpoint_name: Optional[str] = None,
    host: Optional[str] = None,
    lakebase_type: str = "provisioned",
) -> dict:
    """
    Get all connection information for a Lakebase instance.

    Supports both provisioned and autoscaling Lakebase.

    Args:
        instance_name: Name of the Lakebase instance (provisioned)
        user: Postgres username (uses PGUSER env var or current user if not provided)
        client: Optional WorkspaceClient (uses singleton if not provided)
        endpoint_name: Full endpoint resource name (autoscaling only)
        host: Pre-resolved host (autoscaling only)
        lakebase_type: 'autoscaling' or 'provisioned'

    Returns:
        Dictionary with connection details:
        - host: Database hostname
        - port: Database port (5432)
        - database: Database name (databricks_postgres)
        - user: Postgres username
        - password: OAuth token for authentication

    Raises:
        LakebaseError: If connection info retrieval fails
    """
    ws = client or get_databricks_client()

    try:
        if lakebase_type == "autoscaling" and host:
            resolved_host = host
        else:
            instance = ws.database.get_database_instance(name=instance_name)
            resolved_host = instance.read_write_dns

        # Get user from env var or current Databricks user
        if not user:
            user = os.getenv("PGUSER")
        if not user:
            try:
                user = ws.current_user.me().user_name
            except Exception:
                pass

        if not user:
            raise LakebaseError(
                "Could not determine Postgres user. Set PGUSER env var or provide user parameter."
            )

        # Generate credential
        password = generate_lakebase_credential(
            instance_name, client=ws,
            endpoint_name=endpoint_name, lakebase_type=lakebase_type,
        )

        return {
            "host": resolved_host,
            "port": 5432,
            "database": "databricks_postgres",
            "user": user,
            "password": password,
        }

    except LakebaseError:
        raise
    except Exception as e:
        logger.error(f"Failed to get connection info: {e}", exc_info=True)
        raise LakebaseError(f"Failed to get connection info: {e}") from e


def get_lakebase_connection_url(
    instance_name: str,
    user: Optional[str] = None,
    schema: Optional[str] = None,
    client: Optional[WorkspaceClient] = None,
    endpoint_name: Optional[str] = None,
    host: Optional[str] = None,
    lakebase_type: str = "provisioned",
) -> str:
    """
    Generate PostgreSQL connection URL for Lakebase.

    Supports both provisioned and autoscaling Lakebase.
    See: https://docs.databricks.com/aws/en/oltp/instances/query/notebook#sqlalchemy

    Args:
        instance_name: Name of the Lakebase instance
        user: Postgres username (uses PGUSER env var or current user if not provided)
        schema: Optional schema to set in search_path
        client: Optional WorkspaceClient (uses singleton if not provided)
        endpoint_name: Full endpoint resource name (autoscaling only)
        host: Pre-resolved host (autoscaling only)
        lakebase_type: 'autoscaling' or 'provisioned'

    Returns:
        SQLAlchemy-compatible PostgreSQL connection URL

    Example:
        postgresql://user:token@host:5432/databricks_postgres?sslmode=require
    """
    conn_info = get_lakebase_connection_info(
        instance_name=instance_name,
        user=user,
        client=client,
        endpoint_name=endpoint_name,
        host=host,
        lakebase_type=lakebase_type,
    )

    # URL-encode the password in case it contains special characters
    encoded_password = quote_plus(conn_info["password"])

    # Build connection URL with sslmode=require as per Databricks docs
    url = (
        f"postgresql://{conn_info['user']}:{encoded_password}"
        f"@{conn_info['host']}:{conn_info['port']}/{conn_info['database']}"
        f"?sslmode=require"
    )

    if schema:
        url += f"&options=-csearch_path%3D{schema}"

    return url


def setup_lakebase_schema(
    instance_name: str,
    schema: str,
    client_id: str,
    user: Optional[str] = None,
    client: Optional[WorkspaceClient] = None,
    endpoint_name: Optional[str] = None,
    host: Optional[str] = None,
    lakebase_type: str = "provisioned",
) -> None:
    """
    Set up schema and grant permissions in Lakebase for an app.

    Supports both provisioned and autoscaling Lakebase.

    This function connects to the Lakebase instance and:
    1. Creates the schema if it doesn't exist
    2. Grants necessary permissions to the app's service principal (client_id)

    Note: This should be called after the app is created and the database
    resource is attached, as the client_id comes from the app's service principal.

    Args:
        instance_name: Name of the Lakebase instance
        schema: Schema name to create
        client_id: App's service principal client ID (becomes Postgres role)
        user: Postgres username for connection (uses default if not provided)
        client: Optional WorkspaceClient
        endpoint_name: Full endpoint resource name (autoscaling only)
        host: Pre-resolved host (autoscaling only)
        lakebase_type: 'autoscaling' or 'provisioned'

    Raises:
        LakebaseError: If schema setup fails
    """
    logger.info(
        "Setting up Lakebase schema",
        extra={
            "instance_name": instance_name, "schema": schema,
            "client_id": client_id, "lakebase_type": lakebase_type,
        },
    )

    try:
        # Get connection info
        conn_info = get_lakebase_connection_info(
            instance_name=instance_name,
            user=user,
            client=client,
            endpoint_name=endpoint_name,
            host=host,
            lakebase_type=lakebase_type,
        )

        # Use psycopg2 directly for DDL operations
        import psycopg2

        conn = psycopg2.connect(
            host=conn_info["host"],
            port=conn_info["port"],
            user=conn_info["user"],
            password=conn_info["password"],
            dbname=conn_info["database"],
            sslmode="require",
        )
        conn.autocommit = True

        with conn.cursor() as cur:
            # Create schema if not exists
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            logger.info(f"Schema created or verified: {schema}")

            # Grant permissions to app's service principal
            # The client_id is automatically available as a Postgres role when
            # the database is added as an app resource
            cur.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{client_id}"')
            cur.execute(f'GRANT CREATE ON SCHEMA "{schema}" TO "{client_id}"')

            # Grant permissions on all tables in schema (for existing tables)
            cur.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{client_id}"'
            )

            # Grant permissions on all sequences in schema (for auto-increment columns)
            cur.execute(
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{client_id}"'
            )

            # Set default privileges for future tables
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{client_id}"'
            )

            # Set default privileges for future sequences
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
                f'GRANT USAGE, SELECT ON SEQUENCES TO "{client_id}"'
            )

            logger.info(f"Permissions granted to {client_id} on schema {schema}")

        conn.close()

    except ImportError:
        raise LakebaseError(
            "psycopg2 is required for Lakebase schema setup. "
            "Install with: pip install psycopg2-binary"
        )
    except Exception as e:
        logger.error(f"Failed to setup Lakebase schema: {e}", exc_info=True)
        raise LakebaseError(f"Lakebase schema setup failed: {e}") from e


def initialize_lakebase_tables(
    instance_name: str,
    schema: str,
    user: Optional[str] = None,
    client: Optional[WorkspaceClient] = None,
    endpoint_name: Optional[str] = None,
    host: Optional[str] = None,
    lakebase_type: str = "provisioned",
) -> None:
    """
    Initialize SQLAlchemy tables in Lakebase.

    Creates all tables defined in the application's SQLAlchemy models.
    Should be called after schema setup and permissions are configured.

    Supports both provisioned and autoscaling Lakebase.

    Args:
        instance_name: Name of the Lakebase instance
        schema: Schema name where tables should be created
        user: Postgres username for connection (uses default if not provided)
        client: Optional WorkspaceClient
        endpoint_name: Full endpoint resource name (autoscaling only)
        host: Pre-resolved host (autoscaling only)
        lakebase_type: 'autoscaling' or 'provisioned'

    Raises:
        LakebaseError: If table initialization fails
    """
    logger.info(f"Initializing Lakebase tables in schema: {schema}")

    try:
        from sqlalchemy import create_engine, text

        # Get connection URL
        connection_url = get_lakebase_connection_url(
            instance_name=instance_name,
            user=user,
            schema=schema,
            client=client,
            endpoint_name=endpoint_name,
            host=host,
            lakebase_type=lakebase_type,
        )

        # Create engine
        engine = create_engine(connection_url)

        # Set search path to our schema
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            conn.commit()

        # Import Base and create all tables
        from src.core.database import Base

        Base.metadata.create_all(bind=engine)

        logger.info("Lakebase tables initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize Lakebase tables: {e}", exc_info=True)
        raise LakebaseError(f"Lakebase table initialization failed: {e}") from e

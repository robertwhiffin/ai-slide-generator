"""Lakebase instance management for Databricks Apps.

This module provides utilities to create and manage Lakebase database instances
for persistent storage in Databricks deployments.
"""

import logging
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import (
    CatalogInfo,
    SchemaInfo,
)

from src.core.databricks_client import get_databricks_client

logger = logging.getLogger(__name__)


class LakebaseError(Exception):
    """Raised when Lakebase operations fail."""

    pass


def create_lakebase_instance(
    catalog: str,
    database_name: str,
    schema: str = "app_data",
    client: Optional[WorkspaceClient] = None,
) -> dict:
    """
    Create Lakebase database instance in Unity Catalog.

    Creates the catalog, schema, and necessary structures for the application
    to store session data, configuration, and other persistent state.

    Args:
        catalog: Unity Catalog catalog name
        database_name: Database/schema name within the catalog
        schema: Schema name for application tables
        client: Optional WorkspaceClient (uses singleton if not provided)

    Returns:
        Dictionary with created resource information

    Raises:
        LakebaseError: If instance creation fails
    """
    ws = client or get_databricks_client()

    logger.info(
        "Creating Lakebase instance",
        extra={"catalog": catalog, "database_name": database_name, "schema": schema},
    )

    try:
        # Create or get catalog
        catalog_info = _ensure_catalog(ws, catalog)
        logger.info(f"Catalog ready: {catalog_info.name}")

        # Create or get schema
        schema_info = _ensure_schema(ws, catalog, schema)
        logger.info(f"Schema ready: {schema_info.full_name}")

        return {
            "catalog": catalog,
            "database_name": database_name,
            "schema": schema,
            "full_schema_name": f"{catalog}.{schema}",
            "status": "ready",
        }

    except Exception as e:
        logger.error(f"Failed to create Lakebase instance: {e}", exc_info=True)
        raise LakebaseError(f"Lakebase instance creation failed: {e}") from e


def _ensure_catalog(ws: WorkspaceClient, catalog_name: str) -> CatalogInfo:
    """Ensure catalog exists, creating if necessary."""
    try:
        return ws.catalogs.get(catalog_name)
    except Exception:
        logger.error(f"Catalog {catalog_name} does not exist. Please choose existing catalog.")
        raise LakebaseError(f"Catalog '{catalog_name}' does not exist. Please choose existing catalog.")


def _ensure_schema(ws: WorkspaceClient, catalog: str, schema_name: str) -> SchemaInfo:
    """Ensure schema exists within catalog, creating if necessary."""
    full_name = f"{catalog}.{schema_name}"
    try:
        return ws.schemas.get(full_name)
    except Exception:
        try:
            logger.info(f"Creating schema: {full_name}")
            return ws.schemas.create(name=schema_name, catalog_name=catalog)
        except Exception as e:
            error_msg = str(e)
            if "PERMISSION_DENIED" in error_msg or "does not have permission" in error_msg.lower():
                logger.error(
                    f"Permission denied when creating schema '{full_name}': {error_msg}",
                    exc_info=True,
                    extra={"catalog": catalog, "schema": schema_name}
                )
                raise LakebaseError(
                    f"Permission denied: You do not have permission to create schema '{schema_name}' in catalog '{catalog}'."
                ) from e
            else:
                logger.error(
                    f"Failed to create schema '{full_name}': {error_msg}",
                    exc_info=True
                )
                raise LakebaseError(
                    f"Failed to create schema '{schema_name}' in catalog '{catalog}': {error_msg}"
                ) from e


def get_lakebase_connection_url(
    catalog: str,
    schema: str,
    host: Optional[str] = None,
    token: Optional[str] = None,
    http_path: Optional[str] = None,
) -> str:
    """
    Generate SQLAlchemy connection URL for Lakebase.

    Uses the databricks-sql-connector format for SQLAlchemy connections.
    See: https://learn.microsoft.com/en-us/azure/databricks/oltp/instances/query/notebook#sqlalchemy

    Args:
        catalog: Unity Catalog catalog name
        schema: Schema name
        host: Databricks workspace host (from env if not provided)
        token: Databricks token (from env if not provided)
        http_path: SQL warehouse HTTP path (optional)

    Returns:
        SQLAlchemy connection URL string

    Example:
        databricks://token:***@host/catalog/schema?http_path=/sql/...
    """
    import os

    host = host or os.getenv("DATABRICKS_HOST", "")
    token = token or os.getenv("DATABRICKS_TOKEN", "")

    # Remove protocol from host if present
    if host.startswith("https://"):
        host = host[8:]
    elif host.startswith("http://"):
        host = host[7:]

    # Build connection URL
    url = f"databricks://token:{token}@{host}?catalog={catalog}&schema={schema}"

    if http_path:
        url += f"&http_path={http_path}"

    return url


def grant_service_principal_permissions(
    catalog: str,
    schema: str,
    principal_id: str,
    client: Optional[WorkspaceClient] = None,
) -> None:
    """
    Grant full access to a service principal on the Lakebase schema.

    This is used to give the Databricks App service principal access to
    the database for CRUD operations.

    Args:
        catalog: Unity Catalog catalog name
        schema: Schema name
        principal_id: Service principal application ID
        client: Optional WorkspaceClient

    Raises:
        LakebaseError: If permission grant fails
    """
    ws = client or get_databricks_client()

    logger.info(
        "Granting Lakebase permissions",
        extra={"catalog": catalog, "schema": schema, "principal_id": principal_id},
    )

    try:
        from databricks.sdk.service.catalog import (
            PermissionsChange,
            Privilege,
            SecurableType,
        )

        # Grant on catalog
        ws.grants.update(
            securable_type=SecurableType.CATALOG,
            full_name=catalog,
            changes=[
                PermissionsChange(
                    principal=principal_id,
                    add=[Privilege.USE_CATALOG],
                )
            ],
        )

        # Grant on schema
        full_schema = f"{catalog}.{schema}"
        ws.grants.update(
            securable_type=SecurableType.SCHEMA,
            full_name=full_schema,
            changes=[
                PermissionsChange(
                    principal=principal_id,
                    add=[
                        Privilege.USE_SCHEMA,
                        Privilege.CREATE_TABLE,
                        Privilege.SELECT,
                        Privilege.MODIFY,
                    ],
                )
            ],
        )

        logger.info("Lakebase permissions granted successfully")

    except Exception as e:
        logger.error(f"Failed to grant Lakebase permissions: {e}", exc_info=True)
        raise LakebaseError(f"Permission grant failed: {e}") from e


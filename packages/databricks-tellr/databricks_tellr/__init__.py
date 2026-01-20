"""Tellr deployment package for Databricks Apps."""

from databricks_tellr.deploy import create, delete, update

__all__ = ["create", "update", "delete"]

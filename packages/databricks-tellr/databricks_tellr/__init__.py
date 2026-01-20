"""Tellr deployment package for Databricks Apps."""

from databricks_tellr.deploy import delete, setup, update

__all__ = ["setup", "update", "delete"]

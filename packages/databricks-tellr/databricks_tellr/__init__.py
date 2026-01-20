"""Tellr deployment package for Databricks Apps."""

from databricks_tellr import deploy
from databricks_tellr.deploy import create, delete, update

__all__ = ["deploy", "create", "update", "delete"]

"""Workspace-wide settings an admin sets once for everyone.

One row per setting key, holding a JSON value. ``create_all`` builds the table on
startup, so a key absent from it reads as that setting's default.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, String

from src.core.database import Base


class WorkspaceSetting(Base):
    """One admin setting (``src.services.workspace_settings`` owns the keys)."""

    __tablename__ = "workspace_settings"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

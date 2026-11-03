"""Permission models: generic grants table and sync bookkeeping."""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from src.core.database import Base

RESOURCE_APP = "app"
APP_WIDE_RESOURCE_ID = ""
PRIVILEGE_ADMIN = "admin"
SOURCE_CAN_MANAGE_SYNC = "can_manage_sync"
SOURCE_MANUAL = "manual"
SYNC_KEY_APP_CAN_MANAGE = "app_can_manage"
# created_by value on synced rows: the "who" is the sync itself.
SYNC_CREATED_BY = "can_manage_sync"


class Permission(Base):
    """A privilege granted to a user or group on a resource."""

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)
    resource_type = Column(String(32), nullable=False)
    resource_id = Column(String(255), nullable=False, default=APP_WIDE_RESOURCE_ID)

    identity_type = Column(String(10), nullable=False)  # USER or GROUP
    identity_id = Column(String(255), nullable=True)  # Databricks user/group ID
    identity_name = Column(String(255), nullable=False)  # Display name
    identity_key = Column(String(255), nullable=False)  # normalized (lower-cased) name

    privilege = Column(String(32), nullable=False)
    source = Column(String(32), nullable=False)

    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "identity_type",
            "identity_key",
            "privilege",
            "source",
            name="uq_permissions_grant",
        ),
        Index("ix_permissions_lookup", "resource_type", "resource_id", "privilege"),
    )

    def __repr__(self):
        return (
            f"<Permission(id={self.id}, resource='{self.resource_type}:{self.resource_id}', "
            f"identity='{self.identity_type}:{self.identity_key}', privilege='{self.privilege}', "
            f"source='{self.source}')>"
        )


class PermissionSyncState(Base):
    """Bookkeeping for a permission sync loop."""

    __tablename__ = "permission_sync_state"

    sync_key = Column(String(64), primary_key=True)
    last_attempt_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

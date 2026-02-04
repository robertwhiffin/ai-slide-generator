"""Session permissions models for access control."""
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from src.core.database import Base


class PrincipalType(str, Enum):
    """Type of principal that can have permissions."""
    USER = "user"
    GROUP = "group"


class PermissionLevel(str, Enum):
    """Permission levels for sessions."""
    READ = "read"    # Can view session and slides
    EDIT = "edit"    # Can modify session, slides, and share


class SessionVisibility(str, Enum):
    """Session visibility levels."""
    PRIVATE = "private"      # Owner only
    SHARED = "shared"        # Owner + explicit grants
    WORKSPACE = "workspace"  # All workspace users


class SessionPermission(Base):
    """Access control entry for session sharing.
    
    Defines who (principal) has what permission (read/edit) on a session.
    Owners always have edit permission implicitly.
    """
    
    __tablename__ = "session_permissions"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Subject (who has access)
    principal_type = Column(String(20), nullable=False)  # 'user' or 'group'
    principal_id = Column(String(255), nullable=False)   # email or group name
    
    # Permission level
    permission = Column(String(20), nullable=False)      # 'read' or 'edit'
    
    # Metadata
    granted_by = Column(String(255), nullable=False)     # Who granted this permission
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    session = relationship("UserSession", back_populates="permissions")
    
    # Indexes for fast lookups
    __table_args__ = (
        Index("ix_session_permissions_session", "session_id"),
        Index("ix_session_permissions_principal", "principal_type", "principal_id"),
        # Unique constraint on session + principal
        Index("uq_session_principal", "session_id", "principal_type", "principal_id", unique=True),
    )
    
    def __repr__(self):
        return (
            f"<SessionPermission("
            f"session_id={self.session_id}, "
            f"{self.principal_type}={self.principal_id}, "
            f"permission={self.permission})>"
        )

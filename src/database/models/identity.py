"""SQLAlchemy model for local identity storage.

Stores identities of users who have signed into the app.
Used as fallback when no admin token is configured.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Index

from src.core.database import Base


class AppIdentity(Base):
    """
    Local storage for user and group identities.
    
    Populated automatically when users sign into the app.
    Used as fallback identity source when no admin tokens are configured.
    """
    __tablename__ = "app_identities"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Identity information
    identity_id = Column(String(255), unique=True, nullable=False, index=True)
    identity_type = Column(String(20), nullable=False)  # USER or GROUP
    identity_name = Column(String(255), nullable=False)  # Email for users, name for groups
    display_name = Column(String(255))  # Friendly display name
    
    # Timestamps
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Soft delete
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Indexes for common queries
    __table_args__ = (
        Index("idx_app_identities_type", "identity_type"),
        Index("idx_app_identities_name", "identity_name"),
        Index("idx_app_identities_active", "is_active"),
    )
    
    def __repr__(self):
        return f"<AppIdentity {self.identity_type}:{self.identity_name}>"
    
    def to_dict(self) -> dict:
        """Convert to dictionary format matching other providers."""
        if self.identity_type == "USER":
            return {
                "id": self.identity_id,
                "userName": self.identity_name,
                "displayName": self.display_name or self.identity_name,
                "type": "USER",
            }
        else:  # GROUP
            return {
                "id": self.identity_id,
                "displayName": self.display_name or self.identity_name,
                "type": "GROUP",
            }


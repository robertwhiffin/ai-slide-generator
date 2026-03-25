"""Profile contributor model for sharing profiles with Databricks UC identities."""
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from src.core.database import Base


class IdentityType(str, Enum):
    """Type of Databricks identity."""
    USER = "USER"
    GROUP = "GROUP"


class PermissionLevel(str, Enum):
    """Permission level for profile and deck access."""
    CAN_USE = "CAN_USE"        # Use only (e.g. generate slides with a profile)
    CAN_MANAGE = "CAN_MANAGE"  # Full control: edit, delete, share
    CAN_EDIT = "CAN_EDIT"      # Edit profile settings
    CAN_VIEW = "CAN_VIEW"      # View only


class ConfigProfileContributor(Base):
    """
    Profile contributor - users/groups with access to a profile.
    
    Each contributor entry represents a Databricks UC identity (user or group)
    with a specific permission level on a profile.
    
    Follows the config_* naming convention for configuration tables.
    Foreign key references config_profiles.id with CASCADE delete.
    """

    __tablename__ = "config_profile_contributors"

    id = Column(Integer, primary_key=True)
    profile_id = Column(
        Integer, 
        ForeignKey("config_profiles.id", ondelete="CASCADE"), 
        nullable=False,
        index=True,
    )

    # Databricks identity info
    identity_id = Column(String(255), nullable=False, index=True)  # Databricks user/group ID
    identity_type = Column(String(20), nullable=False)  # USER or GROUP
    identity_name = Column(String(255), nullable=False)  # Display name (email or group name)
    
    # Permission level
    permission_level = Column(String(20), nullable=False, default=PermissionLevel.CAN_USE.value)

    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255))  # Who added this contributor

    # Relationships
    profile = relationship("ConfigProfile", back_populates="contributors")

    # Constraints
    __table_args__ = (
        # Each identity can only have one entry per profile
        UniqueConstraint("profile_id", "identity_id", name="uq_config_profile_contributor_identity"),
    )

    def __repr__(self):
        return (
            f"<ConfigProfileContributor(id={self.id}, profile_id={self.profile_id}, "
            f"identity_name='{self.identity_name}', permission='{self.permission_level}')>"
        )


# Backward compatibility alias
ProfileContributor = ConfigProfileContributor


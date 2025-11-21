"""Genie space configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigGenieSpace(Base):
    """
    Genie space configuration.
    
    Each profile has exactly one Genie space. The unique constraint on
    profile_id enforces this at the database level.
    """

    __tablename__ = "config_genie_spaces"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False)

    space_id = Column(String(255), nullable=False)
    space_name = Column(String(255), nullable=False)
    description = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("ConfigProfile", back_populates="genie_spaces")

    # Constraints and indexes
    __table_args__ = (
        Index("idx_config_genie_spaces_profile", "profile_id"),
        UniqueConstraint("profile_id", name="uq_config_genie_spaces_profile"),
    )

    def __repr__(self):
        return f"<ConfigGenieSpace(id={self.id}, space_name='{self.space_name}')>"


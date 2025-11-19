"""Genie space configuration model."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigGenieSpace(Base):
    """Genie space configuration."""
    
    __tablename__ = "config_genie_spaces"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False)
    
    space_id = Column(String(255), nullable=False)
    space_name = Column(String(255), nullable=False)
    description = Column(Text)
    is_default = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="genie_spaces")
    
    # Indexes
    __table_args__ = (
        Index("idx_config_genie_spaces_profile", "profile_id"),
        Index("idx_config_genie_spaces_default", "profile_id", "is_default", 
              postgresql_where=(is_default == True)),
        # Note: single_default_space_per_profile constraint handled in migration
    )
    
    def __repr__(self):
        return f"<ConfigGenieSpace(id={self.id}, space_name='{self.space_name}', is_default={self.is_default})>"


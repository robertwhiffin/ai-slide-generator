"""Configuration profile model."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from src.core.database import Base


class ConfigProfile(Base):
    """Configuration profile."""

    __tablename__ = "config_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = Column(String(255))

    # Encrypted Google OAuth client credentials (credentials.json content)
    google_credentials_encrypted = Column(Text, nullable=True)

    # Relationships
    ai_infra = relationship("ConfigAIInfra", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    genie_spaces = relationship("ConfigGenieSpace", back_populates="profile", cascade="all, delete-orphan")
    prompts = relationship("ConfigPrompts", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    history = relationship("ConfigHistory", back_populates="profile", cascade="all, delete-orphan")

    # Note: single_default_profile constraint handled in migration

    def __repr__(self):
        return f"<ConfigProfile(id={self.id}, name='{self.name}', is_default={self.is_default})>"


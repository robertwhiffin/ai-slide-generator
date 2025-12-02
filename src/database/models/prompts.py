"""Prompts configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from src.core.database import Base


class ConfigPrompts(Base):
    """Prompts configuration."""

    __tablename__ = "config_prompts"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)

    system_prompt = Column(Text, nullable=False)
    slide_editing_instructions = Column(Text, nullable=False)
    user_prompt_template = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("ConfigProfile", back_populates="prompts")

    def __repr__(self):
        return f"<ConfigPrompts(id={self.id}, profile_id={self.profile_id})>"


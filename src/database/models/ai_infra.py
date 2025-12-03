"""AI Infrastructure configuration model."""
from datetime import datetime

from sqlalchemy import DECIMAL, CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from src.core.database import Base


class ConfigAIInfra(Base):
    """AI Infrastructure configuration."""

    __tablename__ = "config_ai_infra"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)

    # LLM settings
    llm_endpoint = Column(String(255), nullable=False)
    llm_temperature = Column(DECIMAL(3, 2), nullable=False)
    llm_max_tokens = Column(Integer, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("ConfigProfile", back_populates="ai_infra")

    # Constraints
    __table_args__ = (
        CheckConstraint("llm_temperature >= 0 AND llm_temperature <= 1", name="check_temperature_range"),
        CheckConstraint("llm_max_tokens > 0", name="check_max_tokens_positive"),
    )

    def __repr__(self):
        return f"<ConfigAIInfra(id={self.id}, profile_id={self.profile_id}, endpoint='{self.llm_endpoint}')>"


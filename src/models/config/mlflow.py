"""MLflow configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigMLflow(Base):
    """MLflow configuration."""

    __tablename__ = "config_mlflow"

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)

    experiment_name = Column(String(255), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("ConfigProfile", back_populates="mlflow")

    def __repr__(self):
        return f"<ConfigMLflow(id={self.id}, profile_id={self.profile_id}, experiment='{self.experiment_name}')>"


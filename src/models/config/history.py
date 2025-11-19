"""Configuration history model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, JSON
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigHistory(Base):
    """Configuration change history."""
    
    __tablename__ = "config_history"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False)
    domain = Column(String(50), nullable=False)  # 'ai_infra', 'genie', 'mlflow', 'prompts', 'profile'
    action = Column(String(50), nullable=False)  # 'create', 'update', 'delete', 'activate'
    changed_by = Column(String(255), nullable=False)
    changes = Column(JSON, nullable=False)  # {"field": {"old": "...", "new": "..."}}
    snapshot = Column(JSON)  # Full config snapshot at time of change
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="history")
    
    # Indexes
    __table_args__ = (
        Index("idx_config_history_profile", "profile_id"),
        Index("idx_config_history_timestamp", "timestamp"),
        Index("idx_config_history_domain", "domain"),
    )
    
    def __repr__(self):
        return f"<ConfigHistory(id={self.id}, domain='{self.domain}', action='{self.action}', timestamp={self.timestamp})>"


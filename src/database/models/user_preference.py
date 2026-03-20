"""Per-user profile preferences."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from src.core.database import Base


class UserProfilePreference(Base):
    """Stores each user's preferred default profile.

    Replaces the global is_default flag on config_profiles with a per-user
    preference. Falls back to the system default when no preference is set.
    """

    __tablename__ = "user_profile_preferences"

    id = Column(Integer, primary_key=True)
    user_name = Column(String(255), unique=True, nullable=False, index=True)
    default_profile_id = Column(
        Integer,
        ForeignKey("config_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    profile = relationship("ConfigProfile")

    def __repr__(self):
        return f"<UserProfilePreference(user={self.user_name}, profile_id={self.default_profile_id})>"

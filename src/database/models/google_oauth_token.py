"""Google OAuth token model.

Stores per-user encrypted Google OAuth tokens so that each
Databricks user can independently authorize with their own Google account.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from src.core.database import Base


class GoogleOAuthToken(Base):
    """Encrypted Google OAuth token scoped to a user."""

    __tablename__ = "google_oauth_tokens"

    id = Column(Integer, primary_key=True)
    user_identity = Column(String(255), nullable=False, index=True)
    token_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_identity", name="uq_user_identity_token"),
    )

    def __repr__(self) -> str:
        return f"<GoogleOAuthToken(id={self.id}, user='{self.user_identity}')>"

"""Google global credentials model.

Stores app-wide encrypted Google OAuth client credentials (credentials.json).
Single-row table: uploading again replaces the existing credentials.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from src.core.database import Base


class GoogleGlobalCredentials(Base):
    """App-wide encrypted Google OAuth client credentials."""

    __tablename__ = "google_global_credentials"

    id = Column(Integer, primary_key=True)
    credentials_encrypted = Column(Text, nullable=False)
    uploaded_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

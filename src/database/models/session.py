"""Session and message models for persistent session storage.

These models support multi-session functionality in production deployments
where session state is stored in Lakebase for persistence across app restarts.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from src.core.database import Base


class UserSession(Base):
    """User session for tracking conversation state.

    Each session represents an independent conversation context with its own
    chat history and slide deck state.
    """

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)  # Optional user identification

    # Session metadata
    title = Column(String(255))  # Optional session title/name
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Genie conversation tracking (cleared on profile switch)
    genie_conversation_id = Column(String(255), nullable=True)

    # Relationships
    messages = relationship(
        "SessionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionMessage.created_at",
    )
    slide_deck = relationship(
        "SessionSlideDeck",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_user_sessions_user_last_activity", "user_id", "last_activity"),
    )

    def __repr__(self):
        return f"<UserSession(session_id='{self.session_id}', user_id='{self.user_id}')>"


class SessionMessage(Base):
    """Chat message within a session.

    Stores the conversation history for replay and context.
    """

    __tablename__ = "session_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Message content
    role = Column(String(20), nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Optional metadata
    message_type = Column(String(50))  # 'chat', 'slide_update', 'error', etc.
    metadata_json = Column(Text)  # JSON string for additional metadata

    # Relationship
    session = relationship("UserSession", back_populates="messages")

    def __repr__(self):
        return f"<SessionMessage(id={self.id}, role='{self.role}', session_id={self.session_id})>"


class SessionSlideDeck(Base):
    """Slide deck state for a session.

    Stores the current slide deck HTML and metadata for persistence.
    """

    __tablename__ = "session_slide_decks"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Slide deck content
    title = Column(String(255))
    html_content = Column(Text)  # Full knitted HTML (legacy, for raw HTML view)
    scripts_content = Column(Text)  # JavaScript for charts, etc.
    slide_count = Column(Integer, default=0)
    
    # Full SlideDeck structure as JSON (for restoration)
    deck_json = Column(Text)  # JSON with slides array, css, external_scripts, scripts

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship
    session = relationship("UserSession", back_populates="slide_deck")

    def __repr__(self):
        return f"<SessionSlideDeck(session_id={self.session_id}, title='{self.title}')>"


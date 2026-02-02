"""Session and message models for persistent session storage.

These models support multi-session functionality in production deployments
where session state is stored in Lakebase for persistence across app restarts.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
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


class ChatRequest(Base):
    """Tracks async chat requests for polling.

    Used by the polling-based streaming implementation to track request
    status and results when SSE is not available (e.g., Databricks Apps).
    """

    __tablename__ = "chat_requests"

    id = Column(Integer, primary_key=True)
    request_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(20), default="pending")  # pending/running/completed/error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # Final result data (JSON) - slides, raw_html, replacement_info
    result_json = Column(Text, nullable=True)

    # Relationship
    session = relationship("UserSession")

    __table_args__ = (Index("ix_chat_requests_session_id", "session_id"),)

    def __repr__(self):
        return f"<ChatRequest(request_id='{self.request_id}', status='{self.status}')>"


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

    # Profile tracking - which profile this session was created under
    profile_id = Column(Integer, nullable=True, index=True)
    profile_name = Column(String(255), nullable=True)  # Cached for display in history

    # Genie conversation tracking (persists across profile switches)
    genie_conversation_id = Column(String(255), nullable=True)

    # MLflow experiment tracking (per-session experiment for tracing)
    experiment_id = Column(String(255), nullable=True)

    # Processing lock for concurrent request handling
    is_processing = Column(Boolean, default=False, nullable=False)
    processing_started_at = Column(DateTime, nullable=True)

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
    versions = relationship(
        "SlideDeckVersion",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SlideDeckVersion.version_number.desc()",
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

    # Async polling support - links messages to specific chat requests
    request_id = Column(String(64), nullable=True, index=True)

    # Relationship
    session = relationship("UserSession", back_populates="messages")

    def __repr__(self):
        return f"<SessionMessage(id={self.id}, role='{self.role}', session_id={self.session_id})>"


class SessionSlideDeck(Base):
    """Slide deck state for a session.

    Stores the current slide deck HTML and metadata for persistence.
    Verification results are stored separately in verification_map to survive
    deck regeneration when chat modifies slides.
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
    # Note: Verification is NOT stored here - it's in verification_map
    deck_json = Column(Text)  # JSON with slides array, css, external_scripts, scripts
    
    # Verification results keyed by content hash (survives deck regeneration)
    # JSON format: {"content_hash": {"score": 95, "rating": "excellent", ...}}
    verification_map = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship
    session = relationship("UserSession", back_populates="slide_deck")

    def __repr__(self):
        return f"<SessionSlideDeck(session_id={self.session_id}, title='{self.title}')>"


class SlideDeckVersion(Base):
    """Save point for slide deck versioning.

    Stores complete snapshots of the slide deck at specific points in time,
    allowing users to preview and rollback to previous states.
    Limited to 40 versions per session (oldest deleted when exceeded).
    """

    __tablename__ = "slide_deck_versions"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Version tracking
    version_number = Column(Integer, nullable=False)
    description = Column(String(255), nullable=False)  # Auto-generated description
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Complete deck snapshot (JSON format)
    deck_json = Column(Text, nullable=False)

    # Verification results at time of snapshot
    verification_map_json = Column(Text, nullable=True)

    # Chat history snapshot (JSON array of messages up to this point)
    chat_history_json = Column(Text, nullable=True)

    # Relationship
    session = relationship("UserSession", back_populates="versions")

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_deck_versions_session_version", "session_id", "version_number"),
        Index("ix_deck_versions_session_created", "session_id", "created_at"),
    )

    def __repr__(self):
        return f"<SlideDeckVersion(session_id={self.session_id}, version={self.version_number}, desc='{self.description}')>"


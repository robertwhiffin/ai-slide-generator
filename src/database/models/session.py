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
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import backref, relationship

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
    session = relationship("UserSession", back_populates="chat_requests")

    __table_args__ = (Index("ix_chat_requests_session_id", "session_id"),)

    def __repr__(self):
        return f"<ChatRequest(request_id='{self.request_id}', status='{self.status}')>"


class ExportJob(Base):
    """Tracks async PPTX export jobs for polling.

    Database-backed job tracking replaces the previous in-memory dict,
    enabling multi-worker deployments where POST (enqueue) and GET (poll)
    requests may hit different processes.
    """

    __tablename__ = "export_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(String(128), nullable=False)  # string session_id, not FK
    status = Column(String(20), default="pending")  # pending/running/completed/error
    progress = Column(Integer, default=0)
    total_slides = Column(Integer, default=0)
    title = Column(String(512), nullable=True)
    output_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    status_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ExportJob(job_id='{self.job_id}', status='{self.status}')>"


class UserSession(Base):
    """User session for tracking conversation state.

    Each session represents an independent conversation context with its own
    chat history and slide deck state.

    Contributor sessions (parent_session_id != NULL) share the parent's slide
    deck but have their own private chat history. This enables multiple users
    to collaboratively edit a presentation via chat while keeping each user's
    conversation private.
    """

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)  # Legacy — kept for backward compat
    created_by = Column(String(255), nullable=True, index=True)  # Username of session creator

    # Workspace-wide deck sharing (root sessions only). NULL = private.
    # CAN_VIEW or CAN_EDIT — CAN_MANAGE is not valid for workspace share.
    global_permission = Column(String(20), nullable=True)

    # Contributor session support: links to the owner's session whose slide
    # deck this contributor reads/writes. NULL = owner (root) session.
    parent_session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Session metadata
    title = Column(String(255))  # Optional session title/name
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Genie conversation tracking (persists across profile switches)
    genie_conversation_id = Column(String(255), nullable=True)

    # MLflow experiment tracking (per-session experiment for tracing)
    experiment_id = Column(String(255), nullable=True)

    # Google Slides export tracking (reuse existing presentation on re-export)
    google_slides_presentation_id = Column(String(255), nullable=True)
    google_slides_url = Column(String(512), nullable=True)

    # Agent configuration override (tools, style, prompts) — stored as JSON blob
    agent_config = Column(JSON, nullable=True, default=None)

    # Processing lock for concurrent request handling
    is_processing = Column(Boolean, default=False, nullable=False)
    processing_started_at = Column(DateTime, nullable=True)

    # Relationships
    messages = relationship(
        "SessionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SessionMessage.created_at",
    )
    slide_deck = relationship(
        "SessionSlideDeck",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    versions = relationship(
        "SlideDeckVersion",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SlideDeckVersion.version_number.desc()",
    )
    chat_requests = relationship(
        "ChatRequest",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    deck_contributors = relationship(
        "DeckContributor",
        back_populates="user_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    parent_session = relationship(
        "UserSession",
        remote_side=[id],
        foreign_keys=[parent_session_id],
        backref=backref(
            "contributor_sessions",
            cascade="all, delete-orphan",
            passive_deletes=True,
        ),
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_user_sessions_created_by_last_activity", "created_by", "last_activity"),
        Index("ix_user_sessions_parent_created_by", "parent_session_id", "created_by"),
    )

    @property
    def is_contributor_session(self) -> bool:
        return self.parent_session_id is not None

    def __repr__(self):
        suffix = f", parent={self.parent_session_id}" if self.parent_session_id else ""
        return f"<UserSession(session_id='{self.session_id}', created_by='{self.created_by}'{suffix})>"


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

    For shared presentations, multiple contributor sessions read/write this
    same deck. The locked_by/locked_at fields provide deck-level locking to
    prevent concurrent modifications, and the version counter enables
    optimistic locking for direct (non-chat) edits.
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

    # Deck spec (full architecture spec, architect-authored)
    # Persisted per-session; inferred from existing HTML once, then persisted (spec §4.3).
    # Snapshot also stored in SlideDeckVersion (spec §4.4).
    deck_spec_json = Column(Text, nullable=True)

    # Deck-level CSS (written by the foreman — single writer for the deck)
    # Builders write only body HTML to their slides; deck CSS is centralized here.
    css = Column(Text, nullable=True)

    # Deck-level external script URLs (Chart.js CDN etc.), JSON array.
    # REQUIRED, not optional: the export chain reads `external_scripts` off the deck
    # dict (`src/api/routes/export.py:52`), and `SlideDeck._ensure_default_external_scripts`
    # (`src/domain/slide_deck.py:74-77`) injects the Chart.js CDN into every deck. If the
    # row path returns [] instead, EVERY export silently loses Chart.js and all charts
    # render blank — the PRD §3 no-regression gate, failing invisibly.
    external_scripts_json = Column(Text, nullable=True)

    # Deck-level editing lock for chat-based edits (long-running operations).
    # When an agent is modifying slides, locked_by holds the username and
    # locked_at records when the lock was acquired. Auto-expires after timeout.
    locked_by = Column(String(255), nullable=True)
    locked_at = Column(DateTime, nullable=True)

    # Optimistic locking counter for direct (non-chat) edits.
    # Incremented on every write; clients send the version they read so the
    # server can detect and reject stale writes (HTTP 409).
    version = Column(Integer, default=0, nullable=False)

    # Authorship
    modified_by = Column(String(255), nullable=True)

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

    # Deck spec snapshot at save-point time (must stay in sync with deck_json for restore)
    deck_spec_json = Column(Text, nullable=True)

    # Relationship
    session = relationship("UserSession", back_populates="versions")

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_deck_versions_session_version", "session_id", "version_number"),
        Index("ix_deck_versions_session_created", "session_id", "created_at"),
    )

    def __repr__(self):
        return f"<SlideDeckVersion(session_id={self.session_id}, version={self.version_number}, desc='{self.description}')>"


class SessionSlide(Base):
    """One row per slide in a session's deck.

    Keyed by (session_id, position). Carries the Slide domain model fields
    plus verification_record (per-row, keyed by content_hash) and deck_spec_slide
    (the slide's fragment of the architecture spec).

    Verification moved here from SessionSlideDeck.verification_map to allow
    parallel per-slide writes without lost-update races (spec §5.2.4).
    """

    __tablename__ = "session_slides"

    # Composite primary key: (session_id, position)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    position = Column(Integer, primary_key=True, nullable=False)

    # Unique row ID (for external references if needed)
    id = Column(String(64), unique=True, nullable=True)

    # Slide content (from Slide domain model)
    html = Column(Text, nullable=False)  # Body HTML only, not full document
    slide_id = Column(String(255), nullable=True)  # Optional UUID
    scripts = Column(Text, nullable=True)  # Chart.js, etc. per-slide code

    # Authorship and timestamps
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)
    modified_by = Column(String(255), nullable=True)
    modified_at = Column(DateTime, nullable=True)

    # Per-slide verification record (keyed by content_hash if present)
    # JSON format: {"content_hash": {findings from reviewer}}
    verification_record = Column(Text, nullable=True)

    # This slide's portion of the deck spec (architect-authored, foreman-distributed)
    # JSON format: {position, purpose, content brief, assumes, hands_off, data_references}
    deck_spec_slide = Column(Text, nullable=True)

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_session_slides_session_position", "session_id", "position"),
        Index("ix_session_slides_id", "id"),
    )

    def __repr__(self):
        return f"<SessionSlide(session_id={self.session_id}, position={self.position})>"


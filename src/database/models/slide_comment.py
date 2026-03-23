"""Slide comment model for per-slide threaded discussions.

Comments are stored against the deck-owner session so all contributors
(viewers, editors, managers) of a shared presentation see the same
comment thread.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import backref, relationship

from src.core.database import Base


class SlideComment(Base):
    """A comment on a specific slide within a presentation.

    Threading is supported via ``parent_comment_id`` (self-referential FK).
    Resolution workflow is supported via ``resolved`` / ``resolved_by``.
    """

    __tablename__ = "slide_comments"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("user_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    slide_id = Column(String(64), nullable=False)
    user_name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)

    mentions = Column(JSON, nullable=True)

    resolved = Column(Boolean, default=False, nullable=False)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    parent_comment_id = Column(
        Integer,
        ForeignKey("slide_comments.id", ondelete="CASCADE"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    session = relationship("UserSession")
    replies = relationship(
        "SlideComment",
        backref=backref("parent", remote_side="SlideComment.id"),
        foreign_keys=[parent_comment_id],
        cascade="all, delete-orphan",
        single_parent=True,
    )

    __table_args__ = (
        Index("ix_slide_comments_session_slide", "session_id", "slide_id"),
        Index("ix_slide_comments_parent", "parent_comment_id"),
    )

    def __repr__(self):
        return (
            f"<SlideComment(id={self.id}, slide_id='{self.slide_id}', "
            f"user='{self.user_name}', resolved={self.resolved})>"
        )

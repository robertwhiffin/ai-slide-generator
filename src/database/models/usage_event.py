"""Durable usage-event log for admin analytics.

One row per event. Unlike ``user_sessions`` this table is never pruned;
it is the source of truth for login/deck activity history.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String

from src.core.database import Base

EVENT_LOGIN = "login"
EVENT_DECK_CREATED = "deck_created"
EVENT_DECK_RETRIEVED = "deck_retrieved"


class UsageEvent(Base):
    """A single usage event (login, deck created, deck retrieved)."""

    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    event_type = Column(String(30), nullable=False)
    # Intentionally NOT a ForeignKey: events must survive session deletion.
    session_id = Column(Integer, nullable=True)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_usage_events_type_ts", "event_type", "ts"),
        Index("ix_usage_events_username_ts", "username", "ts"),
    )

    def __repr__(self):
        return (
            f"<UsageEvent(id={self.id}, username='{self.username}', "
            f"event_type='{self.event_type}', ts={self.ts})>"
        )

"""Pre-turn snapshot of a deck, taken when a graph generation starts.

One row per generation request (``request_id`` is unique). It records enough of
the owner's deck and session state to restore it if the user stops the turn.
``state`` moves ``active`` -> ``sealed`` (turn finished, snapshot no longer
restorable) or ``active`` -> ``restore_failed``.

Created on existing databases by
``src.core.database._migrate_generation_snapshots``.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from src.core.database import Base


class GenerationSnapshot(Base):
    """Deck and session state captured before a generation turn mutates it."""

    __tablename__ = "generation_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), unique=True, nullable=False)
    # user_sessions.id of the requesting session, and of the deck's owning session.
    actor_session_pk = Column(Integer, nullable=False)
    owner_session_pk = Column(Integer, nullable=False)
    deck_present = Column(Boolean, nullable=False)
    deck_columns_json = Column(Text, nullable=True)
    slide_rows_json = Column(Text, nullable=False, default="[]")
    session_fields_json = Column(Text, nullable=False)
    checkpoint_id = Column(String(255), nullable=True)
    # Max shared_deck_mutation_event.id for the deck at snapshot time.
    mutation_watermark = Column(Integer, nullable=True)
    # "active" | "sealed" | "restore_failed"
    state = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"<GenerationSnapshot(request_id='{self.request_id}', state='{self.state}')>"
        )

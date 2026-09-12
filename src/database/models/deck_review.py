"""DeckReview ORM model — content-addressed deck-level review storage.

Deck reviews are keyed by ``(deck_id, deck_digest)`` — content-addressed, not
versioned. This eliminates three bookkeeping problems:

1. **Restore needs no handling.** There is no "current" row to go stale.
   When a user restores to an earlier save point, the digest of the restored
   content matches the row that already exists, and the verdict is immediately
   available without re-running the review.

2. **The save-point cap cannot break it.** ``VERSION_LIMIT = 40`` prunes the
   oldest ``SlideDeckVersion``; anything FK'd to ``slide_deck_versions`` would
   orphan or cascade away the very review history this table exists to keep.
   This table FKs ``session_slide_decks`` only — never ``slide_deck_versions``.

3. **A reorder correctly invalidates a deck review.** A deck review judges
   the narrative arc; a reorder changes the arc. This is the OPPOSITE of the
   per-slide rule — where a verdict travels with its slide across position
   changes, because it is keyed by content hash (position-independent). Both
   are correct: they differ because their grain differs. A reader who knows
   only the per-slide rule will read this as a bug; it is not.

The digest lives in the unique key ``(deck_id, deck_digest)`` and is NOT
denormalised onto ``session_slide_decks``. The row is immutable; the store
function computes the digest at write time and stores it once.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from src.core.database import Base


class DeckReview(Base):
    """Content-addressed store of a deck-level review verdict.

    Unique on ``(deck_id, deck_digest)``. Re-saving the same digest updates
    the existing row rather than inserting a duplicate.
    """

    __tablename__ = "deck_reviews"

    id = Column(Integer, primary_key=True)
    deck_id = Column(
        Integer,
        ForeignKey("session_slide_decks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 64 chars — generous headroom above the 16-char digest returned by
    # compute_deck_digest, in case the algorithm is ever extended.
    deck_digest = Column(String(64), nullable=False)
    # Serialised list[Finding] as JSON.  Each Finding carries slide_index captured
    # at review time — never recomputed from current position (see B2.2b and the
    # module docstring of src/services/deck_review_store.py).
    findings_json = Column(Text, nullable=False, default="[]")
    author = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    deck = relationship("SessionSlideDeck")

    __table_args__ = (
        UniqueConstraint("deck_id", "deck_digest", name="uq_deck_reviews_deck_digest"),
    )

    def __repr__(self) -> str:
        return (
            f"<DeckReview(id={self.id}, deck_id={self.deck_id}, "
            f"digest='{self.deck_digest[:8]}...')>"
        )

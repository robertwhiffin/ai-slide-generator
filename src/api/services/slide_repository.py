"""Repository for slide CRUD operations.

This module provides SlideWriter, the critical write API for PR3's LangGraph graph.
Builders and reviewers write slides here; the foreman reads positions to manage
the reorder buffer and deck-wide state.

Field mapping alignment:
- session_id column: Integer FK to user_sessions.id (deck_owner.id), NOT the string key.
- id column: fresh uuid4 per row (matching dual-write and backfill; slide_id uniqueness
  is not guaranteed globally, so reusing it would violate the UNIQUE constraint).
- timestamps: naive UTC (datetime.utcnow()), consistent with save_slide_deck and backfill.
- scripts: defaults to "" (same as backfill's `scripts = slide_dict.get("scripts") or ""`).
- verification_record: JSON string on disk, parsed to dict in return values.
- deck_spec_slide: JSON string on disk, parsed to dict in return values.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_

from src.api.services.session_manager import SessionManager, get_session_manager
from src.core.database import get_db_session
from src.database.models.session import SessionSlide
from src.utils.slide_hash import compute_slide_hash

# Sentinel prefix used by commit_placeholder so callers can distinguish
# error rows from real slides without parsing the verification_record.
_PLACEHOLDER_CLASS = "slide-placeholder-error"


class SlideWriter:
    """Writes and reads individual slide rows for the PR3 LangGraph graph.

    This is the critical API for PR3's parallel builders/reviewers.  Each reviewer
    calls write_slide() after review completes; the foreman reads positions via
    list_slides_in_position_order() to release them in order (reorder buffer, §6.2).

    The no-arg constructor form is REQUIRED, not a convenience: PR3's graph calls
    SlideWriter() from inside builder/reviewer nodes which are pure functions of
    graph state and carry no SessionManager.  Threading one through graph state
    would put a non-serialisable object into the checkpointer.
    """

    def __init__(self, session_manager: Optional[SessionManager] = None) -> None:
        self.session_manager = session_manager or get_session_manager()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_slide(
        self,
        session_id: str,
        position: int,
        html: str,
        scripts: str = "",
        verification_record: Optional[Dict[str, Any]] = None,
        deck_spec_slide: Optional[Dict[str, Any]] = None,
        modified_by: Optional[str] = None,
    ) -> None:
        """Commit a slide row to the database.

        Atomically writes (or updates) the session_slides row for this
        (deck_owner.id, position) pair.

        Partial-update semantics:
        - If verification_record is None, the existing value is PRESERVED.
        - If deck_spec_slide is None, the existing value is PRESERVED.
        Only pass a non-None value to overwrite.  This allows a reviewer to
        rewrite HTML without touching the verdict, or the foreman to attach a
        spec fragment without disturbing existing verification results.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        now = datetime.utcnow()

        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            existing = (
                db.query(SessionSlide)
                .filter(
                    and_(
                        SessionSlide.session_id == deck_owner.id,
                        SessionSlide.position == position,
                    )
                )
                .one_or_none()
            )

            if existing is not None:
                existing.html = html
                existing.scripts = scripts
                existing.modified_by = modified_by
                existing.modified_at = now
                if verification_record is not None:
                    existing.verification_record = json.dumps(verification_record)
                if deck_spec_slide is not None:
                    existing.deck_spec_slide = json.dumps(deck_spec_slide)
            else:
                row = SessionSlide(
                    session_id=deck_owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    html=html,
                    scripts=scripts,
                    created_by=modified_by,
                    created_at=now,
                    modified_by=modified_by,
                    modified_at=now,
                    verification_record=(
                        json.dumps(verification_record)
                        if verification_record is not None
                        else None
                    ),
                    deck_spec_slide=(
                        json.dumps(deck_spec_slide)
                        if deck_spec_slide is not None
                        else None
                    ),
                )
                db.add(row)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_slide(
        self,
        session_id: str,
        position: int,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a single slide row as a dict.

        Returns None if the row is absent.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            row = (
                db.query(SessionSlide)
                .filter(
                    and_(
                        SessionSlide.session_id == deck_owner.id,
                        SessionSlide.position == position,
                    )
                )
                .one_or_none()
            )

            if row is None:
                return None

            return _row_to_dict(row)

    def list_slides_in_position_order(
        self,
        session_id: str,
        from_position: int = 0,
    ) -> List[Dict[str, Any]]:
        """List all slides at from_position and beyond, in ascending position order.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            rows = (
                db.query(SessionSlide)
                .filter(
                    and_(
                        SessionSlide.session_id == deck_owner.id,
                        SessionSlide.position >= from_position,
                    )
                )
                .order_by(SessionSlide.position)
                .all()
            )

            return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_slide(
        self,
        session_id: str,
        position: int,
    ) -> None:
        """Delete the slide row at this position.  No-op if absent.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)

            row = (
                db.query(SessionSlide)
                .filter(
                    and_(
                        SessionSlide.session_id == deck_owner.id,
                        SessionSlide.position == position,
                    )
                )
                .one_or_none()
            )

            if row is not None:
                db.delete(row)

    # ------------------------------------------------------------------
    # Placeholder (failed position)
    # ------------------------------------------------------------------

    def commit_placeholder(
        self,
        session_id: str,
        position: int,
        error_message: str = "",
    ) -> None:
        """Write a terminal placeholder for a failed position.

        Invariants:
        1. list_slides_in_position_order() reports this position as committed
           (the row exists and is included in results).
        2. The row is distinguishable from a real slide: its html contains the
           class ``slide-placeholder-error`` and its verification_record carries
           ``{"error": True}``.

        This allows PR3's reorder-buffer release and all-committed trigger to
        proceed even when a builder crashes, and gives the UI enough info to
        show an error badge at the correct position.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        placeholder_html = (
            f'<div class="{_PLACEHOLDER_CLASS}" data-error="{error_message}">'
            f"<p>Slide generation failed.</p>"
            f"</div>"
        )
        self.write_slide(
            session_id=session_id,
            position=position,
            html=placeholder_html,
            scripts="",
            verification_record={"error": True, "message": error_message},
        )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _row_to_dict(row: SessionSlide) -> Dict[str, Any]:
    """Convert a SessionSlide ORM row to a plain dict.

    Always includes content_hash (computed from html).
    Parses verification_record and deck_spec_slide from JSON strings.
    """
    d: Dict[str, Any] = {
        "id": row.id,
        "session_id": row.session_id,
        "position": row.position,
        "html": row.html,
        "slide_id": row.slide_id,
        "scripts": row.scripts,
        "created_by": row.created_by,
        "created_at": (
            row.created_at.isoformat() + "Z" if row.created_at else None
        ),
        "modified_by": row.modified_by,
        "modified_at": (
            row.modified_at.isoformat() + "Z" if row.modified_at else None
        ),
        "content_hash": compute_slide_hash(row.html),
    }

    if row.verification_record:
        try:
            d["verification_record"] = json.loads(row.verification_record)
        except json.JSONDecodeError:
            d["verification_record"] = None
    else:
        d["verification_record"] = None

    if row.deck_spec_slide:
        try:
            d["deck_spec_slide"] = json.loads(row.deck_spec_slide)
        except json.JSONDecodeError:
            d["deck_spec_slide"] = None
    else:
        d["deck_spec_slide"] = None

    return d

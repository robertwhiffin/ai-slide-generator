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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_

from src.api.services.session_manager import (
    SessionManager,
    SlideRowsChangedError,
    _snapshot_row,  # noqa: F401 — re-exported; it moved to session_manager
    _splice_slide_rows,
    get_session_manager,
)
from src.core.database import get_db_session
from src.database.models.session import SessionSlide, SessionSlideDeck
from src.domain.deck_spec import DeckSpec
from src.services.shared_deck_attribution import (
    DeckMutationContext,
    record_shared_deck_mutation,
)
from src.utils.slide_hash import compute_slide_hash

# Sentinel prefix used by commit_placeholder so callers can distinguish
# error rows from real slides without parsing the verification_record.
_PLACEHOLDER_CLASS = "slide-placeholder-error"

# Key carried inside a placeholder's per-hash verdict.  A per-task review advised
# PR3 and the UI to key on ``verification_record["error"]``; after F6's hash-keying
# the flag lives one level down, inside the verdict for the placeholder HTML's own
# content hash.  ``is_placeholder_record`` is the supported way to detect it.
PLACEHOLDER_ERROR_KEY = "error"


def is_placeholder_record(verification_record: Optional[Dict[str, Any]]) -> bool:
    """Return True if *verification_record* describes a failed-position placeholder.

    Robust to the hash-keyed shape: a placeholder's record is
    ``{content_hash: {"error": True, "message": ...}}``, so the flag is checked on
    every verdict rather than on the record's top level.  Callers should prefer
    this helper over inspecting keys directly.

    Accepts the value from ``get_slide``/``list_slides_in_position_order``'s
    ``verification_record`` field, or a single resolved verdict from
    ``get_slide_deck``'s per-slide ``verification`` field.
    """
    if not isinstance(verification_record, dict):
        return False
    if verification_record.get(PLACEHOLDER_ERROR_KEY) is True:
        # A single resolved verdict (get_slide_deck's slide["verification"]).
        return True
    return any(
        isinstance(verdict, dict) and verdict.get(PLACEHOLDER_ERROR_KEY) is True
        for verdict in verification_record.values()
    )


def is_placeholder_verdict(verdict: Any) -> bool:
    """Return True if *verdict* (ONE per-hash verdict) is a placeholder's own verdict.

    Stricter than :func:`is_placeholder_record`: the verdict must carry the error
    flag AND nothing but the placeholder's two keys.  The LLM judge's error
    verdict also sets ``error`` but carries ``score``/``rating``/``explanation``
    and more, so it is a judged slide, not a placeholder.  A slot that also holds
    the graph reviewer's verdict is not a placeholder either.  Pass the verdict
    for the row's CURRENT content hash, never a whole record.
    """
    return (
        isinstance(verdict, dict)
        and is_placeholder_record(verdict)
        and set(verdict) <= {PLACEHOLDER_ERROR_KEY, "message"}
    )


#: The copy a failed position's placeholder shows (``commit_placeholder``).
FAILED_SLIDE_TEXT = "Slide generation failed."
#: The copy an inserted position shows until its builder lands (#314).
PENDING_SLIDE_TEXT = "New slide — not built yet."
#: The pending placeholder's ``data-error`` and verdict ``message``.
PENDING_SLIDE_MESSAGE = "Inserted slide not yet built"


def placeholder_slide(
    error_message: str = "", *, text: str = FAILED_SLIDE_TEXT
) -> Tuple[str, Dict[str, Any]]:
    """Build a placeholder slide: ``(html, verification_record)``.

    The record is ``{content_hash: {PLACEHOLDER_ERROR_KEY: True, "message":
    error_message}}``, keyed by the placeholder HTML's own hash (see
    ``commit_placeholder`` for why the hash-keying is load-bearing).  With the
    defaults this is exactly what ``commit_placeholder`` writes for a failed
    position; the pending placeholder passes ``PENDING_SLIDE_MESSAGE`` and
    ``text=PENDING_SLIDE_TEXT``.
    """
    html = (
        f'<div class="{_PLACEHOLDER_CLASS}" data-error="{error_message}">'
        f"<p>{text}</p>"
        f"</div>"
    )
    record = {
        compute_slide_hash(html): {
            PLACEHOLDER_ERROR_KEY: True,
            "message": error_message,
        }
    }
    return html, record


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
        slide_id: Optional[str] = None,
        mutation: Optional[DeckMutationContext] = None,
    ) -> None:
        """Commit a slide row to the database.

        Atomically writes (or updates) the session_slides row for this
        (deck_owner.id, position) pair, via the shared
        ``session_manager._upsert_slide_row`` helper in ``partial`` mode — so this
        writer cannot drift from the dual-write, the backfill and restore again.

        Partial-update semantics (UNCHANGED — PR3 relies on these):
        - If verification_record is None, the existing value is PRESERVED.
        - If deck_spec_slide is None, the existing value is PRESERVED.
        - If modified_by is None, the existing author is PRESERVED (final review
          F8: this used to null it unconditionally, so a reviewer rewriting HTML
          erased the author).
        - If slide_id is None on an UPDATE, the existing slide_id is PRESERVED;
          on an INSERT a fresh uuid4 is generated (F9: this writer used to leave
          slide_id NULL, but the frontend type declares it non-optional and uses
          it as the dnd/React key).

        ``verification_record`` MUST be shaped ``{content_hash: verdict}`` — the
        shape ``get_slide_deck``'s row branch reads back via
        ``.get(compute_slide_hash(row.html))``.  A record keyed any other way is
        invisible to the UI and pollutes ``get_verification_map``'s flat
        aggregate, which is persisted into save points.  It is merged into the
        row's existing record, not assigned, so hash-keyed history survives.

        Args:
            session_id: Session (contributor sessions resolve to the deck owner).
            position: 0-based slide position.
            html: Slide body HTML.
            scripts: Per-slide JavaScript.
            verification_record: ``{content_hash: verdict}``, or None to preserve.
            deck_spec_slide: Spec fragment, or None to preserve.
            modified_by: Author of this write, or None to preserve.
            slide_id: Stable per-slide id; defaults to a fresh uuid4 on insert.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        from src.api.services.session_manager import _upsert_slide_row

        now = datetime.utcnow()

        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)
            deck = deck_owner.slide_deck
            if mutation is not None and deck is None:
                deck = SessionSlideDeck(
                    session_id=deck_owner.id,
                    html_content="",
                    slide_count=0,
                    version=1,
                )
                db.add(deck)
                db.flush()

            slide_dict: Dict[str, Any] = {"html": html, "scripts": scripts}
            if modified_by is not None:
                # created_by is only consumed on INSERT; on UPDATE the helper's
                # partial mode leaves an existing created_by alone.
                slide_dict["created_by"] = modified_by
                slide_dict["modified_by"] = modified_by

            existing_row = (
                db.query(SessionSlide)
                .filter(
                    and_(
                        SessionSlide.session_id == deck_owner.id,
                        SessionSlide.position == position,
                    )
                )
                .one_or_none()
            )
            if slide_id is not None:
                slide_dict["slide_id"] = slide_id
            elif existing_row is None:
                # F9: never leave slide_id NULL on a row this writer creates.
                slide_dict["slide_id"] = str(uuid.uuid4())

            _upsert_slide_row(
                db,
                deck_owner.id,
                position,
                slide_dict,
                now_dt=now,
                verification=verification_record,
                deck_spec_slide=deck_spec_slide,
                partial=True,
            )
            db.flush()
            if mutation is not None:
                row = (
                    db.query(SessionSlide)
                    .filter(
                        and_(
                            SessionSlide.session_id == deck_owner.id,
                            SessionSlide.position == position,
                        )
                    )
                    .one()
                )
                record_shared_deck_mutation(
                    db,
                    requesting_session=session,
                    deck_owner=deck_owner,
                    deck=deck,
                    actor=mutation.actor,
                    operation=mutation.operation,
                    object_type=mutation.object_type,
                    object_id=mutation.object_id or row.slide_id,
                )

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
        mutation: Optional[DeckMutationContext] = None,
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
                object_id = row.slide_id
                db.delete(row)
                db.flush()
                if mutation is not None:
                    record_shared_deck_mutation(
                        db,
                        requesting_session=session,
                        deck_owner=deck_owner,
                        deck=deck_owner.slide_deck,
                        actor=mutation.actor,
                        operation=mutation.operation,
                        object_type=mutation.object_type,
                        object_id=mutation.object_id or object_id,
                    )

    # ------------------------------------------------------------------
    # Placeholder (failed position)
    # ------------------------------------------------------------------

    def commit_placeholder(
        self,
        session_id: str,
        position: int,
        error_message: str = "",
        mutation: Optional[DeckMutationContext] = None,
    ) -> None:
        """Write a terminal placeholder for a failed position.

        Invariants:
        1. list_slides_in_position_order() reports this position as committed
           (the row exists and is included in results).
        2. The row is distinguishable from a real slide: its html contains the
           class ``slide-placeholder-error``, and its verification_record carries
           ``{"error": True}`` **inside the verdict for the placeholder HTML's own
           content hash** — i.e. ``{content_hash: {"error": True, "message": ...}}``.

        The hash-keying is load-bearing (final review F6).  This record used to be
        written flat as ``{"error": True, "message": ...}``, which broke the
        ``{content_hash: verdict}`` contract twice over:
          * ``get_slide_deck`` resolves verification with
            ``.get(compute_slide_hash(row.html))``, so the marker was invisible to
            the UI — the badge could never render; and
          * ``get_verification_map`` merges every row's record into one flat
            ``{content_hash: verdict}`` dict which feeds ``create_version``, so the
            bare ``error``/``message`` keys were persisted into save-point
            ``verification_map_json`` permanently.

        Use ``is_placeholder_record()`` to detect a placeholder; it accepts both a
        whole record and a single resolved verdict, so it works on
        ``get_slide``/``list_slides_in_position_order``'s ``verification_record``
        and on ``get_slide_deck``'s per-slide ``verification``.

        This allows PR3's reorder-buffer release and all-committed trigger to
        proceed even when a builder crashes, and gives the UI enough info to
        show an error badge at the correct position.

        Raises:
            SessionNotFoundError: if session_id does not match any session.
        """
        placeholder_html, record = placeholder_slide(error_message)
        self.write_slide(
            session_id=session_id,
            position=position,
            html=placeholder_html,
            scripts="",
            verification_record=record,
            mutation=mutation,
        )

    # ------------------------------------------------------------------
    # Shift (the graph's slide insertion, #314)
    # ------------------------------------------------------------------

    def insert_pending_slides(
        self,
        session_id: str,
        insert_at: Sequence[int],
        *,
        deck_spec: str,
        expected_rows: Sequence[Tuple[Optional[str], str]],
        created_by: Optional[str],
        mutation: DeckMutationContext,
    ) -> List[str]:
        """Shift the deck's rows and open a pending placeholder at each inserted index.

        The graph's only shift, run at architect commit before any builder is
        dispatched.  Everything happens in ONE ``get_db_session()`` transaction:

        1. The rows are re-read, and ``[(slide_id, content_hash)]`` in position
           order must equal ``expected_rows`` (the rows the architect planned
           against).  A session without a deck row, rows that exist while
           ``expected_rows`` is empty, or any other mismatch raises
           :class:`SlideRowsChangedError`.
        2. Each old row is snapshotted to a plain dict (raw column values) and
           its :class:`SlideAttribution` taken, BEFORE any write: the upsert
           rewrites those ORM rows in place.
        3. A pending placeholder (``PENDING_SLIDE_TEXT``) is spliced in at each
           inserted index, with a fresh ``slide_id`` and explicit authorship
           (``created_by``) and timestamps.
        4. Every position is rewritten through ``_rewrite_slide_rows`` with the
           EXACT old-row map, never the attribution heuristic, and with
           ``now_dt=None``/``author_fallback=None``, so a moved row with a NULL
           author or timestamp stays NULL and no moved row gets a fresh
           ``modified_at``.  Steps 2-4 are ``session_manager._splice_slide_rows``,
           the one shift primitive, shared with ``SessionManager.insert_slide``.
        5. ``deck_spec_json`` is set to *deck_spec*, ``version`` is bumped (which
           invalidates every worker's deck cache) and ``last_activity`` touched.
           ``slide_count`` is NOT written: its single writer is the post-commit
           deck-level write.
        6. One ``insert_slide``/``deck`` mutation event is recorded.

        A row-less (spec-only) deck with ``expected_rows=[]`` gets steps 5 and 6
        only, and ``insert_at`` is checked against *deck_spec*'s slide count.

        Args:
            session_id: the requesting session (a contributor writes the owner's deck).
            insert_at: the NEW indices of the inserted slides, ascending and distinct.
            deck_spec: the canonical spec JSON of the deck after the insert.
            expected_rows: ``[(slide_id, content_hash)]`` the caller planned against.
            created_by: the author of the turn that opens the pending rows.
            mutation: provenance; its actor must be the requesting session and
                its operation ``insert_slide`` on object type ``deck``.

        Returns:
            The new slides' ``slide_id`` values in ``insert_at`` order (``[]`` for
            a row-less deck).

        Raises:
            ValueError: *insert_at* is empty, not ascending and distinct, negative,
                or out of range for the shifted deck; *deck_spec* is not a valid
                DeckSpec or its slide count is not ``len(rows) + len(insert_at)``;
                *mutation* is not an ``insert_slide``/``deck`` context; or the
                evidence write refuses the actor.
            SlideRowsChangedError: the committed rows are not *expected_rows*, or
                the session has no deck row.
            SessionNotFoundError: *session_id* does not match any session.

        Nothing is written on any raise.
        """
        insert_at = list(insert_at)
        if not insert_at:
            raise ValueError("insert_at must name at least one new index")
        if insert_at[0] < 0:
            raise ValueError(f"insert_at must be non-negative: {insert_at}")
        if any(b <= a for a, b in zip(insert_at, insert_at[1:])):
            raise ValueError(f"insert_at must be ascending and distinct: {insert_at}")
        spec = DeckSpec.from_json(deck_spec)
        if spec is None:
            raise ValueError("deck_spec is not a valid DeckSpec")
        if mutation.operation != "insert_slide" or mutation.object_type != "deck":
            raise ValueError(
                "insert_pending_slides records an insert_slide/deck mutation, not "
                f"{mutation.operation}/{mutation.object_type}"
            )
        expected = [(slide_id, content_hash) for slide_id, content_hash in expected_rows]
        spec_count = len(spec.slides)

        with get_db_session() as db:
            session = self.session_manager._get_session_or_raise(db, session_id)
            deck_owner = self.session_manager._get_deck_owner_session(db, session)
            deck = deck_owner.slide_deck
            if deck is None:
                # The caller's prior spec came from this row; its absence means
                # the deck changed under the planner.
                raise SlideRowsChangedError(
                    f"session {session_id} has no deck row to insert into"
                )

            # 1. The rows the caller planned against, or nothing is written.
            old_rows = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == deck_owner.id)
                .order_by(SessionSlide.position)
                .all()
            )
            committed = [
                (row.slide_id, compute_slide_hash(row.html or "")) for row in old_rows
            ]
            if committed != expected:
                raise SlideRowsChangedError(
                    f"the committed rows of session {session_id} are not the rows "
                    f"planned against ({len(committed)} committed, {len(expected)} "
                    "expected)"
                )
            if insert_at[-1] >= spec_count:
                raise ValueError(
                    f"insert_at {insert_at} is beyond the spec's {spec_count} slides"
                )
            new_count = len(old_rows) + len(insert_at)
            if old_rows and spec_count != new_count:
                raise ValueError(
                    f"deck_spec has {spec_count} slides, but {len(old_rows)} rows plus "
                    f"{len(insert_at)} inserted make {new_count}"
                )

            new_ids: List[str] = []
            now = datetime.utcnow()
            if old_rows:
                # 2-4. A pending placeholder at each inserted index, spliced in
                #      through THE shift (session_manager._splice_slide_rows):
                #      snapshots and attributions before any write, then the
                #      whole-deck rewrite with the exact old-row map.
                pending_html, pending_record = placeholder_slide(
                    PENDING_SLIDE_MESSAGE, text=PENDING_SLIDE_TEXT
                )
                new_slides: Dict[int, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
                for new_index in insert_at:
                    slide_id = str(uuid.uuid4())
                    new_ids.append(slide_id)
                    new_slides[new_index] = (
                        {
                            "html": pending_html,
                            "scripts": "",
                            "slide_id": slide_id,
                            "created_by": created_by,
                            "created_at": now,
                            "modified_by": created_by,
                            "modified_at": now,
                        },
                        {
                            content_hash: dict(verdict)
                            for content_hash, verdict in pending_record.items()
                        },
                    )
                _splice_slide_rows(db, deck_owner.id, old_rows, new_slides)

            # 5. Deck columns, in the same transaction as the rows.
            deck.deck_spec_json = deck_spec
            deck.version = (deck.version or 0) + 1
            session.last_activity = now
            if session.id != deck_owner.id:
                deck_owner.last_activity = now

            # 6. Evidence; a refusal here rolls the whole shift back.
            db.flush()
            record_shared_deck_mutation(
                db,
                requesting_session=session,
                deck_owner=deck_owner,
                deck=deck,
                actor=mutation.actor,
                operation="insert_slide",
                object_type="deck",
                object_id=mutation.object_id,
            )
            return new_ids


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

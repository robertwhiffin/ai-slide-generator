"""Row-per-slide backfill: migrate legacy ``deck_json`` blobs into ``session_slides`` rows.

Lives under ``src/`` rather than ``scripts/`` because the app calls
``backfill_unmigrated_decks`` from its FastAPI lifespan on every boot, and the
Databricks Apps wheel ships only ``src/`` (see
``packages/databricks-tellr-app/setup.py``, which copytrees ``src`` and the
frontend/sidecars but NOT ``scripts``).  Importing this from ``scripts`` would
raise ``ModuleNotFoundError`` at startup in production.

``scripts/backfill_session_slides.py`` remains the operator CLI and imports from
here, so there is exactly ONE implementation of the row mapping.

Idempotent: a row already present at ``(session_id, position)`` is skipped.
Also lifts deck-level presentation fields (``css``, ``external_scripts``) out of
``deck_json`` into their dedicated columns — the row read path reads them from
columns, so without the lift every existing deck would silently lose its
stylesheet and the Chart.js CDN on the first read after backfill.  Orphan rows
(``position >= slide count``) are pruned in the same transaction as the inserts.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.api.services.session_manager import _prune_slide_rows_beyond, _upsert_slide_row
from src.database.models.session import SessionSlide, SessionSlideDeck
from src.utils.slide_hash import compute_slide_hash

logger = logging.getLogger(__name__)


def backfill_session(
    db: Session,
    session_id: int,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Backfill one session's session_slides rows from its deck_json blob.

    Args:
        db: Live SQLAlchemy session (the caller commits / rolls back).
        session_id: UserSession.id (Integer PK) to backfill.  This is NOT the
            string business key — callers that accept a string must resolve it
            first via UserSession.session_id.
        dry_run: When True, counts what would change but mutates NOTHING.
            No ORM adds, no column assignments, no deletes.

    Returns:
        dict with keys:
            session_id            – echoes the argument
            slides_inserted       – rows added (or would be added in dry-run)
            slides_skipped        – rows that already existed
            verification_migrated – slides whose verification_record was written
            css_backfilled        – 1 if deck.css was (or would be) set, else 0
            external_scripts_backfilled – 1 if external_scripts_json was (or would be) set
            head_meta_backfilled  – 1 if head_meta_json was (or would be) set
            orphans_pruned        – rows deleted (or that would be deleted) above slide count
    """
    result: Dict[str, Any] = {
        "session_id": session_id,
        "slides_inserted": 0,
        "slides_skipped": 0,
        "verification_migrated": 0,
        "css_backfilled": 0,
        "external_scripts_backfilled": 0,
        "head_meta_backfilled": 0,
        "orphans_pruned": 0,
    }

    # Load the deck for this session.
    deck = (
        db.query(SessionSlideDeck)
        .filter(SessionSlideDeck.session_id == session_id)
        .one_or_none()
    )
    if deck is None:
        logger.info("Session %d has no slide deck — skipping", session_id)
        return result

    if not deck.deck_json:
        logger.info("Session %d deck_json is empty — skipping", session_id)
        return result

    try:
        deck_dict = json.loads(deck.deck_json)
    except json.JSONDecodeError as exc:
        logger.error("Session %d deck_json is invalid JSON: %s", session_id, exc)
        return result

    # Parse verification_map (keyed by content_hash → findings dict).
    verification_map: Dict[str, Any] = {}
    if deck.verification_map:
        try:
            verification_map = json.loads(deck.verification_map)
        except json.JSONDecodeError:
            logger.warning("Session %d verification_map is invalid JSON — skipping", session_id)

    slides = deck_dict.get("slides") or []

    # -------------------------------------------------------------------------
    # Per-slide inserts
    # -------------------------------------------------------------------------
    for position, slide_dict in enumerate(slides):
        existing = (
            db.query(SessionSlide)
            .filter(
                and_(
                    SessionSlide.session_id == session_id,
                    SessionSlide.position == position,
                )
            )
            .one_or_none()
        )
        if existing is not None:
            logger.debug(
                "Session %d position %d already has a row — skipping",
                session_id,
                position,
            )
            result["slides_skipped"] += 1
            continue

        html = slide_dict.get("html") or ""

        # Migrate this slide's verification verdict from the deck-wide blob.
        content_hash = compute_slide_hash(html)
        verification: Optional[Dict[str, Any]] = None
        if content_hash in verification_map:
            verification = {content_hash: verification_map[content_hash]}
            result["verification_migrated"] += 1

        if not dry_run:
            # Shared row writer (session_manager._upsert_slide_row) — one helper
            # owns the full field set for a session_slides row, so the backfill
            # cannot drift from the dual-write, restore or SlideWriter.  It also
            # gives this writer the tz normalisation (naive UTC) that used to live
            # here alone, and the fresh-uuid4 `id` decision:
            #
            #   `id` is String(64) UNIQUE globally across all sessions, and two
            #   sessions' deck_jsons may legitimately carry the same slide_id
            #   (duplicate-slide and restore flows), so reusing slide_id would
            #   violate the constraint on the second insert and abort the backfill
            #   mid-run.  slide_id is preserved in the slide_id column.
            #
            # author_fallback is deliberately omitted (None): the backfill has no
            # writer identity, so created_by/modified_by stay NULL when the slide
            # dict has none.  The live dual-write DOES pass a fallback.  This
            # divergence is intentional — do not "harmonise" it.
            _upsert_slide_row(
                db,
                session_id,
                position,
                slide_dict,
                now_dt=None,
                author_fallback=None,
                verification=verification,
            )

        result["slides_inserted"] += 1
        logger.info(
            "Session %d position %d: %s (html_len=%d, verification=%s)",
            session_id,
            position,
            "would insert" if dry_run else "inserted",
            len(html),
            bool(verification),
        )

    # -------------------------------------------------------------------------
    # Lift deck-level presentation fields into their new columns.
    #
    # CSS and external_scripts live INSIDE deck_json for all existing decks.
    # The row read path (Task 5 / get_slide_deck) reads them from the dedicated
    # columns, so without this lift the first read after backfill returns css=""
    # and external_scripts=[] — the stylesheet and Chart.js CDN vanish silently.
    # This is the PRD §3 no-regression gate on the historical-data side.
    # -------------------------------------------------------------------------
    new_css = deck_dict.get("css") or ""
    new_ext = json.dumps(deck_dict.get("external_scripts") or [])
    new_head_meta = json.dumps(deck_dict.get("head_meta") or {})

    if deck.css is None:
        result["css_backfilled"] += 1
        if not dry_run:
            deck.css = new_css

    if deck.external_scripts_json is None:
        result["external_scripts_backfilled"] += 1
        if not dry_run:
            deck.external_scripts_json = new_ext

    # F5: head_meta is the third deck-level presentation field.  Without this lift
    # the first row-path read after backfill returns the deck's head_meta from the
    # deck_json fallback only; once deck_json is eventually retired the custom
    # viewport would be lost.  Lift it into the column now.
    if deck.head_meta_json is None:
        result["head_meta_backfilled"] += 1
        if not dry_run:
            deck.head_meta_json = new_head_meta

    # -------------------------------------------------------------------------
    # Prune orphan rows (position >= slide count).
    #
    # A re-run after a deck shrank leaves stale higher-position rows.  The read
    # path prefers session_slides whenever ANY rows exist, so get_slide_deck()
    # would return MORE slides than the deck actually has — and PR3's
    # all-committed predicates would wait forever on phantom positions.
    # -------------------------------------------------------------------------
    if not dry_run:
        # Shared prune strategy — see session_manager._prune_slide_rows_beyond.
        result["orphans_pruned"] = _prune_slide_rows_beyond(
            db, session_id, len(slides)
        )
    else:
        orphan_count = (
            db.query(SessionSlide)
            .filter(
                and_(
                    SessionSlide.session_id == session_id,
                    SessionSlide.position >= len(slides),
                )
            )
            .count()
        )
        result["orphans_pruned"] = orphan_count

    if not dry_run:
        db.commit()

    return result


def backfill_unmigrated_decks(session_factory) -> int:
    """Backfill every deck that has NO session_slides rows yet. Returns count migrated.

    Called from the FastAPI lifespan alongside ``migrate_profiles`` so an upgrade
    migrates historical decks by itself, instead of depending on an operator
    remembering to run this module by hand.  Leaving it manual meant every deploy
    sat in a split state: reads still worked (``get_slide_deck`` falls back to
    ``deck_json``), but a deck *edited* before the backfill acquired rows without
    its verdicts, and the idempotency guard then skipped it forever.  Running on
    startup closes that window for untouched decks.

    The guard is a per-deck NOT EXISTS anti-join.  Both indexes it needs already
    exist (``session_slides``' composite PK on ``(session_id, position)`` plus
    ``ix_session_slides_session_position``), so each existence check is an
    index-only probe that stops at the first row.  Once every deck is backfilled
    the query returns zero rows, making later boots a single cheap scan of a
    small table — far below the cost of the OAuth token fetch and pool setup that
    already happen at startup.

    NOTE ON SCOPE: this finds decks with no rows AT ALL.  A *partially*
    backfilled deck (some positions have rows) is deliberately left to the CLI —
    catching those needs per-position comparison and collides with the
    idempotency guard.  See the runbook's "decks edited between deploy and
    backfill" section.
    """
    db = session_factory()
    try:
        unmigrated = [
            row[0]
            for row in db.query(SessionSlideDeck.session_id)
            .filter(
                SessionSlideDeck.deck_json.isnot(None),
                ~db.query(SessionSlide)
                .filter(SessionSlide.session_id == SessionSlideDeck.session_id)
                .exists(),
            )
            .all()
        ]

        if not unmigrated:
            return 0

        logger.info(
            "Row-per-slide backfill: %d deck(s) have no session_slides rows; migrating",
            len(unmigrated),
        )

        migrated = 0
        failed: list[int] = []
        for session_pk in unmigrated:
            # One transaction per deck: a bad deck_json cannot abort the others,
            # and a re-run resumes cleanly because the guard re-evaluates.
            try:
                result = backfill_session(db, session_pk, dry_run=False)
                if result["slides_inserted"]:
                    migrated += 1
            except Exception:
                db.rollback()
                failed.append(session_pk)
                logger.exception(
                    "Row-per-slide backfill failed for session pk=%d; continuing",
                    session_pk,
                )

        if failed:
            # Deliberately not raised: a deck we cannot parse must not block app
            # startup, and its deck_json is still readable via the fallback path.
            logger.error(
                "Row-per-slide backfill: %d deck(s) failed and remain on deck_json: %s",
                len(failed),
                failed,
            )

        return migrated
    finally:
        db.close()

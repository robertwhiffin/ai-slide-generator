"""One-time backfill: migrate deck_json slides into session_slides rows.

Reads each SessionSlideDeck.deck_json, parses it into individual Slide dicts,
and INSERTs them as session_slides rows (with verification_record migrated from
the shared verification_map blob).

Idempotent: if a session_slides row already exists for a (session_id, position),
it is skipped (no re-insert). Dry-run mode prints summary; --yes applies.

Also lifts deck-level presentation fields (css, external_scripts) out of
deck_json into the new columns on SessionSlideDeck — the row read path reads
them from columns, so without this lift every existing deck would silently lose
its stylesheet and the Chart.js CDN on the first read after backfill.

Orphan rows (position >= slide count) are pruned in the same transaction as
inserts to prevent phantom positions misleading the PR3 commit predicates.

Usage:
    # Dry-run (default — safe to run repeatedly, no DB mutations):
    python -m scripts.backfill_session_slides

    # Apply to all sessions:
    python -m scripts.backfill_session_slides --yes

    # Apply to a single session (STRING business key, e.g. from URL or log):
    python -m scripts.backfill_session_slides --yes --session-id <string-key>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.api.services.session_manager import _prune_slide_rows_beyond, _upsert_slide_row
from src.core.database import get_db_session
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.utils.slide_hash import compute_slide_hash

logger = logging.getLogger(__name__)


def parse_args(argv: list | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Returns a namespace with:
        dry_run (bool): True by default; --yes sets it False.
        session_id (str | None): STRING business key from --session-id, or None.
    """
    p = argparse.ArgumentParser(
        description="Backfill session_slides rows from legacy deck_json blobs."
    )
    p.add_argument(
        "--session-id",
        default=None,
        dest="session_id",
        help=(
            "STRING business key of the session to backfill "
            "(UserSession.session_id, e.g. 'abc123' from the URL). "
            "Omit to backfill all sessions with a slide deck."
        ),
    )
    p.add_argument(
        "--yes",
        action="store_false",
        dest="dry_run",
        help="Apply changes to the database (omit for dry-run mode).",
    )
    p.set_defaults(dry_run=True)
    return p.parse_args(argv)


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


def main(argv: list | None = None) -> int:
    """Entry point for `python -m scripts.backfill_session_slides`."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    with get_db_session() as db:
        if args.session_id is not None:
            # Resolve STRING business key → Integer PK.
            user_session = (
                db.query(UserSession)
                .filter(UserSession.session_id == args.session_id)
                .one_or_none()
            )
            if user_session is None:
                print(
                    f"ERROR: No session found with session_id='{args.session_id}'",
                    file=sys.stderr,
                )
                return 1
            session_ids = [user_session.id]
        else:
            # All sessions that own a slide deck.  Query SessionSlideDeck
            # directly — every deck row has a session, no join needed.
            session_ids = [
                row[0]
                for row in db.query(SessionSlideDeck.session_id).all()
            ]

        if not session_ids:
            print("No sessions to backfill.")
            return 0

        mode = "dry-run" if args.dry_run else "APPLYING"
        print(
            f"Backfilling {len(session_ids)} session(s) [{mode}]",
            flush=True,
        )

        total_inserted = 0
        total_skipped = 0
        total_verification = 0
        total_orphans = 0
        failed_sessions: list[int] = []

        for sid in session_ids:
            try:
                result = backfill_session(db, sid, dry_run=args.dry_run)
                print(
                    f"  session pk={sid}: "
                    f"{result['slides_inserted']} inserted, "
                    f"{result['slides_skipped']} skipped, "
                    f"{result['verification_migrated']} verification migrated, "
                    f"css_backfilled={result['css_backfilled']}, "
                    f"ext_backfilled={result['external_scripts_backfilled']}, "
                    f"head_meta_backfilled={result['head_meta_backfilled']}, "
                    f"orphans_pruned={result['orphans_pruned']}",
                    flush=True,
                )
                total_inserted += result["slides_inserted"]
                total_skipped += result["slides_skipped"]
                total_verification += result["verification_migrated"]
                total_orphans += result["orphans_pruned"]
            except Exception as exc:  # noqa: BLE001
                logger.error("Session pk=%d FAILED: %s", sid, exc, exc_info=True)
                print(f"  session pk={sid}: FAILED — {exc}", flush=True)
                failed_sessions.append(sid)
                # Roll back the dirty transaction so the next session starts clean.
                db.rollback()

        print(
            f"\nSummary: {total_inserted} slides inserted, "
            f"{total_skipped} skipped, "
            f"{total_verification} verification records migrated, "
            f"{total_orphans} orphans pruned."
        )

        if failed_sessions:
            print(
                f"\nWARNING: {len(failed_sessions)} session(s) failed "
                f"(pks: {failed_sessions}). "
                "Check logs above. Successful sessions were committed.",
                file=sys.stderr,
            )

        if args.dry_run:
            print("\nDry-run complete. Re-run with --yes to apply.")

    return 1 if failed_sessions else 0


if __name__ == "__main__":
    raise SystemExit(main())

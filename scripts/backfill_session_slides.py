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
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

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
            orphans_pruned        – rows deleted (or that would be deleted) above slide count
    """
    result: Dict[str, Any] = {
        "session_id": session_id,
        "slides_inserted": 0,
        "slides_skipped": 0,
        "verification_migrated": 0,
        "css_backfilled": 0,
        "external_scripts_backfilled": 0,
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
        slide_id = slide_dict.get("slide_id")
        scripts = slide_dict.get("scripts") or ""
        created_by = slide_dict.get("created_by")
        modified_by = slide_dict.get("modified_by")

        created_at: Optional[datetime] = None
        created_at_str = slide_dict.get("created_at")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(
                    str(created_at_str).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        modified_at: Optional[datetime] = None
        modified_at_str = slide_dict.get("modified_at")
        if modified_at_str:
            try:
                modified_at = datetime.fromisoformat(
                    str(modified_at_str).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Compute content hash and migrate verification record if present.
        content_hash = compute_slide_hash(html)
        verification_record: Optional[str] = None
        if content_hash in verification_map:
            verification_record = json.dumps(
                {content_hash: verification_map[content_hash]}
            )
            result["verification_migrated"] += 1

        # id decision: generate a fresh UUID per row.
        # Reason: id is String(64) UNIQUE globally across all sessions.  Two
        # sessions' deck_jsons may carry the same slide_id (duplicate-slide and
        # restore flows make this possible), so reusing slide_id would cause a
        # unique-constraint violation on the second insert and abort the backfill
        # mid-run.  A fresh UUID guarantees uniqueness with zero schema changes.
        # slide_id is preserved in the slide_id column for informational use.
        row_id = str(uuid.uuid4())

        row = SessionSlide(
            session_id=session_id,
            position=position,
            id=row_id,
            html=html,
            slide_id=slide_id,
            scripts=scripts,
            created_by=created_by,
            created_at=created_at,
            modified_by=modified_by,
            modified_at=modified_at,
            verification_record=verification_record,
            deck_spec_slide=None,  # Populated by PR3 (architect agent).
        )

        if not dry_run:
            db.add(row)

        result["slides_inserted"] += 1
        logger.info(
            "Session %d position %d: %s (html_len=%d, verification=%s)",
            session_id,
            position,
            "would insert" if dry_run else "inserted",
            len(html),
            bool(verification_record),
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

    if deck.css is None:
        result["css_backfilled"] += 1
        if not dry_run:
            deck.css = new_css

    if deck.external_scripts_json is None:
        result["external_scripts_backfilled"] += 1
        if not dry_run:
            deck.external_scripts_json = new_ext

    # -------------------------------------------------------------------------
    # Prune orphan rows (position >= slide count).
    #
    # A re-run after a deck shrank leaves stale higher-position rows.  The read
    # path prefers session_slides whenever ANY rows exist, so get_slide_deck()
    # would return MORE slides than the deck actually has — and PR3's
    # all-committed predicates would wait forever on phantom positions.
    # -------------------------------------------------------------------------
    if not dry_run:
        deleted = (
            db.query(SessionSlide)
            .filter(
                and_(
                    SessionSlide.session_id == session_id,
                    SessionSlide.position >= len(slides),
                )
            )
            .delete(synchronize_session=False)
        )
        result["orphans_pruned"] = deleted
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

        for sid in session_ids:
            result = backfill_session(db, sid, dry_run=args.dry_run)
            print(
                f"  session pk={sid}: "
                f"{result['slides_inserted']} inserted, "
                f"{result['slides_skipped']} skipped, "
                f"{result['verification_migrated']} verification migrated, "
                f"css_backfilled={result['css_backfilled']}, "
                f"ext_backfilled={result['external_scripts_backfilled']}, "
                f"orphans_pruned={result['orphans_pruned']}",
                flush=True,
            )
            total_inserted += result["slides_inserted"]
            total_skipped += result["slides_skipped"]
            total_verification += result["verification_migrated"]

        print(
            f"\nSummary: {total_inserted} slides inserted, "
            f"{total_skipped} skipped, "
            f"{total_verification} verification records migrated."
        )

        if args.dry_run:
            print("\nDry-run complete. Re-run with --yes to apply.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

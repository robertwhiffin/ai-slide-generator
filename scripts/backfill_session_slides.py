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
import logging
import sys

from src.core.backfill_session_slides_startup import backfill_session
from src.core.database import get_db_session
from src.database.models.session import SessionSlideDeck, UserSession

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

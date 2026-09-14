"""D6a: restoring a save point discards the pending spec-review marker.

Three test intents (from the task brief):
  1. Restoring discards the marker — including one re-dirtied AFTER a sweeper
     claim, which clear_marker would KEEP.  Both directions pinned, one test each.
  2. Restoring does NOT call run_arc_review (absence assertion, paired with a
     positive assertion that the restore actually happened).
  3. The restored spec comes from the VERSION's snapshot, not the live deck's
     pre-restore value (both sides use DISTINCTIVE, different values).

All tests drive the real in-memory SQLite engine through SessionManager, the same
way test_spec_sync_marker.py does.  Both get_db_session references are patched to
the same engine so restore_version and discard_marker see a consistent DB.

Sabotage log (for each test, break the guard, confirm red for the right reason,
restore, confirm green, then break the guard you wrote):
  See the task-6-report.md alongside this file.
"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import patch

import pytest
from sqlalchemy import text

from src.api.services.session_manager import SessionManager
from src.database.models.session import (
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)
from src.services.spec_sync import clear_marker, discard_marker
from tests.unit.conftest import _make_fake_db, _make_in_memory_engine, _make_factory, _new_session_id

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"

_AUTHOR = "editor@example.com"
_REDIRTY_AUTHOR = "second-editor@example.com"

# Distinctive spec strings.  Their values are chosen so neither matches a
# column default, and neither matches the other — an assertion that expected
# VERSION_SPEC can only pass when VERSION_SPEC was actually written.
_VERSION_SPEC = '{"arc": "version-snapshot-distinctive-aaa111"}'
_LIVE_SPEC = '{"arc": "live-deck-pre-restore-distinctive-bbb222"}'


@contextlib.contextmanager
def _patched_both(factory):
    """Patch both get_db_session refs so restore_version and discard_marker share one DB."""
    fake = _make_fake_db(factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_MANAGER_DB, fake):
        yield


@contextlib.contextmanager
def _patched_spec_only(factory):
    """Patch only spec_sync's get_db_session — for calling spec_sync functions directly."""
    fake = _make_fake_db(factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_MANAGER_DB, fake):
        yield


def _owner_pk(factory, session_id: str) -> int:
    db = factory()
    try:
        return (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .one()
            .id
        )
    finally:
        db.close()


def _set_version_spec(factory, session_id: str, version_number: int, spec: Optional[str]) -> None:
    """Write deck_spec_json directly onto a SlideDeckVersion row."""
    db = factory()
    try:
        owner_id = _owner_pk(factory, session_id)
        db.execute(
            text(
                "UPDATE slide_deck_versions "
                "SET deck_spec_json = :spec "
                "WHERE session_id = :sid AND version_number = :vn"
            ),
            {"spec": spec, "sid": owner_id, "vn": version_number},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _set_live_deck_spec(factory, session_id: str, spec: Optional[str]) -> None:
    """Write deck_spec_json directly onto the live SessionSlideDeck row."""
    db = factory()
    try:
        owner_id = _owner_pk(factory, session_id)
        db.execute(
            text(
                "UPDATE session_slide_decks "
                "SET deck_spec_json = :spec "
                "WHERE session_id = :sid"
            ),
            {"spec": spec, "sid": owner_id},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _live_deck_spec(factory, session_id: str) -> Optional[str]:
    """Read deck_spec_json from the live SessionSlideDeck row."""
    db = factory()
    try:
        owner_id = _owner_pk(factory, session_id)
        row = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner_id)
            .one()
        )
        db.expunge(row)
        return row.deck_spec_json
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Test intent 1 — The distinction between discard_marker and clear_marker
# ---------------------------------------------------------------------------
#
# Brief C-1: "The distinction must be pinned by a test: a marker that was
# re-dirtied after a claim is DISCARDED by a restore and KEPT by a sweeper's
# clear.  One test each, and both must be able to fail."


class TestDiscardVsClearOnReDirtiedMarker:
    """C-1: the two functions behave differently on re-dirtied markers."""

    def test_restore_discards_a_redirtied_marker(self, deck_with_marker):
        """A marker re-dirtied after a sweeper claim is discarded by restore.

        Sabotage: replace the discard_marker call in restore_version with
        clear_marker — the re-dirty rule keeps the marker and this test goes red
        with: assert after.spec_dirty_at is None (spec_dirty_at is not None).
        """
        deck_with_marker.set_claim(age_seconds=100)
        deck_with_marker.set_marker(age_seconds=50, author=_REDIRTY_AUTHOR)

        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at is not None, "precondition: marker is set"
        assert row.spec_dirty_at > row.spec_dirty_claimed_at, (
            "precondition: marker is re-dirtied after the claim"
        )

        with _patched_both(deck_with_marker._factory):
            deck_with_marker._sm.restore_version(deck_with_marker.session_id, 1)

        after = deck_with_marker.deck_row()
        assert after.spec_dirty_at is None, (
            "restore must discard the marker unconditionally, even when re-dirtied "
            "after the sweeper's claim — the deck those edits described no longer exists"
        )
        assert after.spec_dirty_by is None
        assert after.spec_dirty_claimed_at is None

    def test_sweeper_clear_keeps_a_redirtied_marker(self, deck_with_marker):
        """A marker re-dirtied after a sweeper claim is KEPT by clear_marker.

        This is the paired direction: it pins that the two functions differ.
        Without this test, a discard_marker that just called clear_marker
        would leave test_restore_discards_a_redirtied_marker vacuously green
        when both functions happen to clear for the scenario being tested.

        Sabotage: remove the re-dirty rule from clear_marker — this test goes red
        with: assert after.spec_dirty_at == marker_at (spec_dirty_at is None).
        """
        deck_with_marker.set_claim(age_seconds=100)
        deck_with_marker.set_marker(age_seconds=50, author=_REDIRTY_AUTHOR)

        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at > row.spec_dirty_claimed_at, (
            "precondition: re-dirtied after the claim"
        )
        marker_at = row.spec_dirty_at

        with _patched_spec_only(deck_with_marker._factory):
            result = clear_marker(deck_with_marker.session_id)

        assert result is False, (
            "clear_marker must return False when the re-dirty rule keeps the marker"
        )
        after = deck_with_marker.deck_row()
        assert after.spec_dirty_at == marker_at, (
            "clear_marker must KEEP the re-dirty marker so the human's edit still "
            "gets its arc review — discarding it here is the stale-marker bug §B0"
        )
        assert after.spec_dirty_claimed_at is None, (
            "clear_marker releases the lease so the next tick can claim the window"
        )


# ---------------------------------------------------------------------------
# Test intent 2 — Restore does NOT call run_arc_review
# ---------------------------------------------------------------------------
#
# Brief C-2: "Monkeypatch it to raise and assert nothing calls it."
# Paired with an assertion that the restore actually happened so a fixture
# that silently does nothing cannot pass.


class TestRestoreDoesNotRunReview:
    """Absence assertion: restore completes without invoking run_arc_review."""

    def test_restore_never_calls_run_arc_review(self, deck_with_marker):
        """If restore called run_arc_review, the monkeypatch would raise.

        The paired assertion (the restore actually happened) ensures a silent
        no-op cannot satisfy both halves.

        Sabotage for the absence half: add a call to
            run_arc_review(session_id, "test")
        inside restore_version.  The monkeypatch raises RuntimeError and this
        test goes red with: RuntimeError: run_arc_review must not be called.

        Sabotage for the paired half: replace the assert on result["version_number"]
        with a vacuous assert True.  The test then passes even when restore_version
        returned None, hiding a broken restore path.
        """
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)

        with patch(
            "src.services.spec_sync.run_arc_review",
            side_effect=RuntimeError("run_arc_review must not be called during a restore"),
        ):
            with _patched_both(deck_with_marker._factory):
                result = deck_with_marker._sm.restore_version(
                    deck_with_marker.session_id, 1
                )

        # Paired assertion: the restore actually happened.
        # If this were assert True, a silent no-op restore would pass the test.
        assert result["version_number"] == 1, (
            "restore_version must return a result with the restored version number; "
            "a None or missing return means the restore path did not run at all"
        )
        assert "deck" in result, "result must contain the restored deck"

    def test_restore_clears_the_marker_not_reviews_it(self, deck_with_marker):
        """Pairing: the marker is gone after restore, proving the path ran.

        Without this, test_restore_never_calls_run_arc_review could pass while
        the marker was silently left behind (discard_marker never called).
        """
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)
        assert deck_with_marker.deck_row().spec_dirty_at is not None, (
            "precondition: a marker is present before restore"
        )

        with patch(
            "src.services.spec_sync.run_arc_review",
            side_effect=RuntimeError("run_arc_review must not be called during a restore"),
        ):
            with _patched_both(deck_with_marker._factory):
                deck_with_marker._sm.restore_version(
                    deck_with_marker.session_id, 1
                )

        assert deck_with_marker.deck_row().spec_dirty_at is None, (
            "the marker must be gone after restore — it was not discarded"
        )


# ---------------------------------------------------------------------------
# Test intent 3 — Restored spec comes from the VERSION's snapshot
# ---------------------------------------------------------------------------
#
# Brief C-3: "Assert the live deck's deck_spec_json after a restore equals the
# VERSION's snapshot, not what the live deck held before.  Use distinctive,
# different values for the two."


class TestRestoredSpecFromVersionSnapshot:
    """C-3: after restore, live deck spec = version snapshot (not pre-restore live)."""

    def test_live_spec_is_replaced_by_version_snapshot(self, deck_with_marker):
        """The live deck's spec is overwritten with the version's spec on restore.

        Both specs have DISTINCTIVE values so neither can accidentally match the
        other or match a column default (which would be NULL).

        Sabotage: remove the C9 line in restore_version:
            deck.deck_spec_json = getattr(version, "deck_spec_json", None)
        This test goes red with:
            AssertionError: live spec after restore is not the version snapshot.

        To verify the paired direction (values really ARE different), also check
        that the test fails if VERSION_SPEC == LIVE_SPEC — a tautological-default
        trap.  (The values are chosen to be visibly distinct above.)
        """
        # Write SNAPSHOT spec onto the version, LIVE spec onto the live deck.
        _set_version_spec(deck_with_marker._factory, deck_with_marker.session_id, 1, _VERSION_SPEC)
        _set_live_deck_spec(deck_with_marker._factory, deck_with_marker.session_id, _LIVE_SPEC)

        # Confirm the two values are genuinely different before restoring.
        pre_live = _live_deck_spec(deck_with_marker._factory, deck_with_marker.session_id)
        assert pre_live == _LIVE_SPEC, "precondition: live deck has the LIVE spec"
        assert pre_live != _VERSION_SPEC, "precondition: the two spec values differ"

        with _patched_both(deck_with_marker._factory):
            deck_with_marker._sm.restore_version(deck_with_marker.session_id, 1)

        post_live = _live_deck_spec(deck_with_marker._factory, deck_with_marker.session_id)

        assert post_live == _VERSION_SPEC, (
            f"live spec after restore is not the version snapshot.\n"
            f"  expected: {_VERSION_SPEC!r}\n"
            f"  got:      {post_live!r}\n"
            f"The C9 copy-back in restore_version was not applied."
        )

    def test_restored_spec_differs_from_pre_restore_live_spec(self, deck_with_marker):
        """Paired direction: the spec we assert DID change (not just stayed the same).

        Without this, a restore_version that writes nothing to deck_spec_json
        would pass test_live_spec_is_replaced_by_version_snapshot if the live
        deck happened to already hold VERSION_SPEC — a tautological-default trap.

        Sabotage: set _LIVE_SPEC = _VERSION_SPEC (make them equal).  Both tests
        go red: the precondition assert 'pre_live != _VERSION_SPEC' in the
        sibling test fires, and this one catches the identical-value trap.
        """
        _set_version_spec(deck_with_marker._factory, deck_with_marker.session_id, 1, _VERSION_SPEC)
        _set_live_deck_spec(deck_with_marker._factory, deck_with_marker.session_id, _LIVE_SPEC)

        with _patched_both(deck_with_marker._factory):
            deck_with_marker._sm.restore_version(deck_with_marker.session_id, 1)

        post_live = _live_deck_spec(deck_with_marker._factory, deck_with_marker.session_id)

        assert post_live != _LIVE_SPEC, (
            "live spec after restore still equals the PRE-RESTORE live spec; "
            "the restore either did not copy the spec at all, or the two spec "
            "values were not distinct (tautological-default trap)"
        )
        assert _LIVE_SPEC != _VERSION_SPEC, (
            "the test spec constants are equal — the equality/inequality assertions "
            "above cannot distinguish a restore from a no-op"
        )

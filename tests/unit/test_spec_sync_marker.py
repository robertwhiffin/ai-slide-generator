"""Marker semantics for src/services/spec_sync.py: mark_dirty and clear_marker.

Real sqlite throughout — every assertion reads the deck row back.  A mock cannot
see the defect class these functions exist to avoid (a marker written to the
CONTRIBUTOR's row, which no sweeper ever reads).

Driving the module: `mark_dirty` and `clear_marker` open their own DB session via
`get_db_session`, so a throwaway engine reaches them only by patching this
module's own reference, `src.services.spec_sync.get_db_session`.  Both functions
pass `db` explicitly into the two reused `SessionManager` helpers, so
`session_manager.get_db_session` needs no patch — it is patched anyway, following
tests/unit/test_deck_level_writer.py, so that an implementation which delegates to
a SessionManager method runs against THIS engine and fails on the behaviour rather
than on a real-database connection error that would hide it.

Fixtures are ws4b's (tests/unit/conftest.py), which were written for this task:
  deck_with_marker      — session + deck; set_marker(age, author), set_claim(age),
                          deck_row()
  contributor_session   — owner session + deck + contributor session whose
                          parent_session_id is the owner's integer PK
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta

import pytest
from unittest.mock import patch

from src.api.services.session_manager import SessionNotFoundError
from src.database.models.session import SessionSlideDeck, UserSession
from src.services.spec_sync import DEBOUNCE_SECONDS, clear_marker, mark_dirty
from tests.unit.conftest import _make_fake_db, _make_factory, _make_in_memory_engine

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"

_AUTHOR = "editor@example.com"
_LATER_AUTHOR = "second-editor@example.com"


@contextlib.contextmanager
def _patched(factory):
    """Point both get_db_session references at *factory*'s throwaway engine."""
    fake = _make_fake_db(factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_MANAGER_DB, fake):
        yield


def _owner_session_id_of(fixture) -> str:
    """The string session_id of the session that OWNS the contributor's deck.

    This is the id Task 5's `claim_due_marker` will return, so it is the id
    `clear_marker` must agree with.
    """
    db = fixture._factory()
    try:
        deck = db.query(SessionSlideDeck).one()
        return (
            db.query(UserSession).filter(UserSession.id == deck.session_id).one()
        ).session_id
    finally:
        db.close()


def _contributor_deck_row_count(fixture) -> int:
    """How many deck rows exist — a marker must not create a second one."""
    db = fixture._factory()
    try:
        return db.query(SessionSlideDeck).count()
    finally:
        db.close()


class TestTheDebounceConstant:
    def test_debounce_seconds_is_180(self):
        """The plan's value, verbatim. Task 5's claim_due_marker reads it."""
        assert DEBOUNCE_SECONDS == 180


class TestMarkDirtySetsTheMarker:
    def test_a_clean_deck_gets_a_timestamp_and_an_author(self, deck_with_marker):
        before = deck_with_marker.deck_row()
        assert before.spec_dirty_at is None, "fixture precondition: no marker"

        with _patched(deck_with_marker._factory):
            assert mark_dirty(deck_with_marker.session_id, _AUTHOR) is True

        after = deck_with_marker.deck_row()
        assert after.spec_dirty_at is not None
        assert after.spec_dirty_by == _AUTHOR
        assert after.spec_dirty_claimed_at is None, "marking must not claim"

    def test_the_author_is_a_distinctive_value_not_a_default(self, deck_with_marker):
        """The stored author is the one passed, not the column's default.

        `spec_dirty_by` defaults to NULL, so asserting "not None" would pass on a
        hardcoded string.  Two different authors are written in sequence and each
        is read back, so only actual delivery of the argument satisfies both.
        """
        with _patched(deck_with_marker._factory):
            mark_dirty(deck_with_marker.session_id, _AUTHOR)
            assert deck_with_marker.deck_row().spec_dirty_by == _AUTHOR

            mark_dirty(deck_with_marker.session_id, _LATER_AUTHOR)
            assert deck_with_marker.deck_row().spec_dirty_by == _LATER_AUTHOR

    def test_an_unauthenticated_author_is_stored_as_null(self, deck_with_marker):
        """author=None is accepted (local dev with no bound user), not a crash."""
        with _patched(deck_with_marker._factory):
            assert mark_dirty(deck_with_marker.session_id, None) is True
        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at is not None
        assert row.spec_dirty_by is None


class TestCoalescingWithinAWindow:
    """A burst of WYSIWYG edits must become ONE review, not a receding window."""

    def test_an_existing_unclaimed_marker_keeps_its_original_timestamp(
        self, deck_with_marker
    ):
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)
        original = deck_with_marker.deck_row().spec_dirty_at
        assert original is not None, "fixture precondition: a marker exists"

        with _patched(deck_with_marker._factory):
            assert mark_dirty(deck_with_marker.session_id, _LATER_AUTHOR) is True

        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at == original, (
            "spec_dirty_at moved: a burst of edits can now push the review window "
            "out forever and the arc review never runs"
        )

    def test_the_author_IS_refreshed_while_the_timestamp_is_not(
        self, deck_with_marker
    ):
        """Both halves of C-8 in one test: one column frozen, the other current."""
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)
        original = deck_with_marker.deck_row().spec_dirty_at

        with _patched(deck_with_marker._factory):
            mark_dirty(deck_with_marker.session_id, _LATER_AUTHOR)

        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at == original
        assert row.spec_dirty_by == _LATER_AUTHOR, (
            "the most recent human editor is the right attribution"
        )

    def test_repeated_marks_stay_pinned_to_the_first(self, deck_with_marker):
        """Ten edits in a row leave the window where the first edit put it."""
        with _patched(deck_with_marker._factory):
            mark_dirty(deck_with_marker.session_id, _AUTHOR)
            first = deck_with_marker.deck_row().spec_dirty_at
            for _ in range(9):
                mark_dirty(deck_with_marker.session_id, _AUTHOR)
        assert deck_with_marker.deck_row().spec_dirty_at == first

    def test_a_claimed_marker_starts_a_new_window(self, deck_with_marker):
        """An edit made after the sweeper claimed cannot be covered by that review.

        So it opens a NEW window — but must not steal the running worker's lease.
        """
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)
        deck_with_marker.set_claim(age_seconds=100)
        before = deck_with_marker.deck_row()
        original_at = before.spec_dirty_at
        original_claim = before.spec_dirty_claimed_at

        with _patched(deck_with_marker._factory):
            assert mark_dirty(deck_with_marker.session_id, _LATER_AUTHOR) is True

        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at > original_at, (
            "a claimed marker must open a new window, or this human's edit is "
            "silently folded into a review that started before it"
        )
        assert row.spec_dirty_claimed_at == original_claim, (
            "the running worker's lease was released; a second worker can now "
            "review the same deck concurrently"
        )


class TestTheMarkerLandsOnTheOwnerDeck:
    """The shape that raises TypeError if owner resolution is written wrong."""

    def test_a_contributor_edit_marks_the_owners_deck(self, contributor_session):
        """`request.session_id` can be a CONTRIBUTOR id; the marker is the owner's.

        A contributor session's own `UserSession.slide_deck` is None, so an
        implementation without owner resolution marks nothing at all — and a
        sweeper reading owner decks would never see this human's edit.
        """
        assert _contributor_deck_row_count(contributor_session) == 1

        with _patched(contributor_session._factory):
            assert (
                mark_dirty(contributor_session.contributor_session_id, _AUTHOR)
                is True
            )

        owner_deck = contributor_session.owner_deck_row()
        assert owner_deck.spec_dirty_at is not None, (
            "the owner's deck carries no marker after a contributor's edit"
        )
        assert owner_deck.spec_dirty_by == _AUTHOR
        assert _contributor_deck_row_count(contributor_session) == 1, (
            "a second deck row was created for the contributor session"
        )


class TestTheMarkerIsNotDeckState:
    def test_marking_does_not_bump_the_optimistic_lock_version(
        self, deck_with_marker
    ):
        """The editing client holds the version its own edit produced.

        A version bump here would 409 that client's very next save, so the marker
        write must leave `version` alone.
        """
        before = deck_with_marker.deck_row()

        with _patched(deck_with_marker._factory):
            mark_dirty(deck_with_marker.session_id, _AUTHOR)

        after = deck_with_marker.deck_row()
        assert after.version == before.version
        assert after.modified_by == before.modified_by, (
            "modified_by belongs to the edit, not to the marker"
        )

    def test_marking_does_not_touch_deck_content(self, deck_with_marker):
        before = deck_with_marker.deck_row()

        with _patched(deck_with_marker._factory):
            mark_dirty(deck_with_marker.session_id, _AUTHOR)

        after = deck_with_marker.deck_row()
        assert after.deck_json == before.deck_json
        assert after.title == before.title
        assert after.slide_count == before.slide_count


class TestMarkDirtyNeverBreaksTheHumansEdit:
    """It runs AFTER the edit committed, so it must not raise. Ever."""

    def test_an_unknown_session_returns_false_and_does_not_raise(
        self, deck_with_marker
    ):
        with _patched(deck_with_marker._factory):
            assert mark_dirty("no-such-session-id", _AUTHOR) is False

    def test_a_session_with_no_deck_row_returns_false(self):
        """Nothing to invalidate, and no deck row is fabricated."""
        engine = _make_in_memory_engine()
        factory = _make_factory(engine)
        try:
            db = factory()
            try:
                db.add(UserSession(session_id="deckless", created_by="u@example.com"))
                db.commit()
            finally:
                db.close()

            with _patched(factory):
                assert mark_dirty("deckless", _AUTHOR) is False

            db = factory()
            try:
                assert db.query(SessionSlideDeck).count() == 0, (
                    "mark_dirty fabricated a deck row"
                )
            finally:
                db.close()
        finally:
            engine.dispose()

    def test_a_failing_database_returns_false_rather_than_raising(
        self, deck_with_marker
    ):
        """Paired with the success case: the swallow is real, and narrow.

        Without the pair, a mark_dirty that returned False unconditionally would
        satisfy this test.
        """
        with _patched(deck_with_marker._factory):
            assert mark_dirty(deck_with_marker.session_id, _AUTHOR) is True

        boom = patch(
            _SPEC_SYNC_DB, side_effect=RuntimeError("database is on fire")
        )
        with boom:
            assert mark_dirty(deck_with_marker.session_id, _AUTHOR) is False


class TestClearMarker:
    def test_clearing_empties_all_three_columns(self, deck_with_marker):
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)
        deck_with_marker.set_claim(age_seconds=100)
        assert deck_with_marker.deck_row().spec_dirty_at is not None

        with _patched(deck_with_marker._factory):
            assert clear_marker(deck_with_marker.session_id) is True

        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at is None
        assert row.spec_dirty_by is None
        assert row.spec_dirty_claimed_at is None

    def test_clearing_an_unmarked_deck_returns_false(self, deck_with_marker):
        with _patched(deck_with_marker._factory):
            assert clear_marker(deck_with_marker.session_id) is False

    def test_an_unknown_session_raises_rather_than_swallowing(
        self, deck_with_marker
    ):
        """The asymmetry with mark_dirty, pinned.

        clear_marker runs on a background tick with no user to mislead; a
        swallowed failure there would hide a permanently stuck queue.
        """
        with _patched(deck_with_marker._factory):
            with pytest.raises(SessionNotFoundError):
                clear_marker("no-such-session-id")

    def test_marking_does_not_clear_and_clearing_does_not_mark(
        self, deck_with_marker
    ):
        """Round trip: set, clear, set again — each step observable."""
        with _patched(deck_with_marker._factory):
            mark_dirty(deck_with_marker.session_id, _AUTHOR)
            assert deck_with_marker.deck_row().spec_dirty_at is not None

            clear_marker(deck_with_marker.session_id)
            assert deck_with_marker.deck_row().spec_dirty_at is None

            mark_dirty(deck_with_marker.session_id, _LATER_AUTHOR)
            row = deck_with_marker.deck_row()
            assert row.spec_dirty_at is not None
            assert row.spec_dirty_by == _LATER_AUTHOR


class TestClearAndClaimAgreeOnTheKey:
    """Both must key on the OWNER-resolved id or markers never clear.

    Task 5's `claim_due_marker` returns the owner's string id.  If `clear_marker`
    resolved a different row, the sweeper would clear nothing and re-claim the
    same deck forever.
    """

    def test_a_contributor_can_clear_the_marker_it_set(self, contributor_session):
        """DO NOT deduplicate this against its sibling below. It looks redundant
        beside `test_the_owner_id_clears_a_marker_a_contributor_set` and is not:
        this is the ONLY test in the suite that can see a mis-keyed `clear_marker`.

        Measured by sabotage: replace `clear_marker`'s owner resolution with the
        requesting session's own row and this test fails (`clear_marker(...)`
        returns False, the owner's marker survives) while the sibling stays GREEN —
        because an owner id resolves to its own row either way, so the sweeper's own
        path cannot detect the defect.

        The two tests cover different directions on purpose:
          this one  — a CONTRIBUTOR clears; catches missing owner resolution.
          sibling   — the OWNER id clears what a contributor set; pins agreement
                      with the id Task 5's `claim_due_marker` returns.

        Merging them, or deleting this one as duplicative, silently removes the
        guard on the "markers never cleared, deck re-claimed forever" defect.
        """
        with _patched(contributor_session._factory):
            mark_dirty(contributor_session.contributor_session_id, _AUTHOR)
            assert contributor_session.owner_deck_row().spec_dirty_at is not None

            assert (
                clear_marker(contributor_session.contributor_session_id) is True
            )

        assert contributor_session.owner_deck_row().spec_dirty_at is None

    def test_the_owner_id_clears_a_marker_a_contributor_set(
        self, contributor_session
    ):
        """The sweeper's actual path: claim returns the OWNER id, clear uses it."""
        owner_id = _owner_session_id_of(contributor_session)
        assert owner_id != contributor_session.contributor_session_id

        with _patched(contributor_session._factory):
            mark_dirty(contributor_session.contributor_session_id, _AUTHOR)
            assert contributor_session.owner_deck_row().spec_dirty_at is not None

            assert clear_marker(owner_id) is True

        assert contributor_session.owner_deck_row().spec_dirty_at is None, (
            "the sweeper cleared with the owner id and the marker survived: this "
            "deck is now re-claimed on every tick forever"
        )


class TestTheReDirtyRule:
    """An edit made after the claim must survive the finishing review's clear."""

    def test_a_marker_set_after_the_claim_is_kept_and_the_lease_released(
        self, deck_with_marker
    ):
        deck_with_marker.set_claim(age_seconds=100)
        deck_with_marker.set_marker(age_seconds=50, author=_LATER_AUTHOR)
        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at > row.spec_dirty_claimed_at, (
            "fixture precondition: re-dirtied after the claim"
        )
        marker_at = row.spec_dirty_at

        with _patched(deck_with_marker._factory):
            assert clear_marker(deck_with_marker.session_id) is False

        after = deck_with_marker.deck_row()
        assert after.spec_dirty_at == marker_at, (
            "the human edit made during the review was silently discarded"
        )
        assert after.spec_dirty_by == _LATER_AUTHOR
        assert after.spec_dirty_claimed_at is None, (
            "the lease must be released so the next tick can claim the new window"
        )

    def test_a_marker_older_than_the_claim_is_cleared_normally(
        self, deck_with_marker
    ):
        """The paired positive: the rule is narrow, not a blanket refusal.

        Without this, a clear_marker that never cleared anything would pass the
        test above.
        """
        deck_with_marker.set_marker(age_seconds=300, author=_AUTHOR)
        deck_with_marker.set_claim(age_seconds=100)
        row = deck_with_marker.deck_row()
        assert row.spec_dirty_at < row.spec_dirty_claimed_at

        with _patched(deck_with_marker._factory):
            assert clear_marker(deck_with_marker.session_id) is True

        assert deck_with_marker.deck_row().spec_dirty_at is None

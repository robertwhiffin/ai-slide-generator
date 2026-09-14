"""The sweeper half of src/services/spec_sync.py: claim, review, clear.

Real sqlite throughout — every claim assertion reads the deck row back.  A mock
cannot see the two defects these functions exist to avoid: a claim that returns
the INTEGER FK instead of the owner's string id (after which nothing downstream
ever matches a row, in silence, forever), and a lease that four workers can take
at once.

Driving the module
-----------------
`claim_due_marker`, `_release_claim` and `clear_marker` each open their own DB
session via `get_db_session`, so a throwaway engine reaches them only by patching
this module's own reference, `src.services.spec_sync.get_db_session`.
`src.api.services.session_manager.get_db_session` is patched alongside, following
tests/unit/test_spec_sync_marker.py, so that the reused SessionManager helpers —
and `require_editing_lock`, which one test drives for real — run against THIS
engine and fail on the behaviour rather than on a real-database connection error
that would hide it.

`run_arc_review` imports `invoke_graph` inside the function, so the patch target
is the definition site, `src.services.graph.builder.invoke_graph`.

Why the absence assertions here are all PAIRED
----------------------------------------------
"A claimed marker is not re-claimed", "a marker with no author is not claimed"
and "a marker younger than the window is not claimed" are all absence
assertions: each is equally true when `claim_due_marker` never ran at all, or
when its query is broken in a way that claims nothing ever.  So every one of
them asserts, on the SAME deck and in the SAME test, that the claim DOES fire
once the blocking condition is removed.  Deleting the claim query reddens both
halves.

Why the four-claimer test proves less than it looks like it proves
-----------------------------------------------------------------
See `TestFourConcurrentClaimers` — sqlite has a single writer, so four threads
tend to *serialise* rather than race, and the load-bearing version of this test
is ws4e's layer-4 one against a real database.  It is here because it does still
fail when the lease predicate is dropped, which is worth having; it is not here
as proof of exclusivity.

It does NOT use `sqlite_engine_file_backed`: that fixture is `StaticPool`, which
hands every thread ONE connection, and it corrupted the database in 3 of 3
measured fan-out runs on ws4c.  The load-bearing part is the POOL CLASS, not the
storage location, so this file builds its own file-backed engine on the default
`QueuePool` where each thread gets its own connection.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import os
import sys
import tempfile
import threading
import tokenize
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from unittest.mock import patch

from src.api.services.session_manager import SessionManager
from src.core.database import Base, _run_migrations
from src.core.user_context import get_current_user, set_current_user
from src.database.models.session import SessionSlideDeck, UserSession
from src.services.spec_sync import (
    ARC_REVIEW_MESSAGE,
    CLAIM_TTL_SECONDS,
    DEBOUNCE_SECONDS,
    SWEEP_INTERVAL_SECONDS,
    claim_due_marker,
    clear_marker,
    mark_dirty,
    run_arc_review,
    spec_review_sweeper_loop,
    sweep_once,
)
from tests.unit.conftest import _make_fake_db, _make_factory, _make_in_memory_engine

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_INVOKE_GRAPH = "src.services.graph.builder.invoke_graph"

_AUTHOR = "arc-author@example.com"
_SECOND_AUTHOR = "second-arc-author@example.com"
# The editing lock is held by the marker's own author, because that is the real
# situation the binding exists for: the human editing in the WYSIWYG editor took
# the lock AND is the author `mark_dirty` recorded.
_LOCK_HOLDER = _AUTHOR

_REPO_ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def _patched(factory):
    """Point both get_db_session references at *factory*'s throwaway engine."""
    fake = _make_fake_db(factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_MANAGER_DB, fake):
        yield


# ---------------------------------------------------------------------------
# A minimal owner-session + deck, built directly so a test can place a marker
# at an arbitrary age without a fixture round-trip.
# ---------------------------------------------------------------------------


class _Deck:
    """One owner session and its deck row, on a caller-supplied engine."""

    def __init__(self, factory, session_id: str, deck_id: int, owner_pk: int):
        self._factory = factory
        self.session_id = session_id
        self.deck_id = deck_id
        self.owner_pk = owner_pk

    def set_marker(
        self,
        age_seconds: float = 0.0,
        author: Optional[str] = _AUTHOR,
        claim_age_seconds: Optional[float] = None,
        base: Optional[datetime] = None,
    ) -> None:
        """Write the marker *age_seconds* before *base* (default: now).

        `base` exists so a boundary test can place the marker EXACTLY on the
        window edge relative to the `now` it will pass to `claim_due_marker`.
        Reading the clock twice puts the two a few microseconds apart, which is
        enough to flip an exact-boundary assertion run to run.
        """
        now = base or datetime.utcnow()
        values: Dict[str, Any] = {
            "at": now - timedelta(seconds=age_seconds),
            "by": author,
            "claimed": (
                None
                if claim_age_seconds is None
                else now - timedelta(seconds=claim_age_seconds)
            ),
            "id": self.deck_id,
        }
        self._exec(
            "UPDATE session_slide_decks SET spec_dirty_at = :at, "
            "spec_dirty_by = :by, spec_dirty_claimed_at = :claimed WHERE id = :id",
            values,
        )

    def hold_editing_lock(self, user: str = _LOCK_HOLDER) -> None:
        self._exec(
            "UPDATE session_slide_decks SET locked_by = :by, locked_at = :at "
            "WHERE id = :id",
            {"by": user, "at": datetime.utcnow(), "id": self.deck_id},
        )

    def backdate_updated_at(self, seconds: float = 3600.0) -> datetime:
        """Plant a known-old ``updated_at`` and return it.

        Reading the value the INSERT happened to write and asserting it is
        unchanged would be a microsecond-resolution race with the very UPDATE
        under test.  A timestamp an hour old makes both directions exact.
        """
        stamp = datetime.utcnow() - timedelta(seconds=seconds)
        self._exec(
            "UPDATE session_slide_decks SET updated_at = :at WHERE id = :id",
            {"at": stamp, "id": self.deck_id},
        )
        assert self.row().updated_at == stamp, "the backdate did not take"
        return stamp

    def row(self) -> SessionSlideDeck:
        db = self._factory()
        try:
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.id == self.deck_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()

    def _exec(self, sql: str, params: dict) -> None:
        db = self._factory()
        try:
            db.execute(text(sql), params)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _seed_owner_deck(factory, session_id: str = "owner-sess-0001") -> _Deck:
    """Insert one owner UserSession and its SessionSlideDeck; return a handle."""
    db = factory()
    try:
        owner = UserSession(session_id=session_id, created_by="owner@example.com")
        db.add(owner)
        db.flush()
        deck = SessionSlideDeck(
            session_id=owner.id,
            title="Sweeper Deck",
            html_content="",
            scripts_content="",
            slide_count=1,
        )
        db.add(deck)
        db.commit()
        return _Deck(factory, session_id, deck.id, owner.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture
def owner_deck():
    """An in-memory engine carrying one owner session and its deck."""
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    yield _seed_owner_deck(factory)
    engine.dispose()


@pytest.fixture
def owner_factory():
    """(factory, deck) so a test can seed a SECOND session on the same engine."""
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    yield factory, _seed_owner_deck(factory)
    engine.dispose()


class _GraphSpy:
    """Records every invoke_graph call, plus the identity live at call time.

    The identity capture is the entry assertion for the ContextVar binding: a
    test that only inspected `get_current_user()` after the call could not tell a
    binding that never happened from one that was correctly restored.
    """

    def __init__(self, raises: Optional[BaseException] = None, side_effect=None):
        self.calls: List[Dict[str, Any]] = []
        self.identities: List[Optional[str]] = []
        self._raises = raises
        self._side_effect = side_effect

    def __call__(
        self,
        session_id,
        initial=None,
        *,
        emitter=None,
        principal=None,
        describe_only=False,
    ):
        self.calls.append(
            {
                "session_id": session_id,
                "initial": initial,
                "emitter": emitter,
                "principal": principal,
                "describe_only": describe_only,
            }
        )
        self.identities.append(get_current_user())
        if self._side_effect is not None:
            self._side_effect(session_id)
        if self._raises is not None:
            raise self._raises
        return {}


# ---------------------------------------------------------------------------
# The constants the plan fixes verbatim
# ---------------------------------------------------------------------------


class TestTheSweeperConstants:
    def test_sweep_interval_is_60_seconds(self):
        assert SWEEP_INTERVAL_SECONDS == 60

    def test_the_claim_ttl_is_900_seconds(self):
        """A TTL, not a bare IS NULL: a worker that dies mid-review must not
        wedge the deck permanently."""
        assert CLAIM_TTL_SECONDS == 900

    def test_the_ttl_is_longer_than_the_debounce_window(self):
        """Otherwise a claim expires before the review it covers can finish and
        two workers review the same deck — the cost the lease exists to stop."""
        assert CLAIM_TTL_SECONDS > DEBOUNCE_SECONDS


# ---------------------------------------------------------------------------
# claim_due_marker — the due window
# ---------------------------------------------------------------------------


class TestTheDebounceWindow:
    def test_a_marker_younger_than_the_window_is_not_claimed_but_an_older_one_is(
        self, owner_deck
    ):
        """PAIRED absence assertion.

        "Not claimed" is also true of a claim query that never runs, so the same
        deck is then aged past the window and MUST be claimed.  Deleting the
        query reddens the second half.
        """
        now = datetime.utcnow()
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS - 30, author=_AUTHOR)

        with _patched(owner_deck._factory):
            assert claim_due_marker(now) is None, (
                "a marker inside the coalescing window was claimed; a burst of "
                "WYSIWYG edits will pay for one LLM review per edit"
            )
            assert owner_deck.row().spec_dirty_claimed_at is None

            # Entry assertion: the same query, the same deck, one condition away.
            owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 30, author=_AUTHOR)
            claimed = claim_due_marker(now)

        assert claimed is not None, (
            "a marker past the debounce window was NOT claimed — the claim query "
            "never fires, and the first half of this test proves nothing"
        )

    def test_a_deck_with_no_marker_at_all_is_not_claimed_but_a_marked_one_is(
        self, owner_deck
    ):
        """PAIRED absence assertion — the queue must be empty when nothing is due."""
        now = datetime.utcnow()
        assert owner_deck.row().spec_dirty_at is None, "fixture precondition"

        with _patched(owner_deck._factory):
            assert claim_due_marker(now) is None

            owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
            assert claim_due_marker(now) is not None, (
                "the claim finds nothing even with a due marker present"
            )

    def test_a_marker_exactly_at_the_window_boundary_is_claimed(self, owner_deck):
        """`<=`, not `<`: a marker that has waited exactly the window is due."""
        now = datetime.utcnow()
        owner_deck.set_marker(
            age_seconds=DEBOUNCE_SECONDS, author=_AUTHOR, base=now
        )
        assert owner_deck.row().spec_dirty_at == now - timedelta(
            seconds=DEBOUNCE_SECONDS
        ), "the marker is not exactly on the boundary, so this proves nothing"
        with _patched(owner_deck._factory):
            assert claim_due_marker(now) is not None


class TestWhatTheClaimReturns:
    def test_a_due_marker_is_claimed_with_its_recorded_author(self, owner_deck):
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)

        with _patched(owner_deck._factory):
            claimed = claim_due_marker(datetime.utcnow())

        assert claimed == (owner_deck.session_id, _AUTHOR)
        assert owner_deck.row().spec_dirty_claimed_at is not None, (
            "the claim returned a marker without writing the lease; four workers "
            "will all take the same deck"
        )

    def test_the_author_returned_is_the_stored_one_and_not_a_constant(
        self, owner_deck
    ):
        """Two DISTINCT authors in sequence, so a hardcoded value cannot satisfy
        both — the tautological-default trap, whose lazy form here would be
        asserting the author is merely `not None`."""
        with _patched(owner_deck._factory):
            owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
            first = claim_due_marker(datetime.utcnow())

            owner_deck.set_marker(
                age_seconds=DEBOUNCE_SECONDS + 1, author=_SECOND_AUTHOR
            )
            second = claim_due_marker(datetime.utcnow())

        assert first[1] == _AUTHOR
        assert second[1] == _SECOND_AUTHOR

    def test_the_claim_returns_the_STRING_session_id_not_the_integer_fk(
        self, owner_deck
    ):
        """The defect that would wedge a deck in production, invisibly, forever.

        `session_slide_decks.session_id` is the INTEGER FK to `user_sessions.id`,
        so `RETURNING session_id` yields an int while `clear_marker` filters on
        the string.  Return the int and no row ever matches: the marker is never
        cleared and the deck is re-claimed every CLAIM_TTL_SECONDS for ever, with
        nothing raising.
        """
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)

        with _patched(owner_deck._factory):
            claimed = claim_due_marker(datetime.utcnow())

        session_id = claimed[0]
        assert isinstance(session_id, str), (
            f"the claim returned {type(session_id).__name__} "
            f"{session_id!r}; clear_marker filters on the string id and will "
            "match no row"
        )
        assert session_id == owner_deck.session_id
        # The int the FK actually holds, so the assertion above is not merely
        # "some string": it is the RIGHT string, and the two differ.
        assert owner_deck.row().session_id == owner_deck.owner_pk
        assert session_id != owner_deck.owner_pk


class TestAMarkerWithNoAuthorIsNotClaimed:
    def test_a_null_author_blocks_the_claim_but_an_author_unblocks_it(
        self, owner_deck
    ):
        """PAIRED absence assertion.

        With no identity there is no attribution for the write, none for cost,
        and no permission provenance — and inventing a system identity was the
        rejected alternative.  The paired half sets an author on the SAME deck
        and requires the claim to fire, so a claim query that never runs cannot
        pass this test.
        """
        now = datetime.utcnow()
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 60, author=None)
        assert owner_deck.row().spec_dirty_at is not None, (
            "fixture precondition: the marker IS set, only its author is NULL"
        )

        with _patched(owner_deck._factory):
            assert claim_due_marker(now) is None, (
                "a marker with no author was claimed; the arc review would run "
                "with no identity to attribute it to"
            )
            assert owner_deck.row().spec_dirty_claimed_at is None, (
                "the lease was written for a marker that cannot be reviewed"
            )

            owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 60, author=_AUTHOR)
            assert claim_due_marker(now) == (owner_deck.session_id, _AUTHOR), (
                "the same deck is not claimed even WITH an author — the author "
                "predicate is not what blocked the first half"
            )


class TestTheLease:
    def test_a_claimed_marker_is_not_re_claimed_though_the_first_claim_succeeded(
        self, owner_deck
    ):
        """PAIRED absence assertion: the first claim must be shown to happen."""
        now = datetime.utcnow()
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)

        with _patched(owner_deck._factory):
            first = claim_due_marker(now)
            assert first == (owner_deck.session_id, _AUTHOR), (
                "the first claim did not fire, so the second returning None "
                "says nothing about the lease"
            )
            second = claim_due_marker(now)

        assert second is None, (
            "a deck already claimed by another worker was claimed again; one "
            "WYSIWYG session now pays for two identical LLM arc reviews"
        )

    def test_a_claim_younger_than_the_ttl_is_not_reclaimable(self, owner_deck):
        now = datetime.utcnow()
        owner_deck.set_marker(
            age_seconds=DEBOUNCE_SECONDS + 1,
            author=_AUTHOR,
            claim_age_seconds=CLAIM_TTL_SECONDS - 60,
        )
        with _patched(owner_deck._factory):
            assert claim_due_marker(now) is None

    def test_a_stale_claim_IS_reclaimable_so_a_dead_worker_cannot_wedge_the_deck(
        self, owner_deck
    ):
        now = datetime.utcnow()
        owner_deck.set_marker(
            age_seconds=DEBOUNCE_SECONDS + 1,
            author=_AUTHOR,
            claim_age_seconds=CLAIM_TTL_SECONDS + 60,
        )

        with _patched(owner_deck._factory):
            claimed = claim_due_marker(now)

        assert claimed == (owner_deck.session_id, _AUTHOR), (
            "a claim older than CLAIM_TTL_SECONDS was not reclaimable; a worker "
            "killed mid-review wedges this deck permanently"
        )
        fresh = owner_deck.row().spec_dirty_claimed_at
        assert fresh is not None and fresh > now - timedelta(seconds=60), (
            "the reclaim did not refresh the lease timestamp"
        )

    def test_taking_the_lease_does_not_touch_the_marker_or_its_author(
        self, owner_deck
    ):
        """The claim schedules; it does not dequeue.  If it cleared the marker,
        a failed review would have nothing left to retry."""
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        before = owner_deck.row()

        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())

        after = owner_deck.row()
        assert after.spec_dirty_at == before.spec_dirty_at
        assert after.spec_dirty_by == _AUTHOR

    def test_taking_the_lease_does_not_bump_the_decks_modified_timestamp(
        self, owner_deck
    ):
        """`updated_at` is surfaced to the client as the deck's `modified_at`, and
        `Column(onupdate=)` fires on any UPDATE of the row.  A sweeper taking a
        lease is not a modification, so the claim suppresses it."""
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        before = owner_deck.row().updated_at

        with _patched(owner_deck._factory):
            assert claim_due_marker(datetime.utcnow()) is not None

        assert owner_deck.row().updated_at == before, (
            "claiming a lease showed the deck as modified; nobody touched it"
        )


class TestWhoseActionBumpsTheDecksModifiedTimestamp:
    """The rule: a HUMAN action bumps ``modified_at``; a SWEEPER action does not.

    ``updated_at`` carries ``Column(onupdate=datetime.utcnow)`` and is surfaced to
    every client as the deck's ``modified_at``.  SQLAlchemy fires that
    ``onupdate`` on any UPDATE of the row, an ORM flush included — measured, and
    contrary to what this module's docstring said before ws4d — so without a
    deliberate suppression a sweeper finishing a review it alone scheduled shows
    every client that the deck was just modified.

    Both directions are here on purpose.  An implementation that suppressed the
    bump everywhere would satisfy every sweeper assertion below while making a
    real human edit invisible in the session list, so ``mark_dirty``'s bump is
    asserted too.
    """

    def test_mark_dirty_DOES_bump_it_because_a_human_edited_the_deck(
        self, owner_deck
    ):
        planted = owner_deck.backdate_updated_at()
        with _patched(owner_deck._factory):
            assert mark_dirty(owner_deck.session_id, _AUTHOR) is True
        assert owner_deck.row().updated_at > planted, (
            "a human's hand-edit left the deck's modified_at untouched; the "
            "session list will show stale activity"
        )

    def test_claiming_the_lease_does_not_bump_it(self, owner_deck):
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        planted = owner_deck.backdate_updated_at()
        with _patched(owner_deck._factory):
            assert claim_due_marker(datetime.utcnow()) is not None
        assert owner_deck.row().updated_at == planted

    def test_clearing_the_marker_does_not_bump_it(self, owner_deck):
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())
            planted = owner_deck.backdate_updated_at()
            assert clear_marker(owner_deck.session_id) is True

        row = owner_deck.row()
        assert row.spec_dirty_at is None, "the clear did not happen"
        assert row.updated_at == planted, (
            "the sweeper finished its own review and every client now sees this "
            "deck as modified just now"
        )

    def test_the_re_dirty_branchs_lease_release_does_not_bump_it_either(
        self, owner_deck
    ):
        """`clear_marker`'s OTHER branch — the one that keeps the marker.

        A test covering only the full clear leaves this path unguarded, and it is
        the path a human editing during a review takes.
        """
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())
            # Re-dirty AFTER the claim, which is what makes clear_marker keep it.
            assert mark_dirty(owner_deck.session_id, _SECOND_AUTHOR) is True
            planted = owner_deck.backdate_updated_at()
            assert clear_marker(owner_deck.session_id) is False, (
                "the re-dirty branch did not fire, so this test is exercising "
                "the full-clear path instead"
            )

        row = owner_deck.row()
        assert row.spec_dirty_at is not None
        assert row.spec_dirty_claimed_at is None
        assert row.updated_at == planted

    def test_releasing_the_claim_after_a_failure_does_not_bump_it(self, owner_deck):
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())
            planted = owner_deck.backdate_updated_at()
            with patch(_INVOKE_GRAPH, _GraphSpy(raises=RuntimeError("boom"))):
                assert run_arc_review(owner_deck.session_id, _AUTHOR) is False

        row = owner_deck.row()
        assert row.spec_dirty_claimed_at is None, "the lease was not released"
        assert row.updated_at == planted

    def test_none_of_the_sweeper_writes_touch_the_optimistic_lock_version(
        self, owner_deck
    ):
        """The sibling invariant Task 4 pinned for mark_dirty, over the new writes.

        The human whose edit set the marker holds the version their edit
        produced; a bump from a sweeper write would 409 their very next save.
        """
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        before = owner_deck.row().version
        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())
            assert owner_deck.row().version == before
            with patch(_INVOKE_GRAPH, _GraphSpy(raises=RuntimeError("boom"))):
                run_arc_review(owner_deck.session_id, _AUTHOR)
            assert owner_deck.row().version == before
            claim_due_marker(datetime.utcnow())
            assert clear_marker(owner_deck.session_id) is True
        assert owner_deck.row().version == before


class TestTheSweeperTurnIsDescribeOnly:
    def test_the_review_declares_its_turn_describe_only(self, owner_deck):
        """The enforcement half of ARC_REVIEW_MESSAGE.

        The message ASKS the architect not to rebuild; intent is model output, so
        asking is not a control.  `_INTENT_ROUTES` sends both "build" and "edit"
        to the foreman, whose builders' reviewers overwrite slide rows — with no
        emitter, so nobody watching.  The router's own behaviour is pinned in
        tests/unit/test_graph_routers.py and end to end in
        tests/integration/test_sweeper_describe_only.py.
        """
        spy = _GraphSpy()
        with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, spy):
            assert run_arc_review(owner_deck.session_id, _AUTHOR) is True

        assert spy.calls[0]["describe_only"] is True, (
            "the sweeper turn did not declare itself describe-only; a build or "
            "edit intent will dispatch builders over the human's hand-edits"
        )


class TestOldestMarkerFirst:
    def test_the_deck_that_has_waited_longest_is_claimed_first(self, owner_factory):
        """Otherwise a busy deck can starve a quiet one indefinitely."""
        factory, older = owner_factory
        newer = _seed_owner_deck(factory, session_id="owner-sess-0002")

        older.set_marker(age_seconds=DEBOUNCE_SECONDS + 600, author=_AUTHOR)
        newer.set_marker(age_seconds=DEBOUNCE_SECONDS + 10, author=_SECOND_AUTHOR)

        with _patched(factory):
            first = claim_due_marker(datetime.utcnow())
            second = claim_due_marker(datetime.utcnow())

        assert first == (older.session_id, _AUTHOR)
        assert second == (newer.session_id, _SECOND_AUTHOR)


# ---------------------------------------------------------------------------
# The contributor direction.  Nineteen tests on Tasks 1 and 4 stayed green with
# owner resolution removed because they only ever exercised a standalone
# session; the claim, clear_marker and run_arc_review all key on the owner.
# ---------------------------------------------------------------------------


class TestTheContributorDirection:
    @staticmethod
    def _seed_pair(factory) -> Tuple[str, str, int]:
        """Owner session + deck + a contributor whose parent is the owner's PK."""
        db = factory()
        try:
            owner = UserSession(
                session_id="owner-of-shared-deck", created_by="owner@example.com"
            )
            db.add(owner)
            db.flush()
            deck = SessionSlideDeck(
                session_id=owner.id,
                title="Shared Deck",
                html_content="",
                scripts_content="",
                slide_count=1,
            )
            db.add(deck)
            contrib = UserSession(
                session_id="contributor-of-shared-deck",
                created_by="contributor@example.com",
                parent_session_id=owner.id,
            )
            db.add(contrib)
            db.commit()
            return owner.session_id, contrib.session_id, deck.id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def test_a_marker_set_through_a_contributor_id_round_trips_on_the_OWNER(self):
        """The full loop across the seam that has broken three times.

        A contributor's edit marks the OWNER's deck row (there is no deck row for
        a contributor session).  The claim must therefore hand back the OWNER's
        string id — not the contributor's, and not the integer FK — because that
        is the id `clear_marker` keys on.  Get any of the three wrong and the
        marker is never cleared and the deck is re-claimed for ever.
        """
        engine = _make_in_memory_engine()
        factory = _make_factory(engine)
        try:
            owner_sid, contrib_sid, deck_id = self._seed_pair(factory)

            with _patched(factory):
                assert mark_dirty(contrib_sid, _AUTHOR) is True

                # Age the marker past the window without sleeping.
                db = factory()
                try:
                    db.execute(
                        text(
                            "UPDATE session_slide_decks SET spec_dirty_at = :at "
                            "WHERE id = :id"
                        ),
                        {
                            "at": datetime.utcnow()
                            - timedelta(seconds=DEBOUNCE_SECONDS + 60),
                            "id": deck_id,
                        },
                    )
                    db.commit()
                finally:
                    db.close()

                claimed = claim_due_marker(datetime.utcnow())
                assert claimed is not None, (
                    "a contributor's edit produced a marker no sweeper can claim"
                )
                assert claimed[0] == owner_sid, (
                    f"the claim returned {claimed[0]!r}; clear_marker keys on the "
                    f"owner's id {owner_sid!r}"
                )
                assert claimed[0] != contrib_sid
                assert claim_due_marker(datetime.utcnow()) is None

                # The id the claim returned must be the one that clears.
                assert clear_marker(claimed[0]) is True

            db = factory()
            try:
                deck = (
                    db.query(SessionSlideDeck)
                    .filter(SessionSlideDeck.id == deck_id)
                    .one()
                )
                assert deck.spec_dirty_at is None
                assert deck.spec_dirty_by is None
                assert deck.spec_dirty_claimed_at is None
            finally:
                db.close()
        finally:
            engine.dispose()

    def test_a_contributor_sessions_review_runs_end_to_end_as_the_marker_author(
        self,
    ):
        """run_arc_review, driven with the id the claim returned on a shared deck."""
        engine = _make_in_memory_engine()
        factory = _make_factory(engine)
        try:
            owner_sid, contrib_sid, deck_id = self._seed_pair(factory)
            spy = _GraphSpy()

            with _patched(factory), patch(_INVOKE_GRAPH, spy):
                mark_dirty(contrib_sid, _AUTHOR)
                db = factory()
                try:
                    db.execute(
                        text(
                            "UPDATE session_slide_decks SET spec_dirty_at = :at "
                            "WHERE id = :id"
                        ),
                        {
                            "at": datetime.utcnow()
                            - timedelta(seconds=DEBOUNCE_SECONDS + 60),
                            "id": deck_id,
                        },
                    )
                    db.commit()
                finally:
                    db.close()

                assert sweep_once() == 1

            assert len(spy.calls) == 1, "the sweep claimed but never reviewed"
            assert spy.calls[0]["session_id"] == owner_sid
            assert spy.calls[0]["principal"] == _AUTHOR

            db = factory()
            try:
                deck = (
                    db.query(SessionSlideDeck)
                    .filter(SessionSlideDeck.id == deck_id)
                    .one()
                )
                assert deck.spec_dirty_at is None, (
                    "the review ran but the shared deck's marker survived; it "
                    "will be reviewed again every window"
                )
                assert deck.spec_dirty_claimed_at is None
            finally:
                db.close()
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Four concurrent claimers.  Read the module docstring before trusting this.
# ---------------------------------------------------------------------------


def _file_backed_engine() -> Tuple[Any, str]:
    """A file-backed sqlite engine on the DEFAULT QueuePool, plus its path.

    QueuePool, not StaticPool: each thread checks out its own connection, which
    is what makes four claimers four writers instead of four users of one
    connection.  `sqlite_engine_file_backed` is StaticPool and corrupted the
    database in 3 of 3 measured fan-out runs on ws4c — the pool class is the
    load-bearing part, not the storage location.

    WAL and a 20 s busy timeout so a blocked writer waits for the lock rather
    than raising `database is locked`: a claimer that dies with an exception is
    not evidence about exclusivity either way.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    tables = set(sa_inspect(engine).get_table_names())
    assert "session_slide_decks" in tables, (
        f"file-backed engine has no deck table; found {sorted(tables)}"
    )
    return engine, path


class TestFourConcurrentClaimers:
    """UVICORN_WORKERS defaults to 4, so four loops race one marker.

    **This test is weak by construction and is not offered as proof of
    exclusivity.**  sqlite has a single writer, so four threads tend to
    serialise on the write lock rather than race; the load-bearing version of
    this claim is ws4e's layer-4 test against a real database.  What it does
    buy: it reddens when the lease predicate is dropped, and it asserts all four
    claimers COMPLETED — a green "at most one winner" is otherwise also true
    when three of them died.
    """

    def test_exactly_one_of_four_claimers_wins_and_all_four_complete(self):
        engine, path = _file_backed_engine()
        try:
            factory = _make_factory(engine)
            deck = _seed_owner_deck(factory)
            deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 60, author=_AUTHOR)
            now = datetime.utcnow()

            results: List[Optional[Tuple[str, str]]] = []
            errors: List[BaseException] = []
            lock = threading.Lock()
            start = threading.Barrier(4)

            def claimer():
                try:
                    start.wait(timeout=10)
                    with _patched(factory):
                        outcome = claim_due_marker(now)
                    with lock:
                        results.append(outcome)
                except BaseException as exc:  # noqa: BLE001 — recorded, asserted on
                    with lock:
                        errors.append(exc)

            threads = [threading.Thread(target=claimer) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            assert not errors, (
                "a claimer raised, so the winner count is not evidence about "
                f"exclusivity: {errors!r}"
            )
            assert len(results) == 4, (
                f"only {len(results)} of 4 claimers finished; a green winner "
                "count would be an artefact"
            )

            winners = [r for r in results if r is not None]
            assert len(winners) == 1, (
                f"{len(winners)} of 4 workers claimed the same marker — this "
                "session pays for that many identical LLM arc reviews"
            )
            assert winners[0] == (deck.session_id, _AUTHOR)
            assert deck.row().spec_dirty_claimed_at is not None
        finally:
            engine.dispose()
            with contextlib.suppress(OSError):
                os.unlink(path)


# ---------------------------------------------------------------------------
# run_arc_review — identity, the graph call, and the two marker outcomes
# ---------------------------------------------------------------------------


class TestWhatTheReviewPassesToTheGraph:
    def test_the_markers_author_is_passed_as_principal_with_no_emitter(
        self, owner_deck
    ):
        """`principal=` exists for exactly this caller: a sweeper tick has no
        request, so `principal or get_current_user()` would otherwise resolve to
        None and the deck write would land `modified_by=NULL`.  No emitter: there
        is no SSE stream to feed."""
        spy = _GraphSpy()
        with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, spy):
            assert run_arc_review(owner_deck.session_id, _AUTHOR) is True

        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["session_id"] == owner_deck.session_id
        assert call["principal"] == _AUTHOR, (
            "the graph turn was not told who it is acting as; modified_by, cost "
            "attribution and the permission provenance all lose their user"
        )
        assert call["emitter"] is None
        assert call["initial"] == {"architect_message": ARC_REVIEW_MESSAGE}

    def test_a_second_review_passes_its_OWN_author(self, owner_factory):
        """Distinct authors, so a principal wired to a constant fails."""
        factory, first = owner_factory
        second = _seed_owner_deck(factory, session_id="owner-sess-0002")
        spy = _GraphSpy()

        with _patched(factory), patch(_INVOKE_GRAPH, spy):
            run_arc_review(first.session_id, _AUTHOR)
            run_arc_review(second.session_id, _SECOND_AUTHOR)

        assert [c["principal"] for c in spy.calls] == [_AUTHOR, _SECOND_AUTHOR]


class TestIdentityIsBoundNotMerelyStamped:
    def test_the_author_is_live_in_the_context_var_during_the_graph_turn(
        self, owner_deck
    ):
        """Stamping `principal=` is not enough: anything on the turn that reads
        `get_current_user()` itself would see None."""
        spy = _GraphSpy()
        with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, spy):
            run_arc_review(owner_deck.session_id, _AUTHOR)

        assert spy.identities == [_AUTHOR], (
            f"get_current_user() was {spy.identities!r} inside the graph turn; "
            "the tick did not bind the marker's author"
        )

    def test_the_previous_identity_is_restored_and_a_second_tick_sees_its_own(
        self, owner_factory
    ):
        """A ContextVar set in a long-lived loop is not request-scoped.

        Two ticks, two DISTINCT authors: each must see its own inside the turn,
        and the var must be back to its pre-tick value afterwards.  Drop the
        restore and the trailing assertion goes red — the first tick's author is
        still bound with nothing running.
        """
        factory, first = owner_factory
        second = _seed_owner_deck(factory, session_id="owner-sess-0002")
        spy = _GraphSpy()

        set_current_user(None)
        try:
            with _patched(factory), patch(_INVOKE_GRAPH, spy):
                run_arc_review(first.session_id, _AUTHOR)
                assert get_current_user() is None, (
                    "the first tick's author is still bound after it returned; "
                    "it leaks into whatever runs next in this context"
                )

                run_arc_review(second.session_id, _SECOND_AUTHOR)
                assert get_current_user() is None

            assert spy.identities == [_AUTHOR, _SECOND_AUTHOR]
        finally:
            set_current_user(None)

    def test_the_identity_is_restored_even_when_the_review_raises(self, owner_deck):
        spy = _GraphSpy(raises=RuntimeError("skill call blew up"))
        set_current_user(None)
        try:
            with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, spy):
                assert run_arc_review(owner_deck.session_id, _AUTHOR) is False
            assert get_current_user() is None, (
                "a failed review left its author bound in the loop's context"
            )
        finally:
            set_current_user(None)

    def test_a_held_editing_lock_does_not_block_the_review_because_of_the_binding(
        self, owner_deck
    ):
        """C-3's stated failure mode, pinned with the consumer installed.

        The realistic case: the human editing in the WYSIWYG editor holds the
        deck's editing lock AND is the author `mark_dirty` recorded.
        `require_editing_lock` raises when `locked_by != get_current_user()`, so
        an unbound tick (`None`) raises on exactly the deck an arc review exists
        for, while a tick bound to the marker's author passes.

        MEASURED FACT, recorded because it changes what this test is worth: no
        module reachable from `invoke_graph` calls `require_editing_lock` today —
        its callers are the slide routes, the chat route and
        `SessionManager.restore_version` (see
        `TestRequireEditingLockHasNoCallerOnTheGraphPath`).  So C-3's mechanism
        is not reachable on the current graph path, and a test that merely ran
        the real graph would stay green with the binding removed.  This test
        therefore installs the consumer explicitly: the stubbed graph turn calls
        the REAL `require_editing_lock`.  The entry assertion below proves the
        lock genuinely bites when nothing is bound, so this is not an absence
        assertion over an inert fixture.
        """
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        owner_deck.hold_editing_lock(_LOCK_HOLDER)
        assert _LOCK_HOLDER == _AUTHOR, "the lock holder IS the marker's author"
        manager = SessionManager()

        # Entry assertion: the lock really is active, and identity really is what
        # decides.  Without this the test below could pass on a lock that had
        # already expired or was never written.  resolve_display_name is stubbed
        # because the raising path resolves a SCIM display name, which is a
        # Databricks call and is not what this test is about.
        set_current_user(None)
        try:
            with _patched(owner_deck._factory), patch(
                "src.services.identity_provider.resolve_display_name",
                lambda email: email,
            ):
                with pytest.raises(PermissionError):
                    manager.require_editing_lock(owner_deck.session_id)
        finally:
            set_current_user(None)

        def _consumer(session_id):
            manager.require_editing_lock(session_id)

        spy = _GraphSpy(side_effect=_consumer)
        with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, spy), patch(
            "src.services.identity_provider.resolve_display_name",
            lambda email: email,
        ):
            assert run_arc_review(owner_deck.session_id, _AUTHOR) is True, (
                "the arc review failed on a deck whose editing lock its own "
                "author holds — which is exactly the deck it exists for"
            )

        assert len(spy.calls) == 1
        assert spy.identities == [_AUTHOR]
        assert owner_deck.row().spec_dirty_at is None, (
            "the review did not complete, so the marker was never cleared"
        )


class TestTheMarkerOutcomes:
    def test_a_successful_review_clears_all_three_marker_columns(self, owner_deck):
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())
            with patch(_INVOKE_GRAPH, _GraphSpy()):
                assert run_arc_review(owner_deck.session_id, _AUTHOR) is True

        row = owner_deck.row()
        assert row.spec_dirty_at is None
        assert row.spec_dirty_by is None
        assert row.spec_dirty_claimed_at is None

    @staticmethod
    def _a_claimed_deck_whose_review_fails(owner_deck, exc=None):
        """Claim the marker, then run a review that raises. Returns the result."""
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            assert claim_due_marker(datetime.utcnow()) is not None
            assert owner_deck.row().spec_dirty_claimed_at is not None

            spy = _GraphSpy(raises=exc or RuntimeError("model unavailable"))
            with patch(_INVOKE_GRAPH, spy):
                return run_arc_review(owner_deck.session_id, _AUTHOR)

    def test_a_failing_review_reports_failure_without_raising(self, owner_deck):
        """C-6: never raises. It runs on a background tick with no caller to tell,
        and a raise would take the loop's iteration out.

        Split from the row assertions below, per the standing rule: leading with
        this assertion masked them, so a fix that returned the right value while
        wrecking the row read as green on one line of output.
        """
        assert self._a_claimed_deck_whose_review_fails(owner_deck) is False

    def test_a_failing_review_keeps_the_marker_and_releases_only_the_claim(
        self, owner_deck
    ):
        """Fail-open: the deck retries on the next sweep instead of wedging.

        No return-value assertion here — it lives in its sibling above, so these
        three can each fire on their own.
        """
        self._a_claimed_deck_whose_review_fails(owner_deck)

        row = owner_deck.row()
        assert row.spec_dirty_at is not None, (
            "a failed review discarded the marker; that deck's spec stays stale "
            "for ever and nothing will retry"
        )
        assert row.spec_dirty_by == _AUTHOR, (
            "the author was dropped, so the retry has no identity and will never "
            "be claimed again"
        )
        assert row.spec_dirty_claimed_at is None, (
            "the lease survived the failure; the deck is unreviewable until the "
            "TTL expires"
        )

    def test_a_review_whose_GRAPH_IMPORT_fails_also_releases_the_claim(
        self, owner_deck
    ):
        """The deferred `from ... import invoke_graph` must not escape the except.

        The graph package pulls in the nodes, the skills and the session manager,
        so this import can genuinely fail — a circular import was hit while
        probing it.  Escaping, it propagates out of a function C-6 says never
        raises, and `_release_claim` never runs: the deck stays leased for the
        full CLAIM_TTL_SECONDS instead of retrying on the next 60-second tick.
        """
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            assert claim_due_marker(datetime.utcnow()) is not None

            # Break the import the way a circular import would.
            import src.services.graph.builder as builder_mod

            with patch.dict(sys.modules, {"src.services.graph.builder": None}):
                assert builder_mod is not None  # the module object still exists
                result = run_arc_review(owner_deck.session_id, _AUTHOR)

        assert result is False, "an unimportable graph did not report failure"
        row = owner_deck.row()
        assert row.spec_dirty_claimed_at is None, (
            "the lease survived an import failure; this deck is unreviewable for "
            "the full CLAIM_TTL_SECONDS instead of retrying in 60 seconds"
        )
        assert row.spec_dirty_at is not None, "the marker was discarded"

    def test_the_marker_kept_after_a_failure_is_claimable_again(self, owner_deck):
        """The point of keeping it: the next sweep must actually pick it up."""
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
        with _patched(owner_deck._factory):
            claim_due_marker(datetime.utcnow())
            with patch(_INVOKE_GRAPH, _GraphSpy(raises=RuntimeError("boom"))):
                run_arc_review(owner_deck.session_id, _AUTHOR)

            assert claim_due_marker(datetime.utcnow()) == (
                owner_deck.session_id,
                _AUTHOR,
            )

    def test_a_deck_re_dirtied_during_the_review_keeps_its_marker_and_is_not_a_failure(
        self, owner_deck
    ):
        """Task 4's seam: clear_marker's False means "kept, still queued".

        A human edits the deck WHILE the review is running.  `clear_marker`
        releases the lease and deliberately keeps the newer marker so that edit
        gets its own review.  Read that False as an error and the mid-review
        edit is logged as a fault; if the reading ever drove a retry-or-drop
        decision it would be lost outright.

        So: run_arc_review must report SUCCESS, the marker must survive, the
        lease must be gone, and the next sweep must claim it again.
        """
        owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)

        with _patched(owner_deck._factory):
            assert claim_due_marker(datetime.utcnow()) is not None

            def _human_edits_mid_review(session_id):
                # Exactly what the route does, through the real function: this
                # opens a NEW window on an already-claimed marker.
                assert mark_dirty(session_id, _SECOND_AUTHOR) is True

            spy = _GraphSpy(side_effect=_human_edits_mid_review)
            with patch(_INVOKE_GRAPH, spy):
                assert run_arc_review(owner_deck.session_id, _AUTHOR) is True, (
                    "a human's mid-review edit was reported as a failed review; "
                    "clear_marker's False means 'kept, still queued', not 'error'"
                )

            row = owner_deck.row()
            assert row.spec_dirty_at is not None, (
                "the edit made during the review was discarded — the exact work "
                "loss the re-dirty rule exists to prevent"
            )
            assert row.spec_dirty_by == _SECOND_AUTHOR
            assert row.spec_dirty_claimed_at is None

            # And it is genuinely re-queued, not merely left in the row.
            later = datetime.utcnow() + timedelta(seconds=DEBOUNCE_SECONDS + 1)
            assert claim_due_marker(later) == (
                owner_deck.session_id,
                _SECOND_AUTHOR,
            )

    def test_a_review_for_a_vanished_session_does_not_raise_and_keeps_nothing(
        self, owner_deck
    ):
        """run_arc_review NEVER raises — clear_marker does, by design, on an
        unknown session id, and that must not take out the loop's iteration."""
        with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, _GraphSpy()):
            assert run_arc_review("no-such-session", _AUTHOR) is False


# ---------------------------------------------------------------------------
# sweep_once and the loop
# ---------------------------------------------------------------------------


class TestSweepOnce:
    def test_a_tick_with_nothing_due_reviews_nothing_but_a_due_tick_does(
        self, owner_deck
    ):
        """PAIRED absence assertion over the whole tick."""
        spy = _GraphSpy()
        with _patched(owner_deck._factory), patch(_INVOKE_GRAPH, spy):
            assert sweep_once() == 0
            assert spy.calls == []

            owner_deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 1, author=_AUTHOR)
            assert sweep_once() == 1

        assert len(spy.calls) == 1, (
            "the tick claimed nothing even with a due marker; the first half of "
            "this test proves nothing"
        )
        assert spy.calls[0]["principal"] == _AUTHOR

    def test_one_tick_takes_at_most_one_deck(self, owner_factory):
        """Deliberate: an arc review is an LLM turn, and draining a backlog in
        one tick would hold the loop for minutes."""
        factory, first = owner_factory
        second = _seed_owner_deck(factory, session_id="owner-sess-0002")
        first.set_marker(age_seconds=DEBOUNCE_SECONDS + 600, author=_AUTHOR)
        second.set_marker(age_seconds=DEBOUNCE_SECONDS + 10, author=_SECOND_AUTHOR)

        spy = _GraphSpy()
        with _patched(factory), patch(_INVOKE_GRAPH, spy):
            assert sweep_once() == 1
            assert len(spy.calls) == 1
            assert sweep_once() == 1

        assert [c["session_id"] for c in spy.calls] == [
            first.session_id,
            second.session_id,
        ]


async def _cancel_within_a_bounded_wait(task, seconds: float = 5.0) -> None:
    """Cancel *task* and require it to STOP, without ever hanging.

    Why this is not `with pytest.raises(CancelledError): await task`.  Measured:
    a loop that swallows `CancelledError` and CONTINUES makes that form reden
    nothing — the whole run **hangs** (`timeout` exit 124, zero output), because
    `pytest.raises` can only fire if the task terminates.  In CI a hung test burns
    the job's entire timeout and yields no signal at all, which is strictly worse
    than a red.

    So the wait is bounded by polling rather than by `asyncio.wait_for`, whose
    own cancellation semantics would have to be reasoned about on top of the
    behaviour under test.  Three outcomes, three distinct messages:

    * the task ends cancelled — correct;
    * the task never ends — **fails** with a readable message rather than hanging;
    * the task ends without raising (swallow-and-return) — fails, because the
      lifespan awaits this task on shutdown and a loop that returns quietly on
      cancel is indistinguishable from one that crashed.
    """
    task.cancel()
    for _ in range(int(seconds / 0.01)):
        if task.done():
            break
        await asyncio.sleep(0.01)

    assert task.done(), (
        f"the loop did not stop within {seconds}s of being cancelled. It is "
        "swallowing CancelledError and continuing, so shutdown would hang — and "
        "a test that merely awaited it would hang with it instead of failing"
    )
    try:
        await task
    except asyncio.CancelledError:
        return
    raise AssertionError(
        "the loop returned instead of propagating CancelledError; the lifespan "
        "cannot tell a clean shutdown from a crashed loop"
    )


class TestTheLoop:
    @pytest.mark.asyncio
    async def test_the_loop_survives_a_failing_tick_and_re_raises_on_cancel(self):
        """One transient DB failure must not take the loop down for the life of
        the process, and cancellation must still stop it cleanly."""
        calls: List[int] = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient database failure")
            return 0

        with patch("src.services.spec_sync.SWEEP_INTERVAL_SECONDS", 0), patch(
            "src.services.spec_sync.sweep_once", flaky
        ):
            task = asyncio.create_task(spec_review_sweeper_loop())
            for _ in range(500):
                if len(calls) >= 3:
                    break
                await asyncio.sleep(0.01)
            await _cancel_within_a_bounded_wait(task)

        assert len(calls) >= 3, (
            f"the loop stopped after {len(calls)} tick(s); it did not survive "
            "the first failure"
        )

    @pytest.mark.asyncio
    async def test_the_loop_sleeps_before_its_first_tick(self):
        """The interval is read from the module, not captured at import: a test
        that could not change it would prove nothing about the real value."""
        calls: List[int] = []
        sleeps: List[float] = []
        real_sleep = asyncio.sleep

        async def recording_sleep(seconds, *a, **kw):
            sleeps.append(seconds)
            return await real_sleep(0)

        with patch("src.services.spec_sync.SWEEP_INTERVAL_SECONDS", 41), patch(
            "src.services.spec_sync.sweep_once", lambda: calls.append(1) or 0
        ), patch("src.services.spec_sync.asyncio.sleep", recording_sleep):
            task = asyncio.create_task(spec_review_sweeper_loop())
            for _ in range(500):
                if calls:
                    break
                await real_sleep(0.01)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert calls, "the loop never reached a tick"
        assert sleeps and sleeps[0] == 41, (
            f"the loop slept {sleeps[:1]!r}, not the module's interval"
        )


# ---------------------------------------------------------------------------
# Where the loop is registered.  A periodic loop in run.py::init_database would
# die with the pre-fork step; a migration in the lifespan would race four
# workers.  This is the wiring, so it is asserted structurally.
# ---------------------------------------------------------------------------


def _name_tokens(path: Path) -> List[str]:
    """Every NAME token in *path*, comments and strings discarded."""
    readline = io.BytesIO(path.read_bytes()).readline
    return [t.string for t in tokenize.tokenize(readline) if t.type == tokenize.NAME]


class TestWhereTheLoopIsRegistered:
    _MAIN = _REPO_ROOT / "src/api/main.py"
    _RUN = (
        _REPO_ROOT
        / "packages/databricks-tellr-app/databricks_tellr_app/run.py"
    )

    def test_the_files_this_asserts_about_are_the_ones_that_exist(self):
        """Entry assertion for every absence below: a missing path would make
        them all vacuously true."""
        assert self._MAIN.is_file(), self._MAIN
        assert self._RUN.is_file(), self._RUN
        assert "lifespan" in _name_tokens(self._MAIN)
        assert "init_database" in _name_tokens(self._RUN)

    def test_the_sweeper_task_is_created_inside_the_lifespan(self):
        tree = ast.parse(self._MAIN.read_text())
        lifespan = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "lifespan"
        )
        created = [
            n
            for n in ast.walk(lifespan)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_task"
            and n.args
            and isinstance(n.args[0], ast.Call)
            and isinstance(n.args[0].func, ast.Name)
            and n.args[0].func.id == "spec_review_sweeper_loop"
        ]
        assert len(created) == 1, (
            "asyncio.create_task(spec_review_sweeper_loop()) is not inside the "
            "lifespan; nothing consumes the spec-dirty marker at runtime"
        )
        # And the sibling loops are still there, so this test is reading the
        # block it thinks it is reading.
        other = [
            n.args[0].func.id
            for n in ast.walk(lifespan)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_task"
            and n.args
            and isinstance(n.args[0], ast.Call)
            and isinstance(n.args[0].func, ast.Name)
        ]
        assert "mark_timed_out_jobs_loop" in other
        assert "request_log_cleanup_loop" in other

    def test_the_sweeper_task_is_cancelled_on_shutdown(self):
        source = self._MAIN.read_text()
        assert "_spec_sweeper_task.cancel()" in source, (
            "the sweeper task is never cancelled; shutdown will hang or log a "
            "pending-task warning on every deploy"
        )
        assert "_spec_sweeper_task = asyncio.create_task(" in source

    def test_the_pre_fork_init_database_does_NOT_start_the_loop(self):
        """§L8's pre-fork rule is for migrations and backfills, which run once.
        A periodic loop started there would die with that step."""
        tokens = _name_tokens(self._RUN)
        assert "spec_review_sweeper_loop" not in tokens, (
            "the sweeper loop is referenced in run.py; a loop started in the "
            "pre-fork step dies with it and no worker ever sweeps"
        )
        assert "sweep_once" not in tokens


class TestRequireEditingLockHasNoCallerOnTheGraphPath:
    """The measured fact behind
    `test_a_held_editing_lock_does_not_block_the_review_because_of_the_binding`.

    C-3 argues the identity binding is needed because `require_editing_lock`
    reads `get_current_user()`.  It does — but nothing the graph runs calls it,
    so on today's tree the binding has no consumer on the sweeper's own path.
    That is worth recording as a tripwire rather than prose: if a graph node,
    `deck_level_writer`, `slide_repository` or `chat_service` ever starts calling
    it, C-3's mechanism becomes live and this test says so out loud.
    """

    _ALLOWED = {
        "src/api/services/session_manager.py",  # the definition + restore_version
        "src/api/routes/slides.py",
        "src/api/routes/chat.py",
    }

    @staticmethod
    def _files_referencing(token: str) -> set:
        found = set()
        for path in (_REPO_ROOT / "src").rglob("*.py"):
            try:
                if token in _name_tokens(path):
                    found.add(str(path.relative_to(_REPO_ROOT)))
            except (SyntaxError, tokenize.TokenError):  # pragma: no cover
                continue
        return found

    def test_the_scan_finds_the_callers_that_do_exist(self):
        """Entry assertion: an absence over a scan that finds nothing is free."""
        found = self._files_referencing("require_editing_lock")
        assert self._ALLOWED <= found, (
            f"the scan missed known callers: {sorted(self._ALLOWED - found)}"
        )

    def test_no_module_OUTSIDE_THE_ALLOWLIST_calls_require_editing_lock(self):
        """Derived, not enumerated — and the difference was measured.

        An earlier version of this test intersected the scan with a hand-list of
        five files it guessed the graph might reach.  A reviewer added a REAL
        caller to `src/services/graph/routers.py` and got `2 passed`: the list
        did not name it, so the tripwire was blind to `routers.py`, `state.py`,
        `event_emitter.py`, `foreman_service.py` and every skill module.  That is
        the same shape as asserting set-containment where equality is needed — the
        assertion is true and says nothing about what was not listed.

        So the scan now walks all of `src/` and asserts the found set is a SUBSET
        of the allowlist.  Any new caller anywhere reddens, and the failure names
        the file.
        """
        found = self._files_referencing("require_editing_lock")
        unexpected = found - self._ALLOWED
        assert not unexpected, (
            f"{sorted(unexpected)} now references require_editing_lock. If any of "
            "these is reachable from invoke_graph, a sweeper tick's identity "
            "binding is load-bearing on the real graph path: update the reasoning "
            "in run_arc_review's docstring and give the property a test that "
            "drives the real graph. If the caller is a new route, add it to "
            "_ALLOWED deliberately."
        )

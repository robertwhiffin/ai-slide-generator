"""The sweeper's lease, on a real database with genuinely overlapping transactions.

Why this file exists
--------------------
``src/services/spec_sync.py::claim_due_marker`` names its lease predicate
(``unclaimed``) TWICE: once in the candidate subquery and once in the UPDATE's own
WHERE.  The outer copy is the whole defence — dropping it makes the statement
"claim whatever the subquery saw", a read-then-write race that lets four uvicorn
workers pay for four identical LLM arc reviews of one deck.

``tests/unit/test_spec_sync_sweeper.py::TestFourConcurrentClaimers`` cannot see
that.  Measured on this branch: dropping ONLY the outer ``.where(unclaimed)``
leaves all 87 tests of the spec_sync suite green, because SQLite has a single
writer and the four threads serialise instead of racing — the window the
predicate guards never opens.

So the exclusivity claim needs a database with real row locks and real
READ COMMITTED re-checking.  That is what this file is.

The mechanism, stated because the test is worthless if it is wrong
-----------------------------------------------------------------
PostgreSQL READ COMMITTED, four claimers, one due marker:

1. Claimer A runs its UPDATE and takes the marker row's lock.  Its transaction is
   held OPEN (see ``_ClaimGate``) — the row is claimed but not yet committed.
2. Claimers B, C and D then run their UPDATEs.  Each takes its own statement
   snapshot, in which A's write is invisible, so each candidate subquery finds the
   row unclaimed and returns its id.  Each then BLOCKS on A's row lock.
3. The test waits until it can SEE three backends waiting on a lock.  That
   observation is asserted, not assumed: without it a green "one winner" is
   equally true of four claimers that never overlapped, which is the exact
   masking failure this file was written to avoid.
4. A commits.  B, C and D wake one at a time and PostgreSQL re-checks each
   UPDATE's qual against A's committed tuple (EvalPlanQual).  The candidate
   subquery is uncorrelated, so it is an InitPlan computed once before the lock
   wait and NOT recomputed — it still yields the deck id, and ``id = <that id>``
   still matches.  The ONLY predicate that sees A's ``spec_dirty_claimed_at`` is
   the outer ``unclaimed``.  It fails, the UPDATE touches zero rows, and the
   claimer correctly returns ``None``.

Which is why deleting the outer copy turns this test from one winner into four.

The fixture, and the pool class
-------------------------------
``postgres_engine`` (tests/integration/conftest.py), NOT
``sqlite_engine_file_backed``.  That fixture is ``StaticPool``, which hands every
thread ONE connection; it corrupted the database in 3 of 3 measured fan-out runs
on ws4c.  The pool class is the load-bearing part, not the storage location, and
``TestTheFixtureGivesEachThreadItsOwnConnection`` proves it behaviourally rather
than by an isinstance check that would mirror the fixture's own source.

Driving the module
------------------
``claim_due_marker`` opens its own session via ``get_db_session``, so a throwaway
engine reaches it only by patching ``src.services.spec_sync.get_db_session``.
``src.api.services.session_manager.get_db_session`` is patched alongside it,
following tests/unit/test_spec_sync_sweeper.py, so the reused SessionManager
helpers run against THIS engine too.  The patched callable dispatches on the
current thread's name, because one process-wide patch has to give claimer A a
gated transaction and B/C/D plain ones.
"""
from __future__ import annotations

import contextlib
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy import text
from unittest.mock import patch

from src.database.models.session import SessionSlideDeck, UserSession
from src.services.spec_sync import DEBOUNCE_SECONDS, claim_due_marker
from tests.integration.conftest import _make_factory
from tests.integration.postgres_concurrency_helpers import (
    _ClaimGate,
    _Deck,
    _WAIT_SECONDS,
    _await_lock_waiters,
    _seed_owner_deck,
    _thread_aware_db,
)

pytestmark = pytest.mark.postgres

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"

_AUTHOR = "arc-author@example.com"


@contextlib.contextmanager
def _patched(factory, gates: Optional[Dict[str, _ClaimGate]] = None):
    fake = _thread_aware_db(factory, gates or {})
    with patch(_SPEC_SYNC_DB, fake), patch(_MANAGER_DB, fake):
        yield


# ---------------------------------------------------------------------------
# The fixture's pool class, proved by behaviour
# ---------------------------------------------------------------------------


class TestTheFixtureGivesEachThreadItsOwnConnection:
    """Four threads holding a connection at once hold FOUR connections.

    Asserted behaviourally — by collecting ``pg_backend_pid()`` from threads that
    are all still inside their ``with engine.connect()`` block — rather than by
    checking the pool class.  An ``isinstance(engine.pool, QueuePool)`` assertion
    would restate the fixture's own source and would still pass if a future edit
    swapped in some other single-connection pool.  Distinct backend PIDs are the
    property the concurrency tests below actually depend on.
    """

    def test_four_simultaneous_checkouts_are_four_backends(self, postgres_engine):
        barrier = threading.Barrier(4, timeout=_WAIT_SECONDS)
        pids: List[int] = []
        errors: List[BaseException] = []
        lock = threading.Lock()

        def grab() -> None:
            try:
                with postgres_engine.connect() as conn:
                    pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()
                    with lock:
                        pids.append(pid)
                    # Hold the connection until every thread has one of its own.
                    barrier.wait()
            except BaseException as exc:  # noqa: BLE001 — recorded, asserted on
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=grab) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=_WAIT_SECONDS * 2)

        assert not errors, (
            "a thread failed to check out its own connection, so the PID count "
            f"is not evidence about the pool: {errors!r}"
        )
        assert len(pids) == 4, f"only {len(pids)} of 4 threads reported a backend"
        assert len(set(pids)) == 4, (
            f"4 concurrent checkouts share {len(set(pids))} backend(s): {pids}. "
            "postgres_engine has been given a single-connection pool (StaticPool "
            "or equivalent). Every concurrency test in this file then measures "
            "one connection used four times, not four transactions — and on "
            "SQLite that same mistake corrupted the database in 3 of 3 runs."
        )


# ---------------------------------------------------------------------------
# The prize: four claimers whose transactions provably overlap
# ---------------------------------------------------------------------------


class TestFourOverlappingClaimersOnPostgres:
    """UVICORN_WORKERS defaults to 4, so four sweeper loops race one marker.

    Unlike the SQLite version of this test, the overlap here is CONSTRUCTED and
    then OBSERVED, so the result is evidence either way:

      * claimer A's transaction is held open holding the marker row's lock;
      * B, C and D each take a snapshot in which the row is still unclaimed and
        then block on that lock;
      * the test asserts it saw three backends waiting before releasing A.

    Delete the outer ``.where(unclaimed)`` from ``claim_due_marker`` and this
    reddens with four winners.  The SQLite version does not.
    """

    def test_exactly_one_of_four_overlapping_claimers_wins(self, postgres_engine):
        factory = _make_factory(postgres_engine)
        deck = _seed_owner_deck(factory)
        now = datetime.utcnow()
        deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 60, base=now)

        gate = _ClaimGate()
        gates = {"claimer-A": gate}
        results: Dict[str, Optional[Tuple[str, str]]] = {}
        errors: List[BaseException] = []
        lock = threading.Lock()

        def claimer() -> None:
            name = threading.current_thread().name
            try:
                with _patched(factory, gates):
                    outcome = claim_due_marker(now)
                with lock:
                    results[name] = outcome
            except BaseException as exc:  # noqa: BLE001 — recorded, asserted on
                with lock:
                    errors.append(exc)

        first = threading.Thread(target=claimer, name="claimer-A")
        first.start()

        # A has run its UPDATE and holds the row lock, uncommitted.
        assert gate.executed.wait(timeout=_WAIT_SECONDS), (
            "claimer A never reached its commit gate; it did not take the row "
            "lock, so nothing below is evidence about exclusivity"
        )

        rest = [
            threading.Thread(target=claimer, name=f"claimer-{n}")
            for n in ("B", "C", "D")
        ]
        for t in rest:
            t.start()

        # THE assertion that makes the winner count mean something.
        peak_waiters = _await_lock_waiters(postgres_engine, 3)
        try:
            assert peak_waiters >= 3, (
                f"only {peak_waiters} of 3 later claimers were ever seen waiting "
                "on the marker row's lock. Their transactions did not overlap "
                "claimer A's, so a single-winner result would be an artefact of "
                "serialisation — exactly the way the SQLite version of this test "
                "fails to see a dropped lease predicate."
            )
        finally:
            # Release A whatever happened, or the three claimers hang until their
            # own gate timeout and the failure above is buried under theirs.
            gate.release.set()

        first.join(timeout=_WAIT_SECONDS * 2)
        for t in rest:
            t.join(timeout=_WAIT_SECONDS * 2)

        assert not errors, (
            "a claimer raised, so the winner count is not evidence about "
            f"exclusivity: {errors!r}"
        )
        assert len(results) == 4, (
            f"only {sorted(results)} of 4 claimers finished; a green winner "
            "count would be an artefact"
        )

        winners = {name: out for name, out in results.items() if out is not None}
        assert len(winners) == 1, (
            f"{len(winners)} of 4 overlapping workers claimed the same marker "
            f"({sorted(winners)}) — this session pays for that many identical "
            "LLM arc reviews. The lease predicate on the UPDATE's own WHERE is "
            "what stops a blocked claimer from claiming a row another worker "
            "already took."
        )
        assert winners == {"claimer-A": (deck.session_id, _AUTHOR)}, (
            "the winner was not the claimer that took the lock first, or it did "
            f"not return the owner's STRING session id: {winners!r}"
        )

        row = deck.row()
        assert row.spec_dirty_claimed_at is not None, (
            "the winning claim did not persist a lease; the marker is still "
            "claimable and the next tick reviews the deck again"
        )
        assert row.spec_dirty_by == _AUTHOR

    def test_a_lease_older_than_the_ttl_is_reclaimable(self, postgres_engine):
        """The paired direction: the same four-way overlap DOES yield a winner
        when the existing lease has expired.

        Without this, ``exactly one winner`` above is an absence assertion that a
        ``claim_due_marker`` which claims nothing ever would also satisfy.  Here
        the marker starts out claimed — but by a worker that died an hour ago —
        and exactly one of four overlapping claimers must take it over.
        """
        from src.services.spec_sync import CLAIM_TTL_SECONDS

        factory = _make_factory(postgres_engine)
        deck = _seed_owner_deck(factory, session_id="pg-owner-sess-0002")
        now = datetime.utcnow()
        deck.set_marker(
            age_seconds=DEBOUNCE_SECONDS + 60,
            base=now,
            claim_age_seconds=CLAIM_TTL_SECONDS + 60,
        )

        gate = _ClaimGate()
        gates = {"claimer-A": gate}
        results: Dict[str, Optional[Tuple[str, str]]] = {}
        errors: List[BaseException] = []
        lock = threading.Lock()

        def claimer() -> None:
            name = threading.current_thread().name
            try:
                with _patched(factory, gates):
                    outcome = claim_due_marker(now)
                with lock:
                    results[name] = outcome
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        first = threading.Thread(target=claimer, name="claimer-A")
        first.start()
        assert gate.executed.wait(timeout=_WAIT_SECONDS), (
            "claimer A never reached its commit gate"
        )

        rest = [
            threading.Thread(target=claimer, name=f"claimer-{n}")
            for n in ("B", "C", "D")
        ]
        for t in rest:
            t.start()
        peak_waiters = _await_lock_waiters(postgres_engine, 3)
        try:
            assert peak_waiters >= 3, (
                f"only {peak_waiters} of 3 later claimers were seen waiting on "
                "the lock; the transactions did not overlap"
            )
        finally:
            gate.release.set()

        first.join(timeout=_WAIT_SECONDS * 2)
        for t in rest:
            t.join(timeout=_WAIT_SECONDS * 2)

        assert not errors, f"a claimer raised: {errors!r}"
        assert len(results) == 4, f"only {sorted(results)} of 4 claimers finished"

        winners = {name: out for name, out in results.items() if out is not None}
        assert len(winners) == 1, (
            f"{len(winners)} of 4 claimers took over an expired lease "
            f"({sorted(winners)}); the TTL must hand a wedged deck to exactly "
            "one worker, not to all of them"
        )
        assert winners == {"claimer-A": (deck.session_id, _AUTHOR)}
        assert deck.row().spec_dirty_claimed_at == now, (
            "the take-over did not stamp the new lease with the claiming "
            "instant, so the TTL is measured from the dead worker's claim"
        )


# ---------------------------------------------------------------------------
# The other half of the race: mark_dirty's unlocked read-modify-write
# ---------------------------------------------------------------------------


class TestMarkDirtyRacingTheClaim:
    """``mark_dirty`` decides whether to coalesce from a read it does not hold.

    ``spec_sync``'s stated rule (module docstring): "A marker that has already
    been CLAIMED by a sweeper starts a *new* window, because the in-flight review
    cannot cover an edit made after it began."  ``mark_dirty`` implements that by
    reading ``spec_dirty_claimed_at``, deciding ``coalesced``, and only then
    writing — with no lock across the two.  A claim that commits inside that gap
    is invisible to the decision, so the edit coalesces into a window that has
    ALREADY been claimed, ``clear_marker``'s re-dirty rule
    (``spec_dirty_at > spec_dirty_claimed_at``) does not fire, and the finishing
    review clears the marker the human's edit had just set.

    XFAIL, STRICT, ON PURPOSE
    -------------------------
    This is a measured live defect in ``mark_dirty``, not a defect in the test.
    Reproduced on PostgreSQL 14.20 with this harness: the claim lands between the
    read and the write, and ``spec_dirty_at`` stays BEHIND
    ``spec_dirty_claimed_at``.  Fixing it means taking a row lock on a human's
    request path (``SELECT ... FOR UPDATE``, or a conditional UPDATE in the shape
    ``claim_due_marker`` already uses), which is a production change with its own
    design question and is deliberately not made here.

    ``strict=True`` so the record retires itself: the day ``mark_dirty`` takes
    that lock this test XPASSes, which strict xfail reports as a FAILURE, and
    whoever fixed it is told to delete the marker rather than leave a
    permanently-lying xfail behind.

    The cost of the defect is bounded — one skipped re-description of one deck —
    which is why it is recorded rather than treated as a release blocker.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "measured defect: mark_dirty reads spec_dirty_claimed_at and decides "
            "whether to coalesce without holding a lock, so a claim committing in "
            "that gap makes the human's edit coalesce into an already-claimed "
            "window and the finishing review discards it"
        ),
    )
    def test_an_edit_racing_the_claim_is_not_swallowed_by_the_finishing_review(
        self, postgres_engine
    ):
        from src.services.spec_sync import mark_dirty
        import src.services.spec_sync as spec_sync

        factory = _make_factory(postgres_engine)
        deck = _seed_owner_deck(factory, session_id="pg-owner-sess-0003")
        now = datetime.utcnow()
        deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 60, base=now)

        read_done = threading.Event()
        claim_done = threading.Event()
        real_resolve = spec_sync._resolve_owner_deck

        def paused_resolve(db, session_id):
            """Hold mark_dirty between its read of the marker and its write."""
            out = real_resolve(db, session_id)
            # Force the lazy load so the columns are genuinely in this session's
            # snapshot before the pause; otherwise the read happens AFTER the
            # claim and there is no race to observe.
            _ = out[1].spec_dirty_at, out[1].spec_dirty_claimed_at
            read_done.set()
            assert claim_done.wait(timeout=_WAIT_SECONDS), (
                "the claim never completed; nothing here is evidence about the race"
            )
            return out

        marked: Dict[str, Any] = {}

        def editor() -> None:
            with patch.object(spec_sync, "_resolve_owner_deck", paused_resolve):
                with _patched(factory):
                    marked["result"] = mark_dirty(deck.session_id, "second@example.com")

        thread = threading.Thread(target=editor, name="human-editor")
        thread.start()
        assert read_done.wait(timeout=_WAIT_SECONDS), (
            "mark_dirty never reached its pause, so its read never overlapped "
            "the claim and this test proves nothing"
        )

        with _patched(factory):
            claimed = claim_due_marker(now)
        claim_done.set()
        thread.join(timeout=_WAIT_SECONDS * 2)

        # Both halves of the race must actually have happened, or the ordering
        # assertion below is vacuous.
        assert claimed is not None, "the sweeper did not claim the marker"
        assert marked.get("result") is True, (
            f"mark_dirty did not report a write: {marked!r}"
        )
        row = deck.row()
        assert row.spec_dirty_by == "second@example.com", (
            "mark_dirty's write never landed, so the timestamps below say nothing "
            f"about coalescing: spec_dirty_by is {row.spec_dirty_by!r}"
        )
        assert row.spec_dirty_claimed_at is not None, "no lease was recorded"

        assert row.spec_dirty_at > row.spec_dirty_claimed_at, (
            f"spec_dirty_at ({row.spec_dirty_at}) is not after "
            f"spec_dirty_claimed_at ({row.spec_dirty_claimed_at}). The human edit "
            "coalesced into a window the sweeper had already claimed, so "
            "clear_marker's re-dirty rule will not preserve it and the review "
            "now finishing will clear a marker it never covered."
        )

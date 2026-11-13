"""Task 6: orphaned generations, restart recovery, restore retries, and the
restore-transaction hardening of PLAN-CORRECTIONS C11/C13.

The contract:

* ``generation_rollback.recover_orphaned_generations(now=None) -> int`` rolls back
  (``error``, ``"Generation interrupted"``, ``refuse_on_foreign_change=False``)
  every LIVE request with a snapshot in ``active`` / ``sealed`` whose ACTOR
  session's lock is no longer its own (``processing_request_id IS DISTINCT FROM
  request_id``, NULL-safe) or is older than ``ORPHAN_AFTER_SECONDS`` (180 s: three
  missed 60 s refreshes).  An active snapshot is restored; a sealed one keeps the
  finished deck (``SEALED_KEPT``).
* It then retries every ``restore_failed`` snapshot, skipping step 1's liveness
  claim (the request is already terminal) but RE-RUNNING the foreign-change check
  (C11): a foreign change keeps the deck (``kept_foreign_change``).  Each retry
  claims its snapshot inside the restore's own transaction, so a retry that fails
  again changes nothing, and two sweeps never restore twice.  On success:
  ``rollback_outcome='rolled_back'``, the snapshot deleted, the lock released.
* ``job_queue.recover_stuck_requests`` (startup) runs the orphan sweep FIRST;
  then a stuck request with a snapshot goes through ``roll_back_generation``
  rather than the bare flip to ``error``; its lock release is matched on
  ``processing_request_id``; a monolith request keeps today's behaviour.
* C13 at submit: a ``discard_generation_snapshot`` that raises ends the request
  (``fail_chat_request``), so no active snapshot is left on a ``pending`` request
  for the orphan sweep to roll back; and the ``keep_lock`` path (an Enter whose
  rollback's restore failed) answers 500 and keeps the deck locked.
* C11: a mutation event with a NULL actor (its session was deleted) after the
  watermark is somebody else's change.

The concurrency halves of C11/C13 (a seal racing a failing restore, a
contributor's Enter queued on the deck row during one, two retries at once) need
real row locks and are in ``tests/integration/test_generation_rollback_postgres.py``.

How the tests are built
-----------------------
The Task 4 harness (``tests/unit/test_generation_rollback.py``): a file-backed
SQLite database behind every ``get_db_session``, every turn write made by the real
writers under the turn's request id, and whole-database comparisons.  A crashed
process is simulated by what it leaves in the database: a live request, its
snapshot, and a lock that is no longer refreshed (``processing_started_at`` aged)
or no longer its own.  The submit tests use the Task 5 route harness
(``api``: ``TestClient(app)`` over the same kind of database, ``enqueue_job``
recorded).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import pytest
from sqlalchemy import create_engine, delete, select, update

import src.database.models  # noqa: F401 -- registers every ORM model on Base
from src.api.services import job_queue
from src.api.services.session_manager import (
    SESSION_LOCK_TIMEOUT_SECONDS,
    GenerationRefusedError,
    SessionManager,
    get_session_manager,
)
from src.core.database import Base, _run_migrations, get_db_session
from src.database.models.session import (
    ChatRequest,
    SessionMessage,
    SharedDeckMutationEvent,
    UserSession,
)
from src.services import generation_rollback
from src.services.generation_fence import TurnFencedError
from src.services.generation_rollback import RollbackResult
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from tests.integration.test_generation_stop_routes import (  # noqa: F401 -- `api` is a fixture
    INTERNAL_ERROR,
    LEGACY_LOCKED_DETAIL,
    Api,
    _newest_request,
    api,
)
from tests.unit.test_generation_rollback import (
    OWNER,
    RESTORE_PENDING,
    SLIDES_BEFORE,
    RollbackEnv,
    _assert_decks_restored,
    _assert_events,
    _assert_lock,
    _assert_request,
    _assert_rolled_back_to_enter,
    _assert_sessions_equal,
    _assert_tables_equal,
    _expected_restore_event,
    _messages_tagged,
    _one,
    _slide_inserts_fail,
    _without,
    build_env,
    edit_turn,
    first_generation_turn,
    foreign_edit,
    in_turn,
    press_enter,
    roll_back,
    seed_earlier_turn,
)
from tests.unit.test_job_queue_rollback import JobEnv, _monolith_request

#: The orphan sweep's error text (the brief, exact).
INTERRUPTED = "Generation interrupted"
#: ``recover_stuck_requests``'s existing error text (exact).
CRASH_RECOVERY = "Request timed out (worker crash recovery)"

#: (terminal_status, error_message, refuse_on_foreign_change): a stop and a failure.
STOP_AND_FAILURE = [
    pytest.param("cancelled", None, True, id="stop"),
    pytest.param("error", "Model call failed: 403", False, id="failure"),
]


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch, tmp_path) -> Iterator[RollbackEnv]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/recovery.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    try:
        yield build_env(engine, monkeypatch)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


def recover(now: Optional[datetime] = None) -> int:
    """``generation_rollback.recover_orphaned_generations``, looked up at call time."""
    module = importlib.import_module("src.services.generation_rollback")
    if now is None:
        return module.recover_orphaned_generations()
    return module.recover_orphaned_generations(now=now)


def set_lock(session_id: str, **values: Any) -> None:
    """Write *session_id*'s lock columns directly: what a dead process leaves."""
    with get_db_session() as db:
        db.execute(
            update(UserSession)
            .where(UserSession.session_id == session_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )


def age_lock(session_id: str, seconds: float) -> None:
    set_lock(session_id, processing_started_at=datetime.utcnow() - timedelta(seconds=seconds))


def age_request(request_id: str, seconds: float) -> None:
    with get_db_session() as db:
        db.execute(
            update(ChatRequest)
            .where(ChatRequest.request_id == request_id)
            .values(created_at=datetime.utcnow() - timedelta(seconds=seconds))
            .execution_options(synchronize_session=False)
        )


def released(tables: Dict[str, List[Dict[str, Any]]], *session_ids: str) -> Dict[str, Any]:
    """*tables* with the named sessions' locks released (for whole-table comparison)."""
    rows = [
        dict(r, is_processing=False, processing_started_at=None, processing_request_id=None)
        if r["session_id"] in session_ids
        else r
        for r in tables["user_sessions"]
    ]
    return dict(tables, user_sessions=rows)


def _lock(row: Dict[str, Any]) -> tuple:
    return (row["is_processing"], row["processing_started_at"], row["processing_request_id"])


def fail_restore(env: RollbackEnv, rid: str, terminal_status: str, error_message, refuse) -> None:
    """End *rid* with a restore that fails part-way (``restore_failed``)."""
    with _slide_inserts_fail(env.engine) as attempted:
        result = roll_back(rid, terminal_status, error_message, refuse)
    assert attempted, "the restore never inserted a slide row; the injected failure proves nothing"
    assert result == RollbackResult.RESTORE_FAILED
    assert [s["state"] for s in env.snapshot_rows(rid)] == ["restore_failed"]


def test_orphan_threshold_is_three_missed_refreshes():
    assert generation_rollback.ORPHAN_AFTER_SECONDS == 180
    assert generation_rollback.ORPHAN_AFTER_SECONDS == 3 * job_queue.TIMEOUT_SWEEP_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# Orphans: live generations whose job is gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state, kind",
    [("running", "edit"), ("running", "first_generation"), ("pending", None)],
    ids=["running-edit", "running-first-generation", "pending"],
)
def test_orphan_with_stale_lock_rolled_back(env, state, kind):
    """The process running (or holding, queued) this turn died: its lock is still
    the turn's own but has not been refreshed for 400 s.  The sweep rolls the turn
    back to Enter, ends it ``error`` / ``Generation interrupted`` and frees the deck."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    if kind == "edit":
        seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid, start=state == "running")
    if kind == "edit":
        edit_turn(env, sid, sid, rid)
    elif kind == "first_generation":
        first_generation_turn(env, sid, rid)
    age_lock(sid, 400)
    at_turn_end = env.tables()
    assert _lock(_one(at_turn_end["user_sessions"], session_id=sid))[2] == rid

    handled = recover()

    assert handled == 1
    after = env.tables()
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=kind == "edit",
    )
    assert env.snapshot_rows(rid) == []
    _assert_lock(env, sid, held_by=None)
    with in_turn(rid):
        with pytest.raises(TurnFencedError):
            get_session_manager().add_message(
                sid, "assistant", "MK-LATE", message_type="chat", request_id=rid
            )


@pytest.mark.parametrize("snapshot_state", ["active", "sealed"])
@pytest.mark.parametrize("actor", ["owner", "contributor"])
def test_live_job_with_fresh_lock_not_touched(env, actor, snapshot_state):
    """A turn whose job is alive: its ACTOR session's lock is its own and was
    refreshed 30 s ago.  The sweep changes nothing -- whether the snapshot is
    active or already sealed (between the seal and the completion), and on a
    contributor's turn, whose owner session holds no lock at all."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    actor_sid = env.contributor(owner) if actor == "contributor" else owner
    rid = press_enter(env, actor_sid)
    edit_turn(env, actor_sid, owner, rid)
    if snapshot_state == "sealed":
        assert generation_rollback.seal_generation(rid) is True
    age_lock(actor_sid, 30)
    before = env.tables()
    if actor == "contributor":
        assert _lock(env.session_row(owner)) == (False, None, None)

    assert recover() == 0

    _assert_tables_equal(before, env.tables())


def test_fresh_generation_orphaned_by_restart_rolled_back_after_180s(env):
    """After a restart nothing refreshes the lock, which is still the turn's own.
    At 170 s it is left alone (the job may just be between refreshes); at 181 s
    (three missed 60 s refreshes) it is rolled back."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    age_lock(sid, 170)
    at_170 = env.tables()

    assert recover() == 0
    _assert_tables_equal(at_170, env.tables())

    age_lock(sid, 181)
    at_turn_end = env.tables()

    assert recover() == 1

    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=True,
    )
    _assert_lock(env, sid, held_by=None)


def test_orphan_age_is_judged_against_now(env):
    """``now`` is the sweep's clock: the same lock is fresh at its own time and an
    orphan 181 s later."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    started = env.session_row(sid)["processing_started_at"]
    at_turn_end = env.tables()

    assert recover(now=started + timedelta(seconds=10)) == 0
    _assert_tables_equal(at_turn_end, env.tables())

    assert recover(now=started + timedelta(seconds=181)) == 1
    row = env.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "error",
        INTERRUPTED,
        "rolled_back",
    )


@pytest.mark.parametrize(
    "lock", ["released", "held-unbound"], ids=["released-lock", "fresh-unbound-lock"]
)
def test_null_processing_request_id_counts_as_orphan(env, lock):
    """``processing_request_id`` is NULL: the lock was released (a startup flip, a
    crash between bind and run) or taken fresh by an Enter not bound yet.  NULL is
    distinct from the request id (a plain ``!=`` would match nothing), so the turn
    is an orphan and is rolled back; a fresh unbound lock is not its own, so it is
    left exactly as it is."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    fresh = datetime.utcnow() - timedelta(seconds=5)
    if lock == "released":
        set_lock(sid, is_processing=False, processing_started_at=None, processing_request_id=None)
    else:
        set_lock(sid, is_processing=True, processing_started_at=fresh, processing_request_id=None)
    at_turn_end = env.tables()

    assert recover() == 1

    after = env.tables()
    expected_lock = (False, None, None) if lock == "released" else (True, fresh, None)
    assert _lock(env.session_row(sid)) == expected_lock
    # Everything else exactly as a rollback to Enter leaves it.
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        released(after, sid),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=True,
    )


def test_lock_taken_by_a_newer_request_counts_as_orphan(env):
    """The dead turn's lock went stale and the sender's next request took it (on
    another process).  The dead turn is an orphan however fresh that lock is, and
    rolling it back must not release the newer request's lock."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    fresh = datetime.utcnow() - timedelta(seconds=5)
    set_lock(
        sid, is_processing=True, processing_started_at=fresh, processing_request_id="req-newer"
    )
    at_turn_end = env.tables()

    assert recover() == 1

    after = env.tables()
    assert _lock(env.session_row(sid)) == (True, fresh, "req-newer")
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        released(after, sid),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=True,
    )


def test_orphan_with_foreign_change_keeps_the_deck(env):
    """An orphan is a failure, not a stop: another editor's change since Enter
    keeps the deck as it stands (``kept_foreign_change``), ends the request and
    frees the deck.  A refused rollback would leave the orphan live for ever."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    rid = press_enter(env, owner)
    edit_turn(env, owner, owner, rid)
    foreign_edit(env, contrib)
    age_lock(owner, 400)
    before = env.tables()

    assert recover() == 1

    after = env.tables()
    _assert_tables_equal(
        before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    _assert_sessions_equal(released(before, owner), after, touched=(owner,))
    _assert_request(
        env.request_row(rid),
        _one(before["chat_requests"], request_id=rid),
        status="error",
        error_message=INTERRUPTED,
        rollback_outcome="kept_foreign_change",
        completed=True,
    )
    assert after["generation_snapshots"] == []
    assert env.slide_htmls(owner)[0] != SLIDES_BEFORE[0]


def test_sealed_orphan_marked_error_and_deck_kept(env):
    """The turn had sealed (its deck is finished) when its process died, before it
    completed.  The finished deck, its messages and checkpoints stay; the request
    ends ``error`` / ``Generation interrupted`` with no rollback outcome, the
    snapshot goes and the deck is freed."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    assert generation_rollback.seal_generation(rid) is True
    age_lock(sid, 400)
    before = env.tables()

    assert recover() == 1

    after = env.tables()
    _assert_tables_equal(
        before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    _assert_sessions_equal(released(before, sid), after, touched=(sid,))
    _assert_request(
        env.request_row(rid),
        _one(before["chat_requests"], request_id=rid),
        status="error",
        error_message=INTERRUPTED,
        rollback_outcome=None,
        completed=True,
    )
    assert [r for r in after["chat_requests"] if r["request_id"] != rid] == [
        r for r in before["chat_requests"] if r["request_id"] != rid
    ]
    assert after["generation_snapshots"] == []


def test_finished_requests_and_their_snapshots_are_not_orphans(env):
    """Only LIVE requests are orphans.  A completed request, and a terminal one
    whose snapshot was left behind (a discard that failed at submit, C13), are not
    touched however stale their session's lock."""
    sm = get_session_manager()
    done_sid = env.new_session(created_by=OWNER, title="MK-DONE")
    done = press_enter(env, done_sid)
    first_generation_turn(env, done_sid, done)
    assert generation_rollback.seal_generation(done) is True
    assert sm.complete_chat_request(done, {"slides": None}) is True
    age_lock(done_sid, 400)

    left_sid = env.new_session(created_by=OWNER, title="MK-LEFT")
    left = press_enter(env, left_sid)
    first_generation_turn(env, left_sid, left)
    assert sm.fail_chat_request(left, "MK the discard failed") is True
    assert [s["state"] for s in env.snapshot_rows(left)] == ["active"]
    age_lock(left_sid, 400)
    before = env.tables()

    assert recover() == 0

    _assert_tables_equal(before, env.tables())


# ---------------------------------------------------------------------------
# restore_failed: retried until it succeeds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "terminal_status, error_message, refuse, actor",
    [
        pytest.param("cancelled", None, True, "owner", id="stop-owner"),
        pytest.param("error", "Model call failed: 403", False, "contributor", id="failure-contrib"),
    ],
)
def test_restore_failed_retried_and_lock_released(
    env, terminal_status, error_message, refuse, actor
):
    """A restore failed (the deck stays locked to its sender, the snapshot is
    ``restore_failed``).  The sweep retries it -- the request is already terminal,
    so no liveness claim -- and the deck goes back exactly as at Enter, the
    request's outcome becomes ``rolled_back``, the snapshot goes and the ACTOR's
    lock is released.  A new Enter on the deck is then accepted."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    actor_sid = env.contributor(owner) if actor == "contributor" else owner
    before = env.tables()
    rid = press_enter(env, actor_sid)
    edit_turn(env, actor_sid, owner, rid)
    at_turn_end = env.tables()
    fail_restore(env, rid, terminal_status, error_message, refuse)
    _assert_lock(env, actor_sid, held_by=rid)
    assert generation_rollback.has_pending_restore(owner) is True

    assert recover() == 1

    after = env.tables()
    row = env.request_row(rid)
    # The request was ended by the failed restore; the retry keeps its status
    # (error_message is left to the implementation: the brief names only the outcome).
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=actor_sid,
        owner_sid=owner,
        terminal_status=terminal_status,
        error_message=row["error_message"],
        deck_existed=True,
    )
    assert env.slide_htmls(owner) == SLIDES_BEFORE
    assert env.snapshot_rows(rid) == []
    _assert_lock(env, actor_sid, held_by=None)
    assert generation_rollback.has_pending_restore(owner) is False
    # The deck takes a new turn again.
    sm = get_session_manager()
    assert sm.acquire_session_lock(owner)
    rid2 = sm.create_chat_request(owner)
    sm.bind_session_lock(owner, rid2)
    sm.begin_generation(owner, rid2)
    assert [s["state"] for s in env.snapshot_rows(rid2)] == ["active"]


def test_restore_failed_retry_keeps_foreign_change(env, caplog):
    """C11.  The restore failed, and then someone else's edit committed (the
    original restore may have lost a deadlock to it).  The retry re-runs the
    foreign-change check: the deck is kept as it stands, the outcome becomes
    ``kept_foreign_change``, the snapshot goes and the lock is released."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    rid = press_enter(env, owner)
    edit_turn(env, owner, owner, rid)
    fail_restore(env, rid, "error", "Model call failed: 403", False)
    foreign_edit(env, contrib)
    before = env.tables()

    assert recover() == 1

    after = env.tables()
    _assert_tables_equal(
        before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    _assert_sessions_equal(released(before, owner), after, touched=(owner,))
    row = env.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("error", "kept_foreign_change")
    assert _without(row, ("error_message", "rollback_outcome", "completed_at")) == _without(
        _one(before["chat_requests"], request_id=rid),
        ("error_message", "rollback_outcome", "completed_at"),
    )
    assert after["generation_snapshots"] == []
    assert generation_rollback.has_pending_restore(owner) is False


def test_restore_retry_that_fails_again_changes_nothing_and_is_retried_later(env):
    """The retry's own restore fails too.  Its transaction (the claim included)
    rolls back whole: every table exactly as before the retry, the deck still
    locked, the snapshot still ``restore_failed``.  The next sweep succeeds."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    at_turn_end = env.tables()
    fail_restore(env, rid, "error", "Model call failed: 403", False)
    before_retry = env.tables()

    with _slide_inserts_fail(env.engine) as attempted:
        recover()

    assert attempted, "the retry never re-inserted a slide row; the test proves nothing"
    _assert_tables_equal(before_retry, env.tables())

    assert recover() == 1
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=env.request_row(rid)["error_message"],
        deck_existed=True,
    )


def test_second_sweep_after_a_successful_retry_changes_nothing(env):
    """Exactly one restore: a later sweep finds nothing to retry (no second
    ``restore_version`` event, no second version bump)."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    fail_restore(env, rid, "cancelled", None, True)
    assert recover() == 1
    after_first = env.tables()

    assert recover() == 0

    _assert_tables_equal(after_first, env.tables())


# ---------------------------------------------------------------------------
# C11: a NULL actor is somebody else
# ---------------------------------------------------------------------------


def _null_the_actor_of_the_newest_event(owner_pk: int) -> None:
    """What deleting the editor's session does to its evidence on PostgreSQL
    (``actor_session_id`` ``ON DELETE SET NULL``); SQLite enforces no foreign key,
    so the effect is applied directly."""
    table = SharedDeckMutationEvent.__table__
    with get_db_session() as db:
        newest = db.execute(
            select(table.c.id)
            .where(table.c.root_session_id == owner_pk)
            .order_by(table.c.id.desc())
            .limit(1)
        ).scalar_one()
        db.execute(update(table).where(table.c.id == newest).values(actor_session_id=None))


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_null_actor_event_after_watermark_is_a_foreign_change(
    env, terminal_status, error_message, refuse
):
    """C11.  Someone edited the deck mid-turn and their session was then deleted,
    so the event's actor is NULL.  That is still somebody else's work: a stop is
    refused (nothing changes) and a failure keeps the deck as it stands."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    rid = press_enter(env, owner)
    edit_turn(env, owner, owner, rid)
    foreign_edit(env, contrib)
    _null_the_actor_of_the_newest_event(env.pk(owner))
    events = env.tables()["shared_deck_mutation_event"]
    assert events[-1]["actor_session_id"] is None
    assert events[-1]["id"] > env.snapshot_rows(rid)[0]["mutation_watermark"]
    before = env.tables()

    result = roll_back(rid, terminal_status, error_message, refuse)

    after = env.tables()
    if terminal_status == "cancelled":
        assert result == RollbackResult.REFUSED_FOREIGN_CHANGE
        _assert_tables_equal(before, after)
    else:
        assert result == RollbackResult.KEPT_FOREIGN_CHANGE
        _assert_tables_equal(
            before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
        )
        _assert_sessions_equal(released(before, owner), after, touched=(owner,))
        assert env.request_row(rid)["rollback_outcome"] == "kept_foreign_change"


# ---------------------------------------------------------------------------
# Startup recovery (recover_stuck_requests)
# ---------------------------------------------------------------------------


def run_startup_recovery() -> int:
    return asyncio.run(job_queue.recover_stuck_requests())


def test_startup_recovery_restores_old_running_request_with_snapshot(env):
    """A ``running`` Agent turn created 1300 s ago, its lock still its own and
    refreshed 30 s before the crash (so not yet an orphan by the 180 s rule).  The
    stuck-request pass restores it from its snapshot -- not just a flip to
    ``error`` that leaves the half-built deck."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    age_request(rid, 1300)
    age_lock(sid, 30)
    at_turn_end = env.tables()

    assert run_startup_recovery() >= 1

    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=CRASH_RECOVERY,
        deck_existed=True,
    )
    assert env.snapshot_rows(rid) == []
    _assert_lock(env, sid, held_by=None)


def test_startup_recovery_runs_the_orphan_sweep_first(env):
    """The same old turn, but its lock is stale: the orphan sweep runs first and
    rolls it back as interrupted, before the stuck-request pass sees it."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    age_request(rid, 1300)
    age_lock(sid, 400)
    at_turn_end = env.tables()

    run_startup_recovery()

    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=True,
    )


def test_startup_recovery_rolls_back_a_young_orphan(env):
    """A turn only 400 s old (under the 1200 s stuck-request limit) whose lock has
    not been refreshed for 200 s: startup recovery rolls it back too, rather than
    leaving the deck locked to a dead job."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    age_request(rid, 400)
    age_lock(sid, 200)
    at_turn_end = env.tables()

    run_startup_recovery()

    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=True,
    )
    _assert_lock(env, sid, held_by=None)


def _forbid_rollback(monkeypatch) -> List[str]:
    used: List[str] = []

    def forbidden(*args, **kwargs):
        used.append("roll_back_generation")
        raise AssertionError("a monolith request was rolled back")

    monkeypatch.setattr(generation_rollback, "roll_back_generation", forbidden)
    monkeypatch.setattr(job_queue, "roll_back_generation", forbidden, raising=False)
    return used


@pytest.mark.parametrize("shape", ["explicit", "mcp"], ids=["legacy-async", "mcp"])
def test_startup_recovery_leaves_monolith_as_today(env, monkeypatch, shape):
    """Guard: a stuck monolith request (a Legacy deck's async turn, whose lock is
    bound to it; or an MCP job, whose lock is never bound) is flipped to ``error``
    with today's text and its lock freed; nothing is rolled back and nothing else
    changes.  (A matched release may also clear the Legacy turn's leftover
    ``processing_request_id``, which today stays behind.)"""
    sid, rid = _monolith_request(JobEnv(env, None), shape)
    sm = get_session_manager()
    sm.update_chat_request_status(rid, "running")
    sm.add_message(sid, "assistant", "MK-LEGACY partial reply", message_type="chat", request_id=rid)
    age_request(rid, 1300)
    age_lock(sid, 1300)
    used = _forbid_rollback(monkeypatch)
    before = env.tables()

    assert run_startup_recovery() == 1

    after = env.tables()
    assert used == []
    _assert_tables_equal(before, after, exclude=("chat_requests", "user_sessions"))
    _assert_request(
        env.request_row(rid),
        _one(before["chat_requests"], request_id=rid),
        status="error",
        error_message=CRASH_RECOVERY,
        rollback_outcome=None,
        completed=True,
    )
    lock = _lock(env.session_row(sid))
    assert lock[:2] == (False, None), "the stuck monolith request's lock was not freed"
    assert lock[2] in ({rid, None} if shape == "explicit" else {None})
    _assert_sessions_equal(
        before,
        {
            **after,
            "user_sessions": [
                dict(
                    r,
                    is_processing=_one(before["user_sessions"], session_id=sid)["is_processing"],
                    processing_started_at=_one(before["user_sessions"], session_id=sid)[
                        "processing_started_at"
                    ],
                    processing_request_id=_one(before["user_sessions"], session_id=sid)[
                        "processing_request_id"
                    ],
                )
                if r["session_id"] == sid
                else r
                for r in after["user_sessions"]
            ],
        },
        touched=(sid,),
    )


def test_startup_recovery_does_not_release_a_newer_requests_lock(env):
    """A stuck Legacy request's lock went stale and the sender's next request took
    it (it is running on another process).  Recovery flips the stuck request to
    ``error`` as today, but must not free the newer request's lock."""
    sid, rid_old = _monolith_request(JobEnv(env, None), "explicit")
    sm = get_session_manager()
    sm.update_chat_request_status(rid_old, "running")
    age_request(rid_old, 1300)
    age_lock(sid, 400)
    assert sm.acquire_session_lock(sid), "the stale lock could not be taken over"
    rid_new = sm.create_chat_request(sid, OWNER)
    sm.bind_session_lock(sid, rid_new)
    held = _lock(env.session_row(sid))
    assert held[0] is True and held[2] == rid_new

    run_startup_recovery()

    assert env.request_row(rid_old)["status"] == "error"
    assert _lock(env.session_row(sid)) == held, "recovery freed the newer request's lock"
    assert env.request_row(rid_new)["status"] == "pending"


# ---------------------------------------------------------------------------
# C13 at submit (the Task 5 route harness)
# ---------------------------------------------------------------------------


def _contributor_locks_legacy_first(api: Api, monkeypatch, sid: str) -> Dict[str, Any]:
    """Between this Enter's snapshot and its user message, a contributor's first
    message locks the shared deck to Legacy (the race of the Task 5 suite)."""
    contributor = api.rb.contributor(sid)
    at: Dict[str, Any] = {}
    real_add = SessionManager.add_user_message

    def racing_add(self, session_id, content, **kwargs):
        if session_id == sid and "foreign" not in at:
            at["snapshots"] = api.rb.snapshot_rows(kwargs["request_id"])
            real_add(
                self,
                contributor,
                "MK-FOREIGN first message",
                message_type="user_query",
                requested_deck_mode="legacy",
            )
            at["foreign"] = api.tables()
        return real_add(self, session_id, content, **kwargs)

    monkeypatch.setattr(SessionManager, "add_user_message", racing_add)
    return at


@pytest.mark.parametrize("branch", ["engine_mismatch", "deck_mode_locked"])
def test_failed_discard_at_submit_ends_the_request(api, monkeypatch, branch):
    """C13.  The submit drops its snapshot without restoring (the engine changed
    under the message, or another first message locked the mode, C9) -- and that
    discard itself raises.  The request must be ended (``error``), so no active
    snapshot is left on a ``pending`` request: the orphan sweep would otherwise
    "roll it back" and revert the other person's deck-mode lock."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    at = _contributor_locks_legacy_first(api, monkeypatch, sid)
    discards: List[str] = []

    def failing_discard(self, request_id):
        discards.append(request_id)
        raise RuntimeError("MK-INJECTED the discard failed")

    monkeypatch.setattr(SessionManager, "discard_generation_snapshot", failing_discard)

    resp = api.submit(sid, deck_mode="agent" if branch == "deck_mode_locked" else None)

    rid = _newest_request(api, sid)
    assert [s["request_id"] for s in at["snapshots"]] == [rid], "no snapshot was taken"
    assert discards == [rid], "the discard branch was never reached"
    answer = (resp.status_code, resp.json())
    if branch == "engine_mismatch":
        assert answer == (500, {"detail": INTERNAL_ERROR})
    else:
        assert answer in [
            (409, {"detail": LEGACY_LOCKED_DETAIL}),
            (500, {"detail": INTERNAL_ERROR}),
        ]
    api.enqueued.assert_not_awaited()
    row = api.rb.request_row(rid)
    assert row["status"] == "error", (
        f"the request was left {row['status']!r} with its snapshot after the discard failed"
    )
    assert row["rollback_outcome"] is None and row["completed_at"] is not None
    assert _without(row, ("status", "error_message", "completed_at")) == _without(
        _one(at["foreign"]["chat_requests"], request_id=rid),
        ("status", "error_message", "completed_at"),
    )
    _assert_lock(api.rb, sid, held_by=None)
    assert api.rb.session_row(sid)["deck_mode"] == "legacy"
    # The orphan sweep leaves the finished request, and the other person's lock, alone.
    before_sweep = api.tables()
    assert recover() == 0
    _assert_tables_equal(before_sweep, api.tables())


def test_enqueue_failure_whose_restore_fails_keeps_the_lock(api):
    """C13 (the submit's ``keep_lock`` path, chat.py ~1037).  An edit's Enter saved
    its snapshot and message, then the enqueue failed, and the rollback's restore
    failed too.  The answer is a 500, the deck stays locked to this request, and
    the request reads ``(error, <restore-pending copy>, restore_failed)``."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    at: Dict[str, Any] = {}

    with contextlib.ExitStack() as stack:

        async def fail_enqueue(request_id, payload):
            at["enter"] = api.tables()
            # From here on the restore cannot re-insert the slide rows.
            at["attempted"] = stack.enter_context(_slide_inserts_fail(api.rb.engine))
            raise RuntimeError("MK-INJECTED the queue is gone")

        api.enqueued.side_effect = fail_enqueue
        resp = api.submit(sid)

    assert (resp.status_code, resp.json()) == (500, {"detail": INTERNAL_ERROR})
    assert "enter" in at, "the enqueue never ran"
    assert at["attempted"], "the rollback never re-inserted a slide row; the test proves nothing"
    rid = _newest_request(api, sid)
    entered, after = at["enter"], api.tables()
    row = _one(after["chat_requests"], request_id=rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "error",
        RESTORE_PENDING,
        "restore_failed",
    )
    _assert_request(
        row,
        _one(entered["chat_requests"], request_id=rid),
        status="error",
        error_message=RESTORE_PENDING,
        rollback_outcome="restore_failed",
        completed=None,
    )
    _assert_lock(api.rb, sid, held_by=rid)
    assert [s["state"] for s in api.rb.snapshot_rows(rid)] == ["restore_failed"]
    # The restore rolled back whole: nothing else moved since Enter.
    _assert_tables_equal(entered, after, exclude=("chat_requests", "generation_snapshots"))
    assert generation_rollback.has_pending_restore(sid) is True


def test_restore_failed_at_submit_is_retried_by_the_sweep(api):
    """The same failed submit, then the sweep: the Enter is undone (its user
    message gone, the deck as it was), the outcome becomes ``rolled_back`` and the
    deck is free again."""
    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    before = api.tables()
    at: Dict[str, Any] = {}

    with contextlib.ExitStack() as stack:

        async def fail_enqueue(request_id, payload):
            at["enter"] = api.tables()
            stack.enter_context(_slide_inserts_fail(api.rb.engine))
            raise RuntimeError("MK-INJECTED the queue is gone")

        api.enqueued.side_effect = fail_enqueue
        assert api.submit(sid).status_code == 500
    rid = _newest_request(api, sid)
    assert api.rb.request_row(rid)["rollback_outcome"] == "restore_failed"

    assert recover() == 1

    after = api.tables()
    entered = at["enter"]
    _assert_tables_equal(
        before,
        after,
        exclude=(
            "chat_requests",
            "user_sessions",
            "session_slide_decks",
            "shared_deck_mutation_event",
        ),
    )
    _assert_sessions_equal(before, after, touched=(sid,))
    deck_id = _one(before["session_slide_decks"], session_id=api.rb.pk(sid))["id"]
    enter_version = _one(entered["session_slide_decks"], session_id=api.rb.pk(sid))["version"]
    _assert_decks_restored(before, after, restored_deck_id=deck_id, version=enter_version + 1)
    _assert_events(
        entered,
        after,
        restore_event=_expected_restore_event(after, owner_sid=sid, actor_sid=sid),
    )
    assert _messages_tagged(after, rid) == []
    row = api.rb.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("error", "rolled_back")
    _assert_lock(api.rb, sid, held_by=None)
    assert generation_rollback.has_pending_restore(sid) is False


def test_generation_refused_restore_pending_maps_to_the_409_copy():
    """The refusal a queued Enter gets while a restore is pending (the Postgres
    test asserts the refusal itself) is answered with the restore-pending 409."""
    from src.api.routes import chat as chat_routes

    assert (
        chat_routes._GENERATION_REFUSED_DETAILS[GenerationRefusedError.RESTORE_PENDING]
        == RESTORE_PENDING
    )


# ===========================================================================
# Fix round 1
# ===========================================================================

#: Past the orphan threshold.
ORPHAN_AGE = 181


def _deck_accepts_a_new_enter(session_id: str) -> None:
    """An Agent Enter on *session_id*'s deck is accepted (no restore-pending 409)."""
    sm = get_session_manager()
    assert sm.acquire_session_lock(session_id)
    rid = sm.create_chat_request(session_id)
    sm.bind_session_lock(session_id, rid)
    sm.begin_generation(session_id, rid)
    table = generation_rollback.GenerationSnapshot.__table__
    with get_db_session() as db:
        states = list(db.execute(select(table.c.state).where(table.c.request_id == rid)).scalars())
    assert states == ["active"]


def _apply_postgres_delete_effects(session_pk: int) -> None:
    """What PostgreSQL's foreign keys do when a session row is deleted, and SQLite
    (no foreign-key enforcement here) does not: its requests and messages go
    (``ON DELETE CASCADE``) and its mutation evidence loses its actor
    (``actor_session_id ON DELETE SET NULL``)."""
    table = SharedDeckMutationEvent.__table__
    with get_db_session() as db:
        db.execute(delete(ChatRequest).where(ChatRequest.session_id == session_pk))
        db.execute(delete(SessionMessage).where(SessionMessage.session_id == session_pk))
        db.execute(
            update(table)
            .where(table.c.actor_session_id == session_pk)
            .values(actor_session_id=None)
        )


# --- 1. a failed restore whose session was deleted --------------------------


def test_failed_restore_of_a_deleted_deck_is_dropped(env, caplog):
    """The deck owner's session was deleted (on PostgreSQL its contributors and
    requests go with it) while its failed restore was pending.  Snapshots carry no
    foreign key, so the snapshot stayed.  The retry has nothing to restore: it
    drops the snapshot, without an error, and touches nothing else."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    fail_restore(env, rid, "error", "Model call failed: 403", False)
    get_session_manager().delete_session(sid)
    before = env.tables()
    assert [s["state"] for s in env.snapshot_rows(rid)] == ["restore_failed"]
    caplog.set_level(logging.ERROR)
    caplog.clear()

    assert recover() == 1

    after = env.tables()
    _assert_tables_equal(before, after, exclude=("generation_snapshots",))
    assert after["generation_snapshots"] == [
        r for r in before["generation_snapshots"] if r["request_id"] != rid
    ]
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], f"the retry of a deleted deck's restore logged errors: {errors}"
    assert recover() == 0
    _assert_tables_equal(after, env.tables())


def test_failed_restore_of_a_deleted_contributor_restores_the_owners_deck(env, caplog):
    """A contributor's turn on a shared deck failed and its restore failed; then the
    contributor's session was deleted (its evidence keeping its actor id, as on
    SQLite).  The deck stays the owner's: the retry restores the owner's deck and
    owner fields as at Enter (the contributor's own fields went with its session),
    records no restore evidence (there is no actor to attribute it to), settles
    the request and drops the snapshot.  It releases nothing.  The deck takes
    Agent Enters again -- not the restore-pending 409 for ever."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    before = env.tables()
    rid = press_enter(env, contrib)
    edit_turn(env, contrib, owner, rid)
    at_turn_end = env.tables()
    fail_restore(env, rid, "error", "Model call failed: 403", False)
    get_session_manager().delete_session(contrib)
    assert generation_rollback.has_pending_restore(owner) is True
    gone = env.tables()
    caplog.set_level(logging.ERROR)
    caplog.clear()

    assert recover() == 1

    after = env.tables()
    assert after["session_slides"] == before["session_slides"]
    deck_id = _one(before["session_slide_decks"], session_id=env.pk(owner))["id"]
    turn_version = _one(at_turn_end["session_slide_decks"], session_id=env.pk(owner))["version"]
    _assert_decks_restored(before, after, restored_deck_id=deck_id, version=turn_version + 1)
    owner_after = _one(after["user_sessions"], session_id=owner)
    assert _without(owner_after, ("last_activity",)) == _without(
        _one(before["user_sessions"], session_id=owner), ("last_activity",)
    )
    assert after["user_sessions"] == [
        owner_after if r["session_id"] == owner else r for r in gone["user_sessions"]
    ], "a session row other than the owner's changed"
    assert after["shared_deck_mutation_event"] == gone["shared_deck_mutation_event"]
    assert _messages_tagged(after, rid) == []
    row = _one(after["chat_requests"], request_id=rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "error",
        None,
        "rolled_back",
    )
    assert env.snapshot_rows(rid) == []
    assert generation_rollback.has_pending_restore(owner) is False
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], errors
    _deck_accepts_a_new_enter(owner)


def test_failed_restore_of_a_deleted_contributor_on_postgres_keeps_the_deck(env):
    """The same, with what PostgreSQL's foreign keys do on the delete: the
    contributor's request and messages are gone, and its mutation evidence has a
    NULL actor -- which is somebody else's change (C11).  The retry keeps the deck
    as it stands, drops the snapshot and frees the deck for new Enters."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    rid = press_enter(env, contrib)
    edit_turn(env, contrib, owner, rid)
    fail_restore(env, rid, "error", "Model call failed: 403", False)
    contrib_pk = env.pk(contrib)
    get_session_manager().delete_session(contrib)
    _apply_postgres_delete_effects(contrib_pk)
    assert generation_rollback.has_pending_restore(owner) is True
    gone = env.tables()

    assert recover() == 1

    after = env.tables()
    _assert_tables_equal(gone, after, exclude=("generation_snapshots",))
    assert after["generation_snapshots"] == [
        r for r in gone["generation_snapshots"] if r["request_id"] != rid
    ]
    assert generation_rollback.has_pending_restore(owner) is False
    _deck_accepts_a_new_enter(owner)


# --- 2. an Enter whose rollback could not run -------------------------------


def test_enter_whose_rollback_raises_keeps_the_deck_locked_until_the_sweep(api, monkeypatch):
    """The enqueue failed after the Enter committed its snapshot and user message,
    and the rollback itself raised (nothing recorded).  The request is still
    ``pending`` with an ``active`` snapshot, so the lock must stay bound to it: a
    quick re-send is refused, rather than starting a turn the orphan sweep would
    later "restore" the Enter under.  The sweep then rolls the Enter back once the
    lock has gone unrefreshed for 180 s, and frees the deck."""
    from src.api.routes import chat as chat_routes

    sid = api.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(api.rb, sid)
    before = api.tables()
    api.enqueued.side_effect = RuntimeError("MK-INJECTED the queue is gone")

    def rollback_raises(*args, **kwargs):
        raise RuntimeError("MK-INJECTED the rollback could not run")

    monkeypatch.setattr(chat_routes, "roll_back_generation", rollback_raises)

    resp = api.submit(sid)

    assert (resp.status_code, resp.json()) == (500, {"detail": INTERNAL_ERROR})
    rid = _newest_request(api, sid)
    row = api.rb.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("pending", None)
    assert [s["state"] for s in api.rb.snapshot_rows(rid)] == ["active"]
    _assert_lock(api.rb, sid, held_by=rid)

    resend = api.submit(sid, "MK-USER again")
    assert (resend.status_code, resend.json()) == (
        409,
        {"detail": "Session is already processing a request"},
    )
    assert _newest_request(api, sid) == rid

    monkeypatch.setattr(
        chat_routes, "roll_back_generation", generation_rollback.roll_back_generation
    )
    age_lock(sid, ORPHAN_AGE)
    entered = api.tables()

    assert recover() == 1

    after = api.tables()
    _assert_tables_equal(
        before,
        after,
        exclude=(
            "chat_requests",
            "user_sessions",
            "session_slide_decks",
            "shared_deck_mutation_event",
        ),
    )
    _assert_sessions_equal(before, after, touched=(sid,))
    deck_id = _one(before["session_slide_decks"], session_id=api.rb.pk(sid))["id"]
    enter_version = _one(entered["session_slide_decks"], session_id=api.rb.pk(sid))["version"]
    _assert_decks_restored(before, after, restored_deck_id=deck_id, version=enter_version + 1)
    _assert_events(
        entered,
        after,
        restore_event=_expected_restore_event(after, owner_sid=sid, actor_sid=sid),
    )
    assert _messages_tagged(after, rid) == []
    row = api.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "error",
        INTERRUPTED,
        "rolled_back",
    )
    _assert_lock(api.rb, sid, held_by=None)


# --- 3. never restore over a newer live turn ---------------------------------


@pytest.mark.parametrize("newer_state", ["running", "pending"])
def test_orphan_never_restores_over_a_newer_live_turn(env, caplog, newer_state):
    """The turn's process died, its lock went stale, and the sender's next Enter
    took the lock: that newer turn is live and started from the deck the dead turn
    left.  Restoring the dead turn's Enter would wipe the newer turn's starting
    point (and anything it has written) with no way back.  The sweep ends the dead
    turn ``error`` / ``Generation interrupted`` with no rollback outcome, drops its
    snapshot, logs at ERROR, and changes nothing else -- the deck, the newer turn
    and its lock stay exactly as they are."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid1 = press_enter(env, sid)
    edit_turn(env, sid, sid, rid1)
    age_lock(sid, SESSION_LOCK_TIMEOUT_SECONDS + 10)
    rid2 = press_enter(env, sid, "MK-USER second try", start=newer_state == "running")
    before = env.tables()
    assert _lock(_one(before["user_sessions"], session_id=sid))[2] == rid2
    caplog.set_level(logging.ERROR)
    caplog.clear()

    assert recover() == 1

    after = env.tables()
    _assert_tables_equal(before, after, exclude=("chat_requests", "generation_snapshots"))
    _assert_request(
        env.request_row(rid1),
        _one(before["chat_requests"], request_id=rid1),
        status="error",
        error_message=INTERRUPTED,
        rollback_outcome=None,
        completed=True,
    )
    assert [r for r in after["chat_requests"] if r["request_id"] != rid1] == [
        r for r in before["chat_requests"] if r["request_id"] != rid1
    ]
    assert after["generation_snapshots"] == [
        r for r in before["generation_snapshots"] if r["request_id"] != rid1
    ]
    _assert_lock(env, sid, held_by=rid2)
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], "nothing logged at ERROR"
    # The newer turn is not an orphan, and a later sweep leaves it alone.
    assert recover() == 0
    _assert_tables_equal(after, env.tables())


# --- 4. one bad entry never stops a sweep -------------------------------------


def _claim_raises_for(monkeypatch, failing_rid: str) -> None:
    """The rollback's fence claim raises for *failing_rid* only (a broken row, a
    lost connection): ``roll_back_generation`` itself raises for that request."""
    real = generation_rollback.claim_turn_row

    def claim(db, request_id):
        if request_id == failing_rid:
            raise RuntimeError("MK-INJECTED the claim failed")
        return real(db, request_id)

    monkeypatch.setattr(generation_rollback, "claim_turn_row", claim)


def test_one_orphan_that_cannot_be_rolled_back_does_not_stop_the_sweep(env, monkeypatch):
    """Two orphans; rolling back the first raises.  The second is still rolled back,
    and the first is left exactly as it was for the next sweep."""
    first = env.new_session(created_by=OWNER, title="MK-FIRST")
    seed_earlier_turn(env, first)
    rid1 = press_enter(env, first)
    edit_turn(env, first, first, rid1)
    age_lock(first, ORPHAN_AGE)
    second = env.new_session(created_by=OWNER, title="MK-SECOND")
    seed_earlier_turn(env, second)
    before = env.tables()
    rid2 = press_enter(env, second)
    edit_turn(env, second, second, rid2)
    age_lock(second, ORPHAN_AGE)
    at_turn_end = env.tables()
    assert env.snapshot_rows(rid1)[0]["id"] < env.snapshot_rows(rid2)[0]["id"]
    _claim_raises_for(monkeypatch, rid1)

    assert recover() == 1

    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid2,
        actor_sid=second,
        owner_sid=second,
        terminal_status="error",
        error_message=INTERRUPTED,
        deck_existed=True,
    )
    assert env.request_row(rid1) == _one(at_turn_end["chat_requests"], request_id=rid1)
    assert env.snapshot_rows(rid1) == [
        _one(at_turn_end["generation_snapshots"], request_id=rid1)
    ]


def test_one_stuck_request_that_cannot_be_recovered_does_not_stop_the_others(env, monkeypatch):
    """Startup: two stuck requests -- an Agent turn (its lock its own and fresh, so
    not an orphan) whose rollback raises, then a Legacy one.  The Legacy one is
    still recovered; the Agent turn is left as it was."""
    agent = env.new_session(created_by=OWNER, title="MK-AGENT")
    seed_earlier_turn(env, agent)
    rid1 = press_enter(env, agent)
    edit_turn(env, agent, agent, rid1)
    age_request(rid1, 1300)
    age_lock(agent, 30)
    legacy, rid2 = _monolith_request(JobEnv(env, None), "explicit")
    get_session_manager().update_chat_request_status(rid2, "running")
    age_request(rid2, 1300)
    age_lock(legacy, 1300)
    before = env.tables()
    assert env.request_row(rid1)["id"] < env.request_row(rid2)["id"]
    _claim_raises_for(monkeypatch, rid1)

    assert run_startup_recovery() == 1

    after = env.tables()
    _assert_request(
        env.request_row(rid2),
        _one(before["chat_requests"], request_id=rid2),
        status="error",
        error_message=CRASH_RECOVERY,
        rollback_outcome=None,
        completed=True,
    )
    assert _lock(env.session_row(legacy)) == (False, None, None)
    assert env.request_row(rid1) == _one(before["chat_requests"], request_id=rid1)
    assert env.snapshot_rows(rid1) == [_one(before["generation_snapshots"], request_id=rid1)]
    _assert_tables_equal(before, after, exclude=("chat_requests", "user_sessions"))
    assert _one(after["user_sessions"], session_id=agent) == _one(
        before["user_sessions"], session_id=agent
    )

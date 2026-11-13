"""Task 4 on real PostgreSQL: the rollback against the constraints SQLite does not have.

``test_first_generation_rollback_deletes_deck_row_on_postgres`` -- a first-generation
rollback deletes the deck row the turn created, and the turn's mutation evidence
(``shared_deck_mutation_event``) points at that row.  On PostgreSQL the foreign key
is ``ON DELETE SET NULL`` and the table carries the append-only trigger
(``src/core/database.py``, the event guard), which admits exactly one kind of
UPDATE: a reference nulled because its target row is gone.  So the delete must
succeed, every event must survive with ``root_deck_id`` NULL and every other column
unchanged, and the turn's ``deck_reviews`` row must go with the deck through its
``ON DELETE CASCADE``.  SQLite enforces none of these foreign keys, so the unit
suite cannot show any of it.

``test_edit_rollback_is_exact_on_postgres`` -- the edit restore on PostgreSQL types
(timestamps, UUID identities, JSON agent config) and its triggers (deck
collaboration identity immutable, events append-only): every table back as it was
at Enter, the same assertion the unit suite makes on SQLite.

The scenarios, writers and assertions are the unit suite's
(``tests/unit/test_generation_rollback.py``), run here on a throwaway PostgreSQL
database.  Self-skips when no PostgreSQL is reachable (``postgres_engine``).
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Any, Callable, Dict, Iterator, Optional, Set
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

from src.api.schemas.requests import ChatRequest as ChatRequestBody
from src.core.database import get_db_session
from src.core.user_context import set_current_user
from src.services.deck_review_store import compute_deck_digest, save_deck_review
from src.services.generation_fence import fence_turn_write
from src.services.generation_rollback import RollbackResult, seal_generation
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from tests.integration.postgres_concurrency_helpers import _WAIT_SECONDS
from tests.unit.test_generation_rollback import (
    CONTRIBUTOR,
    OWNER,
    RESTORE_PENDING,
    SLIDES_BEFORE,
    SLIDES_BUILT,
    RollbackEnv,
    _assert_lock,
    _assert_request,
    _assert_rolled_back_to_enter,
    _assert_sessions_equal,
    _assert_tables_equal,
    _one,
    _rb,
    _slide_inserts_fail,
    build_env,
    edit_turn,
    first_generation_turn,
    in_turn,
    press_enter,
    roll_back,
    seed_earlier_turn,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


@pytest.fixture
def pg_env(postgres_engine, monkeypatch) -> RollbackEnv:
    return build_env(postgres_engine, monkeypatch)


@pytest.mark.parametrize(
    "terminal_status, error_message, refuse",
    [
        pytest.param("cancelled", None, True, id="stop"),
        pytest.param("error", "Model call failed: 403", False, id="failure"),
    ],
)
def test_first_generation_rollback_deletes_deck_row_on_postgres(
    pg_env, terminal_status, error_message, refuse
):
    env = pg_env
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = env.tables()

    rid = press_enter(env, sid)
    first_generation_turn(env, sid, rid)
    deck_id = env.deck_row(sid)["id"]
    # The deck reviewer's write, as deck_reviewer_node makes it (fenced, same txn).
    with in_turn(rid):
        with get_db_session() as db:
            fence_turn_write(db)
            save_deck_review(db, deck_id, compute_deck_digest(SLIDES_BUILT), [], OWNER)
    at_turn_end = env.tables()
    pointing = [
        e for e in at_turn_end["shared_deck_mutation_event"] if e["root_deck_id"] == deck_id
    ]
    assert pointing, "no mutation evidence points at the deck; the test proves nothing"
    assert [r for r in at_turn_end["deck_reviews"] if r["deck_id"] == deck_id]

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.ROLLED_BACK
    after = env.tables()
    assert env.deck_row(sid) is None
    # Every event kept, the deck reference nulled by the foreign key, nothing else
    # about it changed (the append-only trigger admitted exactly that UPDATE).
    expected_events = [
        dict(e, root_deck_id=None) if e["root_deck_id"] == deck_id else e
        for e in at_turn_end["shared_deck_mutation_event"]
    ]
    assert after["shared_deck_mutation_event"] == expected_events
    # Everything else back as it was at Enter -- including deck_reviews, emptied by
    # the cascade.
    _assert_rolled_back_to_enter(
        env,
        before,
        dict(at_turn_end, shared_deck_mutation_event=expected_events),
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status=terminal_status,
        error_message=error_message,
        deck_existed=False,
    )
    assert after["deck_reviews"] == before["deck_reviews"] == []


def test_edit_rollback_is_exact_on_postgres(pg_env):
    env = pg_env
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()

    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    at_turn_end = env.tables()
    assert env.slide_htmls(sid) != SLIDES_BEFORE

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    after = env.tables()
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="cancelled",
        error_message=None,
        deck_existed=True,
    )
    assert after["session_slides"] == before["session_slides"]
    assert _one(after["chat_requests"], request_id=rid)["rollback_outcome"] == "rolled_back"


# ===========================================================================
# Task 6 (PLAN-CORRECTIONS C11 / C13): the restore transaction under real row
# locks -- two restore retries at once, a seal racing a failing restore, and a
# contributor's Enter queued on the deck row during one.
#
# Each test parks one transaction at a chosen statement on a ``threading.Event``
# (a ``before_cursor_execute`` hook dispatched on the thread's name), starts the
# competing work, OBSERVES it waiting on the parked transaction's locks
# (``pg_blocking_pids``) or finished, then lets the parked transaction go.
# Nothing is ordered by sleeping.
# ===========================================================================

_SLIDE_ROWS_WRITE = re.compile(
    r"^\s*(DELETE\s+FROM|INSERT\s+INTO)\s+[\"`]?session_slides\b", re.IGNORECASE
)
_SLIDE_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+[\"`]?session_slides\b", re.IGNORECASE)


class _Runner(threading.Thread):
    """Runs *fn* on a thread with a fixed name; keeps its result or exception."""

    def __init__(self, name: str, fn: Callable[[], Any]) -> None:
        super().__init__(name=name, daemon=True)
        self._fn = fn
        self.result: Any = None
        self.error: Optional[BaseException] = None
        self.done = threading.Event()

    def run(self) -> None:
        try:
            self.result = self._fn()
        except BaseException as exc:  # noqa: BLE001 -- asserted by the test
            self.error = exc
        finally:
            self.done.set()


class _Backends:
    """Every backend pid each named thread has executed a statement on."""

    def __init__(self) -> None:
        self.by_thread: Dict[str, Set[int]] = {}
        self.latest: Dict[str, int] = {}

    def record(self, cursor) -> int:
        name = threading.current_thread().name
        pid = cursor.connection.get_backend_pid()
        self.by_thread.setdefault(name, set()).add(pid)
        self.latest[name] = pid
        return pid


def _observer(engine):
    """A separate engine for watching ``pg_stat_activity`` (no hook fires on it)."""
    return create_engine(engine.url, poolclass=NullPool)


def _waiting_on(observer, waiter_pid: Optional[int], blockers: Set[int]) -> bool:
    if waiter_pid is None or not blockers:
        return False
    with observer.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT wait_event_type = 'Lock' "
                    "AND pg_blocking_pids(pid) && CAST(:blockers AS integer[]) "
                    "FROM pg_stat_activity WHERE pid = :waiter"
                ),
                {"waiter": waiter_pid, "blockers": sorted(blockers)},
            ).scalar()
        )


def _anyone_waiting_on(observer, blocker_pid: int) -> bool:
    with observer.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' "
                    "AND CAST(:blocker AS integer) = ANY(pg_blocking_pids(pid)))"
                ),
                {"blocker": blocker_pid},
            ).scalar()
        )


def _until(predicate: Callable[[], bool], seconds: float = _WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _recover() -> int:
    from src.services import generation_rollback

    return generation_rollback.recover_orphaned_generations()


def _restore_failed_edit(env: RollbackEnv):
    """An edit turn whose restore failed; returns (session, request, before, at_turn_end)."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    at_turn_end = env.tables()
    with _slide_inserts_fail(env.engine):
        assert roll_back(rid, "error", "MK failed", False) == RollbackResult.RESTORE_FAILED
    assert [s["state"] for s in env.snapshot_rows(rid)] == ["restore_failed"]
    return sid, rid, before, at_turn_end


def test_restore_retry_claimed_once(pg_env, postgres_engine):
    """Two sweeps retry the same ``restore_failed`` snapshot at once.  The first is
    parked inside its restore (after its claim); the second must not restore it
    too -- it waits on the first's claim, or skips at once -- and, once the first
    commits, finds the snapshot gone.  Exactly one restore: one ``restore_version``
    event, one version bump."""
    env = pg_env
    sid, rid, before, at_turn_end = _restore_failed_edit(env)
    backends = _Backends()
    observer = _observer(postgres_engine)
    parked = threading.Event()
    release = threading.Event()

    def hook(conn, cursor, statement, parameters, context, executemany):
        backends.record(cursor)
        if (
            threading.current_thread().name == "retry-1"
            and not parked.is_set()
            and _SLIDE_ROWS_WRITE.match(statement)
        ):
            parked.set()
            if not release.wait(_WAIT_SECONDS):
                raise AssertionError("the parked retry was never released")

    event.listen(postgres_engine, "before_cursor_execute", hook)
    first = _Runner("retry-1", _recover)
    second = _Runner("retry-2", _recover)
    try:
        first.start()
        _until(lambda: parked.is_set() or first.done.is_set())
        assert parked.is_set(), f"the first retry never reached the restore: {first.error!r}"
        second.start()
        overlapped = _until(
            lambda: second.done.is_set()
            or _waiting_on(
                observer, backends.latest.get("retry-2"), backends.by_thread.get("retry-1", set())
            )
        )
        assert overlapped, "the second retry neither finished nor waited on the first"
        assert not first.done.is_set(), "the first retry was not still inside its restore"
    finally:
        release.set()
        for runner in (first, second):
            if runner.ident is not None:
                runner.join(_WAIT_SECONDS)
        event.remove(postgres_engine, "before_cursor_execute", hook)
        observer.dispose()

    assert first.error is None, f"the first retry failed: {first.error!r}"
    assert second.error is None, f"the second retry failed: {second.error!r}"
    assert (first.result, second.result) == (1, 0)
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
    assert env.snapshot_rows(rid) == []
    _assert_lock(env, sid, held_by=None)


def test_seal_racing_a_failing_restore_is_refused(pg_env, postgres_engine):
    """C11 + C13.  A failure's restore fails part-way while the turn is sealing.
    The seal waits on the rollback's claim.  The failed restore must be recorded in
    the SAME transaction (savepoint rolled back, ``restore_failed`` written, then
    commit), so when the seal finally runs the turn is no longer live and the seal
    is refused.  Never a request marked ``restore_failed`` over a ``sealed``
    snapshot: no retry would ever restore it, and it keeps the deck locked."""
    env = pg_env
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    at_turn_end = env.tables()
    backends = _Backends()
    observer = _observer(postgres_engine)
    failing = threading.Event()
    go = threading.Event()

    def hook(conn, cursor, statement, parameters, context, executemany):
        backends.record(cursor)
        if (
            threading.current_thread().name == "rollback"
            and not failing.is_set()
            and _SLIDE_INSERT.match(statement)
        ):
            failing.set()
            if not go.wait(_WAIT_SECONDS):
                raise AssertionError("the failing restore was never let go")
            raise RuntimeError("MK-injected: the slide insert failed")

    event.listen(postgres_engine, "before_cursor_execute", hook)
    rollback = _Runner("rollback", lambda: roll_back(rid, "error", "MK failed", False))
    seal = _Runner("seal", lambda: seal_generation(rid))
    try:
        rollback.start()
        _until(lambda: failing.is_set() or rollback.done.is_set())
        assert failing.is_set(), f"the restore never reached its slide inserts: {rollback.error!r}"
        seal.start()
        assert _until(
            lambda: _waiting_on(
                observer, backends.latest.get("seal"), backends.by_thread.get("rollback", set())
            )
        ), "the seal never waited on the rollback's transaction"
        assert not seal.done.is_set()
    finally:
        go.set()
        rollback.join(_WAIT_SECONDS)
        if seal.ident is not None:
            seal.join(_WAIT_SECONDS)
        event.remove(postgres_engine, "before_cursor_execute", hook)
        observer.dispose()

    assert rollback.error is None, rollback.error
    assert seal.error is None, seal.error
    assert rollback.result == RollbackResult.RESTORE_FAILED
    snapshot_states = [s["state"] for s in env.snapshot_rows(rid)]
    row = env.request_row(rid)
    assert seal.result is False, (
        f"the seal ran in the gap after the failed restore: request "
        f"{row['rollback_outcome']!r}, snapshot {snapshot_states}"
    )
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "error",
        RESTORE_PENDING,
        "restore_failed",
    )
    _assert_request(
        row,
        _one(at_turn_end["chat_requests"], request_id=rid),
        status="error",
        error_message=RESTORE_PENDING,
        rollback_outcome="restore_failed",
        completed=None,
    )
    assert env.snapshot_rows(rid) == [
        dict(_one(at_turn_end["generation_snapshots"], request_id=rid), state="restore_failed")
    ]
    _assert_lock(env, sid, held_by=rid)
    # The restore rolled back whole: the deck is the turn's, untouched.
    _assert_tables_equal(
        at_turn_end, env.tables(), exclude=("chat_requests", "generation_snapshots")
    )


def test_contributor_enter_queued_during_a_failing_restore_is_refused(
    pg_env, postgres_engine, monkeypatch
):
    """C13.  The owner's turn fails and its restore fails part-way.  Meanwhile a
    contributor presses Enter on the same deck (their own session, so the owner's
    session lock does not stop them): ``begin_generation`` queues on the owner's
    deck row, which the restore holds.  The failed restore must be recorded BEFORE
    that lock is let go, so the queued Enter sees the pending restore and is
    refused with the restore-pending 409 -- instead of snapshotting the
    half-generated deck the failed restore left."""
    from src.api.routes import chat as chat_routes

    env = pg_env
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    rid = press_enter(env, owner)
    edit_turn(env, owner, owner, rid)
    at_turn_end = env.tables()

    # Permission is not under test (a contributor needs CAN_EDIT and the editing lock).
    monkeypatch.setattr(
        chat_routes, "_check_chat_permission", lambda session_id, db, **kwargs: None
    )
    enqueued = AsyncMock()
    monkeypatch.setattr(chat_routes, "enqueue_job", enqueued)

    observer = _observer(postgres_engine)
    failing = threading.Event()
    go = threading.Event()
    holder: Dict[str, int] = {}

    def submit_as_contributor():
        async def call():
            set_current_user(CONTRIBUTOR)
            return await chat_routes.submit_chat_async(
                ChatRequestBody(session_id=contrib, message="MK-CONTRIB make me a slide"),
                db=None,
            )

        return asyncio.run(call())

    rollback = _Runner("rollback", lambda: roll_back(rid, "error", "MK failed", False))
    enter = _Runner("enter", submit_as_contributor)

    def hook(conn, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name != "rollback":
            return
        pid = cursor.connection.get_backend_pid()
        if not failing.is_set():
            if _SLIDE_INSERT.match(statement):
                holder["pid"] = pid
                failing.set()
                if not go.wait(_WAIT_SECONDS):
                    raise AssertionError("the failing restore was never let go")
                raise RuntimeError("MK-injected: the slide insert failed")
            return
        # After the failure: while this connection no longer blocks the queued
        # Enter, let that Enter run to its end first, so a restore_failed record
        # made outside the deck-row lock cannot win the race by luck.
        _until(lambda: enter.done.is_set() or _anyone_waiting_on(observer, pid))

    event.listen(postgres_engine, "before_cursor_execute", hook)
    try:
        rollback.start()
        _until(lambda: failing.is_set() or rollback.done.is_set())
        assert failing.is_set(), f"the restore never reached its slide inserts: {rollback.error!r}"
        enter.start()
        assert _until(lambda: _anyone_waiting_on(observer, holder["pid"])), (
            "the contributor's Enter never queued on the restore's locks"
        )
        assert not enter.done.is_set()
    finally:
        go.set()
        rollback.join(_WAIT_SECONDS)
        if enter.ident is not None:
            enter.join(_WAIT_SECONDS)
        event.remove(postgres_engine, "before_cursor_execute", hook)
        observer.dispose()

    assert rollback.error is None, rollback.error
    assert rollback.result == RollbackResult.RESTORE_FAILED
    contrib_requests = [
        r for r in env.tables()["chat_requests"] if r["session_id"] == env.pk(contrib)
    ]
    assert len(contrib_requests) == 1
    contrib_rid = contrib_requests[0]["request_id"]
    assert isinstance(enter.error, HTTPException), (
        f"the contributor's Enter was accepted ({enter.result!r}) and snapshotted the "
        f"deck the failed restore left: {env.snapshot_rows(contrib_rid)}"
    )
    assert (enter.error.status_code, enter.error.detail) == (409, RESTORE_PENDING)
    enqueued.assert_not_awaited()
    assert env.snapshot_rows(contrib_rid) == []
    refused = contrib_requests[0]
    assert (refused["status"], refused["rollback_outcome"], refused["result_json"]) == (
        "error",
        None,
        None,
    )
    _assert_lock(env, contrib, held_by=None)
    _assert_request(
        env.request_row(rid),
        _one(at_turn_end["chat_requests"], request_id=rid),
        status="error",
        error_message=RESTORE_PENDING,
        rollback_outcome="restore_failed",
        completed=None,
    )
    assert env.snapshot_rows(rid) == [
        dict(_one(at_turn_end["generation_snapshots"], request_id=rid), state="restore_failed")
    ]
    _assert_lock(env, owner, held_by=rid)
    # Nothing else moved: the owner's turn's deck as it stood, no contributor message,
    # every session row as it was (the contributor's lock taken and given back).
    after = env.tables()
    _assert_tables_equal(
        at_turn_end, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    _assert_sessions_equal(at_turn_end, after, touched=(contrib, owner))

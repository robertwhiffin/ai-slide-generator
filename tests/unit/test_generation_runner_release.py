"""Task 6: a stop frees the job runner at once; the hard timeout rolls back.

The contract (plan Task 6, PLAN-CORRECTIONS C11/C13):

* **The consumer polls liveness.**  ``_send_message_streaming_graph`` reads the
  graph's queue with ``get(timeout=STOP_POLL_SECONDS)`` and, when the turn has a
  request id, calls ``turn_is_live(request_id)`` at most once per
  ``STOP_POLL_SECONDS``.  A turn that is no longer live raises ``TurnStopped``,
  which ``process_chat_request`` swallows (no status write; its ``finally``
  releases by request id).  So the runner is free for the next turn while the
  abandoned graph thread is still blocked in a model call.
* **The abandoned graph thread ends quietly.**  When its next write is refused
  (``TurnFencedError``) or it fails after the turn was stopped, ``run_graph``
  logs ``"Abandoned graph turn ended"`` at INFO, puts no ERROR event and records
  no error; it still puts the ``None`` sentinel.
* **The stop needs no in-process state.**  A stop handled by another uvicorn
  process (another ``ChatService`` / ``SessionManager``, an empty ``jobs`` dict)
  frees this process's consumer within ``2 * STOP_POLL_SECONDS``.
* **Hard timeout.**  ``mark_timed_out_jobs_once`` rolls a timed-out graph turn
  back (``error``, the existing timeout text, ``refuse_on_foreign_change=False``);
  a monolith job is only marked in memory, as today.
* **Lock refresh.**  ``refresh_job_session_locks_once`` refreshes a graph entry's
  lock only while ``processing_request_id`` is that entry's request id
  (``SessionManager.refresh_session_lock(session_id, request_id=...)``); monolith
  entries are unchanged.  ``mark_timed_out_jobs_loop`` runs
  ``recover_orphaned_generations`` each sweep, off the event loop.

How the tests are built
-----------------------
The harness of ``tests/unit/test_job_queue_rollback.py``: the REAL
``process_chat_request``, the REAL ``ChatService`` graph limb and a REAL
``SessionManager`` over a file-backed SQLite database, the Task 4 real-writer
helpers for everything a turn writes, and whole-database comparisons.  Only
``invoke_graph`` is replaced, by :class:`BlockingGraph`, whose body runs under the
turn's request id and can block on a ``threading.Event`` (never on a sleep) so a
test can stop the turn while the graph thread is provably still inside it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterator, List, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, update

import src.database.models  # noqa: F401 -- registers every ORM model on Base
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import chat_service as chat_service_module
from src.api.services import job_queue
from src.api.services import session_manager as session_manager_module
from src.api.services.chat_service import ChatService
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import SessionManager, get_session_manager
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base, _run_migrations, get_db_session
from src.core.user_context import set_current_user
from src.database.models.session import UserSession
from src.services import generation_fence, generation_rollback
from src.services.generation_fence import TurnFencedError, TurnStopped
from src.services.generation_rollback import RollbackResult
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from tests.unit.test_generation_rollback import (
    OWNER,
    REWRITTEN,
    _assert_lock,
    _assert_rolled_back_to_enter,
    _assert_sessions_equal,
    _assert_tables_equal,
    _ctx,
    _one,
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
from tests.unit.test_job_queue_rollback import (
    THREAD_WAIT,
    USER_MESSAGE,
    JobEnv,
    _monolith_request,
    graph_payload,
    run_job,
    track,
)

#: The brief's runner-release budget: ``process_chat_request`` returns within this
#: many seconds of the stop while the graph thread is still blocked.
RUNNER_RELEASE_BUDGET = 3.0

#: ``mark_timed_out_jobs_once``'s text for a graph turn (existing copy, exact).
GRAPH_TIMEOUT_TEXT = "Generation exceeded maximum duration (20 minutes)"
MONOLITH_TIMEOUT_TEXT = "Generation exceeded maximum duration (10 minutes)"


def stop_poll_seconds() -> float:
    """``job_queue.STOP_POLL_SECONDS`` (1.0 per the brief; asserted separately)."""
    return float(getattr(job_queue, "STOP_POLL_SECONDS", 1.0))


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


class BlockingGraph:
    """Stands in for ``src.services.graph.builder.invoke_graph``.

    Runs :attr:`body` (``body(graph, session_id, request_id)``) with the request id
    bound as the real ``invoke_graph`` binds it, so the real writers it calls are
    fenced as a real turn's are.  Records the graph thread and the emitter queue
    ``_send_message_streaming_graph`` handed in, so a test can join the thread and
    inspect what was put on the queue after the consumer left.  Whatever the body
    raises leaves ``invoke_graph`` (and is recorded in :attr:`raised`).
    """

    def __init__(self) -> None:
        self.calls: List[Optional[str]] = []
        self.body: Optional[Callable[["BlockingGraph", str, Optional[str]], None]] = None
        self.thread: Optional[threading.Thread] = None
        self.emitter: Any = None
        self.wrote = threading.Event()
        self.release = threading.Event()
        self.resumed = threading.Event()
        self.raised: List[BaseException] = []

    def __call__(self, session_id, initial=None, *, emitter=None, request_id=None, **kwargs):
        self.calls.append(request_id)
        self.thread = threading.current_thread()
        self.emitter = emitter
        if self.body is not None:
            with in_turn(request_id):
                try:
                    self.body(self, session_id, request_id)
                except BaseException as exc:  # noqa: BLE001 -- recorded, then re-raised
                    self.raised.append(exc)
                    raise
        return {}

    def wait_until_released(self) -> None:
        assert self.release.wait(THREAD_WAIT), "the test never released the graph thread"
        self.resumed.set()

    def finish(self) -> None:
        """Let the graph thread go and wait for it to end."""
        self.release.set()
        if self.thread is not None:
            self.thread.join(THREAD_WAIT)


@pytest.fixture
def env(monkeypatch, tmp_path) -> Iterator[JobEnv]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/runner-release.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    rb = build_env(engine, monkeypatch)

    graph = BlockingGraph()
    monkeypatch.setattr("src.services.graph.builder.invoke_graph", graph)
    monkeypatch.setattr("src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None))
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title", lambda message, model: None
    )
    monkeypatch.setattr("src.api.services.session_naming.build_session_title_model", MagicMock())

    original_jobs = job_queue.jobs
    original_jobs.clear()
    job_queue.shutdown_chat_executor()
    try:
        yield JobEnv(rb, graph)
    finally:
        graph.finish()
        job_queue.shutdown_chat_executor()
        job_queue.jobs.clear()
        original_jobs.clear()
        engine.dispose()


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


# ---------------------------------------------------------------------------
# Drivers and small helpers
# ---------------------------------------------------------------------------


class JobThread(threading.Thread):
    """``process_chat_request`` on its own thread (its own event loop)."""

    def __init__(self, request_id: str, payload: Dict[str, Any]) -> None:
        super().__init__(name=f"job-{request_id[:6]}", daemon=True)
        self.request_id = request_id
        self.payload = payload
        self.done = threading.Event()
        self.raised: Optional[BaseException] = None
        self.returned_at: Optional[float] = None

    def run(self) -> None:
        try:
            self.raised = run_job(self.request_id, self.payload)
        finally:
            self.returned_at = time.monotonic()
            self.done.set()


class ConsumerThread(threading.Thread):
    """Iterates ``ChatService.send_message_streaming`` (graph) on a thread named
    ``consumer``: the generator's consumer loop runs here."""

    def __init__(self, service: ChatService, session_id: str, request_id: Optional[str]):
        super().__init__(name="consumer", daemon=True)
        self.service = service
        self.session_id = session_id
        self.request_id = request_id
        self.events: List[StreamEvent] = []
        self.enough_events = threading.Event()
        self.ended = threading.Event()
        self.raised: Optional[BaseException] = None
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None

    def run(self) -> None:
        self.started_at = time.monotonic()
        try:
            for event in self.service.send_message_streaming(
                session_id=self.session_id,
                message=USER_MESSAGE,
                request_id=self.request_id,
                is_first_message_override=False,
                engine_mode="graph",
            ):
                self.events.append(event)
                if len(self.events) >= 50:
                    self.enough_events.set()
        except BaseException as exc:  # noqa: BLE001 -- asserted by the test
            self.raised = exc
        finally:
            self.ended_at = time.monotonic()
            self.ended.set()


class GeneratorEnd:
    """Wraps one ``ChatService`` instance's ``send_message_streaming`` and records
    how (and when) the generator ended inside the job."""

    def __init__(self, service: ChatService) -> None:
        real = service.send_message_streaming
        self.raised: Optional[BaseException] = None
        self.at: Optional[float] = None
        self.ended = threading.Event()

        def wrapped(*args, **kwargs):
            try:
                yield from real(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 -- recorded, then re-raised
                self.raised = exc
                raise
            finally:
                self.at = time.monotonic()
                self.ended.set()

        service.send_message_streaming = wrapped


def spy_turn_is_live(monkeypatch) -> List[tuple]:
    """Record every ``turn_is_live`` call as ``(thread name, monotonic time)``.

    Patched on ``generation_fence`` (a lazy import or a module-attribute call) and
    on ``chat_service`` (a module-top ``from ... import``)."""
    calls: List[tuple] = []
    real = generation_fence.turn_is_live

    def spy(request_id):
        calls.append((threading.current_thread().name, time.monotonic()))
        return real(request_id)

    monkeypatch.setattr(generation_fence, "turn_is_live", spy)
    monkeypatch.setattr(chat_service_module, "turn_is_live", spy, raising=False)
    return calls


def set_lock(session_id: str, **values: Any) -> None:
    """Write *session_id*'s lock columns directly (a crashed process, time passing)."""
    with get_db_session() as db:
        db.execute(
            update(UserSession)
            .where(UserSession.session_id == session_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )


def cancel_from_another_process(request_id: str, user: str):
    """``POST /chat/cancel/{request_id}``'s handler, run as *user*."""
    from src.api.routes import chat as chat_routes

    async def call():
        set_current_user(user)
        return await chat_routes.cancel_chat(request_id)

    return asyncio.run(call())


def _lock(row: Dict[str, Any]) -> tuple:
    return (row["is_processing"], row["processing_started_at"], row["processing_request_id"])


def released(tables: Dict[str, List[Dict[str, Any]]], session_id: str) -> Dict[str, Any]:
    """*tables* with *session_id*'s lock released (for a whole-table comparison)."""
    rows = [
        dict(r, is_processing=False, processing_started_at=None, processing_request_id=None)
        if r["session_id"] == session_id
        else r
        for r in tables["user_sessions"]
    ]
    return dict(tables, user_sessions=rows)


# ---------------------------------------------------------------------------
# The constants
# ---------------------------------------------------------------------------


def test_stop_poll_interval_is_one_second():
    assert job_queue.STOP_POLL_SECONDS == 1.0


# ---------------------------------------------------------------------------
# A stop frees the runner while the graph thread is still blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ending", ["fenced_write", "late_failure"])
def test_runner_released_while_graph_thread_still_blocked(env, caplog, ending):
    """The graph made one fenced write and is now blocked (a model call that has not
    returned).  The sender stops the turn: it is rolled back, and the job must give
    its runner back within 3 s while the graph thread is STILL blocked.  The sender
    sends again at once.  When the graph thread finally resumes, its next write is
    refused (``fenced_write``) or it fails (``late_failure``): either way it ends
    quietly -- no row changes, no ERROR event, no ERROR log, an INFO
    ``"Abandoned graph turn ended"`` -- and the newer request's lock is untouched."""
    caplog.set_level(logging.INFO)
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    before = env.tables()
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    graph = env.graph

    def body(g: BlockingGraph, s: str, r: str) -> None:
        # The architect's pre-fan-out deck-level write (it bumps the deck version).
        write_deck_level_columns(
            s,
            css=".mk-turn { color: #0a0b0c; }",
            title="MK-TURN-DECK-TITLE",
            modified_by=OWNER,
            mutation=_ctx(s, "write_deck_level", "deck"),
        )
        g.wrote.set()
        g.wait_until_released()
        if ending == "fenced_write":
            get_session_manager().add_message(
                s, "assistant", "MK-LATE reply", message_type="chat", request_id=r
            )
        else:
            raise RuntimeError("MK-INJECTED the model call failed after the stop")

    graph.body = body
    job = JobThread(rid, payload)
    job.start()
    try:
        assert graph.wrote.wait(THREAD_WAIT), "the graph never made its first write"
        at_turn_end = env.tables()

        assert roll_back(rid, "cancelled", None, True) == RollbackResult.ROLLED_BACK
        stopped_at = time.monotonic()
        after_stop = env.tables()
        # The sender sends again straight away (the stop released the lock).
        rid2 = press_enter(env.rb, sid, "MK-USER second try", start=False)

        returned = job.done.wait(max(0.0, stopped_at + RUNNER_RELEASE_BUDGET - time.monotonic()))
        assert returned, (
            f"process_chat_request did not return within {RUNNER_RELEASE_BUDGET} s of the "
            "stop: the runner is held until the abandoned graph thread finishes"
        )
        assert graph.thread is not None and graph.thread.is_alive(), (
            "the graph thread was not still blocked; the test proves nothing"
        )
        assert not graph.resumed.is_set()
        assert job.raised is None, f"the stopped job raised: {job.raised!r}"
        assert job.returned_at - stopped_at < RUNNER_RELEASE_BUDGET
        assert rid not in job_queue.jobs, "the stopped job is still counted as this process's"
        # The job's end wrote nothing over the stop, and freed nothing it no longer owns.
        assert env.rb.request_row(rid) == _one(after_stop["chat_requests"], request_id=rid)
        _assert_lock(env.rb, sid, held_by=rid2)

        before_release = env.tables()
        caplog.clear()
    finally:
        graph.release.set()
        job.join(THREAD_WAIT)

    graph.thread.join(THREAD_WAIT)
    assert not graph.thread.is_alive(), "the abandoned graph thread never ended"

    # The rollback itself put the deck back exactly as at Enter.
    _assert_rolled_back_to_enter(
        env.rb,
        before,
        at_turn_end,
        after_stop,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="cancelled",
        error_message=None,
        deck_existed=True,
    )
    # The abandoned thread's ending changed nothing at all.
    if ending == "fenced_write":
        assert [type(e) for e in graph.raised] == [TurnFencedError], graph.raised
    _assert_tables_equal(before_release, env.tables())
    _assert_lock(env.rb, sid, held_by=rid2)
    assert env.rb.request_row(rid2)["status"] == "pending"

    leftover = list(graph.emitter.queue)
    assert [e for e in leftover if e is not None and e.type == StreamEventType.ERROR] == [], (
        f"the abandoned graph thread put an ERROR event: {leftover}"
    )
    assert leftover and leftover[-1] is None, "the graph thread did not put its None sentinel"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], f"the abandoned thread logged at ERROR: {[r.getMessage() for r in errors]}"
    infos = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and "Abandoned graph turn ended" in r.getMessage()
    ]
    assert infos, "no INFO 'Abandoned graph turn ended' was logged"


def test_stop_from_another_process_frees_the_consumer(env, monkeypatch):
    """The job runs on process A (``ChatService`` A).  The stop reaches process B:
    a different ``ChatService`` and ``SessionManager`` and an empty ``jobs`` dict,
    so nothing in A's memory can carry it.  A's consumer still notices through the
    database and raises ``TurnStopped`` within ``2 * STOP_POLL_SECONDS``; the job
    returns cleanly and the deck is restored."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    before = env.tables()
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    process_a = ChatService()
    monkeypatch.setattr(chat_service_module, "_chat_service_instance", process_a)
    generator_end = GeneratorEnd(process_a)
    graph = env.graph

    def body(g: BlockingGraph, s: str, r: str) -> None:
        edit_turn(env.rb, s, s, r)
        g.wrote.set()
        g.wait_until_released()
        get_session_manager().add_message(
            s, "assistant", "MK-LATE reply", message_type="chat", request_id=r
        )

    graph.body = body
    job = JobThread(rid, payload)
    job.start()
    try:
        assert graph.wrote.wait(THREAD_WAIT), "the graph never wrote"
        at_turn_end = env.tables()

        # Process B: its own memory and its own service objects.
        monkeypatch.setattr(job_queue, "jobs", {})
        monkeypatch.setattr(chat_service_module, "_chat_service_instance", ChatService())
        monkeypatch.setattr(session_manager_module, "_session_manager", SessionManager())
        response = cancel_from_another_process(rid, OWNER)
        stopped_at = time.monotonic()
        after_stop = env.tables()
        assert response.outcome == "cancelled", response

        budget = 2 * stop_poll_seconds()
        ended = generator_end.ended.wait(max(0.0, stopped_at + budget - time.monotonic()))
        assert ended, (
            f"process A's consumer did not notice the stop within {budget} s: it waits "
            "on the graph thread instead of polling the turn's liveness"
        )
        assert isinstance(generator_end.raised, TurnStopped), (
            f"A's consumer ended with {generator_end.raised!r}, not TurnStopped"
        )
        assert generator_end.raised.request_id == rid
        assert generator_end.at - stopped_at <= budget
        assert graph.thread.is_alive() and not graph.resumed.is_set(), (
            "the graph thread was not still blocked; the test proves nothing"
        )
        assert job.done.wait(THREAD_WAIT), "process_chat_request never returned"
        assert job.raised is None, f"the stopped job raised: {job.raised!r}"
        assert env.rb.request_row(rid) == _one(after_stop["chat_requests"], request_id=rid)
    finally:
        graph.release.set()
        job.join(THREAD_WAIT)
    graph.thread.join(THREAD_WAIT)

    _assert_rolled_back_to_enter(
        env.rb,
        before,
        at_turn_end,
        after_stop,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="cancelled",
        error_message=None,
        deck_existed=True,
    )
    _assert_tables_equal(after_stop, env.tables())
    _assert_lock(env.rb, sid, held_by=None)


def test_stop_during_a_continuous_event_stream_frees_the_consumer(env, monkeypatch):
    """The graph keeps streaming events (no gap in which a blocking ``get`` would
    time out).  The consumer must still notice a stop within
    ``2 * STOP_POLL_SECONDS`` -- and must read the turn's status at most once per
    ``STOP_POLL_SECONDS``, never once per event."""
    calls = spy_turn_is_live(monkeypatch)
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    rid = press_enter(env.rb, sid)
    graph = env.graph

    def body(g: BlockingGraph, s: str, r: str) -> None:
        SlideWriter().write_slide(
            s, 1, REWRITTEN, scripts="", modified_by=OWNER, mutation=_ctx(s, "write_slide", "slide")
        )
        g.wrote.set()
        deadline = time.monotonic() + THREAD_WAIT
        while not g.release.is_set() and time.monotonic() < deadline:
            g.emitter.put(StreamEvent(type=StreamEventType.ASSISTANT, content="MK-progress"))
            g.release.wait(0.005)

    graph.body = body
    consumer = ConsumerThread(ChatService(), sid, rid)
    consumer.start()
    try:
        assert consumer.enough_events.wait(THREAD_WAIT), "the stream never got going"
        assert roll_back(rid, "cancelled", None, True) == RollbackResult.ROLLED_BACK
        stopped_at = time.monotonic()

        budget = 2 * stop_poll_seconds()
        ended = consumer.ended.wait(max(0.0, stopped_at + budget - time.monotonic()))
        assert ended, (
            f"the consumer did not notice the stop within {budget} s while events kept "
            "arriving"
        )
        assert isinstance(consumer.raised, TurnStopped), consumer.raised
        assert graph.thread.is_alive(), "the graph stopped streaming; the test proves nothing"
    finally:
        graph.release.set()
        consumer.join(THREAD_WAIT)
    graph.thread.join(THREAD_WAIT)

    lifetime = consumer.ended_at - consumer.started_at
    polls = [t for name, t in calls if name == "consumer"]
    received = len(consumer.events)
    assert received > 100, f"only {received} events streamed; the test proves nothing"
    assert 1 <= len(polls) <= lifetime / stop_poll_seconds() + 2, (
        f"the consumer read the turn's status {len(polls)} times in {lifetime:.2f} s "
        f"({received} events): at most once per {stop_poll_seconds()} s is allowed"
    )


def test_sse_path_without_request_id_never_polls_liveness(env, monkeypatch):
    """Guard: the SSE route's graph turn has no request id, so nothing is polled
    (and nothing can stop it); it completes as today."""
    calls = spy_turn_is_live(monkeypatch)
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    graph = env.graph

    def body(g: BlockingGraph, s: str, r: Optional[str]) -> None:
        # Longer than one poll interval, so a consumer that polled would have.
        g.release.wait(1.5 * stop_poll_seconds())

    graph.body = body
    consumer = ConsumerThread(ChatService(), sid, None)
    consumer.start()
    assert consumer.ended.wait(THREAD_WAIT)

    assert consumer.raised is None, consumer.raised
    assert StreamEventType.COMPLETE in [e.type for e in consumer.events]
    assert calls == [], f"the SSE path polled the turn's liveness: {calls}"


# ---------------------------------------------------------------------------
# The hard timeout
# ---------------------------------------------------------------------------


def _timed_out_graph_entry(session_id: str, *, age_seconds: int = 1300) -> Dict[str, Any]:
    now = datetime.utcnow()
    return {
        "status": "running",
        "session_id": session_id,
        "engine_mode": "graph",
        "queued_at": now - timedelta(seconds=age_seconds + 5),
        "started_at": now - timedelta(seconds=age_seconds),
    }


@pytest.mark.parametrize("kind", ["first_generation", "edit"])
def test_timeout_rolls_back_graph_turn(env, kind):
    """A graph turn past ``GRAPH_JOB_HARD_TIMEOUT_SECONDS``: the sweep marks it in
    memory as today AND rolls it back -- the deck as at Enter, the request
    ``error`` with the timeout text, the lock free -- and the turn's late writes
    are refused from then on."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    if kind == "edit":
        seed_earlier_turn(env.rb, sid)
    before = env.tables()
    rid = press_enter(env.rb, sid)
    if kind == "edit":
        edit_turn(env.rb, sid, sid, rid)
    else:
        first_generation_turn(env.rb, sid, rid)
    at_turn_end = env.tables()
    job_queue.jobs[rid] = _timed_out_graph_entry(sid)

    marked = asyncio.run(job_queue.mark_timed_out_jobs_once())

    assert marked == 1
    entry = job_queue.jobs[rid]
    assert (entry["status"], entry["error"]) == ("failed", GRAPH_TIMEOUT_TEXT)
    after = env.tables()
    _assert_rolled_back_to_enter(
        env.rb,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=GRAPH_TIMEOUT_TEXT,
        deck_existed=kind == "edit",
    )
    assert env.rb.snapshot_rows(rid) == []
    _assert_lock(env.rb, sid, held_by=None)
    with in_turn(rid):
        with pytest.raises(TurnFencedError):
            get_session_manager().add_message(
                sid, "assistant", "MK-LATE after the timeout", message_type="chat", request_id=rid
            )
    _assert_tables_equal(after, env.tables())


def test_timeout_with_foreign_change_keeps_the_deck(env):
    """A timeout is a failure, not a stop (``refuse_on_foreign_change=False``):
    another editor's change since Enter keeps the deck as it stands, ends the
    request and frees the deck -- it never leaves a timed-out turn live."""
    owner = env.rb.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env.rb, owner)
    contrib = env.rb.contributor(owner)
    rid = press_enter(env.rb, owner)
    edit_turn(env.rb, owner, owner, rid)
    foreign_edit(env.rb, contrib)
    before = env.tables()
    job_queue.jobs[rid] = _timed_out_graph_entry(owner)

    assert asyncio.run(job_queue.mark_timed_out_jobs_once()) == 1

    after = env.tables()
    _assert_tables_equal(
        before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    _assert_sessions_equal(released(before, owner), after, touched=(owner,))
    row = env.rb.request_row(rid)
    assert _without(row, ("completed_at",)) == _without(
        dict(
            _one(before["chat_requests"], request_id=rid),
            status="error",
            error_message=GRAPH_TIMEOUT_TEXT,
            rollback_outcome="kept_foreign_change",
        ),
        ("completed_at",),
    )
    assert row["completed_at"] is not None
    assert [r for r in after["chat_requests"] if r["request_id"] != rid] == [
        r for r in before["chat_requests"] if r["request_id"] != rid
    ]
    assert after["generation_snapshots"] == [
        r for r in before["generation_snapshots"] if r["request_id"] != rid
    ]
    _assert_lock(env.rb, owner, held_by=None)


def test_timed_out_job_is_freed_and_writes_nothing_after_the_rollback(env):
    """The real job is blocked in its graph when the sweep times it out.  The
    rollback ends the turn; the job's consumer notices and returns within the
    runner-release budget, and nothing the job does afterwards overwrites the
    timed-out request or frees anything."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    graph = env.graph

    def body(g: BlockingGraph, s: str, r: str) -> None:
        edit_turn(env.rb, s, s, r)
        g.wrote.set()
        g.wait_until_released()

    graph.body = body
    job = JobThread(rid, payload)
    job.start()
    try:
        assert graph.wrote.wait(THREAD_WAIT)
        # What worker() records when it hands the job over, aged past the limit.
        job_queue.jobs[rid].update(
            status="running", started_at=datetime.utcnow() - timedelta(seconds=1300)
        )
        assert asyncio.run(job_queue.mark_timed_out_jobs_once()) == 1
        swept_at = time.monotonic()
        after_sweep = env.tables()
        row = env.rb.request_row(rid)
        assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
            "error",
            GRAPH_TIMEOUT_TEXT,
            "rolled_back",
        )

        returned = job.done.wait(max(0.0, swept_at + RUNNER_RELEASE_BUDGET - time.monotonic()))
        assert returned, "the timed-out job kept its runner while its graph was blocked"
        assert graph.thread.is_alive(), "the graph thread was not still blocked"
        assert job.raised is None, f"the timed-out job raised: {job.raised!r}"
        _assert_tables_equal(after_sweep, env.tables())
        assert rid not in job_queue.jobs
    finally:
        graph.release.set()
        job.join(THREAD_WAIT)
    graph.thread.join(THREAD_WAIT)
    _assert_tables_equal(after_sweep, env.tables())


def _forbid_rollback(monkeypatch) -> List[str]:
    used: List[str] = []

    def forbidden(*args, **kwargs):
        used.append("roll_back_generation")
        raise AssertionError("a monolith job was rolled back")

    monkeypatch.setattr(generation_rollback, "roll_back_generation", forbidden)
    monkeypatch.setattr(job_queue, "roll_back_generation", forbidden, raising=False)
    return used


@pytest.mark.parametrize("shape", ["explicit", "mcp"], ids=["engine_mode=monolith", "mcp-payload"])
def test_timeout_leaves_monolith_unchanged(env, monkeypatch, shape):
    """Guard: a timed-out monolith job (a Legacy deck's, or MCP's) is only marked
    in memory, exactly as today; the database is not touched and the rollback is
    never called."""
    sid, rid = _monolith_request(env, shape)
    get_session_manager().update_chat_request_status(rid, "running")
    used = _forbid_rollback(monkeypatch)
    job_queue.jobs[rid] = {
        "status": "running",
        "session_id": sid,
        "engine_mode": "monolith" if shape == "explicit" else None,
        "queued_at": datetime.utcnow() - timedelta(seconds=705),
        "started_at": datetime.utcnow() - timedelta(seconds=700),
    }
    before = env.tables()

    marked = asyncio.run(job_queue.mark_timed_out_jobs_once())

    assert marked == 1
    entry = job_queue.jobs[rid]
    assert (entry["status"], entry["error"]) == ("failed", MONOLITH_TIMEOUT_TEXT)
    assert used == []
    _assert_tables_equal(before, env.tables())


# ---------------------------------------------------------------------------
# The lock heartbeat
# ---------------------------------------------------------------------------


def test_cancelled_queued_job_does_not_refresh_newer_lock(env):
    """A turn stopped while it was queued here still has its ``pending`` entry in
    this process's ``jobs`` (the runner has not reached it).  The sender sent
    again through ANOTHER process, which died: the newer request's lock must go
    stale.  The zombie entry must not keep it alive."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid1 = press_enter(env.rb, sid, start=False)
    track(rid1, graph_payload(sid))
    assert roll_back(rid1, "cancelled", None, True) == RollbackResult.ROLLED_BACK
    rid2 = press_enter(env.rb, sid, "MK-USER second try", start=False)
    set_lock(sid, processing_started_at=datetime.utcnow() - timedelta(seconds=200))
    before = env.tables()
    assert _lock(_one(before["user_sessions"], session_id=sid))[2] == rid2

    refreshed = asyncio.run(job_queue.refresh_job_session_locks_once())

    assert refreshed == 0
    _assert_tables_equal(before, env.tables())


@pytest.mark.parametrize("with_zombie", [False, True], ids=["alone", "beside-a-stopped-entry"])
def test_graph_entry_refreshes_its_own_bound_lock(env, with_zombie):
    """Guard (today's behaviour for the owning entry): a graph turn this process
    runs keeps its own lock live, even beside a stopped entry of the same session."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    if with_zombie:
        rid0 = press_enter(env.rb, sid, start=False)
        track(rid0, graph_payload(sid))
        assert roll_back(rid0, "cancelled", None, True) == RollbackResult.ROLLED_BACK
    rid = press_enter(env.rb, sid)
    track(rid, graph_payload(sid))
    job_queue.jobs[rid]["status"] = "running"
    set_lock(sid, processing_started_at=datetime.utcnow() - timedelta(seconds=200))
    before = env.tables()
    t0 = datetime.utcnow()

    refreshed = asyncio.run(job_queue.refresh_job_session_locks_once())

    assert refreshed == 1
    after = env.tables()
    row = _one(after["user_sessions"], session_id=sid)
    assert row["is_processing"] is True and row["processing_request_id"] == rid
    assert row["processing_started_at"] >= t0 - timedelta(seconds=1)
    _assert_tables_equal(before, after, exclude=("user_sessions",))

    def norm(rows):
        return [
            _without(r, ("processing_started_at", "last_activity")) if r["session_id"] == sid else r
            for r in rows
        ]

    assert norm(after["user_sessions"]) == norm(before["user_sessions"])


@pytest.mark.parametrize("binding", ["unbound", "bound-to-another-request"])
def test_monolith_entry_refresh_unchanged(env, binding):
    """Guard: a monolith entry refreshes its session's held lock whatever the lock
    is bound to (MCP never binds; a Legacy async turn binds), exactly as today."""
    shape = "mcp" if binding == "unbound" else "explicit"
    sid, rid = _monolith_request(env, shape)
    if binding == "bound-to-another-request":
        get_session_manager().bind_session_lock(sid, "req-someone-else")
    job_queue.jobs[rid] = {
        "status": "running",
        "session_id": sid,
        "engine_mode": None if shape == "mcp" else "monolith",
        "queued_at": datetime.utcnow(),
        "started_at": datetime.utcnow(),
    }
    set_lock(sid, processing_started_at=datetime.utcnow() - timedelta(seconds=200))
    t0 = datetime.utcnow()

    refreshed = asyncio.run(job_queue.refresh_job_session_locks_once())

    assert refreshed == 1
    row = env.rb.session_row(sid)
    assert row["is_processing"] is True
    assert row["processing_started_at"] >= t0 - timedelta(seconds=1)


def test_refresh_session_lock_matched_on_request_id(env):
    """``SessionManager.refresh_session_lock(session_id, request_id=...)`` refreshes
    only while that request owns the held lock; without it, as before."""
    sm = get_session_manager()
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    assert sm.acquire_session_lock(sid)
    sm.bind_session_lock(sid, "req-owner")
    old = datetime.utcnow() - timedelta(seconds=200)
    set_lock(sid, processing_started_at=old)

    assert sm.refresh_session_lock(sid, request_id="req-other") is False
    assert _lock(env.rb.session_row(sid)) == (True, old, "req-owner")

    t0 = datetime.utcnow()
    assert sm.refresh_session_lock(sid, request_id="req-owner") is True
    row = env.rb.session_row(sid)
    assert row["processing_request_id"] == "req-owner"
    assert row["processing_started_at"] >= t0 - timedelta(seconds=1)

    set_lock(sid, processing_started_at=old)
    assert sm.refresh_session_lock(sid) is True
    assert env.rb.session_row(sid)["processing_started_at"] >= t0 - timedelta(seconds=1)


def test_timeout_loop_runs_orphan_recovery_off_the_event_loop_each_sweep(monkeypatch):
    """``mark_timed_out_jobs_loop`` runs ``recover_orphaned_generations`` once per
    sweep, in a worker thread (it restores decks: never on the event loop)."""
    ran_on: List[threading.Thread] = []
    sleeps: List[float] = []

    async def sleep(seconds):
        if len(sleeps) == 2:
            raise asyncio.CancelledError
        sleeps.append(seconds)

    async def no_op():
        return 0

    def recover(now=None):
        ran_on.append(threading.current_thread())
        return 0

    monkeypatch.setattr(job_queue.asyncio, "sleep", sleep)
    monkeypatch.setattr(job_queue, "mark_timed_out_jobs_once", no_op)
    monkeypatch.setattr(job_queue, "refresh_job_session_locks_once", no_op)
    monkeypatch.setattr(generation_rollback, "recover_orphaned_generations", recover, raising=False)
    monkeypatch.setattr(job_queue, "recover_orphaned_generations", recover, raising=False)

    loop_thread: List[threading.Thread] = []

    async def scenario():
        loop_thread.append(threading.current_thread())
        with pytest.raises(asyncio.CancelledError):
            await job_queue.mark_timed_out_jobs_loop()

    asyncio.run(scenario())

    assert len(sleeps) == 2, "the loop did not run two sweeps"
    assert len(ran_on) == 2, f"recover_orphaned_generations ran {len(ran_on)} times in 2 sweeps"
    assert all(t is not loop_thread[0] for t in ran_on), (
        "recover_orphaned_generations ran on the event loop's thread"
    )


# ---------------------------------------------------------------------------
# Fix round 1: an unreadable status is not a stop
# ---------------------------------------------------------------------------


def test_unreadable_turn_status_keeps_the_consumer_waiting(env, monkeypatch):
    """Fail-open: every liveness read raises (a database blip).  That is not a stop:
    the consumer keeps waiting on the graph (no ``TurnStopped``) and the turn
    completes when the graph does.  The fence and the seal still guard a turn that
    really was stopped."""
    reads: List[str] = []

    def unreadable(request_id):
        reads.append(threading.current_thread().name)
        raise RuntimeError("MK-INJECTED the status read failed")

    monkeypatch.setattr(generation_fence, "turn_is_live", unreadable)
    monkeypatch.setattr(chat_service_module, "turn_is_live", unreadable, raising=False)
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    rid = press_enter(env.rb, sid)
    graph = env.graph

    def body(g: BlockingGraph, s: str, r: str) -> None:
        # Long enough for the consumer to read the status (and fail) twice.
        g.release.wait(2.5 * stop_poll_seconds())

    graph.body = body
    consumer = ConsumerThread(ChatService(), sid, rid)
    consumer.start()
    assert consumer.ended.wait(THREAD_WAIT), "the consumer never ended"

    assert consumer.raised is None, f"an unreadable status ended the turn: {consumer.raised!r}"
    assert StreamEventType.COMPLETE in [e.type for e in consumer.events]
    consumer_reads = reads.count("consumer")
    assert consumer_reads >= 2, f"the consumer read the status {consumer_reads} times"
    assert env.rb.request_row(rid)["status"] == "running"
    assert [s["state"] for s in env.rb.snapshot_rows(rid)] == ["sealed"]

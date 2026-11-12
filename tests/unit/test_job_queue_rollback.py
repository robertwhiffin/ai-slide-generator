"""Task 5: the job's side of the all-or-nothing turn.

``process_chat_request`` (``src/api/services/job_queue.py``) and the graph limb
of ``ChatService.send_message_streaming`` decide how an Agent-deck turn ends:

* **Start.** A graph request moves ``pending`` -> ``running`` with the
  conditional ``start_chat_request``.  A request stopped while it was queued is
  never started: no graph run, no status write, no lock release, and its
  in-memory ``jobs`` entry is dropped.
* **Seal, then save point.** ``_send_message_streaming_graph`` seals the turn's
  snapshot as soon as the graph has finished, BEFORE the "Generated N slide(s)"
  save point.  A stop before the seal rolls the turn back and the generator
  raises ``TurnStopped`` without attempting the save point; a stop after it is
  "already finished" (``NOT_LIVE``) and the finished deck and its save point stay.
* **Success.** ``SessionManager.complete_chat_request(request_id, result)``
  claims the row, stores the result, marks it ``completed`` and deletes the
  snapshot in one transaction; it returns False (and writes nothing) once the
  request is no longer live.
* **Failure.** With a snapshot, a failed graph turn (generic, or the typed
  pinned-configuration failure) is rolled back exactly like a stop; without one
  the status write is conditional on the request still being live, so a stop is
  never overwritten by ``error``.  The ``finally`` releases the lock by request
  id, and not at all while the snapshot survives (a failed restore keeps the
  deck locked).
* **Monolith** (Legacy decks, every MCP job) takes exactly today's path.

How the tests are built
-----------------------
* The REAL ``process_chat_request``, the REAL ``ChatService`` graph limb (seal,
  save point, COMPLETE event) and a REAL ``SessionManager``, over a file-backed
  SQLite database: the job runs its generator on the chat-job executor thread and
  the graph on its own thread, and an in-memory engine would hand those threads
  an empty database (``tests/unit/test_job_queue_lock_release.py``).
* Only ``invoke_graph`` is replaced (:class:`GraphStub`).  Its body runs the REAL
  turn writers under the turn's request id (the helpers of
  ``tests/unit/test_generation_rollback.py``), so what is rolled back, kept or
  sealed is what a real turn writes.  Monolith tests replace
  ``send_message_streaming`` instead: the monolith's own agent is not under test.
* Enter is ``press_enter`` from the Task 4 suite: lock, request row, bound lock,
  snapshot, user message (the order ``submit_chat_async`` uses).
* "Nothing written" and "rolled back to Enter" compare EVERY table, every column.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import inspect
import json
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

import src.database.models  # noqa: F401 -- registers every ORM model on Base
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import chat_service as chat_service_module
from src.api.services import job_queue
from src.api.services.chat_service import GRAPH_TURN_FAILED_MESSAGE, ChatService
from src.api.services.job_queue import PINNED_GRAPH_CONFIGURATION_ERROR
from src.api.services.session_manager import SessionManager, get_session_manager
from src.core.database import Base, _run_migrations, get_db_session
from src.services import generation_rollback
from src.services.conversation_pins import ConversationPinMissingError
from src.services.generation_fence import TurnStopped, start_chat_request
from src.services.generation_rollback import RollbackResult
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from tests.unit.test_generation_rollback import (
    OWNER,
    RESTORE_PENDING,
    SLIDES_BEFORE,
    SLIDES_BUILT,
    RollbackEnv,
    _assert_lock,
    _assert_rolled_back_to_enter,
    _assert_tables_equal,
    _messages_tagged,
    _one,
    _slide_inserts_fail,
    _without,
    build_env,
    edit_turn,
    first_generation_turn,
    in_turn,
    press_enter,
    roll_back,
    seed_earlier_turn,
)

#: How long any test waits on a thread it started before failing instead of hanging.
THREAD_WAIT = 30

USER_MESSAGE = "MK-USER make me a deck"


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


class GraphStub:
    """Stands in for ``src.services.graph.builder.invoke_graph``.

    Records every call, then runs :attr:`body` (``body(session_id, request_id)``)
    with the request id bound as the real ``invoke_graph`` binds it, so the real
    writers it calls are fenced exactly as a real turn's are.  An exception the
    body raises leaves ``invoke_graph`` as a real node failure would.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.body: Optional[Callable[[str, Optional[str]], None]] = None

    def __call__(self, session_id, initial=None, *, emitter=None, request_id=None, **kwargs):
        self.calls.append({"session_id": session_id, "request_id": request_id})
        if self.body is not None:
            with in_turn(request_id):
                self.body(session_id, request_id)
        return {}


class JobEnv:
    def __init__(self, rb: RollbackEnv, graph: GraphStub) -> None:
        self.rb = rb
        self.graph = graph

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.rb.tables()

    def versions(self, session_id: str) -> List[Dict[str, Any]]:
        pk = self.rb.pk(session_id)
        return [r for r in self.tables()["slide_deck_versions"] if r["session_id"] == pk]


@pytest.fixture
def env(monkeypatch, tmp_path) -> Iterator[JobEnv]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/job-queue-rollback.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    rb = build_env(engine, monkeypatch)

    graph = GraphStub()
    monkeypatch.setattr("src.services.graph.builder.invoke_graph", graph)
    # send_message_streaming reads settings for the title model; no workspace here.
    monkeypatch.setattr("src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None))
    # No session title is generated (and none is written) unless a test asks.
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title", lambda message, model: None
    )
    monkeypatch.setattr("src.api.services.session_naming.build_session_title_model", MagicMock())

    job_queue.jobs.clear()
    job_queue.shutdown_chat_executor()
    try:
        yield JobEnv(rb, graph)
    finally:
        job_queue.shutdown_chat_executor()
        job_queue.jobs.clear()
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
# Driving the job
# ---------------------------------------------------------------------------


def graph_payload(session_id: str, *, is_first_message: bool = False) -> Dict[str, Any]:
    """What ``submit_chat_async`` enqueues for an Agent deck (plus ``_context``,
    which ``enqueue_job`` adds)."""
    return {
        "session_id": session_id,
        "message": USER_MESSAGE,
        "slide_context": None,
        "is_first_message": is_first_message,
        "image_ids": None,
        "engine_mode": "graph",
        "_context": contextvars.copy_context(),
    }


def monolith_payload(session_id: str, shape: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "message": USER_MESSAGE,
        "slide_context": None,
        "is_first_message": False,
        "image_ids": None,
        "_context": contextvars.copy_context(),
    }
    if shape == "explicit":
        payload["engine_mode"] = "monolith"
    else:  # mcp_server.py's payload: no engine_mode key, MCP's own `mode`
        payload["mode"] = "generate"
        payload["correlation_id"] = "corr-1"
    return payload


def track(request_id: str, payload: Dict[str, Any]) -> None:
    """The in-memory entry ``enqueue_job`` makes (read by the lock refresher)."""
    job_queue.jobs[request_id] = {
        "status": "pending",
        "session_id": payload["session_id"],
        "engine_mode": payload.get("engine_mode"),
        "queued_at": datetime.utcnow(),
    }


def run_job(request_id: str, payload: Dict[str, Any]) -> Optional[BaseException]:
    """``process_chat_request`` to its end; what it raised, or None."""
    try:
        asyncio.run(job_queue.process_chat_request(request_id, payload))
    except Exception as exc:  # noqa: BLE001 -- the caller asserts on it
        return exc
    return None


def start(request_id: str) -> None:
    with get_db_session() as db:
        assert start_chat_request(db, request_id), "the job could not start the request"


def spy_get_slides(monkeypatch) -> List[Any]:
    """Record what ``ChatService.get_slides`` returned (the COMPLETE event's slides)."""
    seen: List[Any] = []
    real = ChatService.get_slides

    def recording(self, session_id):
        out = real(self, session_id)
        seen.append(out)
        return out

    monkeypatch.setattr(ChatService, "get_slides", recording)
    return seen


def spy_create_version(monkeypatch, after: Optional[Callable[[], None]] = None) -> List[str]:
    """Record every save-point attempt; run *after* once the real call returned."""
    calls: List[str] = []
    real = SessionManager.create_version

    def recording(self, *args, **kwargs):
        calls.append(kwargs.get("description") or (args[1] if len(args) > 1 else None))
        out = real(self, *args, **kwargs)
        if after is not None:
            after()
        return out

    monkeypatch.setattr(SessionManager, "create_version", recording)
    return calls


def _graph_result(slides: Any) -> Dict[str, Any]:
    """The result dict ``process_chat_request`` builds from a graph COMPLETE event."""
    return json.loads(
        json.dumps(
            {
                "slides": slides,
                "raw_html": None,
                "replacement_info": None,
                "experiment_url": None,
                "metadata": {"engine_mode": "graph"},
            }
        )
    )


def _lock_fields(row: Dict[str, Any]) -> tuple:
    return (row["is_processing"], row["processing_started_at"], row["processing_request_id"])


# ---------------------------------------------------------------------------
# Start: a request stopped while queued never starts
# ---------------------------------------------------------------------------


def test_cancelled_pending_request_never_starts(env):
    """A stop on a queued request rolled it back; the person sent again at once.
    When the runner finally reaches the stopped request, it must not run the graph,
    must not move the request out of ``cancelled``, must not touch the lock the
    newer request holds, and must drop its in-memory entry."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid1 = press_enter(env.rb, sid, start=False)
    payload1 = graph_payload(sid, is_first_message=True)
    track(rid1, payload1)
    assert roll_back(rid1, "cancelled", None, True) == RollbackResult.ROLLED_BACK
    rid2 = press_enter(env.rb, sid, "MK-USER second try", start=False)
    _assert_lock(env.rb, sid, held_by=rid2)
    env.graph.body = lambda s, r: first_generation_turn(env.rb, s, r)
    before = env.tables()

    raised = run_job(rid1, payload1)

    assert raised is None, f"the stopped request's job raised: {raised!r}"
    assert env.graph.calls == [], "the graph ran for a request stopped while it was queued"
    _assert_tables_equal(before, env.tables())
    assert env.rb.request_row(rid1)["status"] == "cancelled"
    _assert_lock(env.rb, sid, held_by=rid2)
    assert rid1 not in job_queue.jobs, "the stopped request is still counted as a job"


def test_start_failure_rolls_back_and_frees_the_deck(env, monkeypatch):
    """The conditional start itself raises (the database blipped).  The turn fails
    like any other graph failure: rolled back to Enter, ``error`` with the start's
    error, the lock released and the job dropped.  Never a ``pending`` request
    still holding the deck's lock with nothing running it."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = env.tables()
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid, is_first_message=True)
    track(rid, payload)
    at_enter = env.tables()
    env.graph.body = lambda s, r: first_generation_turn(env.rb, s, r)

    def failing_start(self, request_id):
        raise RuntimeError("MK-start failed")

    monkeypatch.setattr(SessionManager, "start_chat_request", failing_start)

    raised = run_job(rid, payload)

    assert isinstance(raised, RuntimeError) and str(raised) == "MK-start failed", raised
    assert env.graph.calls == [], "the graph ran for a request that never started"
    _assert_rolled_back_to_enter(
        env.rb,
        before,
        at_enter,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message="MK-start failed",
        deck_existed=False,
    )
    assert env.rb.snapshot_rows(rid) == []
    _assert_lock(env.rb, sid, held_by=None)
    assert rid not in job_queue.jobs


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_success_path_completes_and_drops_snapshot(env, monkeypatch):
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    at: Dict[str, Any] = {}

    def body(s, r):
        first_generation_turn(env.rb, s, r)
        at["turn_end"] = env.tables()

    env.graph.body = body
    slides_sent = spy_get_slides(monkeypatch)

    raised = run_job(rid, payload)

    assert raised is None, f"the turn failed: {raised!r}"
    assert len(env.graph.calls) == 1
    after = env.tables()
    row = _one(after["chat_requests"], request_id=rid)
    base = _one(at["turn_end"]["chat_requests"], request_id=rid)
    assert row["completed_at"] is not None
    assert len(slides_sent) == 1, "the COMPLETE event was not built exactly once"
    assert json.loads(row["result_json"]) == _graph_result(slides_sent[0])
    assert _without(row, ("completed_at", "result_json")) == _without(
        dict(base, status="completed", error_message=None, rollback_outcome=None),
        ("completed_at", "result_json"),
    )
    _assert_lock(env.rb, sid, held_by=None)
    assert [v["description"] for v in env.versions(sid)] == ["Generated 3 slide(s)"]
    # Everything the turn wrote stays exactly as it wrote it.
    _assert_tables_equal(
        at["turn_end"],
        after,
        exclude=("chat_requests", "generation_snapshots", "slide_deck_versions", "user_sessions"),
    )
    assert env.rb.slide_htmls(sid) == SLIDES_BUILT
    assert len(_messages_tagged(after, rid)) == 4
    assert rid not in job_queue.jobs
    assert env.rb.snapshot_rows(rid) == [], "the completed turn's snapshot was not deleted"
    assert generation_rollback.has_generation_snapshot(rid) is False


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["first_generation", "edit"])
def test_graph_failure_rolls_back(env, kind):
    """A builder crash mid-turn: the turn is undone exactly like a stop, the
    request ends ``error`` with the code-owned failure text, and the deck is free."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    if kind == "edit":
        seed_earlier_turn(env.rb, sid)
    before = env.tables()
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    at: Dict[str, Any] = {}

    def body(s, r):
        if kind == "edit":
            edit_turn(env.rb, s, s, r)
        else:
            first_generation_turn(env.rb, s, r)
        at["turn_end"] = env.tables()
        raise RuntimeError("MK-INJECTED a builder crashed")

    env.graph.body = body

    run_job(rid, payload)

    assert "turn_end" in at, "the graph never ran"
    after = env.tables()
    _assert_rolled_back_to_enter(
        env.rb,
        before,
        at["turn_end"],
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=GRAPH_TURN_FAILED_MESSAGE,
        deck_existed=kind == "edit",
    )
    assert env.rb.snapshot_rows(rid) == []
    _assert_lock(env.rb, sid, held_by=None)
    assert rid not in job_queue.jobs


def test_graph_failure_with_failed_restore_keeps_the_lock(env):
    """The failure's restore itself fails: the request is ``restore_failed``, the
    snapshot is kept for the retry, and the job's ``finally`` must NOT release the
    session lock (the deck stays locked to its sender until it is restored)."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)

    with contextlib.ExitStack() as stack:

        def body(s, r):
            edit_turn(env.rb, s, s, r)
            # From here on every slide-row INSERT fails: the restore cannot finish.
            stack.enter_context(_slide_inserts_fail(env.rb.engine))
            raise RuntimeError("MK-INJECTED a builder crashed")

        env.graph.body = body
        run_job(rid, payload)

    row = env.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "error",
        RESTORE_PENDING,
        "restore_failed",
    )
    assert [s["state"] for s in env.rb.snapshot_rows(rid)] == ["restore_failed"]
    _assert_lock(env.rb, sid, held_by=rid)
    assert generation_rollback.has_pending_restore(sid) is True
    assert rid not in job_queue.jobs


def test_pinned_configuration_failure_rolls_back(env):
    """A first generation whose pin cannot be loaded fails in ``invoke_graph``'s
    pin loader before any node runs, yet Enter already saved the user message,
    locked the deck mode and pinned the owner: all three are undone."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = env.tables()
    assert env.rb.session_row(sid)["deck_mode"] is None
    rid = press_enter(env.rb, sid, start=False)
    at_enter = env.tables()
    assert env.rb.session_row(sid)["deck_mode"] == "agent"
    assert env.rb.session_row(sid)["graph_release_id"] == env.rb.release_id
    payload = graph_payload(sid, is_first_message=True)
    track(rid, payload)

    def body(s, r):
        raise ConversationPinMissingError(s)

    env.graph.body = body

    run_job(rid, payload)

    assert len(env.graph.calls) == 1
    after = env.tables()
    _assert_rolled_back_to_enter(
        env.rb,
        before,
        at_enter,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="error",
        error_message=PINNED_GRAPH_CONFIGURATION_ERROR,
        deck_existed=False,
    )
    # Spelled out (implied above):
    assert _messages_tagged(after, rid) == [], "the user message of the failed turn remains"
    assert env.rb.session_row(sid)["deck_mode"] is None, "the deck-mode lock was not undone"
    assert env.rb.session_row(sid)["graph_release_id"] is None, "the pin was not undone"
    _assert_lock(env.rb, sid, held_by=None)


def test_failure_after_cancel_does_not_overwrite_cancelled(env):
    """The stop lands mid-turn; the abandoned graph's next write is refused and the
    turn fails.  The job must write nothing: the request stays ``cancelled`` with
    its ``rolled_back`` outcome, and no ``error`` text appears."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    at: Dict[str, Any] = {}

    def body(s, r):
        first_generation_turn(env.rb, s, r)
        at["stop"] = roll_back(r, "cancelled", None, True)
        at["after_stop"] = env.tables()
        # The abandoned graph carries on; its next write is refused.
        get_session_manager().add_message(
            s, "assistant", "MK-LATE reply", message_type="chat", request_id=r
        )

    env.graph.body = body

    run_job(rid, payload)

    assert at.get("stop") == RollbackResult.ROLLED_BACK
    _assert_tables_equal(at["after_stop"], env.tables())
    row = env.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "cancelled",
        None,
        "rolled_back",
    )
    assert rid not in job_queue.jobs


# ---------------------------------------------------------------------------
# The seal: the commit point comes before the save point
# ---------------------------------------------------------------------------


def test_stop_after_seal_is_already_finished_and_keeps_save_point(env, monkeypatch):
    """A stop that arrives after the save point (so after the seal) loses the race:
    it is "already finished" and changes nothing, and the turn completes with its
    deck and its save point -- never a restored deck with a stray save point."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env.rb, sid, start=False)
    payload = graph_payload(sid)
    track(rid, payload)
    env.graph.body = lambda s, r: first_generation_turn(env.rb, s, r)
    at: Dict[str, Any] = {}

    def stop_after_the_save_point():
        at["before_stop"] = env.tables()
        at["stop"] = roll_back(rid, "cancelled", None, True)
        at["after_stop"] = env.tables()

    spy_create_version(monkeypatch, after=stop_after_the_save_point)

    raised = run_job(rid, payload)

    assert "stop" in at, "the save point was never created"
    assert at["stop"] == RollbackResult.NOT_LIVE, (
        f"a stop after the seal must be 'already finished', got {at['stop']!r}"
    )
    _assert_tables_equal(at["before_stop"], at["after_stop"])
    assert raised is None, f"the turn failed: {raised!r}"
    row = env.rb.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("completed", None)
    assert env.rb.slide_htmls(sid) == SLIDES_BUILT
    assert [v["description"] for v in env.versions(sid)] == ["Generated 3 slide(s)"]
    assert len(_messages_tagged(env.tables(), rid)) == 4
    assert env.rb.snapshot_rows(rid) == []
    _assert_lock(env.rb, sid, held_by=None)


def test_stop_before_seal_leaves_no_save_point(env, monkeypatch):
    """The graph has finished but the turn has not sealed: a stop now rolls the
    edit back, and the generator raises ``TurnStopped`` at the seal -- no COMPLETE
    event, no save-point attempt, nothing written after the stop."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env.rb, sid)
    rid = press_enter(env.rb, sid)
    at: Dict[str, Any] = {}

    def stop() -> None:
        at["stop"] = roll_back(rid, "cancelled", None, True)
        at["after_stop"] = env.tables()

    def body(s, r):
        edit_turn(env.rb, s, s, r)
        # The turn is blocked just before the seal while another request stops it.
        stopper = threading.Thread(target=stop)
        stopper.start()
        stopper.join(timeout=THREAD_WAIT)

    env.graph.body = body
    save_points = spy_create_version(monkeypatch)

    events: List[StreamEvent] = []
    raised: Optional[BaseException] = None
    try:
        for event in ChatService().send_message_streaming(
            session_id=sid,
            message=USER_MESSAGE,
            request_id=rid,
            is_first_message_override=False,
            engine_mode="graph",
        ):
            events.append(event)
    except Exception as exc:  # noqa: BLE001 -- asserted below
        raised = exc

    assert at.get("stop") == RollbackResult.ROLLED_BACK
    assert isinstance(raised, TurnStopped), f"the generator did not stop at the seal: {raised!r}"
    assert raised.request_id == rid
    assert StreamEventType.COMPLETE not in [e.type for e in events], (
        "a COMPLETE event was sent for a stopped turn"
    )
    assert save_points == [], f"a save point was attempted for a stopped turn: {save_points}"
    _assert_tables_equal(at["after_stop"], env.tables())
    assert env.versions(sid) == []
    assert env.rb.slide_htmls(sid) == SLIDES_BEFORE


# ---------------------------------------------------------------------------
# complete_chat_request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ended_by", ["cancelled", "failed", "completed"])
def test_complete_after_cancel_returns_false_and_writes_nothing(env, ended_by):
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env.rb, sid)
    first_generation_turn(env.rb, sid, rid)
    sm = get_session_manager()
    if ended_by == "cancelled":
        assert roll_back(rid, "cancelled", None, True) == RollbackResult.ROLLED_BACK
    elif ended_by == "failed":
        assert roll_back(rid, "error", "MK failed", False) == RollbackResult.ROLLED_BACK
    else:
        assert sm.complete_chat_request(rid, {"slides": {"MK": "first"}}) is True
    before = env.tables()

    assert sm.complete_chat_request(rid, {"slides": {"MK": "late"}}) is False

    _assert_tables_equal(before, env.tables())


@pytest.mark.parametrize("snapshot_state", ["active", "sealed", "none"])
def test_complete_chat_request_completes_and_deletes_the_snapshot(env, snapshot_state):
    """The live request is completed with its result, and its snapshot (in either
    live state) is deleted; nothing else changes."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env.rb, sid)
    first_generation_turn(env.rb, sid, rid)
    if snapshot_state == "sealed":
        assert generation_rollback.seal_generation(rid) is True
    elif snapshot_state == "none":
        with get_db_session() as db:
            generation_rollback.discard_generation_snapshot(db, rid)
    before = env.tables()
    result = {"slides": {"slides": [{"html": "MK"}]}, "metadata": {"engine_mode": "graph"}}

    assert get_session_manager().complete_chat_request(rid, result) is True

    after = env.tables()
    _assert_tables_equal(before, after, exclude=("chat_requests", "generation_snapshots"))
    assert after["generation_snapshots"] == []
    assert [r for r in after["chat_requests"] if r["request_id"] != rid] == [
        r for r in before["chat_requests"] if r["request_id"] != rid
    ]
    row = _one(after["chat_requests"], request_id=rid)
    assert row["completed_at"] is not None
    assert json.loads(row["result_json"]) == result
    assert _without(row, ("completed_at", "result_json")) == _without(
        dict(_one(before["chat_requests"], request_id=rid), status="completed"),
        ("completed_at", "result_json"),
    )


# ---------------------------------------------------------------------------
# Monolith: exactly today's path
# ---------------------------------------------------------------------------


class _MonolithService:
    """Stands in for ChatService on a monolith job: the turn's generator."""

    def __init__(self, *, fail_with: Optional[BaseException] = None) -> None:
        self.fail_with = fail_with
        self.calls: List[Dict[str, Any]] = []

    def send_message_streaming(self, **kwargs) -> Iterator[StreamEvent]:
        self.calls.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with
        yield StreamEvent(
            type=StreamEventType.COMPLETE,
            slides={"slides": [{"html": "MK-MONOLITH"}]},
            raw_html="<html>MK-MONOLITH</html>",
            metadata={"engine_mode": "monolith"},
        )
        yield StreamEvent(type=StreamEventType.SESSION_TITLE, session_title="MK Monolith Title")


def _monolith_request(env: JobEnv, shape: str) -> tuple:
    """A Legacy deck's request as the route (or MCP) leaves it: locked, pending."""
    sid = env.rb.new_session(created_by=OWNER, title="MK-LEGACY")
    sm = get_session_manager()
    sm.add_user_message(
        sid, "MK-EARLIER legacy first message", message_type="user_query",
        requested_deck_mode="legacy",
    )
    assert sm.acquire_session_lock(sid)
    rid = sm.create_chat_request(sid, OWNER)
    if shape == "explicit":
        sm.bind_session_lock(sid, rid)  # the async route binds; MCP never does
    sm.add_message(sid, "user", USER_MESSAGE, message_type="user_query", request_id=rid)
    return sid, rid


def _spy_writes(monkeypatch) -> List[tuple]:
    """Every SessionManager status / result / lock write the job makes, with its
    arguments bound by name (defaults applied)."""
    calls: List[tuple] = []
    names = [
        "update_chat_request_status",
        "set_chat_request_result",
        "release_session_lock",
        "bind_session_lock",
    ]
    if hasattr(SessionManager, "complete_chat_request"):
        names.append("complete_chat_request")
    for name in names:
        real = getattr(SessionManager, name)

        def recording(self, *args, __real=real, __name=name, **kwargs):
            bound = inspect.signature(__real).bind(self, *args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            arguments.pop("self")
            calls.append((__name, arguments))
            return __real(self, *args, **kwargs)

        monkeypatch.setattr(SessionManager, name, recording)
    return calls


def _forbid_rollback_machinery(monkeypatch) -> List[str]:
    """No snapshot exists for a monolith request, and the rollback is never run."""
    used: List[str] = []

    def forbidden(name):
        def call(*args, **kwargs):
            used.append(name)
            raise AssertionError(f"a monolith job called {name}")

        return call

    monkeypatch.setattr(generation_rollback, "has_generation_snapshot", lambda rid: False)
    monkeypatch.setattr(job_queue, "has_generation_snapshot", lambda rid: False, raising=False)
    for name in ("roll_back_generation", "seal_generation"):
        monkeypatch.setattr(generation_rollback, name, forbidden(name))
        monkeypatch.setattr(job_queue, name, forbidden(name), raising=False)
    return used


@pytest.mark.parametrize("shape", ["explicit", "mcp"], ids=["engine_mode=monolith", "mcp-payload"])
def test_monolith_success_writes_unchanged(env, monkeypatch, shape):
    """Guard: today's three writes, in today's order, with today's arguments, then
    today's unconditional lock release."""
    sid, rid = _monolith_request(env, shape)
    service = _MonolithService()
    monkeypatch.setattr(chat_service_module, "_chat_service_instance", service)
    used = _forbid_rollback_machinery(monkeypatch)
    writes = _spy_writes(monkeypatch)
    payload = monolith_payload(sid, shape)
    track(rid, payload)

    raised = run_job(rid, payload)

    assert raised is None, f"the monolith job failed: {raised!r}"
    assert [c["engine_mode"] for c in service.calls] == ["monolith"]
    expected_result = {
        "slides": {"slides": [{"html": "MK-MONOLITH"}]},
        "raw_html": "<html>MK-MONOLITH</html>",
        "replacement_info": None,
        "experiment_url": None,
        "metadata": {"engine_mode": "monolith"},
        "session_title": "MK Monolith Title",
    }
    assert writes == [
        ("update_chat_request_status", {"request_id": rid, "status": "running", "error": None}),
        ("set_chat_request_result", {"request_id": rid, "result": expected_result}),
        ("update_chat_request_status", {"request_id": rid, "status": "completed", "error": None}),
        ("release_session_lock", {"session_id": sid, "request_id": None}),
    ]
    assert used == []
    row = env.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "completed",
        None,
        None,
    )
    assert json.loads(row["result_json"]) == expected_result
    assert row["completed_at"] is not None
    assert _lock_fields(env.rb.session_row(sid)) == (False, None, None)
    assert env.tables()["generation_snapshots"] == []
    assert rid not in job_queue.jobs


@pytest.mark.parametrize("shape", ["explicit", "mcp"], ids=["engine_mode=monolith", "mcp-payload"])
def test_monolith_failure_path_unchanged(env, monkeypatch, shape):
    """Guard: a failed monolith turn ends ``error`` with the exception's own text,
    the exception still propagates, the lock is released unconditionally, and the
    rollback machinery is never touched."""
    sid, rid = _monolith_request(env, shape)
    boom = RuntimeError("MK-monolith model call failed: 403")
    service = _MonolithService(fail_with=boom)
    monkeypatch.setattr(chat_service_module, "_chat_service_instance", service)
    used = _forbid_rollback_machinery(monkeypatch)
    writes = _spy_writes(monkeypatch)
    payload = monolith_payload(sid, shape)
    track(rid, payload)
    before = env.tables()

    raised = run_job(rid, payload)

    assert raised is boom, f"the monolith failure did not propagate unchanged: {raised!r}"
    assert used == []
    assert writes[0] == (
        "update_chat_request_status",
        {"request_id": rid, "status": "running", "error": None},
    )
    assert writes[-1] == ("release_session_lock", {"session_id": sid, "request_id": None})
    after = env.tables()
    row = _one(after["chat_requests"], request_id=rid)
    assert row["completed_at"] is not None
    assert _without(row, ("completed_at",)) == _without(
        dict(
            _one(before["chat_requests"], request_id=rid),
            status="error",
            error_message="MK-monolith model call failed: 403",
            rollback_outcome=None,
        ),
        ("completed_at",),
    )
    assert _lock_fields(env.rb.session_row(sid)) == (False, None, None)
    _assert_tables_equal(before, after, exclude=("chat_requests", "user_sessions"))
    assert rid not in job_queue.jobs

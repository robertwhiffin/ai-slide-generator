# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Task 3b: a stopped turn's messages, progress, session fields, images, title and
save point never land.

Once a turn's ``chat_requests`` row is terminal, every one of these writers must
refuse (the Task 2 fence), so the graph thread that keeps running after a stop, the
title thread and the image pool change nothing:

* ``SessionManager.add_message`` -- fenced from the request-id ``ContextVar`` ONLY.
  The monolith passes an explicit ``request_id`` too, with no ContextVar, and its
  writes must behave exactly as today
  (``test_monolith_add_message_after_completion_still_lands``).
* ``SessionManager.record_chat_request_progress`` -- its conditional ``UPDATE``
  matches only a live row: ``False`` and ``progress_json`` unchanged after a stop.
* ``SessionManager.set_genie_one_conversation_id`` -- fenced before its row lock.
* ``SessionManager.rename_session`` / ``update_session`` -- ``request_id=`` and
  ``allow_completed=`` (the title thread can outlive the 10 s join, so a title
  arriving after ``completed`` must still land).
* ``SessionManager.create_version`` and ``ChatService.create_save_point`` --
  ``request_id=``; the graph turn's save point passes it.
* ``image_generation_tool.save_to_library`` -- fenced, AND the jobs on ``_POOL``
  carry the turn's context: a pool thread has no ContextVar, so without the copy
  the fence is a silent no-op (``test_image_save_through_real_pool_*``).
* ``gateway_tool.make_image_saver``'s ``save`` -- runs in the node's own thread
  (PLAN-CORRECTIONS C6), so fencing it is enough.

The pairs follow Task 3a (``test_generation_fence_writers.py``, whose helpers this
module reuses): ``..._refused_after_cancel`` raises ``TurnFencedError`` (or returns
the writer's own "nothing stored" value) and EVERY row of EVERY table is
byte-identical afterwards; ``..._lands_while_live`` lands AND the request-row claim
is the first write of the writer's own transaction.

``TestAnAbandonedTurnStops`` is the ``except TurnFencedError: raise`` audit for
these writers: ``_say`` swallows every exception, and on a deck-level change the
architect goes on from its refused message to one re-review model call per
committed slide.

``TestARefusedWriteEndsTheToolLoop`` and ``TestAnswerToolCall`` pin the controller's
ruling for the architect's tools: a refused write inside the runtime's tool loop (an
image save, a Gateway image save, either tool's progress row) ENDS the turn.  It is
never answered to the model in-band, and the architect makes no tool-less fallback
call after it.  Any other tool error is still answered in-band, as today.
``TestARefusedWriteEndsTheAnalystLoop`` pins the same for the data analyst (Genie
One's progress row, a Gateway tool's progress row, no fallback call).

Real SQLite schema throughout (``conftest_graph``); only the models, the brand
resolvers, the image generator and the title model are stubbed.
"""
from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from PIL import Image
from pydantic import BaseModel

from src.api.schemas.streaming import StreamEventType
from src.api.services.chat_service import ChatService
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import SessionManager, get_session_manager
from src.database.models.session import UserSession
from src.domain.skill_io import OUTPUT_SCHEMAS, AnalystOutput, ArchitectOutput
from src.services import image_generation as image_generation_service
from src.services.agent_runtime import AgentModelConfiguration, DatabricksModelAdapter
from src.services.agent_tools import image_generation_tool as image_tool_module
from src.services.agent_tools.gateway_tool import make_image_saver
from src.services.agent_tools.image_generation_tool import (
    BUDGET_SECONDS,
    MAX_CALLS_PER_TURN,
    MAX_CONCURRENT,
    MAX_IMAGES_PER_TURN,
    ImageGenerationAgentTool,
    ImageGenerationArgs,
    ImageToolContext,
    save_to_library,
)
from src.services.agent_tools.registry import GENIE_TOOL_NAME
from src.services.agent_tools.toolset import AgentToolset
from src.services.generation_fence import TurnFencedError
from src.services.graph import nodes
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from src.services.image_generation import ENV_FLAG, GeneratedImage, ImageGenerator
from tests.fixtures.graph_tool_runtime import install_runtime, turn_state
from tests.fixtures.tool_call_doubles import tool_call_reply
from tests.unit.conftest_graph import (  # noqa: F401 -- fixtures
    graph_env,
    graph_env_threadsafe,
    make_spec,
    review_out,
)
from tests.unit.test_data_analyst_genie_one import (
    GENIE_ONE_ONLY,
    Q1,
    _analyst_state,
    _Replay,
    _serve,
    _set_agent_config,
    _sign_in,
    _success,
    q1_replies,
)
from tests.unit.test_generation_fence_writers import (
    _THREE,
    _WRITE_RE,
    _assert_claim_opens_the_write,
    _assert_unchanged,
    _in_turn,
    _owner,
    _set_status,
    _snapshot,
    _transactions,
    _writes,
)
from tests.unit.test_graph_gateway_mcp import (
    EXPORT,
    LAKEDRAW,
    LAKEDRAW_ROW,
    LAKEDRAW_TOOLS,
    WEB,
    WEB_ANALYST_ROW,
    _entry,
    _export_result,
    _gateway_deck,
    _Service,
    _web_result,
    _web_tools,
)

USER = "turn-author@example.com"
TITLE = "MK-Generated Session Title"
LATE = "MK-LATE-WRITE"
#: How long a test waits for a thread it started (the title thread, the image pool).
THREAD_WAIT = 15.0

_ROW_LOCK_SELECT_RE = re.compile(r"^\s*SELECT\b.*\bFROM\s+user_sessions\b", re.I | re.S)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    """Every test starts with no request id bound; the old value is put back after."""
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


@pytest.fixture(autouse=True)
def _no_real_gateway(monkeypatch) -> None:
    """A real ``ImageGenerator`` would reach the Gateway with the developer's credentials."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unit tests must never reach the real Gateway")

    monkeypatch.setattr(image_generation_service, "get_system_client", refuse)


def _route_core_db(env, monkeypatch):
    """Point ``src.core.database.get_db_session`` at *env*'s database as well.

    ``graph_env`` patches the module-level ``get_db_session`` of the graph's own
    writers; the image tool, the Gateway saver and ``chat_service``'s lazy imports
    call the real one, which reads ``get_session_local``.
    """
    monkeypatch.setattr("src.core.database.get_session_local", lambda: env.factory)
    return env


@pytest.fixture
def env(graph_env, monkeypatch):
    return _route_core_db(graph_env, monkeypatch)


@pytest.fixture
def threaded_env(graph_env_threadsafe, monkeypatch):
    """File-backed: the title thread and the image pool write from other threads."""
    return _route_core_db(graph_env_threadsafe, monkeypatch)


def _request(env, status: str) -> str:
    """A ``chat_requests`` row for this session in *status* (seeded ``running``)."""
    rid = env.seed_running_request(f"req-{uuid.uuid4().hex[:16]}")
    if status != "running":
        _set_status(env, rid, status)
    return rid


def _request_row(env, rid: str) -> Dict[str, Any]:
    rows = [r for r in _snapshot(env.engine)["chat_requests"] if r["request_id"] == rid]
    assert len(rows) == 1, f"expected one chat_requests row for {rid}: {rows}"
    return rows[0]


def _session_row(env) -> Dict[str, Any]:
    rows = [
        r for r in _snapshot(env.engine)["user_sessions"] if r["session_id"] == env.session_id
    ]
    assert len(rows) == 1
    return rows[0]


def _new_rows(before, after, table: str) -> List[Dict[str, Any]]:
    return [row for row in after[table] if row not in before[table]]


def _fence_sql(transactions: List[List[str]]) -> List[str]:
    return [
        s.strip()[:100]
        for t in transactions
        for s in _writes(t)
        if _WRITE_RE.match(s).group(1).lower() == "chat_requests"
    ]


def _assert_claim_precedes_the_row_lock(transactions: List[List[str]]) -> None:
    """In the transaction writing ``user_sessions``, the claim comes before the
    ``SELECT ... FOR UPDATE`` of the session row (SQLite drops ``FOR UPDATE``; the
    SELECT is still there).  Taken after it, a writer holding the session row would
    wait on the request row the rollback holds while the rollback waits for the
    session row: the lock order P1 exists for."""
    writing = [
        t for t in transactions
        if any(_WRITE_RE.match(s).group(1).lower() == "user_sessions" for s in _writes(t))
    ]
    assert writing, "no transaction wrote user_sessions: the write did not land"
    for statements in writing:
        claim_at = next(
            (i for i, s in enumerate(statements) if s in _writes(statements)
             and _WRITE_RE.match(s).group(1).lower() == "chat_requests"),
            None,
        )
        lock_at = next(
            (i for i, s in enumerate(statements) if _ROW_LOCK_SELECT_RE.match(s)), None
        )
        assert claim_at is not None, "the user_sessions write was not fenced"
        assert lock_at is not None, "no SELECT of the session row in its own write"
        assert claim_at < lock_at, (
            "the session row was read for update before the request-row claim: "
            f"{[s.strip()[:60] for s in statements[: lock_at + 1]]}"
        )


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (24, 16), (20, 120, 200, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _generated() -> GeneratedImage:
    return GeneratedImage(
        data=_png(),
        mime="image/png",
        ext="png",
        model="fake-image-model",
        preset_id="illustration",
        revised_prompt=None,
        latency_s=0.01,
        usage=None,
    )


def _set_genie_one(env, conversation_id: str) -> None:
    db = env.factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        owner.agent_config = {"tools": [{"type": "genie_one", "conversation_id": conversation_id}]}
        db.commit()
    finally:
        db.close()


# -- the writers, each called the way its turn caller calls it ----------------


def _add_message(env, request_id: Optional[str]) -> None:
    get_session_manager().add_message(
        env.session_id,
        role="assistant",
        content=LATE,
        message_type="llm_response",
        request_id=request_id,
    )


def _deck_dict(env) -> Dict[str, Any]:
    return {
        "title": "MK deck",
        "slides": [{"html": r.html, "slide_id": r.slide_id} for r in env.rows()],
        "slide_count": len(env.rows()),
    }


# ---------------------------------------------------------------------------
# add_message: fenced from the ContextVar only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "explicit", [True, False], ids=["graph-call-shape", "no-explicit-request-id"]
)
def test_add_message_refused_after_cancel(env, explicit):
    """The graph's ``_say`` / ``_surface_notice`` pass ``request_id=`` the ContextVar's
    value; the fence keys on the ContextVar, so a call without the argument is
    refused as well."""
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError) as excinfo:
            _add_message(env, rid if explicit else None)

    assert excinfo.value.request_id == rid
    _assert_unchanged(before, _snapshot(env.engine))


def test_add_message_lands_while_live(env):
    rid = _request(env, "running")
    before = _snapshot(env.engine)

    with _in_turn(rid), _transactions(env.engine) as transactions:
        _add_message(env, rid)

    after = _snapshot(env.engine)
    new = _new_rows(before, after, "session_messages")
    assert len(new) == 1, f"expected one new message row, got {new}"
    assert new[0] == {
        "id": new[0]["id"],
        "session_id": _owner(env).id,
        "role": "assistant",
        "content": LATE,
        "created_at": new[0]["created_at"],
        "message_type": "llm_response",
        "metadata_json": None,
        "request_id": rid,
    }
    _assert_claim_opens_the_write(transactions, "session_messages")
    assert after["chat_requests"] == before["chat_requests"]


@pytest.mark.parametrize("status", ["completed", "error", "cancelled"])
def test_monolith_add_message_after_completion_still_lands(env, status):
    """The monolith (Legacy / MCP) tags its rows with an explicit ``request_id`` and
    never binds the ContextVar.  Its writes behave exactly as today: the row is
    written whatever the request's status, and no fence SQL is issued."""
    rid = _request(env, status)
    before = _snapshot(env.engine)

    with _transactions(env.engine) as transactions:
        _add_message(env, rid)

    new = _new_rows(before, _snapshot(env.engine), "session_messages")
    assert [(r["content"], r["request_id"]) for r in new] == [(LATE, rid)], (
        f"the monolith's message was not written for a {status} request"
    )
    assert _fence_sql(transactions) == [], (
        f"a monolith add_message issued fence SQL: {_fence_sql(transactions)}"
    )


# ---------------------------------------------------------------------------
# record_chat_request_progress: the conditional UPDATE matches only a live row
# ---------------------------------------------------------------------------


def _progress(seq: int, phase: str = "building") -> Dict[str, Any]:
    return {"seq": seq, "phase": phase, "covered": [0, 1], "slides": {"0": "building"}}


@pytest.mark.parametrize("status", ["cancelled", "error"])
@pytest.mark.parametrize("bound", [True, False], ids=["in-turn", "no-context"])
def test_record_chat_request_progress_refused_after_cancel(env, status, bound):
    """A late progress report from an abandoned slide branch: rowcount 0, so the
    call returns False and the row keeps the stage it had when the turn stopped.
    It does not raise: ``progress._persist`` is a side channel and the guard is the
    UPDATE's own predicate, so it holds with or without the ContextVar."""
    rid = _request(env, "running")
    manager = get_session_manager()
    assert manager.record_chat_request_progress(rid, 1, _progress(1, "planning")) is True
    _set_status(env, rid, status)
    before = _snapshot(env.engine)

    with _in_turn(rid if bound else None):
        stored = manager.record_chat_request_progress(rid, 2, _progress(2))

    assert stored is False, "a progress snapshot was stored on a stopped turn's row"
    after = _snapshot(env.engine)
    assert json.loads(_request_row(env, rid)["progress_json"]) == _progress(1, "planning")
    _assert_unchanged(before, after)


@pytest.mark.parametrize("status", ["pending", "running"])
def test_record_chat_request_progress_lands_while_live(env, status):
    rid = _request(env, status)
    before = _request_row(env, rid)

    with _in_turn(rid):
        stored = get_session_manager().record_chat_request_progress(rid, 4, _progress(4))

    assert stored is True
    assert _request_row(env, rid) == {
        **before,
        "progress_json": json.dumps(_progress(4)),
        "progress_seq": 4,
    }


# ---------------------------------------------------------------------------
# set_genie_one_conversation_id
# ---------------------------------------------------------------------------


def test_set_genie_one_conversation_id_refused_after_cancel(env):
    _set_genie_one(env, "conv-before-stop")
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError) as excinfo:
            get_session_manager().set_genie_one_conversation_id(env.session_id, "conv-late")

    assert excinfo.value.request_id == rid
    _assert_unchanged(before, _snapshot(env.engine))


def test_set_genie_one_conversation_id_lands_while_live(env):
    _set_genie_one(env, "conv-before")
    rid = _request(env, "running")

    with _in_turn(rid), _transactions(env.engine) as transactions:
        get_session_manager().set_genie_one_conversation_id(env.session_id, "conv-live")

    assert _session_row(env)["agent_config"]["tools"] == [
        {"type": "genie_one", "conversation_id": "conv-live"}
    ]
    _assert_claim_opens_the_write(transactions, "user_sessions")
    _assert_claim_precedes_the_row_lock(transactions)


# ---------------------------------------------------------------------------
# rename_session / update_session: request_id= and allow_completed=
# ---------------------------------------------------------------------------


def test_rename_session_refused_after_cancel(env):
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with pytest.raises(TurnFencedError) as excinfo:
        get_session_manager().rename_session(env.session_id, TITLE, request_id=rid)

    assert excinfo.value.request_id == rid
    _assert_unchanged(before, _snapshot(env.engine))


def test_update_session_refused_after_cancel(env):
    env.seed_slides(list(_THREE))
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with pytest.raises(TurnFencedError):
        get_session_manager().update_session(
            env.session_id, title=TITLE, slide_count=9, request_id=rid
        )

    _assert_unchanged(before, _snapshot(env.engine))


def test_rename_session_lands_while_live(env):
    rid = _request(env, "running")

    with _transactions(env.engine) as transactions:
        get_session_manager().rename_session(env.session_id, TITLE, request_id=rid)

    assert _session_row(env)["title"] == TITLE
    _assert_claim_opens_the_write(transactions, "user_sessions")


def test_rename_session_lands_after_completion_with_allow_completed(env):
    rid = _request(env, "completed")

    with _transactions(env.engine) as transactions:
        get_session_manager().rename_session(
            env.session_id, TITLE, request_id=rid, allow_completed=True
        )

    assert _session_row(env)["title"] == TITLE
    _assert_claim_opens_the_write(transactions, "user_sessions")


def test_rename_session_refused_after_completion_without_allow_completed(env):
    rid = _request(env, "completed")
    before = _snapshot(env.engine)

    with pytest.raises(TurnFencedError):
        get_session_manager().rename_session(env.session_id, TITLE, request_id=rid)

    _assert_unchanged(before, _snapshot(env.engine))


def test_allow_completed_still_refuses_a_cancelled_turn(env):
    """``allow_completed`` admits ``completed`` only: a title arriving after a STOP
    must not overwrite the title the rollback restored."""
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with pytest.raises(TurnFencedError):
        get_session_manager().rename_session(
            env.session_id, TITLE, request_id=rid, allow_completed=True
        )

    _assert_unchanged(before, _snapshot(env.engine))


# ---------------------------------------------------------------------------
# create_version / create_save_point: request_id=
# ---------------------------------------------------------------------------


def test_create_version_refused_after_cancel(env):
    env.seed_slides(list(_THREE))
    rid = _request(env, "cancelled")
    deck = _deck_dict(env)
    before = _snapshot(env.engine)

    with pytest.raises(TurnFencedError) as excinfo:
        get_session_manager().create_version(
            env.session_id, "Generated 3 slide(s)", deck, request_id=rid
        )

    assert excinfo.value.request_id == rid
    _assert_unchanged(before, _snapshot(env.engine))


def test_create_version_lands_while_live(env):
    env.seed_slides(list(_THREE))
    rid = _request(env, "running")
    deck = _deck_dict(env)
    before = _snapshot(env.engine)

    with _transactions(env.engine) as transactions:
        get_session_manager().create_version(
            env.session_id, "Generated 3 slide(s)", deck, request_id=rid
        )

    new = _new_rows(before, _snapshot(env.engine), "slide_deck_versions")
    assert [(r["version_number"], r["description"], json.loads(r["deck_json"])) for r in new] == [
        (1, "Generated 3 slide(s)", deck)
    ]
    _assert_claim_opens_the_write(transactions, "slide_deck_versions")


def test_create_save_point_passes_the_request_id_to_create_version(env):
    env.seed_slides(list(_THREE))
    rid = _request(env, "cancelled")
    service = ChatService()
    deck = service._get_or_load_deck(env.session_id)
    assert deck is not None and len(deck.slides) == 3
    before = _snapshot(env.engine)

    with pytest.raises(TurnFencedError):
        service.create_save_point(
            env.session_id, "Generated 3 slide(s)", deck=deck, request_id=rid
        )

    _assert_unchanged(before, _snapshot(env.engine))


# ---------------------------------------------------------------------------
# The graph turn's own save point and title (``_send_message_streaming_graph``)
# ---------------------------------------------------------------------------


class _Turn:
    """``_send_message_streaming_graph`` driven with ``invoke_graph`` and the title
    model replaced.  The title model waits for :attr:`release_title`, so a test
    decides when the title thread writes; :attr:`title_written` is set once its
    ``rename_session`` call has returned or raised (the real method runs)."""

    def __init__(self, env, monkeypatch, *, on_graph=None):
        self.env = env
        self.release_title = threading.Event()
        self.title_written = threading.Event()
        self.title_outcomes: List[Any] = []
        self.thread_errors: List[BaseException] = []

        def fake_invoke_graph(session_id, state, *, emitter, request_id=None):
            if on_graph is not None:
                on_graph()

        def fake_title(message, model):
            self.release_title.wait(timeout=THREAD_WAIT)
            return TITLE

        real_rename = SessionManager.rename_session

        def watched_rename(manager, *args, **kwargs):
            try:
                result = real_rename(manager, *args, **kwargs)
                self.title_outcomes.append(result)
                return result
            except BaseException as exc:
                self.title_outcomes.append(exc)
                raise
            finally:
                self.title_written.set()

        monkeypatch.setattr("src.services.graph.builder.invoke_graph", fake_invoke_graph)
        monkeypatch.setattr("src.api.services.chat_service.generate_session_title", fake_title)
        monkeypatch.setattr(
            "src.api.services.session_naming.build_session_title_model", MagicMock()
        )
        monkeypatch.setattr(SessionManager, "rename_session", watched_rename)
        monkeypatch.setattr(
            threading, "excepthook", lambda args: self.thread_errors.append(args.exc_value)
        )
        self.service = ChatService()

    def run(self, request_id, *, is_first_message, on_event=None):
        """All events, and what the generator raised (None when it ended cleanly)."""
        events: List[Any] = []
        raised: Optional[BaseException] = None
        stream = self.service._send_message_streaming_graph(
            self.env.session_id,
            "Build me a deck about Q3",
            is_first_message=is_first_message,
            request_id=request_id,
        )
        try:
            for event in stream:
                events.append(event)
                if on_event is not None:
                    on_event(event)
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            raised = exc
        return events, raised


def _turn_stopped(exc: Optional[BaseException]) -> bool:
    """The generator's own stop signal (Tasks 5/6 raise it at the seal), not a failure."""
    from src.services.generation_fence import TurnStopped

    return isinstance(exc, TurnStopped)


def test_graph_turn_save_point_after_cancel_is_dropped(env, monkeypatch):
    """Stop pressed as the graph finished, right before the save point: no
    "Generated N slide(s)" version may be left behind on a deck the rollback
    restores.  The generator thread has no ContextVar, so this holds only if
    ``_send_message_streaming_graph`` passes ``request_id=`` to the save point; a
    refused save point is not a turn failure."""
    env.seed_slides(list(_THREE))
    rid = _request(env, "running")
    turn = _Turn(env, monkeypatch)
    at_cancel: Dict[str, Any] = {}
    real_load = ChatService._get_or_load_deck

    def load_then_stop(session_id):
        deck = real_load(turn.service, session_id)
        _set_status(env, rid, "cancelled")
        at_cancel["tables"] = _snapshot(env.engine)
        return deck

    turn.service._get_or_load_deck = load_then_stop

    events, raised = turn.run(rid, is_first_message=False)

    assert "tables" in at_cancel, "the save point's deck was never loaded"
    assert raised is None or _turn_stopped(raised), (
        f"a refused save point failed the turn: {raised!r}"
    )
    _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))


def test_graph_turn_save_point_lands_while_live(env, monkeypatch):
    env.seed_slides(list(_THREE))
    rid = _request(env, "running")
    turn = _Turn(env, monkeypatch)
    before = _snapshot(env.engine)

    with _transactions(env.engine) as transactions:
        events, raised = turn.run(rid, is_first_message=False)

    assert raised is None, f"the turn failed: {raised!r}"
    assert events[-1].type == StreamEventType.COMPLETE
    new = _new_rows(before, _snapshot(env.engine), "slide_deck_versions")
    assert [r["description"] for r in new] == ["Generated 3 slide(s)"]
    _assert_claim_opens_the_write(transactions, "slide_deck_versions")


def test_title_thread_write_after_cancel_is_dropped(threaded_env, monkeypatch, caplog):
    """Stop pressed while the title model was still running.  Its thread copied
    the context before ``invoke_graph`` bound the request id, so it must pass the id
    to ``rename_session`` itself; the refused title is dropped quietly (INFO, not a
    WARNING with a traceback) and nothing escapes the thread."""
    env = threaded_env
    rid = _request(env, "running")
    at_cancel: Dict[str, Any] = {}

    def stop_during_the_graph():
        _set_status(env, rid, "cancelled")
        at_cancel["tables"] = _snapshot(env.engine)
        turn.release_title.set()

    turn = _Turn(env, monkeypatch, on_graph=stop_during_the_graph)

    with caplog.at_level(logging.INFO, logger="src.api.services.chat_service"):
        events, raised = turn.run(rid, is_first_message=True)
        assert turn.title_written.wait(timeout=THREAD_WAIT), "the title thread never wrote"

    assert "tables" in at_cancel
    assert raised is None or _turn_stopped(raised), f"the turn failed: {raised!r}"
    _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))
    assert StreamEventType.SESSION_TITLE not in [e.type for e in events], (
        "a SESSION_TITLE event was sent for a title that was refused"
    )
    assert turn.thread_errors == [], f"an exception escaped a thread: {turn.thread_errors}"
    warnings = [
        r.getMessage() for r in caplog.records
        if r.funcName == "run_title_gen" and r.levelno >= logging.WARNING
    ]
    assert warnings == [], f"a refused title was logged as a failure: {warnings}"


def test_title_after_completed_still_lands(threaded_env, monkeypatch):
    """The title thread is joined for only 10 s, so a slow title can arrive after
    the job marked the request ``completed``; it must still land."""
    env = threaded_env
    rid = _request(env, "running")
    turn = _Turn(env, monkeypatch)

    def complete_then_release(event):
        if event.type == StreamEventType.COMPLETE:
            _set_status(env, rid, "completed")
            turn.release_title.set()

    with _transactions(env.engine) as transactions:
        events, raised = turn.run(rid, is_first_message=True, on_event=complete_then_release)
        assert turn.title_written.wait(timeout=THREAD_WAIT), "the title thread never wrote"

    assert raised is None, f"the turn failed: {raised!r}"
    assert _session_row(env)["title"] == TITLE, (
        f"the title did not land after completion: {turn.title_outcomes}"
    )
    _assert_claim_opens_the_write(transactions, "user_sessions")


# ---------------------------------------------------------------------------
# Images: save_to_library (direct and through the real _POOL) and the Gateway saver
# ---------------------------------------------------------------------------


def _save_to_library() -> str:
    return save_to_library(
        _generated(), owner=USER, prompt="a calm harbour", category="content",
        tags=["ai_generated"],
    )


def test_save_to_library_refused_after_cancel(env):
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError):
            _save_to_library()

    _assert_unchanged(before, _snapshot(env.engine))


def test_save_to_library_lands_while_live(env):
    rid = _request(env, "running")
    before = _snapshot(env.engine)

    with _in_turn(rid), _transactions(env.engine) as transactions:
        token = _save_to_library()

    new = _new_rows(before, _snapshot(env.engine), "image_assets")
    assert [(r["token"], r["uploaded_by"]) for r in new] == [(token, USER)]
    _assert_claim_opens_the_write(transactions, "image_assets")


class _FakeGenerator:
    """The ``generator_factory`` double: returns one image at once, records the thread."""

    def __init__(self) -> None:
        self.threads: List[str] = []

    def factory(self) -> "_FakeGenerator":
        return self

    def generate(self, prompt, preset_id, model=None, quality=None, *, timeout_s=None):
        self.threads.append(threading.current_thread().name)
        return _generated()


def _image_tool(fake: _FakeGenerator) -> ImageGenerationAgentTool:
    return ImageGenerationAgentTool(
        ImageToolContext(
            owner=USER,
            session_id=None,
            on_call=lambda kind, n: None,
            calls_left=MAX_CALLS_PER_TURN,
            images_left=MAX_IMAGES_PER_TURN,
            seconds_left=BUDGET_SECONDS,
            deadline_at=None,
            generator_factory=fake.factory,
        )
    )


def _run_image_tool(tool: ImageGenerationAgentTool) -> str:
    return tool.run(
        ImageGenerationArgs(prompt="a calm harbour", kind="illustration", count=1),
        remaining_seconds=120.0,
    )


def test_image_save_through_real_pool_refused_after_cancel(threaded_env):
    """The image jobs run on ``_POOL``, a plain ``ThreadPoolExecutor``: without a
    context copy at submit the pool thread sees no request id, the fence in
    ``save_to_library`` is a silent no-op, and the image is saved after the stop.
    The refusal is raised out of ``run`` (the tool loop ruling), never turned into
    "not generated" text."""
    env = threaded_env
    rid = _request(env, "cancelled")
    fake = _FakeGenerator()
    tool = _image_tool(fake)
    before = _snapshot(env.engine)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError):
            _run_image_tool(tool)

    assert len(fake.threads) == 1 and fake.threads[0].startswith("chat-image-gen"), (
        f"the generation did not run on the real pool: {fake.threads}"
    )
    _assert_unchanged(before, _snapshot(env.engine))
    assert tool.saved_tokens() == []


def test_image_save_through_real_pool_lands_while_live(threaded_env):
    env = threaded_env
    rid = _request(env, "running")
    fake = _FakeGenerator()
    tool = _image_tool(fake)
    before = _snapshot(env.engine)

    with _in_turn(rid), _transactions(env.engine) as transactions:
        _run_image_tool(tool)

    new = _new_rows(before, _snapshot(env.engine), "image_assets")
    assert [r["token"] for r in new] == tool.saved_tokens() and len(new) == 1
    _assert_claim_opens_the_write(transactions, "image_assets")


def _gateway_save() -> str:
    save = make_image_saver(user=USER, service_name="lakedraw", display_name="LakeDraw")
    return save(_png(), "image/png")


def test_gateway_image_save_refused_after_cancel(env):
    rid = _request(env, "cancelled")
    before = _snapshot(env.engine)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError):
            _gateway_save()

    _assert_unchanged(before, _snapshot(env.engine))


def test_gateway_image_save_lands_while_live(env):
    rid = _request(env, "running")
    before = _snapshot(env.engine)

    with _in_turn(rid), _transactions(env.engine) as transactions:
        token = _gateway_save()

    new = _new_rows(before, _snapshot(env.engine), "image_assets")
    assert [(r["token"], r["uploaded_by"], r["tags"]) for r in new] == [
        (token, USER, ["gateway_mcp", "lakedraw"])
    ]
    _assert_claim_opens_the_write(transactions, "image_assets")


# ---------------------------------------------------------------------------
# Outside a turn: no request id, no fence SQL, everything writes as today
# ---------------------------------------------------------------------------


def test_session_writers_unfenced_outside_a_turn(env):
    """Manual renames, save points from the editor, uploads, the monolith: no
    request id, so no fence SQL -- even beside a cancelled request of this session,
    so a fence keyed on "this session has a stopped turn" would show here."""
    env.seed_slides(list(_THREE))
    _set_genie_one(env, "conv-before")
    _request(env, "cancelled")
    manager = get_session_manager()
    before = _snapshot(env.engine)

    with _transactions(env.engine) as transactions:
        manager.add_message(env.session_id, role="assistant", content=LATE)
        manager.set_genie_one_conversation_id(env.session_id, "conv-manual")
        manager.rename_session(env.session_id, TITLE)
        manager.create_version(env.session_id, "Manual save", _deck_dict(env))
        _save_to_library()
        _gateway_save()

    after = _snapshot(env.engine)
    assert [r["content"] for r in _new_rows(before, after, "session_messages")] == [LATE]
    assert _session_row(env)["title"] == TITLE
    assert _session_row(env)["agent_config"]["tools"][0]["conversation_id"] == "conv-manual"
    assert len(_new_rows(before, after, "slide_deck_versions")) == 1
    assert len(_new_rows(before, after, "image_assets")) == 2
    assert _fence_sql(transactions) == [], (
        f"a writer outside a turn issued fence SQL: {_fence_sql(transactions)}"
    )


# ---------------------------------------------------------------------------
# The except-TurnFencedError audit: an abandoned turn ends at its refused message
# ---------------------------------------------------------------------------


NEW_AUDIENCE = "the CFO, not engineers"


class TestAnAbandonedTurnStops:
    def test_abandoned_turn_stops_at_refused_message_write(self, env):
        """Stop pressed while the architect plans a deck-level change.

        The architect's message is its first write after the model call
        (``_say_architect_message``, ``nodes.py:~5258``), and ``_say`` swallows every
        exception.  On a deck-level change the node then re-reviews every
        committed slide, one model call each (``rereview_committed_slides``), before
        the deck-level write that 3a fenced.  The refused message must end the node:
        the only model call is the architect's own.
        """
        write_deck_level_columns(
            env.session_id, deck_spec=make_spec((0, 1, 2)).to_json(), modified_by=USER
        )
        env.seed_slides(list(_THREE))
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}
        new_spec = make_spec((0, 1, 2)).model_copy(update={"audience": NEW_AUDIENCE})

        def architect(payload):
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return ArchitectOutput(
                intent="build",
                message="Retargeting the deck at the CFO.",
                target_positions=[],
                deck_spec=new_spec,
            )

        env.skills.set("architect", architect)
        env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

        raised: Optional[BaseException] = None
        updates: Any = None
        with _in_turn(rid):
            try:
                updates = nodes.architect_node(
                    env.state(architect_message="pitch this to the CFO instead")
                )
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert "tables" in at_cancel, "the architect model was never called"
        assert [c["name"] for c in env.skills.calls] == ["architect"], (
            "model calls started after the architect's message write was refused: "
            f"{[c['name'] for c in env.skills.calls]}"
        )
        assert isinstance(raised, TurnFencedError), (
            f"the refused message did not end the node; it raised {raised!r} and "
            f"returned {updates!r}"
        )
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))


# ---------------------------------------------------------------------------
# A refused write inside the tool loop ENDS the turn (controller ruling on 3b)
# ---------------------------------------------------------------------------
#
# The architect's tools run inside the runtime's bounded loop, whose
# ``_answer_tool_call`` answers every tool exception to the model in-band.  A
# refused write there must not be answered: it must end the loop, the node and the
# turn, so no further model round (and no tool-less fallback call) starts.
#
# The runtime below runs the REAL ``DatabricksModelAdapter``: ``invoke_with_tools``
# when a call carries a toolset, the plain structured ``invoke`` when it does not.
# Only the chat model is a double, and it counts its rounds.

CONFIGURATION = AgentModelConfiguration(
    endpoint_name="system.ai.claude-opus-5-5", temperature=0.5, max_tokens=4096, top_p=0.95
)
DISCUSS = ArchitectOutput(intent="discuss", message="Here is an option for the diagram.")
IMAGE_TOOL = "generate_image"


class _CountingModel:
    """The chat model behind the real loop: one reply per round from *script* (the
    last step repeats, so an extra round is counted, never an error); a step is an
    ``AIMessage`` or a callable returning one."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.rounds: List[Optional[str]] = []
        self.agent: Optional[str] = None

    def bind_tools(self, tools, **kwargs):
        return RunnableLambda(self._reply)

    def _reply(self, messages: Any) -> AIMessage:
        self.rounds.append(self.agent)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return step() if callable(step) else step


class _LoopRuntime:
    """Stands in for ``AgentRuntime``; the adapter and its tool loop are production's."""

    def __init__(self, model: _CountingModel) -> None:
        self.model = model
        self.calls: List[tuple] = []
        self.adapter = DatabricksModelAdapter(
            model_factory=lambda **kwargs: model, client_factory=lambda: object()
        )

    def run(self, name, graph_release_id, payload, assembly_context):
        toolset = assembly_context.toolset
        self.calls.append((name, toolset is not None))
        self.model.agent = name
        schema = OUTPUT_SCHEMAS[name]
        if toolset is None:
            output = self.adapter.invoke(
                agent_key=name, configuration=CONFIGURATION, schema=schema, prompt="p"
            )
        else:
            output = self.adapter.invoke_with_tools(
                agent_key=name,
                configuration=CONFIGURATION,
                schema=schema,
                prompt="p",
                toolset=toolset,
            )
        return SimpleNamespace(output=output)


def _tool_call(name: str, args: Dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": "call_tool", "type": "tool_call"}],
    )


def _image_call() -> AIMessage:
    return _tool_call(IMAGE_TOOL, {"prompt": "a calm harbour", "kind": "illustration", "count": 1})


def _gateway_call() -> AIMessage:
    return _tool_call(EXPORT, {"diagram_id": "dgm-1"})


def _final() -> AIMessage:
    return tool_call_reply(ArchitectOutput, DISCUSS)


def _run_architect_turn(env, rid: str):
    """``architect_node`` once, under *rid*; what it raised (or None) and returned."""
    raised: Optional[BaseException] = None
    updates: Any = None
    with _in_turn(rid):
        try:
            updates = nodes.architect_node(turn_state(env))
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            raised = exc
    return raised, updates


def _assert_the_loop_ended(
    runtime: _LoopRuntime, raised, updates, *, agent: str = "architect"
) -> None:
    assert runtime.model.rounds == [agent], (
        "a model round started after the refused write: "
        f"rounds={runtime.model.rounds}, runtime calls={runtime.calls}"
    )
    assert runtime.calls == [(agent, True)], (
        f"the {agent} was called again (a fallback call?): {runtime.calls}"
    )
    assert isinstance(raised, TurnFencedError), (
        f"the refused write did not end the turn; it raised {raised!r} and returned "
        f"{updates!r}"
    )


@pytest.fixture
def images_on(monkeypatch):
    """The image tool is available: the env flag on and no admin row (on)."""
    monkeypatch.setenv(ENV_FLAG, "1")


def _fake_generate(on_generate):
    def generate(self, prompt, preset_id, model=None, quality=None, *, timeout_s=None):
        on_generate()
        return _generated()

    return generate


def _free_image_slots() -> int:
    """How many of the process-wide image slots can be taken right now."""
    taken = image_tool_module._take_slots(MAX_CONCURRENT)
    for _ in range(taken):
        image_tool_module._SLOTS.release()
    return taken


class TestARefusedWriteEndsTheToolLoop:
    @pytest.mark.image_tool
    def test_refused_image_save_ends_the_architect_tool_loop(
        self, threaded_env, monkeypatch, images_on
    ):
        """Stop pressed while the image model ran.  The save that follows is refused
        on the pool thread; today that becomes "not generated" text, the model reads
        it and answers in a second round, and the turn goes on."""
        env = threaded_env
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}
        generated: List[str] = []

        def stop_while_generating():
            generated.append(threading.current_thread().name)
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)

        monkeypatch.setattr(ImageGenerator, "generate", _fake_generate(stop_while_generating))
        runtime = install_runtime(
            monkeypatch, _LoopRuntime(_CountingModel(_image_call(), _final()))
        )

        raised, updates = _run_architect_turn(env, rid)

        assert generated, "the image tool never ran: the test proves nothing"
        _assert_the_loop_ended(runtime, raised, updates)
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_refused_gateway_save_ends_the_architect_tool_loop(self, env, monkeypatch):
        """Stop pressed while the Gateway tool ran.  Its image is saved after the
        call returns; today the refused save becomes "[image not saved: ...]" and the
        model answers in a second round."""
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}

        def stop_during_the_call(name, arguments):
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)

        lakedraw = _Service(
            LAKEDRAW,
            LAKEDRAW_TOOLS,
            results={EXPORT: _export_result()},
            on_call=stop_during_the_call,
        )
        _gateway_deck(
            env,
            monkeypatch,
            entries=[_entry(LAKEDRAW, "LakeDraw")],
            rows=[LAKEDRAW_ROW],
            services=[lakedraw],
        )
        runtime = install_runtime(
            monkeypatch, _LoopRuntime(_CountingModel(_gateway_call(), _final()))
        )

        raised, updates = _run_architect_turn(env, rid)

        assert [name for name, _ in lakedraw.calls] == [EXPORT], (
            f"the Gateway tool was not called once: {lakedraw.calls}"
        )
        _assert_the_loop_ended(runtime, raised, updates)
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    @pytest.mark.image_tool
    def test_refused_image_progress_row_ends_the_loop_before_generating(
        self, threaded_env, monkeypatch, images_on
    ):
        """Stop pressed while the model chose to call the tool: the "Generating ..."
        progress row is the tool's first write.  Today ``on_call`` swallows its
        failure and the PAID generation starts.  No image slot may leak either: the
        slots are process-wide, and a leaked one makes later turns "busy"."""
        env = threaded_env
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}
        generated: List[str] = []

        def stop_then_call_the_tool():
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return _image_call()

        monkeypatch.setattr(
            ImageGenerator, "generate", _fake_generate(lambda: generated.append("generated"))
        )
        runtime = install_runtime(
            monkeypatch, _LoopRuntime(_CountingModel(stop_then_call_the_tool, _final()))
        )

        raised, updates = _run_architect_turn(env, rid)

        assert generated == [], "the image model was called after the turn was stopped"
        _assert_the_loop_ended(runtime, raised, updates)
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))
        assert _free_image_slots() == MAX_CONCURRENT, "a refused progress row leaked image slots"

    def test_refused_gateway_progress_row_ends_the_loop_before_calling(self, env, monkeypatch):
        """The Gateway tool's progress row ("LakeDraw · ...") is its first write; today
        ``run`` swallows its failure and calls the service anyway."""
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}
        lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, results={EXPORT: _export_result()})
        _gateway_deck(
            env,
            monkeypatch,
            entries=[_entry(LAKEDRAW, "LakeDraw")],
            rows=[LAKEDRAW_ROW],
            services=[lakedraw],
        )

        def stop_then_call_the_tool():
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return _gateway_call()

        runtime = install_runtime(
            monkeypatch, _LoopRuntime(_CountingModel(stop_then_call_the_tool, _final()))
        )

        raised, updates = _run_architect_turn(env, rid)

        assert lakedraw.calls == [], "the Gateway service was called after the turn was stopped"
        _assert_the_loop_ended(runtime, raised, updates)
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))


def _analyst_final() -> AIMessage:
    return tool_call_reply(AnalystOutput, _success())


def _run_analyst_turn(env, rid: str):
    """``data_analyst_node`` once, under *rid*; what it raised (or None) and returned."""
    raised: Optional[BaseException] = None
    updates: Any = None
    with _in_turn(rid):
        try:
            updates = nodes.data_analyst_node(
                _analyst_state(env, turn_started_at=time.time() - 5)
            )
        except Exception as exc:  # noqa: BLE001 - asserted by the caller
            raised = exc
    return raised, updates


class TestARefusedWriteEndsTheAnalystLoop:
    """The same ruling for the data analyst's tools: Genie One and its Gateway tools.

    The request is cancelled while the model chooses its tool, so the tool's
    progress row ("Asking Genie One: ...", "Web Search · ...") is the first
    refused write.  It must end the loop and the node: no question is sent, no
    service is called, no further model round starts and the analyst makes no
    fallback call (Genie One's own toolset, or none).
    """

    def test_refused_genie_one_progress_row_ends_the_loop_before_asking(
        self, env, monkeypatch
    ):
        """Today the Genie One tool swallows a failing progress row, so the question
        is still sent (an answer takes minutes) and the model reads the answer in a
        second round."""
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}
        _set_agent_config(env, env.session_id, GENIE_ONE_ONLY)
        _sign_in()
        genie = _Replay(q1_replies())
        _serve(monkeypatch, genie)

        def stop_then_ask():
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return _tool_call(GENIE_TOOL_NAME, {"question": Q1})

        runtime = install_runtime(
            monkeypatch, _LoopRuntime(_CountingModel(stop_then_ask, _analyst_final()))
        )

        raised, updates = _run_analyst_turn(env, rid)

        assert genie.asks() == [], (
            f"Genie One was asked after the turn was stopped: {genie.asks()}"
        )
        _assert_the_loop_ended(runtime, raised, updates, agent="data_analyst")
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_refused_gateway_progress_row_ends_the_analyst_without_a_fallback(
        self, env, monkeypatch
    ):
        """A Gateway tool's refused progress row leaves the loop (Task 3b).  Without
        the analyst's own re-raise, ``without_tools`` claims the failure as the
        Gateway pass's and the analyst calls the model again without tools."""
        rid = _request(env, "running")
        at_cancel: Dict[str, Any] = {}
        web = _Service(WEB, _web_tools(), results={"web_search": _web_result()})
        _gateway_deck(
            env,
            monkeypatch,
            entries=[_entry(WEB, "Web Search")],
            rows=[WEB_ANALYST_ROW],
            services=[web],
        )

        def stop_then_search():
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return _tool_call("web_search", {"query": "Databricks AI Gateway MCP services"})

        runtime = install_runtime(
            monkeypatch, _LoopRuntime(_CountingModel(stop_then_search, _analyst_final()))
        )

        raised, updates = _run_analyst_turn(env, rid)

        assert web.calls == [], "the Gateway service was called after the turn was stopped"
        _assert_the_loop_ended(runtime, raised, updates, agent="data_analyst")
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))


class _LookupArgs(BaseModel):
    question: str


class _RaisingTool:
    """An ``AgentTool`` whose run raises *error*."""

    name = "lookup"
    description = "Look something up."
    args_schema = _LookupArgs

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.runs = 0

    def run(self, args, *, remaining_seconds: float) -> str:
        self.runs += 1
        raise self.error


def _answer(tool: _RaisingTool) -> str:
    toolset = AgentToolset(tools=(tool,))
    toolset.start()
    return DatabricksModelAdapter._answer_tool_call(
        {"name": tool.name, "args": {"question": "q"}, "id": "c1", "type": "tool_call"},
        {tool.name: tool},
        toolset,
        budget_text="budget spent",
    )


class TestAnswerToolCall:
    """The loop's one choke point for tool errors."""

    def test_a_refused_write_in_a_tool_is_not_answered_in_band(self):
        tool = _RaisingTool(TurnFencedError("req-loop"))

        with pytest.raises(TurnFencedError) as excinfo:
            _answer(tool)

        assert tool.runs == 1
        assert excinfo.value.request_id == "req-loop"

    @pytest.mark.parametrize(
        "error",
        [RuntimeError("boom"), ValueError("bad value"), KeyError("k")],
        ids=["RuntimeError", "ValueError", "KeyError"],
    )
    def test_any_other_tool_error_is_still_answered_in_band(self, error):
        """The guard: only the refusal escapes.  ``TurnFencedError`` is a
        ``RuntimeError``, so a fix that let every ``RuntimeError`` through would
        fail turns that today recover from a tool's failure."""
        tool = _RaisingTool(error)

        text = _answer(tool)

        assert text.startswith(f"Tool error: {type(error).__name__}: "), text
        assert tool.runs == 1

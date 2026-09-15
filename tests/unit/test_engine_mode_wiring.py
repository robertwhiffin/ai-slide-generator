"""Engine-mode WIRING (ws4d D2): the six edit points that carry the mode.

Task 1 built `resolve_engine_mode` and gave it no call sites.  This suite pins
the call sites, and it exists because the plan's picture of the streaming path
was wrong in a way that ships a defect either direction.

The path, measured
------------------
`ChatService.send_message_streaming` has exactly TWO backend call sites and only
one of them is a route:

    src/api/routes/chat.py:~491     the streaming route POST /chat/stream
    src/api/services/job_queue.py   _run_streaming_generator, reached from
                                    process_chat_request <- worker <- enqueue_job

`POST /chat/async` never calls it — it enqueues a job.  **And MCP enqueues onto
the same queue**, drained by the same worker into the same
`process_chat_request`.  So resolving mode inside the job queue would put MCP on
the graph (the exact defect the plan's placement rule exists to prevent), and
resolving it only in the streaming route would leave the production async path
on the monolith forever.  Mode is therefore resolved in BOTH chat routes and
travels to the worker in the job payload.

Why the payload key is `engine_mode` and never `mode`
-----------------------------------------------------
`mode` is ALREADY a key in that payload: `mcp_server.py`'s `enqueue_create_job`
sets `"mode": mode` for its own generate-vs-edit flag, whose values are
`"generate"` and `"edit"`.  `payload.get("mode", "monolith")` would therefore
return `"generate"` on every MCP job — safe only by accident, and inverted the
moment anyone compares against `"monolith"` instead of `"graph"`.
`TestTheKeyIsEngineModeNotMode` is the guard that reddens if the two are ever
conflated.

MCP's exclusion is STRUCTURAL, not a check
------------------------------------------
Nothing in `mcp_server.py` was touched.  Its payload simply carries no
`engine_mode` key, and `process_chat_request`'s default is `"monolith"`, so an
MCP job runs on the monolith without MCP knowing this switch exists.
`TestMcpIsExcludedByItsPayload` drives an MCP-SHAPED payload through the real
`process_chat_request` rather than only reading source.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import inspect
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import job_queue
from src.api.services.chat_service import (
    AGENT_MODE_PHRASE,
    ChatService,
    resolve_engine_mode_or,
)
from src.core.database import Base, get_db
from tests.unit.conftest import _make_factory, _make_fake_db

# resolve_engine_mode and clear_context import get_db_session lazily inside the
# function body, so the module holds no own reference to patch.  The reachable
# target is the SOURCE attribute; the session_manager one is patched alongside
# it so a delegating implementation would still run against THIS engine.
_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"

_PHRASE_MESSAGE = f"{AGENT_MODE_PHRASE} build me a deck about puffins"
_PLAIN_MESSAGE = "and now add a slide about eider ducks"


# ---------------------------------------------------------------------------
# Route harness — the same shape tests/unit/test_chat_session_creation.py uses
# ---------------------------------------------------------------------------


@pytest.fixture
def route_db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(route_db_engine):
    """TestClient with `get_db` overridden onto the throwaway engine."""
    factory = sessionmaker(autocommit=False, autoflush=False, bind=route_db_engine)
    db = factory()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    db.close()


@pytest.fixture
def route_env(client, route_db_engine):
    """Routes wired to a mocked session manager and a mocked chat service.

    Permission checking is bypassed: this suite is about which engine a turn
    runs on, and no route's authorization is touched by ws4d D2.  The mode
    resolver itself is NOT mocked — it reads `route_db_engine` through the two
    `get_db_session` patches, so "sticky" is measured off committed rows.
    """
    factory = _make_factory(route_db_engine)
    fake_db = _make_fake_db(factory)

    with patch("src.api.routes.chat._check_chat_permission"), \
         patch("src.api.routes.chat.get_session_manager") as route_sm, \
         patch("src.api.routes.chat.get_chat_service") as get_service, \
         patch("src.api.routes.chat.enqueue_job", new_callable=AsyncMock) as enqueue, \
         patch(_DB_SOURCE, fake_db), \
         patch(_MANAGER_DB, fake_db):
        manager = MagicMock()
        manager.acquire_session_lock.return_value = True
        manager.release_session_lock.return_value = None
        manager.create_chat_request.return_value = "req-ws4d"
        manager.get_session.return_value = {"message_count": 1}
        route_sm.return_value = manager

        service = MagicMock()
        service.send_message_streaming.return_value = iter(
            [StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})]
        )
        get_service.return_value = service

        yield {
            "client": client,
            "factory": factory,
            "manager": manager,
            "service": service,
            "enqueue": enqueue,
        }


def _seed_session(factory, user_messages: List[str]) -> str:
    """A UserSession whose transcript is *user_messages*, earliest first."""
    from datetime import datetime, timedelta

    from src.database.models.session import SessionMessage, UserSession

    sid = f"ws4d-wiring-{uuid.uuid4().hex[:10]}"
    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()
        base = datetime.utcnow()
        for i, content in enumerate(user_messages):
            db.add(
                SessionMessage(
                    session_id=us.id,
                    role="user",
                    content=content,
                    message_type="user_query",
                    created_at=base + timedelta(seconds=i),
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return sid


def _append_user_message(factory, session_id: str, content: str) -> None:
    """Append one `role='user'` row, as the async route's add_message would."""
    from datetime import datetime

    from src.database.models.session import SessionMessage, UserSession

    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        db.add(
            SessionMessage(
                session_id=us.id,
                role="user",
                content=content,
                message_type="user_query",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The streaming route
# ---------------------------------------------------------------------------


class TestStreamingRoute:
    """POST /chat/stream resolves the mode and passes it to the service."""

    def _post(self, env, session_id: str, message: str):
        response = env["client"].post(
            "/api/chat/stream",
            json={"session_id": session_id, "message": message},
        )
        assert response.status_code == 200, response.text
        # StreamingResponse is lazy — the body must be consumed for the
        # generator (and therefore the service call) to run at all.
        response.read()
        return env["service"].send_message_streaming.call_args

    def test_a_graph_mode_session_reaches_the_service_as_graph(self, route_env):
        sid = _seed_session(route_env["factory"], [_PHRASE_MESSAGE])
        call = self._post(route_env, sid, _PLAIN_MESSAGE)
        assert call.kwargs["engine_mode"] == "graph"

    def test_the_mode_is_sticky_on_this_entry_point(self, route_env):
        """A later turn carrying no phrase still runs on the graph.

        The deck's EARLIEST user message decides, so the message posted here
        deliberately does not carry the phrase.  Stickiness is what stops a
        deck being written alternately by both engines.
        """
        sid = _seed_session(
            route_env["factory"], [_PHRASE_MESSAGE, "turn 2", "turn 3"]
        )
        call = self._post(route_env, sid, _PLAIN_MESSAGE)
        assert call.kwargs["engine_mode"] == "graph"

    def test_a_monolith_session_reaches_the_service_as_monolith(self, route_env):
        sid = _seed_session(route_env["factory"], ["build me a deck", "turn 2"])
        call = self._post(route_env, sid, _PLAIN_MESSAGE)
        assert call.kwargs["engine_mode"] == "monolith"

    def test_a_later_phrase_does_not_switch_a_monolith_deck(self, route_env):
        """The phrase in THIS turn's text must not flip an established deck."""
        sid = _seed_session(route_env["factory"], ["build me a deck"])
        call = self._post(route_env, sid, _PHRASE_MESSAGE)
        assert call.kwargs["engine_mode"] == "monolith"

    def test_the_engine_mode_is_always_passed_explicitly(self, route_env):
        """Never omitted and left to the default — the route decides."""
        sid = _seed_session(route_env["factory"], ["build me a deck"])
        call = self._post(route_env, sid, _PLAIN_MESSAGE)
        assert "engine_mode" in call.kwargs


class TestStreamingRouteCannotSeeTurnOne:
    """What the ROUTE can know on turn 1 — which is nothing, by construction.

    `POST /chat/stream` does not persist the user message; `send_message_streaming`
    does it on the route's behalf, DOWNSTREAM.  So at the route's resolution
    point a brand-new session has no `role='user'` row and `resolve_engine_mode`
    fails closed to monolith.  This test pins that as a property of the route,
    because it is what makes the seventh edit point necessary rather than
    redundant.

    The GAP this used to record is now CLOSED, one layer down:
    `send_message_streaming` re-resolves after its persist block, guarded on
    `not request_id` so MCP cannot reach it.  The behaviour that matters to a
    user — turn 1 of an SSE session carrying the phrase runs the graph — is
    pinned by
    `tests/integration/test_graph_mode_turn.py::TestTheSseTurnOneReResolve`.
    Do not "fix" the assertion below to `"graph"`: the route genuinely cannot
    return that, and pretending otherwise would hide why the re-resolve exists.
    """

    def test_the_route_still_resolves_monolith_for_a_new_session(
        self, route_env
    ):
        sid = _seed_session(route_env["factory"], [])
        response = route_env["client"].post(
            "/api/chat/stream",
            json={"session_id": sid, "message": _PHRASE_MESSAGE},
        )
        assert response.status_code == 200, response.text
        response.read()
        call = route_env["service"].send_message_streaming.call_args
        assert call.kwargs["engine_mode"] == "monolith"


# ---------------------------------------------------------------------------
# The async route
# ---------------------------------------------------------------------------


class TestAsyncRoute:
    """POST /chat/async resolves the mode and puts it in the job payload."""

    def _payload(self, env, session_id: str, message: str) -> Dict[str, Any]:
        response = env["client"].post(
            "/api/chat/async",
            json={"session_id": session_id, "message": message},
        )
        assert response.status_code == 200, response.text
        assert env["enqueue"].await_count == 1
        return env["enqueue"].await_args.args[1]

    def test_a_graph_mode_session_is_enqueued_as_graph(self, route_env):
        sid = _seed_session(route_env["factory"], [_PHRASE_MESSAGE])
        assert self._payload(route_env, sid, _PLAIN_MESSAGE)["engine_mode"] == "graph"

    def test_the_mode_is_sticky_on_this_entry_point(self, route_env):
        sid = _seed_session(
            route_env["factory"], [_PHRASE_MESSAGE, "turn 2", "turn 3"]
        )
        assert self._payload(route_env, sid, _PLAIN_MESSAGE)["engine_mode"] == "graph"

    def test_a_monolith_session_is_enqueued_as_monolith(self, route_env):
        sid = _seed_session(route_env["factory"], ["build me a deck"])
        payload = self._payload(route_env, sid, _PLAIN_MESSAGE)
        assert payload["engine_mode"] == "monolith"

    def test_turn_one_of_a_new_session_DOES_see_the_phrase(self, route_env):
        """The async route persists the user turn BEFORE it resolves — ORDER.

        The counterpart to `TestStreamingRouteCannotSeeTurnOne`.  The session starts
        with ZERO user rows and the mocked `add_message` really inserts one, so
        the only way the phrase can be seen is if resolution runs AFTER that
        call.  Moving the resolve above it reddens this test.
        """
        sid = _seed_session(route_env["factory"], [])
        factory = route_env["factory"]
        route_env["manager"].get_session.return_value = {"message_count": 0}

        def really_add_message(**kwargs):
            _append_user_message(factory, kwargs["session_id"], kwargs["content"])
            return {"id": 1}

        route_env["manager"].add_message.side_effect = really_add_message

        payload = self._payload(route_env, sid, _PHRASE_MESSAGE)
        assert payload["engine_mode"] == "graph"


class TestTheKeyIsEngineModeNotMode:
    """`mode` is MCP's generate/edit flag. Conflating the two ships a defect."""

    def test_the_async_payload_carries_engine_mode(self, route_env):
        sid = _seed_session(route_env["factory"], [_PHRASE_MESSAGE])
        route_env["client"].post(
            "/api/chat/async", json={"session_id": sid, "message": _PLAIN_MESSAGE}
        )
        payload = route_env["enqueue"].await_args.args[1]
        assert "engine_mode" in payload

    def test_the_async_payload_does_not_reuse_the_mode_key(self, route_env):
        sid = _seed_session(route_env["factory"], [_PHRASE_MESSAGE])
        route_env["client"].post(
            "/api/chat/async", json={"session_id": sid, "message": _PLAIN_MESSAGE}
        )
        payload = route_env["enqueue"].await_args.args[1]
        assert "mode" not in payload, (
            "the browser payload must not write MCP's generate/edit `mode` key"
        )

    def test_the_worker_reads_engine_mode_and_not_mode(self):
        """Source guard on the one line the C-2 collision would live in.

        Behavioural coverage of the same rule is
        `TestMcpIsExcludedByItsPayload`; this pins the READ, because
        `payload.get("mode", "monolith")` would return MCP's `"generate"` and
        still compare unequal to `"graph"` — passing every behavioural test
        while being wrong.
        """
        source = inspect.getsource(job_queue.process_chat_request)
        assert 'payload.get("engine_mode", "monolith")' in source
        assert 'payload.get("mode"' not in source

    def test_mcp_builds_no_engine_mode_key(self):
        """MCP's exclusion must come from the default, not from a check in MCP."""
        from src.api import mcp_server

        source = inspect.getsource(mcp_server)
        assert "engine_mode" not in source, (
            "mcp_server.py must stay unaware of the engine switch — its "
            "exclusion is structural"
        )


# ---------------------------------------------------------------------------
# The job queue
# ---------------------------------------------------------------------------


class _Recorder:
    """Stands in for `_run_streaming_generator`; records every argument."""

    def __init__(self) -> None:
        self.args: Optional[tuple] = None
        self.kwargs: Optional[dict] = None

    def __call__(self, *args, **kwargs) -> list:
        self.args = args
        self.kwargs = kwargs
        return [StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})]

    @property
    def engine_mode(self):
        """The value that reached the parameter, positional or keyword.

        Both call sites pass POSITIONALLY, so reading only kwargs would report
        None however the wiring behaved.  The signature is
        (chat_service, session_id, message, slide_context, request_id,
        is_first_message, image_ids, engine_mode) — index 7.
        """
        if self.kwargs and "engine_mode" in self.kwargs:
            return self.kwargs["engine_mode"]
        assert self.args is not None, "_run_streaming_generator was never called"
        return self.args[7] if len(self.args) > 7 else None


@contextlib.contextmanager
def _worker_env():
    """`process_chat_request` with its collaborators stubbed out."""
    recorder = _Recorder()
    manager = MagicMock()
    with patch(
        "src.api.services.job_queue._run_streaming_generator", recorder
    ), patch(
        "src.api.services.session_manager.get_session_manager", return_value=manager
    ), patch(
        "src.api.services.chat_service.get_chat_service", return_value=MagicMock()
    ):
        yield recorder, manager


def _run(payload: dict) -> Any:
    with _worker_env() as (recorder, _manager):
        asyncio.run(job_queue.process_chat_request("req-1", dict(payload)))
        return recorder.engine_mode


_BASE_PAYLOAD = {
    "session_id": "s-1",
    "message": "build me a deck",
    "slide_context": None,
    "is_first_message": True,
    "image_ids": None,
}


class TestTheWorkerForwardsTheMode:
    """Both `_run_streaming_generator` call sites carry it, positionally."""

    def test_the_no_context_fallback_branch_forwards_graph(self):
        """The `else:` recovery branch at `process_chat_request`'s `if ctx:`."""
        assert _run({**_BASE_PAYLOAD, "engine_mode": "graph"}) == "graph"

    def test_the_context_branch_forwards_graph(self):
        """The `if ctx:` branch — a payload that went through `enqueue_job`."""
        payload = {
            **_BASE_PAYLOAD,
            "engine_mode": "graph",
            "_context": contextvars.copy_context(),
        }
        assert _run(payload) == "graph"

    def test_the_context_branch_forwards_monolith(self):
        payload = {
            **_BASE_PAYLOAD,
            "engine_mode": "monolith",
            "_context": contextvars.copy_context(),
        }
        assert _run(payload) == "monolith"


class TestMcpIsExcludedByItsPayload:
    """An MCP-shaped payload runs on the monolith, and does not error."""

    def test_a_payload_with_no_engine_mode_key_falls_to_monolith(self):
        assert _run(dict(_BASE_PAYLOAD)) == "monolith"

    def test_an_mcp_generate_payload_falls_to_monolith(self):
        """MCP's real payload shape: `mode` set, `engine_mode` absent."""
        payload = {
            **_BASE_PAYLOAD,
            "mode": "generate",
            "correlation_id": "corr-1",
            "_context": contextvars.copy_context(),
        }
        assert _run(payload) == "monolith"

    def test_an_mcp_edit_payload_falls_to_monolith(self):
        payload = {**_BASE_PAYLOAD, "mode": "edit", "correlation_id": "corr-2"}
        assert _run(payload) == "monolith"

    def test_an_mcp_payload_does_not_raise(self):
        """A KeyError here would break every MCP job, not just graph ones."""
        with _worker_env() as (_recorder, manager):
            asyncio.run(
                job_queue.process_chat_request(
                    "req-mcp", {**_BASE_PAYLOAD, "mode": "generate"}
                )
            )
        manager.update_chat_request_status.assert_any_call("req-mcp", "completed")


class TestRunStreamingGeneratorPassesItOn:
    """`_run_streaming_generator` hands the mode to the service by keyword."""

    def _call(self, **kwargs):
        service = MagicMock()
        service.send_message_streaming.return_value = iter([])
        job_queue._run_streaming_generator(
            service, "s-1", "hello", None, "req-1", False, None, **kwargs
        )
        return service.send_message_streaming.call_args.kwargs

    def test_graph_is_forwarded(self):
        assert self._call(engine_mode="graph")["engine_mode"] == "graph"

    def test_the_parameter_defaults_to_monolith(self):
        assert self._call()["engine_mode"] == "monolith"


# ---------------------------------------------------------------------------
# The defaults, and the paths that must never see the graph
# ---------------------------------------------------------------------------


class TestDefaultsFailClosed:
    """Every hop defaults to monolith. That default IS MCP's exclusion."""

    @pytest.mark.parametrize(
        "func",
        [ChatService.send_message_streaming, job_queue._run_streaming_generator],
        ids=["send_message_streaming", "_run_streaming_generator"],
    )
    def test_the_engine_mode_parameter_defaults_to_monolith(self, func):
        param = inspect.signature(func).parameters["engine_mode"]
        assert param.default == "monolith"


class TestResolutionFailureNeverFailsATurn:
    """Mode resolution must never be the thing that fails a turn (Task 1's own
    contract, quoted from `resolve_engine_mode`'s docstring).

    `resolve_engine_mode` returns monolith for its three "no answer" cases but
    lets an unexpected database error propagate, and every call site sits on the
    request path of a turn that would otherwise have run fine.  Measured while
    adding the seventh edit point: a bare re-resolve killed three pre-existing
    monolith tests with `psycopg2.ProgrammingError`, which is the same shape a
    transient database error takes in production — a monolith turn that
    previously needed no database read at all would 500.

    So every call site goes through `resolve_engine_mode_or`, and these are the
    assertions that it is a fail-OPEN and not a fail-loud.
    """

    _BOOM = "src.api.services.chat_service.resolve_engine_mode"

    def test_a_raising_resolver_returns_the_callers_value(self):
        def boom(session_id):
            raise RuntimeError("the database went away")

        with patch(self._BOOM, boom):
            assert resolve_engine_mode_or("s-1", "graph") == "graph"

    def test_the_fallback_defaults_to_monolith(self):
        def boom(session_id):
            raise RuntimeError("the database went away")

        with patch(self._BOOM, boom):
            assert resolve_engine_mode_or("s-1") == "monolith"

    def test_a_successful_resolution_is_passed_straight_through(self):
        """The wrapper must not swallow the answer as well as the error."""
        with patch(self._BOOM, lambda session_id: "graph"):
            assert resolve_engine_mode_or("s-1", "monolith") == "graph"

    def test_the_streaming_route_still_serves_the_turn(self, route_env):
        sid = _seed_session(route_env["factory"], [_PHRASE_MESSAGE])

        def boom(session_id):
            raise RuntimeError("the database went away")

        with patch(self._BOOM, boom):
            response = route_env["client"].post(
                "/api/chat/stream",
                json={"session_id": sid, "message": _PLAIN_MESSAGE},
            )
            assert response.status_code == 200, response.text
            response.read()

        call = route_env["service"].send_message_streaming.call_args
        assert call.kwargs["engine_mode"] == "monolith"

    def test_the_async_route_still_enqueues_the_job(self, route_env):
        sid = _seed_session(route_env["factory"], [_PHRASE_MESSAGE])

        def boom(session_id):
            raise RuntimeError("the database went away")

        with patch(self._BOOM, boom):
            response = route_env["client"].post(
                "/api/chat/async",
                json={"session_id": sid, "message": _PLAIN_MESSAGE},
            )
            assert response.status_code == 200, response.text

        payload = route_env["enqueue"].await_args.args[1]
        assert payload["engine_mode"] == "monolith"


class TestSendMessageNeverReferencesTheGraph:
    """The non-streaming entry point is explicitly out of scope (D2, C-9).

    `send_message` contains no `yield`; adding one converts it into a generator
    and breaks every caller.  A graph branch there is therefore not "the same
    three lines" — it is a separately designed path.
    """

    def test_send_message_is_not_a_generator(self):
        assert not inspect.isgeneratorfunction(ChatService.send_message)

    @pytest.mark.parametrize(
        "token", ["invoke_graph", "engine_mode", "_send_message_streaming_graph"]
    )
    def test_send_message_mentions_nothing_graph_related(self, token):
        assert token not in inspect.getsource(ChatService.send_message)

    def test_send_message_takes_no_engine_mode_parameter(self):
        assert "engine_mode" not in inspect.signature(ChatService.send_message).parameters

    def test_the_sync_chat_route_never_resolves_a_mode(self):
        """POST /chat (the non-streaming route) is out of scope."""
        from src.api.routes import chat as chat_routes

        source = inspect.getsource(chat_routes.send_message)
        assert "resolve_engine_mode" not in source
        assert "engine_mode" not in source

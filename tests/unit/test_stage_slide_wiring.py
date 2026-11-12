"""Stage-slide WIRING (architect stage context, Task 2).

The browser sends the slide that was ON STAGE when the user pressed send as an
optional ``stage_slide: {slide_number, slide_id?}`` snapshot.  This suite pins
how that snapshot travels through the backend, unchanged, until it is seeded on
the graph's initial state:

    POST /chat/stream  -> ChatService.send_message_streaming(stage_slide=...)
    POST /chat/async   -> enqueue_job payload["stage_slide"]
                       -> process_chat_request (BOTH ctx branches)
                       -> _run_streaming_generator (appended after engine_mode)
                       -> ChatService.send_message_streaming(stage_slide=...)
    graph engine       -> _send_message_streaming_graph(*, stage_slide=...)
                       -> invoke_graph(session_id, {"architect_message": ...,
                                                    "stage_slide": <raw>})

Rules pinned here:

* ``slide_number`` is a STRICT positive int (no 0, negatives, floats, bools or
  numeric strings); ``slide_id`` is an optional non-empty string of at most
  256 characters.  A malformed snapshot is a 422 on both routes, before any
  service or queue work.
* Both the identity (``slide_id``) and the number survive every hop unchanged.
* ``invoke_graph`` always receives the ``stage_slide`` key -- ``None`` included
  -- because turn state accumulates across a checkpointed thread: omitting the
  key would let a later, stage-less turn inherit an earlier turn's stage.
* Legacy is frozen: the monolith path never enters the graph because of a
  stage, and the Legacy-only sync route ``POST /chat`` is unchanged.

No live calls: the graph, the service's deck stores, settings and the session
manager are all stubbed.  The route tests run the real FastAPI app and the real
engine-mode resolver against a throwaway SQLite engine (same harness shape as
``test_engine_mode_wiring.py``).
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import inspect
import threading
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.api.schemas import requests as request_schemas
from src.api.schemas.requests import ChatRequest
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import job_queue
from src.api.services.chat_service import ChatService
from src.core.database import Base, get_db
from tests.unit.conftest import _make_factory, _make_fake_db

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_INVOKE_GRAPH = "src.services.graph.builder.invoke_graph"
_SETTINGS = "src.core.settings_db.get_settings"
_SERVICE_SM = "src.api.services.chat_service.get_session_manager"
_QUEUE_SM = "src.api.services.session_manager.get_session_manager"
_QUEUE_SERVICE = "src.api.services.chat_service.get_chat_service"

_MESSAGE = "make the title bigger"
_MISSING = object()

# The snapshot as the browser sends it, and as the backend must hand it on.
_STAGE_WITH_ID = {"slide_number": 3, "slide_id": "slide-7f3a"}
# Older slide data carries no stable id: the number alone is the snapshot.
_STAGE_NUMBER_ONLY = {"slide_number": 2}
_STAGE_NUMBER_ONLY_DUMPED = {"slide_number": 2, "slide_id": None}


def _stage_model():
    """The request model, or a clear FAILURE (not a collection error)."""
    model = getattr(request_schemas, "StageSlideContext", None)
    if model is None:
        pytest.fail("src.api.schemas.requests.StageSlideContext does not exist")
    return model


def _stage_of(request: ChatRequest) -> Any:
    value = getattr(request, "stage_slide", _MISSING)
    if value is _MISSING:
        pytest.fail("ChatRequest has no stage_slide field")
    return value


def _call_accepting_stage(fn, *args, **kwargs):
    """Call *fn*; a signature that rejects the stage is a feature failure."""
    try:
        return fn(*args, **kwargs)
    except TypeError as exc:
        text = str(exc)
        if "stage_slide" in text or "positional argument" in text:
            pytest.fail(f"{getattr(fn, '__qualname__', fn)} does not accept stage_slide: {text}")
        raise


# ---------------------------------------------------------------------------
# 1. The request schema
# ---------------------------------------------------------------------------


class TestStageSlideContextSchema:
    """``StageSlideContext``: strict positive number, optional bounded id."""

    @pytest.mark.parametrize("number", [1, 3, 250])
    def test_a_positive_number_is_accepted_unchanged(self, number):
        stage = _stage_model()(slide_number=number)
        assert stage.slide_number == number
        assert type(stage.slide_number) is int

    def test_the_id_is_optional_and_defaults_to_none(self):
        stage = _stage_model()(slide_number=4)
        assert stage.slide_id is None
        assert stage.model_dump() == {"slide_number": 4, "slide_id": None}

    def test_an_explicit_null_id_is_accepted(self):
        assert _stage_model()(slide_number=4, slide_id=None).slide_id is None

    def test_number_and_id_dump_unchanged(self):
        stage = _stage_model()(**_STAGE_WITH_ID)
        assert stage.model_dump() == _STAGE_WITH_ID

    def test_a_256_character_id_is_accepted(self):
        slide_id = "s" * 256
        assert _stage_model()(slide_number=1, slide_id=slide_id).slide_id == slide_id

    @pytest.mark.parametrize(
        "number",
        [0, -1, -40, 2.0, 2.5, True, False, "2", "two", None],
        ids=["zero", "minus-one", "minus-forty", "float-whole", "float",
             "bool-true", "bool-false", "numeric-string", "word", "null"],
    )
    def test_an_invalid_number_is_rejected(self, number):
        model = _stage_model()
        with pytest.raises(ValidationError):
            model(slide_number=number)

    def test_a_missing_number_is_rejected(self):
        model = _stage_model()
        with pytest.raises(ValidationError):
            model(slide_id="slide-7f3a")

    @pytest.mark.parametrize(
        "slide_id", ["", "s" * 257], ids=["empty", "257-chars"]
    )
    def test_an_empty_or_oversized_id_is_rejected(self, slide_id):
        model = _stage_model()
        with pytest.raises(ValidationError):
            model(slide_number=1, slide_id=slide_id)


class TestChatRequestCarriesTheStage:
    """``ChatRequest.stage_slide`` is optional, defaults None, and validates."""

    def test_omitted_is_none(self):
        assert _stage_of(ChatRequest(message=_MESSAGE)) is None

    def test_explicit_null_is_none(self):
        assert _stage_of(ChatRequest(message=_MESSAGE, stage_slide=None)) is None

    def test_a_snapshot_parses_into_the_stage_model(self):
        stage = _stage_of(ChatRequest(message=_MESSAGE, stage_slide=_STAGE_WITH_ID))
        assert isinstance(stage, _stage_model())
        assert stage.model_dump() == _STAGE_WITH_ID

    def test_a_number_only_snapshot_parses(self):
        stage = _stage_of(ChatRequest(message=_MESSAGE, stage_slide=_STAGE_NUMBER_ONLY))
        assert stage.model_dump() == _STAGE_NUMBER_ONLY_DUMPED

    @pytest.mark.parametrize(
        "stage",
        [
            {},
            {"slide_id": "slide-7f3a"},
            {"slide_number": 0},
            {"slide_number": -2, "slide_id": "x"},
            {"slide_number": 1.0},
            {"slide_number": True},
            {"slide_number": "3"},
            {"slide_number": 3, "slide_id": ""},
            {"slide_number": 3, "slide_id": "s" * 257},
            3,
            "3",
            [3],
            [{"slide_number": 3}],
        ],
        ids=["empty-object", "id-only", "zero", "negative", "float", "bool",
             "numeric-string", "empty-id", "oversized-id", "bare-int",
             "bare-string", "list", "list-of-object"],
    )
    def test_a_malformed_snapshot_is_rejected(self, stage):
        with pytest.raises(ValidationError):
            ChatRequest(message=_MESSAGE, stage_slide=stage)
        # Precondition: had the field been ignored, this would not have raised.
        _stage_of(ChatRequest(message=_MESSAGE))


# ---------------------------------------------------------------------------
# Shared doubles
# ---------------------------------------------------------------------------


class _GraphEntry:
    """Stands in for ``invoke_graph``; records the INITIAL state it was given."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, session_id, initial=None, **kwargs):
        self.calls.append(
            {
                "session_id": session_id,
                "initial": None if initial is None else dict(initial),
                "kwargs": kwargs,
            }
        )
        return {}

    @property
    def initial(self) -> Dict[str, Any]:
        assert len(self.calls) == 1, f"invoke_graph called {len(self.calls)} times"
        return self.calls[0]["initial"]


class _MonolithReached(Exception):
    """Raised by the first monolith-only step: proves which branch ran."""


def _service_double() -> ChatService:
    """A real ChatService with its deck stores stubbed (no DB, no LLM)."""
    service = ChatService.__new__(ChatService)
    service._deck_cache = {}
    service._cache_lock = threading.Lock()
    service._get_or_load_deck = MagicMock(return_value=None)
    service.get_slides = MagicMock(return_value={"slides": []})
    # The first monolith-only call in send_message_streaming.  A graph turn
    # never reaches it; a monolith turn stops here, before any LLM work.
    service._detect_edit_intent = MagicMock(side_effect=_MonolithReached())
    return service


def _service_manager() -> MagicMock:
    manager = MagicMock()
    manager.get_session.return_value = {"message_count": 1}
    return manager


@contextlib.contextmanager
def _service_env():
    """Patch the service's own collaborators; yield the graph recorder."""
    graph = _GraphEntry()
    with patch(_INVOKE_GRAPH, graph), \
         patch(_SETTINGS, return_value=MagicMock()), \
         patch(_SERVICE_SM, return_value=_service_manager()):
        yield graph


# ---------------------------------------------------------------------------
# Route harness
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
    """Both chat routes with a mocked session manager, service and queue.

    The engine-mode resolver is REAL: a session's engine comes from its stored
    ``deck_mode`` (NULL -> graph, "legacy" -> monolith).
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
        manager.create_chat_request.return_value = "req-stage"
        manager.get_session.return_value = {"message_count": 1}
        route_sm.return_value = manager

        service = MagicMock()
        service.send_message_streaming.side_effect = lambda **_kw: iter(
            [StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})]
        )
        service.send_message.return_value = {"messages": [], "metadata": {}}
        get_service.return_value = service

        yield {
            "client": client,
            "factory": factory,
            "manager": manager,
            "service": service,
            "get_service": get_service,
            "enqueue": enqueue,
        }


def _seed_session(factory, *, deck_mode: Optional[str] = None) -> str:
    from datetime import datetime

    from src.database.models.session import SessionMessage, UserSession

    sid = f"stage-wiring-{uuid.uuid4().hex[:10]}"
    db = factory()
    try:
        us = UserSession(
            session_id=sid, created_by="test-user@example.com", deck_mode=deck_mode
        )
        db.add(us)
        db.flush()
        db.add(
            SessionMessage(
                session_id=us.id,
                role="user",
                content="build me a deck",
                message_type="user_query",
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()
    return sid


def _body(sid: str, stage: Any = _MISSING) -> Dict[str, Any]:
    body: Dict[str, Any] = {"session_id": sid, "message": _MESSAGE}
    if stage is not _MISSING:
        body["stage_slide"] = stage
    return body


def _stream(env, body) -> Any:
    response = env["client"].post("/api/chat/stream", json=body)
    assert response.status_code == 200, response.text
    response.read()  # the SSE generator (and the service call) is lazy
    assert env["service"].send_message_streaming.call_count == 1
    return env["service"].send_message_streaming.call_args


def _enqueued(env, body) -> Dict[str, Any]:
    response = env["client"].post("/api/chat/async", json=body)
    assert response.status_code == 200, response.text
    assert env["enqueue"].await_count == 1
    return env["enqueue"].await_args.args[1]


# ---------------------------------------------------------------------------
# 2. POST /chat/stream
# ---------------------------------------------------------------------------


class TestStreamingRouteForwardsTheStage:
    """The SSE route hands the parsed snapshot to the service by keyword."""

    def test_a_graph_turn_forwards_number_and_identity(self, route_env):
        sid = _seed_session(route_env["factory"])
        call = _stream(route_env, _body(sid, _STAGE_WITH_ID))
        assert call.kwargs["engine_mode"] == "graph"  # precondition
        assert call.kwargs.get("stage_slide") == _STAGE_WITH_ID

    def test_a_number_only_snapshot_is_forwarded(self, route_env):
        sid = _seed_session(route_env["factory"])
        call = _stream(route_env, _body(sid, _STAGE_NUMBER_ONLY))
        assert call.kwargs.get("stage_slide") == _STAGE_NUMBER_ONLY_DUMPED

    @pytest.mark.parametrize("stage", [_MISSING, None], ids=["omitted", "null"])
    def test_no_stage_forwards_none(self, route_env, stage):
        sid = _seed_session(route_env["factory"])
        call = _stream(route_env, _body(sid, stage))
        assert call.kwargs.get("stage_slide", None) is None
        # The pre-existing keywords are untouched by the new one.
        assert call.kwargs["user_message_persisted"] is True
        assert call.kwargs["slide_context"] is None

    @pytest.mark.parametrize(
        "stage",
        [{"slide_number": 0}, {"slide_number": "3"}, {"slide_number": 3, "slide_id": ""}, "3"],
        ids=["zero", "numeric-string", "empty-id", "bare-string"],
    )
    def test_a_malformed_stage_is_a_422_before_any_work(self, route_env, stage):
        sid = _seed_session(route_env["factory"])
        response = route_env["client"].post("/api/chat/stream", json=_body(sid, stage))
        assert response.status_code == 422, response.text
        route_env["service"].send_message_streaming.assert_not_called()
        route_env["manager"].acquire_session_lock.assert_not_called()


# ---------------------------------------------------------------------------
# 3. POST /chat/async -> the job payload
# ---------------------------------------------------------------------------


class TestAsyncRoutePutsTheStageInThePayload:
    """The polling route carries the snapshot in the job payload."""

    def test_a_graph_turn_enqueues_number_and_identity(self, route_env):
        sid = _seed_session(route_env["factory"])
        payload = _enqueued(route_env, _body(sid, _STAGE_WITH_ID))
        assert payload["engine_mode"] == "graph"  # precondition
        assert payload.get("stage_slide") == _STAGE_WITH_ID

    def test_a_number_only_snapshot_is_enqueued(self, route_env):
        sid = _seed_session(route_env["factory"])
        payload = _enqueued(route_env, _body(sid, _STAGE_NUMBER_ONLY))
        assert payload.get("stage_slide") == _STAGE_NUMBER_ONLY_DUMPED

    @pytest.mark.parametrize("stage", [_MISSING, None], ids=["omitted", "null"])
    def test_no_stage_enqueues_none(self, route_env, stage):
        sid = _seed_session(route_env["factory"])
        payload = _enqueued(route_env, _body(sid, stage))
        assert payload.get("stage_slide", None) is None
        assert payload["engine_mode"] == "graph"

    def test_the_payload_is_json_native(self, route_env):
        """A pydantic object in the payload would not survive a recovery replay."""
        sid = _seed_session(route_env["factory"])
        payload = _enqueued(route_env, _body(sid, _STAGE_WITH_ID))
        assert type(payload.get("stage_slide")) is dict

    @pytest.mark.parametrize(
        "stage",
        [{"slide_number": -1}, {"slide_number": True}, {"slide_id": "x"}, [3]],
        ids=["negative", "bool", "id-only", "list"],
    )
    def test_a_malformed_stage_is_a_422_before_any_work(self, route_env, stage):
        sid = _seed_session(route_env["factory"])
        response = route_env["client"].post("/api/chat/async", json=_body(sid, stage))
        assert response.status_code == 422, response.text
        route_env["enqueue"].assert_not_awaited()
        route_env["manager"].create_chat_request.assert_not_called()

    def test_sse_and_polling_carry_the_same_snapshot(self, route_env):
        sid = _seed_session(route_env["factory"])
        streamed = _stream(route_env, _body(sid, _STAGE_WITH_ID)).kwargs.get("stage_slide")
        enqueued = _enqueued(route_env, _body(sid, _STAGE_WITH_ID)).get("stage_slide")
        assert streamed == enqueued == _STAGE_WITH_ID


class TestTheLegacySyncRouteIsUnchanged:
    """``POST /chat`` is Legacy-only and frozen: a stage changes nothing.

    GREEN BY DESIGN (regression guard): it reddens if the stage is ever passed
    into ``ChatService.send_message``.
    """

    def test_send_message_receives_only_its_four_positional_arguments(self, route_env):
        sid = _seed_session(route_env["factory"], deck_mode="legacy")
        response = route_env["client"].post("/api/chat", json=_body(sid, _STAGE_WITH_ID))
        assert response.status_code == 200, response.text
        call = route_env["service"].send_message.call_args
        assert call.args == (sid, _MESSAGE, None, None)
        assert call.kwargs == {}


# ---------------------------------------------------------------------------
# 4. The worker: process_chat_request -> _run_streaming_generator -> service
# ---------------------------------------------------------------------------


_BASE_PAYLOAD = {
    "session_id": "s-1",
    "message": _MESSAGE,
    "slide_context": None,
    "is_first_message": False,
    "image_ids": None,
    "engine_mode": "graph",
}


@contextlib.contextmanager
def _worker_env(service: Any = None):
    """``process_chat_request`` with the REAL ``_run_streaming_generator``."""
    manager = MagicMock()
    if service is None:
        service = MagicMock()
        service.send_message_streaming.side_effect = lambda **_kw: iter(
            [StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})]
        )
    with patch(_QUEUE_SM, return_value=manager), \
         patch(_QUEUE_SERVICE, return_value=service):
        yield service, manager


def _run_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drain one job; return the keywords the service was called with."""
    with _worker_env() as (service, manager):
        asyncio.run(job_queue.process_chat_request("req-1", dict(payload)))
    assert service.send_message_streaming.call_count == 1
    manager.update_chat_request_status.assert_any_call("req-1", "completed")
    return service.send_message_streaming.call_args.kwargs


class TestTheWorkerForwardsTheStage:
    """Both ``_run_streaming_generator`` call sites carry the stage."""

    def test_the_context_branch_forwards_number_and_identity(self):
        """The ``if ctx:`` branch -- a payload that went through ``enqueue_job``."""
        kwargs = _run_worker(
            {**_BASE_PAYLOAD, "stage_slide": dict(_STAGE_WITH_ID),
             "_context": contextvars.copy_context()}
        )
        assert kwargs.get("stage_slide") == _STAGE_WITH_ID
        assert kwargs["engine_mode"] == "graph"

    def test_the_no_context_fallback_branch_forwards_number_and_identity(self):
        """The ``else:`` recovery branch (no captured ``_context``)."""
        kwargs = _run_worker({**_BASE_PAYLOAD, "stage_slide": dict(_STAGE_WITH_ID)})
        assert kwargs.get("stage_slide") == _STAGE_WITH_ID
        assert kwargs["engine_mode"] == "graph"

    @pytest.mark.parametrize("with_context", [True, False], ids=["ctx", "no-ctx"])
    def test_a_number_only_snapshot_is_forwarded(self, with_context):
        payload = {**_BASE_PAYLOAD, "stage_slide": dict(_STAGE_NUMBER_ONLY_DUMPED)}
        if with_context:
            payload["_context"] = contextvars.copy_context()
        assert _run_worker(payload).get("stage_slide") == _STAGE_NUMBER_ONLY_DUMPED

    @pytest.mark.parametrize("with_context", [True, False], ids=["ctx", "no-ctx"])
    def test_a_payload_without_the_key_forwards_none(self, with_context):
        """MCP's payloads, and jobs queued before this change, have no key."""
        payload = dict(_BASE_PAYLOAD)
        if with_context:
            payload["_context"] = contextvars.copy_context()
        kwargs = _run_worker(payload)
        assert kwargs.get("stage_slide", None) is None
        # The pre-existing keywords are untouched by the new one.
        assert kwargs["engine_mode"] == "graph"
        assert kwargs["request_id"] == "req-1"

    def test_an_mcp_shaped_payload_still_completes(self):
        """MCP's real shape: ``mode`` set, neither ``engine_mode`` nor stage."""
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "engine_mode"}
        kwargs = _run_worker(
            {**payload, "mode": "generate", "correlation_id": "c-1",
             "_context": contextvars.copy_context()}
        )
        assert kwargs.get("stage_slide", None) is None
        assert kwargs["engine_mode"] == "monolith"


class TestRunStreamingGeneratorPassesItOn:
    """The queue helper appends ``stage_slide`` after ``engine_mode``."""

    _LEADING = ("s-1", _MESSAGE, None, "req-1", False, None)

    def _service(self) -> MagicMock:
        service = MagicMock()
        service.send_message_streaming.return_value = iter([])
        return service

    def test_a_keyword_stage_reaches_the_service_by_keyword(self):
        service = self._service()
        _call_accepting_stage(
            job_queue._run_streaming_generator,
            service, *self._LEADING, engine_mode="graph",
            stage_slide=dict(_STAGE_WITH_ID),
        )
        assert service.send_message_streaming.call_args.kwargs.get("stage_slide") == _STAGE_WITH_ID

    def test_the_stage_is_the_positional_argument_after_engine_mode(self):
        """Both worker call sites pass every argument POSITIONALLY."""
        service = self._service()
        _call_accepting_stage(
            job_queue._run_streaming_generator,
            service, *self._LEADING, "graph", dict(_STAGE_WITH_ID),
        )
        kwargs = service.send_message_streaming.call_args.kwargs
        assert kwargs["engine_mode"] == "graph"
        assert kwargs.get("stage_slide") == _STAGE_WITH_ID

    def test_the_parameter_defaults_to_none(self):
        service = self._service()
        job_queue._run_streaming_generator(service, *self._LEADING, "graph")
        assert service.send_message_streaming.call_args.kwargs.get("stage_slide", None) is None
        param = inspect.signature(job_queue._run_streaming_generator).parameters.get(
            "stage_slide"
        )
        assert param is not None, "_run_streaming_generator has no stage_slide parameter"
        assert param.default is None


# ---------------------------------------------------------------------------
# 5. The service -> the graph's initial state
# ---------------------------------------------------------------------------


class TestTheServiceSeedsTheGraph:
    """``send_message_streaming`` -> ``_send_message_streaming_graph`` -> invoke_graph."""

    def _graph_turn(self, **kwargs) -> Dict[str, Any]:
        service = _service_double()
        with _service_env() as graph:
            events = list(
                _call_accepting_stage(
                    service.send_message_streaming,
                    session_id="s-1",
                    message=_MESSAGE,
                    request_id="req-1",
                    engine_mode="graph",
                    is_first_message_override=False,
                    **kwargs,
                )
            )
        assert StreamEventType.COMPLETE in [e.type for e in events]
        return graph.initial

    def test_number_and_identity_reach_the_initial_state_unchanged(self):
        initial = self._graph_turn(stage_slide=dict(_STAGE_WITH_ID))
        assert initial == {"architect_message": _MESSAGE, "stage_slide": _STAGE_WITH_ID}

    def test_a_number_only_snapshot_reaches_the_initial_state(self):
        initial = self._graph_turn(stage_slide=dict(_STAGE_NUMBER_ONLY_DUMPED))
        assert initial == {
            "architect_message": _MESSAGE,
            "stage_slide": _STAGE_NUMBER_ONLY_DUMPED,
        }

    def test_no_stage_seeds_an_explicit_none(self):
        """The key is ALWAYS seeded: None clears a previous turn's stage."""
        initial = self._graph_turn()
        assert "stage_slide" in initial, (
            "invoke_graph must receive stage_slide=None on a stage-less turn, "
            "or a checkpointed thread keeps the previous turn's stage"
        )
        assert initial == {"architect_message": _MESSAGE, "stage_slide": None}

    def test_an_explicit_none_seeds_none(self):
        initial = self._graph_turn(stage_slide=None)
        assert initial == {"architect_message": _MESSAGE, "stage_slide": None}

    def test_the_graph_limb_takes_the_stage_as_a_keyword(self):
        service = _service_double()
        with _service_env() as graph:
            list(
                _call_accepting_stage(
                    service._send_message_streaming_graph,
                    "s-1", _MESSAGE, is_first_message=False,
                    request_id="req-1", stage_slide=dict(_STAGE_WITH_ID),
                )
            )
        assert graph.initial == {"architect_message": _MESSAGE, "stage_slide": _STAGE_WITH_ID}
        assert graph.calls[0]["kwargs"]["request_id"] == "req-1"

    def test_the_graph_limb_defaults_to_seeding_none(self):
        service = _service_double()
        with _service_env() as graph:
            list(service._send_message_streaming_graph("s-1", _MESSAGE))
        assert graph.initial == {"architect_message": _MESSAGE, "stage_slide": None}


class TestLegacyHasNoStageBehaviour:
    """A monolith turn accepts a stage and ignores it: the graph is never entered."""

    def test_a_monolith_turn_with_a_stage_never_enters_the_graph(self):
        service = _service_double()
        service._send_message_streaming_graph = MagicMock(
            side_effect=AssertionError("a monolith turn entered the graph limb")
        )
        with _service_env() as graph:
            stream = _call_accepting_stage(
                service.send_message_streaming,
                session_id="s-1",
                message=_MESSAGE,
                request_id="req-1",
                engine_mode="monolith",
                is_first_message_override=False,
                stage_slide=dict(_STAGE_WITH_ID),
            )
            with pytest.raises(_MonolithReached):
                list(stream)
        assert graph.calls == []
        service._send_message_streaming_graph.assert_not_called()
        # The monolith's own inputs are untouched: it saw the raw message.
        service._detect_edit_intent.assert_called_once_with(_MESSAGE)

    def test_a_legacy_session_streams_on_the_monolith_with_a_stage_in_the_body(
        self, route_env
    ):
        """The browser omits the stage in Legacy; a stray one must not break it."""
        sid = _seed_session(route_env["factory"], deck_mode="legacy")
        call = _stream(route_env, _body(sid, _STAGE_WITH_ID))
        assert call.kwargs["engine_mode"] == "monolith"

    def test_a_legacy_stream_turn_forwards_no_stage(self, route_env):
        """Graph-only gate on /chat/stream: a supplied stage is dropped on Legacy."""
        sid = _seed_session(route_env["factory"], deck_mode="legacy")
        call = _stream(route_env, _body(sid, _STAGE_WITH_ID))
        assert call.kwargs["engine_mode"] == "monolith"  # precondition
        assert "stage_slide" in call.kwargs, "the route must pass the keyword"
        assert call.kwargs["stage_slide"] is None

    def test_a_legacy_async_turn_enqueues_no_stage(self, route_env):
        """Graph-only gate on /chat/async: the Legacy job payload carries None."""
        sid = _seed_session(route_env["factory"], deck_mode="legacy")
        payload = _enqueued(route_env, _body(sid, _STAGE_WITH_ID))
        assert payload["engine_mode"] == "monolith"  # precondition
        assert "stage_slide" in payload
        assert payload["stage_slide"] is None


class TestSignatures:
    """STRUCTURAL (not behaviour): appended, defaulted, existing order kept."""

    def test_send_message_streaming_appends_the_stage_after_user_message_persisted(self):
        params = list(inspect.signature(ChatService.send_message_streaming).parameters)
        assert "stage_slide" in params, "send_message_streaming has no stage_slide"
        assert params.index("stage_slide") == params.index("user_message_persisted") + 1
        assert params[-1] == "stage_slide"
        default = inspect.signature(ChatService.send_message_streaming).parameters[
            "stage_slide"
        ].default
        assert default is None

    def test_the_graph_limb_takes_a_keyword_only_stage(self):
        params = inspect.signature(ChatService._send_message_streaming_graph).parameters
        assert "stage_slide" in params, "_send_message_streaming_graph has no stage_slide"
        assert params["stage_slide"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["stage_slide"].default is None

    def test_the_queue_helper_appends_the_stage_after_engine_mode(self):
        params = list(inspect.signature(job_queue._run_streaming_generator).parameters)
        assert "stage_slide" in params, "_run_streaming_generator has no stage_slide"
        assert params.index("stage_slide") == params.index("engine_mode") + 1

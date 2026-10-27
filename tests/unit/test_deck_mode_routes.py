"""Both chat routes carry the Deck Mode and lock it with the first message (plan Task 4).

``POST /chat/async`` (production) and ``POST /chat/stream`` (local dev) accept an optional
``deck_mode`` (``"agent"`` / ``"legacy"`` / null; anything else is a 422).  Each saves the
user message through ``SessionManager.add_user_message``, which locks an unlocked deck in
the same transaction, and maps its errors:

- ``DeckModeLockedError``  -> 409 ``{"code": "deck_mode_locked", "message": <sentence>,
  "deck_mode": <stored>}``, nothing saved;
- ``ActiveGraphReleaseUnavailableError`` (an agent first message with no release to pin)
  -> 503 ``"No active Graph Release available"``, nothing saved, the deck stays unlocked;
- anything else -> 500 ``"Internal server error"``.

The session lock is released on every one of those exits, exactly once.  On async the
two typed errors also mark the chat request ``"error"``.

The stream route now persists the message itself, BEFORE it resolves the engine, so turn 1
already reads the locked column; it tells the service so (``user_message_persisted=True``
plus ``is_first_message_override``), and the service's SSE turn-1 re-resolve is gone.

Harness.  The REAL ``SessionManager`` singleton (a fresh instance swapped into the module
global; ``routes.chat.get_session_manager`` is NOT patched) on an in-memory sqlite
``StaticPool`` engine, so the route's worker threads and the SSE thread all see one
database.  The factory has the app's settings (no autoflush, expire on commit).  Only
permission, ``get_chat_service`` and ``enqueue_job`` are patched, plus both
``get_db_session`` targets and the org-default getters (``settings_db`` binds its own
``get_db_session``).  An active Graph Release is seeded: ``get_session`` raises without one.
``release_session_lock`` is wrapped with a counting spy that still calls the real method.
Every assertion reads committed rows through a fresh session.

The old opt-out phrase is written out literally (not imported): it is ordinary text now.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.services.session_manager as session_manager_module
import src.database.models  # noqa: F401 -- register every table before create_all
from src.api.main import app
from src.api.routes.chat import ENGINE_MODE_UNAVAILABLE_DETAIL
from src.api.schemas.requests import ChatRequest
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.core.database import Base, get_db
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import ChatRequest as ChatRequestRow
from src.database.models.session import SessionMessage, UserSession
from src.services.conversation_pins import ActiveGraphReleaseUnavailableError
from tests.unit.conftest import _make_fake_db

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_LOCK = "src.api.services.session_manager.lock_active_graph_release"
_RESOLVER = "src.api.services.chat_service.resolve_engine_mode"

_ACTIVE_RELEASE_ID = 41
_ACTIVE_VERSION = 7

_MESSAGE = "build me a deck about puffins"
_LATER_MESSAGE = "and now add a slide about eider ducks"
#: The old opt-out phrase. Since Deck Mode it selects nothing.
_PHRASE_MESSAGE = "USE LEGACY MODE build me a deck about puffins"

_ROUTES = ["async", "stream"]
_PATHS = {"async": "/api/chat/async", "stream": "/api/chat/stream"}
#: ``message_type`` each route saves the user message with.
_MESSAGE_TYPES = {"async": "user_query", "stream": "user_input"}

_INTERNAL_ERROR = {"detail": "Internal server error"}
_NO_RELEASE = {"detail": "No active Graph Release available"}
_LOCKED_MESSAGES = {
    "agent": "This deck's mode is already set to Agent mode, and it can't be changed.",
    "legacy": "This deck's mode is already set to Legacy mode, and it can't be changed.",
}


# ---------------------------------------------------------------------------
# Database, seeding and reading
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture
def factory(engine):
    """The app's session settings (``get_session_local``), with an active release."""
    f = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    now = datetime.now(timezone.utc)
    db = f()
    try:
        db.add(
            GraphRelease(
                id=_ACTIVE_RELEASE_ID,
                version_number=_ACTIVE_VERSION,
                release_note="active deck-mode route release",
                published_by="unit-test@example.com",
                published_at=now - timedelta(days=1),
                effective_from=now - timedelta(days=1),
            )
        )
        db.commit()
    finally:
        db.close()
    return f


def _seed_deck(
    factory,
    *,
    deck_mode: Optional[str] = None,
    pin: Optional[int] = _ACTIVE_RELEASE_ID,
    prior_user_messages: Tuple[str, ...] = (),
) -> str:
    """An owner ``UserSession`` with exactly *deck_mode* and *pin* stored, and
    *prior_user_messages* as its transcript.  Returns its session id."""
    sid = f"deck-mode-route-{uuid.uuid4().hex[:10]}"
    db = factory()
    try:
        row = UserSession(
            session_id=sid,
            created_by="owner@example.com",
            deck_mode=deck_mode,
            graph_release_id=pin,
        )
        db.add(row)
        db.flush()
        base = datetime.utcnow() - timedelta(minutes=10)
        for i, content in enumerate(prior_user_messages):
            db.add(
                SessionMessage(
                    session_id=row.id,
                    role="user",
                    content=content,
                    message_type="user_query",
                    created_at=base + timedelta(seconds=i),
                )
            )
        db.commit()
    finally:
        db.close()
    return sid


def _deck(factory, sid: str) -> Dict[str, Any]:
    """The committed owner row: its mode, its pin and whether it is locked for processing."""
    db = factory()
    try:
        row = db.scalar(select(UserSession).where(UserSession.session_id == sid))
        assert row is not None, sid
        return {
            "deck_mode": row.deck_mode,
            "pin": row.graph_release_id,
            "is_processing": bool(row.is_processing),
        }
    finally:
        db.close()


def _user_rows(factory, sid: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Committed ``role='user'`` rows of *sid*: ``(content, message_type, request_id)``."""
    db = factory()
    try:
        internal = db.scalar(select(UserSession.id).where(UserSession.session_id == sid))
        assert internal is not None, sid
        return [
            (m.content, m.message_type, m.request_id)
            for m in db.scalars(
                select(SessionMessage)
                .where(SessionMessage.session_id == internal, SessionMessage.role == "user")
                .order_by(SessionMessage.id)
            )
        ]
    finally:
        db.close()


def _chat_requests(factory, sid: str) -> List[Tuple[str, Optional[str]]]:
    """Committed ``chat_requests`` rows of *sid*: ``(status, error_message)``."""
    db = factory()
    try:
        internal = db.scalar(select(UserSession.id).where(UserSession.session_id == sid))
        assert internal is not None, sid
        return [
            (r.status, r.error_message)
            for r in db.scalars(
                select(ChatRequestRow)
                .where(ChatRequestRow.session_id == internal)
                .order_by(ChatRequestRow.id)
            )
        ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The route harness
# ---------------------------------------------------------------------------


def _complete(*_args, **_kwargs) -> Iterator[StreamEvent]:
    return iter([StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})])


@dataclass
class _Env:
    client: TestClient
    factory: Any
    manager: SessionManager
    service: MagicMock
    enqueue: AsyncMock
    releases: List[str] = field(default_factory=list)

    def post(self, route: str, body: Dict[str, Any]):
        response = self.client.post(_PATHS[route], json=body)
        if route == "stream":
            # StreamingResponse is lazy: the SSE generator (the service call and its
            # lock release) only runs while the body is consumed.
            response.read()
        return response

    def engine_of_the_turn(self, route: str) -> str:
        """The engine the turn was handed: the job payload's key, or the service kwarg."""
        if route == "async":
            assert self.enqueue.await_count == 1, "no job was enqueued"
            return self.enqueue.await_args.args[1]["engine_mode"]
        assert self.service.send_message_streaming.call_count == 1, "the service never ran"
        return self.service.send_message_streaming.call_args.kwargs["engine_mode"]

    def nothing_ran(self) -> None:
        self.enqueue.assert_not_awaited()
        self.service.send_message_streaming.assert_not_called()


@pytest.fixture
def client(factory):
    db = factory()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


@pytest.fixture
def env(client, factory):
    fake_db = _make_fake_db(factory)
    manager = SessionManager()
    releases: List[str] = []
    real_release = SessionManager.release_session_lock

    def counting_release(self, session_id):
        releases.append(session_id)
        return real_release(self, session_id)

    service = MagicMock()
    service.send_message_streaming.side_effect = _complete

    with patch("src.api.routes.chat._check_chat_permission"), patch(
        "src.api.routes.chat.get_chat_service", return_value=service
    ), patch(
        "src.api.routes.chat.enqueue_job", new_callable=AsyncMock
    ) as enqueue, patch(_DB_SOURCE, fake_db), patch(_MANAGER_DB, fake_db), patch(
        "src.api.routes.chat.get_default_design_system_id", return_value=None
    ), patch(
        "src.api.routes.chat.get_default_slide_style_id", return_value=None
    ), patch(
        "src.api.routes.chat.get_default_template_id", return_value=None
    ), patch.object(
        session_manager_module, "_session_manager", manager
    ), patch.object(
        SessionManager, "release_session_lock", counting_release
    ):
        yield _Env(
            client=client,
            factory=factory,
            manager=manager,
            service=service,
            enqueue=enqueue,
            releases=releases,
        )


def _body(sid: Optional[str], message: str = _MESSAGE, **extra) -> Dict[str, Any]:
    body: Dict[str, Any] = {"message": message, **extra}
    if sid is not None:
        body["session_id"] = sid
    return body


def _assert_released_once(env: _Env, sid: str) -> None:
    assert env.releases == [sid], (
        f"the session lock must be released exactly once, got {env.releases!r}"
    )
    assert _deck(env.factory, sid)["is_processing"] is False
    # And it really is free: the next turn can take it.
    assert env.manager.acquire_session_lock(sid) is True


def _observe_the_service_call(env: _Env, sid: str) -> Dict[str, Any]:
    """Make the mocked service record the database AS IT IS CALLED, then complete."""
    observed: Dict[str, Any] = {}

    def observe(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        observed["user_rows"] = _user_rows(env.factory, sid)
        observed["deck"] = _deck(env.factory, sid)
        return _complete()

    env.service.send_message_streaming.side_effect = observe
    return observed


# ---------------------------------------------------------------------------
# The request field
# ---------------------------------------------------------------------------


def test_the_request_field_is_optional_and_holds_only_the_two_modes():
    assert ChatRequest(message="hi").deck_mode is None
    assert ChatRequest(message="hi", deck_mode=None).deck_mode is None
    assert ChatRequest(message="hi", deck_mode="agent").deck_mode == "agent"
    assert ChatRequest(message="hi", deck_mode="legacy").deck_mode == "legacy"


@pytest.mark.parametrize("value", ["monolith", "graph", "Agent", "LEGACY", ""])
@pytest.mark.parametrize("route", _ROUTES)
def test_an_unknown_deck_mode_is_a_422(env, route, value):
    sid = _seed_deck(env.factory)

    response = env.post(route, _body(sid, deck_mode=value))

    assert response.status_code == 422, response.text
    assert _user_rows(env.factory, sid) == []
    assert _deck(env.factory, sid) == {
        "deck_mode": None,
        "pin": _ACTIVE_RELEASE_ID,
        "is_processing": False,
    }
    assert _chat_requests(env.factory, sid) == []
    env.nothing_ran()


# ---------------------------------------------------------------------------
# A first message locks the deck, and turn 1 runs on what it locked
# ---------------------------------------------------------------------------


def test_async_first_message_with_legacy_enqueues_monolith_and_locks_legacy(env):
    sid = _seed_deck(env.factory)

    response = env.post("async", _body(sid, deck_mode="legacy"))

    assert response.status_code == 200, response.text
    request_id = response.json()["request_id"]
    payload = env.enqueue.await_args.args[1]
    assert payload["engine_mode"] == "monolith"
    assert payload["is_first_message"] is True
    assert _deck(env.factory, sid)["deck_mode"] == "legacy"
    # Locking legacy clears the deck's pin.
    assert _deck(env.factory, sid)["pin"] is None
    assert _user_rows(env.factory, sid) == [(_MESSAGE, "user_query", request_id)]
    # On success the async route hands the lock to the worker; it must not release it.
    assert env.releases == []


def test_stream_first_message_with_legacy_runs_monolith_on_turn_one(env):
    sid = _seed_deck(env.factory)
    observed = _observe_the_service_call(env, sid)

    response = env.post("stream", _body(sid, deck_mode="legacy"))

    assert response.status_code == 200, response.text
    assert "kwargs" in observed, "the service was never called"
    kwargs = observed["kwargs"]
    assert kwargs["engine_mode"] == "monolith"
    assert kwargs["user_message_persisted"] is True
    assert kwargs["is_first_message_override"] is True
    assert kwargs["message"] == _MESSAGE
    # The route saved the message, and locked the deck, BEFORE the service ran.
    assert observed["user_rows"] == [(_MESSAGE, "user_input", None)]
    assert observed["deck"]["deck_mode"] == "legacy"
    assert observed["deck"]["pin"] is None
    # ...and nothing saved it a second time.
    assert _user_rows(env.factory, sid) == [(_MESSAGE, "user_input", None)]
    _assert_released_once(env, sid)


@pytest.mark.parametrize("sent", ["omitted", "null"])
@pytest.mark.parametrize("route", _ROUTES)
def test_a_first_message_with_no_deck_mode_locks_agent(env, route, sent):
    sid = _seed_deck(env.factory)
    extra = {} if sent == "omitted" else {"deck_mode": None}

    response = env.post(route, _body(sid, **extra))

    assert response.status_code == 200, response.text
    assert env.engine_of_the_turn(route) == "graph"
    assert _deck(env.factory, sid)["deck_mode"] == "agent"
    # An agent lock never moves an existing pin.
    assert _deck(env.factory, sid)["pin"] == _ACTIVE_RELEASE_ID
    assert len(_user_rows(env.factory, sid)) == 1
    if route == "stream":
        kwargs = env.service.send_message_streaming.call_args.kwargs
        assert kwargs["is_first_message_override"] is True


@pytest.mark.parametrize("route", _ROUTES)
def test_the_typed_phrase_is_ordinary_text(env, route):
    sid = _seed_deck(env.factory)

    response = env.post(route, _body(sid, message=_PHRASE_MESSAGE))

    assert response.status_code == 200, response.text
    assert env.engine_of_the_turn(route) == "graph"
    assert _deck(env.factory, sid)["deck_mode"] == "agent"
    assert [row[0] for row in _user_rows(env.factory, sid)] == [_PHRASE_MESSAGE]


@pytest.mark.parametrize(
    ("sent", "locked_as", "expected_engine", "expected_pin"),
    [(None, "agent", "graph", _ACTIVE_RELEASE_ID), ("legacy", "legacy", "monolith", None)],
    ids=["no-mode", "legacy"],
)
@pytest.mark.parametrize("route", _ROUTES)
def test_a_new_session_created_by_the_chat_route_is_locked_by_its_first_message(
    env, route, sent, locked_as, expected_engine, expected_pin
):
    """The production first send: a browser-generated id that was never persisted."""
    sid = f"local-{uuid.uuid4().hex[:10]}"
    extra = {} if sent is None else {"deck_mode": sent}

    response = env.post(route, _body(sid, **extra))

    assert response.status_code == 200, response.text
    assert env.engine_of_the_turn(route) == expected_engine
    assert _deck(env.factory, sid)["deck_mode"] == locked_as
    assert _deck(env.factory, sid)["pin"] == expected_pin
    assert [row[:2] for row in _user_rows(env.factory, sid)] == [
        (_MESSAGE, _MESSAGE_TYPES[route])
    ]
    if route == "stream":
        kwargs = env.service.send_message_streaming.call_args.kwargs
        assert kwargs["is_first_message_override"] is True
    else:
        assert env.enqueue.await_args.args[1]["is_first_message"] is True


# ---------------------------------------------------------------------------
# A locked deck
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "sent"),
    [("agent", "legacy"), ("legacy", "agent")],
    ids=["agent-deck", "legacy-deck"],
)
@pytest.mark.parametrize("route", _ROUTES)
def test_a_different_mode_on_a_locked_deck_is_a_409_and_saves_nothing(env, route, stored, sent):
    pin = _ACTIVE_RELEASE_ID if stored == "agent" else None
    sid = _seed_deck(env.factory, deck_mode=stored, pin=pin, prior_user_messages=(_MESSAGE,))

    response = env.post(route, _body(sid, message=_LATER_MESSAGE, deck_mode=sent))

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "deck_mode_locked"
    assert detail["deck_mode"] == stored
    assert detail == {
        "code": "deck_mode_locked",
        "message": _LOCKED_MESSAGES[stored],
        "deck_mode": stored,
    }
    assert [row[0] for row in _user_rows(env.factory, sid)] == [_MESSAGE]
    assert _deck(env.factory, sid)["deck_mode"] == stored
    assert _deck(env.factory, sid)["pin"] == pin
    env.nothing_ran()
    if route == "async":
        assert _chat_requests(env.factory, sid) == [("error", "deck_mode_locked")]
    _assert_released_once(env, sid)


@pytest.mark.parametrize("sent", [None, "legacy"], ids=["no-mode", "same-mode"])
@pytest.mark.parametrize("route", _ROUTES)
def test_a_locked_legacy_deck_with_no_deck_mode_proceeds_on_monolith(env, route, sent):
    sid = _seed_deck(env.factory, deck_mode="legacy", pin=None, prior_user_messages=(_MESSAGE,))
    extra = {} if sent is None else {"deck_mode": sent}
    observed = _observe_the_service_call(env, sid) if route == "stream" else {}

    response = env.post(route, _body(sid, message=_LATER_MESSAGE, **extra))

    assert response.status_code == 200, response.text
    assert env.engine_of_the_turn(route) == "monolith"
    assert [row[0] for row in _user_rows(env.factory, sid)] == [_MESSAGE, _LATER_MESSAGE]
    assert _deck(env.factory, sid)["deck_mode"] == "legacy"
    assert _deck(env.factory, sid)["pin"] is None
    if route == "stream":
        assert observed["kwargs"]["user_message_persisted"] is True
        assert observed["kwargs"]["is_first_message_override"] is False
        assert [row[0] for row in observed["user_rows"]] == [_MESSAGE, _LATER_MESSAGE]
        _assert_released_once(env, sid)
    else:
        assert env.enqueue.await_args.args[1]["is_first_message"] is False


# ---------------------------------------------------------------------------
# Failures around the save
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "locked_as"), [(None, "agent"), ("legacy", "legacy")], ids=["no-mode", "legacy"]
)
@pytest.mark.parametrize("route", _ROUTES)
def test_resolution_failure_after_the_first_message_leaves_the_deck_locked(
    env, route, sent, locked_as
):
    """Review Focus 1: the message committed, so the deck IS locked; the turn 503s."""
    sid = _seed_deck(env.factory)
    extra = {} if sent is None else {"deck_mode": sent}

    def boom(session_id):
        raise RuntimeError("the database went away at 10.0.0.7:5432")

    with patch(_RESOLVER, boom):
        response = env.post(route, _body(sid, **extra))

    assert response.status_code == 503, response.text
    assert response.json() == {"detail": ENGINE_MODE_UNAVAILABLE_DETAIL}
    assert [row[0] for row in _user_rows(env.factory, sid)] == [_MESSAGE]
    assert _deck(env.factory, sid)["deck_mode"] == locked_as
    env.nothing_ran()
    _assert_released_once(env, sid)


@pytest.mark.parametrize("sent", [None, "agent"], ids=["no-mode", "agent"])
@pytest.mark.parametrize("route", _ROUTES)
def test_no_active_graph_release_on_an_agent_first_message_is_a_503_and_leaves_the_deck_unlocked(
    env, route, sent
):
    """An unpinned, unlocked owner: an agent lock must pin it, and nothing can be pinned.

    The release IS seeded (``get_session`` needs it); the pin step is what fails.
    """
    sid = _seed_deck(env.factory, pin=None)
    extra = {} if sent is None else {"deck_mode": sent}

    with patch(_LOCK, side_effect=ActiveGraphReleaseUnavailableError("no active Graph Release")):
        response = env.post(route, _body(sid, **extra))

    assert response.status_code == 503, response.text
    assert response.json() == _NO_RELEASE
    assert _deck(env.factory, sid)["deck_mode"] is None
    assert _deck(env.factory, sid)["pin"] is None
    assert _user_rows(env.factory, sid) == []
    env.nothing_ran()
    if route == "async":
        [(status, error)] = _chat_requests(env.factory, sid)
        assert status == "error"
        assert error, "the failed chat request must carry an error code"
    _assert_released_once(env, sid)


@pytest.mark.parametrize("failure", ["deck-mode-locked", "no-active-release"])
def test_a_failed_status_write_never_masks_the_async_409_or_503(env, failure):
    """Marking the chat request ``error`` is best effort: if that write fails, the
    caller still gets the typed 409/503, and the lock is still released once."""
    if failure == "deck-mode-locked":
        sid = _seed_deck(env.factory, deck_mode="agent", prior_user_messages=(_MESSAGE,))
        body = _body(sid, message=_LATER_MESSAGE, deck_mode="legacy")
        expected = (
            409,
            {
                "detail": {
                    "code": "deck_mode_locked",
                    "message": _LOCKED_MESSAGES["agent"],
                    "deck_mode": "agent",
                }
            },
        )
        lock = contextlib.nullcontext()
    else:
        sid = _seed_deck(env.factory, pin=None)
        body = _body(sid)
        expected = (503, _NO_RELEASE)
        lock = patch(
            _LOCK, side_effect=ActiveGraphReleaseUnavailableError("no active Graph Release")
        )

    with lock, patch.object(
        SessionManager,
        "update_chat_request_status",
        side_effect=RuntimeError("the status write failed"),
    ) as status_write:
        response = env.post("async", body)

    assert status_write.call_count == 1, "the route never tried to mark the request"
    assert (response.status_code, response.json()) == expected, response.text
    assert "the status write failed" not in response.text
    env.nothing_ran()
    _assert_released_once(env, sid)


@pytest.mark.parametrize("route", _ROUTES)
def test_an_unexpected_error_while_saving_the_first_message_releases_the_lock(env, route):
    sid = _seed_deck(env.factory)

    with patch.object(
        SessionManager, "add_user_message", side_effect=RuntimeError("disk on fire")
    ) as save:
        response = env.post(route, _body(sid))

    assert save.call_count == 1, "the route did not save through add_user_message"
    assert response.status_code == 500, response.text
    assert response.json() == _INTERNAL_ERROR
    assert "disk on fire" not in response.text
    assert _user_rows(env.factory, sid) == []
    assert _deck(env.factory, sid)["deck_mode"] is None
    env.nothing_ran()
    _assert_released_once(env, sid)


@pytest.mark.parametrize(
    ("error", "status"),
    [(SessionNotFoundError("gone"), 404), (RuntimeError("the database went away"), 500)],
    ids=["not-found", "other"],
)
@pytest.mark.parametrize("route", _ROUTES)
def test_a_failed_session_read_after_the_lock_is_taken_releases_it(env, route, error, status):
    """The first-message read runs under the lock, before any response exists."""
    sid = _seed_deck(env.factory)
    real_get_session = SessionManager.get_session

    def get_session_failing_under_the_lock(self, session_id):
        if _deck(env.factory, session_id)["is_processing"]:
            raise error
        return real_get_session(self, session_id)

    with patch.object(SessionManager, "get_session", get_session_failing_under_the_lock):
        response = env.post(route, _body(sid))

    assert response.status_code == status, response.text
    if status == 500:
        assert response.json() == _INTERNAL_ERROR
    assert _user_rows(env.factory, sid) == []
    env.nothing_ran()
    _assert_released_once(env, sid)


# ---------------------------------------------------------------------------
# Review Focus 3: images on the stream route
# ---------------------------------------------------------------------------


def test_stream_persists_the_raw_message_once_when_images_are_attached(env):
    sid = _seed_deck(env.factory)
    observed = _observe_the_service_call(env, sid)

    response = env.post("stream", _body(sid, image_ids=["img-1"]))

    assert response.status_code == 200, response.text
    assert "kwargs" in observed, "the service was never called"
    assert observed["kwargs"]["user_message_persisted"] is True
    # The service still gets the images, to inject their context for the model...
    assert observed["kwargs"]["image_ids"] == ["img-1"]
    # ...but the saved row is exactly what the user typed, saved once.
    assert _user_rows(env.factory, sid) == [(_MESSAGE, "user_input", None)]


# ---------------------------------------------------------------------------
# The service: a message the route persisted is not persisted again (C7)
# ---------------------------------------------------------------------------


class _ReachedTheMonolithError(Exception):
    """Raised from ``_detect_edit_intent``: the persist block is already behind us."""


class TestSendMessageStreamingHonoursAPersistedMessage:
    """``ChatService.send_message_streaming`` itself, with a mocked session manager.

    With the route's service mocked, "one user row" cannot catch a service that ignores
    ``user_message_persisted``; this drives the real method up to the monolith's first
    step, with images attached (the injected-context message is what it would save).
    """

    @pytest.fixture
    def manager(self):
        manager = MagicMock()
        manager.get_session.return_value = {"session_id": "sse-1", "message_count": 0}
        manager.add_message.return_value = {"id": 7}

        def inject(self, message, image_ids):
            return f"{message}\n[image context: {', '.join(image_ids)}]"

        with patch(
            "src.api.services.chat_service.get_session_manager", return_value=manager
        ), patch("src.core.settings_db.get_settings", return_value=MagicMock()), patch(
            _RESOLVER, return_value="monolith"
        ), patch.object(ChatService, "_inject_image_context", inject), patch.object(
            ChatService, "_detect_edit_intent", side_effect=_ReachedTheMonolithError
        ), patch.object(
            ChatService,
            "_send_message_streaming_graph",
            side_effect=AssertionError("a monolith turn reached the graph"),
        ):
            yield manager

    def _drive(self, **kwargs) -> None:
        with pytest.raises(_ReachedTheMonolithError):
            for _event in ChatService().send_message_streaming(
                "sse-1",
                _MESSAGE,
                image_ids=["img-1"],
                engine_mode="monolith",
                **kwargs,
            ):
                pass

    def test_a_persisted_message_is_never_saved_again(self, manager):
        self._drive(user_message_persisted=True, is_first_message_override=True)

        manager.add_message.assert_not_called()
        manager.create_session.assert_not_called()

    @pytest.mark.parametrize("persisted", ["explicit-false", "omitted"])
    def test_an_unpersisted_sse_message_is_saved_once(self, manager, persisted):
        kwargs = {"user_message_persisted": False} if persisted == "explicit-false" else {}

        self._drive(**kwargs)

        assert manager.add_message.call_count == 1, manager.add_message.call_args_list
        assert manager.add_message.call_args.kwargs["role"] == "user"

    def test_the_service_never_resolves_the_engine_itself(self, manager):
        """The SSE turn-1 re-resolve is gone: the route resolved after its own save,
        so the service runs exactly the engine it is handed."""
        with patch(
            _RESOLVER,
            side_effect=AssertionError("send_message_streaming resolved the engine itself"),
        ):
            self._drive()

        assert manager.add_message.call_count == 1

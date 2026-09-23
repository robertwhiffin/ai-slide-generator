"""Focused contracts for every Task-2 conversation creator."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 -- register all tables
from src.api.routes.chat import _maybe_create_session
from src.api.schemas.requests import ChatRequest, DuplicateSessionRequest
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import (
    ChatRequest as ChatRequestRow,
    SessionMessage,
    SessionSlideDeck,
    UserSession,
)
from src.domain.conversation_engine import AGENT_MODE_PHRASE
from src.services.conversation_pins import ActiveGraphReleaseUnavailableError


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        db.add_all(
            [
                GraphRelease(
                    id=101,
                    version_number=1,
                    release_note="closed R1",
                    published_by="unit@example.com",
                    published_at=now,
                    effective_from=now,
                    effective_to=now + timedelta(seconds=1),
                ),
                GraphRelease(
                    id=202,
                    version_number=2,
                    previous_release_id=101,
                    release_note="active R2",
                    published_by="unit@example.com",
                    published_at=now + timedelta(seconds=1),
                    effective_from=now + timedelta(seconds=1),
                ),
            ]
        )
    try:
        yield factory
    finally:
        engine.dispose()


def _database_context(factory):
    @contextlib.contextmanager
    def managed_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return managed_session


@pytest.mark.parametrize("supplied_id", [False, True], ids=["generated-id", "supplied-missing-id"])
@pytest.mark.parametrize(
    ("message", "expected_capable"),
    [
        (f"{AGENT_MODE_PHRASE} make a deck", True),
        ("make a deck without the marker", False),
    ],
    ids=["marker", "non-marker"],
)
def test_chat_creation_branches_forward_literal_message_capability(
    supplied_id, message, expected_capable
):
    """Dropping either branch's capability argument creates an unpinned graph chat."""
    manager = MagicMock()
    manager.get_session.side_effect = SessionNotFoundError("client-id")
    manager.create_session.return_value = {"session_id": "server-id"}
    request = ChatRequest(
        session_id="client-id" if supplied_id else None,
        message=message,
    )

    with patch("src.api.routes.chat.get_current_user", return_value="author@example.com"):
        created = _maybe_create_session(request, manager)

    assert created is True
    assert request.session_id == ("client-id" if supplied_id else "server-id")
    assert manager.create_session.call_args.kwargs["graph_capable"] is expected_capable
    if supplied_id:
        manager.get_session.assert_called_once_with("client-id")


class _StopAfterCreation(RuntimeError):
    pass


@pytest.mark.parametrize(
    ("method_name", "message", "expected_capable"),
    [
        ("send_message", f"{AGENT_MODE_PHRASE} sync", True),
        ("send_message", "plain sync", False),
        ("send_message_streaming", f"{AGENT_MODE_PHRASE} stream", True),
        ("send_message_streaming", "plain stream", False),
    ],
)
def test_chat_service_fallbacks_forward_literal_message_capability(
    method_name, message, expected_capable
):
    """A direct service fallback must not create a graph conversation without a pin."""
    manager = MagicMock()
    manager.get_session.side_effect = SessionNotFoundError("missing")
    manager.create_session.return_value = {"session_id": "missing", "message_count": 0}
    service = ChatService.__new__(ChatService)
    service._detect_edit_intent = MagicMock(side_effect=_StopAfterCreation)

    with patch("src.api.services.chat_service.get_session_manager", return_value=manager), patch(
        "src.core.settings_db.get_settings", return_value=MagicMock()
    ):
        with pytest.raises(_StopAfterCreation):
            if method_name == "send_message":
                service.send_message("missing", message)
            else:
                next(
                    service.send_message_streaming(
                        "missing",
                        message,
                        request_id="already-persisted",
                    )
                )

    assert manager.create_session.call_args.kwargs == {
        "session_id": "missing",
        "graph_capable": expected_capable,
    }


def test_create_chat_request_rejects_an_absent_session_without_inserting(factory):
    """Restoring polling auto-create would bypass message-aware release locking."""
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ):
        with pytest.raises(SessionNotFoundError):
            manager.create_chat_request("absent", "author@example.com")

    with factory() as db:
        assert db.scalar(select(UserSession).where(UserSession.session_id == "absent")) is None
        assert db.scalar(select(ChatRequestRow).where(ChatRequestRow.request_id.is_not(None))) is None


def test_async_chat_maps_absent_route_created_session_to_404():
    """Catching the polling boundary generically would hide a disappeared session as 500."""
    from src.api.routes import chat

    manager = MagicMock()
    manager.get_session.return_value = {"message_count": 0}
    manager.acquire_session_lock.return_value = True
    manager.create_chat_request.side_effect = SessionNotFoundError("gone")
    request = ChatRequest(session_id="gone", message="plain request")

    with patch.object(chat, "get_session_manager", return_value=manager), patch.object(
        chat, "_check_chat_permission"
    ), patch.object(chat, "get_current_user", return_value="author@example.com"):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(chat.submit_chat_async(request, MagicMock()))

    assert (exc_info.value.status_code, exc_info.value.detail) == (
        404,
        "Session not found: gone",
    )


def test_contributor_pins_active_r2_without_repinning_r1_parent(factory):
    """Copying the owner's R1 pin would run a newly capable contributor on stale code."""
    with factory.begin() as db:
        db.add(
            UserSession(
                session_id="root-r1",
                created_by="owner@example.com",
                graph_release_id=101,
            )
        )

    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ):
        result = manager.get_or_create_contributor_session(
            "root-r1", "contributor@example.com"
        )

    with factory() as db:
        root = db.scalar(select(UserSession).where(UserSession.session_id == "root-r1"))
        actor = db.scalar(
            select(UserSession).where(UserSession.session_id == result["session_id"])
        )
        assert (root.graph_release_id, actor.graph_release_id) == (101, 202)
        assert actor.parent_session_id == root.id


def test_existing_contributor_returns_before_lock_and_keeps_its_pin(factory):
    """Moving idempotency below the lock would relock or repin an existing actor."""
    with factory.begin() as db:
        root = UserSession(session_id="root", created_by="owner@example.com")
        db.add(root)
        db.flush()
        db.add(
            UserSession(
                session_id="existing-actor",
                created_by="contributor@example.com",
                parent_session_id=root.id,
                graph_release_id=101,
            )
        )

    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        side_effect=AssertionError("existing contributor must not lock"),
    ):
        result = manager.get_or_create_contributor_session(
            "root", "contributor@example.com"
        )

    assert result["session_id"] == "existing-actor"
    with factory() as db:
        actor = db.scalar(
            select(UserSession).where(UserSession.session_id == "existing-actor")
        )
        assert actor.graph_release_id == 101


def _seed_duplicate_source(factory, *, session_id: str, message: str):
    with factory.begin() as db:
        source = UserSession(
            session_id=session_id,
            created_by="owner@example.com",
            title="Source",
            graph_release_id=101,
        )
        db.add(source)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=source.id,
                title="Source",
                html_content="<div>source</div>",
                slide_count=1,
                deck_json='{"slides":[{"html":"<div>source</div>"}]}',
            )
        )
        db.add(SessionMessage(session_id=source.id, role="user", content=message))


def test_graph_marker_duplicate_locks_r2_and_never_copies_or_repins_source(factory):
    """Copying the source pin would give the new graph actor R1 instead of locked R2."""
    _seed_duplicate_source(
        factory,
        session_id="marker-source",
        message=f"{AGENT_MODE_PHRASE} duplicate me",
    )
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ):
        result = manager.duplicate_session("marker-source", "copier@example.com")

    with factory() as db:
        source = db.scalar(
            select(UserSession).where(UserSession.session_id == "marker-source")
        )
        duplicate = db.scalar(
            select(UserSession).where(UserSession.session_id == result["session_id"])
        )
        marker = db.scalar(
            select(SessionMessage).where(SessionMessage.session_id == duplicate.id)
        )
        assert (source.graph_release_id, duplicate.graph_release_id) == (101, 202)
        assert marker.content == f"{AGENT_MODE_PHRASE} duplicate me"


def test_non_marker_duplicate_stays_unpinned_and_never_locks(factory):
    """Locking every duplicate would classify monolith copies as graph actors."""
    _seed_duplicate_source(
        factory,
        session_id="plain-source",
        message="ordinary monolith request",
    )
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        side_effect=AssertionError("non-marker duplicate must not lock"),
    ):
        result = manager.duplicate_session("plain-source", "copier@example.com")

    with factory() as db:
        source = db.scalar(
            select(UserSession).where(UserSession.session_id == "plain-source")
        )
        duplicate = db.scalar(
            select(UserSession).where(UserSession.session_id == result["session_id"])
        )
        assert (source.graph_release_id, duplicate.graph_release_id) == (101, None)
        assert db.scalar(
            select(SessionMessage).where(SessionMessage.session_id == duplicate.id)
        ) is None


@pytest.mark.parametrize("route_name", ["send_message", "send_message_streaming", "submit_chat_async"])
def test_chat_creation_unavailability_maps_to_exact_503(route_name):
    """A missing active release at a chat creator must not leak or become a generic 500."""
    from src.api.routes import chat

    manager = MagicMock()
    manager.create_session.side_effect = ActiveGraphReleaseUnavailableError("no active")
    route = getattr(chat, route_name)
    with patch.object(chat, "get_session_manager", return_value=manager), patch.object(
        chat, "_check_chat_permission"
    ), patch.object(chat, "get_current_user", return_value="author@example.com"):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                route(
                    ChatRequest(message=f"{AGENT_MODE_PHRASE} create"),
                    MagicMock(),
                )
            )

    assert (exc_info.value.status_code, exc_info.value.detail) == (
        503,
        "No active Graph Release available",
    )


@pytest.mark.parametrize("route_name", ["contributor", "duplicate"])
def test_session_creator_unavailability_maps_to_exact_503(route_name):
    """Contributor and marker-duplicate lock failures must preserve the release 503."""
    from src.api.routes import sessions

    manager = MagicMock()
    manager.get_session.return_value = {"created_by": "owner@example.com"}
    error = ActiveGraphReleaseUnavailableError("no active")
    manager.get_or_create_contributor_session.side_effect = error
    manager.duplicate_session.side_effect = error

    with patch.object(sessions, "get_session_manager", return_value=manager), patch.object(
        sessions, "get_current_user", return_value="actor@example.com"
    ), patch.object(
        sessions, "_require_session_access", return_value=PermissionLevel.CAN_VIEW
    ):
        with pytest.raises(HTTPException) as exc_info:
            if route_name == "contributor":
                asyncio.run(
                    sessions.get_or_create_contributor_session("source", MagicMock())
                )
            else:
                asyncio.run(
                    sessions.duplicate_session("source", DuplicateSessionRequest())
                )

    assert (exc_info.value.status_code, exc_info.value.detail) == (
        503,
        "No active Graph Release available",
    )

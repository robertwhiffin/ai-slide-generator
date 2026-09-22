"""Contracts for explicit graph-capable root-session creation."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 -- register ORM tables before create_all
from src.api.schemas.requests import CreateSessionRequest
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import UserSession
from src.services.conversation_pins import (
    MAX_ACTIVE_RELEASE_LOCK_SCANS,
    ActiveGraphReleaseUnavailableError,
    ConversationPinMissingError,
    ConversationSessionNotFoundError,
    PinnedRelease,
    load_conversation_pin,
    lock_active_graph_release,
)


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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


def _session_pin(factory, session_id: str):
    with factory() as db:
        return db.scalar(
            select(UserSession.graph_release_id).where(UserSession.session_id == session_id)
        )


def test_request_defaults_graph_capable_to_false():
    """Changing the request default would accidentally pin non-browser callers."""
    assert CreateSessionRequest().graph_capable is False


def test_non_graph_capable_root_stays_unpinned(factory):
    """Removing the false branch would write a graph identity for legacy roots."""
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release"
    ) as lock_active:
        manager.create_session(session_id="legacy-root", graph_capable=False)

    lock_active.assert_not_called()
    assert _session_pin(factory, "legacy-root") is None


def test_graph_capable_root_is_pinned_to_the_locked_active_release(factory):
    """Omitting the lock result from a new root would make it release-ambiguous."""
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        return_value=PinnedRelease(release_id=41, graph_version=7),
    ) as lock_active:
        manager.create_session(session_id="graph-root", graph_capable=True)

    lock_active.assert_called_once()
    assert _session_pin(factory, "graph-root") == 41


def test_existing_explicit_id_returns_before_locking_or_repinning(factory):
    """Moving duplicate detection below locking would mutate/relock an existing root."""
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        return_value=PinnedRelease(release_id=41, graph_version=7),
    ):
        manager.create_session(session_id="same-root", graph_capable=True)

    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        return_value=PinnedRelease(release_id=99, graph_version=8),
    ) as lock_active:
        result = manager.create_session(session_id="same-root", graph_capable=True)

    lock_active.assert_not_called()
    assert result["session_id"] == "same-root"
    assert _session_pin(factory, "same-root") == 41


def test_load_conversation_pin_uses_only_the_persisted_integer(factory):
    """Replacing persisted identity with an active-release lookup would be incorrect."""
    with factory.begin() as db:
        db.add(UserSession(session_id="pinned-root", graph_release_id=41))

    statements: list[str] = []

    @event.listens_for(factory.kw["bind"], "before_cursor_execute")
    def record_lookup(_conn, _cursor, statement, _params, _ctx, _many):
        statements.append(statement)

    try:
        assert load_conversation_pin(factory, "pinned-root") == 41
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", record_lookup)

    assert len(statements) == 1
    assert "user_sessions" in statements[0]
    assert "FROM graph_release" not in statements[0]


@pytest.mark.parametrize(
    ("session_id", "expected_error"),
    [
        ("missing-root", ConversationSessionNotFoundError),
        ("null-root", ConversationPinMissingError),
    ],
)
def test_load_conversation_pin_distinguishes_missing_session_from_missing_pin(
    factory, session_id, expected_error
):
    """Collapsing these failures would hide a missing pin on an existing root."""
    with factory.begin() as db:
        db.add(UserSession(session_id="null-root", graph_release_id=None))

    with pytest.raises(expected_error):
        load_conversation_pin(factory, session_id)


def test_load_conversation_pin_rejects_a_non_integer_pin():
    """A stringly persisted pin must not become a graph-release identifier."""
    db = Mock()
    db.scalar.return_value = SimpleNamespace(graph_release_id="41")

    @contextlib.contextmanager
    def factory():
        yield db

    with pytest.raises(ConversationPinMissingError):
        load_conversation_pin(factory, "bad-pin")


def test_lock_active_graph_release_stops_after_its_bounded_handoff_retry():
    """Turning retries into a fallback loop could pin a release from a later state."""
    db = Mock()
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(ActiveGraphReleaseUnavailableError):
        lock_active_graph_release(db)

    assert db.execute.call_count == MAX_ACTIVE_RELEASE_LOCK_SCANS


def test_lock_active_graph_release_returns_the_exact_active_release(factory):
    """Inverting the active predicate would make a valid graph-capable root unavailable."""
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        db.add(
            GraphRelease(
                version_number=7,
                release_note="active unit-test release",
                published_by="unit-test@example.com",
                published_at=now,
                effective_from=now,
            )
        )

    with factory() as db:
        assert lock_active_graph_release(db) == PinnedRelease(1, 7)


@pytest.mark.parametrize(
    ("body", "session_id"),
    [
        ({"session_id": "route-omitted"}, "route-omitted"),
        (
            {"session_id": "route-explicit-false", "graph_capable": False},
            "route-explicit-false",
        ),
    ],
)
def test_explicit_sessions_post_omitted_or_false_capability_stays_unpinned(
    factory, body, session_id
):
    """A route default that turns false/omitted into true would pin browser roots."""
    from src.api.routes.sessions import router

    app = FastAPI()
    app.include_router(router)
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        return_value=PinnedRelease(release_id=41, graph_version=7),
    ) as lock_active, patch(
        "src.api.routes.sessions.get_current_user", return_value="route-user@example.com"
    ), patch("src.api.routes.sessions.get_session_manager", return_value=manager), TestClient(
        app
    ) as client:
        response = client.post("/api/sessions", json=body)

    assert response.status_code == 200
    assert response.json()["session_id"] == session_id
    assert _session_pin(factory, session_id) is None
    lock_active.assert_not_called()


def test_explicit_sessions_route_forwards_only_graph_capability():
    """Dropping graph_capable at the explicit root boundary loses the caller's choice."""
    manager = Mock()
    manager.create_session.return_value = {"session_id": "route-root"}
    with patch("src.api.routes.sessions.get_current_user", return_value="user@example.com"), patch(
        "src.api.routes.sessions.get_session_manager", return_value=manager
    ):
        result = asyncio.run(
            __import__("src.api.routes.sessions", fromlist=["create_session"]).create_session(
                CreateSessionRequest(session_id="route-root", title="A", graph_capable=True)
            )
        )

    assert result == {"session_id": "route-root"}
    assert manager.create_session.call_args.kwargs == {
        "session_id": "route-root",
        "title": "A",
        "created_by": "user@example.com",
        "graph_capable": True,
    }


def test_only_explicit_sessions_route_maps_no_active_release_to_503():
    """Treating an unavailable active release as a generic 500 loses retry semantics."""
    from fastapi import HTTPException

    from src.api.routes.sessions import create_session

    manager = Mock()
    manager.create_session.side_effect = ActiveGraphReleaseUnavailableError(
        "no active Graph Release"
    )
    with patch("src.api.routes.sessions.get_current_user", return_value="user@example.com"), patch(
        "src.api.routes.sessions.get_session_manager", return_value=manager
    ), pytest.raises(HTTPException) as raised:
        asyncio.run(create_session(CreateSessionRequest(graph_capable=True)))

    assert raised.value.status_code == 503
    assert raised.value.detail == "No active Graph Release available"

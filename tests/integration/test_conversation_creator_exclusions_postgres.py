"""Real-PostgreSQL exclusions for non-graph conversation creators."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.api import mcp_server
from src.api.routes.tour import _phase1_create_session
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import ChatRequest, UserSession

pytestmark = pytest.mark.postgres


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


def _factory_with_active_release(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        db.add(
            GraphRelease(
                version_number=1,
                release_note="creator exclusion R1",
                published_by="exclusions@example.com",
                published_at=now,
                effective_from=now,
            )
        )
    return factory


def _pin(factory, session_id):
    with factory() as db:
        return db.scalar(
            select(UserSession.graph_release_id).where(
                UserSession.session_id == session_id
            )
        )


def _deck_mode(factory, session_id):
    with factory() as db:
        return db.scalar(
            select(UserSession.deck_mode).where(UserSession.session_id == session_id)
        )


class _RecordingManager:
    """Record the caller's explicit capability while delegating real DB behavior."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.create_kwargs = []

    def create_session(self, **kwargs):
        self.create_kwargs.append(dict(kwargs))
        return self.delegate.create_session(**kwargs)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


def _lock_tripwire(*_args, **_kwargs):
    raise AssertionError("excluded creator must not lock an active Graph Release")


def test_direct_false_creation_stays_null_and_never_locks(postgres_engine):
    """Changing the false branch to lock would pin a legacy/direct root."""
    factory = _factory_with_active_release(postgres_engine)
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        side_effect=_lock_tripwire,
    ):
        result = manager.create_session(
            session_id="direct-false",
            created_by="direct@example.com",
            graph_capable=False,
        )

    assert result["session_id"] == "direct-false"
    assert _pin(factory, "direct-false") is None


def test_create_chat_request_cannot_create_an_absent_session(postgres_engine):
    """Restoring the polling constructor would insert an unlocked, unpinned row."""
    factory = _factory_with_active_release(postgres_engine)
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ):
        with pytest.raises(SessionNotFoundError):
            manager.create_chat_request("absent", "polling@example.com")

    with factory() as db:
        assert db.scalar(select(UserSession).where(UserSession.session_id == "absent")) is None
        assert db.scalar(select(ChatRequest)) is None


def test_tour_spells_true_and_persists_the_active_pin(postgres_engine):
    """The tour is not excluded: it is an agent (graph) deck.

    It is created with Deck Mode ``agent``, so the resolver sends the tour deck
    to the graph; an unpinned tour root would fail its first chat turn with
    ConversationPinMissingError.  It must spell True (not lean on a default)
    and persist the exact active release.
    """
    factory = _factory_with_active_release(postgres_engine)
    recorder = _RecordingManager(SessionManager())
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.routes.tour.get_session_manager", return_value=recorder
    ):
        result = _phase1_create_session("tour@example.com")

    assert recorder.create_kwargs[0]["graph_capable"] is True
    assert recorder.create_kwargs[0].get("deck_mode") == "agent"
    with factory() as db:
        active_id = db.scalar(
            select(GraphRelease.id).where(GraphRelease.effective_to.is_(None))
        )
    assert _pin(factory, result["session_id"]) == active_id
    # The pin and the engine agree: the stored mode selects the graph.
    assert _deck_mode(factory, result["session_id"]) == "agent"


@pytest.mark.asyncio
async def test_mcp_spells_false_and_persists_a_null_pin(postgres_engine):
    """Omitting the MCP exclusion makes a later default change silently pin tool decks.

    MCP is still excluded: it stays on the monolith, so it creates its deck
    with Deck Mode ``legacy``, stored at creation, which agrees with the null
    pin.  (Its first message is persisted verbatim: see
    tests/unit/test_mcp_server.py.)
    """
    factory = _factory_with_active_release(postgres_engine)
    recorder = _RecordingManager(SessionManager())

    @contextlib.contextmanager
    def auth_scope(_request):
        yield SimpleNamespace(user_name="mcp@example.com", source="test-token")

    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch.object(
        mcp_server, "get_session_manager", return_value=recorder
    ), patch.object(
        mcp_server, "mcp_auth_scope", auth_scope
    ), patch.object(
        mcp_server, "get_default_design_system_id", return_value=None
    ), patch.object(
        mcp_server, "get_default_slide_style_id", return_value=None
    ), patch.object(
        mcp_server, "enqueue_create_job", new_callable=AsyncMock, return_value="req-1"
    ), patch(
        "src.api.services.session_manager.lock_active_graph_release",
        side_effect=_lock_tripwire,
    ):
        result = await mcp_server._create_deck_impl(
            request=SimpleNamespace(),
            prompt="make a non-graph deck",
        )

    assert recorder.create_kwargs[0]["graph_capable"] is False
    assert recorder.create_kwargs[0].get("deck_mode") == "legacy"
    assert _pin(factory, result["session_id"]) is None
    assert _deck_mode(factory, result["session_id"]) == "legacy"

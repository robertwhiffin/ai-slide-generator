"""Real-PostgreSQL linearization for every graph-capable creator."""

from __future__ import annotations

import contextlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from src.api.routes.chat import _maybe_create_session
from src.api.schemas.requests import ChatRequest
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, SessionSlideDeck, UserSession
from src.domain.conversation_engine import AGENT_MODE_PHRASE
from tests.integration.postgres_concurrency_helpers import _WAIT_SECONDS, _await_lock_waiters

pytestmark = pytest.mark.postgres

CREATORS = (
    "explicit-root",
    "chat-generated-id",
    "chat-supplied-id",
    "chat-service-sync",
    "chat-service-streaming",
    "contributor",
    "duplicate",
)


class _StopAfterCreation(RuntimeError):
    pass


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


def _release(version, *, active=True, previous_release_id=None):
    now = datetime.now(timezone.utc)
    return GraphRelease(
        version_number=version,
        previous_release_id=previous_release_id,
        release_note=f"creator ordering R{version}",
        published_by="ordering@example.com",
        published_at=now,
        effective_from=now,
        effective_to=None if active else now + timedelta(seconds=1),
    )


def _seed(factory, creator):
    with factory.begin() as db:
        r1 = _release(1)
        db.add(r1)
        db.flush()
        source_id = None
        if creator in {"contributor", "duplicate"}:
            source = UserSession(
                session_id=f"{creator}-source",
                created_by="owner@example.com",
                title="R1 source",
                graph_release_id=r1.id,
            )
            db.add(source)
            db.flush()
            source_id = source.session_id
            if creator == "duplicate":
                db.add(
                    SessionSlideDeck(
                        session_id=source.id,
                        title="R1 source",
                        html_content="<div>R1</div>",
                        slide_count=1,
                        deck_json='{"slides":[{"html":"<div>R1</div>"}]}',
                    )
                )
                db.add(
                    SessionMessage(
                        session_id=source.id,
                        role="user",
                        content=f"{AGENT_MODE_PHRASE} duplicate",
                    )
                )
        return r1.id, source_id


def _await_specific_lock_waiter(engine, pid):
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            waiting = observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid = :pid "
                    "AND wait_event_type = 'Lock')"
                ),
                {"pid": pid},
            )
        if waiting:
            return True
        time.sleep(0.02)
    return False


def _backend_pid(conn):
    return conn.connection.driver_connection.get_backend_pid()


def _create(factory, creator):
    manager = SessionManager()
    marker = f"{AGENT_MODE_PHRASE} build a deck"
    if creator == "explicit-root":
        return manager.create_session(
            session_id="explicit-root-actor",
            created_by="actor@example.com",
            graph_capable=True,
        )["session_id"]
    if creator in {"chat-generated-id", "chat-supplied-id"}:
        request = ChatRequest(
            session_id="chat-supplied-actor" if creator == "chat-supplied-id" else None,
            message=marker,
        )
        assert _maybe_create_session(request, manager) is True
        return request.session_id
    if creator in {"chat-service-sync", "chat-service-streaming"}:
        session_id = f"{creator}-actor"
        service = ChatService.__new__(ChatService)
        service._detect_edit_intent = MagicMock(side_effect=_StopAfterCreation)
        try:
            if creator == "chat-service-sync":
                service.send_message(session_id, marker)
            else:
                next(
                    service.send_message_streaming(
                        session_id,
                        marker,
                        request_id="already-persisted",
                    )
                )
        except _StopAfterCreation:
            pass
        return session_id
    if creator == "contributor":
        return manager.get_or_create_contributor_session(
            "contributor-source", "actor@example.com"
        )["session_id"]
    if creator == "duplicate":
        return manager.duplicate_session(
            "duplicate-source", "actor@example.com"
        )["session_id"]
    raise AssertionError(creator)


@contextlib.contextmanager
def _creator_patches(factory):
    manager = SessionManager()
    with patch(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    ), patch(
        "src.api.routes.chat.get_current_user", return_value="actor@example.com"
    ), patch(
        "src.api.routes.chat.get_default_design_system_id", return_value=None
    ), patch(
        "src.api.routes.chat.get_default_slide_style_id", return_value=None
    ), patch(
        "src.api.services.chat_service.get_session_manager", return_value=manager
    ), patch(
        "src.core.settings_db.get_settings", return_value=MagicMock()
    ):
        yield


def _publish_r2(factory, r1_id, locked, proceed, pids):
    threading.current_thread().name = "publisher"
    with factory.begin() as db:
        pids["publisher"] = db.scalar(text("SELECT pg_backend_pid()"))
        r1 = db.scalar(select(GraphRelease).where(GraphRelease.id == r1_id).with_for_update())
        locked.set()
        assert proceed.wait(timeout=20), "publisher was never released"
        closed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        r1.effective_to = closed_at
        r2 = _release(2, previous_release_id=r1_id)
        r2.effective_from = closed_at
        r2.published_at = closed_at
        db.add(r2)
        db.flush()
        return r2.id


def _assert_final(factory, creator, actor_id, expected_actor_pin, r1_id, r2_id):
    with factory() as db:
        actor = db.scalar(select(UserSession).where(UserSession.session_id == actor_id))
        r1 = db.get(GraphRelease, r1_id)
        r2 = db.get(GraphRelease, r2_id)
        active = db.scalar(select(GraphRelease).where(GraphRelease.effective_to.is_(None)))
        assert actor is not None
        assert actor.graph_release_id == expected_actor_pin
        assert (r1.version_number, r2.version_number, active.id) == (1, 2, r2_id)
        if creator in {"contributor", "duplicate"}:
            source = db.scalar(
                select(UserSession).where(UserSession.session_id == f"{creator}-source")
            )
            assert source.graph_release_id == r1_id
            assert source.id != actor.id
            if creator == "contributor":
                assert actor.parent_session_id == source.id
            else:
                assert actor.parent_session_id is None
                copied = db.scalar(
                    select(SessionMessage).where(SessionMessage.session_id == actor.id)
                )
                assert copied.content == f"{AGENT_MODE_PHRASE} duplicate"


@pytest.mark.parametrize("creator", CREATORS)
def test_publication_first_retries_each_creator_to_exact_r2(postgres_engine, creator):
    """A creator arriving behind R1 publication must scan twice and pin exact R2."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    r1_id, _source_id = _seed(factory, creator)
    publisher_locked = threading.Event()
    release_publisher = threading.Event()
    pids = {}
    scans = []

    @event.listens_for(postgres_engine, "before_cursor_execute")
    def observe_creator(conn, _cursor, statement, _params, _ctx, _many):
        if (
            threading.current_thread().name == "creator"
            and "FROM graph_release" in statement
            and "FOR UPDATE" in statement
        ):
            pids["creator"] = _backend_pid(conn)
            scans.append(1)

    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            publisher = pool.submit(
                _publish_r2,
                factory,
                r1_id,
                publisher_locked,
                release_publisher,
                pids,
            )
            assert publisher_locked.wait(timeout=10), "publisher did not lock R1"

            def create():
                threading.current_thread().name = "creator"
                return _create(factory, creator)

            created = pool.submit(create)
            deadline = time.monotonic() + 10
            while "creator" not in pids and time.monotonic() < deadline:
                time.sleep(0.02)
            assert _await_specific_lock_waiter(postgres_engine, pids["creator"])
            assert _await_lock_waiters(postgres_engine, 1) >= 1
            assert pids["creator"] != pids["publisher"]
            release_publisher.set()
            r2_id = publisher.result(timeout=20)
            actor_id = created.result(timeout=20)
    finally:
        event.remove(postgres_engine, "before_cursor_execute", observe_creator)

    assert scans == [1, 1]
    assert r2_id != r1_id
    _assert_final(factory, creator, actor_id, r2_id, r1_id, r2_id)


@pytest.mark.parametrize("creator", CREATORS)
def test_creation_first_holds_r1_until_each_creator_flushes(postgres_engine, creator):
    """A publisher must wait until the newly flushed R1 actor commits."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    r1_id, _source_id = _seed(factory, creator)
    actor_flushed = threading.Event()
    allow_creator = threading.Event()
    publisher_locked = threading.Event()
    release_publisher = threading.Event()
    pids = {}
    paused = {"done": False}

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def pause_after_actor_insert(conn, _cursor, statement, _params, _ctx, _many):
        if (
            threading.current_thread().name == "creator"
            and statement.lstrip().startswith("INSERT INTO user_sessions")
            and not paused["done"]
        ):
            paused["done"] = True
            pids["creator"] = _backend_pid(conn)
            actor_flushed.set()
            assert allow_creator.wait(timeout=20), "creator was never released"

    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            def create():
                threading.current_thread().name = "creator"
                return _create(factory, creator)

            created = pool.submit(create)
            assert actor_flushed.wait(timeout=10), "creator did not flush its actor"
            publisher = pool.submit(
                _publish_r2,
                factory,
                r1_id,
                publisher_locked,
                release_publisher,
                pids,
            )
            # The publisher records its PID before SELECT FOR UPDATE, then
            # cannot set publisher_locked until the creator commits R1.
            deadline = time.monotonic() + 10
            while "publisher" not in pids and time.monotonic() < deadline:
                time.sleep(0.02)
            assert _await_specific_lock_waiter(postgres_engine, pids["publisher"])
            assert _await_lock_waiters(postgres_engine, 1) >= 1
            assert pids["creator"] != pids["publisher"]
            allow_creator.set()
            actor_id = created.result(timeout=20)
            assert publisher_locked.wait(timeout=10)
            release_publisher.set()
            r2_id = publisher.result(timeout=20)
    finally:
        event.remove(postgres_engine, "after_cursor_execute", pause_after_actor_insert)

    assert r1_id != r2_id
    _assert_final(factory, creator, actor_id, r1_id, r1_id, r2_id)

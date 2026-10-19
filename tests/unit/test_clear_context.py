"""`clear_context` (ws4d D1 / spec §7.2): the service, and the route's CAN_EDIT gate.

Real sqlite for the service half — the defect this code exists to prevent (a
clear that takes the engine-mode marker with it, silently switching the deck's
engine on the next turn; since 2026-10-12 the marker is the LEGACY opt-out, so
a lost marker moves a legacy deck onto the graph) is invisible to a mock, and so is the one that
keeps the spec's row but loses the graph thread.  Every assertion reads rows
back, and mode is re-derived through `resolve_engine_mode` rather than asserted
on a string.

Patch targets: `clear_context` imports `get_db_session` and `get_checkpointer`
lazily inside the method (importing `src.core.checkpointer` at module scope
would pull langgraph into the unit suite's collection chain), so the reachable
targets are the source attributes `src.core.database.get_db_session` and
`src.core.checkpointer.get_checkpointer`.

One transaction (#323).  The clear's transcript prune, its ``usage_events``
attribution row and the graph thread delete commit or roll back together.  The
in-memory engine cannot show that: it hands every session in a thread the SAME
connection, so a second transaction is invisible.  The tests that prove it use
a FILE-BACKED engine with ordinary pooling and the REAL
``SqlAlchemyCheckpointSaver``, where a delete on a second connection blocks on
SQLite's write lock (``database is locked``) — and, in CI, a real PostgreSQL
with a ``do_connect`` listener counting the connections the engine issues.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from src.api.services.chat_service import (
    LEGACY_MODE_PHRASE,
    ChatService,
    resolve_engine_mode,
)
from src.api.services.deck_level_writer import read_deck_spec
from src.api.services.session_manager import SessionNotFoundError
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.core.database import Base, _run_migrations
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import SessionMessage, SessionSlideDeck, UserSession
from src.database.models.usage_event import UsageEvent
from tests.unit.conftest import _make_factory, _make_fake_db

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_CHECKPOINTER = "src.core.checkpointer.get_checkpointer"

_PHRASE_MESSAGE = f"{LEGACY_MODE_PHRASE} and build me a deck about puffins"
_PLAIN_MESSAGE = "Build me a deck about puffins"

# The value stored in ``usage_events.event_type`` for a clear (plan D5:
# ``EVENT_CONTEXT_CLEARED = "context_cleared"``).  Rows are read back by this
# stored string, the way admin analytics reads them, so a constant with another
# value fails here too.
_CONTEXT_CLEARED = "context_cleared"

_CHECKPOINT_TABLES = ("graph_checkpoints", "graph_checkpoint_writes")


class _RecordingSaver:
    """Stands in for SqlAlchemyCheckpointSaver, recording every delete_thread.

    ``sessions`` records the ``session=`` each call received: the clear must
    hand the saver its own transaction's session, never leave it to open one.
    """

    def __init__(self, raises: BaseException | None = None):
        self.deleted: list[str] = []
        self.sessions: list[Any] = []
        self._raises = raises

    def delete_thread(self, thread_id: str, *, session: Any = None) -> None:
        self.deleted.append(thread_id)
        self.sessions.append(session)
        if self._raises is not None:
            raise self._raises


@contextlib.contextmanager
def _patched(factory, saver):
    """Point clear_context's DB and checkpointer at the test's own objects."""
    fake = _make_fake_db(factory)
    with patch(_DB_SOURCE, fake), patch(_MANAGER_DB, fake), patch(_WRITER_DB, fake), \
            patch(_CHECKPOINTER, lambda: saver):
        yield


def _add_message(factory, session_id: str, *, role: str, content: str,
                 message_type=None, offset_seconds: int = 0) -> None:
    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        db.add(
            SessionMessage(
                session_id=us.id,
                role=role,
                content=content,
                message_type=message_type,
                created_at=datetime.utcnow() + timedelta(seconds=offset_seconds),
            )
        )
        db.commit()
    finally:
        db.close()


def _messages_of(factory, session_id: str):
    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        rows = (
            db.query(SessionMessage)
            .filter(SessionMessage.session_id == us.id)
            .order_by(SessionMessage.created_at, SessionMessage.id)
            .all()
        )
        for r in rows:
            db.expunge(r)
        return rows
    finally:
        db.close()


def _deck_spec_column(factory, session_id: str):
    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        deck = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == us.id)
            .one()
        )
        return deck.deck_spec_json
    finally:
        db.close()


def _session_pk(factory, session_id: str) -> int:
    db = factory()
    try:
        return (
            db.query(UserSession).filter(UserSession.session_id == session_id).one().id
        )
    finally:
        db.close()


def _clear_events(factory) -> list[tuple[str, int | None]]:
    """Every committed ``context_cleared`` usage event, as (username, session_id)."""
    db = factory()
    try:
        return [
            (e.username, e.session_id)
            for e in db.query(UsageEvent)
            .filter(UsageEvent.event_type == _CONTEXT_CLEARED)
            .order_by(UsageEvent.id)
            .all()
        ]
    finally:
        db.close()


def _failing_commit_db(factory):
    """A ``get_db_session`` whose COMMIT fails.

    The body runs on a real session; on a clean exit the transaction is rolled
    back and ``RuntimeError("commit failed")`` is raised, which is what a lost
    commit looks like to ``clear_context``.  A body that raises is rolled back
    and its exception propagates, as with the real helper.
    """

    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        else:
            db.rollback()
            raise RuntimeError("commit failed")
        finally:
            db.close()

    return fake_get_db_session


@contextlib.contextmanager
def _patched_with_failing_commit(factory, saver):
    """Every get_db_session the clear can reach fails its commit."""
    fake = _failing_commit_db(factory)
    with patch(_DB_SOURCE, fake), patch(_MANAGER_DB, fake), patch(_WRITER_DB, fake), \
            patch(_CHECKPOINTER, lambda: saver):
        yield


# -- checkpoint helpers, copied from tests/unit/test_checkpointer.py ----------


def _config(thread_id: str, checkpoint_id: str | None = None, ns: str = "") -> dict:
    configurable: dict[str, Any] = {"thread_id": thread_id, "checkpoint_ns": ns}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def _checkpoint(channel_values: dict | None = None) -> dict:
    """A fresh checkpoint. ``empty_checkpoint`` mints a monotonic UUID6 id."""
    checkpoint = empty_checkpoint()
    if channel_values is not None:
        checkpoint["channel_values"] = channel_values
    return checkpoint


def _metadata(step: int = 0, **extra: Any) -> dict:
    return {"source": "loop", "step": step, "parents": {}, **extra}


def _count(engine, table_name: str, thread_id: str) -> int:
    """COUNT on a connection of its own: sees only what was COMMITTED."""
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM {table_name} WHERE thread_id = :t"),
            {"t": thread_id},
        ).scalar_one()


def _seed_clearable_session(factory, saver) -> SimpleNamespace:
    """A session with a four-row transcript and a graph thread to delete.

    The thread (keyed by the session id, as ``invoke_graph`` keys it) gets one
    checkpoint and one pending write, written through the REAL saver.  A second
    thread, belonging to some other session, gets the same, so a clear that
    deleted more than its own thread shows up.
    """
    sid = f"clear-{uuid.uuid4().hex[:12]}"
    other_thread = f"other-{uuid.uuid4().hex[:12]}"

    db = factory()
    try:
        db.add(UserSession(session_id=sid, created_by="owner@example.com"))
        db.commit()
    finally:
        db.close()

    _add_message(factory, sid, role="user", content=_PLAIN_MESSAGE,
                 message_type="user_input")
    _add_message(factory, sid, role="assistant", content="deck built",
                 message_type="llm_response", offset_seconds=5)
    _add_message(factory, sid, role="user", content="make slide 3 shorter",
                 message_type="user_input", offset_seconds=10)
    _add_message(factory, sid, role="assistant", content="done",
                 message_type="llm_response", offset_seconds=15)

    for thread_id in (sid, other_thread):
        checkpoint = _checkpoint({"deck_spec": {"title": "Puffins"}})
        saver.put(_config(thread_id), checkpoint, _metadata(), {})
        saver.put_writes(
            _config(thread_id, checkpoint["id"]), [("slides", {2})], "task-1"
        )

    return SimpleNamespace(
        sid=sid,
        pk=_session_pk(factory, sid),
        other_thread=other_thread,
        transcript=[r.content for r in _messages_of(factory, sid)],
    )


def _assert_thread_rows(engine, thread_id: str, expected: int) -> None:
    for table in _CHECKPOINT_TABLES:
        assert _count(engine, table, thread_id) == expected, (table, thread_id)


@pytest.fixture
def file_backed_db(tmp_path):
    """A FILE-BACKED sqlite engine with ordinary pooling and the full schema.

    The defect is two connections contending for SQLite's single write lock;
    the house in-memory engine gives every session in a thread one connection,
    so it can never have two.  ``timeout=2`` makes the old two-transaction
    clear fail in two seconds rather than hang.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'clear.db'}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    try:
        yield engine
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The service: what survives, what goes.
# ---------------------------------------------------------------------------


class TestClearContextKeepsTheMarkerAndDropsTheRest:
    def test_marker_survives_rest_goes_spec_readable_thread_deleted(
        self, session_with_spec_and_messages, _session_unit_engine
    ):
        """All four in one test, because each alone passes with the others broken.

        "Messages were deleted" passes with the marker deleted too; "the marker
        is there" passes with nothing deleted; both pass with the graph thread
        left behind and with the spec wiped.
        """
        sid = session_with_spec_and_messages
        factory = _make_factory(_session_unit_engine)

        # The fixture's single user row IS the earliest one — make it the marker.
        db = factory()
        try:
            us = db.query(UserSession).filter(UserSession.session_id == sid).one()
            row = (
                db.query(SessionMessage)
                .filter(SessionMessage.session_id == us.id)
                .order_by(SessionMessage.created_at)
                .first()
            )
            row.content = _PHRASE_MESSAGE
            row.message_type = "user_query"
            db.commit()
        finally:
            db.close()

        _add_message(factory, sid, role="assistant", content="deck built",
                     message_type="llm_response", offset_seconds=5)
        _add_message(factory, sid, role="user", content="make slide 2 blue",
                     message_type="user_input", offset_seconds=10)
        _add_message(factory, sid, role="assistant", content="done",
                     message_type="llm_response", offset_seconds=15)

        spec_before = _deck_spec_column(factory, sid)
        assert spec_before, "fixture precondition: the deck carries a spec"
        assert len(_messages_of(factory, sid)) == 4

        saver = _RecordingSaver()
        with _patched(factory, saver):
            result = ChatService().clear_context(sid, cleared_by="test-user@example.com")

            # The marker survived, everything else went.
            rows = _messages_of(factory, sid)
            assert [r.content for r in rows] == [_PHRASE_MESSAGE]
            assert rows[0].role == "user"
            assert result["deleted_messages"] == 3
            assert result["preserved_message_id"] == rows[0].id

            # The mode the marker encodes survived with it.
            assert resolve_engine_mode(sid) == "monolith"

            # The spec is still there AND still readable.
            assert _deck_spec_column(factory, sid) == spec_before
            assert read_deck_spec(sid) == json.loads(spec_before)

        # The graph thread was deleted, keyed by the session id invoke_graph
        # runs the thread under.
        assert saver.deleted == [sid]
        # ... on the clear's own session, so it is in the clear's transaction
        # rather than one the saver opens and commits by itself (#323).
        [given] = saver.sessions
        assert given is not None, "delete_thread was not handed the clear's session"
        assert isinstance(given, Session)
        assert given.get_bind() is _session_unit_engine

    def test_a_graph_sessions_first_row_is_preserved_too(
        self, session_with_messages, _session_unit_engine
    ):
        """Clearing never CHANGES the mode — in either direction."""
        sid = session_with_messages(
            [_PLAIN_MESSAGE, "and now a chart"], message_type="user_input"
        )
        factory = _make_factory(_session_unit_engine)

        saver = _RecordingSaver()
        with _patched(factory, saver):
            result = ChatService().clear_context(sid, cleared_by="test-user@example.com")
            assert [r.content for r in _messages_of(factory, sid)] == [_PLAIN_MESSAGE]
            assert result["deleted_messages"] == 1
            assert resolve_engine_mode(sid) == "graph"

    def test_a_session_with_no_messages_clears_cleanly(
        self, empty_session, _session_unit_engine
    ):
        factory = _make_factory(_session_unit_engine)
        saver = _RecordingSaver()
        with _patched(factory, saver):
            result = ChatService().clear_context(
                empty_session, cleared_by="test-user@example.com"
            )
        assert result["deleted_messages"] == 0
        assert result["preserved_message_id"] is None
        assert saver.deleted == [empty_session]

    def test_an_assistant_only_transcript_is_cleared_completely(
        self, session_with_messages, _session_unit_engine
    ):
        """Nothing is preserved when there is no user row to preserve."""
        sid = session_with_messages([], assistant_messages=["hello", "again"])
        factory = _make_factory(_session_unit_engine)
        with _patched(factory, _RecordingSaver()):
            result = ChatService().clear_context(sid, cleared_by="test-user@example.com")
        assert result["deleted_messages"] == 2
        assert _messages_of(factory, sid) == []

    def test_clearing_a_contributor_session_leaves_the_owners_marker(
        self, contributor_session
    ):
        """The deck's mode lives on the owner's transcript, so it is untouched."""
        factory = contributor_session._factory
        owner_sid = contributor_session._owner_session_id
        contrib_sid = contributor_session.contributor_session_id

        _add_message(factory, owner_sid, role="user", content=_PHRASE_MESSAGE,
                     message_type="user_input")
        _add_message(factory, contrib_sid, role="user", content="my own first ask",
                     message_type="user_query", offset_seconds=10)
        _add_message(factory, contrib_sid, role="user", content="and a second",
                     message_type="user_query", offset_seconds=20)

        saver = _RecordingSaver()
        with _patched(factory, saver):
            ChatService().clear_context(contrib_sid, cleared_by="test-user@example.com")
            assert [r.content for r in _messages_of(factory, owner_sid)] == [
                _PHRASE_MESSAGE
            ]
            assert [r.content for r in _messages_of(factory, contrib_sid)] == [
                "my own first ask"
            ]
            assert resolve_engine_mode(contrib_sid) == "monolith"
        assert saver.deleted == [contrib_sid]

    def test_an_unimplemented_saver_rolls_the_prune_back(
        self, session_with_messages, _session_unit_engine
    ):
        """BaseCheckpointSaver.delete_thread is `raise NotImplementedError`.

        It must surface (the route turns it into a 500) rather than skip quietly,
        and a raise must not leave a half-cleared session behind: the thread
        delete runs inside the clear's one transaction, so the transcript prune
        rolls back with it.

        The reverse direction — the clear's commit failing AFTER the saver
        returned — holds too since #323, because ``delete_thread`` now runs on
        the clear's own session and commits nothing itself.  That one needs a
        real saver on a file-backed database to observe:
        ``test_a_failed_commit_rolls_back_the_thread_delete_too``.
        """
        sid = session_with_messages(
            [_PHRASE_MESSAGE, "turn two", "turn three"], message_type="user_input"
        )
        factory = _make_factory(_session_unit_engine)
        before = [r.content for r in _messages_of(factory, sid)]
        assert len(before) == 3

        saver = _RecordingSaver(raises=NotImplementedError())
        with _patched(factory, saver):
            with pytest.raises(NotImplementedError):
                ChatService().clear_context(sid, cleared_by="test-user@example.com")

        assert [r.content for r in _messages_of(factory, sid)] == before

    def test_unknown_session_raises_session_not_found(self, _session_unit_engine):
        factory = _make_factory(_session_unit_engine)
        saver = _RecordingSaver()
        with _patched(factory, saver):
            with pytest.raises(SessionNotFoundError):
                ChatService().clear_context(
                    "no-such-session", cleared_by="test-user@example.com"
                )
        assert saver.deleted == []


# ---------------------------------------------------------------------------
# Attribution (#323, D5): one usage_events row per committed clear.
# ---------------------------------------------------------------------------


class TestTheClearIsAttributed:
    def test_a_clear_records_who_cleared_it_in_the_same_transaction(
        self, session_with_messages, _session_unit_engine
    ):
        """One ``context_cleared`` row naming the actor and the cleared session.

        Two sessions, and the SECOND is cleared, so the row's ``session_id`` has
        to be the cleared session's own integer id, not merely the first one.
        The "same transaction" half — no row when the clear does not commit — is
        ``test_a_rolled_back_clear_records_no_attribution`` and the file-backed
        ``test_a_failed_commit_rolls_back_the_thread_delete_too``.
        """
        factory = _make_factory(_session_unit_engine)
        bystander = session_with_messages([_PLAIN_MESSAGE], message_type="user_input")
        sid = session_with_messages(
            [_PLAIN_MESSAGE, "and now a chart"], message_type="user_input"
        )
        pk = _session_pk(factory, sid)
        assert pk != _session_pk(factory, bystander), "fixture precondition"
        assert _clear_events(factory) == []

        with _patched(factory, _RecordingSaver()):
            ChatService().clear_context(sid, cleared_by="owner@example.com")

        assert _clear_events(factory) == [("owner@example.com", pk)]

    @pytest.mark.parametrize("actor", [None, ""])
    def test_a_clear_without_an_actor_is_refused_before_anything_changes(
        self, actor, session_with_messages, _session_unit_engine
    ):
        """An unattributable clear must not happen at all."""
        factory = _make_factory(_session_unit_engine)
        sid = session_with_messages(
            [_PHRASE_MESSAGE, "turn two", "turn three"], message_type="user_input"
        )
        before = [(r.id, r.content, r.message_type) for r in _messages_of(factory, sid)]
        assert len(before) == 3

        saver = _RecordingSaver()
        with _patched(factory, saver):
            with pytest.raises(ValueError):
                ChatService().clear_context(sid, cleared_by=actor)

        assert [
            (r.id, r.content, r.message_type) for r in _messages_of(factory, sid)
        ] == before
        assert saver.deleted == []
        assert _clear_events(factory) == []

    def test_a_rolled_back_clear_records_no_attribution(
        self, session_with_messages, _session_unit_engine
    ):
        """The row exists if and only if the clear committed."""
        factory = _make_factory(_session_unit_engine)
        sid = session_with_messages(
            [_PHRASE_MESSAGE, "turn two", "turn three"], message_type="user_input"
        )
        before = [r.content for r in _messages_of(factory, sid)]

        saver = _RecordingSaver(raises=NotImplementedError())
        with _patched(factory, saver):
            with pytest.raises(NotImplementedError):
                ChatService().clear_context(sid, cleared_by="owner@example.com")

        assert saver.deleted == [sid], "precondition: the clear reached the saver"
        assert [r.content for r in _messages_of(factory, sid)] == before
        assert _clear_events(factory) == []


# ---------------------------------------------------------------------------
# One transaction (#323, D2): a REAL saver on a FILE-BACKED database.
# ---------------------------------------------------------------------------


class TestTheClearIsOneTransaction:
    def test_clear_with_the_real_saver_on_a_file_backed_database_is_one_transaction(
        self, file_backed_db
    ):
        """Before #323 this raised ``OperationalError: database is locked``.

        The bulk DELETE holds SQLite's write lock on the clear's connection
        while the saver's own second connection waits for it.  With the thread
        delete on the clear's session, everything commits together.
        """
        factory = _make_factory(file_backed_db)
        saver = SqlAlchemyCheckpointSaver(session_factory=factory)
        seeded = _seed_clearable_session(factory, saver)
        _assert_thread_rows(file_backed_db, seeded.sid, 1)

        with _patched(factory, saver):
            result = ChatService().clear_context(seeded.sid, cleared_by="owner@example.com")

        assert [r.content for r in _messages_of(factory, seeded.sid)] == [_PLAIN_MESSAGE]
        assert result["deleted_messages"] == 3
        _assert_thread_rows(file_backed_db, seeded.sid, 0)
        assert saver.get_tuple(_config(seeded.sid)) is None
        _assert_thread_rows(file_backed_db, seeded.other_thread, 1)
        assert _clear_events(factory) == [("owner@example.com", seeded.pk)]

    def test_a_failed_commit_rolls_back_the_thread_delete_too(self, file_backed_db):
        """A lost commit leaves the transcript, the thread AND the attribution.

        Before #323 the saver committed the thread delete on its own, so this
        state — thread gone, transcript intact — was the documented half-state.
        """
        factory = _make_factory(file_backed_db)
        saver = SqlAlchemyCheckpointSaver(session_factory=factory)
        seeded = _seed_clearable_session(factory, saver)
        assert len(seeded.transcript) == 4

        with _patched_with_failing_commit(factory, saver):
            with pytest.raises(RuntimeError, match="commit failed"):
                ChatService().clear_context(seeded.sid, cleared_by="owner@example.com")

        assert [r.content for r in _messages_of(factory, seeded.sid)] == seeded.transcript
        _assert_thread_rows(file_backed_db, seeded.sid, 1)
        assert saver.get_tuple(_config(seeded.sid)) is not None
        assert _clear_events(factory) == []

        # A retry is an ordinary clear, and it clears both.
        with _patched(factory, saver):
            ChatService().clear_context(seeded.sid, cleared_by="owner@example.com")

        assert [r.content for r in _messages_of(factory, seeded.sid)] == [_PLAIN_MESSAGE]
        _assert_thread_rows(file_backed_db, seeded.sid, 0)
        _assert_thread_rows(file_backed_db, seeded.other_thread, 1)
        assert _clear_events(factory) == [("owner@example.com", seeded.pk)]


# ---------------------------------------------------------------------------
# The route: DELETE /api/sessions/{session_id}/context, gated on CAN_EDIT.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def deck_gate(monkeypatch):
    """Records (session_id, min_permission) and refuses, like a viewer's call."""
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.sessions._check_deck_permission_for_session", gate
    )
    return calls


@pytest.fixture
def allowing_gate(monkeypatch):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))

    monkeypatch.setattr(
        "src.api.routes.sessions._check_deck_permission_for_session", gate
    )
    return calls


@pytest.fixture
def as_editor(monkeypatch):
    """Authenticate requests as ``editor@example.com``.

    The real middleware reads ``DEV_USER_ID`` on every request when no token
    header is sent (``src/api/main.py``), so the identity the route forwards as
    ``cleared_by`` comes from the request, not from anything the test patches.
    """
    monkeypatch.setenv("DEV_USER_ID", "editor@example.com")


@pytest.fixture
def stub_service(monkeypatch):
    """Replaces ChatService for the route tests; records (session_id, cleared_by)."""
    calls = []

    class _Stub:
        def clear_context(self, session_id, *, cleared_by):
            calls.append((session_id, cleared_by))
            return {
                "status": "cleared",
                "session_id": session_id,
                "deleted_messages": 2,
                "preserved_message_id": 7,
            }

    monkeypatch.setattr("src.api.routes.sessions.get_chat_service", lambda: _Stub())
    return calls


class TestClearContextRoute:
    def test_the_route_is_delete_on_the_context_path(self):
        from src.api.main import app

        matches = {
            (r.path, frozenset(r.methods))
            for r in app.routes
            if getattr(r, "path", "") == "/api/sessions/{session_id}/context"
        }
        assert matches == {("/api/sessions/{session_id}/context",
                           frozenset({"DELETE"}))}

    def test_a_viewer_is_refused_and_nothing_is_cleared(
        self, client, deck_gate, stub_service
    ):
        """The gate's DEFAULT is CAN_VIEW: taking it would let a viewer wipe
        another user's transcript and graph thread."""
        resp = client.delete("/api/sessions/s1/context")

        assert resp.status_code == 403
        assert deck_gate == [("s1", PermissionLevel.CAN_EDIT)]
        assert stub_service == [], "the gate must run BEFORE any clearing"

    def test_the_refusal_is_an_httpexception_not_a_permissionerror(
        self, deck_gate, stub_service
    ):
        """`_check_deck_permission_for_session` raises HTTPException; a handler
        that caught it and re-raised something else would 500 instead of 403."""
        from src.api.routes.sessions import clear_session_context

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(clear_session_context("s1"))

        assert excinfo.value.status_code == 403
        assert stub_service == []

    def test_the_happy_path_returns_the_services_result(
        self, client, allowing_gate, stub_service, as_editor
    ):
        resp = client.delete("/api/sessions/s1/context")

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "cleared",
            "session_id": "s1",
            "deleted_messages": 2,
            "preserved_message_id": 7,
        }
        assert allowing_gate == [("s1", PermissionLevel.CAN_EDIT)]
        # The caller is passed as the actor (#323, D5).
        assert stub_service == [("s1", "editor@example.com")]

    def test_a_missing_session_is_a_404(
        self, client, allowing_gate, monkeypatch, as_editor
    ):
        """The stub records the call, so the 404 cannot come from a signature
        mismatch (a TypeError would be a 500, and would record nothing)."""
        calls = []

        class _Missing:
            def clear_context(self, session_id, *, cleared_by):
                calls.append((session_id, cleared_by))
                raise SessionNotFoundError(f"Session not found: {session_id}")

        monkeypatch.setattr(
            "src.api.routes.sessions.get_chat_service", lambda: _Missing()
        )

        resp = client.delete("/api/sessions/ghost/context")
        assert resp.status_code == 404
        assert calls == [("ghost", "editor@example.com")]

    def test_an_unimplemented_saver_surfaces_as_a_500(
        self, client, allowing_gate, monkeypatch, as_editor
    ):
        """The stub records the call: a TypeError from a signature mismatch is
        also a 500, so the status alone would pass while testing nothing."""
        calls = []

        class _Unimplemented:
            def clear_context(self, session_id, *, cleared_by):
                calls.append((session_id, cleared_by))
                raise NotImplementedError

        monkeypatch.setattr(
            "src.api.routes.sessions.get_chat_service", lambda: _Unimplemented()
        )

        resp = client.delete("/api/sessions/s1/context")
        assert resp.status_code == 500
        assert calls == [("s1", "editor@example.com")]


# ---------------------------------------------------------------------------
# The clear against a REAL PostgreSQL (#323, review F11).
#
# On Postgres the old two-transaction clear did not deadlock (the two DELETEs
# touch different tables); it just was not atomic.  What this half can observe
# that SQLite cannot is the CONNECTION: with a NullPool engine every session
# checkout issues a new DBAPI connection through the do_connect listener, so a
# delete_thread that opened its own session would show up as one more entry in
# ``issued``.  Self-skips when no PostgreSQL is reachable; CI's unit-tests job
# provisions one and exports TELLR_TEST_POSTGRES_URL.  Pattern and helpers
# copied from tests/unit/test_checkpointer.py.
# ---------------------------------------------------------------------------

_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


class _ConnectionCountingSaver(SqlAlchemyCheckpointSaver):
    """The real saver, recording ``len(issued)`` before and after each delete."""

    def __init__(self, issued: list, **kwargs: Any):
        super().__init__(**kwargs)
        self._issued = issued
        self.issued_across_delete: list[tuple[int, int]] = []

    def delete_thread(self, thread_id: str, *, session: Any = None) -> None:
        before = len(self._issued)
        super().delete_thread(thread_id, session=session)
        self.issued_across_delete.append((before, len(self._issued)))


@pytest.mark.postgres
class TestTheClearAgainstRealPostgres:
    @pytest.fixture()
    def pg(self):
        """A throwaway PostgreSQL database with the full schema, plus the
        connections its engine issued (NullPool: one per checkout)."""
        if not _postgres_available():  # pragma: no cover - environment-dependent
            pytest.skip(
                f"no PostgreSQL reachable at {_ADMIN_URL}; set "
                "TELLR_TEST_POSTGRES_URL to run the clear's Postgres half"
            )

        db_name = f"tellr_clear_{uuid.uuid4().hex[:16]}"
        admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        engine = create_engine(
            make_url(_ADMIN_URL).set(database=db_name), poolclass=NullPool
        )
        issued: list[dict] = []

        @event.listens_for(engine, "do_connect")
        def record_connect(dialect, conn_rec, cargs, cparams):
            # Stands in for src.core.database.provide_token; returning None lets
            # the normal connect proceed.
            issued.append(cparams)
            return None

        try:
            Base.metadata.create_all(bind=engine)
            _run_migrations(engine)
            issued.clear()
            yield engine, issued
        finally:
            engine.dispose()
            with admin.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :db AND pid <> pg_backend_pid()"
                    ),
                    {"db": db_name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            admin.dispose()

    def test_the_clear_is_one_transaction_on_postgres(self, pg):
        engine, issued = pg
        factory = _make_factory(engine)
        saver = _ConnectionCountingSaver(issued, session_factory=factory)
        seeded = _seed_clearable_session(factory, saver)
        _assert_thread_rows(engine, seeded.sid, 1)

        with _patched(factory, saver):
            ChatService().clear_context(seeded.sid, cleared_by="owner@example.com")

        assert [r.content for r in _messages_of(factory, seeded.sid)] == [_PLAIN_MESSAGE]
        _assert_thread_rows(engine, seeded.sid, 0)
        _assert_thread_rows(engine, seeded.other_thread, 1)
        assert _clear_events(factory) == [("owner@example.com", seeded.pk)]

        # No new DBAPI connection between the clear's checkout and its commit:
        # the thread delete ran on the clear's own connection.
        [(before, after)] = saver.issued_across_delete
        assert after == before, (
            f"delete_thread checked out {after - before} connection(s) of its own"
        )

    def test_a_failed_commit_on_postgres_leaves_everything(self, pg):
        engine, issued = pg
        factory = _make_factory(engine)
        saver = _ConnectionCountingSaver(issued, session_factory=factory)
        seeded = _seed_clearable_session(factory, saver)

        with _patched_with_failing_commit(factory, saver):
            with pytest.raises(RuntimeError, match="commit failed"):
                ChatService().clear_context(seeded.sid, cleared_by="owner@example.com")

        assert saver.issued_across_delete, "precondition: the clear reached the saver"
        assert [r.content for r in _messages_of(factory, seeded.sid)] == seeded.transcript
        _assert_thread_rows(engine, seeded.sid, 1)
        _assert_thread_rows(engine, seeded.other_thread, 1)
        assert _clear_events(factory) == []

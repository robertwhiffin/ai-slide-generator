"""`clear_context` (ws4d D1 / spec §7.2): the service, and the route's gates and lock.

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

The kept row is hidden (#323, D1).  ``clear_context`` keeps the earliest user
row because engine mode is read off it, and re-types it to
``ENGINE_MODE_MARKER_MESSAGE_TYPE``.  Every transcript read -- the chat panel's
``get_messages``, the architect's ``conversation``, the monolith's history, a
save point's ``chat_history`` -- must then see an empty conversation, while
every mode read still sees the row.  Those tests seed the transcript with the
types the live paths write (``user_input`` / ``llm_response``): with the
fixtures' default ``None`` type the architect's and the monolith's own type
filters would already drop the row, and the tests would pass before the fix.
The new constant does not exist until the fix lands, so it is imported inside
the tests, AFTER the behavioural assertion each test is about.
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
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
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
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.core.database import Base, _run_migrations
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import (
    SessionMessage,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)
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
# The kept row is hidden from every transcript read (#323, D1 / D9).
# ---------------------------------------------------------------------------

# The transcript every test below starts from, as (role, content, message_type)
# in order: the types the live sync/streaming path writes, so the architect's
# and the monolith's own type filters ADMIT every row (see the module docstring).
_ORIGINAL_TRANSCRIPT = [
    ("user", _PLAIN_MESSAGE, "user_input"),
    ("assistant", "deck built", "llm_response"),
    ("user", "make slide 3 shorter", "user_input"),
    ("assistant", "done", "llm_response"),
]

# What the user says after the clear.  Distinct from every original row, so a
# replayed old row can never be mistaken for a new one.
_NEW_ASK = "Now make slide 2 blue"
_NEW_REPLY = "Slide 2 is blue now."


def _marker_type() -> str:
    """``ENGINE_MODE_MARKER_MESSAGE_TYPE``, imported only when a test needs it.

    The constant is new in #323; importing it at module scope would stop this
    whole file collecting before the fix lands.
    """
    from src.domain.conversation_engine import ENGINE_MODE_MARKER_MESSAGE_TYPE

    return ENGINE_MODE_MARKER_MESSAGE_TYPE


def _seed_transcript(factory, sid: str | None = None, *, first: str = _PLAIN_MESSAGE) -> str:
    """Give a session ``_ORIGINAL_TRANSCRIPT`` (its first row's content = *first*).

    With *sid*, the session's existing single user row (the
    ``session_with_spec_and_messages`` fixture's) becomes the first row; with
    none, a fresh session is created.  Returns the session id.
    """
    (_, _, first_type), *rest = _ORIGINAL_TRANSCRIPT
    if sid is None:
        sid = f"clear-{uuid.uuid4().hex[:12]}"
        db = factory()
        try:
            db.add(UserSession(session_id=sid, created_by="owner@example.com"))
            db.commit()
        finally:
            db.close()
        _add_message(factory, sid, role="user", content=first, message_type=first_type)
    else:
        db = factory()
        try:
            us = db.query(UserSession).filter(UserSession.session_id == sid).one()
            [row] = db.query(SessionMessage).filter(SessionMessage.session_id == us.id).all()
            assert row.role == "user", "fixture precondition: one user row"
            row.content = first
            row.message_type = first_type
            db.commit()
        finally:
            db.close()
    for i, (role, content, message_type) in enumerate(rest, start=1):
        _add_message(factory, sid, role=role, content=content,
                     message_type=message_type, offset_seconds=5 * i)
    assert [
        (r.role, r.content, r.message_type) for r in _messages_of(factory, sid)
    ] == [(_ORIGINAL_TRANSCRIPT[0][0], first, first_type), *rest], "seed precondition"
    return sid


def _add_new_ask(factory, sid: str, *, with_reply: bool = False) -> None:
    """What the user (and the assistant) say after the clear."""
    _add_message(factory, sid, role="user", content=_NEW_ASK,
                 message_type="user_input", offset_seconds=30)
    if with_reply:
        _add_message(factory, sid, role="assistant", content=_NEW_REPLY,
                     message_type="llm_response", offset_seconds=35)


def _visible(messages) -> list[tuple[str, str, str | None]]:
    """``get_messages`` dicts as (role, content, message_type)."""
    return [(m["role"], m["content"], m["message_type"]) for m in messages]


def _version_rows(factory, sid: str) -> list[dict]:
    """Every save point on *sid*'s deck, EVERY column, by version number."""
    db = factory()
    try:
        pk = db.query(UserSession).filter(UserSession.session_id == sid).one().id
        return [
            {c.name: getattr(v, c.name) for c in SlideDeckVersion.__table__.columns}
            for v in db.query(SlideDeckVersion)
            .filter(SlideDeckVersion.session_id == pk)
            .order_by(SlideDeckVersion.version_number)
            .all()
        ]
    finally:
        db.close()


class TestAClearedConversationIsEmptyToEveryReader:
    def test_get_messages_returns_nothing_after_a_clear_but_the_marker_row_remains(
        self, _session_unit_engine
    ):
        """The chat panel (on load AND on reload) and ``GET /messages`` read this.

        Before #323 the kept row came back here, so a reload after a clear
        showed the deck's first prompt again.  The row itself must stay: engine
        mode is read off it.
        """
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory)

        with _patched(factory, _RecordingSaver()):
            assert _visible(SessionManager().get_messages(sid)) == _ORIGINAL_TRANSCRIPT, (
                "precondition: get_messages reads this test's database"
            )
            result = ChatService().clear_context(sid, cleared_by="owner@example.com")

            assert SessionManager().get_messages(sid) == []

        [kept] = _messages_of(factory, sid)
        assert kept.id == result["preserved_message_id"]
        assert (kept.role, kept.content) == ("user", _PLAIN_MESSAGE)
        assert kept.message_type == _marker_type()

    def test_messages_written_after_a_clear_are_the_whole_transcript(
        self, _session_unit_engine
    ):
        """The new conversation, exactly, in order; ``limit`` never returns the
        hidden row.

        ``limit=3`` is the window that reaches back over the hidden row (three
        rows exist, two are visible): it must return the two visible rows and
        nothing else.  ``limit=1`` is the newest visible row.  Whether the
        filter runs before or after the slice cannot be told apart here: the
        hidden row is always the session's earliest, so the two orders return
        the same rows (measured).
        """
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory)

        with _patched(factory, _RecordingSaver()):
            ChatService().clear_context(sid, cleared_by="owner@example.com")
            _add_new_ask(factory, sid, with_reply=True)
            assert len(_messages_of(factory, sid)) == 3, "precondition: marker + 2 new rows"

            new_turns = [
                ("user", _NEW_ASK, "user_input"),
                ("assistant", _NEW_REPLY, "llm_response"),
            ]
            assert _visible(SessionManager().get_messages(sid)) == new_turns
            assert _visible(SessionManager().get_messages(sid, limit=3)) == new_turns
            assert _visible(SessionManager().get_messages(sid, limit=1)) == new_turns[1:]

    def test_only_the_marker_is_hidden_every_other_row_type_stays_visible(
        self, session_with_spec_and_messages, _session_unit_engine
    ):
        """The filter hides ONE type and nothing else.

        Untyped rows are real (``POST /sessions/{id}/messages`` writes them;
        older decks carry them), and the agent-internal types are what the
        panel shows as reasoning/tool steps.  A filter that also hid any of
        them would silently drop chat from the panel and from new save points,
        and every other test here would stay green (measured: hiding ``None``
        reddened nothing in tests/unit or the graph/savepoint integration files).
        """
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory, session_with_spec_and_messages)
        after = [
            ("user", "an untyped ask", None),
            ("assistant", "add or replace?", "clarification"),
            ("assistant", "thinking it over", "reasoning"),
            ("tool", "rows from genie", "tool_result"),
            ("assistant", "an advisory", "info"),
        ]

        with _patched(factory, _RecordingSaver()):
            ChatService().clear_context(sid, cleared_by="owner@example.com")
            for i, (role, content, message_type) in enumerate(after):
                _add_message(factory, sid, role=role, content=content,
                             message_type=message_type, offset_seconds=30 + i)

            assert _visible(SessionManager().get_messages(sid)) == after
            SessionManager().create_version(
                sid, "after the clear", deck_dict={"title": "t", "slides": []}
            )

        [version] = _version_rows(factory, sid)
        assert [
            (m["role"], m["content"], m["message_type"])
            for m in json.loads(version["chat_history_json"])
        ] == after

    def test_the_architect_conversation_after_a_clear_is_only_new_turns(
        self, _session_unit_engine
    ):
        """``nodes._conversation`` is the architect payload's ``conversation``.

        Before #323 the deck's first prompt was replayed to the architect as
        conversation after a clear (plan Context 4's probe).
        ``_conversation`` swallows a read failure as ``[]``, so the BEFORE
        assertion is what proves this test reads the seeded rows at all.
        """
        from src.services.graph.nodes import _conversation

        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory)

        with _patched(factory, _RecordingSaver()):
            assert _conversation(sid) == [
                {"role": role, "content": content}
                for role, content, _ in _ORIGINAL_TRANSCRIPT
            ], "precondition: the old first prompt is in the conversation before the clear"

            ChatService().clear_context(sid, cleared_by="owner@example.com")
            _add_new_ask(factory, sid)

            assert _conversation(sid) == [{"role": "user", "content": _NEW_ASK}]

    def test_the_monolith_history_after_a_clear_is_only_new_turns(
        self, _session_unit_engine
    ):
        """``_hydrate_chat_history`` is the monolith agent's history."""
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory)

        def hydrated() -> tuple[int, list[tuple[type, str]]]:
            history = ChatMessageHistory()
            count = ChatService()._hydrate_chat_history(sid, history)
            return count, [(type(m), m.content) for m in history.messages]

        with _patched(factory, _RecordingSaver()):
            assert hydrated() == (4, [
                (HumanMessage if role == "user" else AIMessage, content)
                for role, content, _ in _ORIGINAL_TRANSCRIPT
            ]), "precondition: the whole transcript hydrates before the clear"

            ChatService().clear_context(sid, cleared_by="owner@example.com")
            _add_new_ask(factory, sid)

            assert hydrated() == (1, [(HumanMessage, _NEW_ASK)])

    def test_a_later_legacy_phrase_after_a_clear_does_not_move_a_graph_deck(
        self, _session_unit_engine
    ):
        """The kept row is what stops a later ``USE LEGACY MODE`` becoming the
        deck's earliest user row, and so its engine (plan D1's rejected
        alternative: delete the row on graph decks)."""
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory)

        with _patched(factory, _RecordingSaver()):
            assert resolve_engine_mode(sid) == "graph", "precondition: a graph deck"

            ChatService().clear_context(sid, cleared_by="owner@example.com")
            _add_message(factory, sid, role="user",
                         content=f"{LEGACY_MODE_PHRASE} from now on, please",
                         message_type="user_input", offset_seconds=30)

            assert resolve_engine_mode(sid) == "graph"

    def test_message_count_still_counts_the_marker(self, _session_unit_engine):
        """Deliberately NOT filtered: ``is_first_message = message_count == 0``
        gates title generation, and a cleared deck's next turn is not its first."""
        from src.services.graph_configuration import bootstrap_graph_configuration

        factory = _make_factory(_session_unit_engine)
        bootstrap_graph_configuration(factory)  # get_session projects the pin
        sid = _seed_transcript(factory)

        with _patched(factory, _RecordingSaver()):
            assert SessionManager().get_session(sid)["message_count"] == 4, "precondition"
            ChatService().clear_context(sid, cleared_by="owner@example.com")

            assert SessionManager().get_session(sid)["message_count"] == 1

    def test_clearing_twice_keeps_the_same_marker(self, _session_unit_engine):
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory)

        with _patched(factory, _RecordingSaver()):
            first = ChatService().clear_context(sid, cleared_by="owner@example.com")
            second = ChatService().clear_context(sid, cleared_by="owner@example.com")

            assert first["preserved_message_id"] is not None
            assert second["preserved_message_id"] == first["preserved_message_id"]
            assert (first["deleted_messages"], second["deleted_messages"]) == (3, 0)
            assert SessionManager().get_messages(sid) == []

        [kept] = _messages_of(factory, sid)
        assert (kept.id, kept.role, kept.content) == (
            first["preserved_message_id"], "user", _PLAIN_MESSAGE
        )
        assert kept.message_type == _marker_type()

    def test_a_clear_leaves_every_save_point_untouched(
        self, session_with_spec_and_messages, _session_unit_engine
    ):
        """Each save point keeps the chat it captured (D9): a preview of an
        older save point still shows the old conversation.  Every column of
        every version row is compared, not a chosen few."""
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory, session_with_spec_and_messages)

        with _patched(factory, _RecordingSaver()):
            manager = SessionManager()
            manager.create_version(sid, "v1", deck_dict={"title": "t", "slides": []})
            manager.create_version(sid, "v2", deck_dict={"title": "t", "slides": []})
            before = _version_rows(factory, sid)
            assert [v["version_number"] for v in before] == [1, 2], "precondition"
            for v in before:
                assert v["deck_spec_json"], "precondition: the save point snapshots a spec"
                assert [
                    (m["role"], m["content"], m["message_type"])
                    for m in json.loads(v["chat_history_json"])
                ] == _ORIGINAL_TRANSCRIPT, "precondition: it captured the old chat"

            ChatService().clear_context(sid, cleared_by="owner@example.com")

        assert _version_rows(factory, sid) == before

    def test_a_save_point_taken_after_a_clear_captures_no_marker(
        self, session_with_spec_and_messages, _session_unit_engine
    ):
        """Its preview shows the conversation since the clear, nothing more."""
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory, session_with_spec_and_messages)

        with _patched(factory, _RecordingSaver()):
            ChatService().clear_context(sid, cleared_by="owner@example.com")
            _add_new_ask(factory, sid)
            created = SessionManager().create_version(
                sid, "after the clear", deck_dict={"title": "t", "slides": []}
            )

        [*_, new_row] = _messages_of(factory, sid)
        assert (new_row.role, new_row.content) == ("user", _NEW_ASK), "precondition"
        [version] = _version_rows(factory, sid)
        assert json.loads(version["chat_history_json"]) == [
            {
                "id": new_row.id,
                "role": "user",
                "content": _NEW_ASK,
                "message_type": "user_input",
                "created_at": new_row.created_at.isoformat(),
            }
        ]
        assert created["message_count"] == 1

    def test_a_duplicate_of_a_cleared_legacy_deck_stays_legacy_and_shows_no_chat(
        self, session_with_spec_and_messages, _session_unit_engine
    ):
        """The duplicate carries the marker (role only) WITH its hidden type.

        So the copy keeps the source's engine, and its chat panel is empty, as a
        duplicate's always is.
        """
        factory = _make_factory(_session_unit_engine)
        sid = _seed_transcript(factory, session_with_spec_and_messages, first=_PHRASE_MESSAGE)

        with _patched(factory, _RecordingSaver()):
            assert resolve_engine_mode(sid) == "monolith", "precondition: a legacy deck"
            ChatService().clear_context(sid, cleared_by="owner@example.com")

            new = SessionManager().duplicate_session(sid, "copier@example.com")["session_id"]
            assert new != sid

            assert resolve_engine_mode(new) == "monolith"
            assert SessionManager().get_messages(new) == []

        [carried] = _messages_of(factory, new)
        assert (carried.role, carried.content) == ("user", _PHRASE_MESSAGE)
        assert carried.message_type == _marker_type()


# ---------------------------------------------------------------------------
# The route: DELETE /api/sessions/{session_id}/context (#323, D3/D4/D6).
#
# The checks run in exactly this order: the deck gate (CAN_EDIT, resolved on
# the ROOT deck), the creator gate (only the session's creator may change its
# conversation), the session lock (409 while a turn or a slide operation holds
# it, and a 409 never releases a lock it did not take), the clear, then the
# release.  Every stub below appends to ONE shared ``events`` list, so the
# order is asserted, not inferred from call counts.
#
# ``_require_conversation_creator`` and ``CONVERSATION_BUSY_DETAIL`` do not
# exist before the fix: the creator fixtures patch the route module's name with
# ``raising=False`` (an unpatched route simply never calls them, which the
# tests see as a missing event), and the constant is imported AFTER the
# behavioural assertions, so the rest of the file still collects.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def events():
    """The one ordered log every route stub below appends ``(step, session_id)`` to."""
    return []


@pytest.fixture
def deck_gate(monkeypatch, events):
    """Records (session_id, min_permission) and refuses, like a viewer's call."""
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        events.append(("deck_gate", session_id))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.sessions._check_deck_permission_for_session", gate
    )
    return calls


@pytest.fixture
def allowing_gate(monkeypatch, events):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        events.append(("deck_gate", session_id))

    monkeypatch.setattr(
        "src.api.routes.sessions._check_deck_permission_for_session", gate
    )
    return calls


@pytest.fixture
def allowing_creator(monkeypatch, events):
    """The creator gate, passing.  Records (session_id, the caller it ran as)."""
    calls = []

    def gate(session_id):
        calls.append((session_id, get_current_user()))
        events.append(("creator", session_id))

    monkeypatch.setattr(
        "src.api.routes.sessions._require_conversation_creator", gate, raising=False
    )
    return calls


@pytest.fixture
def refusing_creator(monkeypatch, events):
    """The creator gate, refusing: an editor of the deck who did not create
    this session (the owner's, or another contributor's)."""
    calls = []

    def gate(session_id):
        calls.append(session_id)
        events.append(("creator", session_id))
        raise HTTPException(
            status_code=403,
            detail="Only the session's creator can change its conversation.",
        )

    monkeypatch.setattr(
        "src.api.routes.sessions._require_conversation_creator", gate, raising=False
    )
    return calls


@pytest.fixture
def session_lock(monkeypatch, events):
    """The session lock, on the session manager the route module looks up.

    ``grant`` is what ``acquire_session_lock`` answers (False: a turn holds
    it); ``acquired`` / ``released`` record the session id of every call.
    """
    lock = SimpleNamespace(grant=True, acquired=[], released=[])

    class _Manager:
        def acquire_session_lock(self, session_id, timeout_seconds=300):
            lock.acquired.append(session_id)
            events.append(("acquire", session_id))
            return lock.grant

        def release_session_lock(self, session_id):
            lock.released.append(session_id)
            events.append(("release", session_id))

    manager = _Manager()
    monkeypatch.setattr(
        "src.api.routes.sessions.get_session_manager", lambda: manager
    )
    return lock


# The order a clear that gets as far as the service runs its steps in.
def _the_whole_clear(session_id: str) -> list[tuple[str, str]]:
    return [
        ("deck_gate", session_id),
        ("creator", session_id),
        ("acquire", session_id),
        ("service", session_id),
        ("release", session_id),
    ]


@pytest.fixture
def as_editor(monkeypatch):
    """Authenticate requests as ``editor@example.com``.

    The real middleware reads ``DEV_USER_ID`` on every request when no token
    header is sent (``src/api/main.py``), so the identity the route forwards as
    ``cleared_by`` comes from the request, not from anything the test patches.
    """
    monkeypatch.setenv("DEV_USER_ID", "editor@example.com")


@pytest.fixture
def stub_service(monkeypatch, events):
    """Replaces ChatService for the route tests; records (session_id, cleared_by)."""
    calls = []

    class _Stub:
        def clear_context(self, session_id, *, cleared_by):
            calls.append((session_id, cleared_by))
            events.append(("service", session_id))
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
        self, client, deck_gate, allowing_creator, session_lock, stub_service, events
    ):
        """The gate's DEFAULT is CAN_VIEW: taking it would let a viewer wipe
        another user's transcript and graph thread."""
        resp = client.delete("/api/sessions/s1/context")

        assert resp.status_code == 403
        assert deck_gate == [("s1", PermissionLevel.CAN_EDIT)]
        assert stub_service == [], "the gate must run BEFORE any clearing"
        # The deck gate is FIRST: a viewer reaches neither the creator gate nor
        # the lock (#323, Review focus 3).
        assert allowing_creator == []
        assert session_lock.acquired == []
        assert session_lock.released == []
        assert events == [("deck_gate", "s1")]

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
        self, client, allowing_gate, allowing_creator, session_lock, stub_service,
        as_editor, events,
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
        # Exactly this order: deck gate, creator gate, acquire, clear, release
        # (#323, Review focus 3).  The lock is taken only once both gates have
        # passed, and is held across the clear.
        assert events == _the_whole_clear("s1")

    def test_a_lock_release_failure_after_a_committed_clear_is_still_a_200(
        self, client, allowing_gate, allowing_creator, session_lock, stub_service,
        as_editor, events, monkeypatch,
    ):
        """Whole-branch review W2: the clear has committed by the time the
        ``finally`` releases the lock.  If the release raises, the caller must
        still be told the clear happened (D2 rejected "500 for a clear that
        actually happened"); the release failure is logged, not surfaced."""
        from src.api.routes import sessions as sessions_route

        manager = sessions_route.get_session_manager()  # the session_lock stub

        def _broken_release(session_id):
            events.append(("release", session_id))
            raise RuntimeError("lock row unreachable")

        monkeypatch.setattr(manager, "release_session_lock", _broken_release)

        resp = client.delete("/api/sessions/s1/context")

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cleared"
        assert stub_service == [("s1", "editor@example.com")]
        assert events == _the_whole_clear("s1")

    def test_a_missing_session_is_a_404(
        self, client, allowing_gate, allowing_creator, session_lock, monkeypatch,
        as_editor, events,
    ):
        """The stub records the call, so the 404 cannot come from a signature
        mismatch (a TypeError would be a 500, and would record nothing)."""
        calls = []

        class _Missing:
            def clear_context(self, session_id, *, cleared_by):
                calls.append((session_id, cleared_by))
                events.append(("service", session_id))
                raise SessionNotFoundError(f"Session not found: {session_id}")

        monkeypatch.setattr(
            "src.api.routes.sessions.get_chat_service", lambda: _Missing()
        )

        resp = client.delete("/api/sessions/ghost/context")
        assert resp.status_code == 404
        assert calls == [("ghost", "editor@example.com")]
        # A failed clear still gives the lock back: once, after the service.
        assert session_lock.released == ["ghost"]
        assert events == _the_whole_clear("ghost")

    def test_an_unimplemented_saver_surfaces_as_a_500(
        self, client, allowing_gate, allowing_creator, session_lock, monkeypatch,
        as_editor, events,
    ):
        """The stub records the call: a TypeError from a signature mismatch is
        also a 500, so the status alone would pass while testing nothing."""
        calls = []

        class _Unimplemented:
            def clear_context(self, session_id, *, cleared_by):
                calls.append((session_id, cleared_by))
                events.append(("service", session_id))
                raise NotImplementedError

        monkeypatch.setattr(
            "src.api.routes.sessions.get_chat_service", lambda: _Unimplemented()
        )

        resp = client.delete("/api/sessions/s1/context")
        assert resp.status_code == 500
        assert calls == [("s1", "editor@example.com")]
        # A failed clear still gives the lock back: once, after the service.
        assert session_lock.released == ["s1"]
        assert events == _the_whole_clear("s1")

    def test_an_editor_who_is_not_the_sessions_creator_is_refused(
        self, client, allowing_gate, refusing_creator, session_lock, stub_service,
        as_editor, events,
    ):
        """The deck gate resolves on the ROOT deck, so every editor of a shared
        deck passes it -- for the owner's session id too, which is what
        ``/api/sessions/shared`` lists.  Conversations are private (D3/D4): the
        creator gate refuses, before the lock is taken and before anything is
        cleared."""
        resp = client.delete("/api/sessions/owners-session/context")

        assert resp.status_code == 403
        assert refusing_creator == ["owners-session"]
        assert stub_service == [], "a refused clear must not reach the service"
        assert session_lock.acquired == [], "the creator gate runs BEFORE the lock"
        assert session_lock.released == []
        assert events == [
            ("deck_gate", "owners-session"),
            ("creator", "owners-session"),
        ]

    def test_a_session_with_a_turn_in_flight_is_a_409_and_nothing_is_cleared(
        self, client, allowing_gate, allowing_creator, session_lock, stub_service,
        as_editor, events,
    ):
        """A chat turn or a slide operation holds the session lock (D6).  The
        busy answer must NOT release it: the lock belongs to the request that
        took it, and freeing it would let a third request run alongside that
        turn."""
        session_lock.grant = False

        resp = client.delete("/api/sessions/s1/context")

        assert resp.status_code == 409
        assert stub_service == [], "a busy session must not be cleared"
        assert session_lock.acquired == ["s1"]
        assert session_lock.released == [], (
            "a 409 must not release a lock this request did not acquire"
        )
        assert events == [
            ("deck_gate", "s1"),
            ("creator", "s1"),
            ("acquire", "s1"),
        ]

        from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL

        assert resp.json()["detail"] == CONVERSATION_BUSY_DETAIL
        # Plan Task 3 interface, accepted by PLAN-CORRECTIONS C6.  The frontend
        # maps the 409 by status, never by this string.
        assert CONVERSATION_BUSY_DETAIL == (
            "Something is still running on this deck. "
            "Wait for it to finish, then try again."
        )

    def test_the_route_passes_the_caller_as_cleared_by(
        self, client, allowing_gate, allowing_creator, session_lock, stub_service,
        as_editor,
    ):
        """The identity comes from the request (``DEV_USER_ID`` through the real
        middleware), not from anything the test patches: the creator gate judges
        the same caller the clear is attributed to (D5)."""
        resp = client.delete("/api/sessions/s1/context")

        assert resp.status_code == 200
        assert allowing_creator == [("s1", "editor@example.com")]
        assert stub_service == [("s1", "editor@example.com")]


# ---------------------------------------------------------------------------
# The creator gate: ``_require_conversation_creator`` (src/api/routes/_authz.py).
#
# The SAME check GET /api/sessions/{id}/messages makes (sessions.py,
# ``if session.get("created_by") != current_user: 403``): the session's own
# ``created_by`` against the caller, exactly.  No fallback to the parent or root
# deck, and nothing about deck permission -- the owner of a deck is refused on
# a contributor's session.  On top of that copy, a missing user is a 401 (an
# exact compare alone would let "no user" through on a session with no
# recorded creator).  The gate does not exist before the fix, so each test
# imports it inside its body.
# ---------------------------------------------------------------------------


def _conversation_creator_gate():
    from src.api.routes._authz import _require_conversation_creator

    return _require_conversation_creator


def _session_info(
    session_id: str,
    created_by: str | None,
    *,
    internal_id: int = 1,
    parent: str | None = None,
    parent_internal_id: int | None = None,
) -> dict:
    """The keys of ``SessionManager.get_session``'s dict a creator check could read."""
    return {
        "id": internal_id,
        "session_id": session_id,
        "created_by": created_by,
        "is_contributor_session": parent is not None,
        "parent_session_id": parent,
        "parent_session_internal_id": parent_internal_id,
    }


@pytest.fixture
def gate_sessions(monkeypatch):
    """The session manager the gate reads, at ``src.api.routes._authz``.

    ``known`` maps session_id -> ``get_session``'s dict; any other id raises
    ``SessionNotFoundError``, as the real one does.  ``lookups`` records ids.
    """
    state = SimpleNamespace(known={}, lookups=[])

    class _Manager:
        def get_session(self, session_id):
            state.lookups.append(session_id)
            if session_id not in state.known:
                raise SessionNotFoundError(f"Session not found: {session_id}")
            return dict(state.known[session_id])

    manager = _Manager()
    monkeypatch.setattr("src.api.routes._authz.get_session_manager", lambda: manager)
    return state


class TestTheConversationCreatorGate:
    def test_the_creator_passes(self, gate_sessions, as_user):
        gate_sessions.known["s1"] = _session_info("s1", "alice@example.com")
        gate = _conversation_creator_gate()

        with as_user("alice@example.com"):
            assert gate("s1") is None

        assert gate_sessions.lookups == ["s1"]

    @pytest.mark.parametrize(
        "created_by",
        ["alice@example.com", None],
        ids=["someone_elses_session", "no_recorded_creator"],
    )
    def test_another_user_is_a_403(self, gate_sessions, as_user, created_by):
        """``created_by`` is nullable; GET /messages refuses every caller on a
        session with no recorded creator, and so does this gate."""
        gate_sessions.known["s1"] = _session_info("s1", created_by)
        gate = _conversation_creator_gate()

        with as_user("mallory@example.com"), pytest.raises(HTTPException) as excinfo:
            gate("s1")

        assert excinfo.value.status_code == 403

    @pytest.mark.parametrize(
        "created_by",
        ["alice@example.com", None],
        ids=["someone_elses_session", "no_recorded_creator"],
    )
    def test_no_user_is_a_401(self, gate_sessions, as_user, created_by):
        """The ``no_recorded_creator`` case is the one an exact compare alone
        gets wrong: ``None != None`` is False, so it would pass an anonymous caller."""
        gate_sessions.known["s1"] = _session_info("s1", created_by)
        gate = _conversation_creator_gate()

        with as_user(None), pytest.raises(HTTPException) as excinfo:
            gate("s1")

        assert excinfo.value.status_code == 401

    def test_an_unknown_session_is_a_404(self, gate_sessions, as_user):
        """An HTTPException, not the manager's SessionNotFoundError: the route
        calls the gate outside its try block, where that would be a 500."""
        gate = _conversation_creator_gate()

        with as_user("alice@example.com"), pytest.raises(HTTPException) as excinfo:
            gate("ghost")

        assert excinfo.value.status_code == 404
        assert gate_sessions.lookups == ["ghost"]

    def test_a_contributor_session_is_gated_on_the_contributor_not_the_owner(
        self, gate_sessions, as_user
    ):
        """A contributor clears only their own session (D3).  The deck owner,
        though they manage the deck, cannot clear the contributor's
        conversation: the gate reads the session's own ``created_by``, never the
        parent's (the owner's root session is known to the stub, so resolving to
        it would let the owner through and fail here)."""
        gate_sessions.known["owner"] = _session_info(
            "owner", "owner@example.com", internal_id=1
        )
        gate_sessions.known["contrib"] = _session_info(
            "contrib",
            "contributor@example.com",
            internal_id=2,
            parent="owner",
            parent_internal_id=1,
        )
        gate = _conversation_creator_gate()

        with as_user("contributor@example.com"):
            assert gate("contrib") is None

        with as_user("owner@example.com"), pytest.raises(HTTPException) as excinfo:
            gate("contrib")

        assert excinfo.value.status_code == 403


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

"""`clear_context` (ws4d D1 / spec §7.2): the service, and the route's CAN_EDIT gate.

Real sqlite for the service half — the defect this code exists to prevent (a
clear that takes the engine-mode marker with it, silently reverting the deck to
the monolith on the next turn) is invisible to a mock, and so is the one that
keeps the spec's row but loses the graph thread.  Every assertion reads rows
back, and mode is re-derived through `resolve_engine_mode` rather than asserted
on a string.

Patch targets: `clear_context` imports `get_db_session` and `get_checkpointer`
lazily inside the method (importing `src.core.checkpointer` at module scope
would pull langgraph into the unit suite's collection chain), so the reachable
targets are the source attributes `src.core.database.get_db_session` and
`src.core.checkpointer.get_checkpointer`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.services.chat_service import (
    AGENT_MODE_PHRASE,
    ChatService,
    resolve_engine_mode,
)
from src.api.services.deck_level_writer import read_deck_spec
from src.api.services.session_manager import SessionNotFoundError
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import SessionMessage, SessionSlideDeck, UserSession
from tests.unit.conftest import _make_fake_db, _make_factory

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_CHECKPOINTER = "src.core.checkpointer.get_checkpointer"

_PHRASE_MESSAGE = f"{AGENT_MODE_PHRASE} and build me a deck about puffins"
_PLAIN_MESSAGE = "Build me a deck about puffins"


class _RecordingSaver:
    """Stands in for SqlAlchemyCheckpointSaver, recording every delete_thread."""

    def __init__(self, raises: BaseException | None = None):
        self.deleted: list[str] = []
        self._raises = raises

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)
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
            result = ChatService().clear_context(sid)

            # The marker survived, everything else went.
            rows = _messages_of(factory, sid)
            assert [r.content for r in rows] == [_PHRASE_MESSAGE]
            assert rows[0].role == "user"
            assert result["deleted_messages"] == 3
            assert result["preserved_message_id"] == rows[0].id

            # The mode the marker encodes survived with it.
            assert resolve_engine_mode(sid) == "graph"

            # The spec is still there AND still readable.
            assert _deck_spec_column(factory, sid) == spec_before
            assert read_deck_spec(sid) == json.loads(spec_before)

        # The graph thread was deleted, keyed by the session id invoke_graph
        # runs the thread under.
        assert saver.deleted == [sid]

    def test_a_monolith_sessions_first_row_is_preserved_too(
        self, session_with_messages, _session_unit_engine
    ):
        """Clearing never CHANGES the mode — in either direction."""
        sid = session_with_messages(
            [_PLAIN_MESSAGE, "and now a chart"], message_type="user_input"
        )
        factory = _make_factory(_session_unit_engine)

        saver = _RecordingSaver()
        with _patched(factory, saver):
            result = ChatService().clear_context(sid)
            assert [r.content for r in _messages_of(factory, sid)] == [_PLAIN_MESSAGE]
            assert result["deleted_messages"] == 1
            assert resolve_engine_mode(sid) == "monolith"

    def test_a_session_with_no_messages_clears_cleanly(
        self, empty_session, _session_unit_engine
    ):
        factory = _make_factory(_session_unit_engine)
        saver = _RecordingSaver()
        with _patched(factory, saver):
            result = ChatService().clear_context(empty_session)
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
            result = ChatService().clear_context(sid)
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
            ChatService().clear_context(contrib_sid)
            assert [r.content for r in _messages_of(factory, owner_sid)] == [
                _PHRASE_MESSAGE
            ]
            assert [r.content for r in _messages_of(factory, contrib_sid)] == [
                "my own first ask"
            ]
            assert resolve_engine_mode(contrib_sid) == "graph"
        assert saver.deleted == [contrib_sid]

    def test_an_unimplemented_saver_rolls_the_prune_back(
        self, session_with_messages, _session_unit_engine
    ):
        """BaseCheckpointSaver.delete_thread is `raise NotImplementedError`.

        It must surface (the route turns it into a 500) rather than skip
        quietly, and it must not leave a half-cleared session behind: the call
        sits inside the transaction, so the transcript prune rolls back.
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
                ChatService().clear_context(sid)

        assert [r.content for r in _messages_of(factory, sid)] == before

    def test_unknown_session_raises_session_not_found(self, _session_unit_engine):
        factory = _make_factory(_session_unit_engine)
        saver = _RecordingSaver()
        with _patched(factory, saver):
            with pytest.raises(SessionNotFoundError):
                ChatService().clear_context("no-such-session")
        assert saver.deleted == []


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
def stub_service(monkeypatch):
    """Replaces ChatService for the route tests; records clear_context calls."""
    calls = []

    class _Stub:
        def clear_context(self, session_id):
            calls.append(session_id)
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
        self, client, allowing_gate, stub_service
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
        assert stub_service == ["s1"]

    def test_a_missing_session_is_a_404(self, client, allowing_gate, monkeypatch):
        class _Missing:
            def clear_context(self, session_id):
                raise SessionNotFoundError(f"Session not found: {session_id}")

        monkeypatch.setattr(
            "src.api.routes.sessions.get_chat_service", lambda: _Missing()
        )

        resp = client.delete("/api/sessions/ghost/context")
        assert resp.status_code == 404

    def test_an_unimplemented_saver_surfaces_as_a_500(
        self, client, allowing_gate, monkeypatch
    ):
        class _Unimplemented:
            def clear_context(self, session_id):
                raise NotImplementedError

        monkeypatch.setattr(
            "src.api.routes.sessions.get_chat_service", lambda: _Unimplemented()
        )

        resp = client.delete("/api/sessions/s1/context")
        assert resp.status_code == 500

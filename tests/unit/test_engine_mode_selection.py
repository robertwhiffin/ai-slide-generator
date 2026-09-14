"""Engine-mode selection (ws4d D1): the phrase, the sticky resolver, the marker carry.

Real sqlite throughout.  The whole point of `resolve_engine_mode` is that the
answer is DERIVED from committed rows rather than stored, so every assertion
here reads the database back through the resolver; a mock standing in for the
transcript would prove nothing about the derivation.

Patch targets — `resolve_engine_mode` and `clear_context` import
`get_db_session` lazily inside the function body, matching this file's four
existing in-function imports of it, so the module has no own reference to
patch.  The reachable target is therefore the SOURCE attribute,
`src.core.database.get_db_session`; `src.api.services.session_manager.
get_db_session` is patched alongside it so that a wrong implementation which
delegated to a SessionManager method would run against THIS engine and fail on
the behaviour, not on a real-database connection error.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.api.services.chat_service import (
    AGENT_MODE_PHRASE,
    resolve_engine_mode,
)
from src.database.models.session import SessionMessage, UserSession
from tests.unit.conftest import _make_fake_db, _make_factory

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"

# The two message_type values the two live user-turn paths write for the SAME
# kind of turn: "user_input" on the sync/streaming path (chat_service.py:903),
# "user_query" on the async route (chat.py:636) and MCP (mcp_server.py:238).
# None is the third real shape — POST /sessions/{id}/messages leaves it NULL.
# Mode resolution must filter on `role` alone, so every stickiness assertion
# runs against all three.
MESSAGE_TYPES = ["user_input", "user_query", None]

_PHRASE_MESSAGE = f"{AGENT_MODE_PHRASE} and build me a deck about puffins"
_PLAIN_MESSAGE = "Build me a deck about puffins"


@contextlib.contextmanager
def _patched(factory):
    """Point the resolver's DB at *factory*'s throwaway engine."""
    fake = _make_fake_db(factory)
    with patch(_DB_SOURCE, fake), patch(_MANAGER_DB, fake):
        yield


def _add_message(factory, session_id: str, *, role: str, content: str,
                 message_type=None, offset_seconds: int = 0) -> None:
    """Append one row to *session_id*'s transcript, *offset_seconds* from now."""
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


# ---------------------------------------------------------------------------
# The phrase in the FIRST user message selects the graph; its absence doesn't.
# ---------------------------------------------------------------------------


class TestThePhraseSelectsTheEngine:
    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_phrase_in_first_user_message_selects_graph(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        sid = session_with_messages([_PHRASE_MESSAGE], message_type=message_type)
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_absence_of_the_phrase_selects_monolith(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        sid = session_with_messages([_PLAIN_MESSAGE], message_type=message_type)
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "monolith"

    def test_the_match_is_a_substring_anywhere_in_the_message(
        self, session_with_messages, _session_unit_engine
    ):
        """§D0: a loose substring match is the intended (unhardened) form."""
        sid = session_with_messages([f"hello there, {AGENT_MODE_PHRASE}, thanks"])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    def test_the_match_is_case_sensitive(
        self, session_with_messages, _session_unit_engine
    ):
        """Pins a judgment call: the constant's own casing is the trigger.

        Loose on position, exact on case — a lowercase 'use agent mode' in
        prose is far likelier to be accidental than the shouted form.  One
        `.lower()` reverses it if the operator wants the looser rule.
        """
        sid = session_with_messages([AGENT_MODE_PHRASE.lower() + " please"])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "monolith"


# ---------------------------------------------------------------------------
# Sticky: only the EARLIEST user row counts.
# ---------------------------------------------------------------------------


class TestStickiness:
    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_mode_is_sticky_across_later_turns(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        """Turn 2 and turn 3 carry no phrase and must still resolve to graph."""
        sid = session_with_messages(
            [_PHRASE_MESSAGE, "make slide 2 blue", "now add a summary"],
            assistant_messages=["done", "done again"],
            message_type=message_type,
        )
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_a_later_phrase_does_not_switch_a_monolith_session(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        """Otherwise turn n writes rows while turn n-1 wrote deck_json."""
        sid = session_with_messages(
            [_PLAIN_MESSAGE, _PHRASE_MESSAGE, _PHRASE_MESSAGE],
            message_type=message_type,
        )
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "monolith"

    def test_an_assistant_message_carrying_the_phrase_is_ignored(
        self, session_with_messages, _session_unit_engine
    ):
        """Echoed tool output must not be able to flip the engine."""
        sid = session_with_messages(
            [_PLAIN_MESSAGE], assistant_messages=[f"I will {AGENT_MODE_PHRASE}"]
        )
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "monolith"

    def test_an_assistant_only_transcript_carrying_the_phrase_is_ignored(
        self, session_with_messages, _session_unit_engine
    ):
        """No user row at all: the assistant's phrase is still not a marker."""
        sid = session_with_messages([], assistant_messages=[_PHRASE_MESSAGE])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "monolith"

    def test_a_system_role_message_carrying_the_phrase_is_ignored(
        self, empty_session, _session_unit_engine
    ):
        """POST /sessions/{id}/messages accepts an arbitrary role (sessions.py:658).

        A 'system' row carrying the phrase on a session with no user turn is
        unusual but reachable, and must not select the graph.
        """
        factory = _make_factory(_session_unit_engine)
        _add_message(
            factory, empty_session, role="system", content=_PHRASE_MESSAGE
        )
        with _patched(factory):
            assert resolve_engine_mode(empty_session) == "monolith"


# ---------------------------------------------------------------------------
# Defaults: everything unknown is the monolith.
# ---------------------------------------------------------------------------


class TestDefaultsToMonolith:
    def test_session_with_no_user_message_gets_monolith(
        self, empty_session, _session_unit_engine
    ):
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(empty_session) == "monolith"

    def test_mcp_created_session_gets_monolith(
        self, mcp_created_session, _session_unit_engine
    ):
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(mcp_created_session) == "monolith"

    def test_unknown_session_gets_monolith(self, _session_unit_engine):
        """Mode resolution must never be the thing that fails a turn."""
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode("no-such-session") == "monolith"

    def test_no_session_id_gets_monolith(self):
        assert resolve_engine_mode(None) == "monolith"
        assert resolve_engine_mode("") == "monolith"

    def test_empty_first_user_message_gets_monolith(
        self, session_with_messages, _session_unit_engine
    ):
        sid = session_with_messages(["", _PHRASE_MESSAGE])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "monolith"


# ---------------------------------------------------------------------------
# Ruling W-3: the mode belongs to the OWNER DECK, not the calling session.
# ---------------------------------------------------------------------------


class TestOwnerDeckResolution:
    def test_the_fixture_is_a_real_contributor_session(self, contributor_session):
        """Precondition for the two tests below, asserted rather than assumed.

        A test using a standalone session would pass whether or not the owner
        was resolved, so it would prove nothing about W-3.
        """
        db = contributor_session._factory()
        try:
            contrib = (
                db.query(UserSession)
                .filter(
                    UserSession.session_id
                    == contributor_session.contributor_session_id
                )
                .one()
            )
            assert contrib.parent_session_id is not None
            assert contrib.slide_deck is None
        finally:
            db.close()

    def test_contributor_inherits_the_owner_decks_graph_mode(
        self, contributor_session
    ):
        """The marker is on the OWNER's transcript; the contributor has none."""
        factory = contributor_session._factory
        _add_message(
            factory,
            contributor_session._owner_session_id,
            role="user",
            content=_PHRASE_MESSAGE,
            message_type="user_input",
        )
        _add_message(
            factory,
            contributor_session.contributor_session_id,
            role="user",
            content=_PLAIN_MESSAGE,
            message_type="user_query",
            offset_seconds=10,
        )
        with _patched(factory):
            assert (
                resolve_engine_mode(contributor_session.contributor_session_id)
                == "graph"
            )

    def test_contributor_phrase_does_not_switch_the_owners_monolith_deck(
        self, contributor_session
    ):
        """The divergence W-3 closes: two contributors, one deck, two engines."""
        factory = contributor_session._factory
        _add_message(
            factory,
            contributor_session._owner_session_id,
            role="user",
            content=_PLAIN_MESSAGE,
            message_type="user_input",
        )
        _add_message(
            factory,
            contributor_session.contributor_session_id,
            role="user",
            content=_PHRASE_MESSAGE,
            message_type="user_query",
            offset_seconds=10,
        )
        with _patched(factory):
            assert (
                resolve_engine_mode(contributor_session.contributor_session_id)
                == "monolith"
            )

    def test_the_owner_session_resolves_its_own_transcript(
        self, contributor_session
    ):
        """An owner session is its own deck owner — the same hop, no parent."""
        factory = contributor_session._factory
        _add_message(
            factory,
            contributor_session._owner_session_id,
            role="user",
            content=_PHRASE_MESSAGE,
        )
        with _patched(factory):
            assert (
                resolve_engine_mode(contributor_session._owner_session_id)
                == "graph"
            )


# ---------------------------------------------------------------------------
# duplicate_session carries the marker — and only the marker.
# ---------------------------------------------------------------------------


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


class TestDuplicateCarriesTheMarker:
    def test_duplicate_of_a_graph_mode_deck_stays_in_graph_mode(
        self, deck_with_three_rows
    ):
        factory = deck_with_three_rows._factory
        _add_message(
            factory,
            deck_with_three_rows.session_id,
            role="user",
            content=_PHRASE_MESSAGE,
            message_type="user_query",
        )

        with _patched(factory):
            assert resolve_engine_mode(deck_with_three_rows.session_id) == "graph"

        copy = deck_with_three_rows.duplicate()

        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "graph"

    def test_only_the_marker_row_is_copied(self, deck_with_three_rows):
        """Copying more rows would replay a phantom conversation into the copy."""
        factory = deck_with_three_rows._factory
        sid = deck_with_three_rows.session_id
        _add_message(factory, sid, role="user", content=_PHRASE_MESSAGE,
                     message_type="user_query")
        _add_message(factory, sid, role="assistant", content="here you go",
                     message_type="llm_response", offset_seconds=5)
        _add_message(factory, sid, role="user", content="make it blue",
                     message_type="user_input", offset_seconds=10)

        copy = deck_with_three_rows.duplicate()

        rows = _messages_of(factory, copy["session_id"])
        assert len(rows) == 1
        assert rows[0].role == "user"
        assert rows[0].content == _PHRASE_MESSAGE
        # Preserved so _hydrate_chat_history's HUMAN_TYPES allowlist treats the
        # carried row exactly as it treated the original.
        assert rows[0].message_type == "user_query"

    def test_duplicate_of_a_monolith_deck_copies_no_message(
        self, deck_with_three_rows
    ):
        """The standing guarantee: a duplicate carries no chat history."""
        factory = deck_with_three_rows._factory
        _add_message(
            factory,
            deck_with_three_rows.session_id,
            role="user",
            content=_PLAIN_MESSAGE,
            message_type="user_input",
        )

        copy = deck_with_three_rows.duplicate()

        assert _messages_of(factory, copy["session_id"]) == []
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "monolith"

    def test_duplicate_from_a_contributor_session_carries_the_owner_marker(
        self, contributor_session
    ):
        """A contributor duplicating a graph-mode deck gets a graph-mode copy."""
        factory = contributor_session._factory
        _add_message(
            factory,
            contributor_session._owner_session_id,
            role="user",
            content=_PHRASE_MESSAGE,
            message_type="user_input",
        )

        with contributor_session._patched():
            copy = contributor_session._sm.duplicate_session(
                source_session_id=contributor_session.contributor_session_id,
                created_by="contributor@example.com",
            )

        rows = _messages_of(factory, copy["session_id"])
        assert [r.content for r in rows] == [_PHRASE_MESSAGE]
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "graph"

    def test_the_carried_marker_predates_the_copys_own_rows(
        self, deck_with_three_rows
    ):
        """restore_version prunes messages by timestamp, so the marker must be
        older than anything the new conversation writes — it keeps the source
        row's created_at, which is older than the copy itself."""
        factory = deck_with_three_rows._factory
        _add_message(
            factory,
            deck_with_three_rows.session_id,
            role="user",
            content=_PHRASE_MESSAGE,
            offset_seconds=-3600,
        )

        copy = deck_with_three_rows.duplicate()

        rows = _messages_of(factory, copy["session_id"])
        db = factory()
        try:
            copy_row = (
                db.query(UserSession)
                .filter(UserSession.session_id == copy["session_id"])
                .one()
            )
            assert rows[0].created_at < copy_row.created_at
        finally:
            db.close()

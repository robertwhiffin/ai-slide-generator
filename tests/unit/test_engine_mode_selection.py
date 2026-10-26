"""Engine-mode selection (ws4d D1): the phrase, the sticky resolver, the marker carry.

Since 2026-10-12 the rule is inverted: every deck runs on the graph UNLESS its
first user message carries ``LEGACY_MODE_PHRASE``.  The old opt-in
``AGENT_MODE_PHRASE`` still lands on the graph (it is simply not the opt-out).

Since Deck Mode (2026-10-22 Task 2) the resolver reads the deck owner's stored
``user_sessions.deck_mode`` instead of its first user message, so every test here
that expects ``"monolith"`` seeds ``deck_mode='legacy'`` on the owner row; the
phrase-semantics tests whose subject is gone were deleted (the rest go in Task 6).
Column-based resolution itself is pinned in ``test_deck_mode_resolution.py``.

Real sqlite throughout: every assertion reads the database back through the
resolver.

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
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.api.services.chat_service import (
    AGENT_MODE_PHRASE,
    LEGACY_MODE_PHRASE,
    resolve_engine_mode,
)
from src.domain.conversation_engine import with_legacy_marker
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, UserSession
from tests.unit.conftest import _make_factory, _make_fake_db

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"

# The two message_type values the two live user-turn paths write for the SAME
# kind of turn: "user_input" on the sync/streaming path (chat_service.py:903),
# "user_query" on the async route (chat.py:636) and MCP (mcp_server.py:238).
# None is the third real shape — POST /sessions/{id}/messages leaves it NULL.
# Mode resolution must filter on `role` alone, so every stickiness assertion
# runs against all three.
MESSAGE_TYPES = ["user_input", "user_query", None]

# The opt-out: the only first message that keeps a deck off the graph.
_PHRASE_MESSAGE = f"{LEGACY_MODE_PHRASE} and build me a deck about puffins"
# The pre-inversion opt-in: still the graph, harmlessly.
_AGENT_MESSAGE = f"{AGENT_MODE_PHRASE} and build me a deck about puffins"
_PLAIN_MESSAGE = "Build me a deck about puffins"


@contextlib.contextmanager
def _patched(factory):
    """Point the resolver's DB at *factory*'s throwaway engine."""
    fake = _make_fake_db(factory)
    with patch(_DB_SOURCE, fake), patch(_MANAGER_DB, fake):
        yield


def _set_deck_mode(factory, session_id: str, deck_mode) -> None:
    """Store *deck_mode* on *session_id*'s row (the deck owner's, where it is read)."""
    db = factory()
    try:
        us = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        us.deck_mode = deck_mode
        db.commit()
    finally:
        db.close()


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
# Graph Release seeding for the duplicate tests.
#
# duplicate_session decides graph capability and then locks the ACTIVE Graph
# Release before constructing the copy's UserSession (correction C-2), because
# #261 makes a graph-capable conversation's pin immutable from creation. A
# marker-carrying duplicate therefore requires a live active release to exist.
#
# Two releases are published, and the SOURCE session is pinned to the SUPERSEDED
# one. That is what gives the pin assertions their teeth: duplication must never
# copy the source's pin, and must never infer "latest" by ordering instead of
# locking the active row — either regression would come back with
# _SUPERSEDED_RELEASE_ID.
# ---------------------------------------------------------------------------

_SUPERSEDED_RELEASE_ID = 501
_ACTIVE_RELEASE_ID = 502


def _seed_releases_pinning_source_to_the_superseded_one(
    factory, source_session_id: str
) -> None:
    """Publish a superseded release plus the active one; pin *source* to the old one."""
    published = datetime.now(timezone.utc) - timedelta(days=2)
    retired = published + timedelta(days=1)
    db = factory()
    try:
        db.add(
            GraphRelease(
                id=_SUPERSEDED_RELEASE_ID,
                version_number=1,
                release_note="superseded engine-mode fixture release",
                published_by="fixture@example.com",
                published_at=published,
                effective_from=published,
                effective_to=retired,
            )
        )
        db.add(
            GraphRelease(
                id=_ACTIVE_RELEASE_ID,
                version_number=2,
                release_note="active engine-mode fixture release",
                published_by="fixture@example.com",
                published_at=retired,
                effective_from=retired,
                effective_to=None,
            )
        )
        source = (
            db.query(UserSession)
            .filter(UserSession.session_id == source_session_id)
            .one()
        )
        source.graph_release_id = _SUPERSEDED_RELEASE_ID
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _pin_of(factory, session_id: str):
    """Return *session_id*'s persisted graph_release_id."""
    db = factory()
    try:
        return (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .one()
            .graph_release_id
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The opt-out in the FIRST user message selects the monolith; its absence the graph.
# ---------------------------------------------------------------------------


class TestThePhraseSelectsTheEngine:
    def test_the_phrase_is_exactly_the_agreed_string(self):
        """Pinned verbatim: the whole switch is this literal, typed by a human.

        Every other test in this file builds its messages FROM the constant, so
        they would all follow a changed value silently — this is the one that
        would not.
        """
        assert LEGACY_MODE_PHRASE == "USE LEGACY MODE"
        assert AGENT_MODE_PHRASE == "USE AGENT MODE"

    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_absence_of_the_phrase_selects_graph(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        sid = session_with_messages([_PLAIN_MESSAGE], message_type=message_type)
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    def test_the_old_agent_mode_phrase_still_selects_graph(
        self, session_with_messages, _session_unit_engine
    ):
        """Pre-inversion habit: typing the old opt-in is harmless."""
        sid = session_with_messages([_AGENT_MESSAGE])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    def test_the_match_is_case_sensitive(
        self, session_with_messages, _session_unit_engine
    ):
        """Pins a judgment call: the constant's own casing is the trigger.

        Loose on position, exact on case — a lowercase 'use legacy mode' in
        prose is far likelier to be accidental than the shouted form.  One
        `.lower()` reverses it if the operator wants the looser rule.
        """
        sid = session_with_messages([LEGACY_MODE_PHRASE.lower() + " please"])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"


# ---------------------------------------------------------------------------
# Sticky: only the EARLIEST user row counts.
# ---------------------------------------------------------------------------


class TestStickiness:
    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_mode_is_sticky_across_later_turns(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        """A legacy deck's turns 2 and 3 still resolve to monolith."""
        factory = _make_factory(_session_unit_engine)
        sid = session_with_messages(
            [_PLAIN_MESSAGE, "make slide 2 blue", "now add a summary"],
            assistant_messages=["done", "done again"],
            message_type=message_type,
        )
        _set_deck_mode(factory, sid, "legacy")
        with _patched(factory):
            assert resolve_engine_mode(sid) == "monolith"

    @pytest.mark.parametrize("message_type", MESSAGE_TYPES)
    def test_a_later_phrase_does_not_switch_a_graph_session(
        self, session_with_messages, _session_unit_engine, message_type
    ):
        """Otherwise turn n writes rows while turn n-1 wrote deck_json."""
        sid = session_with_messages(
            [_PLAIN_MESSAGE, _PHRASE_MESSAGE, _PHRASE_MESSAGE],
            message_type=message_type,
        )
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    def test_an_assistant_message_carrying_the_phrase_is_ignored(
        self, session_with_messages, _session_unit_engine
    ):
        """Echoed tool output must not be able to flip the engine."""
        sid = session_with_messages(
            [_PLAIN_MESSAGE], assistant_messages=[f"I will {LEGACY_MODE_PHRASE}"]
        )
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    def test_an_assistant_only_transcript_carrying_the_phrase_is_ignored(
        self, session_with_messages, _session_unit_engine
    ):
        """No user row at all: the assistant's phrase is still not a marker."""
        sid = session_with_messages([], assistant_messages=[_PHRASE_MESSAGE])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"

    def test_an_assistant_message_that_predates_the_first_user_turn_is_ignored(
        self, empty_session, _session_unit_engine
    ):
        """The version of the test above that a dropped `role` filter fails.

        Sabotage found this: with the assistant row LATER than the user's, the
        earliest-row rule alone still returns the user's message, so dropping
        the role filter changes nothing.  An assistant/info row written before
        the user's first turn is the shape that actually needs the filter.
        """
        factory = _make_factory(_session_unit_engine)
        _add_message(
            factory, empty_session, role="assistant", content=_PHRASE_MESSAGE,
            message_type="llm_response", offset_seconds=-30,
        )
        _add_message(
            factory, empty_session, role="user", content=_PLAIN_MESSAGE,
            message_type="user_input",
        )
        with _patched(factory):
            assert resolve_engine_mode(empty_session) == "graph"

    def test_a_system_role_message_carrying_the_phrase_is_ignored(
        self, empty_session, _session_unit_engine
    ):
        """POST /sessions/{id}/messages accepts an arbitrary role (sessions.py:658).

        A 'system' row carrying the phrase on a session with no user turn is
        unusual but reachable, and must not select the monolith.
        """
        factory = _make_factory(_session_unit_engine)
        _add_message(
            factory, empty_session, role="system", content=_PHRASE_MESSAGE
        )
        with _patched(factory):
            assert resolve_engine_mode(empty_session) == "graph"


# ---------------------------------------------------------------------------
# Defaults: a deck with nothing to say is the graph; no deck at all is not.
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_session_with_no_user_message_gets_graph(
        self, empty_session, _session_unit_engine
    ):
        """The default engine, matching the pin every creator now takes."""
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(empty_session) == "graph"

    def test_mcp_created_deck_gets_monolith(
        self, mcp_created_session, _session_unit_engine
    ):
        """MCP stays on the monolith: its deck is stored as legacy.

        MCP creates its deck with ``deck_mode="legacy"`` (Task 5) and persists
        the prompt verbatim; this is the resolver half -- a legacy MCP deck
        resolves to the monolith, so a browser turn on it cannot land on the
        graph with no pin.
        """
        factory = _make_factory(_session_unit_engine)
        _set_deck_mode(factory, mcp_created_session, "legacy")
        _add_message(
            factory, mcp_created_session, role="user",
            content=_PLAIN_MESSAGE, message_type="user_query",
        )
        with _patched(factory):
            assert resolve_engine_mode(mcp_created_session) == "monolith"

    def test_an_unmarked_mcp_style_session_gets_graph(
        self, mcp_created_session, _session_unit_engine
    ):
        """Why the marker is needed: agent_config does not decide the engine."""
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(mcp_created_session) == "graph"

    def test_unknown_session_gets_monolith(self, _session_unit_engine):
        """Mode resolution must never be the thing that fails a turn."""
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode("no-such-session") == "monolith"

    def test_no_session_id_gets_monolith(self):
        assert resolve_engine_mode(None) == "monolith"
        assert resolve_engine_mode("") == "monolith"

    def test_empty_first_user_message_gets_graph(
        self, session_with_messages, _session_unit_engine
    ):
        """And a later opt-out cannot rescue it: the empty first row decides."""
        sid = session_with_messages(["", _PHRASE_MESSAGE])
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(sid) == "graph"


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

    def test_contributor_inherits_the_owner_decks_monolith_mode(
        self, contributor_session
    ):
        """Legacy is stored on the OWNER's row; the contributor's row is NULL."""
        factory = contributor_session._factory
        _set_deck_mode(factory, contributor_session._owner_session_id, "legacy")
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
            content=_PLAIN_MESSAGE,
            message_type="user_query",
            offset_seconds=10,
        )
        with _patched(factory):
            assert (
                resolve_engine_mode(contributor_session.contributor_session_id)
                == "monolith"
            )

    def test_contributor_phrase_does_not_switch_the_owners_graph_deck(
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
                == "graph"
            )

    def test_the_owner_session_resolves_its_own_deck_mode(
        self, contributor_session
    ):
        """An owner session is its own deck owner — the same hop, no parent."""
        factory = contributor_session._factory
        _set_deck_mode(factory, contributor_session._owner_session_id, "legacy")
        _add_message(
            factory,
            contributor_session._owner_session_id,
            role="user",
            content=_PLAIN_MESSAGE,
        )
        with _patched(factory):
            assert (
                resolve_engine_mode(contributor_session._owner_session_id)
                == "monolith"
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
    """A duplicate keeps its SOURCE deck's engine.

    Since 2026-10-12 the carried marker is the LEGACY opt-out: a graph source
    yields a pinned copy with no messages (no user row resolves to the graph);
    a legacy source yields an unpinned copy carrying exactly the opt-out row.
    """

    def test_duplicate_of_a_graph_mode_deck_stays_in_graph_mode(
        self, deck_with_three_rows
    ):
        factory = deck_with_three_rows._factory
        _seed_releases_pinning_source_to_the_superseded_one(
            factory, deck_with_three_rows.session_id
        )
        _add_message(
            factory,
            deck_with_three_rows.session_id,
            role="user",
            content=_PLAIN_MESSAGE,
            message_type="user_query",
        )

        with _patched(factory):
            assert resolve_engine_mode(deck_with_three_rows.session_id) == "graph"

        copy = deck_with_three_rows.duplicate()

        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "graph"

        # The copy owns a FRESH pin taken under the active-row lock — not the
        # source's superseded pin, and not a "latest by ordering" guess.
        assert _pin_of(factory, copy["session_id"]) == _ACTIVE_RELEASE_ID
        assert _pin_of(factory, deck_with_three_rows.session_id) == (
            _SUPERSEDED_RELEASE_ID
        )

    def test_duplicate_of_a_graph_deck_copies_no_message(
        self, deck_with_three_rows
    ):
        """The standing guarantee: a duplicate carries no chat history.

        The graph is now the default, so a graph copy needs NO marker row: its
        empty transcript already resolves to the graph.
        """
        factory = deck_with_three_rows._factory
        sid = deck_with_three_rows.session_id
        _seed_releases_pinning_source_to_the_superseded_one(factory, sid)
        _add_message(factory, sid, role="user", content=_AGENT_MESSAGE,
                     message_type="user_query")
        _add_message(factory, sid, role="assistant", content="here you go",
                     message_type="llm_response", offset_seconds=5)

        copy = deck_with_three_rows.duplicate()

        assert _messages_of(factory, copy["session_id"]) == []
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "graph"
        assert _pin_of(factory, copy["session_id"]) == _ACTIVE_RELEASE_ID

    def test_duplicate_of_a_deck_with_no_user_message_is_a_pinned_graph_copy(
        self, deck_with_three_rows
    ):
        """No first message is the graph default; the copy must be pinned for it."""
        factory = deck_with_three_rows._factory
        _seed_releases_pinning_source_to_the_superseded_one(
            factory, deck_with_three_rows.session_id
        )

        copy = deck_with_three_rows.duplicate()

        assert _messages_of(factory, copy["session_id"]) == []
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "graph"
        assert _pin_of(factory, copy["session_id"]) == _ACTIVE_RELEASE_ID

    def test_only_the_marker_row_is_copied(self, deck_with_three_rows):
        """Copying more rows would replay a phantom conversation into the copy."""
        factory = deck_with_three_rows._factory
        sid = deck_with_three_rows.session_id
        _seed_releases_pinning_source_to_the_superseded_one(factory, sid)
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

    def test_duplicate_of_a_legacy_deck_stays_legacy_and_unpinned(
        self, deck_with_three_rows
    ):
        """The legacy copy carries the opt-out and takes no pin.

        An active release is available here, and the legacy copy still takes no
        pin: capability decides whether a pin is selected at all.
        """
        factory = deck_with_three_rows._factory
        _seed_releases_pinning_source_to_the_superseded_one(
            factory, deck_with_three_rows.session_id
        )
        _add_message(
            factory,
            deck_with_three_rows.session_id,
            role="user",
            content=_PHRASE_MESSAGE,
            message_type="user_input",
        )

        copy = deck_with_three_rows.duplicate()

        assert [r.content for r in _messages_of(factory, copy["session_id"])] == [
            _PHRASE_MESSAGE
        ]
        assert _pin_of(factory, copy["session_id"]) is None

    def test_duplicate_from_a_contributor_session_carries_the_owner_marker(
        self, contributor_session
    ):
        """A contributor duplicating a legacy deck gets a legacy copy."""
        factory = contributor_session._factory
        _seed_releases_pinning_source_to_the_superseded_one(
            factory, contributor_session._owner_session_id
        )
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
        assert _pin_of(factory, copy["session_id"]) is None

    def test_duplicate_from_a_contributor_of_a_graph_deck_is_pinned_graph(
        self, contributor_session
    ):
        """Resolving the contributor to the deck owner decides capability.

        The contributor's OWN transcript carries the opt-out; the owner's does
        not, so the copy is graph -- and its pin is its own, from the active row.
        """
        factory = contributor_session._factory
        _seed_releases_pinning_source_to_the_superseded_one(
            factory, contributor_session._owner_session_id
        )
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

        with contributor_session._patched():
            copy = contributor_session._sm.duplicate_session(
                source_session_id=contributor_session.contributor_session_id,
                created_by="contributor@example.com",
            )

        assert _messages_of(factory, copy["session_id"]) == []
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "graph"
        assert _pin_of(factory, copy["session_id"]) == _ACTIVE_RELEASE_ID
        assert _pin_of(factory, contributor_session._owner_session_id) == (
            _SUPERSEDED_RELEASE_ID
        )

    def test_the_carried_marker_predates_the_copys_own_rows(
        self, deck_with_three_rows
    ):
        """restore_version prunes messages by timestamp, so the marker must be
        older than anything the new conversation writes — it keeps the source
        row's created_at, which is older than the copy itself."""
        factory = deck_with_three_rows._factory
        _seed_releases_pinning_source_to_the_superseded_one(
            factory, deck_with_three_rows.session_id
        )
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


# ---------------------------------------------------------------------------
# The shared predicate every creator uses to decide whether to pin.
# ---------------------------------------------------------------------------


class TestTheCreationPredicate:
    """``selects_graph_engine`` decides the PIN at every creator, and
    ``resolve_engine_mode`` decides the ENGINE; they must agree on every input,
    or turn 1 creates an unpinned deck that the resolver sends to the graph."""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (None, True),
            ("", True),
            (_PLAIN_MESSAGE, True),
            (_AGENT_MESSAGE, True),
            (_PHRASE_MESSAGE, False),
            (LEGACY_MODE_PHRASE.lower(), True),
        ],
        ids=["no-message", "empty", "plain", "old-agent-phrase", "legacy", "lowercase"],
    )
    def test_the_predicate(self, content, expected):
        from src.domain.conversation_engine import selects_graph_engine

        assert selects_graph_engine(content) is expected

    def test_with_legacy_marker_is_idempotent_and_keeps_the_prompt(self):
        marked = with_legacy_marker(_PLAIN_MESSAGE)
        assert marked.startswith(LEGACY_MODE_PHRASE)
        assert marked.endswith(_PLAIN_MESSAGE)
        assert with_legacy_marker(marked) == marked
        assert with_legacy_marker(_PHRASE_MESSAGE) == _PHRASE_MESSAGE

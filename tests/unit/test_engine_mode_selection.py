"""Engine-mode selection: the sticky resolver, the owner hop, the duplicate.

A deck's engine is its owner's stored Deck Mode (``user_sessions.deck_mode``):
``legacy`` runs on the monolith; ``agent`` and NULL (not chosen yet) run on the
graph.  No message text selects anything: the ``USE LEGACY MODE`` /
``USE AGENT MODE`` phrases and their helpers were deleted with Task 6, and the
end of this file pins that they are gone.  Column-based resolution itself is
pinned in ``test_deck_mode_resolution.py``, including that the old phrase in a
first message is ordinary text.

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
import importlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.api.services.chat_service import resolve_engine_mode
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
# pinned (non-legacy) duplicate therefore requires a live active release to exist.
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
# Sticky: later turns never move a deck.
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
        """``agent_config`` does not decide the engine: only the stored mode does."""
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode(mcp_created_session) == "graph"

    def test_unknown_session_gets_monolith(self, _session_unit_engine):
        """Mode resolution must never be the thing that fails a turn."""
        with _patched(_make_factory(_session_unit_engine)):
            assert resolve_engine_mode("no-such-session") == "monolith"

    def test_no_session_id_gets_monolith(self):
        assert resolve_engine_mode(None) == "monolith"
        assert resolve_engine_mode("") == "monolith"

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
# duplicate_session copies the owner's deck_mode, and no message.
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


class TestDuplicateKeepsTheOwnersEngine:
    """A duplicate keeps its SOURCE deck's engine.

    Since Deck Mode (Task 5) the copy takes the deck owner's stored
    ``deck_mode``: a legacy source yields an unpinned legacy copy, any other a
    pinned copy.  No copy carries a message; the old marker-row carry is gone.
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
        _add_message(factory, sid, role="user", content=_PLAIN_MESSAGE,
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

    def test_duplicate_of_a_legacy_deck_stays_legacy_and_unpinned(
        self, deck_with_three_rows
    ):
        """The copy keeps the owner's stored legacy mode: it resolves to the
        monolith, takes no pin and carries no message.

        An active release is available here, and the legacy copy still takes no
        pin.  The source's first message is plain text: the column, not the
        text, makes it legacy.
        """
        factory = deck_with_three_rows._factory
        sid = deck_with_three_rows.session_id
        _seed_releases_pinning_source_to_the_superseded_one(factory, sid)
        _set_deck_mode(factory, sid, "legacy")
        _add_message(factory, sid, role="user", content=_PLAIN_MESSAGE,
                     message_type="user_input")

        copy = deck_with_three_rows.duplicate()

        assert _messages_of(factory, copy["session_id"]) == []
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "monolith"
        assert _pin_of(factory, copy["session_id"]) is None

    def test_duplicate_from_a_contributor_session_copies_the_owners_legacy_mode(
        self, contributor_session
    ):
        """A contributor duplicating a legacy deck gets a legacy copy.

        The mode is read off the deck OWNER's row; the owner's first row is not
        copied.
        """
        factory = contributor_session._factory
        owner_sid = contributor_session._owner_session_id
        _seed_releases_pinning_source_to_the_superseded_one(factory, owner_sid)
        _set_deck_mode(factory, owner_sid, "legacy")
        _add_message(factory, owner_sid, role="user", content=_PLAIN_MESSAGE,
                     message_type="user_input")

        with contributor_session._patched():
            copy = contributor_session._sm.duplicate_session(
                source_session_id=contributor_session.contributor_session_id,
                created_by="contributor@example.com",
            )

        assert _messages_of(factory, copy["session_id"]) == []
        with _patched(factory):
            assert resolve_engine_mode(copy["session_id"]) == "monolith"
        assert _pin_of(factory, copy["session_id"]) is None

    def test_duplicate_from_a_contributor_of_a_graph_deck_is_pinned_graph(
        self, contributor_session
    ):
        """Resolving the contributor to the deck owner decides capability.

        The owner's mode is unset, so the copy is graph -- and its pin is its
        own, from the active row, not the owner's superseded one.
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
            content="my own first ask",
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


# ---------------------------------------------------------------------------
# Task 6: the phrase, its helpers and the startup pin backfill are deleted; the
# marker type that hides a kept row is not.
# ---------------------------------------------------------------------------

# What the deleted names look like, as a pattern rather than as the names: the
# Step 4 grep for them over ``tests`` must come back empty, this file included.
# Measured before the deletion, it matches exactly the fourteen names Task 6
# deletes in these three modules and nothing else: the two mode phrases, the two
# ``selects_*`` predicates and the legacy-marker helper (conversation_engine);
# the agent-mode predicate and the re-exported phrases and predicate
# (chat_service); the backfill, its in-transaction helper and its result type,
# and the phrase imports (conversation_pins).  As a pattern it also catches a
# survivor under a new name.
_PHRASE_ERA_NAME = re.compile(r"PHRASE|^_?selects_|legacy_marker|[Bb]ackfill")


@pytest.mark.parametrize(
    "module_name",
    [
        "src.domain.conversation_engine",
        "src.api.services.chat_service",
        "src.services.conversation_pins",
    ],
)
def test_the_phrase_helpers_are_gone(module_name):
    """No message text selects an engine any more, and boot pins nothing, so no
    module offers a phrase, a phrase predicate or the startup backfill."""
    module = importlib.import_module(module_name)
    leftovers = sorted(name for name in dir(module) if _PHRASE_ERA_NAME.search(name))
    assert leftovers == [], f"{module_name} still defines {leftovers}"


@pytest.mark.parametrize(
    ("module_name", "name"),
    [
        ("src.domain.conversation_engine", "ENGINE_MODE_MARKER_MESSAGE_TYPE"),
        ("src.domain.conversation_engine", "is_transcript_message"),
        ("src.api.services.chat_service", "ENGINE_MODE_MARKER_MESSAGE_TYPE"),
    ],
)
def test_the_marker_symbols_stay(module_name, name):
    """The row a clear or a delete keeps is still re-typed and hidden: these stay."""
    assert hasattr(importlib.import_module(module_name), name)


def test_the_marker_type_keeps_its_stored_value():
    """Kept rows already in the database carry this string; a new value would
    show them in every transcript again."""
    from src.domain.conversation_engine import (
        ENGINE_MODE_MARKER_MESSAGE_TYPE,
        is_transcript_message,
    )

    assert ENGINE_MODE_MARKER_MESSAGE_TYPE == "engine_mode_marker"
    assert is_transcript_message("engine_mode_marker") is False
    assert is_transcript_message("user_input") is True


def test_the_glossary_defines_deck_mode():
    """CONTEXT.md carries the **Deck Mode** term (spec 2026-10-22 §8) with its
    Avoid list.  Whitespace is normalised, so the entry may wrap anywhere."""
    context = (Path(__file__).resolve().parents[2] / "CONTEXT.md").read_text()
    entry = re.search(r"^\*\*Deck Mode\*\*:(.*?)(?:\n[ \t]*\n|\Z)", context, re.S | re.M)
    assert entry, "CONTEXT.md has no **Deck Mode**: entry"
    body = " ".join(entry.group(1).split())
    assert "Avoid" in body, body
    assert 'engine mode, graph/monolith, "USE LEGACY MODE"' in body, body

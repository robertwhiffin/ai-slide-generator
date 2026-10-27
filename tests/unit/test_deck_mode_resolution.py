"""Deck Mode → engine resolution, and the session API's ``deck_mode`` (spec 2026-10-22
§5.1, §5.4, §5.5).

A deck's stored ``user_sessions.deck_mode`` is ``"agent"``, ``"legacy"`` or NULL (not
chosen yet).  The job payload keeps its internal ``engine_mode`` values, so resolution
maps the stored mode onto them: ``legacy`` → ``"monolith"``; ``agent`` and NULL →
``"graph"`` (the graph is the default).

The column is meaningful on the deck OWNER's row only.  A contributor session reads
it through the owner hop, for the engine (``resolve_engine_mode``) and for the
session API (``get_session``), so every contributor test below gives the contributor's
own row a value that would change the answer if it were read.

Real sqlite throughout, read back through the shipped functions.
``resolve_engine_mode`` imports ``get_db_session`` lazily, so the reachable patch
target is the source attribute ``src.core.database.get_db_session``;
``src.api.services.session_manager.get_db_session`` is patched alongside it, because
``create_session`` / ``get_session`` go through it.

Every ``create_session`` / ``get_session`` test seeds an active Graph Release, the
unpinned cases included: both return dicts project ``get_conversation_graph_version``,
which raises ``ConversationGraphReleaseIntegrityError`` when no release is active.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from unittest.mock import patch

import pytest
from sqlalchemy import event

from src.api.services.chat_service import resolve_engine_mode
from src.api.services.session_manager import SessionManager
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, UserSession
from src.domain import conversation_engine
from src.services.conversation_pins import lock_active_graph_release
from tests.unit.conftest import _make_factory, _make_fake_db, _make_in_memory_engine

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_LOCK = "src.api.services.session_manager.lock_active_graph_release"

_ACTIVE_RELEASE_ID = 41
_ACTIVE_VERSION = 7

# The removed opt-out, verbatim: since Deck Mode it is ordinary text.
_OLD_OPT_OUT_MESSAGE = "USE LEGACY MODE build a deck"
_PLAIN_MESSAGE = "Build me a deck about puffins"


# ---------------------------------------------------------------------------
# The pure mapping (Task 1)
# ---------------------------------------------------------------------------


def test_engine_mode_for_deck_mode_maps_legacy_to_monolith_else_graph():
    engine_mode_for_deck_mode = conversation_engine.engine_mode_for_deck_mode

    assert engine_mode_for_deck_mode("legacy") == "monolith"
    assert engine_mode_for_deck_mode("agent") == "graph"
    assert engine_mode_for_deck_mode(None) == "graph"


def test_deck_mode_values_are_exactly_agent_and_legacy():
    """The stored values are a fixed vocabulary: every writer validates against
    ``DECK_MODES`` and the migration's fill must equal ``DECK_MODE_LEGACY``."""
    assert conversation_engine.DECK_MODE_AGENT == "agent"
    assert conversation_engine.DECK_MODE_LEGACY == "legacy"
    assert isinstance(conversation_engine.DECK_MODES, frozenset)
    assert conversation_engine.DECK_MODES == frozenset({"agent", "legacy"})

    engine_mode_for_deck_mode = conversation_engine.engine_mode_for_deck_mode
    assert engine_mode_for_deck_mode(conversation_engine.DECK_MODE_LEGACY) == "monolith"
    assert engine_mode_for_deck_mode(conversation_engine.DECK_MODE_AGENT) == "graph"


# ---------------------------------------------------------------------------
# Fixtures and helpers (Task 2)
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """The full Tellr schema (``create_all`` + ``_run_migrations``) in memory."""
    eng = _make_in_memory_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    return _make_factory(engine)


@contextlib.contextmanager
def _patched(factory):
    """Point every ``get_db_session`` the code under test reaches at *factory*."""
    fake = _make_fake_db(factory)
    with patch(_DB_SOURCE, fake), patch(_MANAGER_DB, fake):
        yield


def _seed_session(
    factory,
    *,
    deck_mode: Optional[str] = None,
    parent: Optional[str] = None,
    user_messages: Iterable[str] = (),
) -> str:
    """One ``UserSession`` with *deck_mode* stored, optionally a contributor of
    *parent* (a session id), whose transcript is *user_messages*, earliest first."""
    sid = f"deck-mode-{uuid.uuid4().hex[:10]}"
    db = factory()
    try:
        parent_pk = None
        if parent is not None:
            parent_pk = (
                db.query(UserSession).filter(UserSession.session_id == parent).one().id
            )
        session = UserSession(
            session_id=sid,
            created_by="owner@example.com" if parent is None else "contributor@example.com",
            parent_session_id=parent_pk,
            deck_mode=deck_mode,
        )
        db.add(session)
        db.flush()
        base = datetime.utcnow() - timedelta(minutes=5)
        for i, content in enumerate(user_messages):
            db.add(
                SessionMessage(
                    session_id=session.id,
                    role="user",
                    content=content,
                    message_type="user_input",
                    created_at=base + timedelta(seconds=i),
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return sid


def _row(factory, session_id: str) -> Optional[UserSession]:
    """The persisted ``UserSession`` for *session_id* (detached), or None."""
    db = factory()
    try:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        if row is not None:
            db.expunge(row)
        return row
    finally:
        db.close()


def _seed_active_release(
    factory, release_id: int = _ACTIVE_RELEASE_ID, version: int = _ACTIVE_VERSION
) -> None:
    """The active Graph Release a pinned creation locks (as in
    ``tests/unit/test_conversation_pin_creation.py``)."""
    now = datetime.now(timezone.utc)
    db = factory()
    try:
        db.add(
            GraphRelease(
                id=release_id,
                version_number=version,
                release_note="active deck-mode test release",
                published_by="unit-test@example.com",
                published_at=now,
                effective_from=now,
            )
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# resolve_engine_mode reads the OWNER's column
# ---------------------------------------------------------------------------


def test_a_legacy_owner_resolves_to_monolith(factory):
    """Its first message is plain text: only the column can make it legacy."""
    sid = _seed_session(factory, deck_mode="legacy", user_messages=[_PLAIN_MESSAGE])
    with _patched(factory):
        assert resolve_engine_mode(sid) == "monolith"


def test_an_agent_owner_resolves_to_graph(factory):
    """Its first message carries the old opt-out text, and the column still wins."""
    sid = _seed_session(
        factory, deck_mode="agent", user_messages=[_OLD_OPT_OUT_MESSAGE, "turn 2"]
    )
    with _patched(factory):
        assert resolve_engine_mode(sid) == "graph"


def test_an_unchosen_owner_resolves_to_graph(factory):
    """NULL (not chosen yet) runs as agent: the graph is the default."""
    no_turn = _seed_session(factory, deck_mode=None)
    one_turn = _seed_session(factory, deck_mode=None, user_messages=[_PLAIN_MESSAGE])
    with _patched(factory):
        assert resolve_engine_mode(no_turn) == "graph"
        assert resolve_engine_mode(one_turn) == "graph"


def test_a_contributor_resolves_through_its_owners_column(factory):
    """The owner is legacy and the contributor's own row is NULL."""
    owner = _seed_session(factory, deck_mode="legacy")
    contributor = _seed_session(
        factory, deck_mode=None, parent=owner, user_messages=[_PLAIN_MESSAGE]
    )
    assert _row(factory, contributor).deck_mode is None, "precondition"
    with _patched(factory):
        assert resolve_engine_mode(contributor) == "monolith"
        assert resolve_engine_mode(owner) == "monolith"


def test_a_contributors_own_column_never_decides_the_engine(factory):
    """Only the owner's row is read: a value on the contributor's own row (which
    no writer sets) is ignored whether the owner is chosen or not."""
    agent_owner = _seed_session(factory, deck_mode="agent")
    stray_under_agent = _seed_session(factory, deck_mode="legacy", parent=agent_owner)
    unchosen_owner = _seed_session(factory, deck_mode=None)
    stray_under_unchosen = _seed_session(factory, deck_mode="legacy", parent=unchosen_owner)
    with _patched(factory):
        assert resolve_engine_mode(stray_under_agent) == "graph"
        assert resolve_engine_mode(stray_under_unchosen) == "graph"


def test_the_phrase_in_the_first_message_no_longer_selects_legacy(factory):
    sid = _seed_session(
        factory, deck_mode=None, user_messages=[_OLD_OPT_OUT_MESSAGE, "make it blue"]
    )
    with _patched(factory):
        assert resolve_engine_mode(sid) == "graph"


def test_resolution_never_queries_the_transcript(engine, factory):
    """Spec §9: per turn, resolution is a column read on the owner row it already
    loads, not an ordered query over ``session_messages``."""
    owner = _seed_session(factory, deck_mode="legacy", user_messages=[_PLAIN_MESSAGE])
    contributor = _seed_session(
        factory, parent=owner, user_messages=[_OLD_OPT_OUT_MESSAGE]
    )
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with _patched(factory):
            answers = [resolve_engine_mode(contributor), resolve_engine_mode(owner)]
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements, "precondition: resolution read the database"
    assert not [s for s in statements if "session_messages" in s], statements
    assert answers == ["monolith", "monolith"]


# ---------------------------------------------------------------------------
# get_session exposes the OWNER's deck_mode
# ---------------------------------------------------------------------------


def test_get_session_reports_the_owners_deck_mode_for_a_contributor(factory):
    _seed_active_release(factory)
    legacy_owner = _seed_session(factory, deck_mode="legacy")
    contributor = _seed_session(factory, deck_mode=None, parent=legacy_owner)
    agent_owner = _seed_session(factory, deck_mode="agent")
    unchosen_owner = _seed_session(factory, deck_mode=None)
    # A value on a contributor's own row must not leak into its session dict.
    stray = _seed_session(factory, deck_mode="agent", parent=unchosen_owner)

    with _patched(factory):
        manager = SessionManager()
        assert manager.get_session(contributor)["deck_mode"] == "legacy"
        assert manager.get_session(legacy_owner)["deck_mode"] == "legacy"
        assert manager.get_session(agent_owner)["deck_mode"] == "agent"

        unchosen = manager.get_session(unchosen_owner)
        assert "deck_mode" in unchosen and unchosen["deck_mode"] is None
        stray_view = manager.get_session(stray)
        assert "deck_mode" in stray_view and stray_view["deck_mode"] is None


# ---------------------------------------------------------------------------
# create_session(deck_mode=...)
# ---------------------------------------------------------------------------


def test_create_session_stores_deck_mode_and_rejects_unknown_values(factory):
    _seed_active_release(factory)

    with _patched(factory):
        manager = SessionManager()
        agent = manager.create_session(session_id="mode-agent", deck_mode="agent")
        legacy = manager.create_session(session_id="mode-legacy", deck_mode="legacy")
        unchosen = manager.create_session(session_id="mode-none", deck_mode=None)
        omitted = manager.create_session(session_id="mode-omitted")

        for i, bad in enumerate(["monolith", "graph", "Agent", "LEGACY", ""]):
            with pytest.raises(ValueError):
                manager.create_session(session_id=f"mode-bad-{i}", deck_mode=bad)
            assert _row(factory, f"mode-bad-{i}") is None, (
                f"deck_mode={bad!r} was rejected but a session row was still written"
            )

        # The check runs before the idempotent existing-id branch, so a bad
        # value is refused for an id that already exists too.
        with pytest.raises(ValueError):
            manager.create_session(session_id="mode-agent", deck_mode="monolith")

    assert _row(factory, "mode-agent").deck_mode == "agent"
    assert _row(factory, "mode-legacy").deck_mode == "legacy"
    assert _row(factory, "mode-none").deck_mode is None
    assert _row(factory, "mode-omitted").deck_mode is None

    assert agent["deck_mode"] == "agent"
    assert legacy["deck_mode"] == "legacy"
    assert "deck_mode" in unchosen and unchosen["deck_mode"] is None
    assert "deck_mode" in omitted and omitted["deck_mode"] is None


@pytest.mark.parametrize(
    ("deck_mode", "graph_capable", "pinned"),
    [
        ("legacy", True, False),
        ("agent", False, True),
        (None, True, True),
        (None, False, False),
    ],
    ids=[
        "legacy-is-never-pinned",
        "agent-is-always-pinned",
        "unchosen-capable-is-pinned",
        "unchosen-incapable-is-unpinned",
    ],
)
def test_create_session_pin_follows_deck_mode(factory, deck_mode, graph_capable, pinned):
    """One pin rule: legacy is never pinned whatever ``graph_capable`` says, agent
    is always pinned, and an unchosen deck follows ``graph_capable``.  An unpinned
    creation does not lock the active release at all."""
    _seed_active_release(factory)
    sid = f"pin-{uuid.uuid4().hex[:10]}"

    with _patched(factory), patch(_LOCK, wraps=lock_active_graph_release) as lock:
        result = SessionManager().create_session(
            session_id=sid, graph_capable=graph_capable, deck_mode=deck_mode
        )

    row = _row(factory, sid)
    assert row.deck_mode == deck_mode
    assert result["deck_mode"] == deck_mode
    if pinned:
        assert row.graph_release_id == _ACTIVE_RELEASE_ID
        assert result["graph_version"] == _ACTIVE_VERSION
        lock.assert_called_once()
    else:
        assert row.graph_release_id is None
        assert result["graph_version"] is None
        lock.assert_not_called()


def test_create_session_on_an_existing_id_reports_and_keeps_the_stored_mode(factory):
    """The idempotent existing-id branch returns the row's own mode and never
    overwrites it (or its pin) from the argument."""
    _seed_active_release(factory)

    with _patched(factory):
        manager = SessionManager()
        manager.create_session(session_id="kept-legacy", deck_mode="legacy", graph_capable=True)
        manager.create_session(session_id="kept-unchosen", deck_mode=None, graph_capable=False)

        again_legacy = manager.create_session(
            session_id="kept-legacy", deck_mode="agent", graph_capable=True
        )
        again_unchosen = manager.create_session(
            session_id="kept-unchosen", deck_mode="legacy", graph_capable=False
        )

    assert again_legacy["deck_mode"] == "legacy"
    assert "deck_mode" in again_unchosen and again_unchosen["deck_mode"] is None
    legacy_row = _row(factory, "kept-legacy")
    assert (legacy_row.deck_mode, legacy_row.graph_release_id) == ("legacy", None)
    unchosen_row = _row(factory, "kept-unchosen")
    assert (unchosen_row.deck_mode, unchosen_row.graph_release_id) == (None, None)

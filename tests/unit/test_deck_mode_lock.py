"""The atomic first-message lock (spec 2026-10-22 §5.2, §5.3, §5.5; plan Task 3).

``SessionManager.add_user_message`` saves a user message and, when the deck is still
unlocked (owner row ``deck_mode IS NULL``), locks it in the SAME transaction:

- a conditional ``UPDATE … WHERE deck_mode IS NULL`` on the deck OWNER's row writes the
  requested mode (or ``"agent"`` when none is sent);
- locking ``legacy`` clears the pin of the owner and of every contributor session on the
  deck; locking ``agent`` pins an unpinned owner to the locked active Graph Release and
  never moves an existing pin;
- a locked deck that receives a DIFFERENT mode raises ``DeckModeLockedError`` (carrying
  the stored mode) and saves nothing; the same mode, or none, saves the message.

New contributor sessions on a legacy deck are created unpinned.

Fixtures.  Real sqlite with the full schema (``create_all`` + ``_run_migrations``),
driven through a session factory with the APP's settings (``autoflush=False`` and
expire-on-commit, ``src/core/database.py:get_session_local``), so a missing explicit
flush or a return dict built after the commit fails here as it would in production.
Every assertion reads committed rows back through a fresh session.

- The in-memory engine hands every session in a thread ONE connection
  (``SingletonThreadPool``).  That is what lets the commit-failure test see a split
  transaction: a nested ``get_db_session`` that commits, commits the outer's writes too.
- The race tests need two REAL connections, so they use a FILE-backed engine with the
  default pool (pattern: ``file_backed_db`` in ``tests/unit/test_clear_context.py``).
  pysqlite's deferred BEGIN lets the competitor commit while the outer has only read.

Patch targets: ``src.api.services.session_manager.get_db_session`` (and the source
attribute ``src.core.database.get_db_session``, for any lazy import), and
``src.api.services.session_manager.lock_active_graph_release``.

``DeckModeLockedError`` is looked up when a test runs, not imported at module scope, so
that before the implementation lands each test fails on its own rather than the whole
module failing to collect.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import src.api.services.session_manager as session_manager_module
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.core.database import Base, _run_migrations
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionMessage,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.services.conversation_pins import (
    ActiveGraphReleaseUnavailableError,
    lock_active_graph_release,
)
from tests.unit.conftest import _make_fake_db, _make_in_memory_engine

_DB_SOURCE = "src.core.database.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_LOCK = "src.api.services.session_manager.lock_active_graph_release"

#: A closed (superseded) release: a pin to it must never be moved by a lock.
_OLD_RELEASE_ID = 40
_OLD_VERSION = 6
#: The active release a new pin is taken from.
_ACTIVE_RELEASE_ID = 41
_ACTIVE_VERSION = 7

_FIRST_MESSAGE = "Build me a deck about puffins"
_RESULT_KEYS = {"id", "role", "content", "created_at", "deck_mode", "locked_now"}
_LONG_AGO = datetime(2020, 1, 1)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _app_factory(engine):
    """A session factory with the app's settings: no autoflush, expire on commit."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_releases(factory, *, active: bool = True) -> None:
    """Release 40 (v6, closed) and, when *active*, release 41 (v7, the active one)."""
    start = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    db = factory()
    try:
        db.add(
            GraphRelease(
                id=_OLD_RELEASE_ID,
                version_number=_OLD_VERSION,
                release_note="superseded deck-mode lock release",
                published_by="unit-test@example.com",
                published_at=start,
                effective_from=start,
                effective_to=start + timedelta(days=1),
            )
        )
        if active:
            db.add(
                GraphRelease(
                    id=_ACTIVE_RELEASE_ID,
                    version_number=_ACTIVE_VERSION,
                    previous_release_id=_OLD_RELEASE_ID,
                    release_note="active deck-mode lock release",
                    published_by="unit-test@example.com",
                    published_at=start + timedelta(days=1),
                    effective_from=start + timedelta(days=1),
                )
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture
def engine():
    eng = _make_in_memory_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    """The in-memory full schema with releases 40 (closed) and 41 (active)."""
    f = _app_factory(engine)
    _seed_releases(f)
    return f


@pytest.fixture
def file_factory(tmp_path):
    """A FILE-backed engine with the default pool: two sessions, two connections."""
    eng = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )
    Base.metadata.create_all(bind=eng)
    _run_migrations(eng)
    f = _app_factory(eng)
    _seed_releases(f)
    try:
        yield f
    finally:
        eng.dispose()


@contextlib.contextmanager
def _patched(factory):
    """Point every ``get_db_session`` the code under test reaches at *factory*."""
    fake = _make_fake_db(factory)
    with patch(_DB_SOURCE, fake), patch(_MANAGER_DB, fake):
        yield


def _locked_error_class():
    """``DeckModeLockedError`` from the session manager, or an assertion failure."""
    cls = getattr(session_manager_module, "DeckModeLockedError", None)
    assert cls is not None, (
        "DeckModeLockedError is not defined in src.api.services.session_manager"
    )
    assert issubclass(cls, Exception)
    return cls


def _seed_session(
    factory,
    *,
    parent: Optional[str] = None,
    deck_mode: Optional[str] = None,
    pin: Optional[int] = None,
    with_deck: bool = False,
) -> str:
    """One ``UserSession`` (a contributor of *parent* when given) with the exact
    *deck_mode* and *pin* stored, ``last_activity`` far in the past, and optionally an
    owner deck row.  Returns its session id."""
    sid = f"{'contrib' if parent else 'owner'}-{uuid.uuid4().hex[:10]}"
    db = factory()
    try:
        parent_pk = None
        if parent is not None:
            parent_pk = db.scalar(
                select(UserSession.id).where(UserSession.session_id == parent)
            )
            assert parent_pk is not None
        row = UserSession(
            session_id=sid,
            created_by=(
                "owner@example.com" if parent is None else f"{sid}@example.com"
            ),
            parent_session_id=parent_pk,
            deck_mode=deck_mode,
            graph_release_id=pin,
            last_activity=_LONG_AGO,
        )
        db.add(row)
        db.flush()
        if with_deck:
            db.add(
                SessionSlideDeck(
                    session_id=row.id,
                    title="Shared deck",
                    html_content="<div>before</div>",
                    slide_count=0,
                    version=1,
                )
            )
        db.commit()
    finally:
        db.close()
    return sid


def _seed_message(factory, sid: str, *, role: str, content: str, message_type: str) -> None:
    db = factory()
    try:
        pk = db.scalar(select(UserSession.id).where(UserSession.session_id == sid))
        db.add(
            SessionMessage(
                session_id=pk,
                role=role,
                content=content,
                message_type=message_type,
                created_at=_LONG_AGO,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_conversation(factory, sid: str) -> None:
    """One earlier user turn and its reply: the deck has been talked to."""
    _seed_message(factory, sid, role="user", content="an earlier turn", message_type="user_input")
    _seed_message(factory, sid, role="assistant", content="a reply", message_type="llm_response")


def _modes_and_pins(factory, *sids: str) -> list[tuple[Optional[str], Optional[int]]]:
    """Committed ``(deck_mode, graph_release_id)`` of each session, in order."""
    db = factory()
    try:
        out = []
        for sid in sids:
            row = db.execute(
                select(UserSession.deck_mode, UserSession.graph_release_id).where(
                    UserSession.session_id == sid
                )
            ).one()
            out.append((row.deck_mode, row.graph_release_id))
        return out
    finally:
        db.close()


def _pins(factory, *sids: str) -> list[Optional[int]]:
    return [pin for _mode, pin in _modes_and_pins(factory, *sids)]


def _deck_mode(factory, sid: str) -> Optional[str]:
    return _modes_and_pins(factory, sid)[0][0]


def _last_activity(factory, sid: str) -> datetime:
    db = factory()
    try:
        return db.scalar(
            select(UserSession.last_activity).where(UserSession.session_id == sid)
        )
    finally:
        db.close()


def _messages(factory) -> list[tuple]:
    """Every committed message as ``(id, session_id, role, content, message_type,
    request_id)``, oldest row first."""
    db = factory()
    try:
        rows = db.execute(
            select(
                SessionMessage.id,
                UserSession.session_id,
                SessionMessage.role,
                SessionMessage.content,
                SessionMessage.message_type,
                SessionMessage.request_id,
            )
            .join(UserSession, UserSession.id == SessionMessage.session_id)
            .order_by(SessionMessage.id)
        ).all()
        return [tuple(r) for r in rows]
    finally:
        db.close()


def _events(factory) -> list[tuple]:
    """Every ``SharedDeckMutationEvent`` as ``(actor session_id, operation,
    graph_release_id, graph_version)``, oldest first."""
    db = factory()
    try:
        rows = db.execute(
            select(
                UserSession.session_id,
                SharedDeckMutationEvent.operation,
                SharedDeckMutationEvent.graph_release_id,
                SharedDeckMutationEvent.graph_version,
            )
            .join(UserSession, UserSession.id == SharedDeckMutationEvent.actor_session_id)
            .order_by(SharedDeckMutationEvent.id)
        ).all()
        return [tuple(r) for r in rows]
    finally:
        db.close()


def _deck_state(factory, owner_sid: str) -> tuple:
    db = factory()
    try:
        return tuple(
            db.execute(
                select(
                    SessionSlideDeck.title,
                    SessionSlideDeck.html_content,
                    SessionSlideDeck.version,
                )
                .join(UserSession, UserSession.id == SessionSlideDeck.session_id)
                .where(UserSession.session_id == owner_sid)
            ).one()
        )
    finally:
        db.close()


def _assert_message_result(
    result, *, content: str, deck_mode: str, locked_now: bool, factory
) -> None:
    """The return dict: ``add_message``'s keys plus ``deck_mode`` / ``locked_now``,
    describing the row that was actually committed."""
    assert set(result) == _RESULT_KEYS
    assert result["role"] == "user"
    assert result["content"] == content
    assert result["deck_mode"] == deck_mode
    assert result["locked_now"] is locked_now
    assert isinstance(result["created_at"], str)
    datetime.fromisoformat(result["created_at"])
    committed_ids = [m[0] for m in _messages(factory) if m[3] == content]
    assert committed_ids == [result["id"]]


# ---------------------------------------------------------------------------
# Locking an unlocked deck
# ---------------------------------------------------------------------------


def test_first_message_with_legacy_locks_legacy_and_clears_every_pin_on_the_deck(factory):
    """The owner and two contributors are pinned (one to a superseded release).  The
    legacy lock writes the owner's column and clears all three pins, and only this
    deck's: another pinned deck and its contributor are untouched."""
    owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID)
    c1 = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)
    c2 = _seed_session(factory, parent=owner, pin=_OLD_RELEASE_ID)
    other_owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID)
    other_contributor = _seed_session(factory, parent=other_owner, pin=_OLD_RELEASE_ID)

    with _patched(factory):
        result = SessionManager().add_user_message(
            owner,
            _FIRST_MESSAGE,
            message_type="user_input",
            request_id="req-legacy-1",
            requested_deck_mode="legacy",
        )

    _assert_message_result(
        result, content=_FIRST_MESSAGE, deck_mode="legacy", locked_now=True, factory=factory
    )
    assert _modes_and_pins(factory, owner, c1, c2) == [
        ("legacy", None),
        (None, None),  # the lock lives on the owner's row only
        (None, None),
    ]
    assert _modes_and_pins(factory, other_owner, other_contributor) == [
        (None, _ACTIVE_RELEASE_ID),
        (None, _OLD_RELEASE_ID),
    ]
    assert [m[1:] for m in _messages(factory)] == [
        (owner, "user", _FIRST_MESSAGE, "user_input", "req-legacy-1")
    ]


@pytest.mark.parametrize(
    "mode_kwargs", [{}, {"requested_deck_mode": None}], ids=["omitted", "explicit-none"]
)
def test_first_message_with_no_mode_locks_agent(factory, mode_kwargs):
    """Older clients and non-UI callers send no mode: the deck locks ``agent``.  The
    owner is pinned to a SUPERSEDED release, and an agent lock never moves a pin."""
    owner = _seed_session(factory, pin=_OLD_RELEASE_ID)
    contributor = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)

    with _patched(factory):
        result = SessionManager().add_user_message(
            owner, _FIRST_MESSAGE, message_type="user_input", **mode_kwargs
        )

    _assert_message_result(
        result, content=_FIRST_MESSAGE, deck_mode="agent", locked_now=True, factory=factory
    )
    assert _modes_and_pins(factory, owner, contributor) == [
        ("agent", _OLD_RELEASE_ID),
        (None, _ACTIVE_RELEASE_ID),
    ]
    assert [m[1:4] for m in _messages(factory)] == [(owner, "user", _FIRST_MESSAGE)]


@pytest.mark.parametrize("requested", ["agent", None], ids=["agent", "no-mode"])
def test_first_message_with_agent_pins_an_unpinned_owner(factory, requested):
    """A deck created unpinned (e.g. by an old client) that locks ``agent`` gets the
    owner pinned, in the lock's transaction, through the release LOCK (the plain
    SELECT is not enough on Postgres).  A contributor's existing pin is untouched."""
    owner = _seed_session(factory, pin=None)
    contributor = _seed_session(factory, parent=owner, pin=_OLD_RELEASE_ID)

    with _patched(factory), patch(_LOCK, wraps=lock_active_graph_release) as lock:
        result = SessionManager().add_user_message(
            owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=requested
        )

    _assert_message_result(
        result, content=_FIRST_MESSAGE, deck_mode="agent", locked_now=True, factory=factory
    )
    assert _modes_and_pins(factory, owner, contributor) == [
        ("agent", _ACTIVE_RELEASE_ID),
        (None, _OLD_RELEASE_ID),
    ]
    assert lock.call_count == 1


@pytest.mark.parametrize(
    "mode, owner_pin, expected",
    [
        # legacy: owner, the caller and the other contributor all end unpinned.
        ("legacy", _ACTIVE_RELEASE_ID, [("legacy", None), (None, None), (None, None)]),
        # agent: the unpinned OWNER is pinned; contributors keep their pins.
        (
            "agent",
            None,
            [("agent", _ACTIVE_RELEASE_ID), (None, _ACTIVE_RELEASE_ID), (None, _OLD_RELEASE_ID)],
        ),
    ],
    ids=["legacy", "agent"],
)
def test_a_contributors_first_message_locks_the_owners_deck(factory, mode, owner_pin, expected):
    """The lock is deck-wide: a contributor's first message writes the OWNER's column
    (its own row stays NULL), changes the pins of the whole deck, and the message is
    saved on the contributor's own session."""
    owner = _seed_session(factory, pin=owner_pin)
    caller = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)
    other = _seed_session(factory, parent=owner, pin=_OLD_RELEASE_ID)

    with _patched(factory):
        result = SessionManager().add_user_message(
            caller, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=mode
        )

    _assert_message_result(
        result, content=_FIRST_MESSAGE, deck_mode=mode, locked_now=True, factory=factory
    )
    assert _modes_and_pins(factory, owner, caller, other) == expected
    assert [m[1:4] for m in _messages(factory)] == [(caller, "user", _FIRST_MESSAGE)]


# ---------------------------------------------------------------------------
# A locked deck
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("second_caller", ["owner", "contributor"])
@pytest.mark.parametrize(
    "first, second",
    [("agent", "legacy"), ("legacy", "agent")],
    ids=["agent-then-legacy", "legacy-then-agent"],
)
def test_a_different_mode_on_a_locked_deck_raises_and_saves_nothing(
    factory, first, second, second_caller
):
    """The deck is locked by a real first message; a later message carrying the other
    mode raises ``DeckModeLockedError`` with the STORED mode and leaves the transcript,
    the column, the pins and the activity stamps exactly as they were."""
    locked_error = _locked_error_class()
    owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID)
    contributor = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)
    manager = SessionManager()

    with _patched(factory):
        manager.add_user_message(
            owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=first
        )
        before_rows = _modes_and_pins(factory, owner, contributor)
        before_activity = [_last_activity(factory, s) for s in (owner, contributor)]
        before_messages = _messages(factory)
        caller = owner if second_caller == "owner" else contributor

        with pytest.raises(locked_error) as exc_info:
            manager.add_user_message(
                caller, "now switch modes", message_type="user_input", requested_deck_mode=second
            )

    assert exc_info.value.deck_mode == first
    assert _messages(factory) == before_messages
    assert _modes_and_pins(factory, owner, contributor) == before_rows
    assert before_rows[0][0] == first
    assert [_last_activity(factory, s) for s in (owner, contributor)] == before_activity


@pytest.mark.parametrize("caller_role", ["owner", "contributor"])
@pytest.mark.parametrize("requested", ["same", None], ids=["same-mode", "no-mode"])
@pytest.mark.parametrize(
    "stored, owner_pin, contributor_pin",
    [
        ("agent", _OLD_RELEASE_ID, _ACTIVE_RELEASE_ID),
        ("legacy", None, None),
        # A deck that existed before Deck Mode: the migration marked it legacy and
        # left its pins.  Pins change only in the LOCKING transaction, so a later
        # message must not clear them.
        ("legacy", _ACTIVE_RELEASE_ID, _ACTIVE_RELEASE_ID),
    ],
    ids=["agent", "legacy-unpinned", "legacy-premigration-pinned"],
)
def test_the_same_mode_or_no_mode_on_a_locked_deck_saves_the_message(
    factory, stored, owner_pin, contributor_pin, requested, caller_role
):
    """The same mode, or none, on a locked deck proceeds: the message is saved on the
    caller's session (whose activity is bumped), ``locked_now`` is False, the reported
    mode is the stored one, and neither the column nor any pin moves."""
    owner = _seed_session(factory, deck_mode=stored, pin=owner_pin)
    contributor = _seed_session(factory, parent=owner, pin=contributor_pin)
    _seed_conversation(factory, owner)
    caller = owner if caller_role == "owner" else contributor
    before_messages = _messages(factory)

    with _patched(factory):
        result = SessionManager().add_user_message(
            caller,
            "make slide 3 shorter",
            message_type="user_input",
            request_id="req-later",
            requested_deck_mode=stored if requested == "same" else None,
        )

    _assert_message_result(
        result, content="make slide 3 shorter", deck_mode=stored, locked_now=False, factory=factory
    )
    assert _modes_and_pins(factory, owner, contributor) == [
        (stored, owner_pin),
        (None, contributor_pin),
    ]
    after = _messages(factory)
    assert after[:-1] == before_messages
    assert after[-1][1:] == (caller, "user", "make slide 3 shorter", "user_input", "req-later")
    assert _last_activity(factory, caller) > _LONG_AGO


@pytest.mark.parametrize(
    "stored, requested, owner_pin",
    [("agent", "legacy", _ACTIVE_RELEASE_ID), ("legacy", "agent", None)],
    ids=["agent-deck", "legacy-deck"],
)
def test_a_lock_already_set_before_the_call_is_honoured(factory, stored, requested, owner_pin):
    """A deck locked with NO message ever sent (a pre-existing empty deck the migration
    marked legacy, or a duplicate locked at creation) is locked: the first message
    with the other mode raises, and nothing is written."""
    locked_error = _locked_error_class()
    owner = _seed_session(factory, deck_mode=stored, pin=owner_pin)
    contributor = _seed_session(factory, parent=owner, pin=owner_pin)

    with _patched(factory):
        with pytest.raises(locked_error) as exc_info:
            SessionManager().add_user_message(
                owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=requested
            )

    assert exc_info.value.deck_mode == stored
    assert _messages(factory) == []
    assert _modes_and_pins(factory, owner, contributor) == [
        (stored, owner_pin),
        (None, owner_pin),
    ]


# ---------------------------------------------------------------------------
# The race (spec §12): two first messages on one unlocked deck
# ---------------------------------------------------------------------------


def _interleave_competitor(manager, competitor_sid: str, competitor_mode: Optional[str]):
    """Wrap ``_get_deck_owner_session`` so that, on its FIRST call only and after it
    has returned the still-unlocked owner, a complete competing ``add_user_message``
    runs and commits in its own ``get_db_session`` (on its own connection).  The guard
    keeps the competitor's own call from recursing."""
    real = SessionManager._get_deck_owner_session
    state = {"calls": 0, "owner_mode_seen": "not-called", "competitor": None}

    def interleaved(self, *args, **kwargs):
        owner_row = real(self, *args, **kwargs)
        state["calls"] += 1
        if state["calls"] == 1:
            state["owner_mode_seen"] = owner_row.deck_mode
            state["competitor"] = manager.add_user_message(
                competitor_sid,
                "the competitor's first message",
                message_type="user_input",
                requested_deck_mode=competitor_mode,
            )
        return owner_row

    return patch.object(SessionManager, "_get_deck_owner_session", interleaved), state


def test_two_first_messages_interleaved_exactly_one_mode_wins(file_factory):
    """Owner sends ``legacy`` while a contributor's ``agent`` first message commits in
    between the owner row's read and the conditional UPDATE.  The UPDATE matches no
    row, so the outer call must RE-READ the column (the identity map is not to be
    trusted: SQLAlchemy writes the loser's own value into it) and refuse with the
    winner's mode.  Removing the refresh turns this red.

    The true concurrent race needs Postgres; this deterministic interleaving is the
    local proof, and the concurrent one is recorded as not run."""
    locked_error = _locked_error_class()
    f = file_factory
    owner = _seed_session(f, pin=None)
    contributor = _seed_session(f, parent=owner, pin=_ACTIVE_RELEASE_ID)
    manager = SessionManager()
    interleave, state = _interleave_competitor(manager, contributor, "agent")

    with _patched(f), interleave:
        with pytest.raises(locked_error) as exc_info:
            manager.add_user_message(
                owner, "the owner's first message", message_type="user_input",
                requested_deck_mode="legacy",
            )

    assert state["owner_mode_seen"] is None, (
        "the outer call must read the owner before the competitor"
    )
    assert state["competitor"] is not None
    assert state["competitor"]["deck_mode"] == "agent"
    assert state["competitor"]["locked_now"] is True
    assert exc_info.value.deck_mode == "agent"
    # Exactly one mode won, and only the winner's message exists.
    assert _modes_and_pins(f, owner, contributor) == [
        ("agent", _ACTIVE_RELEASE_ID),  # the winner pinned the unpinned owner
        (None, _ACTIVE_RELEASE_ID),
    ]
    assert [m[1:4] for m in _messages(f) if m[2] == "user"] == [
        (contributor, "user", "the competitor's first message")
    ]


@pytest.mark.parametrize("loser_mode", [None, "legacy"], ids=["no-mode", "same-mode"])
def test_a_first_message_that_loses_the_race_to_its_own_mode_proceeds(file_factory, loser_mode):
    """The spec §12 race row's other half: the loser PROCEEDS when it sent the winner's
    mode or none.  A contributor locks ``legacy`` between the owner's read and the
    owner's conditional UPDATE.  The owner's message is saved, reported on the deck's
    real mode (``legacy``, read back after the lost UPDATE, not the ``agent`` a
    mode-less call would have chosen), ``locked_now`` is False, and the winner's
    cleared pins stay cleared."""
    f = file_factory
    owner = _seed_session(f, pin=_ACTIVE_RELEASE_ID)
    contributor = _seed_session(f, parent=owner, pin=_ACTIVE_RELEASE_ID)
    manager = SessionManager()
    interleave, state = _interleave_competitor(manager, contributor, "legacy")

    with _patched(f), interleave:
        result = manager.add_user_message(
            owner, "the owner's first message", message_type="user_input",
            requested_deck_mode=loser_mode,
        )

    assert state["owner_mode_seen"] is None, (
        "the outer call must read the owner before the competitor"
    )
    assert state["competitor"]["deck_mode"] == "legacy"
    assert state["competitor"]["locked_now"] is True
    _assert_message_result(
        result, content="the owner's first message", deck_mode="legacy", locked_now=False, factory=f
    )
    assert _modes_and_pins(f, owner, contributor) == [("legacy", None), (None, None)]
    assert sorted(m[1:4] for m in _messages(f)) == sorted(
        [
            (contributor, "user", "the competitor's first message"),
            (owner, "user", "the owner's first message"),
        ]
    )


# ---------------------------------------------------------------------------
# One transaction: a failure anywhere leaves nothing behind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode, owner_pin", [("legacy", _ACTIVE_RELEASE_ID), ("agent", None)], ids=["legacy", "agent"]
)
def test_a_failed_message_insert_rolls_back_the_lock_and_the_pins(factory, mode, owner_pin):
    """``_insert_user_message`` raising leaves the deck unlocked with every pin as it
    was, and saves no message.  The insert is reached once, for the CALLER's session,
    as a user message."""
    owner = _seed_session(factory, pin=owner_pin)
    contributor = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)
    seen = []

    def failing_insert(self, db, session, **kwargs):
        seen.append((session.session_id, kwargs["role"], kwargs["content"], kwargs["message_type"]))
        raise RuntimeError("insert failed")

    with _patched(factory), patch.object(
        SessionManager, "_insert_user_message", autospec=True, side_effect=failing_insert
    ):
        with pytest.raises(RuntimeError, match="insert failed"):
            SessionManager().add_user_message(
                contributor, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=mode
            )

    assert seen == [(contributor, "user", _FIRST_MESSAGE, "user_input")]
    assert _modes_and_pins(factory, owner, contributor) == [
        (None, owner_pin),
        (None, _ACTIVE_RELEASE_ID),
    ]
    assert _messages(factory) == []


def _counting_db(factory):
    """A working ``get_db_session`` that counts how many times it is entered."""
    inner = _make_fake_db(factory)
    count = {"opened": 0}

    @contextlib.contextmanager
    def counting_get_db_session():
        count["opened"] += 1
        with inner() as db:
            yield db

    return counting_get_db_session, count


def test_add_user_message_opens_exactly_one_database_session(factory):
    """Structural proof of ONE transaction per call: locking, proceeding and refusing
    each open exactly one ``get_db_session``.  A call that reuses ``add_message`` (its
    own transaction) or locks and inserts in separate blocks opens two."""
    locked_error = _locked_error_class()
    agent_owner = _seed_session(factory, pin=None)
    agent_contributor = _seed_session(factory, parent=agent_owner, pin=_ACTIVE_RELEASE_ID)
    legacy_owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID)
    counting, count = _counting_db(factory)
    manager = SessionManager()

    with patch(_MANAGER_DB, counting), patch(_DB_SOURCE, counting):
        manager.add_user_message(
            agent_owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode="agent"
        )
        assert count["opened"] == 1, "an agent lock (with its owner pin) is one transaction"

        manager.add_user_message(
            legacy_owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode="legacy"
        )
        assert count["opened"] == 2, "a legacy lock (with its pin clear) is one transaction"

        manager.add_user_message(agent_contributor, "a later turn", message_type="user_input")
        assert count["opened"] == 3, "a message on a locked deck is one transaction"

        with pytest.raises(locked_error):
            manager.add_user_message(
                agent_contributor, "switch", message_type="user_input", requested_deck_mode="legacy"
            )
        assert count["opened"] == 4, "a refusal is one transaction"

    # The calls really did their work through that one session each.
    assert _deck_mode(factory, agent_owner) == "agent"
    assert _deck_mode(factory, legacy_owner) == "legacy"
    assert len([m for m in _messages(factory) if m[2] == "user"]) == 3


def _nth_commit_fails(factory, n: int):
    """A ``get_db_session`` whose *n*-th commit, counted in the order the commits
    happen (i.e. the order the blocks exit), fails: that block is rolled back and
    ``RuntimeError("commit failed")`` is raised, which is what a lost commit looks
    like to the caller (pattern: ``_failing_commit_db``,
    ``tests/unit/test_clear_context.py``).  Every other block commits normally, and a
    block whose body raises is rolled back with its exception propagating."""
    state = {"commits": 0}

    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        else:
            state["commits"] += 1
            if state["commits"] == n:
                db.rollback()
                raise RuntimeError("commit failed")
            db.commit()
        finally:
            db.close()

    return fake_get_db_session


@pytest.mark.parametrize(
    "failing_commit", [1, 2], ids=["first-commit-fails", "second-commit-fails"]
)
@pytest.mark.parametrize(
    "mode, owner_pin, locked_pins",
    [
        ("legacy", _ACTIVE_RELEASE_ID, [None, None]),
        ("agent", None, [_ACTIVE_RELEASE_ID, _OLD_RELEASE_ID]),
    ],
    ids=["legacy", "agent"],
)
def test_the_lock_the_pins_and_the_message_commit_together(
    factory, mode, owner_pin, locked_pins, failing_commit
):
    """All or nothing, whichever commit fails (spec §5.2: "All of it commits, or none
    of it does"; §12: a failed first-message save leaves the deck unlocked with its
    pins unchanged).

    An atomic call makes exactly one commit.  Failing it (``first-commit-fails``)
    must raise and leave the deck unlocked, the pins as they were and no message;
    there is no second commit to fail, so ``second-commit-fails`` must leave all of
    it committed.  A split call makes two commits: a nested ``add_message`` commits
    first (on the in-memory engine's one connection, taking the outer's lock and
    pin writes with it), and locking and inserting in two blocks commits the lock
    first, so failing the SECOND commit leaves a locked deck behind."""
    owner = _seed_session(factory, pin=owner_pin)
    contributor = _seed_session(factory, parent=owner, pin=_OLD_RELEASE_ID)
    fake = _nth_commit_fails(factory, failing_commit)

    raised = None
    with patch(_MANAGER_DB, fake), patch(_DB_SOURCE, fake):
        try:
            SessionManager().add_user_message(
                owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=mode
            )
        except RuntimeError as exc:
            raised = exc

    if failing_commit == 1:
        assert raised is not None and str(raised) == "commit failed"

    deck = (
        _deck_mode(factory, owner),
        _pins(factory, owner, contributor),
        [m[1:4] for m in _messages(factory)],
    )
    if raised is not None:
        assert deck == (None, [owner_pin, _OLD_RELEASE_ID], []), "a failed call left writes behind"
    else:
        assert deck == (mode, locked_pins, [(owner, "user", _FIRST_MESSAGE)])


def test_an_agent_lock_with_no_active_release_raises_and_leaves_the_deck_unlocked(engine):
    """Pinning the unpinned owner needs the active release.  When there is none,
    ``ActiveGraphReleaseUnavailableError`` propagates (the routes answer 503) and the
    conditional UPDATE is rolled back with everything else."""
    f = _app_factory(engine)
    _seed_releases(f, active=False)
    owner = _seed_session(f, pin=None)

    with _patched(f):
        with pytest.raises(ActiveGraphReleaseUnavailableError):
            SessionManager().add_user_message(
                owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode="agent"
            )

    assert _modes_and_pins(f, owner) == [(None, None)]
    assert _messages(f) == []


def test_a_legacy_lock_needs_no_active_release(engine):
    """A legacy deck never uses a Graph Release, so locking one must not depend on an
    active release being available."""
    f = _app_factory(engine)
    _seed_releases(f, active=False)
    owner = _seed_session(f, pin=_OLD_RELEASE_ID)
    contributor = _seed_session(f, parent=owner, pin=_OLD_RELEASE_ID)

    with _patched(f):
        result = SessionManager().add_user_message(
            owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode="legacy"
        )

    _assert_message_result(
        result, content=_FIRST_MESSAGE, deck_mode="legacy", locked_now=True, factory=f
    )
    assert _modes_and_pins(f, owner, contributor) == [("legacy", None), (None, None)]


# ---------------------------------------------------------------------------
# Bad input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["monolith", "graph", "Agent", "LEGACY", ""])
def test_an_unknown_requested_mode_raises_value_error_and_writes_nothing(factory, bad):
    """There is no DB CHECK, so a stray value would be stored forever (and resolve as
    graph).  It is refused with ``ValueError`` before any write, on an unlocked deck
    and on a locked one alike (not as a lock conflict)."""
    locked_error = _locked_error_class()
    unlocked = _seed_session(factory, pin=_ACTIVE_RELEASE_ID)
    locked = _seed_session(factory, deck_mode="agent", pin=_ACTIVE_RELEASE_ID)
    manager = SessionManager()

    with _patched(factory):
        for sid in (unlocked, locked):
            with pytest.raises(ValueError) as exc_info:
                manager.add_user_message(
                    sid, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode=bad
                )
            assert not isinstance(exc_info.value, locked_error)

    assert _modes_and_pins(factory, unlocked, locked) == [
        (None, _ACTIVE_RELEASE_ID),
        ("agent", _ACTIVE_RELEASE_ID),
    ]
    assert _messages(factory) == []


def test_add_user_message_on_a_missing_session_raises_and_writes_nothing(factory):
    owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID)

    with _patched(factory):
        with pytest.raises(SessionNotFoundError):
            SessionManager().add_user_message(
                "no-such-session", _FIRST_MESSAGE, message_type="user_input",
                requested_deck_mode="legacy",
            )

    assert _modes_and_pins(factory, owner) == [(None, _ACTIVE_RELEASE_ID)]
    assert _messages(factory) == []


# ---------------------------------------------------------------------------
# Pins after the lock: contributors and mutation provenance (spec §5.5)
# ---------------------------------------------------------------------------


def test_a_new_contributor_on_a_legacy_deck_is_unpinned(factory):
    """A contributor session created on a legacy deck gets no pin, without locking a
    release it will never use; its own ``deck_mode`` stays NULL."""
    owner = _seed_session(factory, deck_mode="legacy", pin=None)

    with _patched(factory), patch(_LOCK, wraps=lock_active_graph_release) as lock:
        result = SessionManager().get_or_create_contributor_session(
            owner, "new-contributor@example.com"
        )

    assert _modes_and_pins(factory, result["session_id"]) == [(None, None)]
    lock.assert_not_called()


@pytest.mark.parametrize("owner_mode", [None, "agent"], ids=["unlocked", "agent"])
def test_a_new_contributor_on_an_unlocked_deck_is_pinned(factory, owner_mode):
    """On an unlocked deck (which may still lock agent) and on an agent deck, a new
    contributor is pinned to the locked active release, as today."""
    owner = _seed_session(factory, deck_mode=owner_mode, pin=_OLD_RELEASE_ID)

    with _patched(factory), patch(_LOCK, wraps=lock_active_graph_release) as lock:
        result = SessionManager().get_or_create_contributor_session(
            owner, "new-contributor@example.com"
        )

    assert _modes_and_pins(factory, result["session_id"]) == [(None, _ACTIVE_RELEASE_ID)]
    assert lock.call_count == 1


def test_legacy_deck_mutation_provenance_records_no_graph_version(factory):
    """After a legacy lock, a deck write through the production path
    (``save_slide_deck`` with a ``deck_mutation_context`` snapshot) by the owner and by
    a contributor records ``SharedDeckMutationEvent`` rows with no Graph Release and
    no Graph Version, so "Who changed this deck" never credits a legacy edit to a
    graph version."""
    owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID, with_deck=True)
    contributor = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)
    manager = SessionManager()

    with _patched(factory):
        manager.add_user_message(
            owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode="legacy"
        )
        for sid in (owner, contributor):
            manager.save_slide_deck(
                sid,
                "t",
                "<div></div>",
                slide_count=0,
                mutation=manager.deck_mutation_context(
                    sid, operation="save_deck", object_type="deck"
                ),
            )

    assert _events(factory) == [
        (owner, "save_deck", None, None),
        (contributor, "save_deck", None, None),
    ]


@pytest.mark.parametrize("actor_role", ["owner", "contributor"])
def test_a_mutation_snapshot_taken_before_a_legacy_lock_is_rejected(factory, actor_role):
    """A deck write must not straddle the lock (spec §5.5).  A ``deck_mutation_context``
    taken on the unlocked, pinned deck snapshots the pin; the legacy lock then clears
    it; the write with the stale snapshot is refused cleanly and the deck and its
    event log are unchanged."""
    owner = _seed_session(factory, pin=_ACTIVE_RELEASE_ID, with_deck=True)
    contributor = _seed_session(factory, parent=owner, pin=_ACTIVE_RELEASE_ID)
    actor = owner if actor_role == "owner" else contributor
    manager = SessionManager()

    with _patched(factory):
        stale = manager.deck_mutation_context(actor, operation="save_deck", object_type="deck")
        assert stale.actor.graph_release_id == _ACTIVE_RELEASE_ID

        manager.add_user_message(
            owner, _FIRST_MESSAGE, message_type="user_input", requested_deck_mode="legacy"
        )
        assert _pins(factory, owner, contributor) == [None, None]
        before_deck = _deck_state(factory, owner)

        with pytest.raises(
            ValueError, match="mutation actor pin does not match its persisted pin"
        ):
            manager.save_slide_deck(
                actor, "after", "<div>after</div>", slide_count=0, mutation=stale
            )

    assert before_deck == ("Shared deck", "<div>before</div>", 1)
    assert _deck_state(factory, owner) == before_deck
    assert _events(factory) == []

"""Contributor creation racing the Deck Mode lock, on real PostgreSQL (spec 2026-10-22 §5.5).

Invariant: no session on a legacy deck has a pin.  ``get_or_create_contributor_session``
pins a new contributor unless the parent is ``legacy``; ``add_user_message``'s legacy
lock clears the pins of the owner and of every contributor it can see.  Without a
row lock, a legacy lock committing while a contributor creation sits between its
read of the parent and its insert leaves a PINNED contributor on a legacy deck (the
lock's pin clear cannot see the uncommitted row, and the creation read NULL).

The fix re-reads the parent's ``deck_mode`` ``FOR SHARE`` before taking the release
lock.  ``FOR SHARE`` conflicts with the lock's ``UPDATE`` of the owner row, so the
two serialise in either order, with lock order parent -> release (the same as the
agent lock's).  These tests prove both orders and that the agent path does not
deadlock.

SQLite renders no ``FOR SHARE``, so this can only be proven here.  Each test uses two
real connections (``postgres_engine``'s QueuePool) on two threads, and a gate that
holds one transaction open at a chosen point.  Self-skips with no PostgreSQL.
"""

from __future__ import annotations

import contextlib
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import src.api.services.session_manager as session_manager_module
from src.api.services.session_manager import DeckModeLockedError, SessionManager
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, UserSession
from tests.integration.postgres_concurrency_helpers import _WAIT_SECONDS, _lock_waiters

pytestmark = pytest.mark.postgres

_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_DB_SOURCE = "src.core.database.get_db_session"
_LOCK = "src.api.services.session_manager.lock_active_graph_release"
_OWNER = "race-owner"
_LATE_CONTRIBUTOR = "late-contributor@example.com"


def _database_context(factory):
    """``get_db_session``: one session (one pooled connection) per block."""

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


def _seed(postgres_engine, *, owner_mode: Optional[str], owner_pinned: bool):
    """The app's session settings (autoflush off, expire on commit), one active
    release, and an owner deck.  Returns ``(factory, active_release_id)``."""
    factory = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        release = GraphRelease(
            version_number=1,
            release_note="deck-mode contributor race R1",
            published_by="deck-mode-race@example.com",
            published_at=now,
            effective_from=now,
        )
        db.add(release)
        db.flush()
        release_id = release.id
        db.add(
            UserSession(
                session_id=_OWNER,
                created_by="owner@example.com",
                deck_mode=owner_mode,
                graph_release_id=release_id if owner_pinned else None,
            )
        )
    return factory, release_id


def _mode_and_pin(factory, session_id: str):
    with factory() as db:
        row = db.execute(
            select(UserSession.deck_mode, UserSession.graph_release_id).where(
                UserSession.session_id == session_id
            )
        ).one()
        return (row.deck_mode, row.graph_release_id)


class _Gate:
    """Holds one named thread's transaction open at a chosen point."""

    def __init__(self, thread_name: str) -> None:
        self.thread_name = thread_name
        self.reached = threading.Event()
        self.release = threading.Event()

    def pause_here(self) -> None:
        if threading.current_thread().name == self.thread_name:
            self.reached.set()
            assert self.release.wait(timeout=_WAIT_SECONDS), "gate was never released"


def _release_lock_then(gate: _Gate, calls: list):
    """``lock_active_graph_release`` that records the calling thread and, for the gated
    thread, pauses AFTER taking the release lock: the creation is then between its
    read of the parent and its insert, holding every lock it takes before the pin."""
    real = session_manager_module.lock_active_graph_release

    def gated(db):
        calls.append(threading.current_thread().name)
        pinned = real(db)
        gate.pause_here()
        return pinned

    return gated


def _insert_then(gate: _Gate):
    """``_insert_user_message`` that pauses the gated thread BEFORE inserting: the lock's
    UPDATE and pin change have run and are uncommitted."""
    real = SessionManager._insert_user_message

    def gated(self, db, session, **kwargs):
        gate.pause_here()
        return real(self, db, session, **kwargs)

    return gated


def _waits_on_a_lock(engine, future: Future) -> bool:
    """True once a backend on this database waits on a row lock while *future* is still
    running; False if *future* finishes first (it never had to wait)."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if future.done():
            return False
        if _lock_waiters(engine) >= 1:
            return True
        time.sleep(0.02)
    raise AssertionError("neither finished nor waited on a lock within the deadline")


def _create_contributor(manager: SessionManager):
    threading.current_thread().name = "contributor"
    return manager.get_or_create_contributor_session(_OWNER, _LATE_CONTRIBUTOR)


def _first_message(manager: SessionManager, mode: str):
    threading.current_thread().name = "locker"
    return manager.add_user_message(
        _OWNER, "the deck's first message", message_type="user_input",
        requested_deck_mode=mode,
    )


def test_a_legacy_lock_arriving_mid_contributor_creation_waits_and_clears_its_pin(
    postgres_engine,
):
    """The contributor creation has read the parent (NULL) and locked the release; a
    legacy first message arrives.  The lock's UPDATE must wait for the creation's
    FOR SHARE, so its pin clear runs after the contributor committed and clears it.
    Without the row lock the legacy lock commits first and the contributor is
    inserted pinned on a legacy deck."""
    factory, _release_id = _seed(postgres_engine, owner_mode=None, owner_pinned=True)
    manager = SessionManager()
    gate = _Gate("contributor")
    calls: list = []
    db_context = _database_context(factory)

    with patch(_MANAGER_DB, db_context), patch(_DB_SOURCE, db_context), patch(
        _LOCK, _release_lock_then(gate, calls)
    ), ThreadPoolExecutor(max_workers=2) as pool:
        try:
            contributor = pool.submit(_create_contributor, manager)
            assert gate.reached.wait(timeout=_WAIT_SECONDS), "contributor never reached its pin"
            locker = pool.submit(_first_message, manager, "legacy")
            locker_waited = _waits_on_a_lock(postgres_engine, locker)
        finally:
            gate.release.set()
        created = contributor.result(timeout=_WAIT_SECONDS)
        locked = locker.result(timeout=_WAIT_SECONDS)

    assert (locked["deck_mode"], locked["locked_now"]) == ("legacy", True)
    assert _mode_and_pin(factory, _OWNER) == ("legacy", None)
    assert _mode_and_pin(factory, created["session_id"]) == (None, None), (
        "a contributor created alongside a legacy lock kept its pin on a legacy deck"
    )
    assert locker_waited, "the legacy lock did not wait for the contributor's row lock"
    assert calls == ["contributor"]  # the pin was taken (then cleared by the lock)


def test_a_contributor_created_while_a_legacy_lock_is_uncommitted_reads_legacy(
    postgres_engine,
):
    """The other order: the legacy lock has updated the owner row and cleared the pins
    but not committed when a contributor is created.  The creation's FOR SHARE waits
    for the lock's commit, reads ``legacy`` and creates an UNPINNED contributor without
    touching the release lock.  Without the row lock it reads NULL, pins, and commits
    a row the lock's pin clear never saw."""
    factory, _release_id = _seed(postgres_engine, owner_mode=None, owner_pinned=True)
    manager = SessionManager()
    gate = _Gate("locker")
    calls: list = []
    db_context = _database_context(factory)
    no_gate = _Gate("nobody")

    with patch(_MANAGER_DB, db_context), patch(_DB_SOURCE, db_context), patch(
        _LOCK, _release_lock_then(no_gate, calls)
    ), patch.object(
        SessionManager, "_insert_user_message", _insert_then(gate)
    ), ThreadPoolExecutor(max_workers=2) as pool:
        try:
            locker = pool.submit(_first_message, manager, "legacy")
            assert gate.reached.wait(timeout=_WAIT_SECONDS), "the lock never reached its insert"
            contributor = pool.submit(_create_contributor, manager)
            contributor_waited = _waits_on_a_lock(postgres_engine, contributor)
        finally:
            gate.release.set()
        locked = locker.result(timeout=_WAIT_SECONDS)
        created = contributor.result(timeout=_WAIT_SECONDS)

    assert (locked["deck_mode"], locked["locked_now"]) == ("legacy", True)
    assert _mode_and_pin(factory, _OWNER) == ("legacy", None)
    assert _mode_and_pin(factory, created["session_id"]) == (None, None), (
        "a contributor created during an uncommitted legacy lock was pinned"
    )
    assert contributor_waited, "contributor creation did not wait for the lock's row lock"
    assert calls == [], "a contributor on a legacy deck must not lock a Graph Release"


def test_an_agent_lock_racing_a_contributor_creation_pins_both_without_deadlock(
    postgres_engine,
):
    """Lock order is parent -> release on both paths.  The creation holds the parent
    FOR SHARE and the release lock; an agent first message on the unpinned owner
    waits on the parent row, then pins the owner once the creation commits.  A
    creation that took the parent lock AFTER the release lock would deadlock here."""
    factory, release_id = _seed(postgres_engine, owner_mode=None, owner_pinned=False)
    manager = SessionManager()
    gate = _Gate("contributor")
    calls: list = []
    db_context = _database_context(factory)

    with patch(_MANAGER_DB, db_context), patch(_DB_SOURCE, db_context), patch(
        _LOCK, _release_lock_then(gate, calls)
    ), ThreadPoolExecutor(max_workers=2) as pool:
        try:
            contributor = pool.submit(_create_contributor, manager)
            assert gate.reached.wait(timeout=_WAIT_SECONDS), "contributor never reached its pin"
            locker = pool.submit(_first_message, manager, "agent")
            locker_waited = _waits_on_a_lock(postgres_engine, locker)
        finally:
            gate.release.set()
        created = contributor.result(timeout=_WAIT_SECONDS)
        locked = locker.result(timeout=_WAIT_SECONDS)

    assert (locked["deck_mode"], locked["locked_now"]) == ("agent", True)
    assert _mode_and_pin(factory, _OWNER) == ("agent", release_id)
    assert _mode_and_pin(factory, created["session_id"]) == (None, release_id)
    assert locker_waited, "the agent lock did not wait for the contributor's locks"
    assert sorted(calls) == ["contributor", "locker"]


@pytest.mark.parametrize(
    "owner_mode, pinned",
    [(None, True), ("agent", True), ("legacy", False)],
    ids=["unlocked", "agent", "legacy"],
)
def test_a_contributor_joining_a_deck_is_pinned_unless_the_deck_is_legacy(
    postgres_engine, owner_mode, pinned
):
    """No race: the FOR SHARE re-read runs on PostgreSQL and the pin rule holds.  An
    unlocked or agent deck pins the new contributor (through the release lock); a
    legacy deck leaves it unpinned and never takes the release lock."""
    factory, release_id = _seed(
        postgres_engine, owner_mode=owner_mode, owner_pinned=owner_mode != "legacy"
    )
    manager = SessionManager()
    calls: list = []
    db_context = _database_context(factory)

    with patch(_MANAGER_DB, db_context), patch(_DB_SOURCE, db_context), patch(
        _LOCK, _release_lock_then(_Gate("nobody"), calls)
    ):
        created = manager.get_or_create_contributor_session(_OWNER, _LATE_CONTRIBUTOR)
        again = manager.get_or_create_contributor_session(_OWNER, _LATE_CONTRIBUTOR)

    assert again["session_id"] == created["session_id"]
    assert _mode_and_pin(factory, created["session_id"]) == (
        None,
        release_id if pinned else None,
    )
    assert _mode_and_pin(factory, _OWNER)[0] == owner_mode
    assert len(calls) == (1 if pinned else 0)


def _send_first_message(manager: SessionManager, session_id: str, mode: str, name: str):
    threading.current_thread().name = name
    try:
        return manager.add_user_message(
            session_id, f"first message from {name}", message_type="user_input",
            requested_deck_mode=mode,
        )
    except DeckModeLockedError as exc:
        return exc


def _user_message_count(factory, *session_ids: str) -> int:
    with factory() as db:
        ids = db.execute(
            select(UserSession.id).where(UserSession.session_id.in_(session_ids))
        ).scalars().all()
        rows = db.execute(
            select(SessionMessage.id).where(
                SessionMessage.session_id.in_(ids), SessionMessage.role == "user"
            )
        ).all()
        return len(rows)


def _race_two_first_messages(postgres_engine, owner_mode: str, contributor_mode: str):
    """The owner's first message has run its lock UPDATE (uncommitted, held at the
    insert) when a contributor's first message on the same empty deck arrives; the
    contributor's UPDATE of the owner row blocks on the owner's row lock.  Returns
    ``(factory, release_id, contributor_session_id, owner_result, contributor_result,
    contributor_waited)``."""
    factory, release_id = _seed(postgres_engine, owner_mode=None, owner_pinned=True)
    manager = SessionManager()
    db_context = _database_context(factory)
    gate = _Gate("owner")

    with patch(_MANAGER_DB, db_context), patch(_DB_SOURCE, db_context), patch.object(
        SessionManager, "_insert_user_message", _insert_then(gate)
    ):
        contributor_id = manager.get_or_create_contributor_session(
            _OWNER, _LATE_CONTRIBUTOR
        )["session_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                owner = pool.submit(_send_first_message, manager, _OWNER, owner_mode, "owner")
                assert gate.reached.wait(timeout=_WAIT_SECONDS), "owner never reached its insert"
                contributor = pool.submit(
                    _send_first_message, manager, contributor_id, contributor_mode, "contributor"
                )
                waited = _waits_on_a_lock(postgres_engine, contributor)
            finally:
                gate.release.set()
            owner_result = owner.result(timeout=_WAIT_SECONDS)
            contributor_result = contributor.result(timeout=_WAIT_SECONDS)
    return factory, release_id, contributor_id, owner_result, contributor_result, waited


@pytest.mark.parametrize("owner_mode, loser_mode", [("legacy", "agent"), ("agent", "legacy")])
def test_two_first_messages_in_flight_with_different_modes_one_wins_and_one_gets_409(
    postgres_engine, owner_mode, loser_mode
):
    """Spec §12 row 4.  The owner holds the lock UPDATE uncommitted; the contributor
    asked for the other mode and waits on the owner row.  When the owner commits, the
    contributor's conditional UPDATE matches nothing, it re-reads the stored mode and
    raises ``DeckModeLockedError`` carrying the WINNER's mode.  One user row exists
    and the pins follow the winner (legacy clears both; agent keeps both)."""
    factory, release_id, contributor_id, owner_result, loser, waited = _race_two_first_messages(
        postgres_engine, owner_mode, loser_mode
    )

    assert waited, "the contributor's lock UPDATE did not wait for the owner's row lock"
    assert (owner_result["deck_mode"], owner_result["locked_now"]) == (owner_mode, True)
    assert isinstance(loser, DeckModeLockedError)
    assert loser.deck_mode == owner_mode
    assert _user_message_count(factory, _OWNER, contributor_id) == 1
    expected_pin = None if owner_mode == "legacy" else release_id
    assert _mode_and_pin(factory, _OWNER) == (owner_mode, expected_pin)
    assert _mode_and_pin(factory, contributor_id) == (None, expected_pin)


@pytest.mark.parametrize("mode", ["legacy", "agent"])
def test_two_first_messages_in_flight_with_the_same_mode_both_save_and_one_locks(
    postgres_engine, mode
):
    """Spec §12 row 4, same mode on both sides: the loser re-reads the winner's mode,
    finds it is the mode it asked for, and saves its message too."""
    factory, release_id, contributor_id, owner_result, contributor_result, waited = (
        _race_two_first_messages(postgres_engine, mode, mode)
    )

    assert waited, "the contributor's lock UPDATE did not wait for the owner's row lock"
    assert not isinstance(contributor_result, Exception)
    assert owner_result["deck_mode"] == contributor_result["deck_mode"] == mode
    assert sorted([owner_result["locked_now"], contributor_result["locked_now"]]) == [False, True]
    assert _user_message_count(factory, _OWNER, contributor_id) == 2
    expected_pin = None if mode == "legacy" else release_id
    assert _mode_and_pin(factory, _OWNER) == (mode, expected_pin)
    assert _mode_and_pin(factory, contributor_id) == (None, expected_pin)

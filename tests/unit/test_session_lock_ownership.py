"""The session processing lock belongs to the request that took it.

Today ``release_session_lock(session_id)`` sets ``is_processing = False`` whoever
holds the lock, and ``process_chat_request`` calls it in a ``finally``.  Once a
stop can end a turn early, the abandoned job's ``finally`` runs late -- after the
person has already sent their next message -- and would free the NEXT turn's lock.

So a graph turn binds its request id to the lock (``bind_session_lock``) right
after creating its request row, and releases with that id: a release naming a
request that no longer holds the lock is a no-op.  A release without an id (the
monolith/MCP job, the manual-edit routes) behaves as today.

Lock state is re-read from the database after every step and compared as the whole
``user_sessions`` row.  The one column left out is ``last_activity``: it carries
``onupdate=datetime.utcnow``, so any ORM or Core UPDATE of the row bumps it, and
when it moves is not part of the lock's contract.
"""
from __future__ import annotations

import contextlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from src.api.services.session_manager import SESSION_LOCK_TIMEOUT_SECONDS, SessionManager
from src.database.models.session import UserSession

#: Excluded from row comparisons -- see the module docstring.
_VOLATILE = ("last_activity",)


class _Locks:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        self.sm = SessionManager()

    def new_session(
        self,
        *,
        processing: bool = False,
        age_seconds: Optional[float] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """Insert a user_sessions row in a chosen lock state; return its session_id."""
        sid = f"lock-{uuid.uuid4().hex[:12]}"
        started = (
            None if age_seconds is None else datetime.utcnow() - timedelta(seconds=age_seconds)
        )
        with self.factory() as db:
            db.add(
                UserSession(
                    session_id=sid,
                    created_by="lock-owner@example.com",
                    is_processing=processing,
                    processing_started_at=started,
                    processing_request_id=request_id,
                )
            )
            db.commit()
        return sid

    def row(self, sid: str) -> Dict[str, Any]:
        """The whole user_sessions row (bar ``last_activity``), read fresh."""
        table = UserSession.__table__
        with self.engine.connect() as conn:
            row = conn.execute(
                select(table).where(table.c.session_id == sid)
            ).mappings().one()
        return {k: v for k, v in row.items() if k not in _VOLATILE}

    def acquire_now(self, sid: str) -> Dict[str, Any]:
        """Acquire *sid*'s lock, assert it was taken fresh and unbound, return the row."""
        before = self.row(sid)
        t0 = datetime.utcnow()
        assert self.sm.acquire_session_lock(sid) is True, "acquire refused a free lock"
        t1 = datetime.utcnow()
        held = self.row(sid)
        started = held["processing_started_at"]
        assert started is not None and t0 - timedelta(seconds=1) <= started <= t1 + timedelta(seconds=1)
        assert held == {
            **before,
            "is_processing": True,
            "processing_started_at": started,
            "processing_request_id": None,
        }
        return held


@pytest.fixture
def locks(sqlite_engine_with_decks, monkeypatch) -> _Locks:
    env = _Locks(sqlite_engine_with_decks)
    # ``get_db_session`` resolves its factory through this at call time.
    monkeypatch.setattr("src.core.database.get_session_local", lambda: env.factory)
    return env


def _freed(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **row,
        "is_processing": False,
        "processing_started_at": None,
        "processing_request_id": None,
    }


def _bound(row: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    return {**row, "processing_request_id": request_id}


@contextlib.contextmanager
def _capture_sql(engine) -> Iterator[List[str]]:
    seen: List[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


# ---------------------------------------------------------------------------
# bind_session_lock
# ---------------------------------------------------------------------------


def test_bind_session_lock_records_the_owner(locks):
    sid = locks.new_session()
    held = locks.acquire_now(sid)

    assert locks.sm.bind_session_lock(sid, "r1") is None

    assert locks.row(sid) == _bound(held, "r1")


def test_bind_does_not_take_a_free_lock(locks):
    """``bind`` sets the id only WHERE is_processing -- it never takes the lock."""
    sid = locks.new_session()
    before = locks.row(sid)

    locks.sm.bind_session_lock(sid, "r1")

    assert locks.row(sid) == before
    # A missing session is harmless and creates nothing.
    locks.sm.bind_session_lock("no-such-session", "r1")
    table = UserSession.__table__
    with locks.engine.connect() as conn:
        assert conn.execute(
            select(table.c.id).where(table.c.session_id == "no-such-session")
        ).first() is None


# ---------------------------------------------------------------------------
# A request-scoped release frees only its own lock
# ---------------------------------------------------------------------------


def test_old_request_release_does_not_free_new_lock(locks):
    sid = locks.new_session()

    # Turn r1 takes, binds and releases its own lock.
    held = locks.acquire_now(sid)
    locks.sm.bind_session_lock(sid, "r1")
    assert locks.sm.release_session_lock(sid, "r1") is True
    assert locks.row(sid) == _freed(held)

    # Turn r2 takes the lock; r1's late release (its job's ``finally`` running
    # after a stop) must not free it.
    held = locks.acquire_now(sid)
    locks.sm.bind_session_lock(sid, "r2")
    owned_by_r2 = _bound(held, "r2")
    assert locks.row(sid) == owned_by_r2

    assert locks.sm.release_session_lock(sid, "r1") is False
    assert locks.row(sid) == owned_by_r2, "r1's late release touched r2's lock"
    assert locks.sm.acquire_session_lock(sid) is False, "r2's lock was freed"
    assert locks.row(sid) == owned_by_r2

    assert locks.sm.release_session_lock(sid, "r2") is True
    assert locks.row(sid) == _freed(owned_by_r2)


def test_request_scoped_release_of_a_free_or_missing_session_is_false(locks):
    sid = locks.new_session()
    before = locks.row(sid)

    assert locks.sm.release_session_lock(sid, "r1") is False
    assert locks.row(sid) == before
    assert locks.sm.release_session_lock("no-such-session", "r1") is False


def test_refused_acquire_keeps_the_holders_binding(locks):
    """A second sender's refused acquire must not clear the holder's request id.

    Clearing it would orphan the lock: the holder's matched release would then
    find no match and the lock would stay held, refreshed by the heartbeat.
    """
    sid = locks.new_session()
    held = locks.acquire_now(sid)
    locks.sm.bind_session_lock(sid, "r1")
    owned = _bound(held, "r1")

    assert locks.sm.acquire_session_lock(sid) is False
    assert locks.row(sid) == owned

    assert locks.sm.release_session_lock(sid, "r1") is True
    assert locks.row(sid) == _freed(owned)


@pytest.mark.parametrize(
    "processing, age_seconds",
    [
        # A turn that died holding its lock, now stale.
        (True, SESSION_LOCK_TIMEOUT_SECONDS + 5),
        # A free row still carrying an id -- what ``recover_stuck_requests`` leaves:
        # it clears is_processing and processing_started_at directly.
        (False, None),
    ],
    ids=["stale-dead-turn", "free-with-leftover-id"],
)
def test_acquire_clears_a_previous_binding(locks, processing, age_seconds):
    sid = locks.new_session(processing=processing, age_seconds=age_seconds, request_id="r-dead")
    before = locks.row(sid)
    assert before["processing_request_id"] == "r-dead"

    t0 = datetime.utcnow()
    assert locks.sm.acquire_session_lock(sid) is True
    held = locks.row(sid)
    started = held["processing_started_at"]
    assert started is not None and started >= t0 - timedelta(seconds=1)
    assert held == {
        **before,
        "is_processing": True,
        "processing_started_at": started,
        "processing_request_id": None,
    }, "taking the lock did not clear the previous request's binding"

    # The dead turn's late release no longer matches the new holder.
    assert locks.sm.release_session_lock(sid, "r-dead") is False
    assert locks.row(sid) == held


# ---------------------------------------------------------------------------
# A release without a request id is today's behaviour
# ---------------------------------------------------------------------------


def test_release_without_request_id_is_unchanged(locks):
    """The manual-edit path: release frees the lock whoever holds it, and says so."""
    sid = locks.new_session()

    held = locks.acquire_now(sid)
    assert locks.sm.release_session_lock(sid) is True
    assert locks.row(sid) == _freed(held)

    # A bound lock too -- and the binding is cleared with it.
    held = locks.acquire_now(sid)
    locks.sm.bind_session_lock(sid, "r1")
    assert locks.row(sid) == _bound(held, "r1")
    assert locks.sm.release_session_lock(sid) is True
    assert locks.row(sid) == _freed(held)

    assert locks.sm.release_session_lock("no-such-session") is False


def test_monolith_job_releases_unbound_lock(locks):
    """An MCP-style job: acquire, never bind, release without an id -- freed as today.

    ``mcp_server.py`` acquires the lock and never binds a request id, and its jobs
    run on the monolith, whose ``finally`` keeps the unconditional release.  A
    request-scoped release (some graph turn's) must not free the unbound lock.
    """
    sid = locks.new_session()
    held = locks.acquire_now(sid)

    assert locks.sm.release_session_lock(sid, "r-some-graph-turn") is False
    assert locks.row(sid) == held

    assert locks.sm.release_session_lock(sid) is True
    assert locks.row(sid) == _freed(held)
    assert locks.sm.acquire_session_lock(sid) is True, "the freed lock could not be retaken"


# ---------------------------------------------------------------------------
# The matched release is one conditional UPDATE
# ---------------------------------------------------------------------------


def test_matched_release_is_one_conditional_update(locks):
    """Read-then-write would let a release check r1, lose the row to r2, then free r2.

    SQLite has one writer, so that race cannot open here; what can be checked is
    the statement shape the brief requires: no read of the row before the write,
    and one UPDATE whose WHERE carries the request id.
    """
    sid = locks.new_session()
    held = locks.acquire_now(sid)
    locks.sm.bind_session_lock(sid, "r1")

    with _capture_sql(locks.engine) as sql:
        assert locks.sm.release_session_lock(sid, "r1") is True

    touching = [s for s in sql if re.search(r"\buser_sessions\b", s)]
    assert touching, f"release issued no statement on user_sessions: {sql}"
    first = touching[0]
    assert re.match(r"^\s*UPDATE\b", first, re.IGNORECASE), (
        f"the matched release read the row before writing it: {touching}"
    )
    where = re.split(r"\bWHERE\b", first, maxsplit=1, flags=re.IGNORECASE)
    assert len(where) == 2 and "processing_request_id" in where[1], (
        f"the release's UPDATE is not conditional on the request id: {first}"
    )
    updates = [s for s in touching if re.match(r"^\s*UPDATE\b", s, re.IGNORECASE)]
    assert len(updates) == 1, f"expected one UPDATE, got {updates}"
    assert locks.row(sid) == _freed(held)


def test_release_never_reports_freeing_a_lock_that_was_not_held(locks):
    """A free row can carry a leftover id (recover_stuck_requests); a matched
    release for that id must not claim to have released anything."""
    sid = locks.new_session(processing=False, request_id="r-leftover")
    before = locks.row(sid)

    assert locks.sm.release_session_lock(sid, "r-leftover") is False
    assert locks.row(sid) == before

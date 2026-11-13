"""The write fence: a chat turn may write only while its ``chat_requests`` row is live.

Every database write a turn makes first "claims" its request row with a
conditional ``UPDATE ... SET status = status WHERE request_id = :rid AND status IN
('pending', 'running')``.  Once a stop or a failure has moved the row to a terminal
status, the claim matches nothing and the write is refused with
``TurnFencedError``.  Later tasks put this in front of every writer and roll the
deck back on stop, so this file is the contract they rest on.

What is proven here, on a real SQLite schema built the production way
(``create_all`` + ``_run_migrations``, via ``sqlite_engine_with_decks``):

* with no request id in play (no argument, no ``ContextVar``) the fence issues no
  SQL at all -- the SSE path, the arc-review sweeper and every monolith writer go
  through unchanged;
* a live row passes, a terminal (or absent) row is refused, and the claim never
  moves the row;
* the fence reads the request id from the graph's ``ContextVar`` when no id is
  passed, and an explicit id wins over it;
* ``allow_completed=True`` (the title thread) refuses only ``cancelled``/``error``;
* ``start_chat_request`` moves a row ``pending -> running`` exactly once;
* ``turn_is_live`` reads committed status and writes nothing;
* ``raise_if_turn_ended`` (the check before a model call that no fenced write
  precedes) refuses a turn that is not live, reads only, issues no SQL without a
  request id, and lets an unreadable status through.

Every test seeds a live *neighbour* request alongside its target and compares the
WHOLE ``chat_requests`` table before and after.  A claim or start that lost its
``request_id`` predicate would then match the neighbour: for a terminal target the
sabotaged claim's ``rowcount`` is exactly 1 and the fence would wrongly pass, and a
sabotaged start would flip the neighbour to ``running``.

The row lock the claim takes -- what makes the fence and the rollback serialise --
needs real row locks, so it is proven on PostgreSQL in
``tests/integration/test_generation_fence_postgres.py``.
"""
from __future__ import annotations

import contextlib
import re
import uuid
from typing import Any, Dict, Iterator, List, Optional

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.orm import sessionmaker

from src.database.models.session import ChatRequest, UserSession
from src.services import generation_fence
from src.services.generation_fence import (
    LIVE_STATUSES,
    TurnFencedError,
    TurnStopped,
    claim_turn_row,
    fence_turn_write,
    raise_if_turn_ended,
    start_chat_request,
    turn_is_live,
)
from src.services.graph.event_emitter import (
    chat_request_id_var,
    get_chat_request_id,
    set_chat_request_id,
)

_ALL_STATUSES = ("pending", "running", "completed", "cancelled", "error")
_TERMINAL = ("completed", "cancelled", "error")
_WRITE_SQL = re.compile(r"^\s*(UPDATE|INSERT|DELETE|REPLACE)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    """Start every test with no request id bound, and put the old value back after.

    ``invoke_graph`` sets the var on every turn; a value left behind by another
    test in this thread would make the "no request id" tests vacuous.
    """
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)


class _Db:
    """A throwaway Tellr schema, with ``get_db_session`` routed onto it."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        self._owner_pk = self._seed_owner()
        #: A live request on the same session as every target -- see the docstring.
        self.neighbour = self.seed("pending")

    def _seed_owner(self) -> int:
        with self.factory() as db:
            owner = UserSession(
                session_id=f"fence-{uuid.uuid4().hex[:12]}",
                created_by="fence-owner@example.com",
            )
            db.add(owner)
            db.commit()
            return owner.id

    def seed(self, status: str) -> str:
        """Insert a chat_requests row with *status*; return its request_id."""
        rid = f"req-{uuid.uuid4().hex[:16]}"
        with self.factory() as db:
            db.add(ChatRequest(request_id=rid, session_id=self._owner_pk, status=status))
            db.commit()
        return rid

    def set_status(self, rid: str, status: str) -> None:
        table = ChatRequest.__table__
        with self.factory() as db:
            db.execute(
                update(table).where(table.c.request_id == rid).values(status=status)
            )
            db.commit()

    def table(self) -> Dict[str, Dict[str, Any]]:
        """Every chat_requests row, every column, keyed by request_id.

        Read on a connection of its own, only ever with no session open: the
        in-memory engine is ``SingletonThreadPool``, so a reader closing mid-
        transaction would roll back the session under test.
        """
        table = ChatRequest.__table__
        with self.engine.connect() as conn:
            rows = conn.execute(select(table)).mappings().all()
        return {row["request_id"]: dict(row) for row in rows}


@pytest.fixture
def db(sqlite_engine_with_decks, monkeypatch) -> _Db:
    env = _Db(sqlite_engine_with_decks)
    # ``get_db_session`` resolves its factory through this at call time, so a
    # function that opens its own session (``turn_is_live``) lands on this engine
    # however it imported ``get_db_session``.
    monkeypatch.setattr("src.core.database.get_session_local", lambda: env.factory)
    return env


@contextlib.contextmanager
def _capture_sql(engine) -> Iterator[List[str]]:
    """Every statement SQLAlchemy sends to *engine* while the block runs."""
    seen: List[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _fence(db: _Db, rid: Optional[str] = None, **kwargs) -> Optional[TurnFencedError]:
    """Run the fence in its own transaction; return the refusal, or None if it passed.

    A pass is committed (the claim is part of the writer's transaction), a refusal
    rolled back -- the shape of every production call site.
    """
    with db.factory() as session:
        try:
            if rid is None:
                result = fence_turn_write(session, **kwargs)
            else:
                result = fence_turn_write(session, rid, **kwargs)
        except TurnFencedError as exc:
            session.rollback()
            return exc
        assert result is None, f"fence_turn_write returned {result!r}, not None"
        session.commit()
        return None


# ---------------------------------------------------------------------------
# The interface later tasks import
# ---------------------------------------------------------------------------


def test_live_statuses_and_the_two_exceptions():
    assert LIVE_STATUSES == ("pending", "running")
    for cls in (TurnFencedError, TurnStopped):
        exc = cls("req-abc")
        assert isinstance(exc, RuntimeError), f"{cls.__name__} is not a RuntimeError"
        assert exc.request_id == "req-abc"


# ---------------------------------------------------------------------------
# No request id: no SQL
# ---------------------------------------------------------------------------


def test_fence_noop_without_request_id(db, monkeypatch):
    """No argument and no ContextVar: the fence returns without touching the DB.

    Two independent proofs, so neither an inlined claim nor a call through the
    module global slips past: ``claim_turn_row`` is replaced by one that fails the
    test if called, and every statement sent to the engine is recorded.  A
    ``cancelled`` row exists, so a fence that looked anything up would also raise.
    """
    fenced = db.seed("cancelled")
    before = db.table()

    def _claim_must_not_run(*args, **kwargs):
        raise AssertionError("claim_turn_row was called with no request id in play")

    monkeypatch.setattr(generation_fence, "claim_turn_row", _claim_must_not_run)
    assert get_chat_request_id() is None

    with db.factory() as session, _capture_sql(db.engine) as sql:
        assert fence_turn_write(session) is None
        assert fence_turn_write(session, None) is None
        assert fence_turn_write(session, allow_completed=True) is None
        assert fence_turn_write(session, None, allow_completed=True) is None

    assert sql == [], f"the fence issued SQL with no request id: {sql}"
    assert db.table() == before
    assert before[fenced]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Live rows pass; terminal rows are refused; nothing moves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "running"])
def test_fence_passes_while_live(db, status):
    rid = db.seed(status)
    before = db.table()

    assert _fence(db, rid) is None, f"a {status} request was fenced"

    assert db.table() == before, "the claim changed a chat_requests row"


@pytest.mark.parametrize("status", _TERMINAL)
def test_fence_raises_after_terminal(db, status):
    rid = db.seed(status)
    before = db.table()

    refusal = _fence(db, rid)

    assert refusal is not None, f"a {status} request was not fenced"
    assert refusal.request_id == rid
    assert db.table() == before


def test_fence_raises_for_a_request_with_no_row(db):
    """No row matches the claim, so the write is refused -- not let through."""
    before = db.table()

    refusal = _fence(db, "req-that-was-never-created")

    assert refusal is not None
    assert refusal.request_id == "req-that-was-never-created"
    assert db.table() == before


def test_fence_follows_a_cancel(db):
    """The same request passes, is cancelled, and is then refused."""
    rid = db.seed("running")
    assert _fence(db, rid) is None

    db.set_status(rid, "cancelled")
    before = db.table()

    refusal = _fence(db, rid)
    assert refusal is not None and refusal.request_id == rid
    assert db.table() == before


# ---------------------------------------------------------------------------
# The ContextVar
# ---------------------------------------------------------------------------


def test_fence_reads_context_var(db):
    cancelled = db.seed("cancelled")
    live = db.seed("running")
    before = db.table()

    set_chat_request_id(cancelled)
    refusal = _fence(db)
    assert refusal is not None, "the fence ignored the ContextVar's cancelled request"
    assert refusal.request_id == cancelled

    # The control: the same call passes once the var names a live request, so the
    # refusal above came from the var's request and not from "always raise".
    set_chat_request_id(live)
    assert _fence(db) is None

    assert db.table() == before


def test_explicit_request_id_wins_over_context_var(db):
    """``rid = request_id or get_chat_request_id()`` -- the argument comes first."""
    cancelled = db.seed("cancelled")
    live = db.seed("running")
    before = db.table()

    set_chat_request_id(cancelled)
    assert _fence(db, live) is None, "the ContextVar overrode the explicit request id"

    set_chat_request_id(live)
    refusal = _fence(db, cancelled)
    assert refusal is not None and refusal.request_id == cancelled

    assert db.table() == before


# ---------------------------------------------------------------------------
# allow_completed (the title thread)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, refused",
    [
        ("pending", False),
        ("running", False),
        ("completed", False),
        ("cancelled", True),
        ("error", True),
    ],
)
def test_allow_completed_refuses_only_cancelled_and_error(db, status, refused):
    rid = db.seed(status)
    before = db.table()

    refusal = _fence(db, rid, allow_completed=True)

    if refused:
        assert refusal is not None, f"allow_completed let a {status} request write"
        assert refusal.request_id == rid
    else:
        assert refusal is None, f"allow_completed refused a {status} request"
    assert db.table() == before, "the claim changed a chat_requests row"


# ---------------------------------------------------------------------------
# claim_turn_row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_claim_turn_row_matches_only_live_rows(db, status):
    rid = db.seed(status)
    before = db.table()

    with db.factory() as session:
        claimed = claim_turn_row(session, rid)
        session.commit()

    assert claimed is (status in ("pending", "running"))
    assert db.table() == before


def test_claim_turn_row_without_a_row_is_false(db):
    before = db.table()
    with db.factory() as session:
        assert claim_turn_row(session, "req-missing") is False
        session.commit()
    assert db.table() == before


# ---------------------------------------------------------------------------
# start_chat_request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_start_chat_request_only_from_pending(db, status):
    """True exactly once, from ``pending``; False for every other status.

    A stop that lands while the request is queued moves it to ``cancelled``; the
    job runner's start must then refuse rather than resurrect it to ``running``.
    """
    rid = db.seed(status)
    before = db.table()

    with db.factory() as session:
        started = start_chat_request(session, rid)
        session.commit()

    if status == "pending":
        assert started is True
        expected = {**before, rid: {**before[rid], "status": "running"}}
        assert db.table() == expected

        # Only once: the row is running now.
        with db.factory() as session:
            assert start_chat_request(session, rid) is False
            session.commit()
        assert db.table() == expected
    else:
        assert started is False, f"start_chat_request started a {status} request"
        assert db.table() == before


def test_start_chat_request_without_a_row_is_false(db):
    before = db.table()
    with db.factory() as session:
        assert start_chat_request(session, "req-missing") is False
        session.commit()
    assert db.table() == before


# ---------------------------------------------------------------------------
# turn_is_live
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_turn_is_live_reads_status_and_writes_nothing(db, status):
    rid = db.seed(status)
    before = db.table()

    with _capture_sql(db.engine) as sql:
        live = turn_is_live(rid)

    assert live is (status in ("pending", "running"))
    assert sql, "turn_is_live answered without reading the database"
    writes = [s for s in sql if _WRITE_SQL.match(s)]
    assert writes == [], f"turn_is_live wrote: {writes}"
    assert db.table() == before


def test_turn_is_live_follows_a_committed_cancel(db):
    rid = db.seed("running")
    assert turn_is_live(rid) is True

    db.set_status(rid, "cancelled")

    assert turn_is_live(rid) is False


def test_turn_is_live_without_a_row_is_false(db):
    assert turn_is_live("req-missing") is False


# ---------------------------------------------------------------------------
# raise_if_turn_ended: the read-only check before a model call
# ---------------------------------------------------------------------------


def _check(rid: Optional[str] = None) -> Optional[TurnFencedError]:
    """Run the check; return the refusal, or None if it passed."""
    try:
        result = raise_if_turn_ended() if rid is None else raise_if_turn_ended(rid)
    except TurnFencedError as exc:
        return exc
    assert result is None, f"raise_if_turn_ended returned {result!r}, not None"
    return None


def test_raise_if_turn_ended_is_silent_without_request_id(db, monkeypatch):
    """No argument and no ContextVar: no lookup and no SQL, even beside a cancelled row."""
    fenced = db.seed("cancelled")
    before = db.table()

    def _lookup_must_not_run(*args, **kwargs):
        raise AssertionError("turn_is_live was called with no request id in play")

    monkeypatch.setattr(generation_fence, "turn_is_live", _lookup_must_not_run)
    assert get_chat_request_id() is None

    with _capture_sql(db.engine) as sql:
        assert _check() is None
        assert raise_if_turn_ended(None) is None

    assert sql == [], f"the check issued SQL with no request id: {sql}"
    assert db.table() == before
    assert before[fenced]["status"] == "cancelled"


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_raise_if_turn_ended_refuses_once_not_live_and_writes_nothing(db, status):
    """Live passes, terminal raises; it reads (no claim, no lock) and moves nothing."""
    rid = db.seed(status)
    before = db.table()

    with _capture_sql(db.engine) as sql:
        refusal = _check(rid)

    if status in LIVE_STATUSES:
        assert refusal is None, f"a {status} turn was refused"
    else:
        assert refusal is not None, f"a {status} turn was let through"
        assert refusal.request_id == rid
    assert sql, "the check answered without reading the database"
    writes = [s for s in sql if _WRITE_SQL.match(s)]
    assert writes == [], f"the check wrote (it must be read-only): {writes}"
    assert db.table() == before


def test_raise_if_turn_ended_without_a_row_refuses(db):
    refusal = _check("req-that-was-never-created")
    assert refusal is not None and refusal.request_id == "req-that-was-never-created"


def test_raise_if_turn_ended_reads_context_var_and_an_explicit_id_wins(db):
    cancelled = db.seed("cancelled")
    live = db.seed("running")

    set_chat_request_id(cancelled)
    refusal = _check()
    assert refusal is not None and refusal.request_id == cancelled
    assert _check(live) is None, "the ContextVar overrode the explicit request id"

    set_chat_request_id(live)
    assert _check() is None
    refusal = _check(cancelled)
    assert refusal is not None and refusal.request_id == cancelled


def test_raise_if_turn_ended_carries_on_when_the_status_is_unreadable(
    db, monkeypatch, caplog
):
    """A database blip is not a stop: the next fenced write still decides."""
    rid = db.seed("cancelled")

    def _unreadable(request_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(generation_fence, "turn_is_live", _unreadable)
    with caplog.at_level("WARNING", logger="src.services.generation_fence"):
        assert _check(rid) is None
    assert any(
        r.levelname == "WARNING" and r.name == "src.services.generation_fence"
        for r in caplog.records
    ), "the unreadable status was not logged"

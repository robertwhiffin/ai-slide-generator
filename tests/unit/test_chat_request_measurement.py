"""Task 6: when a chat request started, and what kind of model fault ended it.

Covers:

- ``_migrate_chat_request_measurement`` adds ``started_at`` (TIMESTAMP) and
  ``model_fault_kind`` (VARCHAR(32)), both nullable, to a ``chat_requests`` table
  that predates them; keeps existing rows (NULL in both); is wired into
  ``_run_migrations``; and is idempotent.  On SQLite, and on real PostgreSQL
  (self-skips when none is reachable), where the migrated columns also
  round-trip through the real writers.
- ``generation_fence.start_chat_request`` stamps ``started_at`` in the same
  conditional UPDATE that moves ``pending`` -> ``running``, so a refused start
  writes nothing.
- ``SessionManager.update_chat_request_status(..., "running")`` stamps
  ``started_at`` only while it is NULL; no other status sets it.
- ``SessionManager.set_chat_request_fault_kind`` writes only an ``error`` row,
  and only the row it names.

The job-level half (``process_chat_request`` writing both) is in
``tests/unit/test_job_queue_rollback.py``.

Every migration test drops both columns first and proves they are gone:
``create_all`` builds them from the ORM model, so a test on a ``create_all``
database alone would test ``create_all``, not the migration.  The writer tests
seed a neighbour request beside every target and compare the WHOLE
``chat_requests`` table, as ``tests/unit/test_generation_fence.py`` does.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest
from sqlalchemy import DateTime, String, create_engine, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 -- registers every model on Base.metadata
from src.api.services.session_manager import get_session_manager
from src.core import database as core_database
from src.core.database import Base, _run_migrations
from src.database.models.session import ChatRequest, UserSession
from src.services.generation_fence import start_chat_request

_MEASUREMENT_COLUMNS = ("started_at", "model_fault_kind")
_QUAL = lambda t: f'"{t}"'  # noqa: E731 -- the lambda _run_migrations builds with no schema

_ALL_STATUSES = ("pending", "running", "completed", "cancelled", "error")
_KINDS = ("rate_limited", "server_error", "timeout", "connection", "not_transient")


def _col(row: Dict[str, Any], name: str) -> Any:
    """*row*'s *name* column, asserting the table has one."""
    assert name in row, f"chat_requests has no {name} column: {sorted(row)}"
    return row[name]


# ---------------------------------------------------------------------------
# PostgreSQL self-skip (pattern: tests/unit/test_chat_request_progress.py)
# ---------------------------------------------------------------------------

_PG_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


_PG_REACHABLE = _postgres_available()

# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------


def _column_map(engine) -> dict:
    """Reflect chat_requests' columns through a fresh connection (no cached reflection)."""
    with engine.connect() as conn:
        return {c["name"]: c for c in inspect(conn).get_columns("chat_requests")}


def _column_names(engine) -> list:
    """Every chat_requests column name, duplicates included."""
    with engine.connect() as conn:
        return [c["name"] for c in inspect(conn).get_columns("chat_requests")]


def _drop_measurement_columns(engine) -> None:
    """Return chat_requests to its pre-Task-6 shape, and prove both columns are gone."""
    with engine.begin() as conn:
        for col_name in _MEASUREMENT_COLUMNS:
            conn.execute(text(f"ALTER TABLE chat_requests DROP COLUMN {col_name}"))
    remaining = _column_map(engine)
    for col_name in _MEASUREMENT_COLUMNS:
        assert col_name not in remaining, f"DROP COLUMN did not remove {col_name}"


def _assert_measurement_columns(engine) -> None:
    """Both columns exist exactly once, are nullable, and carry the right types.

    ``started_at`` is a naive timestamp, like ``created_at``: wait time is
    ``started_at - created_at``, and both are ``datetime.utcnow()`` values.
    ``model_fault_kind`` is a VARCHAR(32), like ``rollback_outcome``.
    """
    names = _column_names(engine)
    col_map = _column_map(engine)
    for col_name in _MEASUREMENT_COLUMNS:
        assert names.count(col_name) == 1, (
            f"{col_name} appears {names.count(col_name)} times in chat_requests: {names}"
        )
        assert col_map[col_name]["nullable"] is True, f"{col_name} is not nullable"
    started = col_map["started_at"]["type"]
    assert isinstance(started, DateTime), f"started_at is {started!r}, expected a TIMESTAMP"
    assert not getattr(started, "timezone", False), (
        f"started_at is {started!r}; it must hold naive UTC, like created_at"
    )
    kind = col_map["model_fault_kind"]["type"]
    assert isinstance(kind, String), f"model_fault_kind is {kind!r}, expected VARCHAR(32)"
    assert kind.length == 32, f"model_fault_kind is {kind!r}, expected VARCHAR(32)"


def _migrate_alone(engine) -> None:
    """Run the helper in isolation, as _run_migrations calls it, with a fresh inspector."""
    with engine.begin() as conn:
        core_database._migrate_chat_request_measurement(conn, inspect(conn), None, _QUAL, True)


def _round_trip_through_the_writers(engine, monkeypatch) -> None:
    """Stamp ``started_at`` and set a kind through the real writers; read both back.

    For a database whose columns came from the migration: a ``create_all``
    database cannot see a wrong DDL type string.
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: factory)
    rid = f"req-{uuid.uuid4().hex[:16]}"
    with factory() as db:
        owner = UserSession(
            session_id=f"measure-{uuid.uuid4().hex[:12]}",
            created_by="measure-owner@example.com",
        )
        db.add(owner)
        db.flush()
        db.add(ChatRequest(request_id=rid, session_id=owner.id, status="pending"))
        db.commit()
    manager = get_session_manager()

    t0 = datetime.utcnow()
    assert manager.start_chat_request(rid) is True
    t1 = datetime.utcnow()
    assert manager.fail_chat_request(rid, "MK failed") is True
    assert manager.set_chat_request_fault_kind(rid, "server_error") is None

    table = ChatRequest.__table__
    with engine.connect() as conn:
        row = conn.execute(
            select(table.c.status, table.c.started_at, table.c.model_fault_kind).where(
                table.c.request_id == rid
            )
        ).one()
    assert row.status == "error"
    assert isinstance(row.started_at, datetime), f"started_at read back as {row.started_at!r}"
    assert row.started_at.tzinfo is None, f"started_at read back zone-aware: {row.started_at!r}"
    assert t0 <= row.started_at <= t1, (t0, row.started_at, t1)
    assert row.model_fault_kind == "server_error"


# ---------------------------------------------------------------------------
# Migration (SQLite, file-backed)
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_engine(tmp_path):
    """A fresh SQLite file built in production order: create_all, then _run_migrations."""
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    yield engine
    engine.dispose()


def test_the_migration_adds_both_columns(migrated_engine):
    # A fresh install gets both columns from the ORM model via create_all.
    _assert_measurement_columns(migrated_engine)

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    db = factory()
    try:
        owner = UserSession(session_id="pre-task-6-session", created_by="owner@example.com")
        db.add(owner)
        db.flush()
        db.add(
            ChatRequest(
                request_id="pre-task-6-request",
                session_id=owner.id,
                status="completed",
                error_message=None,
                result_json='{"slides": []}',
                rollback_outcome=None,
            )
        )
        db.commit()
    finally:
        db.close()

    _drop_measurement_columns(migrated_engine)
    _migrate_alone(migrated_engine)

    _assert_measurement_columns(migrated_engine)
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT request_id, status, result_json, started_at, model_fault_kind "
                "FROM chat_requests"
            )
        ).fetchall()
    assert len(rows) == 1, f"expected the pre-existing row to survive, got {rows}"
    row = rows[0]
    assert row.request_id == "pre-task-6-request"
    assert row.status == "completed"
    assert row.result_json == '{"slides": []}'
    assert row.started_at is None
    assert row.model_fault_kind is None


def test_run_migrations_wires_the_helper(migrated_engine):
    _drop_measurement_columns(migrated_engine)

    _run_migrations(migrated_engine)

    _assert_measurement_columns(migrated_engine)


def test_the_migration_is_idempotent(migrated_engine):
    _drop_measurement_columns(migrated_engine)

    _migrate_alone(migrated_engine)  # adds both
    _migrate_alone(migrated_engine)  # must see them and add nothing
    _run_migrations(migrated_engine)
    _run_migrations(migrated_engine)

    _assert_measurement_columns(migrated_engine)


def test_the_migrated_columns_round_trip_through_the_writers(migrated_engine, monkeypatch):
    _drop_measurement_columns(migrated_engine)
    _migrate_alone(migrated_engine)

    _round_trip_through_the_writers(migrated_engine, monkeypatch)


# ---------------------------------------------------------------------------
# PostgreSQL-only: the ALTER path on a real schema (production is PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_engine():
    """A fresh PostgreSQL database with the full Tellr schema, dropped afterwards."""
    if not _PG_REACHABLE:
        pytest.skip(
            f"no PostgreSQL reachable at {_PG_URL}; set TELLR_TEST_POSTGRES_URL to run "
            "the chat-request-measurement Postgres suite",
        )
    db_name = f"tellr_measure_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    engine = create_engine(make_url(_PG_URL).set(database=db_name))
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    try:
        yield engine
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


class TestPostgresAlterPath:
    """_run_migrations adds both columns to a pre-Task-6 chat_requests on PostgreSQL."""

    pytestmark = pytest.mark.postgres

    def test_run_migrations_adds_both_columns_and_reruns_cleanly(self, pg_engine):
        _drop_measurement_columns(pg_engine)

        _run_migrations(pg_engine)
        _assert_measurement_columns(pg_engine)

        _run_migrations(pg_engine)  # second run: no error, no duplicate
        _assert_measurement_columns(pg_engine)

    def test_the_migrated_columns_round_trip_through_the_writers(self, pg_engine, monkeypatch):
        _drop_measurement_columns(pg_engine)
        _run_migrations(pg_engine)

        _round_trip_through_the_writers(pg_engine, monkeypatch)


# ---------------------------------------------------------------------------
# The writers (pattern: the ``db`` fixture of tests/unit/test_generation_fence.py)
# ---------------------------------------------------------------------------


class _Db:
    """A throwaway Tellr schema, with ``get_db_session`` routed onto it."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.factory = sessionmaker(
            bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        self._owner_pk = self._seed_owner()
        #: A live request on the same session as every target: a write that lost
        #: its request_id predicate would land on it.
        self.neighbour = self.seed("pending")

    def _seed_owner(self) -> int:
        with self.factory() as db:
            owner = UserSession(
                session_id=f"measure-{uuid.uuid4().hex[:12]}",
                created_by="measure-owner@example.com",
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

    def set_columns(self, rid: str, **values: Any) -> None:
        table = ChatRequest.__table__
        with self.factory() as db:
            db.execute(update(table).where(table.c.request_id == rid).values(**values))
            db.commit()

    def table(self) -> Dict[str, Dict[str, Any]]:
        """Every chat_requests row, every column, keyed by request_id.

        Read on a connection of its own, only ever with no session open: the
        in-memory engine is ``SingletonThreadPool``.
        """
        table = ChatRequest.__table__
        with self.engine.connect() as conn:
            rows = conn.execute(select(table)).mappings().all()
        return {row["request_id"]: dict(row) for row in rows}


@pytest.fixture
def db(sqlite_engine_with_decks, monkeypatch) -> _Db:
    env = _Db(sqlite_engine_with_decks)
    # ``get_db_session`` resolves its factory through this at call time, so the
    # SessionManager writers land on this engine.
    monkeypatch.setattr("src.core.database.get_session_local", lambda: env.factory)
    return env


def _tick_past(moment: datetime) -> None:
    """Wait until ``datetime.utcnow()`` is past *moment*, so a re-stamp would differ."""
    while datetime.utcnow() <= moment:
        time.sleep(0.0005)


def _without(row: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in keys}


# -- started_at: the conditional start ---------------------------------------


def test_start_sets_started_at(db):
    rid = db.seed("pending")
    before = db.table()
    assert _col(before[rid], "started_at") is None, "a pending request has started"

    t0 = datetime.utcnow()
    with db.factory() as session:
        assert start_chat_request(session, rid) is True
        session.commit()
    t1 = datetime.utcnow()

    after = db.table()
    stamped = after[rid]["started_at"]
    assert isinstance(stamped, datetime), f"started_at is {stamped!r}"
    assert t0 <= stamped <= t1, f"started_at {stamped} is outside the start ({t0} .. {t1})"
    # The move and the stamp, on this row only; the neighbour is byte-identical.
    expected = {**before, rid: {**before[rid], "status": "running", "started_at": stamped}}
    assert after == expected

    # Only once: a second start is refused and moves nothing, started_at included.
    _tick_past(stamped)
    with db.factory() as session:
        assert start_chat_request(session, rid) is False
        session.commit()
    assert db.table() == expected


@pytest.mark.parametrize("status", [s for s in _ALL_STATUSES if s != "pending"])
def test_a_refused_start_leaves_started_at_null(db, status):
    """The stamp rides the conditional UPDATE: a start refused by its status
    predicate writes nothing at all (a separate UPDATE would stamp this row)."""
    rid = db.seed(status)
    before = db.table()

    with db.factory() as session:
        assert start_chat_request(session, rid) is False
        session.commit()

    after = db.table()
    assert _col(after[rid], "started_at") is None, (
        f"a refused start stamped a {status} request"
    )
    assert after == before


# -- started_at: the monolith's move to running -------------------------------


def test_running_sets_started_at_once(db):
    rid = db.seed("pending")
    manager = get_session_manager()
    before = db.table()
    assert _col(before[rid], "started_at") is None

    t0 = datetime.utcnow()
    manager.update_chat_request_status(rid, "running")
    t1 = datetime.utcnow()

    first = db.table()
    stamped = first[rid]["started_at"]
    assert isinstance(stamped, datetime), f"started_at is {stamped!r}"
    assert t0 <= stamped <= t1, f"started_at {stamped} is outside the move ({t0} .. {t1})"
    assert first == {**before, rid: {**before[rid], "status": "running", "started_at": stamped}}

    # A second "running" (the clock has moved on) keeps the first stamp exactly.
    _tick_past(stamped)
    manager.update_chat_request_status(rid, "running")

    assert db.table() == first


def test_running_keeps_an_earlier_started_at(db):
    """A row that already started keeps its stamp, whoever wrote it."""
    rid = db.seed("running")
    earlier = datetime(2026, 11, 17, 9, 0, 0, 123456)
    db.set_columns(rid, started_at=earlier)
    before = db.table()
    assert before[rid]["started_at"] == earlier

    get_session_manager().update_chat_request_status(rid, "running")

    assert db.table() == before


@pytest.mark.parametrize("status", ["pending", "completed", "error", "cancelled"])
def test_no_other_status_sets_started_at(db, status):
    """A request that never ran (no move to running) never gets a start time."""
    rid = db.seed("pending")
    before = db.table()
    error = "MK failed" if status == "error" else None

    get_session_manager().update_chat_request_status(rid, status, error)

    after = db.table()
    row = after[rid]
    assert _col(row, "started_at") is None, f"a move to {status} set started_at"
    expected = dict(before[rid], status=status)
    if error:
        expected["error_message"] = error
    assert _without(row, ("completed_at",)) == _without(expected, ("completed_at",))
    if status in ("completed", "error"):
        assert row["completed_at"] is not None
    else:
        assert row["completed_at"] is None
    assert {k: v for k, v in after.items() if k != rid} == {
        k: v for k, v in before.items() if k != rid
    }


# -- model_fault_kind ----------------------------------------------------------


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_set_chat_request_fault_kind_writes_only_an_error_row(db, status):
    """Only a request that ended ``error`` gets a kind: never a live one, never a
    stopped or completed one, and never a neighbour (another ``error`` row)."""
    rid = db.seed(status)
    errored_neighbour = db.seed("error")
    before = db.table()
    assert {r: _col(row, "model_fault_kind") for r, row in before.items()} == {
        r: None for r in before
    }

    assert get_session_manager().set_chat_request_fault_kind(rid, "rate_limited") is None

    after = db.table()
    if status == "error":
        assert after == {**before, rid: {**before[rid], "model_fault_kind": "rate_limited"}}
    else:
        assert after == before, f"a {status} request was written a fault kind"
    assert after[errored_neighbour]["model_fault_kind"] is None


@pytest.mark.parametrize("kind", _KINDS)
def test_set_chat_request_fault_kind_stores_the_kind_it_is_given(db, kind):
    rid = db.seed("error")
    before = db.table()

    get_session_manager().set_chat_request_fault_kind(rid, kind)

    assert db.table() == {**before, rid: {**before[rid], "model_fault_kind": kind}}


def test_set_chat_request_fault_kind_of_an_unknown_request_writes_nothing(db):
    db.seed("error")
    before = db.table()

    assert get_session_manager().set_chat_request_fault_kind("no-such-request", "timeout") is None

    assert db.table() == before

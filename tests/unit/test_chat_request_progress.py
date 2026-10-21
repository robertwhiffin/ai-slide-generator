"""A graph turn's stage summary stored on its chat request (#319, Task 1).

Covers:
- ``_migrate_chat_request_progress`` adds ``progress_json`` (TEXT) and
  ``progress_seq`` (INTEGER), both nullable, to a ``chat_requests`` table that
  predates #319, keeps existing rows (NULL in both), is wired into
  ``_run_migrations`` and is idempotent.
- ``SessionManager.record_chat_request_progress`` stores a snapshot only when its
  ``seq`` is newer than the stored one, touches only its own request, and the
  status/result writers never clobber it.
- ``get_chat_request`` serves the stored snapshot as ``turn_progress`` (None
  before any is recorded).
- On real PostgreSQL, the ALTER path through ``_run_migrations`` (self-skips when
  no PostgreSQL is reachable; CI provides one).

``SET LOCAL lock_timeout`` must only be issued on PostgreSQL.  SQLite rejects it
(probed on SQLite 3.53.1: ``sqlite3.OperationalError: near "SET": syntax error``),
and ``get_db_session`` re-raises, so every SQLite test below that records progress
goes red if the dialect guard is dropped.  The PostgreSQL lock-timeout behaviour
itself is proven in Task 5.
"""

import json
import os
import uuid

import pytest
from sqlalchemy import Integer, Text, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — registers every model on Base.metadata
from src.api.services.session_manager import get_session_manager
from src.core import database as core_database
from src.core.database import Base, _run_migrations
from src.database.models.session import ChatRequest, UserSession
from tests.unit.conftest_graph import graph_env  # noqa: F401 — fixture

_PROGRESS_COLUMNS = ("progress_json", "progress_seq")
_QUAL = lambda t: f'"{t}"'  # noqa: E731 — the lambda _run_migrations builds with no schema

# ---------------------------------------------------------------------------
# PostgreSQL self-skip (pattern: tests/unit/test_spec_dirty_marker.py)
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
# Helpers
# ---------------------------------------------------------------------------


def _column_map(engine) -> dict:
    """Reflect chat_requests' columns through a fresh connection (no cached reflection)."""
    with engine.connect() as conn:
        return {c["name"]: c for c in inspect(conn).get_columns("chat_requests")}


def _column_names(engine) -> list:
    """Every chat_requests column name, duplicates included."""
    with engine.connect() as conn:
        return [c["name"] for c in inspect(conn).get_columns("chat_requests")]


def _drop_progress_columns(engine) -> None:
    """Return chat_requests to its pre-#319 shape, and prove both columns are gone."""
    with engine.begin() as conn:
        for col_name in _PROGRESS_COLUMNS:
            conn.execute(text(f"ALTER TABLE chat_requests DROP COLUMN {col_name}"))
    remaining = _column_map(engine)
    for col_name in _PROGRESS_COLUMNS:
        assert col_name not in remaining, f"DROP COLUMN did not remove {col_name}"


def _assert_progress_columns(engine) -> None:
    """Both columns exist exactly once, are nullable, and carry the right types.

    ``progress_seq`` must be an integer: the guard compares it with ``<``, and a
    text column would compare lexicographically ('10' < '9').
    """
    names = _column_names(engine)
    col_map = _column_map(engine)
    for col_name in _PROGRESS_COLUMNS:
        assert names.count(col_name) == 1, (
            f"{col_name} appears {names.count(col_name)} times in chat_requests: {names}"
        )
        assert col_map[col_name]["nullable"] is True, f"{col_name} is not nullable"
    assert isinstance(col_map["progress_json"]["type"], Text), (
        f"progress_json is {col_map['progress_json']['type']!r}, expected TEXT"
    )
    assert isinstance(col_map["progress_seq"]["type"], Integer), (
        f"progress_seq is {col_map['progress_seq']['type']!r}, expected INTEGER"
    )


def _migrate_alone(engine) -> None:
    """Run the helper in isolation, as _run_migrations calls it, with a fresh inspector."""
    with engine.begin() as conn:
        core_database._migrate_chat_request_progress(conn, inspect(conn), None, _QUAL, True)


def _snapshot(seq: int, phase: str = "building") -> dict:
    """A stage summary in the shape the tracker publishes (Task 2)."""
    return {
        "seq": seq,
        "phase": phase,
        "slides": {
            "total": 10,
            "building": [0, 1, 2],
            "reviewing": [3],
            "fixing": [4, 5],
            "done": [6, 7, 8, 9],
        },
    }


def _raw_progress(env, request_id: str):
    """``(progress_json, progress_seq)`` exactly as stored on the row."""
    db = env.factory()
    try:
        row = db.execute(
            text(
                "SELECT progress_json, progress_seq FROM chat_requests "
                "WHERE request_id = :r"
            ),
            {"r": request_id},
        ).one()
        return row.progress_json, row.progress_seq
    finally:
        db.close()


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


def test_a_pre_319_chat_requests_table_gains_both_columns(migrated_engine):
    # A fresh install gets both columns from the ORM model via create_all.
    _assert_progress_columns(migrated_engine)

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    db = factory()
    try:
        owner = UserSession(session_id="pre-319-session", created_by="owner@example.com")
        db.add(owner)
        db.flush()
        db.add(
            ChatRequest(
                request_id="pre-319-request",
                session_id=owner.id,
                status="completed",
                result_json=json.dumps({"slides": []}),
            )
        )
        db.commit()
    finally:
        db.close()

    _drop_progress_columns(migrated_engine)
    _migrate_alone(migrated_engine)

    _assert_progress_columns(migrated_engine)
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT request_id, status, result_json, progress_json, progress_seq "
                "FROM chat_requests"
            )
        ).fetchall()
    assert len(rows) == 1, f"expected the pre-existing row to survive, got {rows}"
    row = rows[0]
    assert row.request_id == "pre-319-request"
    assert row.status == "completed"
    assert json.loads(row.result_json) == {"slides": []}
    assert row.progress_json is None
    assert row.progress_seq is None


def test_run_migrations_wires_the_helper(migrated_engine):
    _drop_progress_columns(migrated_engine)

    _run_migrations(migrated_engine)

    _assert_progress_columns(migrated_engine)


def test_the_migration_is_idempotent(migrated_engine):
    _drop_progress_columns(migrated_engine)

    _migrate_alone(migrated_engine)  # adds both
    _migrate_alone(migrated_engine)  # must see them and add nothing
    _run_migrations(migrated_engine)
    _run_migrations(migrated_engine)

    _assert_progress_columns(migrated_engine)


# ---------------------------------------------------------------------------
# SessionManager (SQLite via graph_env: every record call below would raise
# "near SET: syntax error" if SET LOCAL were issued on SQLite)
# ---------------------------------------------------------------------------


def test_get_chat_request_reports_no_progress_before_any_is_recorded(graph_env):
    manager = get_session_manager()
    rid = manager.create_chat_request(graph_env.session_id)

    served = manager.get_chat_request(rid)

    assert "turn_progress" in served, f"get_chat_request has no turn_progress key: {served}"
    assert served["turn_progress"] is None


def test_a_newer_snapshot_replaces_an_older_one(graph_env):
    manager = get_session_manager()
    rid = manager.create_chat_request(graph_env.session_id)

    assert manager.record_chat_request_progress(rid, 1, _snapshot(1, "planning")) is True
    assert manager.get_chat_request(rid)["turn_progress"] == _snapshot(1, "planning")

    assert manager.record_chat_request_progress(rid, 3, _snapshot(3)) is True
    assert manager.get_chat_request(rid)["turn_progress"] == _snapshot(3)

    # The guard compares numerically: 10 is newer than 3 (a text compare says '10' < '3').
    assert manager.record_chat_request_progress(rid, 10, _snapshot(10, "reviewing_deck")) is True
    assert manager.get_chat_request(rid)["turn_progress"] == _snapshot(10, "reviewing_deck")
    assert _raw_progress(graph_env, rid)[1] == 10


def test_an_older_snapshot_never_overwrites_a_newer_one(graph_env):
    manager = get_session_manager()
    rid = manager.create_chat_request(graph_env.session_id)

    assert manager.record_chat_request_progress(rid, 3, _snapshot(3)) is True
    assert manager.record_chat_request_progress(rid, 2, _snapshot(2, "planning")) is False
    assert manager.record_chat_request_progress(rid, 3, _snapshot(3, "reviewing_deck")) is False

    served = manager.get_chat_request(rid)["turn_progress"]
    assert served == _snapshot(3)
    assert served["seq"] == 3
    raw_json, raw_seq = _raw_progress(graph_env, rid)
    assert raw_seq == 3
    assert json.loads(raw_json) == _snapshot(3)


def test_an_unknown_request_records_nothing_and_does_not_raise(graph_env):
    manager = get_session_manager()
    # A real request beside the unknown one: an UPDATE that ignores request_id
    # would hit it, report True, and give it progress.
    sibling = manager.create_chat_request(graph_env.session_id)

    assert manager.record_chat_request_progress("no-such-request", 1, _snapshot(1)) is False

    assert manager.get_chat_request("no-such-request") is None
    assert manager.get_chat_request(sibling)["turn_progress"] is None
    assert _raw_progress(graph_env, sibling) == (None, None)


def test_status_and_result_writers_do_not_clobber_progress(graph_env):
    manager = get_session_manager()
    rid = manager.create_chat_request(graph_env.session_id)
    assert manager.record_chat_request_progress(rid, 2, _snapshot(2)) is True

    manager.update_chat_request_status(rid, "running")
    manager.set_chat_request_result(rid, {"slides": None})
    manager.update_chat_request_status(rid, "completed")

    served = manager.get_chat_request(rid)
    # The writers really ran ...
    assert served["status"] == "completed"
    assert served["result"] == {"slides": None}
    # ... and left the stage summary alone.
    assert served["turn_progress"] == _snapshot(2)
    assert _raw_progress(graph_env, rid)[1] == 2


# ---------------------------------------------------------------------------
# PostgreSQL-only: the ALTER path on a real schema
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_engine():
    """A fresh PostgreSQL database with the full Tellr schema, dropped afterwards."""
    if not _PG_REACHABLE:
        pytest.skip(
            f"no PostgreSQL reachable at {_PG_URL}; set TELLR_TEST_POSTGRES_URL to run "
            "the chat-request-progress Postgres suite",
        )
    db_name = f"tellr_progress_{uuid.uuid4().hex[:16]}"
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
    """_run_migrations adds both columns to a pre-#319 chat_requests on PostgreSQL."""

    pytestmark = pytest.mark.postgres

    def test_run_migrations_adds_both_columns_and_reruns_cleanly(self, pg_engine):
        _drop_progress_columns(pg_engine)

        _run_migrations(pg_engine)
        _assert_progress_columns(pg_engine)

        _run_migrations(pg_engine)  # second run: no error, no duplicate
        _assert_progress_columns(pg_engine)

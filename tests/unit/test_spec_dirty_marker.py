"""Tests for the B2.3 spec-dirty marker columns and migration.

Covers:
- The three columns exist on session_slide_decks, are nullable, and have the
  expected types (DATETIME / VARCHAR) on a real SQLite engine.
- The migration is idempotent (calling it twice raises no error).
- ``spec_dirty`` does not appear in ``get_slide_deck``'s source (the columns are NOT
  deck presentation state).
- On real PostgreSQL, ``_migrate_spec_dirty_marker`` creates the partial index
  ``ix_session_slide_decks_spec_dirty_at``; gated by the self-skip pattern (§0.3).
- A lease round-trip: set ``spec_dirty_claimed_at``, read it back.

All SQLite tests use the shared ``sqlite_engine_with_decks`` fixture from conftest so
they inherit the production create_all + _run_migrations ordering without duplicating it.
"""

import inspect
import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — registers every model on Base.metadata
from src.core.database import Base, _SPEC_DIRTY_INDEX, _migrate_spec_dirty_marker, _run_migrations

# ---------------------------------------------------------------------------
# PostgreSQL self-skip (§0.3 pattern)
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.postgres  # the postgres marker on the PG-only tests is set per-class

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


def _get_column_map(engine, table_name: str) -> dict:
    """Return {column_name: column_info_dict} for *table_name*."""
    insp = sa_inspect(engine)
    return {c["name"]: c for c in insp.get_columns(table_name)}


# ---------------------------------------------------------------------------
# SQLite-backed tests (always run)
# ---------------------------------------------------------------------------


class TestEffectiveSchema:
    """The three B2.3 columns are present, nullable, and carry the right types.

    These tests use ``sqlite_engine_with_decks``, which builds the schema via
    ``create_all`` followed by ``_run_migrations`` — the same ordering as
    production.  They assert the *effective* schema that results from both steps
    combined.  They cannot distinguish whether a column came from the ORM model
    (``create_all``) or from the migration helper (``ALTER TABLE``); for that
    isolated proof see ``TestMigrationAlterPath``.
    """

    def test_spec_dirty_at_exists_and_is_nullable(self, sqlite_engine_with_decks):
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        assert "spec_dirty_at" in cols, (
            "spec_dirty_at missing from session_slide_decks — "
            "check the ORM model (src/database/models/session.py) and "
            "_migrate_spec_dirty_marker; this fixture runs both and cannot isolate which is missing"
        )
        assert cols["spec_dirty_at"]["nullable"] is True

    def test_spec_dirty_by_exists_and_is_nullable(self, sqlite_engine_with_decks):
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        assert "spec_dirty_by" in cols, (
            "spec_dirty_by missing from session_slide_decks"
        )
        assert cols["spec_dirty_by"]["nullable"] is True

    def test_spec_dirty_claimed_at_exists_and_is_nullable(self, sqlite_engine_with_decks):
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        assert "spec_dirty_claimed_at" in cols, (
            "spec_dirty_claimed_at missing from session_slide_decks"
        )
        assert cols["spec_dirty_claimed_at"]["nullable"] is True

    def test_spec_dirty_at_type_is_datetime(self, sqlite_engine_with_decks):
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        col_type = cols["spec_dirty_at"]["type"]
        # SQLAlchemy reflects DateTime as DATETIME on SQLite; the type class name
        # covers both the SQLAlchemy wrapper and any dialect-native variant.
        type_name = type(col_type).__name__.upper()
        assert "DATETIME" in type_name or "DATE" in type_name, (
            f"spec_dirty_at has unexpected type: {col_type!r}"
        )

    def test_spec_dirty_by_type_is_varchar(self, sqlite_engine_with_decks):
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        col_type = cols["spec_dirty_by"]["type"]
        type_name = type(col_type).__name__.upper()
        assert "VARCHAR" in type_name or "STRING" in type_name or "TEXT" in type_name, (
            f"spec_dirty_by has unexpected type: {col_type!r}"
        )

    def test_spec_dirty_claimed_at_type_is_datetime(self, sqlite_engine_with_decks):
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        col_type = cols["spec_dirty_claimed_at"]["type"]
        type_name = type(col_type).__name__.upper()
        assert "DATETIME" in type_name or "DATE" in type_name, (
            f"spec_dirty_claimed_at has unexpected type: {col_type!r}"
        )


class TestMigrationIdempotency:
    """Running the migration twice must not raise."""

    def test_second_run_is_a_no_op(self, sqlite_engine_with_decks):
        # The fixture already ran create_all + _run_migrations once.
        # Running again must not raise.
        _run_migrations(sqlite_engine_with_decks)
        # If we get here the second run did not raise.
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        assert "spec_dirty_at" in cols


class TestNotPresentationState:
    """spec_dirty must not appear anywhere in get_slide_deck's source.

    The columns are internal sweep-scheduling state, not deck presentation
    data.  A reader who looks at get_slide_deck's returned dict must not see
    them.  This test guards against accidental inclusion.
    """

    def test_spec_dirty_absent_from_get_slide_deck_source(self):
        from src.api.services.session_manager import SessionManager
        source = inspect.getsource(SessionManager.get_slide_deck)
        assert "spec_dirty" not in source, (
            "spec_dirty appeared in get_slide_deck's source — these columns are "
            "internal sweep state and must NOT be included in the presentation dict"
        )


class TestLeaseRoundTrip:
    """A claim written with raw SQL is read back correctly."""

    def test_set_claimed_at_and_read_back(self, sqlite_engine_with_decks):
        """Insert a deck row, write spec_dirty_claimed_at, read it back."""
        Session = sessionmaker(bind=sqlite_engine_with_decks)
        db = Session()
        try:
            session_sid = uuid.uuid4().hex

            # Insert a minimal user_sessions row so the FK is satisfied.
            # is_processing is NOT NULL with a Python-level default; raw SQL bypasses
            # Python defaults so we must supply it explicitly.
            db.execute(
                text(
                    "INSERT INTO user_sessions "
                    "(session_id, created_by, created_at, last_activity, is_processing) "
                    "VALUES (:sid, :user, :now, :now, 0)"
                ),
                {"sid": session_sid, "user": "testuser", "now": datetime.utcnow()},
            )
            # Retrieve the auto-generated integer PK.
            user_session_pk = db.execute(
                text("SELECT id FROM user_sessions WHERE session_id = :sid"),
                {"sid": session_sid},
            ).scalar()

            # Insert a minimal session_slide_decks row.
            db.execute(
                text(
                    "INSERT INTO session_slide_decks "
                    "(session_id, slide_count, version, created_at, updated_at) "
                    "VALUES (:s_id, 0, 0, :now, :now)"
                ),
                {"s_id": user_session_pk, "now": datetime.utcnow()},
            )
            deck_pk = db.execute(
                text(
                    "SELECT id FROM session_slide_decks WHERE session_id = :s_id"
                ),
                {"s_id": user_session_pk},
            ).scalar()
            db.commit()

            # Write the claim lease.
            now = datetime.utcnow()
            db.execute(
                text(
                    "UPDATE session_slide_decks "
                    "SET spec_dirty_claimed_at = :ts "
                    "WHERE id = :deck_id"
                ),
                {"ts": now, "deck_id": deck_pk},
            )
            db.commit()

            # Read it back.
            result = db.execute(
                text(
                    "SELECT spec_dirty_claimed_at FROM session_slide_decks "
                    "WHERE id = :deck_id"
                ),
                {"deck_id": deck_pk},
            ).one()

            assert result.spec_dirty_claimed_at is not None
            # SQLite raw SQL returns datetime as a string; normalise before arithmetic.
            raw = result.spec_dirty_claimed_at
            if isinstance(raw, str):
                # ISO format: "2026-09-12 12:00:00.000000" or similar
                raw = datetime.fromisoformat(raw)
            age = (datetime.utcnow() - raw).total_seconds()
            assert 0 <= age < 10, f"spec_dirty_claimed_at age {age:.1f}s outside expected range"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# ALTER-path test — the only path that matters for already-provisioned databases
# ---------------------------------------------------------------------------


class TestMigrationAlterPath:
    """_migrate_spec_dirty_marker adds the three columns to a table that lacks them.

    create_all never ALTERs existing tables — it only creates missing ones.  So for
    a database provisioned before B2.3 landed, _migrate_spec_dirty_marker is the
    sole mechanism that adds the three columns.  This test simulates that case by
    dropping all three from a freshly-built schema (SQLite >= 3.35 supports
    ALTER TABLE … DROP COLUMN), confirming they are genuinely absent, then calling
    the migration helper in isolation, and asserting all three return with the
    correct nullability.
    """

    def test_migration_adds_columns_to_existing_table(self, sqlite_engine_with_decks):
        """Drop the three B2.3 columns, run the migration alone, assert they return."""
        from sqlalchemy import inspect as _inspect

        # Drop the partial index first.  SQLite refuses DROP COLUMN on any column
        # referenced by an index (including partial indexes), so we must remove
        # ix_session_slide_decks_spec_dirty_at before dropping spec_dirty_at.
        # Then drop all three columns to simulate a pre-B2.3 provisioned database.
        # SQLite 3.51.0 (this environment) supports ALTER TABLE … DROP COLUMN (≥3.35).
        with sqlite_engine_with_decks.begin() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {_SPEC_DIRTY_INDEX}"))
            conn.execute(text("ALTER TABLE session_slide_decks DROP COLUMN spec_dirty_at"))
            conn.execute(text("ALTER TABLE session_slide_decks DROP COLUMN spec_dirty_by"))
            conn.execute(text("ALTER TABLE session_slide_decks DROP COLUMN spec_dirty_claimed_at"))

        # Confirm all three are genuinely gone before invoking the migration.
        # A fresh connect() gets a fresh inspector with no cached reflection.
        with sqlite_engine_with_decks.connect() as check_conn:
            cols_after_drop = {c["name"] for c in _inspect(check_conn).get_columns("session_slide_decks")}
        assert "spec_dirty_at" not in cols_after_drop, "DROP COLUMN did not remove spec_dirty_at"
        assert "spec_dirty_by" not in cols_after_drop, "DROP COLUMN did not remove spec_dirty_by"
        assert "spec_dirty_claimed_at" not in cols_after_drop, "DROP COLUMN did not remove spec_dirty_claimed_at"

        # Call the migration directly — same call _run_migrations makes in production.
        # _qual with no schema quotes just the table name, matching _run_migrations' lambda.
        _qual = lambda t: f'"{t}"'
        with sqlite_engine_with_decks.begin() as conn:
            insp = _inspect(conn)
            _migrate_spec_dirty_marker(conn, insp, schema=None, _qual=_qual, is_sqlite=True)

        # Assert all three columns are back and nullable.
        with sqlite_engine_with_decks.connect() as check_conn:
            col_map = {c["name"]: c for c in _inspect(check_conn).get_columns("session_slide_decks")}
        for col_name in ("spec_dirty_at", "spec_dirty_by", "spec_dirty_claimed_at"):
            assert col_name in col_map, (
                f"{col_name} missing from session_slide_decks after _migrate_spec_dirty_marker — "
                f"the ALTER TABLE path in the migration helper did not add it"
            )
            assert col_map[col_name]["nullable"] is True, (
                f"{col_name} is not nullable after migration"
            )


# ---------------------------------------------------------------------------
# PostgreSQL-only tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def pg_engine_with_dirty_marker():
    """A fresh PostgreSQL database with the full Tellr schema, dropped afterwards.

    The database is created blank, schema built via create_all + _run_migrations
    (production ordering), and torn down after the test.  This exercises the
    partial-index path inside _migrate_spec_dirty_marker.
    """
    if not _PG_REACHABLE:
        pytest.skip(
            f"no PostgreSQL reachable at {_PG_URL}; set TELLR_TEST_POSTGRES_URL to run "
            "the spec-dirty-marker Postgres suite",
        )
    db_name = f"tellr_specmarker_{uuid.uuid4().hex[:16]}"
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


class TestPostgresPartialIndex:
    """The partial index exists on a real PostgreSQL database.

    These tests are skipped when PostgreSQL is unreachable (self-skip pattern,
    corrections §0.3).  A real PostgreSQL 14.20 IS reachable in the dev environment,
    so this suite should actually execute rather than skip.
    """

    pytestmark = pytest.mark.postgres

    def test_partial_index_exists_after_migration(self, pg_engine_with_dirty_marker):
        """create_all + _run_migrations emits the partial index on PostgreSQL."""
        with pg_engine_with_dirty_marker.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'session_slide_decks'"
                )
            ).fetchall()
        index_names = {r.indexname for r in rows}
        assert _SPEC_DIRTY_INDEX in index_names, (
            f"{_SPEC_DIRTY_INDEX!r} not found in pg_indexes for session_slide_decks; "
            f"found: {sorted(index_names)}"
        )

    def test_partial_index_has_where_clause(self, pg_engine_with_dirty_marker):
        """The index is a partial index, not a full-table one."""
        with pg_engine_with_dirty_marker.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'session_slide_decks' "
                    "AND indexname = :ix"
                ),
                {"ix": _SPEC_DIRTY_INDEX},
            ).fetchone()
        assert row is not None, f"{_SPEC_DIRTY_INDEX!r} not found in pg_indexes"
        assert "where" in row.indexdef.lower(), (
            f"index has no WHERE clause — not a partial index: {row.indexdef!r}"
        )
        # PostgreSQL may wrap the predicate in parens: WHERE (spec_dirty_at IS NOT NULL)
        assert "spec_dirty_at is not null" in row.indexdef.lower(), (
            f"Unexpected WHERE clause in index definition: {row.indexdef!r}"
        )

    def test_migration_is_no_op_on_second_run(self, pg_engine_with_dirty_marker):
        """Running _run_migrations twice on PostgreSQL does not raise or duplicate the index."""
        _run_migrations(pg_engine_with_dirty_marker)
        with pg_engine_with_dirty_marker.connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE tablename = 'session_slide_decks' "
                    "AND indexname = :ix"
                ),
                {"ix": _SPEC_DIRTY_INDEX},
            ).scalar()
        assert count == 1, f"Expected exactly 1 index named {_SPEC_DIRTY_INDEX!r}, got {count}"

    def test_migration_creates_partial_index_on_existing_table(self, pg_engine_with_dirty_marker):
        """Migration's CREATE INDEX path fires when the index is absent but columns exist.

        create_all builds the index from the ORM model's postgresql_where declaration,
        so by the time _run_migrations runs its idempotency guard always matches and the
        migration's own CREATE INDEX SQL never executes in the fixture-based tests.  This
        test isolates that path: drop the index (columns stay), call the migration helper
        directly, and assert the index returns as a partial index with the correct
        WHERE predicate.  A whole-table index created by a broken statement would carry
        the same name and pass tests that only check presence.
        """
        from sqlalchemy import inspect as _inspect

        # Drop just the index — columns stay, matching the production state where a
        # database was provisioned before B2.3 but after the three columns were added
        # by some earlier mechanism.
        with pg_engine_with_dirty_marker.begin() as conn:
            conn.execute(text(f'DROP INDEX IF EXISTS "{_SPEC_DIRTY_INDEX}"'))

        # Confirm the index is genuinely absent before calling the migration.
        with pg_engine_with_dirty_marker.connect() as check_conn:
            pre_count = check_conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE tablename = 'session_slide_decks' AND indexname = :ix"
                ),
                {"ix": _SPEC_DIRTY_INDEX},
            ).scalar()
        assert pre_count == 0, f"{_SPEC_DIRTY_INDEX!r} was not dropped before the migration call"

        # Call the migration directly — the same call _run_migrations makes in production.
        # No schema: _qual quotes just the table name, matching _run_migrations' lambda.
        _qual = lambda t: f'"{t}"'
        with pg_engine_with_dirty_marker.begin() as conn:
            insp = _inspect(conn)
            _migrate_spec_dirty_marker(conn, insp, schema=None, _qual=_qual, is_sqlite=False)

        # Assert the index is back and is a partial index with the correct predicate.
        # A whole-table index would have no WHERE clause in pg_indexes.indexdef.
        with pg_engine_with_dirty_marker.connect() as check_conn:
            row = check_conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'session_slide_decks' AND indexname = :ix"
                ),
                {"ix": _SPEC_DIRTY_INDEX},
            ).fetchone()
        assert row is not None, (
            f"{_SPEC_DIRTY_INDEX!r} not found in pg_indexes after _migrate_spec_dirty_marker — "
            f"the migration's CREATE INDEX path did not run"
        )
        assert "where" in row.indexdef.lower(), (
            f"index has no WHERE clause — migration created a full-table index, not a partial one: "
            f"{row.indexdef!r}"
        )
        assert "spec_dirty_at is not null" in row.indexdef.lower(), (
            f"index WHERE clause does not match expected predicate: {row.indexdef!r}"
        )

    def test_sqlite_early_return_does_not_create_index(self, sqlite_engine_with_decks):
        """The is_sqlite early return in _migrate_spec_dirty_marker skips the index path.

        On SQLite, the partial index is built by create_all from the ORM model's
        sqlite_where declaration (not by the migration helper's Postgres-only code
        path).  We verify that the SQLite engine (which has the migration helper's
        early return) has the column but no error, and that the is_sqlite guard fires.
        This is also the sabotage test: if the early return were dropped the migration
        helper would attempt Postgres-only SQL against SQLite and raise.
        """
        # Columns must still exist (added by create_all on the ORM model).
        cols = _get_column_map(sqlite_engine_with_decks, "session_slide_decks")
        assert "spec_dirty_at" in cols
        # Running the helper directly on SQLite must not raise.
        from sqlalchemy import inspect as sa_inspect_inner
        with sqlite_engine_with_decks.begin() as conn:
            insp = sa_inspect_inner(sqlite_engine_with_decks)
            schema = None
            def _qual(t):
                return t
            _migrate_spec_dirty_marker(conn, insp, schema, _qual, is_sqlite=True)
        # If we reach here, the SQLite early-return path did not raise.

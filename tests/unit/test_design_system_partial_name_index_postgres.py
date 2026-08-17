"""The design-system name index must be PARTIAL on ``is_active``, on real Postgres.

``design_system.name`` used to carry a whole-table UNIQUE constraint, which made the
soft delete reserve the name forever: ``DELETE`` tombstones the row, the list
endpoint hides it, and the tombstone still held the name against every later import.
:func:`_migrate_design_system_partial_name_index` replaces that constraint with a
partial unique index over ``WHERE is_active``.

GATING: requires a reachable PostgreSQL. The migration only runs there — SQLite gets
the right schema straight from ``create_all`` and cannot ``DROP CONSTRAINT`` at all —
so the CONVERSION of an already-provisioned database is only observable here. That is
exactly the half a green SQLite suite cannot vouch for.

All fixtures SYNTHETIC (invented brand names).
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

import src.database.models  # noqa: F401 - register every model with Base.metadata
from src.core.database import (
    _DS_NAME_ACTIVE_INDEX,
    _migrate_design_system_partial_name_index,
    _run_migrations,
)
from src.database.models.design_system import DesignSystem

pytestmark = pytest.mark.postgres

_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


if not _postgres_available():  # pragma: no cover - environment-dependent
    pytest.skip(
        f"no PostgreSQL reachable at {_ADMIN_URL}; set TELLR_TEST_POSTGRES_URL to run "
        "the design-system partial-name-index suite",
        allow_module_level=True,
    )


@pytest.fixture()
def pg_engine():
    """A fresh PostgreSQL database with the real ORM schema, dropped afterwards."""
    db_name = f"tellr_dsindex_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    engine = create_engine(make_url(_ADMIN_URL).set(database=db_name))
    DesignSystem.__table__.create(bind=engine, checkfirst=True)
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


def _revert_to_whole_table_unique(engine) -> str:
    """Put the database back into the PRE-FIX shape an existing deploy is in.

    Drops the partial index ``create_all`` just built and restores the whole-table
    UNIQUE constraint a column-level ``unique=True`` used to emit, so the migration
    is exercised against the state it actually has to convert rather than against a
    hand-built approximation.
    """
    constraint_name = "design_system_name_key"
    with engine.begin() as conn:
        conn.execute(text(f"DROP INDEX IF EXISTS {_DS_NAME_ACTIVE_INDEX}"))
        conn.execute(text(
            f"ALTER TABLE design_system ADD CONSTRAINT {constraint_name} UNIQUE (name)"
        ))
    return constraint_name


def _index_predicates(engine) -> dict[str, str | None]:
    """``{index name: its WHERE predicate or None}`` for every index on the table."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'design_system'"
        )).fetchall()
    out: dict[str, str | None] = {}
    for name, definition in rows:
        _, _, predicate = definition.partition(" WHERE ")
        out[name] = predicate or None
    return out


def _insert(engine, name: str, *, is_active: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO design_system (name, published, is_default, is_active, "
                "version, created_at, updated_at) VALUES (:n, false, false, :a, 1, "
                "now(), now())"
            ),
            {"n": name, "a": is_active},
        )


class TestFreshSchema:
    def test_create_all_emits_the_partial_index_and_no_whole_table_unique(self, pg_engine):
        predicates = _index_predicates(pg_engine)
        assert _DS_NAME_ACTIVE_INDEX in predicates, predicates
        assert predicates[_DS_NAME_ACTIVE_INDEX] == "is_active"

        # No whole-table UNIQUE over (name) survives anywhere.
        constraints = inspect(pg_engine).get_unique_constraints("design_system")
        assert [c for c in constraints if list(c["column_names"]) == ["name"]] == []


class TestMigrationConvertsAnExistingDatabase:
    def test_whole_table_constraint_is_replaced_by_the_partial_index(self, pg_engine):
        constraint_name = _revert_to_whole_table_unique(pg_engine)

        # Sanity: the pre-fix database really does refuse a name a tombstone holds.
        _insert(pg_engine, "Nimbus Widgets DS", is_active=False)
        with pytest.raises(Exception, match="duplicate key|unique constraint"):
            _insert(pg_engine, "Nimbus Widgets DS", is_active=True)

        with pg_engine.begin() as conn:
            _migrate_design_system_partial_name_index(
                conn, inspect(conn), None, lambda t: f'"{t}"', False
            )

        predicates = _index_predicates(pg_engine)
        assert predicates.get(_DS_NAME_ACTIVE_INDEX) == "is_active"
        assert constraint_name not in predicates

        # The tombstoned name is now reusable...
        _insert(pg_engine, "Nimbus Widgets DS", is_active=True)
        # ...but a second LIVE row with that name is still refused.
        with pytest.raises(Exception, match="duplicate key|unique constraint"):
            _insert(pg_engine, "Nimbus Widgets DS", is_active=True)

    def test_many_tombstones_may_share_one_name(self, pg_engine):
        _revert_to_whole_table_unique(pg_engine)
        with pg_engine.begin() as conn:
            _migrate_design_system_partial_name_index(
                conn, inspect(conn), None, lambda t: f'"{t}"', False
            )

        for _ in range(3):
            _insert(pg_engine, "Nimbus Widgets DS", is_active=False)
        _insert(pg_engine, "Nimbus Widgets DS", is_active=True)

        with pg_engine.connect() as conn:
            total = conn.execute(text(
                "SELECT count(*) FROM design_system WHERE name = 'Nimbus Widgets DS'"
            )).scalar()
        assert total == 4

    def test_is_idempotent_across_repeated_runs(self, pg_engine):
        _revert_to_whole_table_unique(pg_engine)
        for _ in range(3):
            with pg_engine.begin() as conn:
                _migrate_design_system_partial_name_index(
                    conn, inspect(conn), None, lambda t: f'"{t}"', False
                )

        predicates = _index_predicates(pg_engine)
        matching = [n for n in predicates if n == _DS_NAME_ACTIVE_INDEX]
        assert matching == [_DS_NAME_ACTIVE_INDEX]
        assert predicates[_DS_NAME_ACTIVE_INDEX] == "is_active"

    def test_is_a_noop_on_an_already_converted_database(self, pg_engine):
        before = _index_predicates(pg_engine)
        with pg_engine.begin() as conn:
            _migrate_design_system_partial_name_index(
                conn, inspect(conn), None, lambda t: f'"{t}"', False
            )
        assert _index_predicates(pg_engine) == before

    def test_full_run_migrations_reaches_the_same_fixpoint(self, pg_engine):
        """The migration must also converge when driven through ``_run_migrations``.

        ``_run_migrations`` returns early on a database without ``config_profiles``,
        so this exercises it against the FULL schema — the way startup calls it.
        """
        from src.core.database import Base

        Base.metadata.create_all(bind=pg_engine)
        _revert_to_whole_table_unique(pg_engine)

        _run_migrations(pg_engine)

        predicates = _index_predicates(pg_engine)
        assert predicates.get(_DS_NAME_ACTIVE_INDEX) == "is_active"
        constraints = inspect(pg_engine).get_unique_constraints("design_system")
        assert [c for c in constraints if list(c["column_names"]) == ["name"]] == []

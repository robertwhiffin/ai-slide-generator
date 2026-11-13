"""Interrupt generation, Task 1: the ``generation_snapshots`` table and two columns.

Covers, against REAL SQLite schemas reflected through the SQLAlchemy inspector:

- ``_run_migrations`` turns a database provisioned BEFORE this feature into the new
  schema: it creates ``generation_snapshots`` with exactly the columns, types and
  nullability the plan specifies, and adds ``user_sessions.processing_request_id``
  and ``chat_requests.rollback_outcome`` (both nullable), leaving every other
  column of those two tables as it was.
- A second ``_run_migrations`` is a no-op: no error, the same reflected schema, and
  a stored snapshot row survives it.
- A fresh install (``create_all`` from the ORM models, no helper) builds the same
  three-table schema as the migration, so the model and the helper cannot drift.
- ``generation_snapshots.request_id`` is unique, on a fresh install (built from the
  ORM model by ``create_all``) and on a migrated database (built by the helper).

The "old schema" is built WITHOUT the migration's help: ``create_all`` restricted to
every table except ``generation_snapshots``, then ``ALTER TABLE ... DROP COLUMN``
for the two new columns (SQLite 3.53.1 supports it). ``create_all`` therefore
cannot be what makes these tests pass: disable either migration helper and the
migration and idempotency tests go red. That is the measured PR1 defect this
guards against: an idempotency test that stayed green with its migration off.

The tests deliberately do not import ``GenerationSnapshot``: they drive the schema
through ``_run_migrations`` and raw SQL, so a missing model or a missing helper
fails as a missing table or column, not as a collection error.

All fixture data is synthetic.
"""

import pytest
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError

import src.database.models  # noqa: F401 - registers every model on Base.metadata
from src.core.database import Base, _run_migrations

_SNAPSHOT_TABLE = "generation_snapshots"

#: Every column of ``generation_snapshots`` -> (type, length, nullable), exactly as
#: the plan's Task 1 interface lists them. ``nullable`` is None for the primary
#: key: the plan does not state it, and SQLite reports an ``INTEGER PRIMARY KEY``
#: either way depending on how the DDL is spelled. The PK is asserted separately.
_SNAPSHOT_SPEC = {
    "id": ("INTEGER", None, None),
    "request_id": ("VARCHAR", 64, False),
    "actor_session_pk": ("INTEGER", None, False),
    "owner_session_pk": ("INTEGER", None, False),
    "deck_present": ("BOOLEAN", None, False),
    "deck_columns_json": ("TEXT", None, True),
    "slide_rows_json": ("TEXT", None, False),
    "session_fields_json": ("TEXT", None, False),
    "checkpoint_id": ("VARCHAR", 255, True),
    "mutation_watermark": ("INTEGER", None, True),
    "state": ("VARCHAR", 20, False),
    "created_at": ("DATETIME", None, False),
}

#: The two columns this task adds to existing tables: table -> (column, spec).
_NEW_COLUMNS = {
    "user_sessions": ("processing_request_id", ("VARCHAR", 64, True)),
    "chat_requests": ("rollback_outcome", ("VARCHAR", 32, True)),
}

_TOUCHED_TABLES = (_SNAPSHOT_TABLE, *_NEW_COLUMNS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    """A file-backed SQLite engine, so every connection sees the same database."""
    eng = create_engine(f"sqlite:///{tmp_path / 'tellr.db'}")
    try:
        yield eng
    finally:
        eng.dispose()


def _type_label(sa_type) -> tuple:
    """(generic type name, length) for a reflected column type.

    ``Text`` is checked before ``String`` because it subclasses it.
    """
    if isinstance(sa_type, Text):
        return ("TEXT", None)
    if isinstance(sa_type, String):
        return ("VARCHAR", sa_type.length)
    if isinstance(sa_type, Boolean):
        return ("BOOLEAN", None)
    if isinstance(sa_type, DateTime):
        return ("DATETIME", None)
    if isinstance(sa_type, Integer):
        return ("INTEGER", None)
    return (repr(sa_type), None)


def _table_names(engine) -> set:
    with engine.connect() as conn:
        return set(inspect(conn).get_table_names())


def _reflect(engine, table: str) -> dict:
    """Every column of *table* -> (type, length, nullable), via a fresh inspector.

    Fails loudly on a duplicated column name, which a dict would otherwise hide.
    """
    with engine.connect() as conn:
        columns = inspect(conn).get_columns(table)
    names = [c["name"] for c in columns]
    assert len(names) == len(set(names)), f"{table} has duplicate columns: {names}"
    return {c["name"]: (*_type_label(c["type"]), c["nullable"]) for c in columns}


def _reflect_touched(engine) -> dict:
    """The full reflected schema of the three tables this task touches."""
    return {table: _reflect(engine, table) for table in _TOUCHED_TABLES}


def _build_old_schema(engine) -> dict:
    """Provision the database as it stood before this feature; return its column specs.

    ``create_all`` builds every table except ``generation_snapshots``; the two new
    columns are then dropped. (The drop is skipped when the ORM model does not
    declare the column yet, so the pre-implementation run fails on the assertions
    below rather than on "no such column"; either way the guard proves the
    starting point.)
    """
    Base.metadata.create_all(
        bind=engine,
        tables=[t for t in Base.metadata.sorted_tables if t.name != _SNAPSHOT_TABLE],
    )
    with engine.begin() as conn:
        for table, (column, _spec) in _NEW_COLUMNS.items():
            present = {c["name"] for c in inspect(conn).get_columns(table)}
            if column in present:
                conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))

    # Loud guard: the starting point really is the old schema.
    tables = _table_names(engine)
    assert _SNAPSHOT_TABLE not in tables, "old schema still has generation_snapshots"
    # _run_migrations returns early when config_profiles is missing.
    assert "config_profiles" in tables, f"config_profiles missing; found {sorted(tables)}"
    old = {}
    for table, (column, _spec) in _NEW_COLUMNS.items():
        old[table] = _reflect(engine, table)
        assert column not in old[table], f"old schema still has {table}.{column}"
    return old


def _assert_snapshot_table(engine) -> None:
    """``generation_snapshots`` exists with exactly the planned columns and its PK."""
    tables = _table_names(engine)
    assert _SNAPSHOT_TABLE in tables, f"{_SNAPSHOT_TABLE} table missing"
    actual = _reflect(engine, _SNAPSHOT_TABLE)
    # The plan does not state the PK's nullability (see _SNAPSHOT_SPEC).
    if "id" in actual:
        actual["id"] = (*actual["id"][:2], None)
    assert actual == _SNAPSHOT_SPEC

    with engine.connect() as conn:
        pk = inspect(conn).get_pk_constraint(_SNAPSHOT_TABLE)
    assert pk["constrained_columns"] == ["id"], pk


def _assert_new_columns(engine, old: dict) -> None:
    """Each existing table is its old self plus exactly its one new column."""
    for table, (column, spec) in _NEW_COLUMNS.items():
        assert _reflect(engine, table) == {**old[table], column: spec}, (
            f"{table} after _run_migrations is not its old schema plus {column} {spec}"
        )


def _snapshot_row(request_id: str, **overrides) -> dict:
    """A complete ``generation_snapshots`` row (every column but ``id``)."""
    row = {
        "request_id": request_id,
        "actor_session_pk": 11,
        "owner_session_pk": 7,
        "deck_present": True,
        "deck_columns_json": '{"title": "Q3 review", "slide_count": 2}',
        "slide_rows_json": '[{"position": 0, "html": "<div>one</div>"}]',
        "session_fields_json": '{"title": "Q3 review"}',
        "checkpoint_id": "1ef-checkpoint",
        "mutation_watermark": 42,
        "state": "active",
        "created_at": "2026-11-12 09:30:00.000000",
    }
    row.update(overrides)
    return row


def _insert_snapshot(engine, row: dict) -> None:
    columns = ", ".join(row)
    params = ", ".join(f":{name}" for name in row)
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_SNAPSHOT_TABLE} ({columns}) VALUES ({params})"), row
        )


def _snapshot_rows(engine) -> list:
    """Every stored snapshot row, oldest first, as full dicts without ``id``."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM {_SNAPSHOT_TABLE} ORDER BY id"))
        return [
            {k: v for k, v in row._mapping.items() if k != "id"} for row in rows
        ]


def _build_fresh_install(engine) -> None:
    """A fresh install's tables, from the ORM models alone (no migration helper)."""
    Base.metadata.create_all(bind=engine)


def _build_migrated(engine) -> None:
    """A pre-feature database brought forward by ``_run_migrations``."""
    _build_old_schema(engine)
    _run_migrations(engine)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_creates_snapshot_table_on_old_schema(engine):
    old = _build_old_schema(engine)

    _run_migrations(engine)

    _assert_snapshot_table(engine)
    _assert_new_columns(engine, old)


def test_migration_is_idempotent(engine):
    old = _build_old_schema(engine)
    _run_migrations(engine)
    # Not vacuous: the first run must have produced the new schema.
    _assert_snapshot_table(engine)
    _assert_new_columns(engine, old)
    first = _reflect_touched(engine)
    _insert_snapshot(engine, _snapshot_row("req-kept"))
    rows_before = _snapshot_rows(engine)

    _run_migrations(engine)  # must not raise

    assert _reflect_touched(engine) == first
    assert _snapshot_rows(engine) == rows_before == [_snapshot_row("req-kept")]


def test_fresh_install_matches_migrated_schema(engine, tmp_path):
    """The ORM models (``create_all`` alone) and the migration converge on one schema.

    Without this, a model that declares a column differently from the helper's
    ALTER (or forgets it) would go unnoticed: the migration tests above only ever
    see the helper's output.
    """
    _build_fresh_install(engine)
    _assert_snapshot_table(engine)
    for table, (column, spec) in _NEW_COLUMNS.items():
        assert _reflect(engine, table).get(column) == spec, (
            f"create_all did not build {table}.{column} as {spec}"
        )

    migrated = create_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    try:
        _build_migrated(migrated)
        assert _reflect_touched(migrated) == _reflect_touched(engine)
    finally:
        migrated.dispose()


@pytest.mark.parametrize(
    "build",
    [_build_fresh_install, _build_migrated],
    ids=["fresh_install", "migrated"],
)
def test_snapshot_request_id_is_unique(engine, build):
    build(engine)
    assert _SNAPSHOT_TABLE in _table_names(engine), (
        f"{_SNAPSHOT_TABLE} missing after {build.__name__}"
    )
    first = _snapshot_row("req-dup")
    _insert_snapshot(engine, first)

    # Same request_id, every other value different: only request_id can collide.
    duplicate = _snapshot_row(
        "req-dup",
        actor_session_pk=12,
        owner_session_pk=8,
        deck_present=False,
        deck_columns_json=None,
        slide_rows_json="[]",
        session_fields_json="{}",
        checkpoint_id=None,
        mutation_watermark=None,
        state="sealed",
        created_at="2026-11-12 09:31:00.000000",
    )
    with pytest.raises(IntegrityError) as excinfo:
        _insert_snapshot(engine, duplicate)
    assert "UNIQUE constraint failed: generation_snapshots.request_id" in str(
        excinfo.value
    ), str(excinfo.value)

    # A new request_id with the first row's other values is accepted, so nothing
    # but request_id is unique among them.
    other = _snapshot_row("req-other")
    _insert_snapshot(engine, other)

    assert _snapshot_rows(engine) == [first, other]

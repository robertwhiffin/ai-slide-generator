"""Tests for database migrations (Phase 4: google_credentials_encrypted → global).

Migration logic:
- Copies first non-null google_credentials_encrypted from config_profiles to google_global_credentials
- Nulls out google_credentials_encrypted on all profile rows after copy
- Handles profile_id removal from google_oauth_tokens (SQLite: recreate table)
- All steps idempotent
"""

import os
import tempfile

import pytest
from sqlalchemy import String, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import src.database.models  # noqa: F401 - register models with Base
import src.core.database as database_module
from src.core.database import Base, _run_migrations, init_db
from src.database.models.session import UserSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_engine():
    """SQLite engine for migration tests.

    Uses a temp file so the DB persists across connection open/close
    (engine.begin() closes its connection on exit; in-memory would be destroyed).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def _create_old_config_profiles(conn, qualified_table: str):
    """Create config_profiles with OLD schema including google_credentials_encrypted."""
    conn.execute(text(f"""
        CREATE TABLE {qualified_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            description TEXT,
            is_default BOOLEAN DEFAULT FALSE NOT NULL,
            is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
            deleted_at TIMESTAMP NULL,
            created_at DATETIME NOT NULL,
            created_by VARCHAR(255),
            updated_at DATETIME NOT NULL,
            updated_by VARCHAR(255),
            google_credentials_encrypted TEXT
        )
    """))
    conn.commit()


def _create_google_global_credentials(conn, qualified_table: str):
    """Create empty google_global_credentials table."""
    conn.execute(text(f"""
        CREATE TABLE {qualified_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            credentials_encrypted TEXT NOT NULL,
            uploaded_by VARCHAR(255),
            created_at DATETIME,
            updated_at DATETIME
        )
    """))
    conn.commit()


# ---------------------------------------------------------------------------
# Test: migration creates google_global_credentials table
# ---------------------------------------------------------------------------

def test_migration_creates_google_global_credentials_table(sqlite_engine):
    """init_db (create_all + migrations) ensures google_global_credentials table exists."""
    with patch("src.core.database.get_engine", return_value=sqlite_engine):
        init_db()

    inspector = inspect(sqlite_engine)
    assert "google_global_credentials" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# Test: migration copies first non-null credentials to global
# ---------------------------------------------------------------------------

def test_migration_copies_first_credentials_to_global(sqlite_engine):
    """Migration copies first non-null google_credentials_encrypted from config_profiles to global table."""
    Base.metadata.create_all(bind=sqlite_engine)
    with sqlite_engine.connect() as conn:
        # Drop and recreate with legacy schema (includes google_credentials_encrypted)
        conn.execute(text("DROP TABLE IF EXISTS config_profiles"))
        conn.execute(text("DROP TABLE IF EXISTS google_global_credentials"))
        conn.commit()
        _create_old_config_profiles(conn, "config_profiles")
        _create_google_global_credentials(conn, "google_global_credentials")
        conn.execute(text("""
            INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at, google_credentials_encrypted)
            VALUES ('p1', 0, 0, datetime('now'), datetime('now'), 'encrypted-blob-1'),
                   ('p2', 1, 0, datetime('now'), datetime('now'), 'encrypted-blob-2')
        """))
        conn.commit()

    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.connect() as conn:
        result = conn.execute(text("SELECT credentials_encrypted FROM google_global_credentials")).fetchone()
        assert result is not None, "Migration should have copied credentials to global table"
        assert result[0] == "encrypted-blob-1"


# ---------------------------------------------------------------------------
# Test: migration nulls out credentials on all profile rows
# ---------------------------------------------------------------------------

def test_migration_nulls_all_profile_credentials(sqlite_engine):
    """Migration nulls out google_credentials_encrypted on all profile rows after copy."""
    Base.metadata.create_all(bind=sqlite_engine)
    with sqlite_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_profiles"))
        conn.execute(text("DROP TABLE IF EXISTS google_global_credentials"))
        conn.commit()
        _create_old_config_profiles(conn, "config_profiles")
        _create_google_global_credentials(conn, "google_global_credentials")
        conn.execute(text("""
            INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at, google_credentials_encrypted)
            VALUES ('p1', 0, 0, datetime('now'), datetime('now'), 'encrypted-blob')
        """))
        conn.commit()

    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT google_credentials_encrypted FROM config_profiles")).fetchall()
        assert all(r[0] is None for r in rows)


# ---------------------------------------------------------------------------
# Test: migration is idempotent
# ---------------------------------------------------------------------------

def test_migration_is_idempotent(sqlite_engine):
    """Running migration twice is safe; no duplicate rows, no errors."""
    Base.metadata.create_all(bind=sqlite_engine)
    with sqlite_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_profiles"))
        conn.execute(text("DROP TABLE IF EXISTS google_global_credentials"))
        conn.commit()
        _create_old_config_profiles(conn, "config_profiles")
        _create_google_global_credentials(conn, "google_global_credentials")
        conn.execute(text("""
            INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at, google_credentials_encrypted)
            VALUES ('p1', 0, 0, datetime('now'), datetime('now'), 'encrypted-blob')
        """))
        conn.commit()

    _run_migrations(sqlite_engine, schema=None)
    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM google_global_credentials")).scalar()
        assert count == 1
        rows = conn.execute(text("SELECT google_credentials_encrypted FROM config_profiles")).fetchall()
        assert all(r[0] is None for r in rows)


def test_conversation_pin_schema_migrates_pre_column_sqlite_table_idempotently(
    sqlite_engine,
):
    """The additive migration owns the legacy-table path, not ``create_all``."""
    migration = getattr(database_module, "_migrate_conversation_pin_schema", None)
    assert migration is not None
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE user_sessions ("
                "id INTEGER PRIMARY KEY, session_id VARCHAR(64) NOT NULL)"
            )
        )

    for _ in range(2):
        with sqlite_engine.begin() as conn:
            inspector = inspect(conn)
            migration(
                conn,
                inspector,
                None,
                lambda table: f'"{table}"',
                True,
            )

    inspector = inspect(sqlite_engine)
    column = next(
        column
        for column in inspector.get_columns("user_sessions")
        if column["name"] == "graph_release_id"
    )
    assert column["nullable"] is True
    assert {index["name"] for index in inspector.get_indexes("user_sessions")} == {
        "ix_user_sessions_graph_release_id"
    }


def test_shared_deck_mutation_schema_backfills_legacy_sqlite_rows_once(
    sqlite_engine,
):
    """Break caught: additive migration skips legacy identities/table or rewrites UUIDs."""
    migration = getattr(database_module, "_migrate_shared_deck_mutation_schema", None)
    assert migration is not None
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE user_sessions ("
                "id INTEGER PRIMARY KEY, session_id VARCHAR(64) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE session_slide_decks ("
                "id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL)"
            )
        )
        conn.execute(text("CREATE TABLE graph_release (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "INSERT INTO user_sessions (id, session_id) VALUES "
                "(1, 'legacy-root'), (2, 'legacy-actor')"
            )
        )
        conn.execute(
            text("INSERT INTO session_slide_decks (id, session_id) VALUES (10, 1)")
        )

    def run_migration():
        with sqlite_engine.begin() as conn:
            migration(
                conn,
                inspect(conn),
                None,
                lambda table: f'"{table}"',
                True,
            )

    run_migration()
    with sqlite_engine.connect() as conn:
        first = conn.execute(
            text(
                "SELECT "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = 1), "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = 2), "
                "(SELECT collaboration_identity FROM session_slide_decks WHERE id = 10)"
            )
        ).one()
    run_migration()
    with sqlite_engine.connect() as conn:
        second = conn.execute(
            text(
                "SELECT "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = 1), "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = 2), "
                "(SELECT collaboration_identity FROM session_slide_decks WHERE id = 10)"
            )
        ).one()

    assert second == first
    assert all(value is not None for value in first)
    inspector = inspect(sqlite_engine)
    assert "shared_deck_mutation_event" in inspector.get_table_names()
    index_columns = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("shared_deck_mutation_event")
    }
    assert (
        "root_deck_identity",
        "actor_session_identity",
        "graph_release_id",
    ) in index_columns
    assert (
        "root_session_identity",
        "actor_session_identity",
        "graph_release_id",
        "occurred_at",
    ) in index_columns


# ---------------------------------------------------------------------------
# collaboration_identity server-side generation (C-11 R1)
# ---------------------------------------------------------------------------
#
# ``collaboration_identity`` is ``nullable=False`` on both ``user_sessions`` and
# ``session_slide_decks``.  A Python-side ``default=uuid.uuid4`` fires only on an
# ORM-mapper insert, so every non-ORM writer — raw SQL, ``insert().values()``
# omitting the column, a bulk insert — violates the constraint.  The column needs
# a *server*-side default, on the fresh ``create_all`` shape and on the legacy
# shape the migration ALTERs into place.


def _raw_insert_session(conn, session_id: str) -> int:
    """Insert a ``user_sessions`` row through raw SQL, omitting the identity.

    Raw SQL is the point: it is the shape every non-ORM writer has, and the only
    shape that proves the default is enforced by the database rather than by the
    ORM mapper.
    """
    conn.execute(
        text(
            "INSERT INTO user_sessions "
            "(session_id, created_by, created_at, last_activity, is_processing) "
            "VALUES (:sid, 'raw@example.com', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, 0)"
        ),
        {"sid": session_id},
    )
    return conn.execute(
        text("SELECT id FROM user_sessions WHERE session_id = :sid"),
        {"sid": session_id},
    ).scalar()


def _raw_insert_deck(conn, owner_row_id: int) -> None:
    """Insert a ``session_slide_decks`` row through raw SQL, omitting the identity."""
    conn.execute(
        text(
            "INSERT INTO session_slide_decks "
            "(session_id, version, created_at, updated_at) "
            "VALUES (:owner, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"owner": owner_row_id},
    )


def _identities(conn, table: str) -> list:
    return [
        row[0]
        for row in conn.execute(
            text(f"SELECT collaboration_identity FROM {table} ORDER BY id")
        ).fetchall()
    ]


def test_collaboration_identity_column_declares_a_server_default_per_dialect():
    """Break caught: the default lives only in a startup migration, so the schema
    create_all() produces is wrong until a repair migration fixes it.

    The ORM column is the single source of truth here. On PostgreSQL the mutation
    migration also runs ``ALTER COLUMN ... SET DEFAULT gen_random_uuid()``, which
    masks a missing column default on that dialect alone — so a dialect-independent
    assertion on the column itself is what actually pins the invariant.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects import sqlite as sqlite_dialect
    from sqlalchemy.schema import CreateTable

    from src.database.models.session import SessionSlideDeck, UserSession

    for model in (UserSession, SessionSlideDeck):
        column = model.__table__.c.collaboration_identity
        assert column.nullable is False
        assert column.server_default is not None, (
            f"{model.__tablename__}.collaboration_identity has no server-side "
            "default; every non-ORM insert omitting it would violate NOT NULL"
        )
        # Python-side default retained too: an ORM insert still gets its UUID
        # without a RETURNING round-trip.
        assert column.default is not None

        postgres_ddl = str(
            CreateTable(model.__table__).compile(dialect=postgresql.dialect())
        )
        sqlite_ddl = str(
            CreateTable(model.__table__).compile(dialect=sqlite_dialect.dialect())
        )
        assert "collaboration_identity UUID DEFAULT gen_random_uuid() NOT NULL" in (
            postgres_ddl
        )
        assert (
            "collaboration_identity CHAR(32) DEFAULT "
            "(lower(hex(randomblob(16)))) NOT NULL"
        ) in sqlite_ddl


def test_collaboration_identity_is_server_generated_on_a_fresh_schema(sqlite_engine):
    """Break caught: the identity column carries only a Python-side ORM default, so
    every raw-SQL/bulk insert that omits it fails NOT NULL."""
    Base.metadata.create_all(bind=sqlite_engine)
    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.begin() as conn:
        first_owner = _raw_insert_session(conn, "raw-sess-1")
        second_owner = _raw_insert_session(conn, "raw-sess-2")
        _raw_insert_deck(conn, first_owner)
        _raw_insert_deck(conn, second_owner)

    with sqlite_engine.connect() as conn:
        session_identities = _identities(conn, "user_sessions")
        deck_identities = _identities(conn, "session_slide_decks")

    assert len(session_identities) == 2
    assert len(deck_identities) == 2
    for label, identities in (
        ("user_sessions", session_identities),
        ("session_slide_decks", deck_identities),
    ):
        assert all(value for value in identities), (
            f"{label}.collaboration_identity was not populated by the database "
            f"for a raw-SQL insert: {identities}"
        )
        assert len(set(identities)) == len(identities), (
            f"{label}.collaboration_identity is not distinct per row: {identities}"
        )

    # The column stays NOT NULL: the default is what makes the insert legal, not a
    # relaxed constraint.
    inspector = inspect(sqlite_engine)
    for table in ("user_sessions", "session_slide_decks"):
        column = next(
            column
            for column in inspector.get_columns(table)
            if column["name"] == "collaboration_identity"
        )
        assert column["nullable"] is False, (
            f"{table}.collaboration_identity must stay NOT NULL"
        )


def test_collaboration_identity_backfill_and_default_on_the_legacy_alter_path(
    sqlite_engine,
):
    """Break caught: the migration adds the column without backfilling historical rows
    with distinct identities, or leaves later non-ORM inserts with no identity."""
    migration = getattr(database_module, "_migrate_shared_deck_mutation_schema", None)
    assert migration is not None

    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE user_sessions ("
                "id INTEGER PRIMARY KEY, session_id VARCHAR(64) NOT NULL, "
                "created_by VARCHAR(255), created_at DATETIME, "
                "last_activity DATETIME, is_processing BOOLEAN)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE session_slide_decks ("
                "id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, "
                "version INTEGER, created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(text("CREATE TABLE graph_release (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "INSERT INTO user_sessions (id, session_id) VALUES "
                "(1, 'legacy-root'), (2, 'legacy-actor'), (3, 'legacy-third')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO session_slide_decks (id, session_id) VALUES "
                "(10, 1), (11, 2)"
            )
        )

    def run_migration():
        with sqlite_engine.begin() as conn:
            migration(conn, inspect(conn), None, lambda table: f'"{table}"', True)

    run_migration()

    with sqlite_engine.connect() as conn:
        backfilled_sessions = _identities(conn, "user_sessions")
        backfilled_decks = _identities(conn, "session_slide_decks")

    assert len(backfilled_sessions) == 3
    assert len(backfilled_decks) == 2
    for label, identities in (
        ("user_sessions", backfilled_sessions),
        ("session_slide_decks", backfilled_decks),
    ):
        assert all(value for value in identities), (
            f"legacy {label} rows were not backfilled: {identities}"
        )
        assert len(set(identities)) == len(identities), (
            f"legacy {label} rows share a backfilled identity: {identities}"
        )

    # A non-ORM insert AFTER the migration must also receive an identity; otherwise
    # every mutation on that row fails in shared_deck_attribution with
    # "collaboration identities must exist before mutation evidence".
    with sqlite_engine.begin() as conn:
        new_owner = _raw_insert_session(conn, "post-migration-sess")
        _raw_insert_deck(conn, new_owner)

    with sqlite_engine.connect() as conn:
        sessions_after = _identities(conn, "user_sessions")
        decks_after = _identities(conn, "session_slide_decks")

    assert len(sessions_after) == 4
    assert len(decks_after) == 3
    for label, identities in (
        ("user_sessions", sessions_after),
        ("session_slide_decks", decks_after),
    ):
        assert all(value for value in identities), (
            f"a post-migration raw insert into {label} got no identity: {identities}"
        )
        assert len(set(identities)) == len(identities), (
            f"{label} identities are not distinct after a raw insert: {identities}"
        )

    # Idempotent: a second pass neither rewrites existing identities nor raises.
    run_migration()
    with sqlite_engine.connect() as conn:
        assert _identities(conn, "user_sessions") == sessions_after
        assert _identities(conn, "session_slide_decks") == decks_after


# ---------------------------------------------------------------------------
# Deck Mode: user_sessions.deck_mode (spec 2026-10-22 §5.1, §6)
# ---------------------------------------------------------------------------
#
# NULL = not chosen yet (unlocked); 'agent' / 'legacy' = chosen and locked.  The
# run-once migration marks every row that predates the column 'legacy', and must
# never touch a row again: re-filling on a later boot would flip agent decks back to
# legacy and lock every unlocked deck as legacy (spec anti-goal 2).
#
# The helper tests hand-build the pre-column table and call the helper directly with
# a fresh inspector per run.  Going through create_all would prove nothing: the column
# would come from the ORM model, not the migration.

_DECK_MODE_QUAL = lambda table: f'"{table}"'  # noqa: E731 — what _run_migrations builds with no schema


def _deck_mode_migration():
    migration = getattr(database_module, "_migrate_deck_mode_schema", None)
    assert migration is not None, (
        "src.core.database._migrate_deck_mode_schema does not exist"
    )
    return migration


def _create_pre_deck_mode_sessions(engine, qualified_table: str = '"user_sessions"'):
    """A user_sessions table from before the column, holding two existing decks."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {qualified_table} ("
                "id INTEGER PRIMARY KEY, session_id VARCHAR(64) NOT NULL)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {qualified_table} (id, session_id) VALUES "
                "(1, 'old-deck-1'), (2, 'old-deck-2')"
            )
        )


def _run_deck_mode_migration(engine, migration, schema=None, qual=_DECK_MODE_QUAL):
    """One boot's worth of the helper: its own transaction and a fresh inspector."""
    with engine.begin() as conn:
        migration(conn, inspect(conn), schema, qual, True)


def _deck_modes_by_id(engine, qualified_table: str = '"user_sessions"') -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text(f"SELECT id, deck_mode FROM {qualified_table} ORDER BY id")
            ).fetchall()
        )


def _deck_mode_column(engine, schema=None):
    """The reflected ``deck_mode`` column of user_sessions, or None if absent."""
    return next(
        (
            column
            for column in inspect(engine).get_columns("user_sessions", schema=schema)
            if column["name"] == "deck_mode"
        ),
        None,
    )


def _assert_deck_mode_column_shape(column) -> None:
    assert column is not None, "user_sessions has no deck_mode column"
    assert column["nullable"] is True, "deck_mode must be nullable (NULL = unlocked)"
    assert isinstance(column["type"], String) and column["type"].length == 16, (
        f"deck_mode is {column['type']!r}, expected VARCHAR(16)"
    )


def test_deck_mode_migration_fills_existing_rows_with_legacy_and_leaves_new_rows_null(
    sqlite_engine,
):
    """Break caught: decks that predate the column are left unchosen (their next
    message would lock them as agent), or the fill outlives the migration as a
    default, so every deck created afterwards is born legacy and locked."""
    migration = _deck_mode_migration()
    _create_pre_deck_mode_sessions(sqlite_engine)

    _run_deck_mode_migration(sqlite_engine, migration)

    assert _deck_modes_by_id(sqlite_engine) == {1: "legacy", 2: "legacy"}

    # A deck created after the migration, by a writer that does not name the column.
    with sqlite_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO user_sessions (id, session_id) VALUES (3, 'new-deck')")
        )

    assert _deck_modes_by_id(sqlite_engine) == {1: "legacy", 2: "legacy", 3: None}
    _assert_deck_mode_column_shape(_deck_mode_column(sqlite_engine))


def test_deck_mode_migration_second_run_is_a_noop(sqlite_engine):
    """Break caught: the legacy fill runs outside the missing-column branch, so every
    boot flips agent decks back to legacy, or locks unlocked (NULL) decks as legacy."""
    migration = _deck_mode_migration()
    _create_pre_deck_mode_sessions(sqlite_engine)
    _run_deck_mode_migration(sqlite_engine, migration)

    # Between boots: deck 1 is chosen as agent, and an unchosen deck appears.
    with sqlite_engine.begin() as conn:
        conn.execute(text("UPDATE user_sessions SET deck_mode = 'agent' WHERE id = 1"))
        conn.execute(
            text(
                "INSERT INTO user_sessions (id, session_id) VALUES (3, 'unlocked-deck')"
            )
        )

    _run_deck_mode_migration(sqlite_engine, migration)  # the next boot

    assert _deck_modes_by_id(sqlite_engine) == {1: "agent", 2: "legacy", 3: None}


def test_deck_mode_is_null_on_a_fresh_create_all_schema(sqlite_engine):
    """Break caught: the ORM column carries a default/server default (new decks are
    born chosen), or the legacy fill runs even when the column already exists, so a
    fresh database's decks turn legacy on the next boot."""
    Base.metadata.create_all(bind=sqlite_engine)
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    with factory() as db:
        db.add(UserSession(session_id="orm-deck", created_by="owner@example.com"))
        db.commit()
    with sqlite_engine.begin() as conn:
        _raw_insert_session(conn, "raw-sql-deck")

    # Two boots over the fresh schema: the column exists, so neither may fill it.
    _run_migrations(sqlite_engine, schema=None)
    _run_migrations(sqlite_engine, schema=None)

    with factory() as db:
        reloaded = db.query(UserSession).filter_by(session_id="orm-deck").one()
        assert reloaded.deck_mode is None
    with sqlite_engine.connect() as conn:
        stored = dict(
            conn.execute(
                text("SELECT session_id, deck_mode FROM user_sessions")
            ).fetchall()
        )
    assert stored == {"orm-deck": None, "raw-sql-deck": None}

    column = _deck_mode_column(sqlite_engine)
    _assert_deck_mode_column_shape(column)
    assert column["default"] is None, (
        f"create_all gave deck_mode a server default: {column['default']!r}"
    )
    # The migration adds no index, so a create_all schema must not carry one either.
    indexed_columns = {
        name
        for index in inspect(sqlite_engine).get_indexes("user_sessions")
        for name in index["column_names"]
    }
    assert "deck_mode" not in indexed_columns


def test_run_migrations_wires_the_deck_mode_helper(sqlite_engine):
    """Break caught: the helper works when called directly but _run_migrations never
    calls it, so no existing database ever gains the column."""
    Base.metadata.create_all(bind=sqlite_engine)
    _run_migrations(sqlite_engine, schema=None)
    assert _deck_mode_column(sqlite_engine) is not None, (
        "create_all built no user_sessions.deck_mode: UserSession.deck_mode is missing"
    )
    with sqlite_engine.begin() as conn:
        _raw_insert_session(conn, "pre-column-deck-1")
        _raw_insert_session(conn, "pre-column-deck-2")

    # Return the table to its pre-column shape, keeping its rows.
    with sqlite_engine.begin() as conn:
        conn.execute(text("ALTER TABLE user_sessions DROP COLUMN deck_mode"))
    assert _deck_mode_column(sqlite_engine) is None, "DROP COLUMN left deck_mode"

    _run_migrations(sqlite_engine, schema=None)

    assert _deck_mode_column(sqlite_engine) is not None, (
        "_run_migrations did not re-add deck_mode: the helper is not wired in"
    )
    _assert_deck_mode_column_shape(_deck_mode_column(sqlite_engine))
    with sqlite_engine.connect() as conn:
        stored = dict(
            conn.execute(
                text("SELECT session_id, deck_mode FROM user_sessions")
            ).fetchall()
        )
    assert stored == {"pre-column-deck-1": "legacy", "pre-column-deck-2": "legacy"}


def test_deck_mode_migration_targets_the_configured_schema(sqlite_engine, tmp_path):
    """Break caught: the helper ignores ``schema``/``_qual`` and reads or writes a bare
    ``user_sessions``. Production passes LAKEBASE_SCHEMA and its qualifier, as for every
    sibling step, and one database can hold several environments' schemas.

    An attached SQLite database stands in for the configured schema.  The main database
    holds a second, already-migrated ``user_sessions`` (another environment's), which a
    bare name resolves to first: reading it says "nothing to do", ALTERing it fails, and
    UPDATEing it rewrites someone else's decks."""
    migration = _deck_mode_migration()
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                'CREATE TABLE "user_sessions" (id INTEGER PRIMARY KEY, '
                "session_id VARCHAR(64) NOT NULL, deck_mode VARCHAR(16))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO \"user_sessions\" (id, session_id, deck_mode) VALUES "
                "(1, 'other-env-unlocked', NULL), (2, 'other-env-agent', 'agent')"
            )
        )
    with sqlite_engine.connect() as conn:
        conn.execute(text(f"ATTACH DATABASE '{tmp_path / 'app.db'}' AS app_data"))
        conn.commit()
    schema_qual = lambda table: f'"app_data"."{table}"'  # noqa: E731
    _create_pre_deck_mode_sessions(sqlite_engine, schema_qual("user_sessions"))

    _run_deck_mode_migration(sqlite_engine, migration, "app_data", schema_qual)

    _assert_deck_mode_column_shape(_deck_mode_column(sqlite_engine, schema="app_data"))
    assert _deck_modes_by_id(sqlite_engine, schema_qual("user_sessions")) == {
        1: "legacy",
        2: "legacy",
    }
    # The other schema's decks are untouched.
    assert _deck_modes_by_id(sqlite_engine, '"main"."user_sessions"') == {
        1: None,
        2: "agent",
    }


def test_deck_mode_migration_rereads_the_live_schema_not_a_cached_inspector(
    sqlite_engine,
):
    """Break caught: the helper decides "column missing" from the caller's shared
    inspector. _run_migrations creates that inspector once per transaction and it
    caches columns, so after any earlier ALTER it can report deck_mode missing when
    it is not, re-running the ALTER (error) or the fill (agent decks become legacy)."""
    migration = _deck_mode_migration()
    _create_pre_deck_mode_sessions(sqlite_engine)

    with sqlite_engine.begin() as conn:
        shared = inspect(conn)
        shared.get_columns("user_sessions")  # caches the pre-column shape
        migration(conn, shared, None, _DECK_MODE_QUAL, True)
        conn.execute(text("UPDATE user_sessions SET deck_mode = 'agent' WHERE id = 1"))
        # The shared inspector still says deck_mode is missing; the table says not.
        migration(conn, shared, None, _DECK_MODE_QUAL, True)

    assert _deck_modes_by_id(sqlite_engine) == {1: "agent", 2: "legacy"}


def test_deck_mode_migration_is_a_noop_without_a_user_sessions_table(sqlite_engine):
    """Break caught: the helper lacks its siblings' reflection guards and raises when
    user_sessions cannot be reflected, aborting the whole migration transaction."""
    migration = _deck_mode_migration()

    _run_deck_mode_migration(sqlite_engine, migration)

    assert "user_sessions" not in inspect(sqlite_engine).get_table_names()

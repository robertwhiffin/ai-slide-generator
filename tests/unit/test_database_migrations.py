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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import src.database.models  # noqa: F401 - register models with Base
import src.core.database as database_module
from src.core.database import Base, _run_migrations, init_db


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

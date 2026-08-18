"""The two writer shapes that still bypassed the agent_config normalizer.

``tests/unit/test_style_exclusivity_persistence_boundary.py`` established the rule
at the column: a ``TypeDecorator`` bind hook every INSERT and UPDATE passes through,
so ``slide_style_id`` and ``design_system_id`` can never both be stored. A
cross-vendor review then confirmed core insert/update/executemany, ORM attribute
assignment, ``Query.update``, ``bulk_save_objects`` and ``merge`` all normalize —
and found exactly TWO shapes that do not:

1. **raw SQL** — ``conn.execute(text("INSERT ... "))``. A bind hook belongs to a
   COLUMN OBJECT, and raw SQL never mentions one: the text is handed to the driver
   as written, so nothing in SQLAlchemy is positioned to intervene. No Python-side
   hook can close this; only the database itself is downstream of every writer,
   which is why the fix is a TRIGGER.
2. **an ORM JSON column assigned a ``str``** — ``row.agent_config = '{"...": 1}'``.
   The bind hook DID run, but it returned early: the value is not a ``dict``, and
   the guard existed to let ``None`` and genuine non-JSON blobs through untouched.
   A JSON-object string is neither — it is the same config in transport form, so it
   is normalized by parsing, applying precedence, and re-serializing.

Both are proven against LIVE PostgreSQL, because both defects are about what the
DATABASE ends up holding. SQLite cannot stand in: the trigger is PL/pgSQL and must
be a clean no-op there, which is asserted separately by the SQLite suite staying
green.

Rule unchanged, and deliberately NOT a 422: DESIGN SYSTEM WINS, the slide style is
dropped, legacy both-set rows HEAL on write. Rejecting a both-set config would wedge
every legacy row on every save — the frontend PUTs the WHOLE config — and that
regression has already shipped once.

GATING. Skipped unless a real PostgreSQL answers. Point
``TELLR_TEST_POSTGRES_URL`` at a throwaway database to run these; absent that a
local default is probed and the module skips. Each test creates and drops its own
uniquely named database, so runs never collide and nothing is left behind.

All fixtures SYNTHETIC (invented ids and session names).
"""

import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 - register every model with Base.metadata
from src.core.database import Base, _run_migrations
from src.database.models.profile import ConfigProfile
from src.database.models.session import UserSession

_STYLE_ID = 7
_DS_ID = 9

#: Admin URL used to CREATE/DROP the throwaway per-test databases. Overridable so
#: a developer can point the suite at any reachable PostgreSQL.
_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
    """True when the admin URL answers, so the module can gate itself."""
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
        "the agent_config bypass-shape suite",
        allow_module_level=True,
    )


@pytest.fixture()
def pg_engine():
    """A migrated PostgreSQL database, dropped when the test finishes."""
    db_name = f"tellr_bypass_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    url = make_url(_ADMIN_URL).set(database=db_name)
    engine = create_engine(url)
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


def _both_set_json() -> str:
    """A both-set config as a hostile or legacy writer supplies it, serialized."""
    return json.dumps({"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID})


def _stored(engine, table, where_sql, params):
    """The agent_config as POSTGRES holds it, read back with raw SQL.

    Never through the ORM attribute: that measures the test's own in-memory input.
    A ``str`` is parsed, so a row stored in transport form is still comparable —
    the point of the assertion is the AUTHORITIES, not the encoding.
    """
    with engine.connect() as conn:
        raw = conn.execute(
            text(f"SELECT agent_config FROM {table} WHERE {where_sql}"), params
        ).scalar()
    if raw is None:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


def _authorities(stored):
    """Which style authorities survived into the stored blob."""
    if stored is None:
        return []
    return [
        field
        for field in ("slide_style_id", "design_system_id")
        if stored.get(field) is not None
    ]


def _assert_design_system_won(stored, *, writer):
    assert stored is not None, f"{writer}: nothing was stored"
    assert _authorities(stored) == ["design_system_id"], (
        f"{writer} persisted BOTH style authorities: {stored!r}. The design system "
        "must win and the slide style must be dropped."
    )
    assert stored.get("design_system_id") == _DS_ID, (
        f"{writer}: the design system must survive, got {stored!r}"
    )


def _insert_session_raw(engine, session_id, config_json):
    """INSERT a session with raw SQL — the shape no bind hook can see."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO user_sessions "
                "(session_id, created_at, last_activity, is_processing, agent_config) "
                "VALUES (:sid, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, FALSE, "
                "CAST(:cfg AS json))"
            ),
            {"sid": session_id, "cfg": config_json},
        )


class TestRawSqlIsNormalized:
    """Shape 1: raw ``text()`` SQL, which reaches no Python-side hook at all."""

    def test_raw_sql_insert(self, pg_engine):
        _insert_session_raw(pg_engine, "raw-insert", _both_set_json())

        _assert_design_system_won(
            _stored(
                pg_engine,
                "user_sessions",
                "session_id = :sid",
                {"sid": "raw-insert"},
            ),
            writer="raw SQL INSERT",
        )

    def test_raw_sql_update(self, pg_engine):
        """An UPDATE must heal too — the trigger fires BEFORE INSERT OR UPDATE."""
        _insert_session_raw(pg_engine, "raw-update", json.dumps({"tools": []}))
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE user_sessions SET agent_config = CAST(:cfg AS json) "
                    "WHERE session_id = :sid"
                ),
                {"sid": "raw-update", "cfg": _both_set_json()},
            )

        _assert_design_system_won(
            _stored(
                pg_engine,
                "user_sessions",
                "session_id = :sid",
                {"sid": "raw-update"},
            ),
            writer="raw SQL UPDATE",
        )

    def test_raw_sql_on_the_profile_column(self, pg_engine):
        """Both agent_config columns carry the rule, not just the session one."""
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO config_profiles "
                    "(name, is_default, is_deleted, created_at, updated_at, "
                    "llm_judge_backend, agent_config) "
                    "VALUES (:n, FALSE, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                    "'mlflow', CAST(:cfg AS json))"
                ),
                {"n": "raw-profile", "cfg": _both_set_json()},
            )

        _assert_design_system_won(
            _stored(
                pg_engine, "config_profiles", "name = :n", {"n": "raw-profile"}
            ),
            writer="raw SQL INSERT (config_profiles)",
        )

    def test_a_config_with_only_one_authority_is_untouched(self, pg_engine):
        """The trigger repairs the contradiction and NOTHING else."""
        only_style = json.dumps({"slide_style_id": _STYLE_ID, "tools": ["a"]})
        _insert_session_raw(pg_engine, "raw-one-authority", only_style)

        stored = _stored(
            pg_engine,
            "user_sessions",
            "session_id = :sid",
            {"sid": "raw-one-authority"},
        )
        assert stored == {"slide_style_id": _STYLE_ID, "tools": ["a"]}, (
            f"a config with ONE authority must be stored byte-for-byte: {stored!r}"
        )

    def test_unknown_keys_survive_the_trigger(self, pg_engine):
        """A key a newer writer stored must not be destroyed by the repair."""
        _insert_session_raw(
            pg_engine,
            "raw-unknown-keys",
            json.dumps(
                {
                    "slide_style_id": _STYLE_ID,
                    "design_system_id": _DS_ID,
                    "a_key_no_model_knows": {"nested": [1, 2]},
                }
            ),
        )

        stored = _stored(
            pg_engine,
            "user_sessions",
            "session_id = :sid",
            {"sid": "raw-unknown-keys"},
        )
        _assert_design_system_won(stored, writer="raw SQL INSERT (unknown keys)")
        assert stored["a_key_no_model_knows"] == {"nested": [1, 2]}, (
            f"the trigger destroyed an unknown key: {stored!r}"
        )

    def test_a_non_object_json_value_is_passed_through(self, pg_engine):
        """A JSON scalar/array is not a config; the trigger must not touch it."""
        _insert_session_raw(pg_engine, "raw-json-array", json.dumps([1, 2, 3]))

        assert _stored(
            pg_engine,
            "user_sessions",
            "session_id = :sid",
            {"sid": "raw-json-array"},
        ) == [1, 2, 3]

    def test_a_null_config_stays_null(self, pg_engine):
        """NULL means "no config at all", which is not an empty config."""
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user_sessions "
                    "(session_id, created_at, last_activity, is_processing, "
                    "agent_config) VALUES (:sid, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, FALSE, NULL)"
                ),
                {"sid": "raw-null"},
            )

        with pg_engine.connect() as conn:
            raw = conn.execute(
                text(
                    "SELECT agent_config FROM user_sessions WHERE session_id = :sid"
                ),
                {"sid": "raw-null"},
            ).scalar()
        assert raw is None


class TestJsonObjectStringIsNormalized:
    """Shape 2: an ORM JSON column handed a ``str`` instead of a ``dict``."""

    def test_orm_attribute_assigned_a_json_object_string(self, pg_engine):
        db = sessionmaker(bind=pg_engine)()
        try:
            row = UserSession(session_id="orm-str")
            row.agent_config = _both_set_json()
            db.add(row)
            db.commit()
        finally:
            db.close()

        _assert_design_system_won(
            _stored(
                pg_engine, "user_sessions", "session_id = :sid", {"sid": "orm-str"}
            ),
            writer="ORM attribute assigned a JSON-object string",
        )

    def test_profile_column_assigned_a_json_object_string(self, pg_engine):
        db = sessionmaker(bind=pg_engine)()
        try:
            profile = ConfigProfile(name="orm-str-profile")
            profile.agent_config = _both_set_json()
            db.add(profile)
            db.commit()
        finally:
            db.close()

        _assert_design_system_won(
            _stored(
                pg_engine,
                "config_profiles",
                "name = :n",
                {"n": "orm-str-profile"},
            ),
            writer="ORM profile attribute assigned a JSON-object string",
        )

    def test_a_non_json_string_is_passed_through_unchanged(self, pg_engine):
        """A blob that is not JSON at all is not a config — store it as given.

        The bind hook must NEVER raise on input it cannot parse: a 500 on a write
        path is a worse failure than storing the caller's own bytes.
        """
        db = sessionmaker(bind=pg_engine)()
        try:
            row = UserSession(session_id="orm-not-json")
            row.agent_config = "not json at all {{{"
            db.add(row)
            db.commit()
        finally:
            db.close()

        with pg_engine.connect() as conn:
            raw = conn.execute(
                text(
                    "SELECT agent_config::text FROM user_sessions "
                    "WHERE session_id = :sid"
                ),
                {"sid": "orm-not-json"},
            ).scalar()
        assert "not json at all" in raw

    def test_malformed_json_does_not_raise(self, pg_engine):
        """Truncated JSON must pass through, not 500."""
        db = sessionmaker(bind=pg_engine)()
        try:
            row = UserSession(session_id="orm-malformed")
            row.agent_config = '{"slide_style_id": 7, "design_system_id":'
            db.add(row)
            db.commit()
        finally:
            db.close()

        with pg_engine.connect() as conn:
            raw = conn.execute(
                text(
                    "SELECT agent_config::text FROM user_sessions "
                    "WHERE session_id = :sid"
                ),
                {"sid": "orm-malformed"},
            ).scalar()
        assert "design_system_id" in raw


class TestTriggerIsIdempotent:
    """The migration must converge from ANY starting state, run any number of times.

    The cautionary tale is on this branch already: two brand-text column migrations
    treated the post-migration state as "needs migrating" and fought each other, so
    the schema OSCILLATED between runs instead of converging, and could abort
    startup once real data existed.
    """

    def test_running_the_migration_repeatedly_converges(self, pg_engine):
        before = _trigger_names(pg_engine)
        for _ in range(3):
            _run_migrations(pg_engine)
        assert _trigger_names(pg_engine) == before, (
            "re-running the migration changed the trigger set — it must converge"
        )

    def test_the_rule_still_holds_after_repeated_migration(self, pg_engine):
        for _ in range(3):
            _run_migrations(pg_engine)

        _insert_session_raw(pg_engine, "raw-after-remigrate", _both_set_json())

        _assert_design_system_won(
            _stored(
                pg_engine,
                "user_sessions",
                "session_id = :sid",
                {"sid": "raw-after-remigrate"},
            ),
            writer="raw SQL INSERT after three migration runs",
        )

    def test_the_trigger_exists_on_both_agent_config_tables(self, pg_engine):
        tables = {table for table, _ in _trigger_rows(pg_engine)}
        assert tables == {"user_sessions", "config_profiles"}, (
            f"the trigger must cover BOTH agent_config columns, found {tables}"
        )

    def test_the_migration_converges_from_a_missing_trigger(self, pg_engine):
        """Dropping the trigger and re-migrating must restore it.

        Convergence "from any starting state" includes the state a database is in
        before the migration has ever run.
        """
        for table, trigger in _trigger_rows(pg_engine):
            with pg_engine.begin() as conn:
                conn.execute(text(f'DROP TRIGGER "{trigger}" ON "{table}"'))
        assert _trigger_rows(pg_engine) == []

        _run_migrations(pg_engine)

        assert {table for table, _ in _trigger_rows(pg_engine)} == {
            "user_sessions",
            "config_profiles",
        }


def _trigger_rows(engine):
    """``(table, trigger)`` for every agent-config precedence trigger present."""
    with engine.connect() as conn:
        return [
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT c.relname, t.tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "WHERE NOT t.tgisinternal "
                    "AND t.tgname LIKE '%agent_config%' "
                    "ORDER BY c.relname, t.tgname"
                )
            ).fetchall()
        ]


def _trigger_names(engine):
    return sorted(_trigger_rows(engine))

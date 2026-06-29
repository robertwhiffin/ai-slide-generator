"""Regression tests for the llm_judge_backend SET DEFAULT migration.

Root cause (devloop branching investigation, 2026-06-29): the migration issued
`ALTER TABLE config_profiles ALTER COLUMN llm_judge_backend SET DEFAULT 'mlflow'`
unconditionally whenever the column existed — even when the default was already
'mlflow'. That needless ownership-gated DDL fails on a copy-on-write branch
(app SP isn't the table owner), and the swallowing try/except left the shared
migration transaction poisoned, breaking every later migration.

The fix: only ALTER when the default is NOT already correct, and wrap the ALTER
in a SAVEPOINT so a failure cannot abort the outer transaction.
"""
from unittest.mock import MagicMock

from src.core.database import _ensure_llm_judge_backend_default


def _executed_sql(conn):
    return [str(c.args[0]) for c in conn.execute.call_args_list]


def test_skips_alter_when_default_already_mlflow():
    """Same-schema fork: default already correct -> no DDL emitted."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = "'mlflow'::character varying"

    _ensure_llm_judge_backend_default(
        conn, "config_profiles",
        '"app_data_prod"."config_profiles"', "app_data_prod", is_sqlite=False,
    )

    sql = _executed_sql(conn)
    assert any("information_schema.columns" in s for s in sql), "should check current default"
    assert not any("SET DEFAULT" in s for s in sql), "must NOT re-issue the ALTER when already correct"
    conn.begin_nested.assert_not_called()


def test_issues_alter_in_savepoint_when_default_missing():
    """Legit backfill: default missing -> ALTER, wrapped in a savepoint."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = None

    _ensure_llm_judge_backend_default(
        conn, "config_profiles",
        '"app_data_prod"."config_profiles"', "app_data_prod", is_sqlite=False,
    )

    sql = _executed_sql(conn)
    assert any("SET DEFAULT" in s for s in sql), "should ALTER when default is missing"
    conn.begin_nested.assert_called_once(), "ALTER must run inside a SAVEPOINT so a failure can't poison the txn"


def test_noop_on_sqlite():
    """SQLite manages the default at column creation; nothing to do."""
    conn = MagicMock()
    _ensure_llm_judge_backend_default(
        conn, "config_profiles", '"config_profiles"', None, is_sqlite=True,
    )
    conn.execute.assert_not_called()


def test_swallowed_alter_failure_does_not_propagate():
    """If the ALTER fails (e.g. non-owner on a fork), it is contained, not raised."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = None
    # Make the ALTER (the execute call inside begin_nested) raise.
    def execute_side_effect(stmt, *a, **k):
        if "SET DEFAULT" in str(stmt):
            raise Exception("must be owner of table config_profiles")
        m = MagicMock()
        m.scalar.return_value = None
        return m
    conn.execute.side_effect = execute_side_effect

    # Must NOT raise.
    _ensure_llm_judge_backend_default(
        conn, "config_profiles",
        '"app_data_prod"."config_profiles"', "app_data_prod", is_sqlite=False,
    )

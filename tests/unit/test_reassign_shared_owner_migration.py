from unittest.mock import MagicMock
from src.core.database import _reassign_new_objects_to_shared_owner


def _conn_role_exists(exists: bool):
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = 1 if exists else None
    return conn


def test_noop_on_sqlite():
    conn = MagicMock()
    _reassign_new_objects_to_shared_owner(conn, is_sqlite=True)
    conn.execute.assert_not_called()


def test_noop_when_role_absent():
    conn = _conn_role_exists(False)
    _reassign_new_objects_to_shared_owner(conn, is_sqlite=False)
    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert "REASSIGN OWNED" not in sql
    conn.begin_nested.assert_not_called()


def test_reassign_runs_in_savepoint_when_role_present():
    conn = _conn_role_exists(True)
    _reassign_new_objects_to_shared_owner(conn, is_sqlite=False)
    conn.begin_nested.assert_called_once()
    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert 'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"' in sql

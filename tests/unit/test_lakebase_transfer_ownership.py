from unittest.mock import MagicMock, patch
import scripts.lakebase_transfer_ownership as t


def _cur_with_owner(owner):
    cur = MagicMock()
    # schema_owner -> fetchone returns (owner,)
    cur.fetchone.return_value = (owner,) if owner else None
    return cur


def test_operator_setup_emits_create_and_grants():
    cur = MagicMock()
    cur.fetchone.return_value = None  # role does not exist yet
    t.operator_setup(cur, "tellr_app_owners", "gid", "oid")
    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert 'CREATE ROLE "tellr_app_owners" NOLOGIN' in executed
    assert 'GRANT "tellr_app_owners" TO "gid" WITH ADMIN OPTION, INHERIT FALSE' in executed
    assert 'GRANT "tellr_app_owners" TO "oid" WITH INHERIT TRUE' in executed


def test_operator_setup_skips_create_when_role_exists():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)  # role exists
    t.operator_setup(cur, "tellr_app_owners", "gid", "oid")
    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert 'CREATE ROLE "tellr_app_owners" NOLOGIN' not in executed


def test_reassign_as_owner_emits_reassign_then_alter_schema():
    cur = MagicMock()
    t.reassign_as_owner(cur, "tellr_app_owners", "app_data_prod")
    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert executed == [
        'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"',
        'ALTER SCHEMA "app_data_prod" OWNER TO "tellr_app_owners"',
    ]


def test_run_transfer_noops_when_already_shared_owned():
    ws = MagicMock()
    op_conn = MagicMock()
    op_conn.cursor.return_value.__enter__.return_value = _cur_with_owner("tellr_app_owners")
    with patch.object(t, "_open_operator_conn", return_value=op_conn), \
         patch.object(t, "_open_sp_conn") as sp_open:
        result = t.run_transfer(
            ws=ws, owner_sp_id="oid", granter_sp_id="gid", sp_token="tok",
            owning_role="tellr_app_owners", schema="app_data_prod",
            database="db-tellr", confirm=True,
        )
    assert result == "noop"
    sp_open.assert_not_called()  # never connect as the SP if nothing to do


def test_run_transfer_runs_setup_then_reassign():
    ws = MagicMock()
    op_cur = _cur_with_owner("some-prod-sp")   # not yet shared-owned
    op_conn = MagicMock()
    op_conn.cursor.return_value.__enter__.return_value = op_cur
    sp_cur = MagicMock()
    sp_conn = MagicMock()
    sp_conn.cursor.return_value.__enter__.return_value = sp_cur
    with patch.object(t, "_open_operator_conn", return_value=op_conn), \
         patch.object(t, "_open_sp_conn", return_value=sp_conn):
        result = t.run_transfer(
            ws=ws, owner_sp_id="oid", granter_sp_id="gid", sp_token="tok",
            owning_role="tellr_app_owners", schema="app_data_prod",
            database="db-tellr", confirm=True,
        )
    assert result == "transferred"
    op_executed = [c.args[0] for c in op_cur.execute.call_args_list]
    assert 'GRANT "tellr_app_owners" TO "gid" WITH ADMIN OPTION, INHERIT FALSE' in op_executed
    sp_executed = [c.args[0] for c in sp_cur.execute.call_args_list]
    assert 'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"' in sp_executed

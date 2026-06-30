from unittest.mock import MagicMock, patch

import scripts.lakebase_grant_owner_role as g


def test_grant_member_emits_inherit_true_grant():
    cur = MagicMock()
    g.grant_member(cur, "tellr_app_owners", "new-sp")
    cur.execute.assert_called_once_with('GRANT "tellr_app_owners" TO "new-sp" WITH INHERIT TRUE')


def test_run_grant_connects_as_granter_and_grants():
    ws = MagicMock()
    ws.postgres.generate_database_credential.return_value.token = "tok"
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    with patch.object(g.psycopg2, "connect", return_value=conn) as connect:
        g.run_grant(
            ws=ws, new_sp_id="new-sp", host="h.example", endpoint_name="ep",
            granter_sp_id="gid", owning_role="tellr_app_owners",
        )
    ws.postgres.generate_database_credential.assert_called_once_with(endpoint="ep")
    kwargs = connect.call_args.kwargs
    assert kwargs["host"] == "h.example" and kwargs["user"] == "gid" and kwargs["password"] == "tok"
    cur.execute.assert_called_once_with('GRANT "tellr_app_owners" TO "new-sp" WITH INHERIT TRUE')

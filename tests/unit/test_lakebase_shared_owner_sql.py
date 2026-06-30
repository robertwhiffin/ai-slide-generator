# tests/unit/test_lakebase_shared_owner_sql.py
from unittest.mock import MagicMock
import scripts.lakebase_shared_owner_sql as m


def test_sql_builders_exact_strings():
    assert m.OWNING_ROLE == "tellr_app_owners"
    assert m.sql_create_owning_role() == 'CREATE ROLE "tellr_app_owners" NOLOGIN'
    assert (
        m.sql_grant_admin("tellr_app_owners", "gid")
        == 'GRANT "tellr_app_owners" TO "gid" WITH ADMIN OPTION, INHERIT FALSE'
    )
    assert (
        m.sql_grant_member("tellr_app_owners", "sid")
        == 'GRANT "tellr_app_owners" TO "sid" WITH INHERIT TRUE'
    )
    assert m.sql_reassign_owned("tellr_app_owners") == 'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"'
    assert (
        m.sql_alter_schema_owner("app_data_prod", "tellr_app_owners")
        == 'ALTER SCHEMA "app_data_prod" OWNER TO "tellr_app_owners"'
    )


def test_owning_role_exists_true_false():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    assert m.owning_role_exists(cur) is True
    cur.fetchone.return_value = None
    assert m.owning_role_exists(cur) is False


def test_schema_owner_and_shared_owned():
    cur = MagicMock()
    cur.fetchone.return_value = ("tellr_app_owners",)
    assert m.schema_owner(cur, "app_data_prod") == "tellr_app_owners"
    assert m.schema_is_shared_owned(cur, "app_data_prod") is True
    cur.fetchone.return_value = ("161834b3-...",)
    assert m.schema_is_shared_owned(cur, "app_data_prod") is False
    cur.fetchone.return_value = None
    assert m.schema_owner(cur, "app_data_prod") is None
    assert m.schema_is_shared_owned(cur, "app_data_prod") is False

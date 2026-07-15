"""CRITICAL-3 (SDR-4437): deploy-time relocation of the Fernet key into Lakebase."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import (
    DeploymentError,
    _migrate_encryption_key_to_lakebase,
    _read_existing_encryption_key,
)

KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
OTHER_KEY = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
CLIENT_ID = "12345678-abcd-abcd-0123-456789abcdef"
SCHEMA = "app_data_prod"


def _cursor(existing_key=None):
    cur = MagicMock()
    cur.fetchone.return_value = (existing_key,) if existing_key else (KEY,)
    return cur


class TestMigrateEncryptionKey:
    def test_fresh_migration_creates_seeds_and_grants(self):
        cur = _cursor(existing_key=KEY)
        _migrate_encryption_key_to_lakebase(cur, SCHEMA, CLIENT_ID, KEY)

        sql = [str(c.args[0]) for c in cur.execute.call_args_list]
        assert any("CREATE TABLE IF NOT EXISTS" in s and "encryption_keys" in s for s in sql)
        assert any("INSERT INTO" in s and "ON CONFLICT (id) DO NOTHING" in s for s in sql)
        assert any(
            "GRANT SELECT, INSERT" in s and f'TO "{CLIENT_ID}"' in s for s in sql
        )

    def test_rerun_with_same_key_is_noop(self):
        cur = _cursor(existing_key=KEY)
        # Must not raise: INSERT no-ops, read-back equals the app.yaml key.
        _migrate_encryption_key_to_lakebase(cur, SCHEMA, CLIENT_ID, KEY)

    def test_mismatched_existing_key_hard_fails_before_grant(self):
        cur = _cursor(existing_key=OTHER_KEY)
        # match is case-sensitive re.search; the message says "DIFFERENT key"
        with pytest.raises(DeploymentError, match="DIFFERENT key"):
            _migrate_encryption_key_to_lakebase(cur, SCHEMA, CLIENT_ID, KEY)
        sql = [str(c.args[0]) for c in cur.execute.call_args_list]
        assert not any("GRANT" in s for s in sql)

    def test_missing_client_id_seeds_but_skips_grant(self):
        cur = _cursor(existing_key=KEY)
        _migrate_encryption_key_to_lakebase(cur, SCHEMA, None, KEY)
        sql = [str(c.args[0]) for c in cur.execute.call_args_list]
        assert any("INSERT INTO" in s for s in sql)
        assert not any("GRANT" in s for s in sql)

    def test_bad_schema_rejected_before_any_ddl(self):
        cur = MagicMock()
        with pytest.raises(ValueError):
            _migrate_encryption_key_to_lakebase(
                cur, 'x"; DROP SCHEMA y; --', CLIENT_ID, KEY
            )
        cur.execute.assert_not_called()

    def test_bad_client_id_rejected_before_grant(self):
        cur = _cursor(existing_key=KEY)
        with pytest.raises(ValueError):
            _migrate_encryption_key_to_lakebase(cur, SCHEMA, '"; GRANT ALL --', KEY)


class TestReadExistingEncryptionKeyStrict:
    def test_returns_none_when_entry_absent(self):
        ws = MagicMock()
        resp = MagicMock()
        resp.read.return_value = b"env:\n  - name: OTHER\n    value: x\n"
        ws.workspace.download.return_value = resp
        assert _read_existing_encryption_key(ws, "/Workspace/x") is None

    def test_returns_key_when_present(self):
        ws = MagicMock()
        resp = MagicMock()
        resp.read.return_value = (
            b"env:\n  - name: GOOGLE_OAUTH_ENCRYPTION_KEY\n    value: " + KEY.encode() + b"\n"
        )
        ws.workspace.download.return_value = resp
        assert _read_existing_encryption_key(ws, "/Workspace/x") == KEY

    def test_download_failure_raises_instead_of_none(self):
        """Silently returning None here would skip the migration and orphan
        ciphertext when the new code boots and generates a fresh key."""
        ws = MagicMock()
        ws.workspace.download.side_effect = OSError("network")
        with pytest.raises(DeploymentError, match="app.yaml"):
            _read_existing_encryption_key(ws, "/Workspace/x")


class TestUpdateDatabricksWiring:
    @patch("databricks_tellr.deploy._get_workspace_client")
    @patch("databricks_tellr.deploy._get_or_create_lakebase")
    @patch("databricks_tellr.deploy._check_breaking_migrations")
    @patch("databricks_tellr.deploy._read_existing_encryption_key", return_value=KEY)
    @patch("databricks_tellr.deploy._get_lakebase_connection")
    @patch("databricks_tellr.deploy._migrate_encryption_key_to_lakebase")
    @patch("databricks_tellr.deploy._write_requirements")
    @patch("databricks_tellr.deploy._write_app_yaml")
    @patch("databricks_tellr.deploy._upload_files")
    def test_migration_runs_before_upload_and_key_not_passed_to_app_yaml(
        self, mock_upload, mock_yaml, mock_reqs, mock_migrate,
        mock_conn, mock_read, mock_check, mock_lakebase, mock_ws_factory,
    ):
        from databricks_tellr.deploy import _update_databricks

        ws = MagicMock()
        mock_ws_factory.return_value = ws
        mock_lakebase.return_value = {"type": "provisioned", "name": "lb"}
        conn = MagicMock()
        mock_conn.return_value = (conn, "me@x.com")
        ws.apps.get.return_value = MagicMock(
            service_principal_client_id=CLIENT_ID, url="https://app"
        )

        manager = MagicMock()
        manager.attach_mock(mock_migrate, "migrate")
        manager.attach_mock(mock_upload, "upload")

        _update_databricks(
            app_name="app", app_file_workspace_path="/Workspace/x",
            lakebase_name="lb", schema_name=SCHEMA,
        )

        # migration strictly precedes upload (order is load-bearing)
        names = [c[0] for c in manager.mock_calls if c[0] in ("migrate", "upload")]
        assert names.index("migrate") < names.index("upload")
        # app.yaml writer no longer receives a key
        assert "encryption_key" not in mock_yaml.call_args.kwargs

    @patch("databricks_tellr.deploy._get_workspace_client")
    @patch("databricks_tellr.deploy._get_or_create_lakebase")
    @patch("databricks_tellr.deploy._check_breaking_migrations")
    @patch("databricks_tellr.deploy._read_existing_encryption_key", return_value=None)
    @patch("databricks_tellr.deploy._migrate_encryption_key_to_lakebase")
    @patch("databricks_tellr.deploy._write_requirements")
    @patch("databricks_tellr.deploy._write_app_yaml")
    @patch("databricks_tellr.deploy._upload_files")
    def test_no_key_in_deployed_yaml_skips_migration(
        self, mock_upload, mock_yaml, mock_reqs, mock_migrate,
        mock_read, mock_check, mock_lakebase, mock_ws_factory,
    ):
        from databricks_tellr.deploy import _update_databricks

        ws = MagicMock()
        mock_ws_factory.return_value = ws
        mock_lakebase.return_value = {"type": "provisioned", "name": "lb"}
        ws.apps.get.return_value = MagicMock(url="https://app")

        _update_databricks(
            app_name="app", app_file_workspace_path="/Workspace/x",
            lakebase_name="lb", schema_name=SCHEMA,
        )
        mock_migrate.assert_not_called()

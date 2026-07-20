"""CRITICAL-3 (SDR-4437): deploy-time relocation of the Fernet key into Lakebase."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import (
    DeploymentError,
    _read_existing_encryption_key,
)

KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
OTHER_KEY = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
CLIENT_ID = "12345678-abcd-abcd-0123-456789abcdef"
SCHEMA = "app_data_prod"


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


class TestUpdateDatabricksCarryForward:
    @patch("databricks_tellr.deploy._get_workspace_client")
    @patch("databricks_tellr.deploy._get_or_create_lakebase")
    @patch("databricks_tellr.deploy._check_breaking_migrations")
    @patch("databricks_tellr.deploy._read_existing_encryption_key", return_value=KEY)
    @patch("databricks_tellr.deploy._write_requirements")
    @patch("databricks_tellr.deploy._write_app_yaml")
    @patch("databricks_tellr.deploy._upload_files")
    def test_legacy_key_is_carried_into_app_yaml(
        self, mock_upload, mock_yaml, mock_reqs, mock_read,
        mock_check, mock_lakebase, mock_ws_factory,
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
        # key is carried forward into the regenerated app.yaml
        assert mock_yaml.call_args.kwargs.get("encryption_key") == KEY

    @patch("databricks_tellr.deploy._get_workspace_client")
    @patch("databricks_tellr.deploy._get_or_create_lakebase")
    @patch("databricks_tellr.deploy._check_breaking_migrations")
    @patch("databricks_tellr.deploy._read_existing_encryption_key", return_value=None)
    @patch("databricks_tellr.deploy._write_requirements")
    @patch("databricks_tellr.deploy._write_app_yaml")
    @patch("databricks_tellr.deploy._upload_files")
    def test_no_legacy_key_writes_keyless(
        self, mock_upload, mock_yaml, mock_reqs, mock_read,
        mock_check, mock_lakebase, mock_ws_factory,
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
        # keyless: encryption_key is None (or absent)
        assert not mock_yaml.call_args.kwargs.get("encryption_key")

    def test_migrate_function_is_removed(self):
        """The deploy-time DDL relocation is gone; boot owns migration now."""
        import databricks_tellr.deploy as d
        assert not hasattr(d, "_migrate_encryption_key_to_lakebase")


class TestWriteAppYamlKeyBlock:
    def _read_yaml(self, staging):
        import yaml
        return yaml.safe_load((staging / "app.yaml").read_text())

    def test_keyless_when_no_key(self, tmp_path):
        from databricks_tellr.deploy import _write_app_yaml
        _write_app_yaml(
            tmp_path, "lb", SCHEMA,
            lakebase_result={"type": "provisioned"},
        )
        parsed = self._read_yaml(tmp_path)
        names = [e["name"] for e in parsed["env"]]
        assert "GOOGLE_OAUTH_ENCRYPTION_KEY" not in names

    def test_emits_entry_when_key_present(self, tmp_path):
        from databricks_tellr.deploy import _write_app_yaml
        _write_app_yaml(
            tmp_path, "lb", SCHEMA,
            lakebase_result={"type": "provisioned"},
            encryption_key=KEY,
        )
        parsed = self._read_yaml(tmp_path)
        entry = next(
            e for e in parsed["env"] if e["name"] == "GOOGLE_OAUTH_ENCRYPTION_KEY"
        )
        assert entry["value"] == KEY

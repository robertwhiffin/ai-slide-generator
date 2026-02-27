"""Tests for Lakebase utility functions with autoscaling support.

Covers the dual-path logic in lakebase.py:
- generate_lakebase_credential(): autoscaling vs provisioned credential generation
- get_lakebase_connection_info(): connection info assembly
- get_lakebase_connection_url(): URL construction with schema support
"""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.lakebase import (
    LakebaseError,
    generate_lakebase_credential,
    get_lakebase_connection_info,
    get_lakebase_connection_url,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ws():
    """Mocked WorkspaceClient with postgres and database services."""
    ws = MagicMock()
    ws.current_user.me.return_value = Mock(user_name="test@example.com")
    return ws


# ---------------------------------------------------------------------------
# generate_lakebase_credential
# ---------------------------------------------------------------------------

class TestGenerateLakebaseCredential:
    """Tests for dual-path credential generation."""

    def test_autoscaling_uses_postgres_api(self, mock_ws):
        cred = Mock()
        cred.token = "auto-token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        token = generate_lakebase_credential(
            "test-instance", client=mock_ws,
            endpoint_name="ep-name", lakebase_type="autoscaling",
        )

        assert token == "auto-token"
        mock_ws.postgres.generate_database_credential.assert_called_once_with(endpoint="ep-name")
        mock_ws.database.generate_database_credential.assert_not_called()

    def test_provisioned_uses_database_api(self, mock_ws):
        cred = Mock()
        cred.token = "prov-token"
        mock_ws.database.generate_database_credential.return_value = cred

        token = generate_lakebase_credential(
            "test-instance", client=mock_ws, lakebase_type="provisioned",
        )

        assert token == "prov-token"
        mock_ws.database.generate_database_credential.assert_called_once()
        mock_ws.postgres.generate_database_credential.assert_not_called()

    def test_defaults_to_provisioned(self, mock_ws):
        cred = Mock()
        cred.token = "prov-token"
        mock_ws.database.generate_database_credential.return_value = cred

        token = generate_lakebase_credential("test-instance", client=mock_ws)

        assert token == "prov-token"
        mock_ws.database.generate_database_credential.assert_called_once()

    def test_autoscaling_without_endpoint_uses_provisioned(self, mock_ws):
        """When lakebase_type=autoscaling but endpoint_name is None, falls back to provisioned."""
        cred = Mock()
        cred.token = "prov-token"
        mock_ws.database.generate_database_credential.return_value = cred

        token = generate_lakebase_credential(
            "test-instance", client=mock_ws,
            endpoint_name=None, lakebase_type="autoscaling",
        )

        assert token == "prov-token"

    def test_raises_lakebase_error_on_failure(self, mock_ws):
        mock_ws.database.generate_database_credential.side_effect = Exception("SDK error")

        with pytest.raises(LakebaseError, match="Credential generation failed"):
            generate_lakebase_credential("test-instance", client=mock_ws)


# ---------------------------------------------------------------------------
# get_lakebase_connection_info
# ---------------------------------------------------------------------------

class TestGetLakebaseConnectionInfo:
    """Tests for connection info assembly."""

    def test_autoscaling_uses_provided_host(self, mock_ws):
        cred = Mock()
        cred.token = "token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        info = get_lakebase_connection_info(
            "test-instance", user="testuser", client=mock_ws,
            endpoint_name="ep", host="auto.host.com", lakebase_type="autoscaling",
        )

        assert info["host"] == "auto.host.com"
        assert info["port"] == 5432
        assert info["database"] == "databricks_postgres"
        assert info["user"] == "testuser"
        assert info["password"] == "token"
        # Should not call get_database_instance for autoscaling
        mock_ws.database.get_database_instance.assert_not_called()

    def test_provisioned_resolves_host_from_sdk(self, mock_ws):
        instance = Mock()
        instance.read_write_dns = "prov.host.com"
        mock_ws.database.get_database_instance.return_value = instance

        cred = Mock()
        cred.token = "token"
        mock_ws.database.generate_database_credential.return_value = cred

        info = get_lakebase_connection_info(
            "test-instance", user="testuser", client=mock_ws,
            lakebase_type="provisioned",
        )

        assert info["host"] == "prov.host.com"
        mock_ws.database.get_database_instance.assert_called_once_with(name="test-instance")

    def test_resolves_user_from_pguser_env(self, mock_ws):
        cred = Mock()
        cred.token = "token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        with patch.dict(os.environ, {"PGUSER": "envuser"}):
            info = get_lakebase_connection_info(
                "test-instance", client=mock_ws,
                host="h", endpoint_name="ep", lakebase_type="autoscaling",
            )

        assert info["user"] == "envuser"

    def test_resolves_user_from_sdk_fallback(self, mock_ws):
        cred = Mock()
        cred.token = "token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        with patch.dict(os.environ, {}, clear=True):
            info = get_lakebase_connection_info(
                "test-instance", client=mock_ws,
                host="h", endpoint_name="ep", lakebase_type="autoscaling",
            )

        assert info["user"] == "test@example.com"

    def test_raises_when_no_user_available(self, mock_ws):
        mock_ws.current_user.me.side_effect = Exception("No user")

        instance = Mock()
        instance.read_write_dns = "host"
        mock_ws.database.get_database_instance.return_value = instance

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(LakebaseError, match="Could not determine Postgres user"):
                get_lakebase_connection_info(
                    "test-instance", client=mock_ws, lakebase_type="provisioned",
                )

    def test_returns_required_keys(self, mock_ws):
        cred = Mock()
        cred.token = "token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        info = get_lakebase_connection_info(
            "test-instance", user="u", client=mock_ws,
            host="h", endpoint_name="ep", lakebase_type="autoscaling",
        )

        for key in ("host", "port", "database", "user", "password"):
            assert key in info


# ---------------------------------------------------------------------------
# get_lakebase_connection_url
# ---------------------------------------------------------------------------

class TestGetLakebaseConnectionUrl:
    """Tests for connection URL construction."""

    def test_returns_postgresql_url(self, mock_ws):
        cred = Mock()
        cred.token = "token123"
        mock_ws.postgres.generate_database_credential.return_value = cred

        url = get_lakebase_connection_url(
            "test-instance", user="testuser", client=mock_ws,
            host="h", endpoint_name="ep", lakebase_type="autoscaling",
        )

        assert url.startswith("postgresql://")
        assert "sslmode=require" in url
        assert "testuser" in url
        assert "token123" in url

    def test_includes_schema_in_search_path(self, mock_ws):
        cred = Mock()
        cred.token = "token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        url = get_lakebase_connection_url(
            "test-instance", user="u", schema="my_schema", client=mock_ws,
            host="h", endpoint_name="ep", lakebase_type="autoscaling",
        )

        assert "my_schema" in url

    def test_omits_schema_when_none(self, mock_ws):
        cred = Mock()
        cred.token = "token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        url = get_lakebase_connection_url(
            "test-instance", user="u", schema=None, client=mock_ws,
            host="h", endpoint_name="ep", lakebase_type="autoscaling",
        )

        assert "search_path" not in url

    def test_url_encodes_special_password_chars(self, mock_ws):
        cred = Mock()
        cred.token = "tok+en/with=special&chars"
        mock_ws.postgres.generate_database_credential.return_value = cred

        url = get_lakebase_connection_url(
            "test-instance", user="u", client=mock_ws,
            host="h", endpoint_name="ep", lakebase_type="autoscaling",
        )

        # The raw special chars should be encoded
        assert "tok+en/with=special&chars" not in url
        # But the encoded form should be present
        assert "tok%2Ben%2Fwith%3Dspecial%26chars" in url

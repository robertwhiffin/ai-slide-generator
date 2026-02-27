"""Tests for Lakebase autoscaling runtime database functions.

Covers the autoscaling-specific logic in database.py:
- _get_lakebase_type(): reads LAKEBASE_TYPE env var
- is_lakebase_environment(): detects Lakebase from env vars
- _get_database_url(): dual-path URL construction (autoscaling vs provisioned)
"""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.database import (
    _get_database_url,
    _get_lakebase_type,
    is_lakebase_environment,
)


# ---------------------------------------------------------------------------
# _get_lakebase_type
# ---------------------------------------------------------------------------

class TestGetLakebaseType:
    """Tests for LAKEBASE_TYPE env var reading."""

    def test_returns_autoscaling(self):
        with patch.dict(os.environ, {"LAKEBASE_TYPE": "autoscaling"}):
            assert _get_lakebase_type() == "autoscaling"

    def test_returns_provisioned(self):
        with patch.dict(os.environ, {"LAKEBASE_TYPE": "provisioned"}):
            assert _get_lakebase_type() == "provisioned"

    def test_returns_empty_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _get_lakebase_type() == ""


# ---------------------------------------------------------------------------
# is_lakebase_environment
# ---------------------------------------------------------------------------

class TestIsLakebaseEnvironment:
    """Tests for Lakebase environment detection."""

    def test_true_when_lakebase_type_autoscaling(self):
        with patch.dict(os.environ, {"LAKEBASE_TYPE": "autoscaling"}, clear=True):
            assert is_lakebase_environment() is True

    def test_true_when_lakebase_type_provisioned(self):
        with patch.dict(os.environ, {"LAKEBASE_TYPE": "provisioned"}, clear=True):
            assert is_lakebase_environment() is True

    def test_true_when_pghost_and_pguser_set(self):
        with patch.dict(os.environ, {"PGHOST": "host", "PGUSER": "user"}, clear=True):
            assert is_lakebase_environment() is True

    def test_false_when_nothing_set(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_lakebase_environment() is False

    def test_false_when_only_pghost_set(self):
        with patch.dict(os.environ, {"PGHOST": "host"}, clear=True):
            assert is_lakebase_environment() is False

    def test_false_when_only_pguser_set(self):
        with patch.dict(os.environ, {"PGUSER": "user"}, clear=True):
            assert is_lakebase_environment() is False


# ---------------------------------------------------------------------------
# _get_database_url
# ---------------------------------------------------------------------------

class TestGetDatabaseUrl:
    """Tests for dual-path database URL construction."""

    def test_returns_explicit_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://custom/db"}, clear=True):
            assert _get_database_url() == "postgresql://custom/db"

    def test_ignores_jdbc_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "jdbc:postgresql://host/db"}, clear=True):
            url = _get_database_url()
            assert url != "jdbc:postgresql://host/db"

    def test_autoscaling_url_with_pg_host(self):
        env = {
            "LAKEBASE_TYPE": "autoscaling",
            "LAKEBASE_PG_HOST": "auto.host.com",
            "PGUSER": "testuser",
        }
        with patch.dict(os.environ, env, clear=True):
            url = _get_database_url()
        assert "auto.host.com" in url
        assert "testuser" in url
        assert "sslmode=require" in url
        assert "databricks_postgres" in url

    def test_autoscaling_url_includes_schema(self):
        env = {
            "LAKEBASE_TYPE": "autoscaling",
            "LAKEBASE_PG_HOST": "auto.host.com",
            "PGUSER": "testuser",
            "LAKEBASE_SCHEMA": "my_schema",
        }
        with patch.dict(os.environ, env, clear=True):
            url = _get_database_url()
        assert "my_schema" in url

    def test_autoscaling_defaults_schema_to_app_data(self):
        env = {
            "LAKEBASE_TYPE": "autoscaling",
            "LAKEBASE_PG_HOST": "auto.host.com",
            "PGUSER": "testuser",
        }
        with patch.dict(os.environ, env, clear=True):
            url = _get_database_url()
        assert "app_data" in url

    def test_autoscaling_raises_when_pg_host_missing(self):
        env = {"LAKEBASE_TYPE": "autoscaling"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="LAKEBASE_PG_HOST required"):
                _get_database_url()

    def test_autoscaling_resolves_user_from_sdk(self):
        env = {
            "LAKEBASE_TYPE": "autoscaling",
            "LAKEBASE_PG_HOST": "auto.host.com",
        }
        mock_ws = MagicMock()
        mock_ws.current_user.me.return_value = Mock(user_name="sdk-user@example.com")

        with patch.dict(os.environ, env, clear=True):
            with patch("src.core.databricks_client.get_system_client", return_value=mock_ws):
                url = _get_database_url()
        assert "sdk-user%40example.com" in url or "sdk-user@example.com" in url

    def test_provisioned_url_with_pghost_pguser(self):
        env = {
            "PGHOST": "prov.host.com",
            "PGUSER": "provuser",
        }
        with patch.dict(os.environ, env, clear=True):
            url = _get_database_url()
        assert "prov.host.com" in url
        assert "provuser" in url
        assert "sslmode=require" in url

    def test_local_fallback_url(self):
        with patch.dict(os.environ, {}, clear=True):
            url = _get_database_url()
        assert url == "postgresql://localhost/ai_slide_generator"

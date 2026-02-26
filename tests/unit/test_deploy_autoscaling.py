"""Tests for Lakebase autoscaling deployment functions.

Covers the autoscaling-specific logic in deploy.py:
- _capacity_to_autoscaling_cu(): CU range mapping
- _probe_autoscaling_available(): workspace probe
- _get_or_create_lakebase(): orchestrator with fallback
- _get_or_create_lakebase_autoscaling(): project creation
- _ensure_sp_autoscaling_role(): SP role management via Postgres API
- _create_app(): dual-path app resource (provisioned vs autoscaling)
- _get_lakebase_connection(): dual-path connection factory
- _grant_schema_permissions(): schema grants (no CREATE ROLE)
"""

from unittest.mock import MagicMock, Mock, patch, call

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import (
    DeploymentError,
    _capacity_to_autoscaling_cu,
    _create_app,
    _ensure_sp_autoscaling_role,
    _get_lakebase_connection,
    _get_or_create_lakebase,
    _get_or_create_lakebase_autoscaling,
    _grant_schema_permissions,
    _probe_autoscaling_available,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ws():
    """Mocked WorkspaceClient with postgres and database services."""
    ws = MagicMock()
    ws.current_user.me.return_value = Mock(user_name="test@example.com", id="user-123")
    return ws


# ---------------------------------------------------------------------------
# _capacity_to_autoscaling_cu
# ---------------------------------------------------------------------------

class TestCapacityToAutoscalingCU:
    """Tests for CU range mapping from provisioned capacity strings."""

    def test_cu_1_returns_half_to_two(self):
        assert _capacity_to_autoscaling_cu("CU_1") == (0.5, 2.0)

    def test_cu_2_returns_one_to_four(self):
        assert _capacity_to_autoscaling_cu("CU_2") == (1.0, 4.0)

    def test_cu_4_returns_two_to_eight(self):
        assert _capacity_to_autoscaling_cu("CU_4") == (2.0, 8.0)

    def test_cu_8_returns_four_to_twelve(self):
        # CU_8 maps to (4.0, 12.0) but gap is 8, so max_cu stays 12.0
        result = _capacity_to_autoscaling_cu("CU_8")
        assert result == (4.0, 12.0)

    def test_unknown_capacity_defaults_to_cu_1(self):
        assert _capacity_to_autoscaling_cu("UNKNOWN") == (0.5, 2.0)

    def test_min_cu_at_least_half(self):
        min_cu, _ = _capacity_to_autoscaling_cu("CU_1")
        assert min_cu >= 0.5

    def test_max_gap_is_eight(self):
        for capacity in ["CU_1", "CU_2", "CU_4", "CU_8"]:
            min_cu, max_cu = _capacity_to_autoscaling_cu(capacity)
            assert max_cu - min_cu <= 8


# ---------------------------------------------------------------------------
# _probe_autoscaling_available
# ---------------------------------------------------------------------------

class TestProbeAutoscalingAvailable:
    """Tests for workspace autoscaling probe."""

    def test_returns_true_when_list_projects_succeeds(self, mock_ws):
        mock_ws.postgres.list_projects.return_value = iter([])
        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", True):
            assert _probe_autoscaling_available(mock_ws) is True

    def test_returns_false_when_list_projects_raises(self, mock_ws):
        mock_ws.postgres.list_projects.return_value = iter([])
        mock_ws.postgres.list_projects.side_effect = Exception("Not available")
        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", True):
            assert _probe_autoscaling_available(mock_ws) is False

    def test_returns_false_when_sdk_not_available(self, mock_ws):
        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", False):
            assert _probe_autoscaling_available(mock_ws) is False
            # Should not even call list_projects
            mock_ws.postgres.list_projects.assert_not_called()


# ---------------------------------------------------------------------------
# _get_or_create_lakebase (orchestrator)
# ---------------------------------------------------------------------------

class TestGetOrCreateLakebase:
    """Tests for the autoscaling→provisioned fallback orchestrator."""

    @patch("databricks_tellr.deploy._get_or_create_lakebase_provisioned")
    @patch("databricks_tellr.deploy._get_or_create_lakebase_autoscaling")
    @patch("databricks_tellr.deploy._probe_autoscaling_available")
    def test_returns_autoscaling_when_available(
        self, mock_probe, mock_autoscaling, mock_provisioned, mock_ws
    ):
        mock_probe.return_value = True
        mock_autoscaling.return_value = {
            "name": "test-db", "type": "autoscaling", "host": "host.example.com",
            "endpoint_name": "ep", "project_id": "test-db",
        }
        result = _get_or_create_lakebase(mock_ws, "test-db", "CU_1")
        assert result["type"] == "autoscaling"
        mock_provisioned.assert_not_called()

    @patch("databricks_tellr.deploy._get_or_create_lakebase_provisioned")
    @patch("databricks_tellr.deploy._probe_autoscaling_available")
    def test_falls_back_when_probe_returns_false(
        self, mock_probe, mock_provisioned, mock_ws
    ):
        mock_probe.return_value = False
        mock_provisioned.return_value = {
            "name": "test-db", "type": "provisioned", "instance_name": "test-db",
        }
        result = _get_or_create_lakebase(mock_ws, "test-db", "CU_1")
        assert result["type"] == "provisioned"

    @patch("databricks_tellr.deploy._get_or_create_lakebase_provisioned")
    @patch("databricks_tellr.deploy._get_or_create_lakebase_autoscaling")
    @patch("databricks_tellr.deploy._probe_autoscaling_available")
    def test_falls_back_when_autoscaling_creation_fails(
        self, mock_probe, mock_autoscaling, mock_provisioned, mock_ws
    ):
        mock_probe.return_value = True
        mock_autoscaling.side_effect = Exception("Creation failed")
        mock_provisioned.return_value = {
            "name": "test-db", "type": "provisioned", "instance_name": "test-db",
        }
        result = _get_or_create_lakebase(mock_ws, "test-db", "CU_1")
        assert result["type"] == "provisioned"
        mock_provisioned.assert_called_once()


# ---------------------------------------------------------------------------
# _get_or_create_lakebase_autoscaling
# ---------------------------------------------------------------------------

class TestGetOrCreateLakebaseAutoscaling:
    """Tests for autoscaling project creation."""

    def _make_endpoint(self, host="pg.example.com", name="ep-name"):
        ep = Mock()
        ep.name = name
        ep.status.hosts.host = host
        return ep

    def test_returns_existing_project(self, mock_ws):
        project = Mock()
        project.name = "projects/test-db"
        mock_ws.postgres.get_project.return_value = project

        endpoint = self._make_endpoint()
        mock_ws.postgres.list_endpoints.return_value = iter([endpoint])
        mock_ws.postgres.get_endpoint.return_value = endpoint

        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", True):
            result = _get_or_create_lakebase_autoscaling(mock_ws, "test-db", "CU_1")

        assert result["type"] == "autoscaling"
        assert result["name"] == "test-db"
        assert result["host"] == "pg.example.com"
        mock_ws.postgres.create_project.assert_not_called()

    def test_creates_new_project_when_not_found(self, mock_ws):
        mock_ws.postgres.get_project.side_effect = Exception("Not found")

        operation = Mock()
        project = Mock()
        project.name = "projects/test-db"
        operation.wait.return_value = project
        mock_ws.postgres.create_project.return_value = operation

        endpoint = self._make_endpoint()
        mock_ws.postgres.list_endpoints.return_value = iter([endpoint])
        mock_ws.postgres.get_endpoint.return_value = endpoint

        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", True):
            result = _get_or_create_lakebase_autoscaling(mock_ws, "test-db", "CU_1")

        assert result["type"] == "autoscaling"
        mock_ws.postgres.create_project.assert_called_once()

    def test_raises_when_no_endpoints(self, mock_ws):
        project = Mock()
        mock_ws.postgres.get_project.return_value = project
        mock_ws.postgres.list_endpoints.return_value = iter([])

        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", True):
            with pytest.raises(DeploymentError, match="No endpoints found"):
                _get_or_create_lakebase_autoscaling(mock_ws, "test-db", "CU_1")

    def test_result_dict_has_required_keys(self, mock_ws):
        project = Mock()
        mock_ws.postgres.get_project.return_value = project

        endpoint = self._make_endpoint()
        mock_ws.postgres.list_endpoints.return_value = iter([endpoint])
        mock_ws.postgres.get_endpoint.return_value = endpoint

        with patch("databricks_tellr.deploy.HAS_AUTOSCALING_SDK", True):
            result = _get_or_create_lakebase_autoscaling(mock_ws, "test-db", "CU_1")

        for key in ("name", "type", "host", "endpoint_name", "project_id"):
            assert key in result


# ---------------------------------------------------------------------------
# _ensure_sp_autoscaling_role
# ---------------------------------------------------------------------------

class TestEnsureSpAutoscalingRole:
    """Tests for SP Postgres role management via the Postgres API."""

    def test_returns_early_when_role_sdk_unavailable(self, mock_ws):
        with patch("databricks_tellr.deploy.HAS_ROLE_SDK", False):
            # Should not raise, just return early
            _ensure_sp_autoscaling_role(mock_ws, "test-project", "abc-123")
            mock_ws.postgres.get_role.assert_not_called()

    def test_skips_creation_when_role_exists_with_correct_auth(self, mock_ws):
        from databricks.sdk.service.postgres import RoleAuthMethod

        existing = Mock()
        existing.status.auth_method = RoleAuthMethod.LAKEBASE_OAUTH_V1
        mock_ws.postgres.get_role.return_value = existing

        with patch("databricks_tellr.deploy.HAS_ROLE_SDK", True):
            _ensure_sp_autoscaling_role(mock_ws, "test-project", "abc-123")

        mock_ws.postgres.create_role.assert_not_called()

    def test_creates_role_when_not_found(self, mock_ws):
        mock_ws.postgres.get_role.side_effect = Exception("Not found")

        operation = Mock()
        role = Mock()
        role.name = "the-role"
        operation.wait.return_value = role
        mock_ws.postgres.create_role.return_value = operation

        with patch("databricks_tellr.deploy.HAS_ROLE_SDK", True):
            _ensure_sp_autoscaling_role(mock_ws, "test-project", "abc-123")

        mock_ws.postgres.create_role.assert_called_once()
        # Verify role_id is prefixed with sp-
        _, kwargs = mock_ws.postgres.create_role.call_args
        assert kwargs["role_id"] == "sp-abc-123"

    def test_recreates_role_when_auth_method_wrong(self, mock_ws):
        existing = Mock()
        existing.status.auth_method = "WRONG_METHOD"
        mock_ws.postgres.get_role.return_value = existing

        delete_op = Mock()
        mock_ws.postgres.delete_role.return_value = delete_op

        create_op = Mock()
        create_op.wait.return_value = Mock(name="new-role")
        mock_ws.postgres.create_role.return_value = create_op

        with patch("databricks_tellr.deploy.HAS_ROLE_SDK", True):
            _ensure_sp_autoscaling_role(mock_ws, "test-project", "abc-123")

        mock_ws.postgres.delete_role.assert_called_once()
        mock_ws.postgres.create_role.assert_called_once()

    def test_raises_deployment_error_on_create_failure(self, mock_ws):
        mock_ws.postgres.get_role.side_effect = Exception("Not found")
        mock_ws.postgres.create_role.side_effect = Exception("API error")

        with patch("databricks_tellr.deploy.HAS_ROLE_SDK", True):
            with pytest.raises(DeploymentError, match="Failed to create SP role"):
                _ensure_sp_autoscaling_role(mock_ws, "test-project", "abc-123")

    def test_role_path_uses_production_branch(self, mock_ws):
        mock_ws.postgres.get_role.side_effect = Exception("Not found")

        operation = Mock()
        operation.wait.return_value = Mock(name="role")
        mock_ws.postgres.create_role.return_value = operation

        with patch("databricks_tellr.deploy.HAS_ROLE_SDK", True):
            _ensure_sp_autoscaling_role(mock_ws, "my-project", "client-uuid")

        _, kwargs = mock_ws.postgres.create_role.call_args
        assert kwargs["parent"] == "projects/my-project/branches/production"


# ---------------------------------------------------------------------------
# _create_app
# ---------------------------------------------------------------------------

class TestCreateApp:
    """Tests for dual-path app resource creation."""

    def test_provisioned_includes_app_resource_database(self, mock_ws):
        mock_ws.apps.get.return_value = Mock()

        with patch("databricks_tellr.deploy.ComputeSize") as mock_cs:
            mock_cs.return_value = "MEDIUM"
            _create_app(
                mock_ws, "test-app", "desc", "/path", "MEDIUM",
                "test-db", lakebase_type="provisioned",
            )

        # Verify the App was created with resources
        app_arg = mock_ws.apps.create_and_wait.call_args[0][0]
        assert len(app_arg.resources) == 1
        assert app_arg.resources[0].name == "app_database"
        assert app_arg.resources[0].database is not None

    def test_autoscaling_excludes_app_resource_database(self, mock_ws):
        mock_ws.apps.get.return_value = Mock()

        with patch("databricks_tellr.deploy.ComputeSize") as mock_cs:
            mock_cs.return_value = "MEDIUM"
            _create_app(
                mock_ws, "test-app", "desc", "/path", "MEDIUM",
                "test-db", lakebase_type="autoscaling",
            )

        app_arg = mock_ws.apps.create_and_wait.call_args[0][0]
        assert len(app_arg.resources) == 0


# ---------------------------------------------------------------------------
# _get_lakebase_connection
# ---------------------------------------------------------------------------

class TestGetLakebaseConnection:
    """Tests for the dual-path connection factory."""

    @patch("databricks_tellr.deploy.psycopg2", create=True)
    def test_autoscaling_uses_postgres_credential(self, mock_psycopg2, mock_ws):
        # We need to mock psycopg2 import inside the function
        mock_conn = Mock()
        mock_psycopg2.connect.return_value = mock_conn

        cred = Mock()
        cred.token = "auto-token"
        mock_ws.postgres.generate_database_credential.return_value = cred

        lakebase_result = {
            "type": "autoscaling",
            "endpoint_name": "ep-name",
            "host": "auto.host.com",
        }

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            conn, user = _get_lakebase_connection(mock_ws, "test-db", lakebase_result)

        mock_ws.postgres.generate_database_credential.assert_called_once_with(endpoint="ep-name")
        mock_psycopg2.connect.assert_called_once()
        connect_kwargs = mock_psycopg2.connect.call_args[1]
        assert connect_kwargs["host"] == "auto.host.com"
        assert connect_kwargs["password"] == "auto-token"

    @patch("databricks_tellr.deploy.psycopg2", create=True)
    def test_provisioned_uses_database_credential(self, mock_psycopg2, mock_ws):
        mock_conn = Mock()
        mock_psycopg2.connect.return_value = mock_conn

        instance = Mock()
        instance.read_write_dns = "prov.host.com"
        mock_ws.database.get_database_instance.return_value = instance

        cred = Mock()
        cred.token = "prov-token"
        mock_ws.database.generate_database_credential.return_value = cred

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            conn, user = _get_lakebase_connection(mock_ws, "test-db")

        mock_ws.database.generate_database_credential.assert_called_once()
        connect_kwargs = mock_psycopg2.connect.call_args[1]
        assert connect_kwargs["host"] == "prov.host.com"
        assert connect_kwargs["password"] == "prov-token"

    def test_raises_when_psycopg2_missing(self, mock_ws):
        with patch.dict("sys.modules", {"psycopg2": None}):
            with pytest.raises(DeploymentError, match="psycopg2"):
                _get_lakebase_connection(mock_ws, "test-db")


# ---------------------------------------------------------------------------
# _grant_schema_permissions
# ---------------------------------------------------------------------------

class TestGrantSchemaPermissions:
    """Tests for schema permission grants."""

    def test_executes_all_grant_statements(self):
        cur = Mock()
        # First call is the role existence check
        cur.fetchone.return_value = (1,)

        _grant_schema_permissions(cur, "app_data", "client-123")

        # 1 SELECT for role check + 6 GRANT/ALTER statements = 7 total
        assert cur.execute.call_count == 7

    def test_warns_when_role_not_found(self):
        cur = Mock()
        cur.fetchone.return_value = None  # role not found

        with patch("databricks_tellr.deploy.logger") as mock_logger:
            _grant_schema_permissions(cur, "app_data", "client-123")
            mock_logger.warning.assert_called_once()

    def test_does_not_create_role(self):
        cur = Mock()
        cur.fetchone.return_value = (1,)

        _grant_schema_permissions(cur, "app_data", "client-123")

        # Verify no CREATE ROLE statement was executed
        for call_args in cur.execute.call_args_list:
            sql = str(call_args[0][0]).upper()
            assert "CREATE ROLE" not in sql

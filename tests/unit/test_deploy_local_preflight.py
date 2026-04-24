"""Tests for branching-mode preflight checks."""
from unittest.mock import MagicMock, patch
import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import DeploymentError


@pytest.fixture
def mock_ws():
    return MagicMock()


@pytest.fixture
def good_config():
    return {
        "lakebase_name": "db-tellr",
        "branch_from_env": "production",
        "branch_from_workspace_path": "/Workspace/Users/x/.apps/prod/tellr",
    }


class TestCheckBranchingPreconditions:
    def test_happy_path_returns_encryption_key(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        # Patch all the Workspace/SDK calls
        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="prod-key-123",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available", return_value=True
        ):
            mock_ws.postgres.get_project.return_value = MagicMock()
            with patch(
                "scripts.deploy_local._branch_exists", return_value=True
            ):
                key = _check_branching_preconditions(mock_ws, good_config)
        assert key == "prod-key-123"

    def test_missing_prod_app_yaml(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value=None,
        ):
            with pytest.raises(
                DeploymentError, match="production not deployed"
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_provisioned_lakebase_errors(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="k",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available",
            return_value=False,
        ):
            with pytest.raises(
                DeploymentError, match="requires autoscaling"
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_project_missing(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="k",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available",
            return_value=True,
        ):
            mock_ws.postgres.get_project.side_effect = Exception("not found")
            with pytest.raises(
                DeploymentError, match="not an autoscaling project"
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_source_branch_missing(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="k",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available",
            return_value=True,
        ), patch(
            "scripts.deploy_local._branch_exists", return_value=False
        ):
            mock_ws.postgres.get_project.return_value = MagicMock()
            with pytest.raises(
                DeploymentError, match='source branch "production" not found'
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_preflight_does_not_mutate_on_any_failure(self, mock_ws, good_config):
        """Confirm no mutating ws.postgres call is made when preflight fails."""
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value=None,
        ):
            with pytest.raises(DeploymentError):
                _check_branching_preconditions(mock_ws, good_config)

        mock_ws.postgres.create_branch.assert_not_called()
        mock_ws.postgres.delete_branch.assert_not_called()
        mock_ws.postgres.create_role.assert_not_called()

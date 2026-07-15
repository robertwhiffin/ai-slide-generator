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
    def test_preflight_ok_when_source_deployed_and_keyless(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key", return_value=None
        ):
            with patch("scripts.deploy_local._probe_autoscaling_available", return_value=True):
                with patch("scripts.deploy_local._branch_exists", return_value=True):
                    mock_ws.postgres.get_project.return_value = MagicMock()
                    # returns None — nothing to relocate on the fork
                    assert _check_branching_preconditions(mock_ws, good_config) is None

    def test_preflight_fails_when_source_still_has_legacy_key(self, mock_ws, good_config):
        from scripts.deploy_local import DeploymentError, _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key", return_value="old-key"
        ):
            with pytest.raises(DeploymentError, match="legacy encryption key"):
                _check_branching_preconditions(mock_ws, good_config)

    def test_preflight_fails_when_source_not_deployed(self, mock_ws, good_config):
        from scripts.deploy_local import DeploymentError, _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            side_effect=DeploymentError(
                "Could not read the deployed app.yaml at /Workspace/x/app.yaml"
            ),
        ):
            with pytest.raises(DeploymentError, match="not deployed"):
                _check_branching_preconditions(mock_ws, good_config)

    def test_provisioned_lakebase_errors(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value=None,
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
            return_value=None,
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
            return_value=None,
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
            side_effect=DeploymentError("Could not read the deployed app.yaml"),
        ):
            with pytest.raises(DeploymentError):
                _check_branching_preconditions(mock_ws, good_config)

        mock_ws.postgres.create_branch.assert_not_called()
        mock_ws.postgres.delete_branch.assert_not_called()
        mock_ws.postgres.create_role.assert_not_called()

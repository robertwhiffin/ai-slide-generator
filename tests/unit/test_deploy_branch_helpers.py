"""Tests for Lakebase branch helpers in databricks_tellr.deploy."""
from unittest.mock import MagicMock, patch
import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import _branch_exists


@pytest.fixture
def mock_ws():
    return MagicMock()


class TestBranchExists:
    def test_returns_true_when_branch_exists(self, mock_ws):
        mock_ws.postgres.get_branch.return_value = MagicMock(name="branch")
        assert _branch_exists(mock_ws, "db-tellr", "production") is True
        mock_ws.postgres.get_branch.assert_called_once_with(
            name="projects/db-tellr/branches/production"
        )

    def test_returns_false_on_not_found(self, mock_ws):
        mock_ws.postgres.get_branch.side_effect = Exception("Resource not found")
        assert _branch_exists(mock_ws, "db-tellr", "staging") is False

    def test_returns_false_on_does_not_exist(self, mock_ws):
        mock_ws.postgres.get_branch.side_effect = Exception("branch does not exist")
        assert _branch_exists(mock_ws, "db-tellr", "staging") is False

    def test_surfaces_other_errors(self, mock_ws):
        mock_ws.postgres.get_branch.side_effect = Exception("permission denied")
        with pytest.raises(Exception, match="permission denied"):
            _branch_exists(mock_ws, "db-tellr", "production")


from databricks_tellr.deploy import _delete_branch


class TestDeleteBranch:
    def test_calls_delete_with_correct_path_and_waits(self, mock_ws):
        operation = MagicMock()
        mock_ws.postgres.delete_branch.return_value = operation

        _delete_branch(mock_ws, "db-tellr", "staging")

        mock_ws.postgres.delete_branch.assert_called_once_with(
            name="projects/db-tellr/branches/staging"
        )
        operation.wait.assert_called_once()

    def test_noop_on_not_found(self, mock_ws):
        mock_ws.postgres.delete_branch.side_effect = Exception("Resource not found")
        # Should not raise
        _delete_branch(mock_ws, "db-tellr", "staging")

    def test_noop_on_does_not_exist(self, mock_ws):
        mock_ws.postgres.delete_branch.side_effect = Exception("branch does not exist")
        _delete_branch(mock_ws, "db-tellr", "staging")

    def test_surfaces_other_errors(self, mock_ws):
        mock_ws.postgres.delete_branch.side_effect = Exception("permission denied")
        with pytest.raises(Exception, match="permission denied"):
            _delete_branch(mock_ws, "db-tellr", "staging")

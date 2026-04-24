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


from databricks_tellr.deploy import _create_branch_from


class TestCreateBranchFrom:
    def test_creates_branch_with_correct_source(self, mock_ws, monkeypatch):
        # Freeze time so the generated branch_id is deterministic.
        monkeypatch.setattr("databricks_tellr.deploy.time.time", lambda: 1777000000)
        expected_branch_id = "staging-1777000000"

        create_op = MagicMock()
        mock_ws.postgres.create_branch.return_value = create_op

        endpoint_ready = MagicMock()
        endpoint_ready.name = (
            f"projects/db-tellr/branches/{expected_branch_id}/endpoints/ep1"
        )
        endpoint_ready.status = MagicMock(
            hosts=MagicMock(host="staging-ep1.example.com")
        )
        # Fresh iterator per call — avoids one-shot iter() exhaustion if polling loops.
        mock_ws.postgres.list_endpoints.side_effect = (
            lambda **kw: iter([endpoint_ready])
        )

        result = _create_branch_from(
            mock_ws,
            project_name="db-tellr",
            source_branch="production",
            target_branch_prefix="staging",
        )

        # Verify create_branch call shape
        call_kwargs = mock_ws.postgres.create_branch.call_args.kwargs
        assert call_kwargs["parent"] == "projects/db-tellr"
        # branch_id is {prefix}-{timestamp} — a fresh unique ID per deploy.
        assert call_kwargs["branch_id"] == expected_branch_id
        branch_arg = call_kwargs["branch"]
        assert branch_arg.spec.source_branch == "projects/db-tellr/branches/production"
        # Databricks API requires an expiration policy. We use ttl=1 day and
        # rely on TTL-driven auto-cleanup rather than explicit delete.
        assert branch_arg.spec.ttl is not None
        assert branch_arg.spec.ttl.seconds == 86400
        # no_expiry MUST NOT be set when ttl is — they're mutually exclusive.
        assert not branch_arg.spec.no_expiry

        create_op.wait.assert_called_once()

        # Verify returned lakebase_result shape
        assert result["type"] == "autoscaling"
        assert result["name"] == "db-tellr"
        assert result["host"] == "staging-ep1.example.com"
        assert (
            result["endpoint_name"]
            == f"projects/db-tellr/branches/{expected_branch_id}/endpoints/ep1"
        )
        assert result["project_id"] == "db-tellr"
        assert result["instance_name"] is None
        # New field: callers (SP role registration, schema grants) use this
        # to reference the unique branch name.
        assert result["branch_id"] == expected_branch_id

    def test_raises_when_no_endpoint_after_timeout(self, mock_ws, monkeypatch):
        """If list_endpoints never returns a ready endpoint, raise DeploymentError."""
        from databricks_tellr.deploy import DeploymentError

        create_op = MagicMock()
        mock_ws.postgres.create_branch.return_value = create_op
        mock_ws.postgres.list_endpoints.side_effect = lambda **kw: iter([])

        monkeypatch.setattr("databricks_tellr.deploy.time.sleep", lambda *_: None)
        monkeypatch.setattr("databricks_tellr.deploy._BRANCH_ENDPOINT_TIMEOUT_S", 0.1)

        with pytest.raises(DeploymentError, match="no endpoint ready"):
            _create_branch_from(mock_ws, "db-tellr", "production", "staging")


from databricks_tellr.deploy import _recreate_ephemeral_branch


class TestRecreateEphemeralBranch:
    def test_delegates_to_create_without_deleting(self, mock_ws, monkeypatch):
        """Delete step removed — TTL handles cleanup. Verify we ONLY create."""
        calls = []

        def fake_delete(ws, project, branch):
            calls.append(("delete", branch))

        def fake_create(ws, project, source, prefix):
            calls.append(("create", source, prefix))
            return {"host": "x", "endpoint_name": "e", "type": "autoscaling",
                    "branch_id": f"{prefix}-12345"}

        monkeypatch.setattr("databricks_tellr.deploy._delete_branch", fake_delete)
        monkeypatch.setattr("databricks_tellr.deploy._create_branch_from", fake_create)

        result = _recreate_ephemeral_branch(
            mock_ws,
            project_name="db-tellr",
            source_branch="production",
            target_branch_prefix="staging",
        )

        # No delete — only create.
        assert calls == [("create", "production", "staging")]
        assert result["host"] == "x"
        assert result["branch_id"] == "staging-12345"

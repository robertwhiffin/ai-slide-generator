"""Tests for --instance resolution + validation in deploy_local."""
import pytest

from databricks_tellr.deploy import DeploymentError
from scripts.deploy_local import _validate_instance, _resolve_target

BRANCHING = {
    "app_name": "db-tellr-dev",
    "workspace_path": "/Workspace/Users/x/.apps/devloop",
    "branch_from_env": "production",
}
NON_BRANCHING = {
    "app_name": "db-tellr-dev",
    "workspace_path": "/Workspace/Users/x/.apps/dev",
    "branch_from_env": None,
}


class TestValidateInstance:
    @pytest.mark.parametrize("good", ["agent-7f3a", "a", "spike01", "x-1-2-3"])
    def test_accepts_valid(self, good):
        _validate_instance(good)  # no raise

    @pytest.mark.parametrize("bad", ["Agent", "1abc", "has_underscore", "has.dot",
                                     "trailing ", "UPPER", "a" * 60])
    def test_rejects_invalid(self, bad):
        with pytest.raises(DeploymentError):
            _validate_instance(bad)


class TestResolveTarget:
    def test_no_instance_uses_env_branch(self):
        app, wp, branch = _resolve_target(BRANCHING, "staging", None)
        assert app == "db-tellr-dev"
        assert wp == "/Workspace/Users/x/.apps/devloop"
        assert branch == "staging"

    def test_instance_suffixes_names_and_dev_branch(self):
        app, wp, branch = _resolve_target(BRANCHING, "devloop", "agent-7f3a")
        assert app == "db-tellr-dev-agent-7f3a"
        assert wp == "/Workspace/Users/x/.apps/devloop/agent-7f3a"
        assert branch == "dev-agent-7f3a"

    def test_instance_on_non_branching_raises(self):
        with pytest.raises(DeploymentError, match="branch_from"):
            _resolve_target(NON_BRANCHING, "development", "agent-7f3a")

    def test_instance_invalid_slug_raises(self):
        with pytest.raises(DeploymentError):
            _resolve_target(BRANCHING, "devloop", "Bad_Id")


from unittest.mock import MagicMock, patch


class TestDeleteLocalBranch:
    def test_deletes_app_and_instance_branch(self, monkeypatch):
        import scripts.deploy_local as dl

        cfg = {
            "app_name": "db-tellr-dev",
            "workspace_path": "/Workspace/Users/x/.apps/devloop",
            "lakebase_name": "db-tellr",
            "schema_name": "app_data_prod",
            "branch_from_env": "production",
        }
        monkeypatch.setattr(dl, "load_deployment_config", lambda env: cfg)
        fake_ws = MagicMock()
        monkeypatch.setattr(dl, "_get_workspace_client", lambda profile: fake_ws)
        delete_calls = {}
        monkeypatch.setattr(dl, "delete", lambda **kw: delete_calls.update(kw) or {"status": "deleted"})
        branch_calls = []
        monkeypatch.setattr(dl, "_delete_branch", lambda ws, proj, br: branch_calls.append((proj, br)))

        dl.delete_local(env="devloop", profile="p", instance="agent-7f3a")

        # App deleted under the instance-suffixed name
        assert delete_calls["app_name"] == "db-tellr-dev-agent-7f3a"
        # Branch deleted with the fixed dev-<instance> name
        assert branch_calls == [("db-tellr", "dev-agent-7f3a")]

    def test_non_branching_delete_does_not_touch_branches(self, monkeypatch):
        import scripts.deploy_local as dl

        cfg = {
            "app_name": "db-tellr-dev",
            "workspace_path": "/Workspace/Users/x/.apps/dev",
            "lakebase_name": "db-tellr",
            "schema_name": "tellr_app_data_dev",
            "branch_from_env": None,
        }
        monkeypatch.setattr(dl, "load_deployment_config", lambda env: cfg)
        monkeypatch.setattr(dl, "delete", lambda **kw: {"status": "deleted"})
        branch_calls = []
        monkeypatch.setattr(dl, "_delete_branch", lambda ws, proj, br: branch_calls.append((proj, br)))

        dl.delete_local(env="development", profile="p")
        assert branch_calls == []

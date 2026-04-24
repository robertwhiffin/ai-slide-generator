"""Tests for branch_from resolution in load_deployment_config."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from scripts.deploy_local import load_deployment_config

FIXTURE_YAML = {
    "environments": {
        "production": {
            "app_name": "db-tellr-prod",
            "description": "prod",
            "workspace_path": "/Workspace/Users/x/.apps/prod/tellr",
            "compute_size": "LARGE",
            "lakebase": {
                "database_name": "db-tellr",
                "schema": "app_data_prod",
                "capacity": "CU_1",
            },
        },
        "staging": {
            "app_name": "db-tellr-staging",
            "description": "staging",
            "workspace_path": "/Workspace/Users/x/.apps/staging/tellr",
            "compute_size": "MEDIUM",
            "lakebase": {
                "database_name": "db-tellr",
                "branch_from": "production",
                "capacity": "CU_1",
            },
        },
        "development": {
            "app_name": "db-tellr-dev",
            "description": "dev",
            "workspace_path": "/Workspace/Users/x/.apps/dev/tellr",
            "compute_size": "MEDIUM",
            "lakebase": {
                "database_name": "db-tellr",
                "schema": "tellr_app_data_dev",
                "capacity": "CU_1",
            },
        },
    },
}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Write FIXTURE_YAML to tmp and point load_deployment_config at it."""
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(yaml.safe_dump(FIXTURE_YAML))
    # load_deployment_config resolves PROJECT_ROOT / "config" / "deployment.yaml"
    # Patch PROJECT_ROOT to tmp_path, and put the yaml at tmp_path/config/deployment.yaml
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "deployment.yaml").write_text(yaml.safe_dump(FIXTURE_YAML))
    monkeypatch.setattr("scripts.deploy_local.PROJECT_ROOT", tmp_path)
    return tmp_path


class TestLoadDeploymentConfig:
    def test_non_branching_env_unchanged(self, config_path):
        """production config is unaffected by branch_from logic."""
        cfg = load_deployment_config("production")
        assert cfg["schema_name"] == "app_data_prod"
        assert cfg.get("branch_from_env") is None
        assert cfg.get("branch_from_workspace_path") is None

    def test_dev_env_unchanged(self, config_path):
        cfg = load_deployment_config("development")
        assert cfg["schema_name"] == "tellr_app_data_dev"
        assert cfg.get("branch_from_env") is None

    def test_staging_inherits_prod_schema(self, config_path):
        cfg = load_deployment_config("staging")
        assert cfg["schema_name"] == "app_data_prod"
        assert cfg["branch_from_env"] == "production"
        assert cfg["branch_from_workspace_path"] == "/Workspace/Users/x/.apps/prod/tellr"
        # database_name still staging's own (same value)
        assert cfg["lakebase_name"] == "db-tellr"

    def test_branch_from_unknown_env_errors(self, config_path, tmp_path, monkeypatch):
        bad = yaml.safe_load(yaml.safe_dump(FIXTURE_YAML))
        bad["environments"]["staging"]["lakebase"]["branch_from"] = "nonexistent"
        (tmp_path / "config" / "deployment.yaml").write_text(yaml.safe_dump(bad))
        with pytest.raises(Exception, match="branch_from.*nonexistent.*not found"):
            load_deployment_config("staging")

    def test_database_name_mismatch_errors(self, config_path, tmp_path, monkeypatch):
        bad = yaml.safe_load(yaml.safe_dump(FIXTURE_YAML))
        bad["environments"]["staging"]["lakebase"]["database_name"] = "other-db"
        (tmp_path / "config" / "deployment.yaml").write_text(yaml.safe_dump(bad))
        with pytest.raises(Exception, match="same database_name"):
            load_deployment_config("staging")


class TestResetDbNoopWarning:
    def test_reset_db_warning_printed_for_branching_env(
        self, config_path, capsys, monkeypatch
    ):
        """update_local with a branching env + reset_database prints a warning and ignores the flag."""
        from scripts import deploy_local

        # Patch every side-effecting call in update_local down to the warning print
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: MagicMock()
        )
        # Make preflight fail loudly with a recognisable error — we just want to
        # get past the warning print, not execute the rest of the flow.
        def boom(*a, **kw):
            raise deploy_local.DeploymentError("STOP")
        monkeypatch.setattr(deploy_local, "_check_branching_preconditions", boom)

        with pytest.raises(deploy_local.DeploymentError, match="STOP"):
            deploy_local.update_local(
                env="staging", profile="p", reset_database=True
            )

        captured = capsys.readouterr()
        assert "--reset-db is a no-op for branching envs" in captured.out

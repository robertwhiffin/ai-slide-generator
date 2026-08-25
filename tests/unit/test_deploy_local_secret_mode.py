"""deploy_local secret-mode plumbing."""

import yaml
import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from scripts import deploy_local


# ---------------------------------------------------------------------------
# Shared config fixture (mirrors the branching fixture in test_deploy_local_config_branching.py)
# ---------------------------------------------------------------------------

_BRANCH_FIXTURE_YAML = {
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
    },
}


@pytest.fixture
def branch_config_path(tmp_path, monkeypatch):
    """Write branching YAML to tmp and point deploy_local at it."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "deployment.yaml"
    cfg_file.write_text(yaml.safe_dump(_BRANCH_FIXTURE_YAML))
    monkeypatch.setattr("scripts.deploy_local.CONFIG_PATH", cfg_file)
    monkeypatch.setattr("scripts.deploy_local.PROJECT_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Finding #1 wiring test
# ---------------------------------------------------------------------------

class TestUpdateLocalForkSecretInheritance:
    """update_local on the branching path MUST pass
    encryption_secret_resource_key=RESOURCE_KEY when the source app is
    secret-mode (_check_branching_preconditions sets config['_inherited_secret']).

    Without the fix the valueFrom entry is dropped from the fork's app.yaml on
    every update iteration, causing the fork to boot without TELLR_ENCRYPTION_KEY
    and mint a fresh key over its inherited ciphertext — silently destroying test
    data.
    """

    def test_fork_update_passes_resource_key_to_write_app_yaml(
        self, branch_config_path, monkeypatch
    ):
        from unittest.mock import MagicMock

        # Mock ws: apps.get returns a live app; deploy_and_wait returns a deployment.
        mock_app = MagicMock()
        mock_app.url = "https://fake.app/url"
        mock_deployment = MagicMock()
        mock_deployment.deployment_id = "deploy-abc123"
        mock_ws = MagicMock()
        mock_ws.apps.get.return_value = mock_app
        mock_ws.apps.deploy_and_wait.return_value = mock_deployment
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: mock_ws
        )

        # Simulate _check_branching_preconditions setting _inherited_secret on config.
        def fake_preconditions(ws, cfg):
            cfg["_inherited_secret"] = ("test-scope", "test-secret-key")

        monkeypatch.setattr(
            deploy_local, "_check_branching_preconditions", fake_preconditions
        )

        # Return a minimal autoscaling lakebase_result (type needed for the print).
        mock_lb_result = {
            "name": "db-tellr",
            "status": "running",
            "type": "autoscaling",
            "host": "test.postgres.host",
            "endpoint_name": "test-endpoint",
            "branch_id": "staging-99999",
        }
        monkeypatch.setattr(
            deploy_local,
            "_recreate_ephemeral_branch",
            lambda ws, lb, src, tgt: mock_lb_result,
        )

        # No SP client id — skip the grant + autoscaling role paths.
        monkeypatch.setattr(deploy_local, "_get_app_client_id", lambda app: None)

        # Allow the schema-setup skip (it would otherwise fail because sp_owner_grant_ran=False).
        monkeypatch.setattr(
            deploy_local, "_assert_fork_schema_setup_skippable", lambda *a, **kw: None
        )

        # Capture what _write_app_yaml receives — this is the assertion target.
        captured: dict = {}

        def fake_write_app_yaml(staging_dir, lb_name, schema_name, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(deploy_local, "_write_app_yaml", fake_write_app_yaml)

        # Stub out everything that touches the filesystem or workspace.
        monkeypatch.setattr(deploy_local, "_write_requirements", lambda *a, **kw: None)
        monkeypatch.setattr(deploy_local, "_upload_files", lambda *a, **kw: None)
        monkeypatch.setattr(
            deploy_local,
            "_mlflow_substitutions_for_app_yaml",
            lambda **kw: {},
        )

        # Use from_pypi so find_app_wheel / upload_wheel are never called.
        deploy_local.update_local(env="staging", profile="p", from_pypi="0.1.0")

        # The valueFrom resource key must be present in the generated app.yaml.
        assert captured.get("encryption_secret_resource_key") == deploy_local.secret_key.RESOURCE_KEY, (
            "update_local branching path did not pass encryption_secret_resource_key "
            "to _write_app_yaml — the fork's app.yaml would be written without the "
            "TELLR_ENCRYPTION_KEY valueFrom entry, causing the fork to mint a fresh "
            "key over inherited ciphertext on the next boot."
        )

        # Confirm no Lakebase connection was opened on the fork path.
        mock_ws.postgres.get_project.assert_not_called()


# ---------------------------------------------------------------------------
# Finding #2 wiring test
# ---------------------------------------------------------------------------


class TestUpdateLocalNonBranchingSecretRetain:
    """update_local on the NON-branching path MUST pass
    encryption_secret_resource_key=RESOURCE_KEY when the deployed app is already
    in secret mode, even when --encryption-secret-scope is NOT re-passed.

    Without the fix the valueFrom entry is dropped from app.yaml on every plain
    update of a secret-mode app, causing the app to boot without
    TELLR_ENCRYPTION_KEY and mint a fresh key over stored ciphertext —
    silently orphaning every stored Google credential.

    RED before fix (encryption_secret_resource_key is None), GREEN after.
    """

    def test_non_branching_update_retains_resource_key_for_secret_mode_app(
        self, branch_config_path, monkeypatch
    ):
        from unittest.mock import MagicMock, Mock
        from databricks_tellr import secret_key as sk

        # Build a secret-mode app response: resources include TELLR_ENCRYPTION_KEY.
        secret_resource = sk.build_secret_resource("test-scope", "test-key")
        mock_app = MagicMock()
        mock_app.url = "https://fake.app/url"
        mock_app.resources = [secret_resource]
        mock_deployment = MagicMock()
        mock_deployment.deployment_id = "deploy-nonbranch-123"

        mock_ws = MagicMock()
        mock_ws.apps.get.return_value = mock_app
        mock_ws.apps.deploy_and_wait.return_value = mock_deployment
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: mock_ws
        )

        # Non-branching lakebase result (production env — no branch_from).
        mock_lb_result = {
            "name": "db-tellr",
            "status": "running",
            "type": "autoscaling",
            "host": "test.postgres.host",
            "endpoint_name": "test-endpoint",
        }
        monkeypatch.setattr(
            deploy_local,
            "_get_or_create_lakebase",
            lambda ws, name, cap: mock_lb_result,
        )

        # No legacy key — skip the CRITICAL-3 relocate block.
        monkeypatch.setattr(
            deploy_local, "_read_existing_encryption_key", lambda ws, path: None
        )

        # Capture what _write_app_yaml receives — this is the assertion target.
        captured: dict = {}

        def fake_write_app_yaml(staging_dir, lb_name, schema_name, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(deploy_local, "_write_app_yaml", fake_write_app_yaml)

        # Stub out filesystem / network helpers.
        monkeypatch.setattr(deploy_local, "_write_requirements", lambda *a, **kw: None)
        monkeypatch.setattr(deploy_local, "_upload_files", lambda *a, **kw: None)
        monkeypatch.setattr(
            deploy_local,
            "_mlflow_substitutions_for_app_yaml",
            lambda **kw: {},
        )

        # Use from_pypi so find_app_wheel / upload_wheel are never called.
        # No encryption_secret_scope — this is the plain update path.
        deploy_local.update_local(
            env="production", profile="p", from_pypi="0.1.0"
        )

        # The valueFrom resource key must be present in the generated app.yaml.
        assert captured.get("encryption_secret_resource_key") == sk.RESOURCE_KEY, (
            "update_local non-branching path did not pass encryption_secret_resource_key "
            "to _write_app_yaml for a secret-mode app — app.yaml would be written "
            "without the TELLR_ENCRYPTION_KEY valueFrom entry, causing the app to "
            "mint a fresh key over existing ciphertext on next boot."
        )

        # The retain path must NOT open a Lakebase connection (no scope was passed).
        mock_ws.postgres.get_project.assert_not_called()


# ---------------------------------------------------------------------------
# Pre-existing parser / config tests
# ---------------------------------------------------------------------------


def test_parser_accepts_the_secret_flags():
    parser = deploy_local.build_parser()
    args = parser.parse_args([
        "--update", "--env", "devtest",
        "--profile", "tellr-dev",
        "--encryption-secret-scope", "tellr",
        "--encryption-secret-key", "tellr-encryption-key",
    ])
    assert args.encryption_secret_scope == "tellr"
    assert args.encryption_secret_key == "tellr-encryption-key"


def test_config_surfaces_the_secret_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(
        "environments:\n"
        "  devtest:\n"
        "    app_name: db-tellr-devtest\n"
        "    workspace_path: /ws/devtest\n"
        "    encryption_secret_scope: tellr\n"
        "    encryption_secret_key: custom-key\n"
        "    lakebase:\n"
        "      database_name: db-tellr\n"
        "      schema: devtest_app_data\n"
    )
    monkeypatch.setattr(deploy_local, "CONFIG_PATH", cfg)
    out = deploy_local.load_deployment_config("devtest")
    assert out["encryption_secret_scope"] == "tellr"
    assert out["encryption_secret_key"] == "custom-key"


def test_branch_source_config_exposes_the_source_app_name(tmp_path, monkeypatch):
    """The fork needs the source app's name to read its resources; the
    workspace_path carries no recoverable suffix rule."""
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(
        "environments:\n"
        "  production:\n"
        "    app_name: db-tellr-prod\n"
        "    workspace_path: /ws/prod/tellr\n"
        "    lakebase:\n"
        "      database_name: db-tellr\n"
        "      schema: app_data_prod\n"
    )
    monkeypatch.setattr(deploy_local, "CONFIG_PATH", cfg)
    src = deploy_local._load_branch_source_config("production")
    assert src["app_name"] == "db-tellr-prod"

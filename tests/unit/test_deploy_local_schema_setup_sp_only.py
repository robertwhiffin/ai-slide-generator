"""Regression tests: dev-loop (fork) deploys must be SP-only.

`_setup_database_schema` / `_reset_schema` connect via `_get_lakebase_connection`,
which authenticates as `ws.current_user.me()` (the deploying human). On the
branching/fork path that step is redundant (the SP is granted into
`tellr_app_owners` WITH INHERIT and the app migrates its own tables at startup),
so it is skipped — otherwise a deployer without a personal Postgres login role
fails with "password authentication failed". These tests pin that behaviour:
the fork path must NOT call `_setup_database_schema`, while the non-fork
(local/prod) path still must.
"""
from unittest.mock import MagicMock

from scripts import deploy_local

_BRANCH_CFG = {
    "app_name": "db-tellr",
    "description": "AI Slide Generator",
    "workspace_path": "/Workspace/Users/x/.apps/devloop/tellr",
    "compute_size": "MEDIUM",
    "lakebase_name": "db-tellr",
    "lakebase_capacity": "CU_1",
    "schema_name": "app_data_prod",
    "branch_from_env": "production",
    "branch_from_workspace_path": "/Workspace/Users/x/.apps/prod/tellr",
    "owner_grant_job_id": 724278545842460,
}

_NONBRANCH_CFG = {
    "app_name": "db-tellr-prod",
    "description": "AI Slide Generator",
    "workspace_path": "/Workspace/Users/x/.apps/prod/tellr",
    "compute_size": "LARGE",
    "lakebase_name": "db-tellr",
    "lakebase_capacity": "CU_1",
    "schema_name": "app_data_prod",
    "branch_from_env": None,
    "branch_from_workspace_path": None,
    "owner_grant_job_id": None,
}

_BRANCH_RESULT = {
    "type": "autoscaling",
    "name": "db-tellr",
    "status": "READY",
    "host": "h.example",
    "endpoint_name": "ep",
    "branch_id": "dev-spfix",
}

_NONBRANCH_RESULT = {
    "type": "provisioned",
    "name": "db-tellr",
    "status": "READY",
}


def _patch_common(monkeypatch, cfg):
    """Patch every side-effecting helper create_local/update_local call, and
    return a spy standing in for `_setup_database_schema`."""
    schema_spy = MagicMock(name="_setup_database_schema")

    monkeypatch.setattr(deploy_local, "load_deployment_config", lambda env: dict(cfg))
    monkeypatch.setattr(
        deploy_local, "_get_workspace_client", lambda profile=None: MagicMock()
    )
    monkeypatch.setattr(
        deploy_local, "_check_branching_preconditions", lambda ws, config: "enc-key"
    )
    monkeypatch.setattr(
        deploy_local, "_recreate_ephemeral_branch",
        lambda *a, **k: dict(_BRANCH_RESULT),
    )
    monkeypatch.setattr(
        deploy_local, "_get_or_create_lakebase",
        lambda *a, **k: dict(_NONBRANCH_RESULT),
    )
    monkeypatch.setattr(deploy_local, "_write_requirements", lambda *a, **k: None)
    monkeypatch.setattr(
        deploy_local, "_mlflow_substitutions_for_app_yaml", lambda **k: {}
    )
    monkeypatch.setattr(deploy_local, "_write_app_yaml", lambda *a, **k: None)
    monkeypatch.setattr(deploy_local, "_upload_files", lambda *a, **k: None)
    monkeypatch.setattr(deploy_local, "_create_app", lambda *a, **k: MagicMock())
    monkeypatch.setattr(deploy_local, "_get_app_client_id", lambda app: "sp-client-id")
    monkeypatch.setattr(deploy_local, "_ensure_sp_autoscaling_role", lambda *a, **k: None)
    # Defined in deploy_local itself; no-op so it doesn't touch ws.jobs.
    monkeypatch.setattr(deploy_local, "_trigger_owner_grant_job", lambda *a, **k: None)
    monkeypatch.setattr(
        deploy_local, "_deploy_app", lambda *a, **k: MagicMock(url="https://app")
    )
    monkeypatch.setattr(deploy_local, "_setup_database_schema", schema_spy)
    return schema_spy


class TestCreateLocalSchemaSetup:
    def test_fork_path_skips_schema_setup(self, monkeypatch):
        """create_local on a branching env must NOT open the human-identity
        schema-setup connection (SP-only)."""
        schema_spy = _patch_common(monkeypatch, _BRANCH_CFG)

        deploy_local.create_local(
            env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
        )

        schema_spy.assert_not_called()

    def test_nonfork_path_still_sets_up_schema(self, monkeypatch):
        """The non-fork (local/prod) path must be unchanged — schema setup
        still runs there."""
        schema_spy = _patch_common(monkeypatch, _NONBRANCH_CFG)

        deploy_local.create_local(
            env="production", profile="p", from_pypi="0.3.11.dev4"
        )

        schema_spy.assert_called_once()


class TestUpdateLocalSchemaSetup:
    def test_fork_path_skips_schema_setup(self, monkeypatch):
        """update_local on a branching env must NOT open the human-identity
        schema-setup connection either."""
        schema_spy = _patch_common(monkeypatch, _BRANCH_CFG)
        # update_local's branching path GETs the app before re-forking.
        mock_ws = MagicMock()
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: mock_ws
        )

        deploy_local.update_local(
            env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
        )

        schema_spy.assert_not_called()

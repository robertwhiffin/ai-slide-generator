"""Regression tests: dev-loop (fork) deploys must be SP-only.

`_setup_database_schema` / `_reset_schema` connect via `_get_lakebase_connection`,
which authenticates as `ws.current_user.me()` (the deploying human). On the
branching/fork path that step is redundant (the SP is granted into
`tellr_app_owners` WITH INHERIT and the app migrates its own tables at startup),
so it is skipped — otherwise a deployer without a personal Postgres login role
fails with "password authentication failed". These tests pin that behaviour:

  * the fork path must NOT open a human-identity schema connection — neither
    `_setup_database_schema` nor `_reset_schema`;
  * the skip is gated on the owner-grant prerequisite: if the app SP was never
    granted into `tellr_app_owners` (no client id / no owner_grant_job_id) the
    deploy fails loudly instead of shipping an app that can't own its schema;
  * the non-fork (local/prod) path is unchanged.
"""
from unittest.mock import MagicMock

import pytest

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

# Branching env whose config omits owner_grant_job_id — the owner-grant job
# never runs, so skipping schema setup would be unsafe.
_BRANCH_CFG_NO_GRANT_JOB = {**_BRANCH_CFG, "owner_grant_job_id": None}

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
    return spies for the two functions that open a human-identity Postgres
    connection (`_setup_database_schema`, `_reset_schema`)."""
    setup_spy = MagicMock(name="_setup_database_schema")
    reset_spy = MagicMock(name="_reset_schema")

    monkeypatch.setattr(deploy_local, "load_deployment_config", lambda env: dict(cfg))
    monkeypatch.setattr(
        deploy_local, "_get_workspace_client", lambda profile=None: MagicMock()
    )
    monkeypatch.setattr(
        deploy_local, "_check_branching_preconditions", lambda ws, config: "enc-key"
    )
    monkeypatch.setattr(
        deploy_local, "_read_existing_encryption_key", lambda *a, **k: "enc-key"
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
    # Defined in deploy_local itself; no-op so it doesn't touch ws.jobs. It
    # raises on real failure, so a clean return models a successful grant.
    monkeypatch.setattr(deploy_local, "_trigger_owner_grant_job", lambda *a, **k: None)
    monkeypatch.setattr(
        deploy_local, "_deploy_app", lambda *a, **k: MagicMock(url="https://app")
    )
    monkeypatch.setattr(deploy_local, "_setup_database_schema", setup_spy)
    monkeypatch.setattr(deploy_local, "_reset_schema", reset_spy)
    return {"setup": setup_spy, "reset": reset_spy}


class TestCreateLocalSchemaSetup:
    def test_fork_path_skips_schema_setup(self, monkeypatch):
        """create_local on a branching env must NOT open the human-identity
        schema connection — neither _setup_database_schema nor _reset_schema."""
        spies = _patch_common(monkeypatch, _BRANCH_CFG)

        deploy_local.create_local(
            env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
        )

        spies["setup"].assert_not_called()
        spies["reset"].assert_not_called()

    def test_nonfork_path_still_sets_up_schema(self, monkeypatch):
        """The non-fork (local/prod) path must be unchanged — schema setup
        still runs there."""
        spies = _patch_common(monkeypatch, _NONBRANCH_CFG)

        deploy_local.create_local(
            env="production", profile="p", from_pypi="0.3.11.dev4"
        )

        spies["setup"].assert_called_once()

    def test_fork_fails_loudly_when_sp_client_id_missing(self, monkeypatch):
        """If the app SP can't be resolved the owner-grant never runs, so the
        SP does not own the inherited schema — the deploy must fail loudly, not
        silently skip schema setup."""
        spies = _patch_common(monkeypatch, _BRANCH_CFG)
        monkeypatch.setattr(deploy_local, "_get_app_client_id", lambda app: None)

        with pytest.raises(deploy_local.DeploymentError, match="tellr_app_owners"):
            deploy_local.create_local(
                env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
            )

        spies["setup"].assert_not_called()

    def test_fork_fails_loudly_when_owner_grant_job_id_missing(self, monkeypatch):
        """If owner_grant_job_id is unset the grant job never runs, so the skip
        is unsafe and the deploy must fail loudly."""
        spies = _patch_common(monkeypatch, _BRANCH_CFG_NO_GRANT_JOB)

        with pytest.raises(deploy_local.DeploymentError, match="tellr_app_owners"):
            deploy_local.create_local(
                env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
            )

        spies["setup"].assert_not_called()


class TestUpdateLocalSchemaSetup:
    def test_fork_path_skips_schema_setup(self, monkeypatch):
        """update_local on a branching env must NOT open the human-identity
        schema connection either."""
        spies = _patch_common(monkeypatch, _BRANCH_CFG)
        # update_local's branching path GETs the app before re-forking.
        mock_ws = MagicMock()
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: mock_ws
        )

        deploy_local.update_local(
            env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
        )

        spies["setup"].assert_not_called()
        spies["reset"].assert_not_called()

    def test_fork_fails_loudly_when_sp_client_id_missing(self, monkeypatch):
        """Same fail-loud guard as create_local, on the update fork path."""
        spies = _patch_common(monkeypatch, _BRANCH_CFG)
        mock_ws = MagicMock()
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: mock_ws
        )
        monkeypatch.setattr(deploy_local, "_get_app_client_id", lambda app: None)

        with pytest.raises(deploy_local.DeploymentError, match="tellr_app_owners"):
            deploy_local.update_local(
                env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
            )

        spies["setup"].assert_not_called()

    def test_nonfork_path_does_not_call_schema_setup(self, monkeypatch):
        """update_local's non-fork path never calls _setup_database_schema:
        update assumes create already set the schema up and only re-deploys the
        wheel (_reset_schema runs only under --reset-db). This pins that
        pre-existing behaviour so the fork-path fix didn't shift it."""
        spies = _patch_common(monkeypatch, _NONBRANCH_CFG)
        mock_ws = MagicMock()
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: mock_ws
        )

        deploy_local.update_local(
            env="production", profile="p", from_pypi="0.3.11.dev4"
        )

        spies["setup"].assert_not_called()
        spies["reset"].assert_not_called()  # reset_database defaults False

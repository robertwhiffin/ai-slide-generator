"""scripts/deploy_local.py attaches the Lakebase branch after each SP role call.

The dev-loop script creates the app service principal's Postgres role itself
(``_ensure_sp_autoscaling_role``) at two call sites: ``create_local`` and the
fork path of ``update_local``. The attach (``_ensure_app_postgres_resource``)
must follow each one and name the branch that call created the role on: the
fork's own branch (``lakebase_result["branch_id"]``, ``dev-<instance>``) on a
devloop deploy, ``production`` otherwise. It must never run before the role
exists. Given the resource first, the platform creates its own
``dbrx-apps-<client id>`` role and the role setup then fails. So when the role
step is skipped, the attach is skipped too. A refused attach never stops the
deploy.

See tests/unit/test_deploy_postgres_resource.py for the helper itself.
"""

import inspect
from unittest.mock import MagicMock

from databricks.sdk.errors import NotFound
from databricks.sdk.service.apps import App, AppsAPI
from databricks.sdk.service.postgres import Role, RoleRoleStatus

from scripts import deploy_local
from tests.unit.test_deploy_local_schema_setup_sp_only import (
    _BRANCH_CFG,
    _BRANCH_RESULT,
    _NONBRANCH_CFG,
    _patch_common,
)

PROJECT = _BRANCH_CFG["lakebase_name"]
FORK_APP = f"{_BRANCH_CFG['app_name']}-spfix"
FORK_BRANCH = _BRANCH_RESULT["branch_id"]

#: ``_get_or_create_lakebase`` for an existing autoscaling project (non-fork env).
AUTOSCALING_PRODUCTION_RESULT = {
    "name": PROJECT,
    "type": "autoscaling",
    "status": "exists",
    "host": "pg.example.com",
    "endpoint_name": f"projects/{PROJECT}/branches/production/endpoints/primary",
    "project_id": PROJECT,
    "instance_name": None,
}


def _record(monkeypatch, cfg, ws):
    """Patch create_local/update_local and record the role, attach, schema and
    deploy steps. Returns ``(events, roles, attaches)``."""
    _patch_common(monkeypatch, cfg)
    events: list[str] = []
    roles: list[dict] = []
    attaches: list[dict] = []

    def _role(ws_arg, project_name, client_id, branch_name="production"):
        assert ws_arg is ws
        events.append("role")
        roles.append(
            {"project_name": project_name, "client_id": client_id, "branch_name": branch_name}
        )

    def _attach(ws_arg, app_name, project_name, branch_name="production"):
        assert ws_arg is ws
        events.append("attach")
        attaches.append(
            {"app_name": app_name, "project_name": project_name, "branch_name": branch_name}
        )
        return True

    def _schema(*a, **k):
        events.append("schema")

    def _deploy_app(*a, **k):
        events.append("deploy")
        return MagicMock(url="https://app")

    ws.apps.deploy_and_wait.side_effect = lambda *a, **kw: (
        events.append("deploy") or MagicMock(deployment_id="d1")
    )
    monkeypatch.setattr(deploy_local, "_get_workspace_client", lambda profile=None: ws)
    monkeypatch.setattr(deploy_local, "_ensure_sp_autoscaling_role", _role)
    monkeypatch.setattr(deploy_local, "_ensure_app_postgres_resource", _attach)
    monkeypatch.setattr(deploy_local, "_setup_database_schema", _schema)
    monkeypatch.setattr(deploy_local, "_deploy_app", _deploy_app)
    return events, roles, attaches


def test_fork_create_attaches_the_forks_branch_after_the_role(monkeypatch):
    ws = MagicMock()
    events, roles, attaches = _record(monkeypatch, _BRANCH_CFG, ws)

    deploy_local.create_local(
        env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
    )

    assert events == ["role", "attach", "deploy"]
    assert attaches == [
        {"app_name": FORK_APP, "project_name": PROJECT, "branch_name": FORK_BRANCH}
    ]
    assert roles[0]["branch_name"] == FORK_BRANCH


def test_fork_update_attaches_the_forks_branch_after_the_role(monkeypatch):
    ws = MagicMock()
    events, roles, attaches = _record(monkeypatch, _BRANCH_CFG, ws)

    deploy_local.update_local(
        env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
    )

    assert events == ["role", "attach", "deploy"]
    assert attaches == [
        {"app_name": FORK_APP, "project_name": PROJECT, "branch_name": FORK_BRANCH}
    ]
    assert roles[0]["branch_name"] == FORK_BRANCH


def test_autoscaling_create_attaches_production_after_the_role(monkeypatch):
    ws = MagicMock()
    events, roles, attaches = _record(monkeypatch, _NONBRANCH_CFG, ws)
    monkeypatch.setattr(
        deploy_local,
        "_get_or_create_lakebase",
        lambda *a, **k: dict(AUTOSCALING_PRODUCTION_RESULT),
    )

    deploy_local.create_local(env="production", profile="p", from_pypi="0.3.11.dev4")

    assert events == ["role", "attach", "schema", "deploy"]
    assert attaches == [
        {
            "app_name": _NONBRANCH_CFG["app_name"],
            "project_name": PROJECT,
            "branch_name": "production",
        }
    ]
    assert roles[0]["branch_name"] == "production"


def test_autoscaling_create_without_the_role_does_not_attach(monkeypatch):
    """No SP client id: the role is skipped, so the attach must be too."""
    ws = MagicMock()
    events, _roles, attaches = _record(monkeypatch, _NONBRANCH_CFG, ws)
    monkeypatch.setattr(
        deploy_local,
        "_get_or_create_lakebase",
        lambda *a, **k: dict(AUTOSCALING_PRODUCTION_RESULT),
    )
    monkeypatch.setattr(deploy_local, "_get_app_client_id", lambda app: None)

    deploy_local.create_local(env="production", profile="p", from_pypi="0.3.11.dev4")

    assert events == ["schema", "deploy"]
    assert attaches == []


def test_provisioned_create_does_not_attach(monkeypatch):
    ws = MagicMock()
    events, _roles, attaches = _record(monkeypatch, _NONBRANCH_CFG, ws)

    deploy_local.create_local(env="production", profile="p", from_pypi="0.3.11.dev4")

    assert events == ["schema", "deploy"]
    assert attaches == []


def test_a_failed_attach_warns_and_the_fork_create_still_deploys(monkeypatch, capsys):
    """The real attach, refused by the workspace: the dev deploy still ships."""
    _patch_common(monkeypatch, _BRANCH_CFG)
    deployed: list[str] = []
    fork_branch = f"projects/{PROJECT}/branches/{FORK_BRANCH}"
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name=FORK_APP,
        description="AI Slide Generator",
        service_principal_client_id="sp-client-id",
    )

    def _list_roles(parent, page_size=None, page_token=None):
        # The SP's role, on the fork's own branch only (role setup just made it).
        if parent != fork_branch:
            raise NotFound(f"Branch {parent} does not exist")
        return iter([Role(status=RoleRoleStatus(postgres_role="sp-client-id"))])

    ws.postgres.list_roles.side_effect = _list_roles
    ws.apps.create_update.side_effect = RuntimeError("postgres app resources are not enabled")
    monkeypatch.setattr(deploy_local, "_get_workspace_client", lambda profile=None: ws)
    monkeypatch.setattr(
        deploy_local,
        "_deploy_app",
        lambda *a, **k: deployed.append("deploy") or MagicMock(url="https://app"),
    )

    result = deploy_local.create_local(
        env="devloop", profile="p", from_pypi="0.3.11.dev4", instance="spfix"
    )

    ws.apps.create_update.assert_called_once()  # the attach WAS attempted
    call = ws.apps.create_update.call_args
    bound = inspect.signature(AppsAPI.create_update).bind(None, *call.args, **call.kwargs)
    assert bound.arguments["update_mask"] == "resources"
    sent = bound.arguments["app"]
    assert [r.postgres.branch for r in sent.resources if r.postgres is not None] == [
        fork_branch
    ]
    ws.apps.update.assert_not_called()
    assert deployed == ["deploy"]
    assert result["status"] == "created"
    out = capsys.readouterr().out
    assert any(
        "WARNING" in line and "postgres app resources are not enabled" in line
        for line in out.splitlines()
    ), out

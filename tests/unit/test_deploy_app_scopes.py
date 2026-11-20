"""App OAuth scopes in the deploy package (Genie One in agent mode, Task 1)."""

import inspect
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.service.apps import App, AppsAPI, ComputeSize
from databricks_tellr import deploy, secret_key

EXPECTED_SCOPES = [
    "sql",
    "dashboards.genie",
    "catalog.tables:read",
    "catalog.schemas:read",
    "catalog.catalogs:read",
    "serving.serving-endpoints",
    "ai-gateway",
    "catalog.connections",
    "mcp.external",
]


def test_create_app_requests_the_full_scope_list_in_order():
    ws = MagicMock()
    deploy._create_app(
        ws, "app", "desc", "/ws/src", "MEDIUM", "lb", lakebase_type="provisioned"
    )
    created = ws.apps.create_and_wait.call_args.args[0]
    assert created.user_api_scopes == EXPECTED_SCOPES
    assert list(deploy.REQUIRED_USER_API_SCOPES) == EXPECTED_SCOPES


def test_ensure_adds_only_missing_scopes_after_existing_ones():
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name="app", user_api_scopes=["sql", "genie", "dashboards.genie"]
    )
    added = deploy._ensure_app_user_api_scopes(ws, "app")
    assert added == [s for s in EXPECTED_SCOPES if s not in ("sql", "dashboards.genie")]
    sent = ws.apps.update.call_args.kwargs["app"]
    assert sent.user_api_scopes == ["sql", "genie", "dashboards.genie"] + added
    assert ws.apps.update.call_args.kwargs["name"] == "app"


def test_ensure_makes_no_update_call_when_nothing_is_missing():
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name="app", user_api_scopes=list(reversed(EXPECTED_SCOPES)) + ["extra"]
    )
    assert deploy._ensure_app_user_api_scopes(ws, "app") == []
    ws.apps.update.assert_not_called()


def test_ensure_carries_description_source_path_and_resources_and_omits_compute_size():
    ws = MagicMock()
    db_resource = MagicMock()
    db_resource.name = "app_database"
    ws.apps.get.return_value = App(
        name="app",
        description="Tellr",
        compute_size=ComputeSize.MEDIUM,
        default_source_code_path="/ws/src",
        user_api_scopes=["sql"],
        resources=[db_resource],
    )
    deploy._ensure_app_user_api_scopes(ws, "app")
    sent = ws.apps.update.call_args.kwargs["app"]
    assert sent.compute_size is None
    assert sent.description == "Tellr"
    assert sent.default_source_code_path == "/ws/src"
    assert sent.resources == [db_resource]


def _stub_update_steps(monkeypatch, ws):
    """Stub every _update_databricks step but the scope update and the deploy."""

    @contextmanager
    def _staging():
        yield "/tmp/staging"

    monkeypatch.setattr(deploy, "_get_workspace_client", lambda c, p: ws)
    monkeypatch.setattr(secret_key, "app_is_secret_mode", lambda w, n: False)
    monkeypatch.setattr(deploy, "_read_existing_encryption_key", lambda w, p: None)
    monkeypatch.setattr(
        deploy, "_get_or_create_lakebase", lambda *a, **k: {"type": "provisioned"}
    )
    monkeypatch.setattr(deploy, "_check_breaking_migrations", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_staging_dir", _staging)
    monkeypatch.setattr(deploy, "_write_requirements", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_write_app_yaml", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_upload_files", lambda *a, **k: None)


def test_a_failed_scope_update_warns_and_the_update_still_deploys(monkeypatch, capsys):
    """Final fix (M6): a workspace that refuses the scope change (or a caller who
    may not update the app) must not abort tellr.update(): the new version ships
    and the admin is told which scope Genie One needs."""
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name="app", url="https://app.example", user_api_scopes=["sql"]
    )
    ws.apps.update.side_effect = RuntimeError("scope ai-gateway is not allowed in this workspace")
    ws.apps.deploy_and_wait.return_value = MagicMock(deployment_id="d1")
    _stub_update_steps(monkeypatch, ws)

    deploy._update_databricks(
        app_name="app",
        app_file_workspace_path="/ws",
        lakebase_name="lb",
        schema_name="s",
    )

    ws.apps.update.assert_called_once()
    ws.apps.deploy_and_wait.assert_called_once()
    out = capsys.readouterr().out
    assert "WARNING: could not add scopes" in out
    assert "scope ai-gateway is not allowed in this workspace" in out
    assert "Genie One needs ai-gateway — add it in the app settings" in out


def test_update_ensures_scopes_before_deploying(monkeypatch):
    """_update_databricks must add missing scopes before deploy_and_wait."""
    order: list[str] = []
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name="app", url="https://app.example", user_api_scopes=["sql"]
    )
    ws.apps.update.side_effect = lambda **kw: order.append("update")
    ws.apps.deploy_and_wait.side_effect = lambda **kw: (
        order.append("deploy") or MagicMock(deployment_id="d1")
    )

    @contextmanager
    def _staging():
        yield "/tmp/staging"

    monkeypatch.setattr(deploy, "_get_workspace_client", lambda c, p: ws)
    monkeypatch.setattr(secret_key, "app_is_secret_mode", lambda w, n: False)
    monkeypatch.setattr(deploy, "_read_existing_encryption_key", lambda w, p: None)
    monkeypatch.setattr(
        deploy, "_get_or_create_lakebase", lambda *a, **k: {"type": "provisioned"}
    )
    monkeypatch.setattr(deploy, "_check_breaking_migrations", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_staging_dir", _staging)
    monkeypatch.setattr(deploy, "_write_requirements", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_write_app_yaml", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_upload_files", lambda *a, **k: None)

    deploy._update_databricks(
        app_name="app",
        app_file_workspace_path="/ws",
        lakebase_name="lb",
        schema_name="s",
    )

    assert order == ["update", "deploy"]


# --- update also attaches an autoscaling install's Lakebase branch -------------
# The resource is what attributes the database's usage to the app; see
# tests/unit/test_deploy_postgres_resource.py for the helper and the create path.

_AUTOSCALING_LAKEBASE = {
    "name": "lb",
    "type": "autoscaling",
    "status": "exists",
    "host": "pg.example.com",
    "endpoint_name": "projects/lb/branches/production/endpoints/primary",
    "project_id": "lb",
    "instance_name": None,
}

_PROVISIONED_LAKEBASE = {
    "name": "lb",
    "type": "provisioned",
    "status": "exists",
    "state": "AVAILABLE",
    "host": None,
    "endpoint_name": None,
    "project_id": None,
    "instance_name": "lb",
}


def _app_with_every_scope() -> App:
    """An app the scope update leaves alone, so any ``apps.update`` is the attach."""
    return App(
        name="app",
        url="https://app.example",
        service_principal_client_id="cid",
        user_api_scopes=list(EXPECTED_SCOPES),
    )


@pytest.mark.parametrize(
    "lakebase_result, expected_attaches, expected_order",
    [
        (
            _AUTOSCALING_LAKEBASE,
            [{"app_name": "app", "project_name": "lb", "branch_name": "production"}],
            ["attach", "deploy"],
        ),
        (_PROVISIONED_LAKEBASE, [], ["deploy"]),
    ],
    ids=["autoscaling", "provisioned"],
)
def test_update_attaches_the_lakebase_branch_before_deploying_on_autoscaling_only(
    monkeypatch, lakebase_result, expected_attaches, expected_order
):
    order: list[str] = []
    attaches: list[dict] = []
    ws = MagicMock()
    ws.apps.get.return_value = _app_with_every_scope()
    ws.apps.deploy_and_wait.side_effect = lambda *a, **kw: (
        order.append("deploy") or MagicMock(deployment_id="d1")
    )
    _stub_update_steps(monkeypatch, ws)
    monkeypatch.setattr(
        deploy, "_get_or_create_lakebase", lambda *a, **k: dict(lakebase_result)
    )

    def _attach(ws_arg, app_name, project_name, branch_name="production"):
        assert ws_arg is ws
        order.append("attach")
        attaches.append(
            {"app_name": app_name, "project_name": project_name, "branch_name": branch_name}
        )
        return True

    monkeypatch.setattr(deploy, "_ensure_app_postgres_resource", _attach)

    deploy._update_databricks(
        app_name="app",
        app_file_workspace_path="/ws",
        lakebase_name="lb",
        schema_name="s",
    )

    assert attaches == expected_attaches
    assert order == expected_order


def test_a_failed_lakebase_attach_warns_and_the_update_still_deploys(monkeypatch, capsys):
    """The real attach, refused by the workspace: tellr.update() still ships the
    new version (same contract as the scopes and the CAN_MANAGE grant)."""
    ws = MagicMock()
    ws.apps.get.return_value = _app_with_every_scope()
    ws.apps.update.side_effect = RuntimeError("postgres app resources are not enabled")
    ws.apps.deploy_and_wait.return_value = MagicMock(deployment_id="d1")
    _stub_update_steps(monkeypatch, ws)
    monkeypatch.setattr(
        deploy, "_get_or_create_lakebase", lambda *a, **k: dict(_AUTOSCALING_LAKEBASE)
    )

    result = deploy._update_databricks(
        app_name="app",
        app_file_workspace_path="/ws",
        lakebase_name="lb",
        schema_name="s",
    )

    # Every scope is present, so the one update call is the attach.
    ws.apps.update.assert_called_once()
    call = ws.apps.update.call_args
    sent = inspect.signature(AppsAPI.update).bind(None, *call.args, **call.kwargs).arguments["app"]
    assert [r.postgres.branch for r in sent.resources if r.postgres is not None] == [
        "projects/lb/branches/production"
    ]
    ws.apps.deploy_and_wait.assert_called_once()
    assert result["status"] == "updated"
    out = capsys.readouterr().out
    assert any(
        "WARNING" in line and "postgres app resources are not enabled" in line
        for line in out.splitlines()
    ), out

"""App OAuth scopes in the deploy package (Genie One in agent mode, Task 1)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.service.apps import App, ComputeSize
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

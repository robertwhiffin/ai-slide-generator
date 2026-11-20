"""The installer links an autoscaling install's Lakebase branch to its app.

Why: an app resource naming the Lakebase branch is what lets the platform
attribute the database's usage to the app. It changes nothing about how the app
connects (it keeps reading the ``LAKEBASE_*`` settings from ``app.yaml``).

Facts verified live on a real workspace (Nov 2026) that these tests pin:

* attached AFTER ``_ensure_sp_autoscaling_role`` has created the service
  principal's role (``sp-<client id>``) it is clean: no restart, roles
  unchanged, the redeploy is healthy, a second attach is a no-op, and a later
  ``tellr.update`` keeps it;
* passed to ``apps.create`` instead, the platform creates the role itself as
  ``dbrx-apps-<client id>`` with no membership, and ``_ensure_sp_autoscaling_role``
  then fails with "role with that name already exists", aborting the install.
  So ``_create_app`` must never carry it, and nothing may attach it before the
  role exists;
* the shape that worked is ``app_database`` /
  ``AppResourcePostgres(branch="projects/<p>/branches/<b>",
  database="projects/<p>/branches/<b>/databases/databricks-postgres",
  permission=CAN_CONNECT_AND_CREATE)``;
* ``apps.update`` is a full replace on the fields it accepts: omitting
  ``description`` blanks it, omitting ``user_api_scopes`` nulls it, and passing
  ``compute_size`` is rejected.

The attach never fails an install or an upgrade: every failure prints a
warning and the deploy carries on.

Run with ``PYTHONPATH=packages/databricks-tellr`` or this module SKIPS.
"""

import inspect
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service import apps as sdk_apps
from databricks.sdk.service.apps import (
    App,
    AppResource,
    AppResourceDatabase,
    AppResourceDatabaseDatabasePermission,
    AppResourcePostgres,
    AppResourcePostgresPostgresPermission,
    AppResourceSecret,
    AppResourceSecretSecretPermission,
    AppResourceSqlWarehouse,
    AppResourceSqlWarehouseSqlWarehousePermission,
    AppsAPI,
    ComputeSize,
)
from databricks_tellr import deploy, secret_key

APP_NAME = "tellr"
PROJECT = "tellr-db"
BRANCH = f"projects/{PROJECT}/branches/production"
DATABASE = f"{BRANCH}/databases/databricks-postgres"

#: The request body for the resource, exactly as verified live.
EXPECTED_RESOURCE = {
    "name": "app_database",
    "postgres": {
        "branch": BRANCH,
        "database": DATABASE,
        "permission": "CAN_CONNECT_AND_CREATE",
    },
}

SCOPES = list(deploy.REQUIRED_USER_API_SCOPES)

#: What ``_get_or_create_lakebase`` returns for an existing autoscaling project.
AUTOSCALING_RESULT = {
    "name": PROJECT,
    "type": "autoscaling",
    "status": "exists",
    "host": "pg.example.com",
    "endpoint_name": f"{BRANCH}/endpoints/primary",
    "project_id": PROJECT,
    "instance_name": None,
}

#: What ``_get_or_create_lakebase`` returns for an existing provisioned instance.
PROVISIONED_RESULT = {
    "name": PROJECT,
    "type": "provisioned",
    "status": "exists",
    "state": "AVAILABLE",
    "host": None,
    "endpoint_name": None,
    "project_id": None,
    "instance_name": PROJECT,
}


def _bound(method_mock, real_method):
    """Bind the single call on ``method_mock`` to the REAL SDK signature.

    Positional-vs-keyword style then does not matter, but a wrong parameter name
    (or a call the real API would reject) fails here.
    """
    method_mock.assert_called_once()
    call = method_mock.call_args
    return inspect.signature(real_method).bind(None, *call.args, **call.kwargs).arguments


def _sent_update(ws) -> tuple[str, App]:
    """``(name, app)`` of the one ``apps.update`` call."""
    args = _bound(ws.apps.update, AppsAPI.update)
    return args["name"], args["app"]


def _live_app(**overrides) -> App:
    """The app as ``apps.get`` returns it, read-only fields included.

    ``compute_size`` is set on purpose: handing this object straight back to
    ``apps.update`` is rejected by the real API, so a test using it catches an
    implementation that does that.
    """
    fields = dict(
        name=APP_NAME,
        description="Tellr AI Slide Generator",
        compute_size=ComputeSize.MEDIUM,
        default_source_code_path="/Workspace/Users/x/.apps/tellr",
        user_api_scopes=list(SCOPES),
        resources=None,
        url="https://tellr.example",
        service_principal_client_id="cid",
    )
    fields.update(overrides)
    return App(**fields)


def _ws(app: App) -> MagicMock:
    """A workspace that knows exactly one app, ``app``."""
    ws = MagicMock()

    def _get(name):
        if name != app.name:
            raise NotFound(f"App {name} does not exist")
        return app

    ws.apps.get.side_effect = _get
    return ws


def _warning_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if "WARNING" in line]


# --- the helper itself ---------------------------------------------------------


def test_attaches_the_branch_last_and_carries_every_other_field():
    existing = [
        secret_key.build_secret_resource("tellr", "tellr-encryption-key"),
        AppResource(
            name="sql_warehouse",
            sql_warehouse=AppResourceSqlWarehouse(
                id="wh-1", permission=AppResourceSqlWarehouseSqlWarehousePermission.CAN_USE
            ),
        ),
    ]
    ws = _ws(_live_app(resources=list(existing)))

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is True

    name, sent = _sent_update(ws)  # exactly one update call
    assert name == APP_NAME
    assert isinstance(sent, App)
    assert sent.name == APP_NAME
    # The existing resources, unchanged and in their order, then the new one.
    assert sent.resources[:-1] == existing
    assert len(sent.resources) == len(existing) + 1
    added = sent.resources[-1]
    assert added.as_dict() == EXPECTED_RESOURCE
    assert added.postgres.permission is AppResourcePostgresPostgresPermission.CAN_CONNECT_AND_CREATE
    # apps.update is a full replace: every mutable field is carried as it was.
    assert sent.description == "Tellr AI Slide Generator"
    assert sent.default_source_code_path == "/Workspace/Users/x/.apps/tellr"
    assert sent.user_api_scopes == SCOPES
    # ...and compute_size is never sent (the update API rejects it).
    assert sent.compute_size is None
    assert "compute_size" not in sent.as_dict()


def test_names_the_forks_own_branch():
    ws = _ws(_live_app())

    assert (
        deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT, branch_name="dev-x")
        is True
    )

    _, sent = _sent_update(ws)
    assert [r.as_dict() for r in sent.resources] == [
        {
            "name": "app_database",
            "postgres": {
                "branch": f"projects/{PROJECT}/branches/dev-x",
                "database": f"projects/{PROJECT}/branches/dev-x/databases/databricks-postgres",
                "permission": "CAN_CONNECT_AND_CREATE",
            },
        }
    ]


@pytest.mark.parametrize(
    "existing",
    [
        AppResource(
            name="app_database",
            postgres=AppResourcePostgres(
                branch=BRANCH,
                database=DATABASE,
                permission=AppResourcePostgresPostgresPermission.CAN_CONNECT_AND_CREATE,
            ),
        ),
        AppResource(
            name="app_database",
            database=AppResourceDatabase(
                instance_name=PROJECT,
                database_name="databricks_postgres",
                permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
            ),
        ),
        AppResource(
            name="my_pg",
            postgres=AppResourcePostgres(
                branch="projects/other/branches/main",
                database="projects/other/branches/main/databases/databricks-postgres",
            ),
        ),
        AppResource(
            name="my_db",
            database=AppResourceDatabase(
                instance_name="other-instance",
                database_name="databricks_postgres",
                permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
            ),
        ),
        # Same name, another kind: a second "app_database" would collide.
        AppResource(
            name="app_database",
            secret=AppResourceSecret(
                scope="tellr", key="k", permission=AppResourceSecretSecretPermission.READ
            ),
        ),
    ],
    ids=[
        "the-resource-this-installer-attached",
        "provisioned-app_database",
        "postgres-under-another-name",
        "database-under-another-name",
        "app_database-of-another-kind",
    ],
)
def test_an_app_that_already_has_a_database_resource_is_left_alone(existing):
    ws = _ws(_live_app(resources=[existing]))

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.update.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("feature not enabled"),
        PermissionDenied("User does not have permission apps/update on tellr"),
    ],
    ids=["refused", "permission-denied"],
)
def test_a_refused_update_warns_with_the_error_and_continues(capsys, error):
    ws = _ws(_live_app())
    ws.apps.update.side_effect = error

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.update.assert_called_once()  # it was attempted
    lines = _warning_lines(capsys.readouterr().out)
    assert any(str(error) in line for line in lines), lines


def test_a_failed_lookup_warns_with_the_error_and_continues(capsys):
    ws = MagicMock()
    ws.apps.get.side_effect = RuntimeError("no such app")

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert any("no such app" in line for line in lines), lines


def test_an_sdk_without_the_postgres_resource_warns_and_continues(monkeypatch, capsys):
    """The installer allows databricks-sdk>=0.85.0, which can predate
    ``AppResourcePostgres``. Model that SDK: the names are gone from the SDK
    module and from deploy's namespace, so the helper must neither raise nor
    send anything, and must say why."""
    for name in ("AppResourcePostgres", "AppResourcePostgresPostgresPermission"):
        monkeypatch.delattr(sdk_apps, name)
        monkeypatch.delattr(deploy, name, raising=False)
    monkeypatch.setattr(deploy, "HAS_POSTGRES_RESOURCE", False, raising=False)
    ws = _ws(_live_app())

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert any("databricks-sdk" in line for line in lines), lines


def test_an_sdk_without_the_role_api_warns_and_does_not_attach(monkeypatch, capsys):
    """Without the role SDK, ``_ensure_sp_autoscaling_role`` creates no role, and
    attaching then would make the platform create its own role for the service
    principal. So the helper touches nothing and says why, on one line."""
    monkeypatch.setattr(deploy, "HAS_ROLE_SDK", False)
    ws = _ws(_live_app())

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.get.assert_not_called()
    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines


# --- _create_app never carries it ------------------------------------------------


@pytest.mark.parametrize("scope", [None, "tellr"], ids=["lakebase-key", "secret-key"])
def test_create_app_on_autoscaling_never_carries_a_database_resource(scope):
    """Passing it to apps.create makes the platform create the role itself, and
    the installer's own role setup then fails with 'role with that name already
    exists'."""
    ws = MagicMock()

    deploy._create_app(
        ws,
        APP_NAME,
        "desc",
        "/ws/src",
        "MEDIUM",
        PROJECT,
        lakebase_type="autoscaling",
        encryption_secret_scope=scope,
        encryption_secret_key="tellr-encryption-key" if scope else None,
    )

    created = _bound(ws.apps.create_and_wait, AppsAPI.create_and_wait)["app"]
    expected = (
        [secret_key.build_secret_resource(scope, "tellr-encryption-key")] if scope else []
    )
    assert list(created.resources or []) == expected
    # Nor is it attached right after create: the role does not exist yet.
    ws.apps.update.assert_not_called()


def test_create_app_on_provisioned_still_carries_the_database_resource():
    ws = MagicMock()

    deploy._create_app(
        ws, APP_NAME, "desc", "/ws/src", "MEDIUM", PROJECT, lakebase_type="provisioned"
    )

    created = _bound(ws.apps.create_and_wait, AppsAPI.create_and_wait)["app"]
    assert created.resources == [
        AppResource(
            name="app_database",
            database=AppResourceDatabase(
                instance_name=PROJECT,
                database_name="databricks_postgres",
                permission=AppResourceDatabaseDatabasePermission.CAN_CONNECT_AND_CREATE,
            ),
        )
    ]
    ws.apps.update.assert_not_called()


# --- create: attach after the role, before the schema and the deploy --------------


def _stub_create_steps(monkeypatch, lakebase_result, events, roles, sp_client_id="cid"):
    """Stub every ``_create_databricks`` step but the attach; record the order.

    ``_staging_dir``/``_write_requirements``/``_write_app_yaml`` are stubbed too
    so nothing touches the filesystem.
    """

    @contextmanager
    def _staging():
        yield "/tmp/staging"

    def _create_app(*a, **k):
        events.append("create_app")
        return App(name=APP_NAME, service_principal_client_id=sp_client_id)

    def _role(ws, project_name, client_id, branch_name="production"):
        events.append("role")
        roles.append(
            {"ws": ws, "project_name": project_name, "client_id": client_id,
             "branch_name": branch_name}
        )

    def _schema(*a, **k):
        events.append("schema")

    def _deploy_app(*a, **k):
        events.append("deploy")
        return App(name=APP_NAME, url="https://tellr.example")

    monkeypatch.setattr(deploy, "_get_or_create_lakebase", lambda *a, **k: dict(lakebase_result))
    monkeypatch.setattr(deploy, "_staging_dir", _staging)
    monkeypatch.setattr(deploy, "_write_requirements", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_write_app_yaml", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_upload_files", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_create_app", _create_app)
    monkeypatch.setattr(deploy, "_ensure_app_sp_can_manage", lambda *a, **k: True)
    monkeypatch.setattr(deploy, "_ensure_sp_autoscaling_role", _role)
    monkeypatch.setattr(deploy, "_setup_database_schema", _schema)
    monkeypatch.setattr(deploy, "_deploy_app", _deploy_app)


def _record_attach(monkeypatch, events, attaches):
    """Replace the attach with a recorder of the same signature."""

    def _attach(ws, app_name, project_name, branch_name="production"):
        events.append("attach")
        attaches.append(
            {"ws": ws, "app_name": app_name, "project_name": project_name,
             "branch_name": branch_name}
        )
        return True

    monkeypatch.setattr(deploy, "_ensure_app_postgres_resource", _attach)


def _run_create(ws):
    return deploy.create(
        lakebase_name=PROJECT,
        schema_name="app_data",
        app_name=APP_NAME,
        app_file_workspace_path="/ws/src",
        client=ws,
    )


def test_create_attaches_after_the_role_and_before_the_schema_and_deploy(monkeypatch):
    events: list[str] = []
    roles: list[dict] = []
    attaches: list[dict] = []
    _stub_create_steps(monkeypatch, AUTOSCALING_RESULT, events, roles)
    _record_attach(monkeypatch, events, attaches)
    ws = MagicMock()

    result = _run_create(ws)

    assert events == ["create_app", "role", "attach", "schema", "deploy"]
    assert attaches == [
        {"ws": ws, "app_name": APP_NAME, "project_name": PROJECT, "branch_name": "production"}
    ]
    # The branch named is the one the role was just created on.
    assert attaches[0]["branch_name"] == roles[0]["branch_name"]
    assert result["status"] == "created"


def test_create_without_the_role_does_not_attach(monkeypatch):
    """No service principal client id means no role, so no attach either: given
    the resource without the role, the platform makes its own role."""
    events: list[str] = []
    roles: list[dict] = []
    attaches: list[dict] = []
    _stub_create_steps(monkeypatch, AUTOSCALING_RESULT, events, roles, sp_client_id=None)
    _record_attach(monkeypatch, events, attaches)

    _run_create(MagicMock())

    assert events == ["create_app", "schema", "deploy"]
    assert attaches == []


def test_create_on_provisioned_lakebase_does_not_attach(monkeypatch):
    events: list[str] = []
    roles: list[dict] = []
    attaches: list[dict] = []
    _stub_create_steps(monkeypatch, PROVISIONED_RESULT, events, roles)
    _record_attach(monkeypatch, events, attaches)

    _run_create(MagicMock())

    assert events == ["create_app", "schema", "deploy"]
    assert attaches == []


def test_a_failed_attach_warns_and_the_create_still_deploys(monkeypatch, capsys):
    """The real attach, refused by the workspace: the install still completes."""
    events: list[str] = []
    roles: list[dict] = []
    _stub_create_steps(monkeypatch, AUTOSCALING_RESULT, events, roles)
    ws = _ws(_live_app(name=APP_NAME))
    ws.apps.update.side_effect = RuntimeError("postgres app resources are not enabled")

    result = _run_create(ws)

    ws.apps.update.assert_called_once()  # the attach WAS attempted
    _, sent = _sent_update(ws)
    assert sent.resources[-1].as_dict() == EXPECTED_RESOURCE
    assert events == ["create_app", "role", "schema", "deploy"]
    assert result["status"] == "created"
    lines = _warning_lines(capsys.readouterr().out)
    assert any("postgres app resources are not enabled" in line for line in lines), lines

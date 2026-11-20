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
* the request that worked is the resources-only update,
  ``apps.create_update(update_mask="resources", app=App(name, resources))``:
  it reached SUCCEEDED in about 2 s, did not restart the app, and left the
  description, scopes, source path and compute size alone. ``apps.update`` is
  a full replace instead: whatever it is not sent, it clears.

The attach also needs the service principal's role on the branch (found by its
Postgres name), and is skipped if the app carries a resource this SDK cannot
model, since ``resources`` is replaced as a whole.

The attach never fails an install or an upgrade: every failure prints a
warning and the deploy carries on.
"""

import inspect
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import DEFAULT, MagicMock

import pytest

# Puts packages/databricks-tellr on sys.path (scripts/deploy_local.py), so this
# module imports databricks_tellr in the CI shape too, whatever the collection
# order.
from scripts import deploy_local  # noqa: F401

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.errors import NotFound, OperationFailed, PermissionDenied
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
    AppUpdate,
    AppUpdateUpdateStatus,
    AppUpdateUpdateStatusUpdateState,
    ComputeSize,
)
from databricks.sdk.service.postgres import Role, RoleRoleStatus
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

SUCCEEDED = AppUpdateUpdateStatusUpdateState.SUCCEEDED

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


def _sent_update(ws) -> tuple[str, str, App]:
    """``(app_name, update_mask, app)`` of the one ``apps.create_update`` call."""
    args = _bound(ws.apps.create_update, AppsAPI.create_update)
    return args["app_name"], args["update_mask"], args["app"]


def _sp_role(postgres_role: str, role_id: str | None = None) -> Role:
    """A Postgres role as ``list_roles`` returns it."""
    return Role(
        name=f"{BRANCH}/roles/{role_id or 'sp-' + postgres_role}",
        status=RoleRoleStatus(postgres_role=postgres_role),
    )


def _update_result(state, message: str = "App update succeeded.") -> AppUpdate:
    """What ``create_update(...).result()`` returns."""
    return AppUpdate(status=AppUpdateUpdateStatus(state=state, message=message))


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


def _ws(app: App, roles: dict[str, list[Role]] | None = None) -> MagicMock:
    """A workspace that knows exactly one app, ``app``, and each branch's roles.

    ``roles`` maps a branch path to what ``list_roles`` returns for it. By
    default the production branch has the app's service-principal role. Listing
    a branch not in the map raises ``NotFound``, so the lookup must name the
    branch being attached. The full-replace ``apps.update`` (the scope and
    secret writers) changes what ``apps.get`` returns. ``create_update`` reaches
    SUCCEEDED.
    """
    state = {"app": app}
    if roles is None:
        client_id = app.service_principal_client_id
        roles = {BRANCH: [_sp_role(client_id)] if client_id else []}
    ws = MagicMock()

    def _get(name):
        if name != state["app"].name:
            raise NotFound(f"App {name} does not exist")
        return state["app"]

    def _update(name, app):
        state["app"] = replace(
            state["app"],
            description=app.description,
            default_source_code_path=app.default_source_code_path,
            user_api_scopes=app.user_api_scopes,
            resources=app.resources,
        )

    def _list_roles(parent, page_size=None, page_token=None):
        if parent not in roles:
            raise NotFound(f"Branch {parent} does not exist")
        return iter(roles[parent])

    ws.apps.get.side_effect = _get
    ws.apps.update.side_effect = _update
    ws.postgres.list_roles.side_effect = _list_roles
    ws.apps.create_update.return_value.result.return_value = _update_result(SUCCEEDED)
    return ws


def _warning_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if "WARNING" in line]


# --- the helper itself ---------------------------------------------------------


def test_attaches_the_branch_last_with_a_resources_only_update():
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

    app_name, update_mask, sent = _sent_update(ws)  # exactly one masked update
    assert app_name == APP_NAME
    assert update_mask == "resources"
    ws.apps.create_update.return_value.result.assert_called_once()  # it waited
    # Never the full-replace update, which clears whatever it is not sent.
    ws.apps.update.assert_not_called()
    assert isinstance(sent, App)
    # The existing resources, unchanged and in their order, then the new one.
    assert sent.resources[:-1] == existing
    assert len(sent.resources) == len(existing) + 1
    added = sent.resources[-1]
    assert added.as_dict() == EXPECTED_RESOURCE
    assert added.postgres.permission is AppResourcePostgresPostgresPermission.CAN_CONNECT_AND_CREATE
    # Only the name and the resources are sent: no other field can change.
    assert sent.as_dict() == {
        "name": APP_NAME,
        "resources": [r.as_dict() for r in existing] + [EXPECTED_RESOURCE],
    }
    for field in ("description", "default_source_code_path", "user_api_scopes", "compute_size"):
        assert getattr(sent, field) is None, field
    # The role was looked up on the branch being attached.
    ws.postgres.list_roles.assert_called_once_with(parent=BRANCH)


def test_says_it_is_attaching_before_the_update_it_waits_on(capsys):
    """``create_update(...).result()`` can wait a long time, so one progress line is
    printed just before the request, and the success line once it has SUCCEEDED."""
    ws = _ws(_live_app())
    printed_before_the_update: list[str] = []

    def _record_what_was_printed(*args, **kwargs):
        printed_before_the_update.extend(capsys.readouterr().out.splitlines())
        return DEFAULT  # the mock's own return value: an update that reaches SUCCEEDED

    ws.apps.create_update.side_effect = _record_what_was_printed

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is True

    ws.apps.create_update.assert_called_once()
    assert printed_before_the_update == [
        "   Attaching the Lakebase branch to the app as a resource..."
    ]
    assert capsys.readouterr().out.splitlines() == [
        "   Lakebase branch attached to the app as a resource"
    ]


def test_names_the_forks_own_branch():
    fork_branch = f"projects/{PROJECT}/branches/dev-x"
    ws = _ws(_live_app(), roles={fork_branch: [_sp_role("cid")]})

    assert (
        deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT, branch_name="dev-x")
        is True
    )

    _, _, sent = _sent_update(ws)
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
def test_an_app_that_already_has_a_database_resource_is_left_alone(capsys, existing):
    ws = _ws(_live_app(resources=[existing]))

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.create_update.assert_not_called()
    ws.apps.update.assert_not_called()
    # Nothing to do, so nothing printed: no progress line, no warning.
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "error, raised_by",
    [
        (RuntimeError("feature not enabled"), "request"),
        (PermissionDenied("User does not have permission apps/update on tellr"), "request"),
        # The SDK waiter raises this when the update reaches FAILED.
        (OperationFailed("failed to reach SUCCEEDED, got FAILED: invalid resource"), "wait"),
    ],
    ids=["refused", "permission-denied", "failed-while-waiting"],
)
def test_a_refused_update_warns_with_the_error_and_continues(capsys, error, raised_by):
    ws = _ws(_live_app())
    if raised_by == "request":
        ws.apps.create_update.side_effect = error
    else:
        ws.apps.create_update.return_value.result.side_effect = error

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.create_update.assert_called_once()  # it was attempted
    lines = _warning_lines(capsys.readouterr().out)
    assert any(str(error) in line for line in lines), lines


@pytest.mark.parametrize(
    "status",
    [
        AppUpdateUpdateStatus(state=AppUpdateUpdateStatusUpdateState.FAILED, message="bad"),
        AppUpdateUpdateStatus(state=AppUpdateUpdateStatusUpdateState.IN_PROGRESS, message="wait"),
        AppUpdateUpdateStatus(state=AppUpdateUpdateStatusUpdateState.NOT_UPDATED, message="no"),
        None,
    ],
    ids=["failed", "in-progress", "not-updated", "no-status"],
)
def test_an_update_that_did_not_succeed_warns_and_returns_false(capsys, status):
    """Only SUCCEEDED counts: any other state the update ends in is a failure."""
    ws = _ws(_live_app())
    ws.apps.create_update.return_value.result.return_value = AppUpdate(status=status)

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.create_update.assert_called_once()
    lines = _warning_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    if status is not None:
        assert status.state.value in lines[0], lines


def test_a_failed_lookup_warns_with_the_error_and_continues(capsys):
    ws = MagicMock()
    ws.apps.get.side_effect = RuntimeError("no such app")

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.create_update.assert_not_called()
    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert any("no such app" in line for line in lines), lines


def test_an_sdk_without_the_postgres_resource_warns_and_continues(monkeypatch, capsys):
    """An SDK older than 0.95.0 has no ``AppResourcePostgres`` (the installer's
    floor is 0.96.0, so this is an older SDK left in the environment). Model
    that SDK: the names are gone from the SDK
    module and from deploy's namespace, so the helper must neither raise nor
    call anything, and must say, on one line, which SDK it needs."""
    for name in ("AppResourcePostgres", "AppResourcePostgresPostgresPermission"):
        monkeypatch.delattr(sdk_apps, name)
        monkeypatch.delattr(deploy, name, raising=False)
    monkeypatch.setattr(deploy, "HAS_POSTGRES_RESOURCE", False, raising=False)
    ws = _ws(_live_app())

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.get.assert_not_called()
    ws.apps.create_update.assert_not_called()
    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert "databricks-sdk" in lines[0] and "0.96.0" in lines[0], lines


def test_an_sdk_without_the_role_api_warns_and_does_not_attach(monkeypatch, capsys):
    """Without the role SDK, ``_ensure_sp_autoscaling_role`` creates no role, and
    attaching then would make the platform create its own role for the service
    principal. So the helper touches nothing and says why, on one line."""
    monkeypatch.setattr(deploy, "HAS_ROLE_SDK", False)
    ws = _ws(_live_app())

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.get.assert_not_called()
    ws.apps.create_update.assert_not_called()
    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines


# --- resources is replaced whole: never send back what this SDK cannot model ----


@pytest.mark.parametrize(
    "unmodelled",
    [
        # Exactly what apps.get yields for a resource kind the SDK does not know.
        AppResource.from_dict({"name": "mystery_kind", "some_future_kind": {"id": "x"}}),
        AppResource(name="mystery_kind", description="only a name and a description"),
    ],
    ids=["unknown-kind-round-trip", "name-and-description-only"],
)
def test_an_app_with_a_resource_this_sdk_cannot_model_is_left_alone(capsys, unmodelled):
    secret = secret_key.build_secret_resource("tellr", "tellr-encryption-key")
    ws = _ws(_live_app(resources=[secret, unmodelled]))

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.create_update.assert_not_called()
    ws.apps.update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert "mystery_kind" in lines[0], lines


# --- the service principal's role must already be on the branch -------------------


def test_an_app_without_a_service_principal_client_id_is_not_attached(capsys):
    ws = _ws(_live_app(service_principal_client_id=None))

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.postgres.list_roles.assert_not_called()
    ws.apps.create_update.assert_not_called()
    assert len(_warning_lines(capsys.readouterr().out)) == 1


@pytest.mark.parametrize(
    "roles",
    [
        {BRANCH: []},
        {BRANCH: [_sp_role("another-service-principal")]},
        {BRANCH: [Role(name=f"{BRANCH}/roles/unknown", status=None)]},
        # The role is there, but on another branch.
        {BRANCH: [], f"projects/{PROJECT}/branches/dev-x": [_sp_role("cid")]},
    ],
    ids=["no-roles", "another-principal", "role-without-status", "role-on-another-branch"],
)
def test_a_branch_without_the_service_principals_role_is_not_attached(capsys, roles):
    """Given the resource with no role for the service principal, the platform
    creates its own ``dbrx-apps-<client id>`` role with no membership."""
    ws = _ws(_live_app(), roles=roles)

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.postgres.list_roles.assert_called_once_with(parent=BRANCH)
    ws.apps.create_update.assert_not_called()
    ws.apps.update.assert_not_called()
    assert len(_warning_lines(capsys.readouterr().out)) == 1


def test_a_failed_role_lookup_is_not_attached(capsys):
    """Fail closed: a role that cannot be seen is treated as missing."""
    ws = _ws(_live_app())
    ws.postgres.list_roles.side_effect = PermissionDenied("cannot list roles on tellr-db")

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is False

    ws.apps.create_update.assert_not_called()
    lines = _warning_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert "cannot list roles on tellr-db" in lines[0], lines


def test_a_role_made_by_hand_counts_by_its_postgres_name():
    """The match is on the Postgres name the service principal logs in as, not
    on the installer's ``sp-<client id>`` role id."""
    ws = _ws(_live_app(), roles={BRANCH: [_sp_role("cid", role_id="made-by-hand")]})

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is True

    _, update_mask, sent = _sent_update(ws)
    assert update_mask == "resources"
    assert sent.resources[-1].as_dict() == EXPECTED_RESOURCE


def test_a_role_without_a_status_listed_first_does_not_hide_the_service_principals_role():
    """``Role.status`` is optional.  A role without one, listed before the service
    principal's role, is skipped: it must not end the lookup in an error, which reads
    as "could not list the roles" and attaches nothing."""
    ws = _ws(
        _live_app(),
        roles={BRANCH: [Role(name=f"{BRANCH}/roles/unknown", status=None), _sp_role("cid")]},
    )

    assert deploy._ensure_app_postgres_resource(ws, APP_NAME, PROJECT) is True

    _, update_mask, sent = _sent_update(ws)
    assert update_mask == "resources"
    assert sent.resources[-1].as_dict() == EXPECTED_RESOURCE


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


@pytest.mark.parametrize(
    "lakebase_result, expected_branch",
    [
        (AUTOSCALING_RESULT, "production"),
        # A result that names its branch: the role and the resource both use it.
        ({**AUTOSCALING_RESULT, "branch_id": "dev-x"}, "dev-x"),
    ],
    ids=["production", "result-names-its-branch"],
)
def test_create_attaches_after_the_role_and_before_the_schema_and_deploy(
    monkeypatch, lakebase_result, expected_branch
):
    events: list[str] = []
    roles: list[dict] = []
    attaches: list[dict] = []
    _stub_create_steps(monkeypatch, lakebase_result, events, roles)
    _record_attach(monkeypatch, events, attaches)
    ws = MagicMock()

    result = _run_create(ws)

    assert events == ["create_app", "role", "attach", "schema", "deploy"]
    assert attaches == [
        {"ws": ws, "app_name": APP_NAME, "project_name": PROJECT, "branch_name": expected_branch}
    ]
    # The branch named is the one the role was just created on.
    assert [role["branch_name"] for role in roles] == [expected_branch]
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
    ws.apps.create_update.side_effect = RuntimeError("postgres app resources are not enabled")

    result = _run_create(ws)

    _, update_mask, sent = _sent_update(ws)  # the attach WAS attempted, once
    assert update_mask == "resources"
    assert sent.resources[-1].as_dict() == EXPECTED_RESOURCE
    ws.apps.update.assert_not_called()
    assert events == ["create_app", "role", "schema", "deploy"]
    assert result["status"] == "created"
    lines = _warning_lines(capsys.readouterr().out)
    assert any("postgres app resources are not enabled" in line for line in lines), lines


# --- update: attach after every pre-deploy step that can abort, before the deploy -
# These live here, not in test_deploy_app_scopes.py, because this module imports
# databricks_tellr in the CI shape (see the deploy_local import at the top).


def _stub_update_steps(monkeypatch, ws, lakebase_result, order):
    """Stub the ``_update_databricks`` steps that touch files or Lakebase.

    Records, in ``order``, the steps that can abort the update (the
    breaking-migration check, the upload) and the deploy.
    ``secret_key.app_is_secret_mode`` stays real: it reads ``ws``.
    """

    @contextmanager
    def _staging():
        yield "/tmp/staging"

    monkeypatch.setattr(deploy, "_get_workspace_client", lambda c, p: ws)
    monkeypatch.setattr(deploy, "_read_existing_encryption_key", lambda w, p: None)
    monkeypatch.setattr(deploy, "_get_or_create_lakebase", lambda *a, **k: dict(lakebase_result))
    monkeypatch.setattr(
        deploy, "_check_breaking_migrations", lambda *a, **k: order.append("breaking_check")
    )
    monkeypatch.setattr(deploy, "_staging_dir", _staging)
    monkeypatch.setattr(deploy, "_write_requirements", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_write_app_yaml", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_upload_files", lambda *a, **k: order.append("upload"))
    ws.apps.deploy_and_wait.side_effect = lambda *a, **k: (
        order.append("deploy") or MagicMock(deployment_id="d1")
    )


def _run_update(**kwargs):
    return deploy._update_databricks(
        app_name=APP_NAME,
        app_file_workspace_path="/ws",
        lakebase_name=PROJECT,
        schema_name="app_data",
        **kwargs,
    )


@pytest.mark.parametrize(
    "lakebase_result, expected_attaches, expected_order",
    [
        (
            AUTOSCALING_RESULT,
            [{"app_name": APP_NAME, "project_name": PROJECT, "branch_name": "production"}],
            ["breaking_check", "upload", "attach", "deploy"],
        ),
        (PROVISIONED_RESULT, [], ["breaking_check", "upload", "deploy"]),
    ],
    ids=["autoscaling", "provisioned"],
)
def test_update_attaches_after_the_abortable_steps_and_before_the_deploy(
    monkeypatch, lakebase_result, expected_attaches, expected_order
):
    """A declined breaking migration or a failed upload must leave the app
    untouched, so the attach comes after them; and before the deploy, so the
    new version starts with the resource."""
    order: list[str] = []
    attaches: list[dict] = []
    ws = _ws(_live_app())
    _stub_update_steps(monkeypatch, ws, lakebase_result, order)

    def _attach(ws_arg, app_name, project_name, branch_name="production"):
        assert ws_arg is ws
        order.append("attach")
        attaches.append(
            {"app_name": app_name, "project_name": project_name, "branch_name": branch_name}
        )
        return True

    monkeypatch.setattr(deploy, "_ensure_app_postgres_resource", _attach)

    result = _run_update()

    assert attaches == expected_attaches
    assert order == expected_order
    assert result["status"] == "updated"


def test_a_failed_lakebase_attach_warns_and_the_update_still_deploys(monkeypatch, capsys):
    """The real attach, refused by the workspace: tellr.update() still ships the
    new version (same contract as the scopes and the CAN_MANAGE grant)."""
    order: list[str] = []
    ws = _ws(_live_app())  # every scope present: the scope writer sends nothing
    ws.apps.create_update.side_effect = RuntimeError("postgres app resources are not enabled")
    _stub_update_steps(monkeypatch, ws, AUTOSCALING_RESULT, order)

    result = _run_update()

    _, update_mask, sent = _sent_update(ws)  # the attach WAS attempted, once
    assert update_mask == "resources"
    assert [r.postgres.branch for r in sent.resources if r.postgres is not None] == [BRANCH]
    ws.apps.update.assert_not_called()
    assert order == ["breaking_check", "upload", "deploy"]
    assert result["status"] == "updated"
    out = capsys.readouterr().out
    assert any(
        "WARNING" in line and "postgres app resources are not enabled" in line
        for line in out.splitlines()
    ), out


@pytest.mark.parametrize("mode", ["moving-to-the-secret", "already-secret"])
def test_update_in_secret_mode_attaches_and_keeps_the_secret(monkeypatch, mode):
    """Secret mode still attaches, and the secret resource survives it.

    ``moving-to-the-secret`` runs the real ``secret_key.attach_secret_resource``
    (a full-replace update) first; the attach then re-reads the app and sends
    the secret back with ``app_database``. ``already-secret`` is a later update
    of an app that already carries the secret.
    """
    secret = secret_key.build_secret_resource("tellr", secret_key.DEFAULT_SECRET_KEY)
    order: list[str] = []
    ws = _ws(_live_app(resources=[secret] if mode == "already-secret" else None))
    _stub_update_steps(monkeypatch, ws, AUTOSCALING_RESULT, order)
    monkeypatch.setattr(
        secret_key, "preflight_scope", lambda w, scope: order.append("secret_preflight")
    )
    monkeypatch.setattr(deploy, "_get_lakebase_connection", lambda *a, **k: (MagicMock(), "me"))
    monkeypatch.setattr(secret_key, "preflight_lakebase_privileges", lambda cur, schema: None)
    monkeypatch.setattr(secret_key, "read_lakebase_key", lambda cur, schema: "lakebase-key")
    monkeypatch.setattr(
        secret_key, "resolve_key_for_update", lambda *a, **k: ("lakebase-key", False)
    )
    monkeypatch.setattr(secret_key, "app_reports_secret_source", lambda w, url: False)
    real_attach = deploy._ensure_app_postgres_resource

    def _attach(*a, **k):
        order.append("attach")
        return real_attach(*a, **k)

    monkeypatch.setattr(deploy, "_ensure_app_postgres_resource", _attach)

    result = _run_update(
        encryption_secret_scope="tellr" if mode == "moving-to-the-secret" else None
    )

    _, update_mask, sent = _sent_update(ws)
    assert update_mask == "resources"
    assert [r.as_dict() for r in sent.resources] == [secret.as_dict(), EXPECTED_RESOURCE]
    if mode == "moving-to-the-secret":
        ws.apps.update.assert_called_once()  # attach_secret_resource, before the attach
        assert order == ["breaking_check", "secret_preflight", "upload", "attach", "deploy"]
    else:
        ws.apps.update.assert_not_called()
        assert order == ["breaking_check", "upload", "attach", "deploy"]
    assert result["status"] == "updated"

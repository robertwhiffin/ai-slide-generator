"""Every deploy path grants the app's own service principal CAN_MANAGE on its app.

Why: the CAN_MANAGE sync reads the app's permission list AS the app SP, and the
spike (tellr-dev, 2026-11-02) proved that read only works once the SP holds
CAN_MANAGE on its own app: no grant -> ``PermissionDenied apps.ruleSets/get``,
CAN_USE -> still denied, CAN_MANAGE -> works after ~30-60 s. So the package
``create``/``update`` and ``scripts/deploy_local.py`` ``create_local``/
``update_local`` all make the grant:

* additively, via ``apps.update_permissions`` (the PATCH). ``set_permissions``
  replaces the whole list and would strip every other holder, so it must never
  be called;
* on update, BEFORE ``deploy_and_wait``, so the grant has propagated by the time
  the new version's first sync runs;
* and a failed grant never aborts the deploy: it warns with the exact manual fix
  and the new version still ships (same contract as the user API scopes).

Run with ``PYTHONPATH=packages/databricks-tellr`` or this module SKIPS.
"""

import inspect
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.apps import (
    App,
    AppAccessControlRequest,
    AppPermissionLevel,
    AppsAPI,
)
from databricks_tellr import deploy

from scripts import deploy_local
from tests.unit.test_deploy_app_scopes import _stub_update_steps
from tests.unit.test_deploy_local_schema_setup_sp_only import (
    _BRANCH_CFG,
    _NONBRANCH_CFG,
    _patch_common,
)

SUCCESS_LINE = "   App service principal granted CAN_MANAGE on the app (admin sync)"

# The manual fix, verbatim, for app "app" and SP client id "cid".
CLI_FIX = (
    "databricks apps update-permissions app --json "
    """'{"access_control_list":[{"service_principal_name":"cid","permission_level":"CAN_MANAGE"}]}'"""
)

# The manual fix when the SP client id is unknown (no CLI command is possible).
UNKNOWN_ID_FIX = (
    "add the app's service principal with Can Manage in the app's Permissions tab"
)


def _bound(method_mock, real_method):
    """Bind the single call on ``method_mock`` to the REAL SDK signature.

    Positional-vs-keyword style then does not matter, but a wrong parameter name
    (or a call the real API would reject) fails here.
    """
    method_mock.assert_called_once()
    call = method_mock.call_args
    return inspect.signature(real_method).bind(None, *call.args, **call.kwargs).arguments


def _grant_args(ws):
    """``(app_name, access_control_list)`` of the one ``update_permissions`` call."""
    args = _bound(ws.apps.update_permissions, AppsAPI.update_permissions)
    return args["app_name"], args.get("access_control_list")


def _assert_only_the_sp_gets_can_manage(acl, client_id):
    """The PATCH carries exactly one entry: the app SP, at CAN_MANAGE.

    Real SDK types matter: ``update_permissions`` serialises each entry with
    ``.as_dict()`` and ``AppPermissionLevel`` is a plain Enum, so a dict entry or
    the bare string ``"CAN_MANAGE"`` would break against the real API.
    """
    assert acl is not None and len(acl) == 1, f"expected one ACL entry, got {acl!r}"
    entry = acl[0]
    assert isinstance(entry, AppAccessControlRequest), type(entry)
    assert entry.service_principal_name == client_id
    assert entry.permission_level == AppPermissionLevel.CAN_MANAGE
    assert entry.user_name is None and entry.group_name is None


# --- the helper itself ---------------------------------------------------------


def test_grants_can_manage_additively(capsys):
    ws = MagicMock()

    assert deploy._ensure_app_sp_can_manage(ws, "app", "cid") is True

    app_name, acl = _grant_args(ws)
    assert app_name == "app"
    _assert_only_the_sp_gets_can_manage(acl, "cid")
    # set_permissions REPLACES the whole permission list — never call it.
    ws.apps.set_permissions.assert_not_called()
    # The client id was given, so there is nothing to look up.
    ws.apps.get.assert_not_called()

    out = capsys.readouterr().out
    assert SUCCESS_LINE in out
    assert "WARNING" not in out


def test_looks_up_client_id_when_not_given():
    ws = MagicMock()
    ws.apps.get.return_value = App(name="app", service_principal_client_id="cid")

    assert deploy._ensure_app_sp_can_manage(ws, "app") is True

    assert _bound(ws.apps.get, AppsAPI.get)["name"] == "app"
    app_name, acl = _grant_args(ws)
    assert app_name == "app"
    _assert_only_the_sp_gets_can_manage(acl, "cid")
    ws.apps.set_permissions.assert_not_called()


@pytest.mark.parametrize(
    "exc",
    [
        PermissionDenied("User does not have permission apps.ruleSets/update"),
        RuntimeError("connection reset by peer"),
    ],
    ids=["PermissionDenied", "any-other-exception"],
)
def test_failure_warns_with_manual_fix_and_returns_false(capsys, exc):
    ws = MagicMock()
    ws.apps.update_permissions.side_effect = exc

    # Never raises: a failed grant must not abort the deploy that called it.
    assert deploy._ensure_app_sp_can_manage(ws, "app", "cid") is False

    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert CLI_FIX in out
    ws.apps.set_permissions.assert_not_called()


def test_missing_client_id_warns_and_makes_no_call(capsys):
    ws = MagicMock()
    # An app whose service principal is not known (no client id, no SP id).
    ws.apps.get.return_value = App(name="app")

    assert deploy._ensure_app_sp_can_manage(ws, "app") is False

    ws.apps.update_permissions.assert_not_called()
    ws.apps.set_permissions.assert_not_called()
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert UNKNOWN_ID_FIX in out
    # "Instead": with no id there is no runnable CLI command to print.
    assert "databricks apps update-permissions" not in out


def test_client_id_lookup_failure_warns_and_returns_false(capsys):
    """The lookup sits inside the guarded block: a failing ``apps.get`` must not
    escape either (the helper never raises), and with no id the fix is the
    Permissions-tab instruction."""
    ws = MagicMock()
    ws.apps.get.side_effect = PermissionDenied("User does not have permission apps/get")

    assert deploy._ensure_app_sp_can_manage(ws, "app") is False

    ws.apps.update_permissions.assert_not_called()
    ws.apps.set_permissions.assert_not_called()
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert UNKNOWN_ID_FIX in out


# --- package update: deploy._update_databricks ---------------------------------


def _update_ws(events):
    """A workspace whose app has an SP and every scope; grant + deploy recorded."""
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name="app",
        url="https://app.example",
        service_principal_client_id="cid",
        user_api_scopes=list(deploy.REQUIRED_USER_API_SCOPES),
    )
    ws.apps.update_permissions.side_effect = lambda *a, **kw: events.append("grant")
    ws.apps.deploy_and_wait.side_effect = lambda *a, **kw: (
        events.append("deploy") or MagicMock(deployment_id="d1")
    )
    return ws


def _run_update():
    return deploy._update_databricks(
        app_name="app",
        app_file_workspace_path="/ws",
        lakebase_name="lb",
        schema_name="s",
    )


def test_update_grants_before_deploying(monkeypatch):
    events: list[str] = []
    ws = _update_ws(events)
    _stub_update_steps(monkeypatch, ws)

    _run_update()

    # Grant first, so it has propagated by the new version's first sync.
    assert events == ["grant", "deploy"]
    app_name, acl = _grant_args(ws)
    assert app_name == "app"
    _assert_only_the_sp_gets_can_manage(acl, "cid")
    ws.apps.set_permissions.assert_not_called()


def test_update_still_deploys_when_grant_fails(monkeypatch, capsys):
    events: list[str] = []
    ws = _update_ws(events)
    ws.apps.update_permissions.side_effect = PermissionDenied(
        "User does not have permission apps.ruleSets/update"
    )
    _stub_update_steps(monkeypatch, ws)

    result = _run_update()

    ws.apps.update_permissions.assert_called_once()  # the grant WAS attempted
    ws.apps.deploy_and_wait.assert_called_once()  # ...and the update still shipped
    assert result["status"] == "updated"
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert CLI_FIX in out


# --- package create: deploy._create_databricks ---------------------------------


def _stub_create_steps(monkeypatch, ws, events):
    """Stub every _create_databricks step; record create / schema / deploy."""

    @contextmanager
    def _staging():
        yield "/tmp/staging"

    def _create_app(*a, **k):
        events.append("create_app")
        return App(name="app", service_principal_client_id="cid")

    def _setup_schema(*a, **k):
        events.append("schema")

    def _deploy_app(*a, **k):
        events.append("deploy")
        return App(name="app", url="https://app.example")

    monkeypatch.setattr(deploy, "_get_workspace_client", lambda c, p: ws)
    # name/status are printed by _create_databricks, so they must be present.
    monkeypatch.setattr(
        deploy,
        "_get_or_create_lakebase",
        lambda *a, **k: {"type": "provisioned", "name": "lb", "status": "AVAILABLE"},
    )
    monkeypatch.setattr(deploy, "_staging_dir", _staging)
    monkeypatch.setattr(deploy, "_write_requirements", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_write_app_yaml", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_upload_files", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_create_app", _create_app)
    monkeypatch.setattr(deploy, "_ensure_sp_autoscaling_role", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_setup_database_schema", _setup_schema)
    monkeypatch.setattr(deploy, "_deploy_app", _deploy_app)


def _run_create():
    return deploy._create_databricks(
        lakebase_name="lb",
        schema_name="s",
        app_name="app",
        app_file_workspace_path="/ws",
    )


def test_create_grants_after_app_registration(monkeypatch):
    events: list[str] = []
    ws = MagicMock()
    ws.apps.update_permissions.side_effect = lambda *a, **kw: events.append("grant")
    _stub_create_steps(monkeypatch, ws, events)

    _run_create()

    assert events.count("grant") == 1, events
    # After the app exists (its SP id is known), before the app is deployed.
    assert events.index("create_app") < events.index("grant") < events.index("deploy"), events
    app_name, acl = _grant_args(ws)
    assert app_name == "app"
    _assert_only_the_sp_gets_can_manage(acl, "cid")
    ws.apps.set_permissions.assert_not_called()
    # The id comes from the app _create_app just returned, not a second GET.
    ws.apps.get.assert_not_called()


def test_create_still_deploys_when_grant_fails(monkeypatch, capsys):
    events: list[str] = []
    ws = MagicMock()
    ws.apps.update_permissions.side_effect = PermissionDenied(
        "User does not have permission apps.ruleSets/update"
    )
    _stub_create_steps(monkeypatch, ws, events)

    result = _run_create()

    ws.apps.update_permissions.assert_called_once()
    assert events.count("deploy") == 1, events
    assert result["status"] == "created"
    out = capsys.readouterr().out
    assert "WARNING:" in out
    assert CLI_FIX in out


# --- scripts/deploy_local.py: create_local / update_local ----------------------


def _record_grants(monkeypatch, events):
    """Replace deploy_local's imported helper with a recorder (same signature)."""
    calls: list[dict] = []

    def _recorder(ws, app_name, client_id=None):
        calls.append({"ws": ws, "app_name": app_name, "client_id": client_id})
        events.append("grant")
        return True

    monkeypatch.setattr(deploy_local, "_ensure_app_sp_can_manage", _recorder)
    return calls


def _drive_create_local(monkeypatch, cfg, events, **kwargs):
    """create_local on ``cfg`` with create/deploy recorded; returns the ws."""
    _patch_common(monkeypatch, cfg)
    ws = MagicMock(name="create-ws")
    monkeypatch.setattr(deploy_local, "_get_workspace_client", lambda profile=None: ws)
    created_app = MagicMock(name="created-app")

    def _create_app(*a, **k):
        events.append("create_app")
        return created_app

    def _deploy_app(*a, **k):
        events.append("deploy")
        return MagicMock(url="https://app")

    monkeypatch.setattr(deploy_local, "_create_app", _create_app)
    monkeypatch.setattr(deploy_local, "_deploy_app", _deploy_app)
    # Only the app _create_app just returned has an SP id.
    monkeypatch.setattr(
        deploy_local,
        "_get_app_client_id",
        lambda app: "sp-client-id" if app is created_app else None,
    )
    deploy_local.create_local(profile="p", from_pypi="0.3.11.dev4", **kwargs)
    return ws


def _drive_update_local(monkeypatch, cfg, events, **kwargs):
    """update_local on ``cfg`` with deploy_and_wait recorded; returns the ws."""
    _patch_common(monkeypatch, cfg)
    ws = MagicMock(name="update-ws")
    ws.apps.deploy_and_wait.side_effect = lambda *a, **kw: (
        events.append("deploy") or MagicMock(deployment_id="d1")
    )
    monkeypatch.setattr(deploy_local, "_get_workspace_client", lambda profile=None: ws)
    deploy_local.update_local(profile="p", from_pypi="0.3.11.dev4", **kwargs)
    return ws


def test_deploy_local_create_and_update_grant(monkeypatch):
    """Plain (non-branch) env: ``create_local`` grants with the new app's SP id;
    ``update_local`` grants before deploying, with NO client id — on this path
    neither ``app`` nor ``client_id`` is bound, so the helper looks it up."""
    events: list[str] = []
    calls = _record_grants(monkeypatch, events)
    app_name = _NONBRANCH_CFG["app_name"]

    # --- create_local -------------------------------------------------------
    ws = _drive_create_local(monkeypatch, _NONBRANCH_CFG, events, env="production")

    assert [c["app_name"] for c in calls] == [app_name]
    assert calls[0]["ws"] is ws
    assert calls[0]["client_id"] == "sp-client-id"
    assert events.index("create_app") < events.index("grant") < events.index("deploy"), events

    # --- update_local (plain non-branch path) --------------------------------
    events.clear()
    calls.clear()
    ws = _drive_update_local(monkeypatch, _NONBRANCH_CFG, events, env="production")

    assert [c["app_name"] for c in calls] == [app_name]
    assert calls[0]["ws"] is ws
    assert calls[0]["client_id"] is None, "update_local must let the helper look the id up"
    assert events == ["grant", "deploy"]


def test_deploy_local_fork_create_and_update_grant(monkeypatch):
    """The devloop (branch_from, ``--instance``) paths grant too, on the
    instance-suffixed app — this is the path every dev deploy takes."""
    events: list[str] = []
    calls = _record_grants(monkeypatch, events)
    app_name = f"{_BRANCH_CFG['app_name']}-spfix"

    # --- create_local (fork) ------------------------------------------------
    ws = _drive_create_local(
        monkeypatch, _BRANCH_CFG, events, env="devloop", instance="spfix"
    )

    assert [c["app_name"] for c in calls] == [app_name]
    assert calls[0]["ws"] is ws
    assert calls[0]["client_id"] == "sp-client-id"
    assert events.index("create_app") < events.index("grant") < events.index("deploy"), events

    # --- update_local (fork) ------------------------------------------------
    events.clear()
    calls.clear()
    ws = _drive_update_local(
        monkeypatch, _BRANCH_CFG, events, env="devloop", instance="spfix"
    )

    assert [c["app_name"] for c in calls] == [app_name]
    assert calls[0]["ws"] is ws
    assert events == ["grant", "deploy"]

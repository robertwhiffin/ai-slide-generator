"""Unit tests for the CAN_MANAGE sync: the app's permission list -> ``permissions`` rows.

Task 2 of docs/superpowers/plans/2026-11-02-admin-permissions.md (brief + addendum in
.superpowers/sdd/2026-11-02-admin-permissions/).

``holders_from_acl`` is tested on real SDK objects from ``databricks.sdk.service.apps``.
``sync_once`` runs against an in-memory SQLite database: the module's own
``get_db_session`` name is patched with a context manager that commits on a clean exit
and rolls back on an exception, like the real one, and every assertion on stored state
reads the rows back in a fresh session. Only the Databricks client is faked. The loop
tests patch the module's own ``asyncio`` name, so no real time passes.
"""

import ast
import asyncio
import io
import logging
import tokenize
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.apps import (
    AppAccessControlResponse,
    AppPermission,
    AppPermissionLevel,
    AppPermissions,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.services.can_manage_sync as can_manage_sync
from src.core.database import Base
from src.database.models.permission import Permission
from src.services.admin_permissions import AclHolder, get_sync_status, record_sync_result
from src.services.can_manage_sync import holders_from_acl, sync_once

CAN_MANAGE = AppPermissionLevel.CAN_MANAGE
CAN_USE = AppPermissionLevel.CAN_USE

EMPTY_READ_MESSAGE = "the app's permissions list no direct CAN_MANAGE users or groups"

T0 = datetime(2026, 11, 2, 8, 0, 0)
T = datetime(2026, 11, 2, 9, 0, 0)

# Verbatim from ~/tellr-loop/admin-acl-spike/probe-4-can-manage-delayed.json,
# key "apps.get_permissions" -> "result": what the app's SP read once it held
# CAN_MANAGE on its own app. The workspace `admins` group appears only as the entry
# every app inherits from /apps; the SP and the deploying user hold direct CAN_MANAGE.
SPIKE_GET_PERMISSIONS_RESULT = {
    "access_control_list": [
        {
            "all_permissions": [
                {
                    "inherited": True,
                    "inherited_from_object": ["/apps"],
                    "permission_level": "CAN_MANAGE",
                }
            ],
            "group_name": "admins",
        },
        {
            "all_permissions": [{"inherited": False, "permission_level": "CAN_MANAGE"}],
            "display_name": "app-1lhyho acl-spike",
            "service_principal_name": "434da09e-20ca-4f44-af60-32c51579bd5a",
        },
        {
            "all_permissions": [{"inherited": False, "permission_level": "CAN_MANAGE"}],
            "display_name": "Robert Whiffin",
            "user_name": "robert.whiffin@databricks.com",
        },
    ],
    "object_id": "/apps/434da09e-20ca-4f44-af60-32c51579bd5a",
    "object_type": "apps",
}


# ---------------------------------------------------------------------------
# SDK object builders
# ---------------------------------------------------------------------------


def _direct(level=CAN_MANAGE) -> AppPermission:
    return AppPermission(inherited=False, permission_level=level)


def _inherited(level=CAN_MANAGE) -> AppPermission:
    return AppPermission(
        inherited=True, inherited_from_object=["/apps"], permission_level=level
    )


def _user(name, *perms) -> AppAccessControlResponse:
    return AppAccessControlResponse(user_name=name, all_permissions=list(perms))


def _group(name, *perms) -> AppAccessControlResponse:
    return AppAccessControlResponse(group_name=name, all_permissions=list(perms))


def _sp(client_id, *perms, display_name="app-sp tellr") -> AppAccessControlResponse:
    return AppAccessControlResponse(
        service_principal_name=client_id,
        display_name=display_name,
        all_permissions=list(perms),
    )


def _acl(*entries) -> AppPermissions:
    return AppPermissions(
        access_control_list=list(entries),
        object_id="/apps/434da09e-20ca-4f44-af60-32c51579bd5a",
        object_type="apps",
    )


@pytest.fixture
def spike_acl() -> AppPermissions:
    return AppPermissions.from_dict(SPIKE_GET_PERMISSIONS_RESULT)


# ---------------------------------------------------------------------------
# Database: an in-memory SQLite engine shared by every session (StaticPool), and
# the module's get_db_session replaced by a commit-on-exit context manager.
# ---------------------------------------------------------------------------


@pytest.fixture
def session_factory(monkeypatch):
    import src.database.models  # noqa: F401 - register every model on Base.metadata

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # autoflush=False matches production (src/core/database.py get_session_local).
    factory = sessionmaker(bind=engine, autoflush=False)

    @contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(
        "src.services.can_manage_sync.get_db_session", fake_get_db_session
    )
    yield factory
    engine.dispose()


@pytest.fixture
def app_name(monkeypatch):
    monkeypatch.setenv("DATABRICKS_APP_NAME", "tellr")
    return "tellr"


def _client_returning(acl=None, *, raises=None) -> MagicMock:
    client = MagicMock()
    if raises is not None:
        client.apps.get_permissions.side_effect = raises
    else:
        client.apps.get_permissions.return_value = acl
    return client


def _patch_system_client(monkeypatch, client) -> MagicMock:
    get_client = MagicMock(return_value=client)
    monkeypatch.setattr("src.services.can_manage_sync.get_system_client", get_client)
    return get_client


def _seed(factory, identity_type, identity_name, source):
    """Insert one app-admin row directly (independent of the code under test)."""
    with factory() as db:
        db.add(
            Permission(
                resource_type="app",
                resource_id="",
                identity_type=identity_type,
                identity_name=identity_name,
                identity_key=identity_name.strip().lower(),
                privilege="admin",
                source=source,
                created_by="can_manage_sync" if source == "can_manage_sync" else "priya",
            )
        )
        db.commit()


def _seed_success(factory, when):
    """Record a past successful sync through Task 1's store (not the code under test)."""
    with factory() as db:
        record_sync_result(db, now=when, error=None)
        db.commit()


def _keys(factory, source) -> set[tuple[str, str]]:
    """Fresh-session read of the app-admin (type, key) pairs for one source."""
    with factory() as db:
        rows = (
            db.query(Permission.identity_type, Permission.identity_key)
            .filter(
                Permission.resource_type == "app",
                Permission.resource_id == "",
                Permission.privilege == "admin",
                Permission.source == source,
            )
            .all()
        )
    return {(t, k) for t, k in rows}


def _status(factory):
    with factory() as db:
        return get_sync_status(db)


def _warnings(caplog) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]


# ---------------------------------------------------------------------------
# holders_from_acl
# ---------------------------------------------------------------------------


def test_spike_payload_yields_only_the_direct_user(spike_acl):
    # The inherited `admins` entry (workspace admins) and the app's own SP drop out.
    assert holders_from_acl(spike_acl) == [
        AclHolder("USER", "robert.whiffin@databricks.com")
    ]


def test_direct_group_grant_is_kept_even_if_named_admins():
    acl = _acl(_group("admins", _direct()))

    assert holders_from_acl(acl) == [AclHolder("GROUP", "admins")]


def test_entry_with_inherited_and_direct_can_manage_is_kept():
    acl = _acl(
        _user("both@x.com", _inherited(), _direct()),
        # Control: the same user shape with only the inherited item is dropped.
        _user("inherited-only@x.com", _inherited()),
    )

    assert holders_from_acl(acl) == [AclHolder("USER", "both@x.com")]


def test_direct_can_use_only_is_dropped():
    acl = _acl(
        _user("viewer@x.com", _direct(CAN_USE)),
        # Control, kept. The constraint says `inherited` falsy, so an omitted flag
        # (None) counts as a direct grant.
        _user("manager@x.com", AppPermission(permission_level=CAN_MANAGE)),
    )

    assert holders_from_acl(acl) == [AclHolder("USER", "manager@x.com")]


def test_service_principals_are_dropped():
    acl = _acl(
        _sp("434da09e-20ca-4f44-af60-32c51579bd5a", _direct()),
        # "Drop every service_principal_name entry", even one that also carries a
        # user_name: it is still a service principal.
        AppAccessControlResponse(
            service_principal_name="9f1c0000-ci-sp",
            user_name="9f1c0000-ci-sp",
            all_permissions=[_direct()],
        ),
        _user("deployer@x.com", _direct()),
    )

    assert holders_from_acl(acl) == [AclHolder("USER", "deployer@x.com")]


def test_blank_names_are_skipped():
    acl = _acl(
        _user("", _direct()),
        _group("  ", _direct()),
        _user("real@x.com", _direct()),
    )

    assert holders_from_acl(acl) == [AclHolder("USER", "real@x.com")]


def test_case_variants_are_deduped_keeping_the_first_spelling():
    acl = _acl(
        _user("Robert.Whiffin@Databricks.com", _direct()),
        _user("robert.whiffin@databricks.com", _direct()),
        _group("Tellr Maintainers", _direct()),
        _group("TELLR MAINTAINERS", _direct()),
        # Same name, different type: a different identity, kept.
        _group("robert.whiffin@databricks.com", _direct()),
    )

    assert holders_from_acl(acl) == [
        AclHolder("USER", "Robert.Whiffin@Databricks.com"),
        AclHolder("GROUP", "Tellr Maintainers"),
        AclHolder("GROUP", "robert.whiffin@databricks.com"),
    ]


# ---------------------------------------------------------------------------
# sync_once
# ---------------------------------------------------------------------------


def test_sync_once_success_reconciles_and_records_success(
    session_factory, app_name, monkeypatch
):
    _seed(session_factory, "USER", "gone@x.com", "can_manage_sync")
    _seed(session_factory, "USER", "keep@x.com", "manual")
    client = _client_returning(_acl(_user("new@x.com", _direct())))
    _patch_system_client(monkeypatch, client)

    assert sync_once(now=T) is True

    assert _keys(session_factory, "can_manage_sync") == {("USER", "new@x.com")}
    assert _keys(session_factory, "manual") == {("USER", "keep@x.com")}
    status = _status(session_factory)
    assert status.last_success_at == T
    assert status.last_attempt_at == T
    assert status.last_error is None
    client.apps.get_permissions.assert_called_once_with(app_name="tellr")


def test_sync_once_read_failure_changes_nothing(
    session_factory, app_name, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)
    _seed(session_factory, "USER", "kept@x.com", "can_manage_sync")
    client = _client_returning(
        raises=PermissionDenied("does not have apps.ruleSets/get")
    )
    _patch_system_client(monkeypatch, client)

    assert sync_once(now=T) is False

    assert _keys(session_factory, "can_manage_sync") == {("USER", "kept@x.com")}
    status = _status(session_factory)
    assert "ruleSets/get" in status.last_error
    assert status.last_error == "PermissionDenied: does not have apps.ruleSets/get"
    assert status.last_attempt_at == T
    assert status.last_success_at is None
    client.apps.get_permissions.assert_called_once_with(app_name="tellr")

    warnings = _warnings(caplog)
    assert warnings, "a failed read must log a warning"
    # No sync has ever succeeded, so the warning says how to fix it.
    assert any("tellr.update" in w for w in warnings), warnings


def test_sync_once_read_failure_after_a_success_keeps_the_success_time(
    session_factory, app_name, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)
    _seed(session_factory, "USER", "kept@x.com", "can_manage_sync")
    _seed_success(session_factory, T0)
    client = _client_returning(
        raises=PermissionDenied("does not have apps.ruleSets/get")
    )
    _patch_system_client(monkeypatch, client)

    assert sync_once(now=T) is False

    assert _keys(session_factory, "can_manage_sync") == {("USER", "kept@x.com")}
    status = _status(session_factory)
    assert status.last_success_at == T0
    assert status.last_attempt_at == T
    assert "ruleSets/get" in status.last_error

    warnings = _warnings(caplog)
    assert warnings, "a failed read logs a warning every time"
    # A sync has succeeded before, so the "never succeeded / run tellr.update"
    # hint is not given.
    assert not any("tellr.update" in w for w in warnings), warnings


def test_sync_once_untrusted_empty_read_changes_nothing(
    session_factory, app_name, monkeypatch
):
    _seed(session_factory, "USER", "kept@x.com", "can_manage_sync")
    _seed(session_factory, "GROUP", "Tellr Maintainers", "can_manage_sync")
    client = _client_returning(
        _acl(
            _group("admins", _inherited()),
            _sp("434da09e-20ca-4f44-af60-32c51579bd5a", _direct()),
        )
    )
    _patch_system_client(monkeypatch, client)

    assert sync_once(now=T) is False

    assert _keys(session_factory, "can_manage_sync") == {
        ("USER", "kept@x.com"),
        ("GROUP", "tellr maintainers"),
    }
    status = _status(session_factory)
    assert status.last_error == EMPTY_READ_MESSAGE
    assert status.last_attempt_at == T
    assert status.last_success_at is None
    client.apps.get_permissions.assert_called_once_with(app_name="tellr")


def test_sync_once_without_app_name_fails_without_calling_the_api(
    session_factory, monkeypatch
):
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    _seed(session_factory, "USER", "kept@x.com", "can_manage_sync")
    get_client = _patch_system_client(monkeypatch, MagicMock())

    assert sync_once(now=T) is False

    get_client.assert_not_called()
    assert _keys(session_factory, "can_manage_sync") == {("USER", "kept@x.com")}
    status = _status(session_factory)
    assert "DATABRICKS_APP_NAME is not set" in status.last_error
    assert status.last_success_at is None


# ---------------------------------------------------------------------------
# can_manage_sync_loop
# ---------------------------------------------------------------------------


class _LoopRanAway(BaseException):
    """Stops a loop that swallowed the scripted cancellation, so a broken loop
    fails the test instead of hanging it (there is no pytest-timeout here)."""


def _run_loop(monkeypatch, outcomes, *, cancel_on_sleep, cancel_in_to_thread=False):
    """Run can_manage_sync_loop with scripted sync_once outcomes.

    ``outcomes`` are returned (or raised, if an exception) by successive sync_once
    calls. The ``cancel_on_sleep``-th sleep raises CancelledError. With
    ``cancel_in_to_thread``, the first ``asyncio.to_thread`` call raises
    CancelledError instead (the task cancelled while a sync is in flight). Returns
    the ordered event log: ("sync", ran_via_to_thread), ("sleep", seconds) and
    ("cancelled_in_to_thread", None).
    """
    events = []
    remaining = list(outcomes)
    in_to_thread = {"active": False}

    def fake_sync_once(*args, **kwargs):
        events.append(("sync", in_to_thread["active"]))
        if not remaining:
            raise _LoopRanAway("sync_once called after the scripted outcomes")
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def fake_sleep(seconds, *args, **kwargs):
        events.append(("sleep", seconds))
        sleeps = sum(1 for e in events if e[0] == "sleep")
        if sleeps == cancel_on_sleep:
            raise asyncio.CancelledError()
        if sleeps > cancel_on_sleep:
            raise _LoopRanAway("the loop kept going after CancelledError")

    async def inline_to_thread(func, /, *args, **kwargs):
        if cancel_in_to_thread and not any(e[0] == "cancelled_in_to_thread" for e in events):
            events.append(("cancelled_in_to_thread", None))
            raise asyncio.CancelledError()
        in_to_thread["active"] = True
        try:
            return func(*args, **kwargs)
        finally:
            in_to_thread["active"] = False

    monkeypatch.setattr(can_manage_sync, "sync_once", fake_sync_once)
    monkeypatch.setattr(
        can_manage_sync,
        "asyncio",
        SimpleNamespace(
            sleep=fake_sleep,
            to_thread=inline_to_thread,
            CancelledError=asyncio.CancelledError,
        ),
    )

    async def drive():
        with pytest.raises(asyncio.CancelledError):
            await can_manage_sync.can_manage_sync_loop()

    asyncio.run(drive())
    return events


def _sleeps(events):
    return [e[1] for e in events if e[0] == "sleep"]


def test_loop_retries_fast_until_first_success_then_slows(monkeypatch):
    assert can_manage_sync.RETRY_INTERVAL_SECONDS == 30
    assert can_manage_sync.SYNC_INTERVAL_SECONDS == 300

    events = _run_loop(monkeypatch, [False, False, True, True], cancel_on_sleep=4)

    assert _sleeps(events) == [30, 30, 300, 300]
    # The first sync runs immediately, before any sleep, then one sync per sleep.
    # Every sync runs through asyncio.to_thread, off the event loop.
    assert events == [
        ("sync", True),
        ("sleep", 30),
        ("sync", True),
        ("sleep", 30),
        ("sync", True),
        ("sleep", 300),
        ("sync", True),
        ("sleep", 300),
    ]


def test_loop_stays_slow_after_a_later_failure(monkeypatch):
    # "Retry every 30 s until the FIRST success, then every 300 s": a failure after
    # a success does not drop back to the fast retry.
    events = _run_loop(monkeypatch, [False, True, False, False], cancel_on_sleep=4)

    assert _sleeps(events) == [30, 300, 300, 300]


def test_loop_survives_an_exception_in_sync_once(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)

    events = _run_loop(
        monkeypatch,
        [RuntimeError("boom: tick exploded"), True, True],
        cancel_on_sleep=3,
    )

    # The raising tick counts as not succeeded (fast retry); the loop keeps going.
    assert _sleeps(events) == [30, 300, 300]
    assert [e[0] for e in events] == ["sync", "sleep"] * 3
    # The exception is logged, not swallowed silently.
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert "boom: tick exploded" in caplog.text


def test_loop_stops_when_cancelled_during_a_sync(monkeypatch):
    # Shutdown cancels the task while it awaits to_thread(sync_once). The loop must
    # re-raise, not treat it as a failed tick and go to sleep (which would hold up
    # shutdown for up to five minutes).
    events = _run_loop(
        monkeypatch, [True], cancel_on_sleep=1, cancel_in_to_thread=True
    )

    assert events == [("cancelled_in_to_thread", None)]


# ---------------------------------------------------------------------------
# Where the loop is registered. Lifespan never runs under IS_TESTING, so no
# behavioural test reaches this wiring; it is asserted structurally, the same way
# as tests/unit/test_spec_sync_sweeper.py::TestWhereTheLoopIsRegistered.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _name_tokens(path: Path) -> list[str]:
    """Every NAME token in *path*, comments and strings discarded."""
    readline = io.BytesIO(path.read_bytes()).readline
    return [t.string for t in tokenize.tokenize(readline) if t.type == tokenize.NAME]


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class TestWhereTheLoopIsRegistered:
    _MAIN = _REPO_ROOT / "src/api/main.py"
    _RUN = _REPO_ROOT / "packages/databricks-tellr-app/databricks_tellr_app/run.py"

    def _lifespan(self) -> ast.AsyncFunctionDef:
        tree = ast.parse(self._MAIN.read_text())
        return next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "lifespan"
        )

    def _create_task_calls(self, lifespan) -> list[ast.Call]:
        return [
            n
            for n in ast.walk(lifespan)
            if isinstance(n, ast.Call)
            and _callee(n) == "create_task"
            and n.args
            and isinstance(n.args[0], ast.Call)
            and _callee(n.args[0]) == "can_manage_sync_loop"
        ]

    def test_the_files_this_asserts_about_are_the_ones_that_exist(self):
        """Entry assertion for every absence below: a missing path would make
        them all vacuously true."""
        assert self._MAIN.is_file(), self._MAIN
        assert self._RUN.is_file(), self._RUN
        assert "lifespan" in _name_tokens(self._MAIN)
        assert "init_database" in _name_tokens(self._RUN)

    def test_the_sync_task_is_created_inside_the_lifespan(self):
        lifespan = self._lifespan()
        created = self._create_task_calls(lifespan)
        assert len(created) == 1, (
            "asyncio.create_task(can_manage_sync_loop()) is not inside the "
            "lifespan; the CAN_MANAGE sync never runs"
        )
        # The task is kept in the module global the shutdown half cancels; without
        # the `global` line the assignment is a local and shutdown sees None.
        assigned = [
            n
            for n in ast.walk(lifespan)
            if isinstance(n, ast.Assign)
            and n.value is created[0]
            and any(
                isinstance(t, ast.Name) and t.id == "_can_manage_sync_task"
                for t in n.targets
            )
        ]
        assert assigned, "the created task is not stored in _can_manage_sync_task"
        declared_global = {
            name
            for n in ast.walk(lifespan)
            if isinstance(n, ast.Global)
            for name in n.names
        }
        assert "_can_manage_sync_task" in declared_global

    def test_the_sync_task_only_starts_in_production_with_an_app_name(self):
        lifespan = self._lifespan()
        (created,) = self._create_task_calls(lifespan)
        parents = {
            child: parent
            for parent in ast.walk(lifespan)
            for child in ast.iter_child_nodes(parent)
        }
        guards = []
        node = created
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.If):
                names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                strings = {
                    n.value
                    for n in ast.walk(node.test)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                }
                guards.append((names, strings))
        assert any(
            "IS_PRODUCTION" in names and "DATABRICKS_APP_NAME" in strings | names
            for names, strings in guards
        ), (
            "create_task(can_manage_sync_loop()) is not under an `if` that checks "
            f"both IS_PRODUCTION and DATABRICKS_APP_NAME; enclosing if-tests: {guards}"
        )

    def test_the_sync_task_is_cancelled_on_shutdown(self):
        lifespan = self._lifespan()
        (yield_node,) = [n for n in ast.walk(lifespan) if isinstance(n, ast.Yield)]
        cancels = [
            n
            for n in ast.walk(lifespan)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "cancel"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "_can_manage_sync_task"
        ]
        assert cancels, (
            "_can_manage_sync_task is never cancelled; shutdown will hang or log a "
            "pending-task warning on every deploy"
        )
        # In the shutdown half, i.e. after the lifespan's yield.
        assert all(c.lineno > yield_node.lineno for c in cancels)

    def test_the_pre_fork_init_database_does_not_start_the_loop(self):
        """run.py::init_database runs once, before the workers fork. A periodic
        loop started there would die with that step."""
        tokens = _name_tokens(self._RUN)
        assert "can_manage_sync_loop" not in tokens, (
            "the CAN_MANAGE sync loop is referenced in run.py; a loop started in "
            "the pre-fork step dies with it and no worker ever syncs"
        )
        assert "can_manage_sync" not in tokens

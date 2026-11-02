"""Tests for src/api/routes/_authz.py (SDR-4437 PR-2 serial gate)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Consolidation: helpers importable from _authz with preserved signatures
# ---------------------------------------------------------------------------


def test_helpers_importable_from_authz():
    from src.api.routes._authz import (  # noqa: F401
        _check_deck_permission_for_session,
        _require_export_job_access,
        _require_session_access,
        _require_slide_permission,
        require_admin,
        reset_admin_cache,
    )


def test_sessions_and_slides_reexport_helpers():
    """Existing call sites in sessions.py / slides.py keep working."""
    from src.api.routes import sessions, slides
    from src.api.routes import _authz

    assert sessions._check_deck_permission_for_session is _authz._check_deck_permission_for_session
    assert sessions._require_session_access is _authz._require_session_access
    assert slides._require_slide_permission is _authz._require_slide_permission


def test_check_deck_permission_signature_defaults():
    import inspect

    from src.api.routes._authz import _check_deck_permission_for_session
    from src.database.models.profile_contributor import PermissionLevel

    sig = inspect.signature(_check_deck_permission_for_session)
    params = list(sig.parameters.values())
    assert params[0].name == "session_id"
    assert params[1].name == "min_permission"
    assert params[1].default == PermissionLevel.CAN_VIEW


# ---------------------------------------------------------------------------
# _require_export_job_access
# ---------------------------------------------------------------------------


def test_export_job_access_unknown_job_404(monkeypatch):
    from src.api.routes import _authz

    class _EmptyQuery:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

    class _FakeDB:
        def query(self, *a, **kw):
            return _EmptyQuery()

    from contextlib import contextmanager

    @contextmanager
    def fake_db_session():
        yield _FakeDB()

    monkeypatch.setattr(_authz, "get_db_session", fake_db_session)
    with pytest.raises(HTTPException) as exc:
        _authz._require_export_job_access("job-unknown")
    assert exc.value.status_code == 404


def test_export_job_access_delegates_to_deck_permission(monkeypatch):
    from src.api.routes import _authz
    from src.database.models.profile_contributor import PermissionLevel

    job = MagicMock()
    job.session_id = "sess-1"

    class _Query:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return job

    class _FakeDB:
        def query(self, *a, **kw):
            return _Query()

    from contextlib import contextmanager

    @contextmanager
    def fake_db_session():
        yield _FakeDB()

    calls = []
    monkeypatch.setattr(_authz, "get_db_session", fake_db_session)
    monkeypatch.setattr(
        _authz,
        "_check_deck_permission_for_session",
        lambda sid, min_permission=PermissionLevel.CAN_VIEW: calls.append((sid, min_permission)),
    )
    _authz._require_export_job_access("job-1")
    assert calls == [("sess-1", PermissionLevel.CAN_VIEW)]


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_env(monkeypatch):
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    _authz.reset_admin_cache()
    yield _authz
    _authz.reset_admin_cache()


def test_require_admin_bypasses_outside_production(monkeypatch):
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: False)
    _authz.require_admin()  # no raise


def test_require_admin_non_admin_403(admin_env, monkeypatch):
    monkeypatch.setattr(admin_env, "_admin_acl_probe", lambda user: False)
    with pytest.raises(HTTPException) as exc:
        admin_env.require_admin()
    assert exc.value.status_code == 403


def test_require_admin_admin_passes(admin_env, monkeypatch):
    monkeypatch.setattr(admin_env, "_admin_acl_probe", lambda user: True)
    admin_env.require_admin()  # no raise


def test_require_admin_fails_closed_on_probe_error(admin_env, monkeypatch):
    """Transient probe errors deny THIS request but must not be cached."""
    calls = []

    def probe(user):
        calls.append(user)
        if len(calls) == 1:
            raise RuntimeError("workspace unreachable")
        return True

    monkeypatch.setattr(admin_env, "_admin_acl_probe", probe)
    with pytest.raises(HTTPException) as exc:
        admin_env.require_admin()
    assert exc.value.status_code == 403
    # The error-derived denial is NOT cached: the next request re-probes
    # and, the blip gone, the real admin gets in (no 60s lockout).
    admin_env.require_admin()  # no raise
    assert len(calls) == 2


def test_require_admin_definitive_non_admin_is_cached_deny(admin_env, monkeypatch):
    """A definitive non-admin verdict (absent from all CAN_MANAGE grants) caches."""
    calls = []

    def probe(user):
        calls.append(user)
        return False

    monkeypatch.setattr(admin_env, "_admin_acl_probe", probe)
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            admin_env.require_admin()
        assert exc.value.status_code == 403
    assert calls == ["user@test.com"]  # second 403 served from cache


def test_require_admin_no_user_403(admin_env, monkeypatch):
    monkeypatch.setattr(admin_env, "get_current_user", lambda: None)
    with pytest.raises(HTTPException) as exc:
        admin_env.require_admin()
    assert exc.value.status_code == 403


def test_require_admin_caches_verdict(admin_env, monkeypatch):
    probes = []

    def probe(user):
        probes.append(user)
        return True

    monkeypatch.setattr(admin_env, "_admin_acl_probe", probe)
    admin_env.require_admin()
    admin_env.require_admin()
    assert probes == ["user@test.com"]  # second call served from cache


# ---------------------------------------------------------------------------
# _admin_acl_probe — the ``permissions`` table decides admin
#
# Admin == a ``permissions`` row for (app, "", admin) matching the caller: a
# USER row for the caller's email, or a GROUP row for one of the caller's OWN
# group display names (current_user.me().groups on the caller's OBO client; the
# app SP cannot list group members). Membership of the workspace ``admins``
# group no longer counts by itself. Rows come from the CAN_MANAGE sync and the
# Admins tab. Any DB or group-lookup error propagates, so require_admin fails
# closed without caching it.
#
# The probe runs against a real in-memory SQLite ``permissions`` table reached
# through a patched ``_authz.get_db_session``; rows are seeded with the store
# service. Only the OBO client and the group-lookup seam are faked.
# ---------------------------------------------------------------------------


def _fake_get_db_session_over(factory):
    """A ``get_db_session`` stand-in shaped like the real one: commit on a clean
    exit, roll back and re-raise on an exception, always close."""

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

    return fake_get_db_session


@pytest.fixture
def probe_db(monkeypatch):
    """In-memory SQLite with every table, behind ``_authz.get_db_session``.

    Yields the session factory so a test can seed rows before probing.
    """
    import src.database.models  # noqa: F401 - register every model on Base.metadata
    from src.api.routes import _authz
    from src.core.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # autoflush=False matches production (src/core/database.py get_session_local).
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(_authz, "get_db_session", _fake_get_db_session_over(factory))
    _authz.reset_admin_cache()
    yield factory
    _authz.reset_admin_cache()
    engine.dispose()


def _seed_manual(factory, identity_type, identity_name):
    """Seed an Admins-tab (``manual``) row, committed."""
    from src.services.admin_permissions import add_manual_admin

    with factory() as db:
        add_manual_admin(
            db,
            identity_type=identity_type,
            identity_name=identity_name,
            identity_id=None,
            created_by="seeder@test.com",
        )
        db.commit()


def _seed_synced(factory, *holders):
    """Seed CAN_MANAGE-sync (``can_manage_sync``) rows, committed.

    ``holders`` are ``(identity_type, identity_name)`` pairs.
    """
    from src.services.admin_permissions import AclHolder, reconcile_can_manage

    with factory() as db:
        reconcile_can_manage(db, [AclHolder(t, n) for t, n in holders])
        db.commit()


def _wire_probe(monkeypatch, *, caller_groups):
    """Fake the caller's OBO client and record every group lookup.

    ``_caller_group_display_names`` is replaced by a recorder that returns
    ``caller_groups``. Returns ``(fake_client, group_calls)``: ``fake_client``
    is what ``get_user_client()`` returns, and ``group_calls`` gets one
    ``(client, user_name)`` tuple per group lookup.
    """
    from src.api.routes import _authz

    fake_client = MagicMock(name="caller_obo_client")
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: fake_client
    )
    group_calls = []

    def recording_group_lookup(client, user_name):
        group_calls.append((client, user_name))
        return set(caller_groups)

    monkeypatch.setattr(_authz, "_caller_group_display_names", recording_group_lookup)
    return fake_client, group_calls


def test_probe_user_row_is_admin_without_group_lookup(probe_db, monkeypatch):
    """A USER row for the caller's email makes them admin (matched
    case-insensitively) and their groups are never looked up.

    A GROUP row the caller is not in is seeded as well, so the user row must be
    checked BEFORE any group lookup, not merely when no GROUP rows exist.
    """
    from src.api.routes import _authz

    _seed_manual(probe_db, "USER", "bob@test.com")
    _seed_synced(probe_db, ("GROUP", "Tellr Maintainers"))
    _, group_calls = _wire_probe(monkeypatch, caller_groups=["users"])

    assert _authz._admin_acl_probe("BOB@test.com") is True
    assert group_calls == [], "a USER-row admin must not trigger a group lookup"


@pytest.mark.parametrize("table", ["empty", "rows_for_others"])
def test_probe_workspace_admins_member_without_row_is_denied(
    probe_db, monkeypatch, table
):
    """REGRESSION for the semantic change: being in the workspace ``admins``
    group no longer makes the caller a Tellr admin.

    Denied on an empty table, and on a populated one with no row for this
    caller or their groups (the state after the first CAN_MANAGE sync on an
    upgraded install, which drops the inherited ``admins`` entry).
    """
    from src.api.routes import _authz

    if table == "rows_for_others":
        _seed_synced(
            probe_db, ("USER", "owner@test.com"), ("GROUP", "Tellr Maintainers")
        )
        _seed_manual(probe_db, "USER", "helper@test.com")
    _wire_probe(monkeypatch, caller_groups=["admins"])

    assert _authz._admin_acl_probe("wsadmin@test.com") is False


def test_probe_group_row_matches_callers_group(probe_db, monkeypatch):
    """A GROUP row admits the caller when it names one of the caller's OWN
    group display names, compared case-insensitively.

    The groups are read through the caller's OBO client, never another one
    (``me()`` on the app SP's client would return the SP's groups, not the
    caller's).
    """
    from src.api.routes import _authz

    _seed_synced(probe_db, ("GROUP", "Tellr Maintainers"))
    fake_client, group_calls = _wire_probe(
        monkeypatch, caller_groups=["tellr maintainers"]
    )

    assert _authz._admin_acl_probe("carol@test.com") is True
    assert group_calls, "the caller's groups were never looked up"
    assert all(client is fake_client for client, _ in group_calls)


def test_probe_admins_group_row_counts_when_granted_directly(probe_db, monkeypatch):
    """The other side of the regression above: ``admins`` is not blacklisted.

    A GROUP row named ``admins`` (CAN_MANAGE granted directly on the app, or
    added in the Admins tab) admits its members like any other group row
    (spec: "A group granted CAN_MANAGE directly on the app counts, even if it
    is the workspace ``admins`` group").
    """
    from src.api.routes import _authz

    _seed_synced(probe_db, ("GROUP", "admins"))
    _wire_probe(monkeypatch, caller_groups=["admins"])

    assert _authz._admin_acl_probe("wsadmin@test.com") is True


def _operational_error():
    from sqlalchemy.exc import OperationalError

    return OperationalError(
        "SELECT permissions.id FROM permissions", {}, Exception("connection refused")
    )


@pytest.mark.parametrize("fails_at", ["session_open", "first_query"])
def test_probe_db_error_raises(monkeypatch, fails_at):
    """A database error propagates; it is never turned into a verdict.

    Returning False would be cached by require_admin and lock a real admin out
    for the TTL; falling back to group membership would fail open (the caller
    here IS in ``admins``). ``session_open``: ``get_db_session`` itself raises.
    ``first_query``: the session opens but the first query fails, which is
    where a broken database actually surfaces (here: the ``permissions`` table
    was never created).
    """
    from sqlalchemy.exc import OperationalError

    from src.api.routes import _authz

    if fails_at == "session_open":

        def broken_get_db_session():
            raise _operational_error()

        monkeypatch.setattr(_authz, "get_db_session", broken_get_db_session)
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )  # no create_all: every query raises "no such table"
        factory = sessionmaker(bind=engine, autoflush=False)
        monkeypatch.setattr(
            _authz, "get_db_session", _fake_get_db_session_over(factory)
        )
    _wire_probe(monkeypatch, caller_groups=["admins"])

    with pytest.raises(OperationalError):
        _authz._admin_acl_probe("wsadmin@test.com")


def test_probe_group_lookup_error_raises_when_group_rows_exist(probe_db, monkeypatch):
    """With a GROUP row to match against, a failing ``current_user.me()``
    propagates, so require_admin fails closed WITHOUT caching (a False here
    would be cached and lock every group admin out for the TTL)."""
    from src.api.routes import _authz

    _seed_synced(probe_db, ("GROUP", "Tellr Maintainers"))
    fake_client = MagicMock(name="caller_obo_client")
    fake_client.current_user.me.side_effect = RuntimeError("workspace unreachable")
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: fake_client
    )

    with pytest.raises(RuntimeError, match="workspace unreachable"):
        _authz._admin_acl_probe("carol@test.com")


def test_caller_group_display_names_reads_me_group_display(monkeypatch):
    """_caller_group_display_names returns the caller's own group *display* names
    from current_user.me() on the OBO client (iam.current-user:read scope)."""
    from src.api.routes import _authz

    g1 = MagicMock(); g1.display = "admins"
    g2 = MagicMock(); g2.display = "users"
    me = MagicMock(); me.groups = [g1, g2]
    client = MagicMock()
    client.current_user.me.return_value = me

    names = _authz._caller_group_display_names(client, "alice@test.com")
    assert names == {"admins", "users"}

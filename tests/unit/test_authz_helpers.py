"""Tests for src/api/routes/_authz.py (SDR-4437 PR-2 serial gate)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


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
# _admin_acl_probe — workspace ``admins`` group membership (Direction C)
#
# Admin is decided from the caller's OWN group membership via the OBO client's
# current_user.me().groups — NOT an app-object ACL read. apps.get_permissions
# is the wrong primitive at runtime: the app's OBO token lacks the
# access-management scope and the app SP is absent from its own ACL. Deciding
# on the caller's own group list cannot fail open (a non-admin's me().groups
# won't contain "admins" and cannot be forged).
# ---------------------------------------------------------------------------


def _wire_probe(monkeypatch, *, caller_groups):
    """Patch _admin_acl_probe's only dependency: the caller's own group names.

    The probe resolves groups via get_user_client().current_user.me().groups
    (OBO); the seam is _caller_group_display_names, which takes the OBO token's
    own identity. No app name, no ACL, no SP.
    """
    from src.api.routes import _authz

    fake_client = MagicMock()
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: fake_client
    )
    monkeypatch.setattr(
        _authz, "_caller_group_display_names", lambda client, user: set(caller_groups)
    )
    return _authz


def test_probe_admins_group_member_is_admin(monkeypatch):
    """Caller whose own groups include 'admins' -> admin."""
    _authz = _wire_probe(monkeypatch, caller_groups=["admins", "users"])
    assert _authz._admin_acl_probe("bob@test.com") is True


def test_probe_non_admin_group_member_denied(monkeypatch):
    """FAIL-OPEN REGRESSION: caller not in 'admins' -> DENIED, even though
    they are an authenticated user with their own (non-admin) groups."""
    _authz = _wire_probe(monkeypatch, caller_groups=["users", "tellr consumers"])
    assert _authz._admin_acl_probe("stranger@test.com") is False


def test_probe_no_groups_denied(monkeypatch):
    """Caller with no group memberships -> not admin."""
    _authz = _wire_probe(monkeypatch, caller_groups=[])
    assert _authz._admin_acl_probe("nobody@test.com") is False


def test_probe_transient_error_raises(monkeypatch):
    """A me() failure propagates so require_admin fails closed WITHOUT caching."""
    from src.api.routes import _authz

    fake_client = MagicMock()
    fake_client.current_user.me.side_effect = RuntimeError("workspace unreachable")
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: fake_client
    )
    with pytest.raises(RuntimeError):
        _authz._admin_acl_probe("alice@test.com")


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

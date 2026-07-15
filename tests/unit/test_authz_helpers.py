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


def test_require_admin_permission_denied_is_cached_deny(admin_env, monkeypatch):
    """A definitive PermissionDenied from the API is a cacheable non-admin verdict."""
    from databricks.sdk.errors import PermissionDenied

    calls = []

    def probe(user):
        calls.append(user)
        raise PermissionDenied("no CAN_MANAGE on app")

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

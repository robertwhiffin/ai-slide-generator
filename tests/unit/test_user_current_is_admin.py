"""``GET /api/user/current`` exposes an ``is_admin`` flag for UX gating only.

The flag lets the frontend hide the /admin page from non-admins. It is NOT
authorization: every admin route keeps ``Depends(require_admin)`` and the
server-side 403s remain the real protection. What this file pins is that the
flag is derived from the SAME admin primitive as those 403s (so it can never
disagree with the gate), and that it fails CLOSED — an unresolvable identity
or a broken group lookup yields ``is_admin: false``, never ``true`` and never
a 500 that would break the whole identity fetch.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def prod_authz(monkeypatch):
    """Force the production admin path (tests otherwise take the dev bypass).

    Same seam the other authz suites use: ``_authz`` module attributes, which
    ``is_caller_admin`` resolves at call time.
    """
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    _authz.reset_admin_cache()
    yield _authz
    _authz.reset_admin_cache()


@pytest.fixture
def permissions_db(monkeypatch):
    """In-memory SQLite with every table, behind ``_authz.get_db_session``.

    The stand-in is shaped like the real ``get_db_session`` (commit on a clean
    exit, roll back and re-raise on an exception). Yields the session factory
    so a test can seed ``permissions`` rows.
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

    monkeypatch.setattr(_authz, "get_db_session", fake_get_db_session)
    _authz.reset_admin_cache()
    yield factory
    _authz.reset_admin_cache()
    engine.dispose()


def test_is_admin_true_for_admin_caller(client, prod_authz, monkeypatch):
    monkeypatch.setattr(prod_authz, "_admin_acl_probe", lambda user: True)
    resp = client.get("/api/user/current")
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True


def test_is_admin_false_for_non_admin_caller(client, prod_authz, monkeypatch):
    monkeypatch.setattr(prod_authz, "_admin_acl_probe", lambda user: False)
    resp = client.get("/api/user/current")
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False


def test_is_admin_false_not_500_when_group_lookup_throws(
    client, prod_authz, permissions_db, monkeypatch
):
    """A broken group lookup must not take the identity endpoint down with it.

    Patched at the real group-lookup seam (``_caller_group_display_names``,
    the ``current_user.me().groups`` read) rather than at the probe, so this
    exercises the same failure the workspace API actually produces.

    The probe only looks the caller's groups up when a GROUP row exists, so one
    is seeded (and no USER row for the caller, which would short-circuit), and
    the test asserts the failing lookup really ran: without that, ``is_admin``
    would be False for want of any row and the test would prove nothing.
    """
    from src.services.admin_permissions import AclHolder, reconcile_can_manage

    with permissions_db() as db:
        reconcile_can_manage(db, [AclHolder("GROUP", "Tellr Maintainers")])
        db.commit()

    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: MagicMock()
    )

    def boom(client_, user):
        raise RuntimeError("workspace unreachable")

    boom_calls = []

    def recording(fn):
        def wrapper(*args, **kwargs):
            boom_calls.append(args)
            return fn(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(prod_authz, "_caller_group_display_names", recording(boom))

    resp = client.get("/api/user/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_admin"] is False
    # The identity itself still resolves — only the admin flag degrades.
    assert body["username"]
    # Non-vacuous: the failing group lookup was actually reached.
    assert boom_calls, "the group lookup never ran, so this test proved nothing"


def test_is_admin_false_when_caller_identity_is_unknown(
    client, prod_authz, monkeypatch
):
    """No resolvable caller -> not admin (fail closed, never open)."""
    monkeypatch.setattr(prod_authz, "get_current_user", lambda: None)
    resp = client.get("/api/user/current")
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False


def test_is_admin_true_in_local_dev_matching_the_require_admin_bypass(
    client, monkeypatch
):
    """Dev/test: ``is_admin`` is true, deliberately.

    ``require_admin`` bypasses in non-production (dev auth is ``DEV_USER_ID``
    with no token or group membership behind it), so the flag must report the
    same thing the server gate would enforce. Reporting false here would hide
    /admin from a devloop tester whose requests the backend still allows.
    """
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: False)
    _authz.reset_admin_cache()
    resp = client.get("/api/user/current")
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True


def test_is_admin_agrees_with_require_admin(prod_authz, monkeypatch):
    """The flag and the real gate must never disagree.

    Pins the derivation itself: for the same caller and probe verdict, a false
    flag implies ``require_admin`` raises and a true flag implies it does not.
    A future refactor that computes the flag from a SECOND, drifting source
    fails here.
    """
    from fastapi import HTTPException

    from src.api.routes._authz import is_caller_admin, require_admin

    for verdict in (True, False):
        monkeypatch.setattr(prod_authz, "_admin_acl_probe", lambda user: verdict)
        prod_authz.reset_admin_cache()
        flag = is_caller_admin()
        prod_authz.reset_admin_cache()
        try:
            require_admin()
            gate_allows = True
        except HTTPException:
            gate_allows = False
        assert flag is gate_allows

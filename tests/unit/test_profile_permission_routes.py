"""Unit tests for profile permission checks (Tasks 8 & 9).

Tests cover:
- Profile contributor validation rejects CAN_VIEW, accepts CAN_USE/CAN_EDIT/CAN_MANAGE
- Contributor management (add/update/delete) requires CAN_MANAGE
- list_contributors requires CAN_USE
- load_profile requires CAN_USE
- update_profile requires CAN_EDIT
- delete_profile requires CAN_MANAGE
- list_profiles only shows accessible profiles
"""

import os
import pytest
from contextlib import contextmanager
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch, MagicMock

from src.core.database import Base, get_db
from src.database.models.profile import ConfigProfile
from src.database.models.profile_contributor import (
    ConfigProfileContributor,
    PermissionLevel,
)
from src.database.models.session import UserSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Module-level variable so the get_db_session patch can access the session factory
_TestingSessionFactory = None


@contextmanager
def _mock_get_db_session():
    """Replacement for get_db_session that uses the test database."""
    session = _TestingSessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite with StaticPool so all sessions share one connection."""
    global _TestingSessionFactory
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import src.database.models.session  # noqa: F401
    import src.database.models.profile  # noqa: F401
    import src.database.models.profile_contributor  # noqa: F401
    import src.database.models.deck_contributor  # noqa: F401

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    _TestingSessionFactory = TestingSession
    session = TestingSession()

    from src.api.main import app

    def _override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db

    yield session

    session.close()
    app.dependency_overrides.clear()
    _TestingSessionFactory = None


def _make_client(user_name: str, user_id: str = "uid-test"):
    """Build a TestClient that sets DEV env vars so the middleware picks them up."""
    from src.api.main import app
    os.environ["DEV_USER_ID"] = user_name
    os.environ["DEV_USER_DATABRICKS_ID"] = user_id
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def owner_client(db_session):
    """Client as profile owner."""
    with patch("src.api.routes.profiles.get_db_session", _mock_get_db_session):
        c = _make_client("owner@example.com", "uid-owner")
        yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def editor_client(db_session):
    """Client as a user with CAN_EDIT on profiles."""
    with patch("src.api.routes.profiles.get_db_session", _mock_get_db_session):
        c = _make_client("editor@example.com", "uid-editor")
        yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def user_client(db_session):
    """Client as a user with CAN_USE on profiles."""
    with patch("src.api.routes.profiles.get_db_session", _mock_get_db_session):
        c = _make_client("user@example.com", "uid-user")
        yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def stranger_client(db_session):
    """Client with no profile access."""
    with patch("src.api.routes.profiles.get_db_session", _mock_get_db_session):
        c = _make_client("stranger@example.com", "uid-stranger")
        yield c
    os.environ.pop("DEV_USER_ID", None)
    os.environ.pop("DEV_USER_DATABRICKS_ID", None)


@pytest.fixture
def owned_profile(db_session):
    """A profile owned by owner@example.com."""
    p = ConfigProfile(
        name="Owner Profile",
        description="Owned by owner",
        agent_config={"tools": []},
        created_by="owner@example.com",
    )
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def shared_profile_edit(db_session, owned_profile):
    """Give editor@example.com CAN_EDIT on owned_profile."""
    c = ConfigProfileContributor(
        profile_id=owned_profile.id,
        identity_id="uid-editor",
        identity_type="USER",
        identity_name="editor@example.com",
        permission_level=PermissionLevel.CAN_EDIT.value,
        created_by="owner@example.com",
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def shared_profile_use(db_session, owned_profile):
    """Give user@example.com CAN_USE on owned_profile."""
    c = ConfigProfileContributor(
        profile_id=owned_profile.id,
        identity_id="uid-user",
        identity_type="USER",
        identity_name="user@example.com",
        permission_level=PermissionLevel.CAN_USE.value,
        created_by="owner@example.com",
    )
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def session_for_load(db_session):
    """A UserSession to load profiles into."""
    s = UserSession(session_id="load-session-1", created_by="owner@example.com")
    db_session.add(s)
    db_session.commit()
    return s


# ---------------------------------------------------------------------------
# Task 8: Contributor validation and permission gate tests
# ---------------------------------------------------------------------------


class TestValidatePermissionLevel:
    """_validate_permission_level should accept CAN_USE/CAN_EDIT/CAN_MANAGE, reject CAN_VIEW."""

    def test_rejects_can_view(self):
        """CAN_VIEW is deck-only; profiles should reject it."""
        from src.api.routes.settings.contributors import _validate_permission_level
        with pytest.raises(ValueError, match="Invalid permission level"):
            _validate_permission_level("CAN_VIEW")

    def test_accepts_can_use(self):
        from src.api.routes.settings.contributors import _validate_permission_level
        assert _validate_permission_level("CAN_USE") == "CAN_USE"

    def test_accepts_can_edit(self):
        from src.api.routes.settings.contributors import _validate_permission_level
        assert _validate_permission_level("CAN_EDIT") == "CAN_EDIT"

    def test_accepts_can_manage(self):
        from src.api.routes.settings.contributors import _validate_permission_level
        assert _validate_permission_level("CAN_MANAGE") == "CAN_MANAGE"

    def test_rejects_invalid(self):
        from src.api.routes.settings.contributors import _validate_permission_level
        with pytest.raises(ValueError):
            _validate_permission_level("ADMIN")


class TestContributorManagementRequiresManage:
    """Contributor add/update/delete require CAN_MANAGE, not CAN_EDIT."""

    def test_add_contributor_with_edit_permission_returns_403(
        self, editor_client, owned_profile, shared_profile_edit
    ):
        """Editor (CAN_EDIT) should NOT be able to add contributors."""
        payload = {
            "identity_id": "uid-new",
            "identity_type": "USER",
            "identity_name": "new@example.com",
            "permission_level": "CAN_USE",
        }
        resp = editor_client.post(
            f"/api/settings/profiles/{owned_profile.id}/contributors",
            json=payload,
        )
        assert resp.status_code == 403

    def test_add_contributor_with_manage_permission_succeeds(
        self, owner_client, owned_profile
    ):
        """Owner (CAN_MANAGE) should be able to add contributors."""
        payload = {
            "identity_id": "uid-new",
            "identity_type": "USER",
            "identity_name": "new@example.com",
            "permission_level": "CAN_USE",
        }
        resp = owner_client.post(
            f"/api/settings/profiles/{owned_profile.id}/contributors",
            json=payload,
        )
        assert resp.status_code == 201

    def test_bulk_add_contributors_with_edit_returns_403(
        self, editor_client, owned_profile, shared_profile_edit
    ):
        """Editor should NOT be able to bulk add contributors."""
        payload = {
            "contributors": [
                {
                    "identity_id": "uid-a",
                    "identity_type": "USER",
                    "identity_name": "a@example.com",
                    "permission_level": "CAN_USE",
                }
            ]
        }
        resp = editor_client.post(
            f"/api/settings/profiles/{owned_profile.id}/contributors/bulk",
            json=payload,
        )
        assert resp.status_code == 403

    def test_update_contributor_with_edit_returns_403(
        self, editor_client, owned_profile, shared_profile_edit
    ):
        """Editor should NOT be able to update contributor permissions."""
        resp = editor_client.put(
            f"/api/settings/profiles/{owned_profile.id}/contributors/{shared_profile_edit.id}",
            json={"permission_level": "CAN_MANAGE"},
        )
        assert resp.status_code == 403

    def test_remove_contributor_with_edit_returns_403(
        self, editor_client, owned_profile, shared_profile_edit
    ):
        """Editor should NOT be able to remove contributors."""
        resp = editor_client.delete(
            f"/api/settings/profiles/{owned_profile.id}/contributors/{shared_profile_edit.id}",
        )
        assert resp.status_code == 403

    def test_list_contributors_with_use_permission_succeeds(
        self, user_client, owned_profile, shared_profile_use
    ):
        """User with CAN_USE should be able to list contributors."""
        resp = user_client.get(
            f"/api/settings/profiles/{owned_profile.id}/contributors",
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Task 9: Profile route permission checks
# ---------------------------------------------------------------------------


class TestListProfilesPermissions:
    """list_profiles should only return accessible profiles."""

    def test_owner_sees_own_profile(self, owner_client, owned_profile):
        resp = owner_client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        ids = [p["id"] for p in data]
        assert owned_profile.id in ids

    def test_stranger_does_not_see_private_profile(
        self, stranger_client, owned_profile
    ):
        resp = stranger_client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        ids = [p["id"] for p in data]
        assert owned_profile.id not in ids

    def test_user_with_access_sees_shared_profile(
        self, user_client, owned_profile, shared_profile_use
    ):
        resp = user_client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        ids = [p["id"] for p in data]
        assert owned_profile.id in ids


class TestLoadProfilePermissions:
    """load_profile_into_session requires CAN_USE."""

    def test_load_profile_without_access_returns_403(
        self, stranger_client, owned_profile, session_for_load
    ):
        resp = stranger_client.post(
            f"/api/sessions/{session_for_load.session_id}/load-profile/{owned_profile.id}",
        )
        assert resp.status_code == 403

    def test_load_profile_with_use_access_succeeds(
        self, user_client, owned_profile, shared_profile_use, session_for_load
    ):
        resp = user_client.post(
            f"/api/sessions/{session_for_load.session_id}/load-profile/{owned_profile.id}",
        )
        assert resp.status_code == 200

    def test_load_profile_as_owner_succeeds(
        self, owner_client, owned_profile, session_for_load
    ):
        resp = owner_client.post(
            f"/api/sessions/{session_for_load.session_id}/load-profile/{owned_profile.id}",
        )
        assert resp.status_code == 200


class TestUpdateProfilePermissions:
    """update_profile requires CAN_EDIT."""

    def test_update_profile_without_access_returns_403(
        self, stranger_client, owned_profile
    ):
        resp = stranger_client.put(
            f"/api/profiles/{owned_profile.id}",
            json={"name": "Hacked"},
        )
        assert resp.status_code == 403

    def test_update_profile_with_use_access_returns_403(
        self, user_client, owned_profile, shared_profile_use
    ):
        resp = user_client.put(
            f"/api/profiles/{owned_profile.id}",
            json={"name": "Hacked"},
        )
        assert resp.status_code == 403

    def test_update_profile_with_edit_access_succeeds(
        self, editor_client, owned_profile, shared_profile_edit
    ):
        resp = editor_client.put(
            f"/api/profiles/{owned_profile.id}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200

    def test_update_profile_as_owner_succeeds(
        self, owner_client, owned_profile
    ):
        resp = owner_client.put(
            f"/api/profiles/{owned_profile.id}",
            json={"name": "Owner Updated"},
        )
        assert resp.status_code == 200


class TestDeleteProfilePermissions:
    """delete_profile requires CAN_MANAGE."""

    def test_delete_profile_without_access_returns_403(
        self, stranger_client, owned_profile
    ):
        resp = stranger_client.delete(f"/api/profiles/{owned_profile.id}")
        assert resp.status_code == 403

    def test_delete_profile_with_edit_access_returns_403(
        self, editor_client, owned_profile, shared_profile_edit
    ):
        resp = editor_client.delete(f"/api/profiles/{owned_profile.id}")
        assert resp.status_code == 403

    def test_delete_profile_as_owner_succeeds(
        self, owner_client, owned_profile
    ):
        resp = owner_client.delete(f"/api/profiles/{owned_profile.id}")
        assert resp.status_code == 200

"""Unit tests for simplified profile routes (list/save/load/update/delete)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from src.api.main import app

    return TestClient(app)


def _make_profile(
    id=1,
    name="My Profile",
    description="desc",
    is_default=False,
    agent_config=None,
    created_at=None,
    created_by="user@test.com",
    is_deleted=False,
):
    """Create a mock ConfigProfile object."""
    p = MagicMock()
    p.id = id
    p.name = name
    p.description = description
    p.is_default = is_default
    p.agent_config = agent_config
    p.created_at = created_at or datetime(2026, 1, 1, 12, 0, 0)
    p.created_by = created_by
    p.is_deleted = is_deleted
    p.deleted_at = None
    return p


class TestListProfiles:
    @patch("src.api.routes.profiles.get_db_session")
    def test_list_profiles(self, mock_get_db, client):
        """GET /api/profiles returns non-deleted profiles."""
        p1 = _make_profile(id=1, name="Profile A", is_default=True)
        p2 = _make_profile(id=2, name="Profile B", is_default=False)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [p1, p2]
        mock_get_db.return_value = mock_db

        response = client.get("/api/profiles")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["name"] == "Profile A"
        assert data[0]["is_default"] is True
        assert data[1]["id"] == 2


class TestSaveFromSession:
    @patch("src.api.routes.profiles.get_db_session")
    @patch("src.api.routes.profiles.get_session_manager")
    def test_save_from_session_creates_profile(self, mock_get_mgr, mock_get_db, client):
        """POST /api/profiles/save-from-session/{session_id} creates a profile from session config."""
        mgr = MagicMock()
        mgr.get_session.return_value = {
            "session_id": "sess-1",
            "agent_config": {"tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}]},
        }
        mock_get_mgr.return_value = mgr

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = mock_db

        # Mock the flush to set an id on the profile
        def set_id_on_flush():
            # The profile added to the db will be tracked via add call
            added_obj = mock_db.add.call_args[0][0]
            added_obj.id = 42

        mock_db.flush.side_effect = set_id_on_flush

        response = client.post(
            "/api/profiles/save-from-session/sess-1",
            json={"name": "Saved Config", "description": "From session"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 42
        assert data["name"] == "Saved Config"
        assert "agent_config" in data

    @patch("src.api.routes.profiles.get_db_session")
    @patch("src.api.routes.profiles.get_session_manager")
    def test_save_from_session_defaults_when_no_config(self, mock_get_mgr, mock_get_db, client):
        """When session has no agent_config, saves AgentConfig() defaults."""
        mgr = MagicMock()
        mgr.get_session.return_value = {
            "session_id": "sess-1",
            "agent_config": None,
        }
        mock_get_mgr.return_value = mgr

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = mock_db

        def set_id_on_flush():
            added_obj = mock_db.add.call_args[0][0]
            added_obj.id = 10

        mock_db.flush.side_effect = set_id_on_flush

        response = client.post(
            "/api/profiles/save-from-session/sess-1",
            json={"name": "Default Config"},
        )
        assert response.status_code == 201
        data = response.json()
        # Should have default agent config (empty tools, null ids)
        assert data["agent_config"]["tools"] == []

    @patch("src.api.routes.profiles.get_db_session")
    @patch("src.api.routes.profiles.get_session_manager")
    def test_save_from_session_rejects_duplicate_config(self, mock_get_mgr, mock_get_db, client):
        """POST /api/profiles/save-from-session rejects when identical agent_config already exists."""
        config = {"tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}]}
        mgr = MagicMock()
        mgr.get_session.return_value = {
            "session_id": "sess-1",
            "agent_config": config,
        }
        mock_get_mgr.return_value = mgr

        existing_profile = _make_profile(id=99, name="Existing", agent_config=config)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = [existing_profile]
        mock_get_db.return_value = mock_db

        response = client.post(
            "/api/profiles/save-from-session/sess-1",
            json={"name": "New Profile"},
        )
        assert response.status_code == 409
        assert "Existing" in response.json()["detail"]

    @patch("src.api.routes.profiles.get_db_session")
    @patch("src.api.routes.profiles.get_session_manager")
    def test_save_from_session_allows_unique_config(self, mock_get_mgr, mock_get_db, client):
        """POST /api/profiles/save-from-session succeeds when no matching config exists."""
        config = {"tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}]}
        mgr = MagicMock()
        mgr.get_session.return_value = {
            "session_id": "sess-1",
            "agent_config": config,
        }
        mock_get_mgr.return_value = mgr

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_get_db.return_value = mock_db

        def set_id_on_flush():
            added_obj = mock_db.add.call_args[0][0]
            added_obj.id = 50

        mock_db.flush.side_effect = set_id_on_flush

        response = client.post(
            "/api/profiles/save-from-session/sess-1",
            json={"name": "New Profile"},
        )
        assert response.status_code == 201


class TestLoadProfileIntoSession:
    @patch("src.api.routes.profiles.get_db_session")
    @patch("src.api.routes.profiles.get_session_manager")
    def test_load_profile_into_session(self, mock_get_mgr, mock_get_db, client):
        """POST /api/sessions/{sid}/load-profile/{pid} copies profile config to session."""
        agent_cfg = {"tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}]}
        profile = _make_profile(id=5, agent_config=agent_cfg)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = profile
        mock_get_db.return_value = mock_db

        # Mock session DB lookup for writing agent_config
        mock_session = MagicMock()
        mock_session.agent_config = None

        # We need a second query call to return the session
        # Use side_effect to differentiate between profile and session queries
        from src.database.models.profile import ConfigProfile
        from src.database.models.session import UserSession

        def query_side_effect(model):
            q = MagicMock()
            if model is ConfigProfile:
                q.filter.return_value.first.return_value = profile
            elif model is UserSession:
                q.filter.return_value.first.return_value = mock_session
            return q

        mock_db.query.side_effect = query_side_effect
        mock_get_db.return_value = mock_db

        response = client.post("/api/sessions/sess-1/load-profile/5")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "loaded"
        assert "agent_config" in data


class TestUpdateProfile:
    @patch("src.api.routes.profiles.get_db_session")
    def test_update_profile_name(self, mock_get_db, client):
        """PUT /api/profiles/{id} updates profile name."""
        profile = _make_profile(id=3, name="Old Name")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = profile
        mock_get_db.return_value = mock_db

        response = client.put("/api/profiles/3", json={"name": "New Name"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"

    @patch("src.api.routes.profiles.get_db_session")
    def test_set_default_clears_others(self, mock_get_db, client):
        """PUT /api/profiles/{id} with is_default=true clears other defaults."""
        profile = _make_profile(id=3, name="Profile C", is_default=False)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = profile
        mock_get_db.return_value = mock_db

        response = client.put("/api/profiles/3", json={"is_default": True})
        assert response.status_code == 200
        data = response.json()
        assert data["is_default"] is True

        # Verify that an update was issued to clear other defaults
        # The mock_db.query should have been called with an update to clear is_default
        update_calls = mock_db.execute.call_args_list
        assert len(update_calls) > 0, "Expected execute call to clear other defaults"


class TestDeleteProfile:
    @patch("src.api.routes.profiles.get_db_session")
    def test_delete_profile(self, mock_get_db, client):
        """DELETE /api/profiles/{id} soft-deletes the profile."""
        profile = _make_profile(id=7, name="To Delete")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = profile
        mock_get_db.return_value = mock_db

        response = client.delete("/api/profiles/7")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

        # Verify soft-delete fields were set
        assert profile.is_deleted is True
        assert profile.deleted_at is not None

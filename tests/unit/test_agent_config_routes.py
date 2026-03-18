"""Unit tests for agent config API routes (GET/PUT/PATCH)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from src.api.main import app

    return TestClient(app)


def _mock_session_manager(agent_config=None):
    """Return a mock session manager whose get_session returns the given agent_config."""
    mgr = MagicMock()
    mgr.get_session.return_value = {
        "session_id": "sess-1",
        "agent_config": agent_config,
    }
    return mgr


class TestGetAgentConfig:
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_get_agent_config_returns_defaults_when_null(self, mock_get_mgr, client):
        """GET returns defaults when session has no agent_config."""
        mock_get_mgr.return_value = _mock_session_manager(agent_config=None)

        response = client.get("/api/sessions/sess-1/agent-config")
        assert response.status_code == 200
        data = response.json()
        assert data["tools"] == []
        assert data["slide_style_id"] is None
        assert data["deck_prompt_id"] is None

    @patch("src.api.routes.agent_config.get_session_manager")
    def test_get_agent_config_returns_stored_config(self, mock_get_mgr, client):
        """GET returns the stored config when present."""
        stored = {
            "tools": [{"type": "genie", "space_id": "abc", "space_name": "My Space"}],
            "slide_style_id": 5,
            "deck_prompt_id": 3,
        }
        mock_get_mgr.return_value = _mock_session_manager(agent_config=stored)

        response = client.get("/api/sessions/sess-1/agent-config")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 1
        assert data["tools"][0]["space_id"] == "abc"
        assert data["slide_style_id"] == 5
        assert data["deck_prompt_id"] == 3

    @patch("src.api.routes.agent_config.get_session_manager")
    def test_get_agent_config_session_not_found(self, mock_get_mgr, client):
        """GET returns 404 when session doesn't exist."""
        from src.api.services.session_manager import SessionNotFoundError

        mgr = MagicMock()
        mgr.get_session.side_effect = SessionNotFoundError("not found")
        mock_get_mgr.return_value = mgr

        response = client.get("/api/sessions/sess-missing/agent-config")
        assert response.status_code == 404


class TestPutAgentConfig:
    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config._validate_references")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_put_agent_config_persists(self, mock_get_mgr, mock_validate, mock_save, client):
        """PUT saves config to session."""
        mgr = _mock_session_manager()
        mock_get_mgr.return_value = mgr

        payload = {
            "tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}],
            "slide_style_id": None,
            "deck_prompt_id": None,
        }

        # Make _save_agent_config return the config dict it receives
        mock_save.side_effect = lambda sid, cfg: cfg.model_dump()

        response = client.put("/api/sessions/sess-1/agent-config", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 1
        assert data["tools"][0]["space_id"] == "g1"

    def test_put_agent_config_rejects_duplicates(self, client):
        """PUT rejects duplicate tools (422)."""
        payload = {
            "tools": [
                {"type": "genie", "space_id": "g1", "space_name": "Sales"},
                {"type": "genie", "space_id": "g1", "space_name": "Sales Copy"},
            ],
        }

        response = client.put("/api/sessions/sess-1/agent-config", json=payload)
        assert response.status_code == 422

    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config._validate_references")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_put_agent_config_validates_style_id(self, mock_get_mgr, mock_validate, mock_save, client):
        """PUT rejects invalid slide_style_id (422)."""
        from fastapi import HTTPException

        mock_get_mgr.return_value = _mock_session_manager()
        mock_validate.side_effect = HTTPException(
            status_code=422, detail="slide_style_id 999 not found"
        )

        payload = {"tools": [], "slide_style_id": 999}

        response = client.put("/api/sessions/sess-1/agent-config", json=payload)
        assert response.status_code == 422
        assert "999" in response.json()["detail"]


class TestPatchTools:
    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_patch_tools_adds_tool(self, mock_get_mgr, mock_save, client):
        """PATCH with action=add adds a tool."""
        existing = {"tools": [], "slide_style_id": None, "deck_prompt_id": None}
        mgr = _mock_session_manager(agent_config=existing)
        mock_get_mgr.return_value = mgr
        mock_save.side_effect = lambda sid, cfg: cfg.model_dump()

        payload = {
            "action": "add",
            "tool": {"type": "genie", "space_id": "g1", "space_name": "Sales"},
        }

        response = client.patch("/api/sessions/sess-1/agent-config/tools", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 1
        assert data["tools"][0]["space_id"] == "g1"

    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_patch_tools_removes_tool(self, mock_get_mgr, mock_save, client):
        """PATCH with action=remove removes a tool."""
        existing = {
            "tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}],
            "slide_style_id": None,
            "deck_prompt_id": None,
        }
        mgr = _mock_session_manager(agent_config=existing)
        mock_get_mgr.return_value = mgr
        mock_save.side_effect = lambda sid, cfg: cfg.model_dump()

        payload = {
            "action": "remove",
            "tool": {"type": "genie", "space_id": "g1", "space_name": "Sales"},
        }

        response = client.patch("/api/sessions/sess-1/agent-config/tools", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 0

    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_patch_tools_add_duplicate_rejected(self, mock_get_mgr, mock_save, client):
        """PATCH add rejects duplicate tool (422)."""
        existing = {
            "tools": [{"type": "genie", "space_id": "g1", "space_name": "Sales"}],
        }
        mgr = _mock_session_manager(agent_config=existing)
        mock_get_mgr.return_value = mgr

        payload = {
            "action": "add",
            "tool": {"type": "genie", "space_id": "g1", "space_name": "Sales Again"},
        }

        response = client.patch("/api/sessions/sess-1/agent-config/tools", json=payload)
        assert response.status_code == 422

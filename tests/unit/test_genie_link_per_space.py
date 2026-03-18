"""Tests for per-space Genie link endpoint.

Verifies that GET /api/verification/genie-link accepts an optional space_id
query param and returns per-space Genie deep-links from agent_config.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_session_manager():
    with patch("src.api.routes.verification.get_session_manager") as mock:
        manager = MagicMock()
        mock.return_value = manager
        yield manager


class TestGenieLinkWithSpaceId:
    """GET /api/verification/genie-link?session_id=X&space_id=Y"""

    def test_returns_link_for_specific_space(self, client, mock_session_manager):
        """When space_id is provided, should use agent_config to find conversation_id."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": "legacy-conv",
            "agent_config": {
                "tools": [
                    {
                        "type": "genie",
                        "space_id": "space-abc",
                        "space_name": "Sales",
                        "conversation_id": "conv-per-space",
                    }
                ],
            },
        }

        with patch("src.core.settings_db.get_settings") as mock_settings:
            settings = MagicMock()
            settings.databricks_host = "https://adb-12345.us-west-2.azuredatabricks.net"
            settings.genie = MagicMock()
            settings.genie.space_id = "default-space"
            mock_settings.return_value = settings

            response = client.get(
                "/api/verification/genie-link?session_id=test-123&space_id=space-abc"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["has_genie_conversation"] is True
        assert "conv-per-space" in data["url"]
        assert "space-abc" in data["url"]

    def test_returns_no_conversation_when_space_not_found(self, client, mock_session_manager):
        """When space_id doesn't match any tool, should return no conversation."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": "legacy-conv",
            "agent_config": {
                "tools": [
                    {
                        "type": "genie",
                        "space_id": "space-abc",
                        "space_name": "Sales",
                        "conversation_id": None,
                    }
                ],
            },
        }

        response = client.get(
            "/api/verification/genie-link?session_id=test-123&space_id=nonexistent"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_genie_conversation"] is False

    def test_returns_no_conversation_when_tool_has_no_conv_id(self, client, mock_session_manager):
        """When space_id matches but tool has no conversation_id, return no conversation."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": None,
            "agent_config": {
                "tools": [
                    {
                        "type": "genie",
                        "space_id": "space-abc",
                        "space_name": "Sales",
                        "conversation_id": None,
                    }
                ],
            },
        }

        response = client.get(
            "/api/verification/genie-link?session_id=test-123&space_id=space-abc"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_genie_conversation"] is False

    def test_legacy_fallback_without_space_id(self, client, mock_session_manager):
        """Without space_id, should fall back to legacy behavior."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": "legacy-conv",
        }

        with patch("src.core.settings_db.get_settings") as mock_settings:
            settings = MagicMock()
            settings.databricks_host = "https://adb-12345.us-west-2.azuredatabricks.net"
            settings.genie = MagicMock()
            settings.genie.space_id = "default-space"
            mock_settings.return_value = settings

            response = client.get(
                "/api/verification/genie-link?session_id=test-123"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["has_genie_conversation"] is True
        assert "legacy-conv" in data["url"]

"""Unit tests for tool discovery API routes (GET /api/tools/available)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from src.api.main import app

    return TestClient(app)


def _make_genie_space(space_id: str, title: str, description: str | None = None):
    """Create a mock Genie space object."""
    space = MagicMock()
    space.space_id = space_id
    space.title = title
    space.description = description
    return space


class TestGetAvailableTools:
    @patch("src.api.routes.tools._list_genie_spaces")
    @patch("src.api.routes.tools._list_mcp_servers")
    def test_available_tools_returns_genie_spaces(self, mock_mcp, mock_genie, client):
        """GET /api/tools/available returns Genie spaces."""
        mock_genie.return_value = [
            {"type": "genie", "space_id": "sp-1", "space_name": "Sales", "description": "Sales data"},
        ]
        mock_mcp.return_value = []

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "genie"
        assert data[0]["space_id"] == "sp-1"
        assert data[0]["space_name"] == "Sales"
        assert data[0]["description"] == "Sales data"

    @patch("src.api.routes.tools._list_genie_spaces")
    @patch("src.api.routes.tools._list_mcp_servers")
    def test_available_tools_returns_mcp_servers(self, mock_mcp, mock_genie, client):
        """GET /api/tools/available returns MCP servers from config."""
        mock_genie.return_value = []
        mock_mcp.return_value = [
            {"type": "mcp", "connection_name": "http://localhost:8080", "server_name": "my-mcp", "config": {"key": "val"}},
        ]

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "mcp"
        assert data[0]["connection_name"] == "http://localhost:8080"
        assert data[0]["server_name"] == "my-mcp"
        assert data[0]["config"] == {"key": "val"}

    @patch("src.api.routes.tools._list_genie_spaces")
    @patch("src.api.routes.tools._list_mcp_servers")
    def test_available_tools_merges_sources(self, mock_mcp, mock_genie, client):
        """GET /api/tools/available merges both sources."""
        mock_genie.return_value = [
            {"type": "genie", "space_id": "sp-1", "space_name": "Sales", "description": None},
        ]
        mock_mcp.return_value = [
            {"type": "mcp", "connection_name": "http://localhost:8080", "server_name": "my-mcp", "config": {}},
        ]

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        types = {item["type"] for item in data}
        assert types == {"genie", "mcp"}

    @patch("src.api.routes.tools._list_genie_spaces")
    @patch("src.api.routes.tools._list_mcp_servers")
    def test_genie_failure_returns_empty(self, mock_mcp, mock_genie, client):
        """Genie SDK failure doesn't break the endpoint."""
        mock_genie.return_value = []  # graceful degradation already handled inside _list_genie_spaces
        mock_mcp.return_value = [
            {"type": "mcp", "connection_name": "http://localhost:8080", "server_name": "my-mcp", "config": {}},
        ]

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "mcp"

    @patch("src.api.routes.tools._list_genie_spaces")
    @patch("src.api.routes.tools._list_mcp_servers")
    def test_mcp_failure_returns_empty(self, mock_mcp, mock_genie, client):
        """Config failure doesn't break the endpoint."""
        mock_genie.return_value = [
            {"type": "genie", "space_id": "sp-1", "space_name": "Sales", "description": None},
        ]
        mock_mcp.return_value = []  # graceful degradation already handled inside _list_mcp_servers

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["type"] == "genie"

    @patch("src.api.routes.tools._list_genie_spaces")
    @patch("src.api.routes.tools._list_mcp_servers")
    def test_both_empty(self, mock_mcp, mock_genie, client):
        """Returns empty list when no tools available."""
        mock_genie.return_value = []
        mock_mcp.return_value = []

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        assert response.json() == []


class TestListGenieSpacesInternal:
    """Test the _list_genie_spaces helper directly (graceful degradation)."""

    @patch("src.api.routes.tools.get_user_client")
    def test_list_genie_spaces_success(self, mock_get_client):
        """Returns formatted Genie spaces from Databricks SDK."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.spaces = [
            _make_genie_space("sp-1", "Sales", "Sales data"),
            _make_genie_space("sp-2", "Marketing", None),
        ]
        mock_response.next_page_token = None
        mock_client.genie.list_spaces.return_value = mock_response
        mock_get_client.return_value = mock_client

        from src.api.routes.tools import _list_genie_spaces

        result = _list_genie_spaces()
        assert len(result) == 2
        assert result[0] == {"type": "genie", "space_id": "sp-1", "space_name": "Sales", "description": "Sales data"}
        assert result[1] == {"type": "genie", "space_id": "sp-2", "space_name": "Marketing", "description": None}

    @patch("src.api.routes.tools.get_user_client")
    def test_list_genie_spaces_sdk_failure(self, mock_get_client):
        """Returns empty list on SDK failure."""
        mock_get_client.side_effect = Exception("SDK unavailable")

        from src.api.routes.tools import _list_genie_spaces

        result = _list_genie_spaces()
        assert result == []

    @patch("src.api.routes.tools.get_user_client")
    def test_list_genie_spaces_pagination(self, mock_get_client):
        """Handles paginated responses."""
        mock_client = MagicMock()

        page1 = MagicMock()
        page1.spaces = [_make_genie_space("sp-1", "Sales", "Sales data")]
        page1.next_page_token = "token-2"

        page2 = MagicMock()
        page2.spaces = [_make_genie_space("sp-2", "Marketing", None)]
        page2.next_page_token = None

        mock_client.genie.list_spaces.side_effect = [page1, page2]
        mock_get_client.return_value = mock_client

        from src.api.routes.tools import _list_genie_spaces

        result = _list_genie_spaces()
        assert len(result) == 2
        assert result[0]["space_id"] == "sp-1"
        assert result[1]["space_id"] == "sp-2"


class TestListMcpServersInternal:
    """Test the _list_mcp_servers helper directly (graceful degradation)."""

    @patch("src.api.routes.tools.load_config")
    def test_list_mcp_servers_success(self, mock_load):
        """Returns formatted MCP servers from config."""
        mock_load.return_value = {
            "mcp_servers": [
                {"uri": "http://localhost:8080", "name": "my-mcp", "config": {"key": "val"}},
                {"uri": "http://localhost:9090", "name": "other-mcp"},
            ]
        }

        from src.api.routes.tools import _list_mcp_servers

        result = _list_mcp_servers()
        assert len(result) == 2
        assert result[0] == {"type": "mcp", "connection_name": "http://localhost:8080", "server_name": "my-mcp", "config": {"key": "val"}}
        assert result[1] == {"type": "mcp", "connection_name": "http://localhost:9090", "server_name": "other-mcp", "config": {}}

    @patch("src.api.routes.tools.load_config")
    def test_list_mcp_servers_no_key(self, mock_load):
        """Returns empty list when mcp_servers key is absent."""
        mock_load.return_value = {"llm": {}, "genie": {}, "api": {}, "output": {}, "logging": {}}

        from src.api.routes.tools import _list_mcp_servers

        result = _list_mcp_servers()
        assert result == []

    @patch("src.api.routes.tools.load_config")
    def test_list_mcp_servers_config_failure(self, mock_load):
        """Returns empty list on config failure."""
        mock_load.side_effect = Exception("Config not found")

        from src.api.routes.tools import _list_mcp_servers

        result = _list_mcp_servers()
        assert result == []

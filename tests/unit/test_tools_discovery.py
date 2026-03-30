"""Tests for tool discovery endpoints."""

import pytest
from unittest.mock import MagicMock, patch


def _make_client():
    return MagicMock()


class TestGenieDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_genie_returns_spaces(self, mock_client_fn):
        from src.api.routes.tools import _discover_genie_spaces

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client
        mock_space = MagicMock()
        mock_space.space_id = "space-1"
        mock_space.title = "Sales Data"
        mock_space.description = "Revenue analytics"
        mock_response = MagicMock()
        mock_response.spaces = [mock_space]
        mock_response.next_page_token = None
        mock_client.genie.list_spaces.return_value = mock_response
        result = _discover_genie_spaces()
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "space-1"
        assert result["items"][0]["name"] == "Sales Data"
        assert result["items"][0]["description"] == "Revenue analytics"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_genie_pagination(self, mock_client_fn):
        from src.api.routes.tools import _discover_genie_spaces

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_space1 = MagicMock()
        mock_space1.space_id = "space-1"
        mock_space1.title = "Sales"
        mock_space1.description = None

        mock_space2 = MagicMock()
        mock_space2.space_id = "space-2"
        mock_space2.title = "Marketing"
        mock_space2.description = "Marketing data"

        page1 = MagicMock()
        page1.spaces = [mock_space1]
        page1.next_page_token = "token-2"

        page2 = MagicMock()
        page2.spaces = [mock_space2]
        page2.next_page_token = None

        mock_client.genie.list_spaces.side_effect = [page1, page2]
        result = _discover_genie_spaces()
        assert len(result["items"]) == 2
        assert result["items"][0]["id"] == "space-1"
        assert result["items"][1]["id"] == "space-2"


class TestVectorDiscovery:
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_index_with_embedding(name: str):
        """Return a (list_indexes item, get_index detail) pair that has embedding support."""
        idx = MagicMock()
        idx.name = name
        idx.index_type.value = "DELTA_SYNC"
        idx.primary_key = "id"

        detail = MagicMock()
        detail.delta_sync_index_spec = MagicMock()
        detail.delta_sync_index_spec.embedding_source_columns = [MagicMock()]
        detail.direct_access_index_spec = None
        return idx, detail

    @staticmethod
    def _make_index_without_embedding(name: str):
        """Return a (list_indexes item, get_index detail) pair with NO embedding support."""
        idx = MagicMock()
        idx.name = name
        idx.index_type.value = "DELTA_SYNC"
        idx.primary_key = "id"

        detail = MagicMock()
        detail.delta_sync_index_spec = MagicMock()
        detail.delta_sync_index_spec.embedding_source_columns = []
        detail.direct_access_index_spec = None
        return idx, detail

    # ------------------------------------------------------------------
    # Endpoint discovery tests
    # ------------------------------------------------------------------

    def _clear_endpoint_cache(self):
        """Clear the vector endpoints cache before each test."""
        import src.api.routes.tools as tools_mod
        tools_mod._vector_endpoints_cache = None
        tools_mod._vector_endpoints_cache_time = 0

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_endpoints(self, mock_client_fn):
        """ONLINE endpoint with an embedding index is included."""
        self._clear_endpoint_cache()
        from src.api.routes.tools import _discover_vector_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_ep = MagicMock()
        mock_ep.name = "vs-endpoint-1"
        mock_ep.endpoint_status = MagicMock()
        mock_ep.endpoint_status.state.value = "ONLINE"
        mock_client.vector_search_endpoints.list_endpoints.return_value = [mock_ep]

        idx, detail = self._make_index_with_embedding("cat.schema.idx")
        mock_client.vector_search_indexes.list_indexes.return_value = [idx]
        mock_client.vector_search_indexes.get_index.return_value = detail

        result = _discover_vector_endpoints()
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "vs-endpoint-1"
        assert result["items"][0]["metadata"]["state"] == "ONLINE"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_endpoints_filters_offline(self, mock_client_fn):
        """OFFLINE endpoints are excluded regardless of their indexes."""
        self._clear_endpoint_cache()
        from src.api.routes.tools import _discover_vector_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_online = MagicMock()
        mock_online.name = "online-ep"
        mock_online.endpoint_status = MagicMock()
        mock_online.endpoint_status.state.value = "ONLINE"

        mock_offline = MagicMock()
        mock_offline.name = "offline-ep"
        mock_offline.endpoint_status = MagicMock()
        mock_offline.endpoint_status.state.value = "OFFLINE"

        mock_client.vector_search_endpoints.list_endpoints.return_value = [
            mock_online,
            mock_offline,
        ]

        # Only the online endpoint will have its indexes checked
        idx, detail = self._make_index_with_embedding("cat.schema.idx")
        mock_client.vector_search_indexes.list_indexes.return_value = [idx]
        mock_client.vector_search_indexes.get_index.return_value = detail

        result = _discover_vector_endpoints()
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "online-ep"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_indexes_with_embedding(self, mock_client_fn):
        """Indexes with embedding_source_columns are included."""
        from src.api.routes.tools import _discover_vector_indexes

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_idx = MagicMock()
        mock_idx.name = "my_catalog.my_schema.my_index"
        mock_idx.index_type.value = "DELTA_SYNC"
        mock_idx.primary_key = "id"

        # get_index returns detail with embedding_source_columns set
        mock_detail = MagicMock()
        mock_detail.delta_sync_index_spec = MagicMock()
        mock_detail.delta_sync_index_spec.embedding_source_columns = [MagicMock()]
        mock_detail.direct_access_index_spec = None

        mock_client.vector_search_indexes.list_indexes.return_value = [mock_idx]
        mock_client.vector_search_indexes.get_index.return_value = mock_detail

        result = _discover_vector_indexes("vs-endpoint-1")
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "my_catalog.my_schema.my_index"
        assert result["items"][0]["metadata"]["index_type"] == "DELTA_SYNC"
        assert result["items"][0]["metadata"]["primary_key"] == "id"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_indexes_filters_no_embedding(self, mock_client_fn):
        """Indexes without embedding_source_columns are excluded."""
        from src.api.routes.tools import _discover_vector_indexes

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_idx_no_emb = MagicMock()
        mock_idx_no_emb.name = "my_catalog.my_schema.raw_vector_index"
        mock_idx_no_emb.index_type.value = "DELTA_SYNC"
        mock_idx_no_emb.primary_key = "id"

        mock_idx_with_emb = MagicMock()
        mock_idx_with_emb.name = "my_catalog.my_schema.text_index"
        mock_idx_with_emb.index_type.value = "DELTA_SYNC"
        mock_idx_with_emb.primary_key = "id"

        # First index: no embedding_source_columns
        mock_detail_no_emb = MagicMock()
        mock_detail_no_emb.delta_sync_index_spec = MagicMock()
        mock_detail_no_emb.delta_sync_index_spec.embedding_source_columns = []
        mock_detail_no_emb.direct_access_index_spec = None

        # Second index: has embedding_source_columns
        mock_detail_with_emb = MagicMock()
        mock_detail_with_emb.delta_sync_index_spec = MagicMock()
        mock_detail_with_emb.delta_sync_index_spec.embedding_source_columns = [MagicMock()]
        mock_detail_with_emb.direct_access_index_spec = None

        mock_client.vector_search_indexes.list_indexes.return_value = [
            mock_idx_no_emb,
            mock_idx_with_emb,
        ]
        mock_client.vector_search_indexes.get_index.side_effect = [
            mock_detail_no_emb,
            mock_detail_with_emb,
        ]

        result = _discover_vector_indexes("vs-endpoint-1")
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "my_catalog.my_schema.text_index"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_indexes_includes_on_get_index_error(self, mock_client_fn):
        """If get_index raises, the index is included (fail-open)."""
        from src.api.routes.tools import _discover_vector_indexes

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_idx = MagicMock()
        mock_idx.name = "my_catalog.my_schema.my_index"
        mock_idx.index_type.value = "DELTA_SYNC"
        mock_idx.primary_key = "id"

        mock_client.vector_search_indexes.list_indexes.return_value = [mock_idx]
        mock_client.vector_search_indexes.get_index.side_effect = Exception("Permission denied")

        result = _discover_vector_indexes("vs-endpoint-1")
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "my_catalog.my_schema.my_index"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_vector_columns_delta_sync(self, mock_client_fn):
        from src.api.routes.tools import _discover_vector_columns

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_index = MagicMock()
        mock_index.primary_key = "id"
        mock_index.index_type.value = "DELTA_SYNC"

        # delta_sync_index_spec
        mock_source_col = MagicMock()
        mock_source_col.name = "text_content"
        mock_embedding_col = MagicMock()
        mock_embedding_col.name = "text_content_embedding"
        mock_embedding_col.embedding_dimension = 768

        mock_index.delta_sync_index_spec = MagicMock()
        mock_index.delta_sync_index_spec.source_table = "my_catalog.my_schema.my_table"
        mock_index.delta_sync_index_spec.embedding_source_columns = [mock_source_col]
        mock_index.delta_sync_index_spec.embedding_vector_columns = [mock_embedding_col]
        mock_index.direct_access_index_spec = None

        mock_client.vector_search_indexes.get_index.return_value = mock_index
        result = _discover_vector_columns("vs-endpoint-1", "my_catalog.my_schema.my_index")

        assert result["primary_key"] == "id"
        assert result["source_table"] == "my_catalog.my_schema.my_table"
        assert len(result["columns"]) >= 2


class TestMCPDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_mcp_connections(self, mock_client_fn):
        from src.api.routes.tools import _discover_mcp_connections

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client
        mock_conn = MagicMock()
        mock_conn.name = "jira-conn"
        mock_conn.connection_type.value = "HTTP"
        mock_conn.comment = "Jira integration"
        mock_client.connections.list.return_value = [mock_conn]
        result = _discover_mcp_connections()
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "jira-conn"
        assert result["items"][0]["description"] == "Jira integration"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_mcp_connections_filters_non_http(self, mock_client_fn):
        from src.api.routes.tools import _discover_mcp_connections

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_http = MagicMock()
        mock_http.name = "jira-conn"
        mock_http.connection_type.value = "HTTP"
        mock_http.comment = "Jira"

        mock_snowflake = MagicMock()
        mock_snowflake.name = "sf-conn"
        mock_snowflake.connection_type.value = "SNOWFLAKE"
        mock_snowflake.comment = "Snowflake warehouse"

        mock_client.connections.list.return_value = [mock_http, mock_snowflake]
        result = _discover_mcp_connections()
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "jira-conn"


class TestModelEndpointDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_model_endpoints_excludes_agents(self, mock_client_fn):
        from src.api.routes.tools import _discover_model_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client
        mock_foundation = MagicMock()
        mock_foundation.name = "claude-sonnet"
        mock_foundation.task = "llm/v1/chat"
        mock_foundation.description = "Claude model"
        mock_agent = MagicMock()
        mock_agent.name = "hr-bot"
        mock_agent.task = "agent/langchain"
        mock_agent.description = "HR agent"
        mock_custom = MagicMock()
        mock_custom.name = "fraud-model"
        mock_custom.task = "custom/inference"
        mock_custom.description = "Fraud detection"
        mock_client.serving_endpoints.list.return_value = [
            mock_foundation,
            mock_agent,
            mock_custom,
        ]
        result = _discover_model_endpoints()
        names = [item["name"] for item in result["items"]]
        assert "claude-sonnet" in names
        assert "fraud-model" in names
        assert "hr-bot" not in names

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_model_endpoints_detects_foundation(self, mock_client_fn):
        from src.api.routes.tools import _discover_model_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_foundation = MagicMock()
        mock_foundation.name = "claude-sonnet"
        mock_foundation.task = "llm/v1/chat"
        mock_foundation.description = "Claude model"

        mock_custom = MagicMock()
        mock_custom.name = "fraud-model"
        mock_custom.task = "custom/inference"
        mock_custom.description = "Fraud detection"

        mock_client.serving_endpoints.list.return_value = [
            mock_foundation,
            mock_custom,
        ]
        result = _discover_model_endpoints()
        foundation_item = next(
            i for i in result["items"] if i["name"] == "claude-sonnet"
        )
        custom_item = next(
            i for i in result["items"] if i["name"] == "fraud-model"
        )
        assert foundation_item["metadata"]["endpoint_type"] == "foundation"
        assert custom_item["metadata"]["endpoint_type"] == "custom"

    @patch("src.api.routes.tools.get_user_client")
    def test_discover_model_endpoints_excludes_embeddings(self, mock_client_fn):
        from src.api.routes.tools import _discover_model_endpoints

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.name = "embedding-model"
        mock_embedding.task = "llm/v1/embeddings"
        mock_embedding.description = "Embedding model"

        mock_chat = MagicMock()
        mock_chat.name = "claude-sonnet"
        mock_chat.task = "llm/v1/chat"
        mock_chat.description = "Chat model"

        mock_completions = MagicMock()
        mock_completions.name = "codegen"
        mock_completions.task = "llm/v1/completions"
        mock_completions.description = "Code gen"

        mock_client.serving_endpoints.list.return_value = [
            mock_embedding,
            mock_chat,
            mock_completions,
        ]
        result = _discover_model_endpoints()
        names = [item["name"] for item in result["items"]]
        assert "embedding-model" not in names  # Excluded
        assert "claude-sonnet" in names  # Foundation
        assert "codegen" in names  # Foundation
        # Verify both are classified as foundation
        for item in result["items"]:
            assert item["metadata"]["endpoint_type"] == "foundation"


class TestAgentBricksDiscovery:
    @patch("src.api.routes.tools.get_user_client")
    def test_discover_agent_bricks_only_agents(self, mock_client_fn):
        from src.api.routes.tools import _discover_agent_bricks

        mock_client = _make_client()
        mock_client_fn.return_value = mock_client
        mock_foundation = MagicMock()
        mock_foundation.name = "claude-sonnet"
        mock_foundation.task = "llm/v1/chat"
        mock_agent = MagicMock()
        mock_agent.name = "hr-bot"
        mock_agent.task = "agent/langchain"
        mock_agent.description = "HR agent"
        mock_client.serving_endpoints.list.return_value = [
            mock_foundation,
            mock_agent,
        ]
        result = _discover_agent_bricks()
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "hr-bot"
        assert result["items"][0]["metadata"]["task"] == "agent/langchain"


class TestDiscoveryErrorHandling:
    """All discovery endpoints must return empty items on SDK failure."""

    @patch("src.api.routes.tools.get_user_client")
    def test_genie_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_genie_spaces

        mock_client_fn.return_value.genie.list_spaces.side_effect = Exception(
            "Auth failed"
        )
        result = _discover_genie_spaces()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_vector_discovery_returns_empty_on_error(self, mock_client_fn):
        import src.api.routes.tools as tools_mod
        tools_mod._vector_endpoints_cache = None
        tools_mod._vector_endpoints_cache_time = 0

        from src.api.routes.tools import _discover_vector_endpoints

        mock_client_fn.return_value.vector_search_endpoints.list_endpoints.side_effect = (
            Exception("No access")
        )
        result = _discover_vector_endpoints()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_vector_indexes_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_vector_indexes

        mock_client_fn.return_value.vector_search_indexes.list_indexes.side_effect = (
            Exception("Not found")
        )
        result = _discover_vector_indexes("some-endpoint")
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_vector_columns_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_vector_columns

        mock_client_fn.return_value.vector_search_indexes.get_index.side_effect = (
            Exception("Not found")
        )
        result = _discover_vector_columns("some-endpoint", "some-index")
        assert result["columns"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_mcp_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_mcp_connections

        mock_client_fn.return_value.connections.list.side_effect = Exception(
            "Not configured"
        )
        result = _discover_mcp_connections()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_model_endpoint_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_model_endpoints

        mock_client_fn.return_value.serving_endpoints.list.side_effect = Exception(
            "Timeout"
        )
        result = _discover_model_endpoints()
        assert result["items"] == []

    @patch("src.api.routes.tools.get_user_client")
    def test_agent_bricks_discovery_returns_empty_on_error(self, mock_client_fn):
        from src.api.routes.tools import _discover_agent_bricks

        mock_client_fn.return_value.serving_endpoints.list.side_effect = Exception(
            "Timeout"
        )
        result = _discover_agent_bricks()
        assert result["items"] == []

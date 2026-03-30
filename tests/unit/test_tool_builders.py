"""Tests for tool builder functions.

Verifies that each builder produces a valid LangChain StructuredTool with
correct naming, descriptions, and index-based suffixes.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestBuildVectorTool:
    """Tests for build_vector_tool."""

    @patch("src.services.tools.vector_tool.get_user_client")
    def test_build_returns_structured_tool(self, mock_client_fn):
        from src.api.schemas.agent_config import VectorIndexTool
        from src.services.tools.vector_tool import build_vector_tool

        config = VectorIndexTool(
            type="vector_index",
            endpoint_name="ep",
            index_name="idx",
            description="Product docs",
            columns=["title", "content"],
        )
        tool = build_vector_tool(config, index=1)
        assert tool.name == "search_vector_index"
        assert "Product docs" in tool.description

    def test_build_second_tool_has_index_suffix(self):
        from src.api.schemas.agent_config import VectorIndexTool
        from src.services.tools.vector_tool import build_vector_tool

        config = VectorIndexTool(
            type="vector_index",
            endpoint_name="ep",
            index_name="idx",
        )
        tool = build_vector_tool(config, index=2)
        assert tool.name == "search_vector_index_2"

    def test_default_description_includes_index_name(self):
        from src.api.schemas.agent_config import VectorIndexTool
        from src.services.tools.vector_tool import build_vector_tool

        config = VectorIndexTool(
            type="vector_index",
            endpoint_name="ep",
            index_name="catalog.schema.my_index",
        )
        tool = build_vector_tool(config, index=1)
        assert "catalog.schema.my_index" in tool.description


class TestBuildModelEndpointTool:
    """Tests for build_model_endpoint_tool."""

    def test_build_returns_structured_tool(self):
        from src.api.schemas.agent_config import ModelEndpointTool
        from src.services.tools.model_endpoint_tool import build_model_endpoint_tool

        config = ModelEndpointTool(
            type="model_endpoint",
            endpoint_name="my-llm",
            description="Foundation model",
        )
        tool = build_model_endpoint_tool(config, index=1)
        assert tool.name == "query_model_endpoint"
        assert "Foundation model" in tool.description

    def test_build_second_tool_has_index_suffix(self):
        from src.api.schemas.agent_config import ModelEndpointTool
        from src.services.tools.model_endpoint_tool import build_model_endpoint_tool

        config = ModelEndpointTool(
            type="model_endpoint",
            endpoint_name="my-llm",
        )
        tool = build_model_endpoint_tool(config, index=2)
        assert tool.name == "query_model_endpoint_2"

    def test_default_description_includes_endpoint_name(self):
        from src.api.schemas.agent_config import ModelEndpointTool
        from src.services.tools.model_endpoint_tool import build_model_endpoint_tool

        config = ModelEndpointTool(
            type="model_endpoint",
            endpoint_name="my-custom-llm",
        )
        tool = build_model_endpoint_tool(config, index=1)
        assert "my-custom-llm" in tool.description


class TestBuildAgentBricksTool:
    """Tests for build_agent_bricks_tool."""

    def test_build_returns_structured_tool(self):
        from src.api.schemas.agent_config import AgentBricksTool
        from src.services.tools.agent_bricks_tool import build_agent_bricks_tool

        config = AgentBricksTool(
            type="agent_bricks",
            endpoint_name="hr-bot",
            description="HR knowledge assistant",
        )
        tool = build_agent_bricks_tool(config, index=1)
        assert tool.name == "query_agent"
        assert "HR knowledge assistant" in tool.description

    def test_build_second_tool_has_index_suffix(self):
        from src.api.schemas.agent_config import AgentBricksTool
        from src.services.tools.agent_bricks_tool import build_agent_bricks_tool

        config = AgentBricksTool(
            type="agent_bricks",
            endpoint_name="hr-bot",
        )
        tool = build_agent_bricks_tool(config, index=2)
        assert tool.name == "query_agent_2"

    def test_default_description_includes_endpoint_name(self):
        from src.api.schemas.agent_config import AgentBricksTool
        from src.services.tools.agent_bricks_tool import build_agent_bricks_tool

        config = AgentBricksTool(
            type="agent_bricks",
            endpoint_name="sales-assistant",
        )
        tool = build_agent_bricks_tool(config, index=1)
        assert "sales-assistant" in tool.description


class TestBuildMCPTools:
    """Tests for build_mcp_tools."""

    @patch("src.services.tools.mcp_tool.list_mcp_tools")
    def test_build_returns_list_of_tools(self, mock_list):
        from src.api.schemas.agent_config import MCPTool
        from src.services.tools.mcp_tool import build_mcp_tools

        mock_list.return_value = [
            {
                "name": "search",
                "description": "Search",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"],
                },
            },
        ]
        config = MCPTool(type="mcp", connection_name="jira", server_name="Jira")
        tools = build_mcp_tools(config)
        assert isinstance(tools, list)
        assert len(tools) >= 1
        assert "jira" in tools[0].name

    @patch("src.services.tools.mcp_tool.list_mcp_tools")
    def test_build_multiple_discovered_tools(self, mock_list):
        from src.api.schemas.agent_config import MCPTool
        from src.services.tools.mcp_tool import build_mcp_tools

        mock_list.return_value = [
            {
                "name": "search_issues",
                "description": "Search JIRA issues",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "jql": {"type": "string", "description": "JQL query"}
                    },
                    "required": ["jql"],
                },
            },
            {
                "name": "get_issue",
                "description": "Get a JIRA issue",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "issue_key": {"type": "string", "description": "Issue key"}
                    },
                    "required": ["issue_key"],
                },
            },
        ]
        config = MCPTool(type="mcp", connection_name="jira", server_name="Jira")
        tools = build_mcp_tools(config)
        assert len(tools) == 2
        assert tools[0].name == "mcp_jira_search_issues"
        assert tools[1].name == "mcp_jira_get_issue"

    @patch("src.services.tools.mcp_tool.list_mcp_tools")
    def test_build_falls_back_to_generic_when_no_discovery(self, mock_list):
        from src.api.schemas.agent_config import MCPTool
        from src.services.tools.mcp_tool import build_mcp_tools

        mock_list.return_value = []
        config = MCPTool(
            type="mcp",
            connection_name="tavily",
            server_name="Tavily",
            description="Web search",
        )
        tools = build_mcp_tools(config)
        assert len(tools) == 1
        assert "tavily" in tools[0].name
        assert "search" in tools[0].name


class TestModelEndpointResponseExtractors:
    """Tests for response extraction helper functions."""

    def test_extract_agent_response(self):
        from src.services.tools.model_endpoint_tool import _extract_agent_response

        result = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Hello from agent"}
                    ],
                }
            ]
        }
        assert _extract_agent_response(result) == "Hello from agent"

    def test_extract_agent_response_string_output(self):
        from src.services.tools.model_endpoint_tool import _extract_agent_response

        result = {"output": "Simple string response"}
        assert _extract_agent_response(result) == "Simple string response"

    def test_extract_agent_response_empty(self):
        from src.services.tools.model_endpoint_tool import _extract_agent_response

        assert _extract_agent_response({}) == ""
        assert _extract_agent_response({"output": []}) == ""

    def test_extract_foundation_response(self):
        from src.services.tools.model_endpoint_tool import _extract_foundation_response

        result = {
            "choices": [
                {"message": {"content": "Hello from foundation model"}}
            ]
        }
        assert _extract_foundation_response(result) == "Hello from foundation model"

    def test_extract_foundation_response_empty(self):
        from src.services.tools.model_endpoint_tool import _extract_foundation_response

        assert _extract_foundation_response({}) == ""
        assert _extract_foundation_response({"choices": []}) == ""


class TestAgentBricksResponseExtractor:
    """Tests for agent bricks response extraction."""

    def test_extract_agent_response(self):
        from src.services.tools.agent_bricks_tool import _extract_agent_response

        result = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Answer from the agent"}
                    ],
                }
            ]
        }
        assert _extract_agent_response(result) == "Answer from the agent"

    def test_extract_agent_response_string_output(self):
        from src.services.tools.agent_bricks_tool import _extract_agent_response

        result = {"output": "Simple response"}
        assert _extract_agent_response(result) == "Simple response"

    def test_extract_agent_response_fallback_to_json(self):
        from src.services.tools.agent_bricks_tool import _extract_agent_response
        import json

        result = {"unexpected": "format"}
        extracted = _extract_agent_response(result)
        # Should fall back to JSON representation
        assert "unexpected" in extracted


class TestEndpointTypeDetection:
    """Tests for model endpoint type detection and caching."""

    def test_detect_agent_type(self):
        from src.services.tools.model_endpoint_tool import (
            _detect_endpoint_type,
            _endpoint_type_cache,
            ENDPOINT_TYPE_AGENT,
        )

        # Clear cache
        _endpoint_type_cache.clear()

        mock_client = MagicMock()
        mock_ep = MagicMock()
        mock_ep.as_dict.return_value = {"task": "agent/chat"}
        mock_client.serving_endpoints.get.return_value = mock_ep

        result = _detect_endpoint_type(mock_client, "test-agent")
        assert result == ENDPOINT_TYPE_AGENT

    def test_detect_foundation_type(self):
        from src.services.tools.model_endpoint_tool import (
            _detect_endpoint_type,
            _endpoint_type_cache,
            ENDPOINT_TYPE_FOUNDATION,
        )

        _endpoint_type_cache.clear()

        mock_client = MagicMock()
        mock_ep = MagicMock()
        mock_ep.as_dict.return_value = {"task": "llm/v1/chat"}
        mock_client.serving_endpoints.get.return_value = mock_ep

        result = _detect_endpoint_type(mock_client, "test-foundation")
        assert result == ENDPOINT_TYPE_FOUNDATION

    def test_detect_custom_ml_type(self):
        from src.services.tools.model_endpoint_tool import (
            _detect_endpoint_type,
            _endpoint_type_cache,
            ENDPOINT_TYPE_CUSTOM_ML,
        )

        _endpoint_type_cache.clear()

        mock_client = MagicMock()
        mock_ep = MagicMock()
        mock_ep.as_dict.return_value = {"task": ""}
        mock_client.serving_endpoints.get.return_value = mock_ep

        result = _detect_endpoint_type(mock_client, "test-custom")
        assert result == ENDPOINT_TYPE_CUSTOM_ML

    def test_detection_uses_cache(self):
        from src.services.tools.model_endpoint_tool import (
            _detect_endpoint_type,
            _endpoint_type_cache,
            ENDPOINT_TYPE_AGENT,
        )
        import time

        _endpoint_type_cache.clear()
        _endpoint_type_cache["cached-ep"] = (ENDPOINT_TYPE_AGENT, time.monotonic())

        mock_client = MagicMock()
        result = _detect_endpoint_type(mock_client, "cached-ep")
        assert result == ENDPOINT_TYPE_AGENT
        # Should NOT have called the API
        mock_client.serving_endpoints.get.assert_not_called()

    def test_detection_returns_none_on_failure(self):
        from src.services.tools.model_endpoint_tool import (
            _detect_endpoint_type,
            _endpoint_type_cache,
        )

        _endpoint_type_cache.clear()

        mock_client = MagicMock()
        mock_client.serving_endpoints.get.side_effect = Exception("API error")

        result = _detect_endpoint_type(mock_client, "broken-ep")
        assert result is None

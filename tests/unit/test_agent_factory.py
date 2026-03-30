"""Tests for agent_factory: per-request agent construction from AgentConfig."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def default_prompts():
    """Standard prompt dict returned by mocked _get_prompt_content."""
    return {
        "system_prompt": "default prompt",
        "slide_editing_instructions": "default editing",
        "deck_prompt": None,
        "slide_style": "default style",
        "image_guidelines": None,
    }


def test_build_agent_with_no_tools(default_prompts):
    """Default config produces agent with search_images only (no Genie)."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig()
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
         patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = default_prompts
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = build_agent_for_request(config, session_data)

    assert agent is not None
    tool_names = [t.name for t in agent.tools]
    assert "search_images" in tool_names
    assert "query_genie_space" not in tool_names


def test_build_agent_with_genie_tool(default_prompts):
    """Config with Genie tool produces agent with query_genie_space."""
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(tools=[
        GenieTool(type="genie", space_id="abc", space_name="Sales")
    ])
    session_data = {"session_id": "test-123", "genie_conversation_id": "conv-456"}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
         patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = default_prompts
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = build_agent_for_request(config, session_data)

    tool_names = [t.name for t in agent.tools]
    assert "query_genie_space" in tool_names
    assert "search_images" in tool_names


def test_custom_system_prompt_overrides_default(default_prompts):
    """Custom system_prompt in config overrides the backend default."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(system_prompt="You are a custom assistant")
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
         patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        mock_model.return_value = MagicMock()
        # The factory should pass the custom prompt through to the agent
        custom_prompts = {**default_prompts, "system_prompt": "You are a custom assistant"}
        mock_prompts.return_value = custom_prompts
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = build_agent_for_request(config, session_data)

    assert agent.system_prompt == "You are a custom assistant"


def test_custom_editing_instructions_override(default_prompts):
    """Custom slide_editing_instructions in config overrides the default."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(slide_editing_instructions="Custom editing rules")
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
         patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        mock_model.return_value = MagicMock()
        custom_prompts = {
            **default_prompts,
            "slide_editing_instructions": "Custom editing rules",
        }
        mock_prompts.return_value = custom_prompts
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = build_agent_for_request(config, session_data)

    # The pre_built_prompts should contain the custom editing instructions
    assert agent._pre_built_prompts["slide_editing_instructions"] == "Custom editing rules"


def test_mcp_tool_builds_tools(default_prompts):
    """MCPTool entries now call build_mcp_tools and add tools to the agent."""
    from src.api.schemas.agent_config import AgentConfig, MCPTool
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(tools=[
        MCPTool(type="mcp", connection_name="my-mcp-conn", server_name="MyMCP")
    ])
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    mock_mcp_tool = MagicMock()
    mock_mcp_tool.name = "mcp_my_mcp_conn_search"

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
         patch("src.services.agent_factory.build_mcp_tools") as mock_build_mcp, \
         patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = default_prompts
        mock_build_mcp.return_value = [mock_mcp_tool]
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = build_agent_for_request(config, session_data)

    # search_images + 1 MCP tool
    tool_names = [t.name for t in agent.tools]
    assert "search_images" in tool_names
    assert "mcp_my_mcp_conn_search" in tool_names
    assert len(tool_names) == 2
    mock_build_mcp.assert_called_once()


def test_get_prompt_content_uses_config_overrides():
    """_get_prompt_content prioritizes config values over defaults."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig(
        system_prompt="Custom system prompt",
        slide_editing_instructions="Custom editing",
    )

    result = _get_prompt_content(config)

    assert result["system_prompt"] == "Custom system prompt"
    assert result["slide_editing_instructions"] == "Custom editing"
    # Defaults should still be used for non-overridden fields
    assert result["slide_style"] is not None  # DEFAULT_SLIDE_STYLE
    assert result["deck_prompt"] is None  # No deck_prompt_id set


def test_get_prompt_content_uses_defaults_when_no_overrides():
    """_get_prompt_content returns backend defaults when config has no overrides."""
    from src.api.schemas.agent_config import AgentConfig
    from src.core.defaults import DEFAULT_CONFIG, DEFAULT_SLIDE_STYLE
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig()

    result = _get_prompt_content(config)

    assert result["system_prompt"] == DEFAULT_CONFIG["prompts"]["system_prompt"]
    assert result["slide_editing_instructions"] == DEFAULT_CONFIG["prompts"]["slide_editing_instructions"]
    assert result["slide_style"] == DEFAULT_SLIDE_STYLE
    assert result["deck_prompt"] is None


def test_get_prompt_content_resolves_slide_style_id():
    """_get_prompt_content fetches slide style from DB when slide_style_id is set."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig(slide_style_id=42)

    mock_style = MagicMock()
    mock_style.style_content = "Custom DB style"
    mock_style.image_guidelines = "Use logo.png"

    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_style

    with patch("src.core.database.get_db_session") as mock_get_db:
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = _get_prompt_content(config)

    assert result["slide_style"] == "Custom DB style"
    assert result["image_guidelines"] == "Use logo.png"


def test_get_prompt_content_resolves_deck_prompt_id():
    """_get_prompt_content fetches deck prompt from DB when deck_prompt_id is set."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig(deck_prompt_id=7)

    mock_prompt = MagicMock()
    mock_prompt.prompt_content = "Quarterly review deck template"

    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_prompt

    with patch("src.core.database.get_db_session") as mock_get_db:
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = _get_prompt_content(config)

    assert result["deck_prompt"] == "Quarterly review deck template"


def test_multiple_genie_tools(default_prompts):
    """Multiple Genie tools in config each produce a tool (though only last wins name)."""
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    from src.services.agent_factory import _build_tools

    config = AgentConfig(tools=[
        GenieTool(type="genie", space_id="abc", space_name="Sales"),
        GenieTool(type="genie", space_id="def", space_name="Marketing"),
    ])
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    tools = _build_tools(config, session_data)

    # search_images + 2 genie tools
    assert len(tools) == 3
    genie_tools = [t for t in tools if "query_genie_space" in t.name]
    assert len(genie_tools) == 2
    # Unique names
    assert genie_tools[0].name == "query_genie_space"
    assert genie_tools[1].name == "query_genie_space_2"


def test_backward_compatible_init():
    """SlideGeneratorAgent() with no args still works (backward compatibility)."""
    from src.services.agent import SlideGeneratorAgent

    with patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        settings_mock = MagicMock()
        settings_mock.prompts = {
            "system_prompt": "You are a test assistant.",
            "slide_style": "Default style",
            "slide_editing_instructions": "Edit slides.",
            "deck_prompt": "",
            "image_guidelines": "",
        }
        mock_settings.return_value = settings_mock
        mock_client.return_value = MagicMock()

        agent = SlideGeneratorAgent()

    assert agent._pre_built_model is None
    assert agent._pre_built_tools is None
    assert agent._pre_built_prompts is None
    assert agent.tools == []
    assert agent.system_prompt is None


class TestBuildToolsNewTypes:
    @patch("src.services.agent_factory.build_vector_tool")
    def test_build_tools_includes_vector(self, mock_build):
        from src.api.schemas.agent_config import AgentConfig, VectorIndexTool
        from src.services.agent_factory import _build_tools
        mock_tool = MagicMock()
        mock_tool.name = "search_vector_index"
        mock_build.return_value = mock_tool
        config = AgentConfig(tools=[
            VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx"),
        ])
        tools = _build_tools(config, {})
        assert any(t.name == "search_vector_index" for t in tools)
        mock_build.assert_called_once()

    @patch("src.services.agent_factory.build_model_endpoint_tool")
    def test_build_tools_includes_model_endpoint(self, mock_build):
        from src.api.schemas.agent_config import AgentConfig, ModelEndpointTool
        from src.services.agent_factory import _build_tools
        mock_tool = MagicMock()
        mock_tool.name = "query_model_endpoint"
        mock_build.return_value = mock_tool
        config = AgentConfig(tools=[
            ModelEndpointTool(type="model_endpoint", endpoint_name="llm"),
        ])
        tools = _build_tools(config, {})
        assert any(t.name == "query_model_endpoint" for t in tools)
        mock_build.assert_called_once()

    @patch("src.services.agent_factory.build_agent_bricks_tool")
    def test_build_tools_includes_agent_bricks(self, mock_build):
        from src.api.schemas.agent_config import AgentConfig, AgentBricksTool
        from src.services.agent_factory import _build_tools
        mock_tool = MagicMock()
        mock_tool.name = "query_agent"
        mock_build.return_value = mock_tool
        config = AgentConfig(tools=[
            AgentBricksTool(type="agent_bricks", endpoint_name="hr-bot"),
        ])
        tools = _build_tools(config, {})
        assert any(t.name == "query_agent" for t in tools)
        mock_build.assert_called_once()

    @patch("src.services.agent_factory.build_mcp_tools")
    def test_build_tools_includes_mcp(self, mock_build):
        from src.api.schemas.agent_config import AgentConfig, MCPTool
        from src.services.agent_factory import _build_tools
        mock_tool = MagicMock()
        mock_tool.name = "mcp_jira_search"
        mock_build.return_value = [mock_tool]  # MCP returns a list
        config = AgentConfig(tools=[
            MCPTool(type="mcp", connection_name="jira", server_name="Jira"),
        ])
        tools = _build_tools(config, {})
        assert any(t.name == "mcp_jira_search" for t in tools)
        mock_build.assert_called_once()

    @patch("src.services.agent_factory.build_agent_bricks_tool")
    @patch("src.services.agent_factory.build_model_endpoint_tool")
    @patch("src.services.agent_factory.build_vector_tool")
    @patch("src.services.agent_factory.build_mcp_tools")
    @patch("src.services.agent_factory.build_genie_tool")
    def test_build_tools_all_types_together(self, mock_genie, mock_mcp, mock_vector, mock_model, mock_agent):
        from src.api.schemas.agent_config import (
            AgentConfig, GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool,
        )
        from src.services.agent_factory import _build_tools

        mock_genie.return_value = MagicMock(name="query_genie_space")
        mock_mcp.return_value = [MagicMock(name="mcp_jira_search")]
        mock_vector.return_value = MagicMock(name="search_vector_index")
        mock_model.return_value = MagicMock(name="query_model_endpoint")
        mock_agent.return_value = MagicMock(name="query_agent")

        config = AgentConfig(tools=[
            GenieTool(type="genie", space_id="s1", space_name="Sales"),
            MCPTool(type="mcp", connection_name="jira", server_name="Jira"),
            VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx"),
            ModelEndpointTool(type="model_endpoint", endpoint_name="llm"),
            AgentBricksTool(type="agent_bricks", endpoint_name="hr-bot"),
        ])
        tools = _build_tools(config, {})
        # 1 image search + 5 tool types = 6
        assert len(tools) == 6

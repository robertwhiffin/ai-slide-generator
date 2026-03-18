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


def test_mcp_tool_logs_warning_and_skipped(default_prompts):
    """MCPTool entries are skipped with a warning (not yet supported)."""
    from src.api.schemas.agent_config import AgentConfig, MCPTool
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(tools=[
        MCPTool(type="mcp", server_uri="http://mcp.example.com", server_name="MyMCP")
    ])
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
         patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client, \
         patch("src.services.agent_factory.logger") as mock_logger:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = default_prompts
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = build_agent_for_request(config, session_data)

    # Only search_images, no MCP tool
    tool_names = [t.name for t in agent.tools]
    assert "search_images" in tool_names
    assert len(tool_names) == 1

    # Verify warning was logged
    mock_logger.warning.assert_any_call(
        "MCP tools not yet supported, skipping",
        extra={
            "server_uri": "http://mcp.example.com",
            "server_name": "MyMCP",
        },
    )


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
    genie_tools = [t for t in tools if t.name == "query_genie_space"]
    assert len(genie_tools) == 2


def test_backward_compatible_init():
    """SlideGeneratorAgent() with no args still works (backward compatibility)."""
    from src.services.agent import SlideGeneratorAgent

    with patch("src.services.agent.get_settings") as mock_settings, \
         patch("src.services.agent.get_databricks_client") as mock_client:
        mock_settings.return_value = MagicMock()
        mock_client.return_value = MagicMock()

        agent = SlideGeneratorAgent()

    assert agent._pre_built_model is None
    assert agent._pre_built_tools is None
    assert agent._pre_built_prompts is None
    assert agent.tools == []
    assert agent.system_prompt is None

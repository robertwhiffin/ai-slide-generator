"""Tests for agent_factory: per-request agent construction from AgentConfig."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def default_prompts():
    """Standard prompt dict returned by mocked _get_prompt_content.

    Uses pre_assembled=True to exercise the new modular path in
    _create_prompt.  Tests that need the legacy concatenation path
    should override pre_assembled to False and supply slide_style.
    """
    return {
        "system_prompt": "default prompt",
        "slide_editing_instructions": None,
        "deck_prompt": None,
        "slide_style": None,
        "image_guidelines": None,
        "pre_assembled": True,
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
    """Custom system_prompt in config triggers legacy path with pre_assembled=False."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig(
        system_prompt="Custom system prompt",
        slide_editing_instructions="Custom editing",
    )

    result = _get_prompt_content(config)

    assert result["system_prompt"] == "Custom system prompt"
    assert result["slide_editing_instructions"] == "Custom editing"
    assert result["pre_assembled"] is False
    assert result["slide_style"] is not None
    assert result["deck_prompt"] is None


def test_get_prompt_content_generate_mode_uses_modules():
    """Without custom overrides, generate mode produces a pre-assembled prompt
    that includes generation rules and excludes editing rules."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig()
    result = _get_prompt_content(config, mode="generate")

    assert result["pre_assembled"] is True
    assert "<!DOCTYPE html>" in result["system_prompt"]
    assert "SLIDE EDITING MODE" not in result["system_prompt"]
    # Other keys are None because everything is baked in
    assert result["slide_editing_instructions"] is None
    assert result["slide_style"] is None


def test_get_prompt_content_edit_mode_uses_modules():
    """Without custom overrides, edit mode produces a pre-assembled prompt
    that includes editing rules and excludes generation-only rules."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig()
    result = _get_prompt_content(config, mode="edit")

    assert result["pre_assembled"] is True
    assert "SLIDE EDITING MODE" in result["system_prompt"]
    # Generation-only output format should be absent
    assert "Start directly with: <!DOCTYPE html>" not in result["system_prompt"]
    assert "PRESENTATION_GUIDELINES" not in result["system_prompt"]
    assert result["slide_editing_instructions"] is None


def test_get_prompt_content_defaults_backward_compat():
    """Default generate mode still produces a usable prompt dict."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import _get_prompt_content

    config = AgentConfig()
    result = _get_prompt_content(config)

    assert result["pre_assembled"] is True
    assert len(result["system_prompt"]) > 100


def test_get_prompt_content_resolves_slide_style_id():
    """_get_prompt_content fetches slide style from DB and bakes it into
    the pre-assembled system prompt."""
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

    assert result["pre_assembled"] is True
    assert "Custom DB style" in result["system_prompt"]
    assert "Use logo.png" in result["system_prompt"]


def test_get_prompt_content_resolves_deck_prompt_id():
    """_get_prompt_content fetches deck prompt from DB and bakes it into
    the pre-assembled system prompt."""
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

    assert result["pre_assembled"] is True
    assert "Quarterly review deck template" in result["system_prompt"]


# ---------------------------------------------------------------------------
# Design System wiring (Phase 2): design_system_id resolves compiled_style_content
# through the SAME build_generation_system_prompt seam, with precedence
# design_system_id -> slide_style_id -> default. The legacy slide_style_id path
# must remain byte-for-byte unchanged when no design system is selected.
# ---------------------------------------------------------------------------


def _dispatching_db(*, design_system=None, slide_style=None, deck_prompt=None):
    """MagicMock DB whose query(Model).filter_by(...).first() dispatches by model.

    Lets a single test control what each of the DesignSystem / SlideStyleLibrary /
    SlideDeckPromptLibrary lookups returns, so precedence can be asserted.
    """
    from src.database.models import (
        DesignSystem,
        SlideDeckPromptLibrary,
        SlideStyleLibrary,
    )

    mapping = {
        DesignSystem: design_system,
        SlideStyleLibrary: slide_style,
        SlideDeckPromptLibrary: deck_prompt,
    }
    queried_models = []
    db = MagicMock()

    def _query(model):
        queried_models.append(model)
        q = MagicMock()
        q.filter_by.return_value.first.return_value = mapping.get(model)
        return q

    db.query.side_effect = _query
    db.queried_models = queried_models
    return db


def _run_with_db(config, db, mode="generate"):
    from src.services.agent_factory import _get_prompt_content

    with patch("src.core.database.get_db_session") as mock_get_db:
        mock_get_db.return_value.__enter__ = MagicMock(return_value=db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        return _get_prompt_content(config, mode=mode)


def test_design_system_id_resolves_compiled_style_content():
    """A selected design system's compiled_style_content reaches the pre-assembled
    system prompt via the existing seam."""
    from src.api.schemas.agent_config import AgentConfig

    config = AgentConfig(design_system_id=99)
    ds = MagicMock()
    ds.compiled_style_content = "ACME-DS-COMPILED :root { --brand-core-primary: #123456; }"
    db = _dispatching_db(design_system=ds)

    result = _run_with_db(config, db)

    assert result["pre_assembled"] is True
    assert "ACME-DS-COMPILED" in result["system_prompt"]
    assert "--brand-core-primary" in result["system_prompt"]


def test_design_system_id_resolves_in_edit_mode():
    """EDIT mode resolves a design system's compiled_style_content through the
    editing-prompt seam, exactly as generation does — so on-brand styling applies
    when refining an existing deck, not just when generating a new one."""
    from src.api.schemas.agent_config import AgentConfig

    config = AgentConfig(design_system_id=99)
    ds = MagicMock()
    ds.compiled_style_content = "ACME-DS-EDIT-MARKER :root { --brand-core-primary: #123456; }"
    db = _dispatching_db(design_system=ds)

    result = _run_with_db(config, db, mode="edit")

    assert result["pre_assembled"] is True
    assert "ACME-DS-EDIT-MARKER" in result["system_prompt"]


def test_design_system_takes_precedence_over_slide_style():
    """When both are set, the design system wins and the slide style is not used."""
    from src.api.schemas.agent_config import AgentConfig

    config = AgentConfig(design_system_id=99, slide_style_id=42)
    ds = MagicMock()
    ds.compiled_style_content = "DS-MARKER"
    style = MagicMock()
    style.style_content = "LEGACY-STYLE-MARKER"
    style.image_guidelines = None
    db = _dispatching_db(design_system=ds, slide_style=style)

    result = _run_with_db(config, db)

    assert "DS-MARKER" in result["system_prompt"]
    assert "LEGACY-STYLE-MARKER" not in result["system_prompt"]


def test_design_system_missing_falls_back_to_default():
    """A dangling design_system_id degrades to the default style, not a crash."""
    from src.api.schemas.agent_config import AgentConfig

    config = AgentConfig(design_system_id=99)
    db = _dispatching_db(design_system=None)

    result = _run_with_db(config, db)

    assert result["pre_assembled"] is True
    # DEFAULT_SLIDE_STYLE marker present.
    assert "Modern sans-serif font" in result["system_prompt"]


def test_design_system_empty_compiled_content_falls_back_to_default():
    """A design system with no compiled artifact yet also degrades to default."""
    from src.api.schemas.agent_config import AgentConfig

    config = AgentConfig(design_system_id=99)
    ds = MagicMock()
    ds.compiled_style_content = None
    db = _dispatching_db(design_system=ds)

    result = _run_with_db(config, db)

    assert "Modern sans-serif font" in result["system_prompt"]


def test_slide_style_path_injects_identically_when_no_design_system():
    """BACKWARD COMPAT: with only slide_style_id set, the resolved prompt is
    byte-identical to feeding style_content straight into the seam — the design
    system code path does not alter the legacy result at all."""
    from src.api.schemas.agent_config import AgentConfig
    from src.core.prompt_modules import build_generation_system_prompt

    config = AgentConfig(slide_style_id=42)
    style = MagicMock()
    style.style_content = "LEGACY-STYLE-MARKER"
    style.image_guidelines = "Use logo.png"
    db = _dispatching_db(slide_style=style)

    result = _run_with_db(config, db)

    expected = build_generation_system_prompt(
        slide_style="LEGACY-STYLE-MARKER",
        deck_prompt=None,
        image_guidelines="Use logo.png",
    )
    assert result["system_prompt"] == expected
    assert result["pre_assembled"] is True


def test_design_system_not_queried_when_unset():
    """BACKWARD COMPAT: with design_system_id unset, DesignSystem is never queried
    — the new branch cannot interfere with the legacy slide_style path."""
    from src.api.schemas.agent_config import AgentConfig
    from src.database.models import DesignSystem

    config = AgentConfig(slide_style_id=42)
    style = MagicMock()
    style.style_content = "LEGACY-STYLE-MARKER"
    style.image_guidelines = None
    db = _dispatching_db(slide_style=style)

    _run_with_db(config, db)

    assert DesignSystem not in db.queried_models


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


class TestBrandAssetToolRegistration:
    """Phase 2 reset: search_brand_assets is registered ONLY when a design system
    is selected, bound to config.design_system_id; search_images is unaffected."""

    def test_no_design_system_no_brand_asset_tool(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _build_tools

        names = [t.name for t in _build_tools(AgentConfig(), {})]
        assert "search_images" in names
        assert "search_brand_assets" not in names

    def test_design_system_set_adds_brand_asset_tool(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _build_tools

        names = [t.name for t in _build_tools(AgentConfig(design_system_id=7), {})]
        assert "search_images" in names
        assert "search_brand_assets" in names

    def test_brand_asset_tool_bound_to_design_system_id(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.services import agent_factory

        with patch("src.services.agent_factory.build_ds_asset_tool") as mock_build:
            marker = MagicMock()
            marker.name = "search_brand_assets"
            mock_build.return_value = marker
            tools = agent_factory._build_tools(AgentConfig(design_system_id=99), {})

        mock_build.assert_called_once_with(99)
        assert marker in tools

    def test_brand_asset_tool_not_built_without_design_system(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.services import agent_factory

        with patch("src.services.agent_factory.build_ds_asset_tool") as mock_build:
            agent_factory._build_tools(AgentConfig(), {})
        mock_build.assert_not_called()

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

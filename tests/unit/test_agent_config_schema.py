import pytest
from pydantic import ValidationError


def test_empty_config_is_valid():
    """Null/empty config means defaults."""
    from src.api.schemas.agent_config import AgentConfig
    config = AgentConfig()
    assert config.tools == []
    assert config.slide_style_id is None
    assert config.deck_prompt_id is None
    assert config.system_prompt is None
    assert config.slide_editing_instructions is None


def test_genie_tool_requires_space_id_and_name():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    with pytest.raises(ValidationError):
        GenieTool(type="genie")


def test_genie_tool_valid():
    from src.api.schemas.agent_config import GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales", description="Revenue data")
    assert tool.space_id == "abc"
    assert tool.type == "genie"


def test_mcp_tool_requires_server_uri_and_name():
    from src.api.schemas.agent_config import MCPTool
    with pytest.raises(ValidationError):
        MCPTool(type="mcp")


def test_mcp_tool_valid():
    from src.api.schemas.agent_config import MCPTool
    tool = MCPTool(type="mcp", server_uri="https://example.com", server_name="Search")
    assert tool.server_uri == "https://example.com"


def test_duplicate_genie_tools_rejected():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_mcp_tools_rejected():
    from src.api.schemas.agent_config import AgentConfig, MCPTool
    tool = MCPTool(type="mcp", server_uri="https://example.com", server_name="Search")
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_mixed_tools_no_duplicates():
    from src.api.schemas.agent_config import AgentConfig, GenieTool, MCPTool
    g = GenieTool(type="genie", space_id="abc", space_name="Sales")
    m = MCPTool(type="mcp", server_uri="https://example.com", server_name="Search")
    config = AgentConfig(tools=[g, m])
    assert len(config.tools) == 2


def test_system_prompt_must_be_nonempty_if_set():
    from src.api.schemas.agent_config import AgentConfig
    with pytest.raises(ValidationError):
        AgentConfig(system_prompt="")


def test_slide_editing_instructions_must_be_nonempty_if_set():
    from src.api.schemas.agent_config import AgentConfig
    with pytest.raises(ValidationError):
        AgentConfig(slide_editing_instructions="")


def test_config_serializes_to_dict():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
    config = AgentConfig(tools=[tool], slide_style_id=3, deck_prompt_id=7)
    d = config.model_dump()
    assert d["tools"][0]["type"] == "genie"
    assert d["slide_style_id"] == 3


def test_config_from_dict():
    from src.api.schemas.agent_config import AgentConfig
    data = {
        "tools": [{"type": "genie", "space_id": "abc", "space_name": "Sales"}],
        "slide_style_id": 3,
    }
    config = AgentConfig.model_validate(data)
    assert config.tools[0].space_id == "abc"


def test_config_from_none_returns_defaults():
    from src.api.schemas.agent_config import AgentConfig, resolve_agent_config
    config = resolve_agent_config(None)
    assert config.tools == []
    assert config.slide_style_id is None

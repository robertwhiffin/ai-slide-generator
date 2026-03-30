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


def test_mcp_tool_requires_connection_name_and_server_name():
    from src.api.schemas.agent_config import MCPTool
    with pytest.raises(ValidationError):
        MCPTool(type="mcp")


def test_mcp_tool_valid():
    from src.api.schemas.agent_config import MCPTool
    tool = MCPTool(type="mcp", connection_name="jira", server_name="Search")
    assert tool.connection_name == "jira"


def test_duplicate_genie_tools_rejected():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_mcp_tools_rejected():
    from src.api.schemas.agent_config import AgentConfig, MCPTool
    tool = MCPTool(type="mcp", connection_name="jira", server_name="Search")
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_mixed_tools_no_duplicates():
    from src.api.schemas.agent_config import AgentConfig, GenieTool, MCPTool
    g = GenieTool(type="genie", space_id="abc", space_name="Sales")
    m = MCPTool(type="mcp", connection_name="jira", server_name="Search")
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


# --- VectorIndexTool tests ---

def test_vector_index_tool_valid():
    from src.api.schemas.agent_config import VectorIndexTool
    tool = VectorIndexTool(
        type="vector_index",
        endpoint_name="my-endpoint",
        index_name="my-index",
        description="Product docs",
        columns=["title", "content"],
        num_results=5,
    )
    assert tool.endpoint_name == "my-endpoint"
    assert tool.index_name == "my-index"
    assert tool.columns == ["title", "content"]
    assert tool.num_results == 5


def test_vector_index_tool_requires_endpoint_and_index():
    from src.api.schemas.agent_config import VectorIndexTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VectorIndexTool(type="vector_index")


def test_vector_index_tool_defaults():
    from src.api.schemas.agent_config import VectorIndexTool
    tool = VectorIndexTool(
        type="vector_index",
        endpoint_name="ep",
        index_name="idx",
    )
    assert tool.columns is None
    assert tool.num_results == 5
    assert tool.description is None


# --- ModelEndpointTool tests ---

def test_model_endpoint_tool_valid():
    from src.api.schemas.agent_config import ModelEndpointTool
    tool = ModelEndpointTool(
        type="model_endpoint",
        endpoint_name="my-llm",
        endpoint_type="foundation",
        description="Claude model",
    )
    assert tool.endpoint_name == "my-llm"
    assert tool.endpoint_type == "foundation"


def test_model_endpoint_tool_requires_endpoint_name():
    from src.api.schemas.agent_config import ModelEndpointTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ModelEndpointTool(type="model_endpoint")


def test_model_endpoint_tool_defaults():
    from src.api.schemas.agent_config import ModelEndpointTool
    tool = ModelEndpointTool(type="model_endpoint", endpoint_name="ep")
    assert tool.endpoint_type is None
    assert tool.description is None


# --- AgentBricksTool tests ---

def test_agent_bricks_tool_valid():
    from src.api.schemas.agent_config import AgentBricksTool
    tool = AgentBricksTool(
        type="agent_bricks",
        endpoint_name="hr-knowledge-bot",
        description="HR assistant",
    )
    assert tool.endpoint_name == "hr-knowledge-bot"


def test_agent_bricks_tool_requires_endpoint_name():
    from src.api.schemas.agent_config import AgentBricksTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentBricksTool(type="agent_bricks")


# --- Updated MCPTool tests ---

def test_mcp_tool_connection_name_valid():
    from src.api.schemas.agent_config import MCPTool
    tool = MCPTool(type="mcp", connection_name="jira-conn", server_name="Jira")
    assert tool.connection_name == "jira-conn"
    assert tool.server_name == "Jira"


def test_mcp_tool_connection_name_required():
    from src.api.schemas.agent_config import MCPTool
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MCPTool(type="mcp", server_name="Jira")


# --- Mixed tool config tests ---

def test_config_with_all_tool_types():
    from src.api.schemas.agent_config import (
        AgentConfig, GenieTool, MCPTool,
        VectorIndexTool, ModelEndpointTool, AgentBricksTool,
    )
    config = AgentConfig(tools=[
        GenieTool(type="genie", space_id="s1", space_name="Sales"),
        MCPTool(type="mcp", connection_name="jira", server_name="Jira"),
        VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx"),
        ModelEndpointTool(type="model_endpoint", endpoint_name="llm"),
        AgentBricksTool(type="agent_bricks", endpoint_name="hr-bot"),
    ])
    assert len(config.tools) == 5


def test_duplicate_vector_index_rejected():
    from src.api.schemas.agent_config import AgentConfig, VectorIndexTool
    tool = VectorIndexTool(type="vector_index", endpoint_name="ep", index_name="idx")
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_model_endpoint_rejected():
    from src.api.schemas.agent_config import AgentConfig, ModelEndpointTool
    tool = ModelEndpointTool(type="model_endpoint", endpoint_name="llm")
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_agent_bricks_rejected():
    from src.api.schemas.agent_config import AgentConfig, AgentBricksTool
    tool = AgentBricksTool(type="agent_bricks", endpoint_name="bot")
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_resolve_agent_config_with_new_types():
    from src.api.schemas.agent_config import resolve_agent_config
    raw = {
        "tools": [
            {"type": "vector_index", "endpoint_name": "ep", "index_name": "idx"},
            {"type": "model_endpoint", "endpoint_name": "llm"},
            {"type": "agent_bricks", "endpoint_name": "bot"},
        ]
    }
    config = resolve_agent_config(raw)
    assert len(config.tools) == 3

from unittest.mock import patch

from src.services.tools.genie_tool import build_genie_tool
from src.api.schemas.agent_config import GenieTool


def test_factory_genie_tool_wraps_output():
    # NB: GenieTool is a discriminated-union model — `type` is required.
    cfg = GenieTool(type="genie", space_id="sp", space_name="Sales", conversation_id="c1")
    tool = build_genie_tool(cfg, {"session_id": "s1", "genie_conversation_id": "c1"}, index=1)
    with patch(
        "src.services.tools.genie_tool.query_genie_space",
        return_value={"message": "hi", "data": "1,2,3"},
    ):
        out = tool.func("show sales")
    assert out.startswith('<untrusted-data source="genie">')
    assert out.rstrip().endswith("</untrusted-data>")
    assert "1,2,3" in out


def test_factory_image_tool_wraps_output():
    from src.services.agent_factory import _build_tools
    from src.api.schemas.agent_config import AgentConfig

    tools = _build_tools(AgentConfig(), {"session_id": "s1"})
    image_tool = next(t for t in tools if t.name == "search_images")
    with patch(
        "src.services.agent_factory.search_images",
        return_value='{"images": []}',
    ):
        out = image_tool.func(query="logo")
    assert out.startswith('<untrusted-data source="image_search">')

import pytest
from pydantic import ValidationError


def test_empty_config_is_valid():
    """Null/empty config means defaults."""
    from src.api.schemas.agent_config import AgentConfig
    config = AgentConfig()
    assert config.tools == []
    assert config.slide_style_id is None
    assert config.deck_prompt_id is None
    assert config.design_system_id is None
    assert config.system_prompt is None
    assert config.slide_editing_instructions is None


def test_design_system_id_optional_field():
    """AgentConfig carries an optional design_system_id (Phase 2 wiring)."""
    from src.api.schemas.agent_config import AgentConfig, resolve_agent_config
    config = AgentConfig(design_system_id=5)
    assert config.design_system_id == 5
    # Round-trips through dict form used to persist config on sessions/profiles.
    assert config.model_dump()["design_system_id"] == 5
    assert resolve_agent_config({"design_system_id": 9}).design_system_id == 9


def test_template_id_optional_field():
    """AgentConfig carries an optional template_id pinning one of the selected
    design system's templates (Phase 4 wiring); default None = no-template."""
    from src.api.schemas.agent_config import AgentConfig, resolve_agent_config
    assert AgentConfig().template_id is None
    config = AgentConfig(design_system_id=5, template_id=7)
    assert config.template_id == 7
    # Round-trips through dict form used to persist config on sessions/profiles.
    assert config.model_dump()["template_id"] == 7
    assert resolve_agent_config({"design_system_id": 5, "template_id": 7}).template_id == 7
    # Pre-Phase-4 persisted configs lack the key entirely and must still parse.
    assert resolve_agent_config({"design_system_id": 5}).template_id is None


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


# ---------------------------------------------------------------------------
# style_source must FAIL SOFT (a stored config can never brick GET)
# ---------------------------------------------------------------------------
#
# ``style_source`` is a Literal["seeded", "user"], so an unexpected stored value
# raised ValidationError out of ``resolve_agent_config`` — which every config
# LOAD goes through. A single bad row (a hand-edited config, an older/newer
# writer, a partial migration) therefore made the session unloadable rather than
# merely mis-provenanced.
#
# Provenance is metadata ABOUT a choice, not the choice itself: when it cannot be
# read, the safe reading is "a user chose this", because that is the
# NON-OVERRIDING branch — it never silently substitutes the org default for
# something a person may have deliberately selected.


class TestMalformedStyleSourceFailsSoft:
    def test_bogus_string_is_treated_as_user_chosen(self):
        from src.api.schemas.agent_config import resolve_agent_config

        config = resolve_agent_config({"tools": [], "style_source": "bogus"})
        assert config.style_source == "user"

    def test_number_is_treated_as_user_chosen(self):
        from src.api.schemas.agent_config import resolve_agent_config

        assert resolve_agent_config({"tools": [], "style_source": 7}).style_source == "user"

    def test_explicit_null_is_preserved_as_absent_provenance(self):
        """``null`` is not malformed — it is the LEGACY shape (a config written
        before provenance existed) and must stay distinguishable, because Item 4
        gives an EXISTING stored config with no marker the user-chosen reading."""
        from src.api.schemas.agent_config import resolve_agent_config

        assert resolve_agent_config({"tools": [], "style_source": None}).style_source is None

    def test_missing_key_is_preserved_as_absent_provenance(self):
        from src.api.schemas.agent_config import resolve_agent_config

        assert resolve_agent_config({"tools": []}).style_source is None

    def test_malformed_value_never_raises_and_keeps_the_rest_of_the_config(self):
        """The whole point: loading must not fail, and no other field is lost."""
        from src.api.schemas.agent_config import resolve_agent_config

        config = resolve_agent_config(
            {
                "tools": [],
                "style_source": ["unexpected", "list"],
                "design_system_id": 7,
                "slide_style_id": 3,
                "deck_prompt_id": 9,
                "system_prompt": "synthetic",
            }
        )
        assert config.style_source == "user"
        assert config.design_system_id == 7
        assert config.slide_style_id == 3
        assert config.deck_prompt_id == 9
        assert config.system_prompt == "synthetic"

    def test_malformed_value_logs_a_warning(self, caplog):
        """Silently rewriting provenance would hide a data problem, so the
        coercion is observable."""
        import logging

        from src.api.schemas.agent_config import resolve_agent_config

        with caplog.at_level(logging.WARNING, logger="src.api.schemas.agent_config"):
            resolve_agent_config({"tools": [], "style_source": "bogus"})

        messages = [record.getMessage() for record in caplog.records]
        assert any("style_source" in message for message in messages), (
            f"no warning mentioned style_source: {messages}"
        )

    def test_a_valid_provenance_value_is_untouched(self):
        from src.api.schemas.agent_config import resolve_agent_config

        for valid in ("seeded", "user"):
            assert resolve_agent_config(
                {"tools": [], "style_source": valid}
            ).style_source == valid

    def test_strict_validation_still_applies_to_direct_construction(self):
        """The leniency belongs to READING STORED data. Constructing an
        AgentConfig with a bogus provenance is a programming error and still
        raises, so the type stays meaningful in code."""
        import pytest as _pytest
        from pydantic import ValidationError

        from src.api.schemas.agent_config import AgentConfig

        with _pytest.raises(ValidationError):
            AgentConfig(style_source="bogus")


# ---------------------------------------------------------------------------
# Style-source exclusivity is enforced SERVER-side (write path)
# ---------------------------------------------------------------------------
#
# Round 2 review: exclusivity was frontend-only, so an API or MCP caller could
# persist BOTH slide_style_id and design_system_id (PUT answered 200) and
# generation silently applied design-system precedence. Now that MCP sets
# design_system_id, that is a real path.
#
# CONTRACT CHOSEN: deterministic NORMALISATION to design-system-wins with a
# warning, NOT a 422. Reasoning:
#   * It matches what generation has always done (agent_factory resolves the
#     design system first), so nothing about the rendered deck changes — the
#     stored row simply stops disagreeing with the behaviour.
#   * A 422 would WEDGE the legacy rows this must not break: the frontend PUTs
#     the WHOLE config, so a user sitting on a stored both-set row who changed
#     only their deck prompt would get 422 on every save — precisely the
#     dangling-design-system bug fixed one round earlier, reintroduced.
#   * The precedence is already the documented product rule, so silently
#     honouring it is not inventing policy.
# Normalisation is WRITE-side only; reads of legacy rows keep both values.


class TestStyleSourceExclusivityOnWrite:
    def test_both_set_normalises_to_design_system_wins(self):
        from src.api.schemas.agent_config import (
            AgentConfig,
            normalize_style_source_exclusivity,
        )

        config = AgentConfig(slide_style_id=42, design_system_id=7)
        assert normalize_style_source_exclusivity(config) is True
        assert config.design_system_id == 7
        assert config.slide_style_id is None, (
            "the slide style must be dropped so the prompt carries ONE authority"
        )

    def test_normalisation_logs_a_warning(self, caplog):
        import logging

        from src.api.schemas.agent_config import (
            AgentConfig,
            normalize_style_source_exclusivity,
        )

        with caplog.at_level(logging.WARNING, logger="src.api.schemas.agent_config"):
            normalize_style_source_exclusivity(
                AgentConfig(slide_style_id=42, design_system_id=7), session_id="sess-x"
            )

        messages = [r.getMessage() for r in caplog.records]
        assert any("slide_style_id" in m and "design_system_id" in m for m in messages), (
            f"the normalisation must be observable: {messages}"
        )
        assert any("sess-x" in m for m in messages)

    def test_either_alone_is_untouched(self):
        from src.api.schemas.agent_config import (
            AgentConfig,
            normalize_style_source_exclusivity,
        )

        style_only = AgentConfig(slide_style_id=42)
        assert normalize_style_source_exclusivity(style_only) is False
        assert style_only.slide_style_id == 42

        ds_only = AgentConfig(design_system_id=7)
        assert normalize_style_source_exclusivity(ds_only) is False
        assert ds_only.design_system_id == 7

    def test_neither_set_is_untouched(self):
        """"Neither" is a legitimate choice and must not be disturbed."""
        from src.api.schemas.agent_config import (
            AgentConfig,
            normalize_style_source_exclusivity,
        )

        config = AgentConfig()
        assert normalize_style_source_exclusivity(config) is False
        assert config.slide_style_id is None
        assert config.design_system_id is None

    def test_a_legacy_stored_row_with_both_still_loads_unchanged(self):
        """The hard requirement: reads must keep working AND must not rewrite the
        stored row. Normalisation is write-side only, so a legacy row still
        reports both values — which is what the config bar's precedence hint
        needs in order to explain itself."""
        from src.api.schemas.agent_config import resolve_agent_config

        config = resolve_agent_config(
            {"tools": [], "slide_style_id": 42, "design_system_id": 7}
        )
        assert config.design_system_id == 7
        assert config.slide_style_id == 42, (
            "a READ must not silently rewrite a legacy both-set row"
        )

    def test_normalisation_is_idempotent(self):
        from src.api.schemas.agent_config import (
            AgentConfig,
            normalize_style_source_exclusivity,
        )

        config = AgentConfig(slide_style_id=42, design_system_id=7)
        assert normalize_style_source_exclusivity(config) is True
        assert normalize_style_source_exclusivity(config) is False  # nothing left
        assert config.model_dump()["slide_style_id"] is None

"""Behavioral contract for the model-driven Graph Node runtime.

The expected prompts below reproduce the shipped pre-runtime assembly rules from
their independent code-owned inputs.  They deliberately do not call a production
prompt helper: the test must disagree if AgentRuntime changes ordering, separators,
serialization, model settings, or schema selection during the prefactor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, field_validator

import src.services.agent_runtime as runtime_module
from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills import load_skill
from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import (
    MODEL_DRIVEN_AGENT_KEYS,
    AgentAssemblyContext,
    AgentModelConfiguration,
    AgentRuntime,
    DatabricksModelAdapter,
    RunObservation,
    UnknownAgentKeyError,
)
from src.services.agent_runtime_identity import (
    RecordingAgentInvocationIdentitySink,
)
from src.services.agent_schema_registry import (
    AgentOutputValidationError,
    AgentSchemaRegistry,
    _canonical_digest,
    _schema_contract_material,
)
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS
from src.services.graph_definition_manifest import (
    AssemblyRulesV1,
    AssemblyRulesV2,
    ContentIdentity,
    CustomTextBlock,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.persisted_graph_release import (
    PersistedConfigurationUnavailableError,
    PinnedInvocationEndpointError,
    ResolvedDefinition,
)
from src.services.prompt_assembler import V2_PROTECTED_ASSEMBLY_IDENTITY
from tests.fixtures.deterministic_model_adapter import (
    FAKE_OUTPUTS,
    INVALID_OPTIONAL_FIELD,
    DeterministicFakeModelAdapter,
    fake_output,
)
from tests.fixtures.packaged_release_loader import packaged_v1_runtime
from tests.fixtures.tool_call_doubles import (
    no_tool_call_reply,
    replying,
    tool_call_reply,
)

EXPECTED_PROTECTED_PROMPT_DIGEST = (
    "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852"
)
EXPECTED_SCHEMA_DIGESTS = {
    "architect": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}


@dataclass(frozen=True)
class ModelCall:
    configuration: AgentModelConfiguration
    schema: type[BaseModel]
    prompt: str


class RecordingModelAdapter:
    """Adapter double that answers with an instance of the schema it is handed.

    This mirrors ``with_structured_output``: the provider result is an instance of
    the *composed* schema the runtime selected, so the double cannot accidentally
    prove that an unvalidated object is passed straight through.
    """

    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.calls: list[ModelCall] = []

    def invoke(
        self,
        *,
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        self.calls.append(ModelCall(configuration, schema, prompt))
        return schema.model_validate(self.values)


#: The one shared table (#267 Correction 26), not a local copy that could drift.
VALID_OUTPUT_VALUES = FAKE_OUTPUTS


def _output_for(agent_key: str) -> dict[str, Any]:
    return dict(VALID_OUTPUT_VALUES[agent_key])


def _assert_composed_schema(
    schema: type[BaseModel], agent_key: str, version: int
) -> None:
    """The adapter is bound to the registry's composed schema, not the canonical one."""
    canonical = OUTPUT_SCHEMAS[agent_key]
    assert schema is not canonical
    assert issubclass(schema, canonical)
    assert schema.model_config["extra"] == "forbid"
    # The model-facing tool is named after the model: it keeps the canonical name
    # (#264 I5), so the prompts' "Return an <CanonicalOutput>" still names it.
    assert schema.__name__ == canonical.__name__
    expected_optional = {"diagnostic_notes"} if version == 2 else set()
    assert set(schema.model_fields) == set(canonical.model_fields) | expected_optional


def _payload_for(agent_key: str) -> dict[str, Any]:
    return {"agent_key": agent_key, "sequence": 7, "optional": None}


def _expected_prompt(
    agent_key: str,
    payload: dict[str, Any],
    *,
    design_system_active: bool,
) -> str:
    parts = [load_skill(agent_key).instructions]
    if not design_system_active:
        parts.append(_SLIDE_FRAME_CONSTRAINTS)
    if design_system_active:
        parts.append(DESIGN_SYSTEM_PRECEDENCE)
    parts.append(json.dumps(payload, indent=2, default=str))
    return "\n\n".join(parts)


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
def test_every_model_driven_role_preserves_prompt_model_schema_and_output(agent_key):
    output = _output_for(agent_key)
    model = RecordingModelAdapter(output)
    runtime = packaged_v1_runtime(model_adapter=model)
    payload = _payload_for(agent_key)

    result = runtime.run(
        agent_key,
        1,
        payload,
        AgentAssemblyContext(design_system_active=False),
    )

    # The runtime exposes the ORIGINAL canonical output class to graph logic, not
    # the composed adapter subclass it bound the provider to.
    assert type(result.output) is OUTPUT_SCHEMAS[agent_key]
    assert result.output == OUTPUT_SCHEMAS[agent_key].model_validate(output)
    assert result.diagnostics.additional_fields == {}
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call.configuration == AgentModelConfiguration(
        endpoint_name="databricks-claude-opus-4-6",
        temperature=0.7,
        max_tokens=60000,
        top_p=0.95,
    )
    assert call.prompt == _expected_prompt(
        agent_key,
        payload,
        design_system_active=False,
    )
    _assert_composed_schema(call.schema, agent_key, 1)
    assert result.diagnostics.agent_key == agent_key
    assert result.diagnostics.assembled_prompt == call.prompt
    assert result.diagnostics.model_configuration == call.configuration
    assert result.diagnostics.protected_prompt.version == 1
    assert result.diagnostics.protected_prompt.digest == EXPECTED_PROTECTED_PROMPT_DIGEST
    assert result.diagnostics.schema_contract.agent_key == agent_key
    assert result.diagnostics.schema_contract.version == 1
    assert result.diagnostics.schema_contract.digest == EXPECTED_SCHEMA_DIGESTS[agent_key]
    assert result.diagnostics.latency_ms >= 0


def test_design_system_prompt_preserves_precedence_and_omits_frame_constraints():
    output = _output_for("builder")
    model = RecordingModelAdapter(output)
    runtime = packaged_v1_runtime(model_adapter=model)
    payload = {"position": 3}

    runtime.run(
        "builder",
        1,
        payload,
        AgentAssemblyContext(design_system_active=True),
    )

    assert model.calls[0].prompt == _expected_prompt(
        "builder",
        payload,
        design_system_active=True,
    )
    assert DESIGN_SYSTEM_PRECEDENCE in model.calls[0].prompt
    assert _SLIDE_FRAME_CONSTRAINTS not in model.calls[0].prompt


def test_build_reviewer_deck_brief_preserves_conditional_instruction_order():
    output = _output_for("build_reviewer")
    model = RecordingModelAdapter(output)
    runtime = packaged_v1_runtime(model_adapter=model)
    payload = {"position": 2, "deck_brief": {"argument": "Revenue compounds"}}

    runtime.run(
        "build_reviewer",
        1,
        payload,
        AgentAssemblyContext(design_system_active=False),
    )

    expected_instructions = "\n\n".join(
        [load_skill("build_reviewer").instructions, DECK_BRIEF_REVIEW]
    )
    expected = "\n\n".join(
        [
            expected_instructions,
            _SLIDE_FRAME_CONSTRAINTS,
            json.dumps(payload, indent=2, default=str),
        ]
    )
    assert model.calls[0].prompt == expected


def test_manifest_v1_contract_identities_match_stable_literals():
    definitions = {defn.agent_key: defn for defn in load_graph_v1_manifest().definitions}

    assert set(definitions) == set(EXPECTED_SCHEMA_DIGESTS)
    assert {defn.protected_assembly.digest for defn in definitions.values()} == {
        EXPECTED_PROTECTED_PROMPT_DIGEST
    }
    assert {
        key: defn.schema_contract.digest for key, defn in definitions.items()
    } == EXPECTED_SCHEMA_DIGESTS
    assert all(
        isinstance(defn.assembly_rules, AssemblyRulesV1)
        for defn in definitions.values()
    )


def test_schema_contract_identity_changes_when_validator_behavior_changes():
    """Two schemas with identical JSON Schema must not share a contract digest."""

    class PositiveContract(BaseModel):
        model_config = ConfigDict(title="ContractProbe")
        value: int

        @field_validator("value")
        @classmethod
        def _check_value(cls, value: int) -> int:
            if value <= 0:
                raise ValueError("value must be positive")
            return value

    class NegativeContract(BaseModel):
        model_config = ConfigDict(title="ContractProbe")
        value: int

        @field_validator("value")
        @classmethod
        def _check_value(cls, value: int) -> int:
            if value >= 0:
                raise ValueError("value must be negative")
            return value

    for schema in (PositiveContract, NegativeContract):
        schema.__qualname__ = "ContractProbe"

    assert PositiveContract.model_json_schema() == NegativeContract.model_json_schema()
    assert _canonical_digest(
        _schema_contract_material("probe", PositiveContract)
    ) != _canonical_digest(_schema_contract_material("probe", NegativeContract))


def test_schema_contract_identity_changes_with_validation_configuration():
    """Validation config is contract behavior even when JSON Schema is unchanged."""

    class CoercingContract(BaseModel):
        model_config = ConfigDict(title="ContractProbe", strict=False)
        value: int

    class StrictContract(BaseModel):
        model_config = ConfigDict(title="ContractProbe", strict=True)
        value: int

    for schema in (CoercingContract, StrictContract):
        schema.__qualname__ = "ContractProbe"

    assert CoercingContract.model_json_schema() == StrictContract.model_json_schema()
    assert CoercingContract.model_validate({"value": "1"}).value == 1
    with pytest.raises(ValueError):
        StrictContract.model_validate({"value": "1"})
    assert _canonical_digest(
        _schema_contract_material("probe", CoercingContract)
    ) != _canonical_digest(_schema_contract_material("probe", StrictContract))


@pytest.mark.parametrize("agent_key", ["foreman", "unknown", "Architect"])
def test_unknown_or_deterministic_role_fails_before_model_invocation(agent_key):
    model = RecordingModelAdapter(_output_for("architect"))
    runtime = packaged_v1_runtime(model_adapter=model)

    with pytest.raises(UnknownAgentKeyError, match=agent_key):
        runtime.run(agent_key, 1, {}, AgentAssemblyContext(False))

    assert model.calls == []


def test_unavailable_protected_bundle_fails_before_model_invocation():
    manifest = load_graph_v1_manifest()
    architect_content = next(d for d in manifest.definitions if d.agent_key == "architect")
    bad_protected = ContentIdentity(version=999, digest="0" * 64)
    unavailable = architect_content.model_copy(update={"protected_assembly": bad_protected})
    model = RecordingModelAdapter(_output_for("architect"))
    runtime = packaged_v1_runtime(
        model_adapter=model,
        content_overrides={"architect": unavailable},
    )

    with pytest.raises(PersistedConfigurationUnavailableError) as raised:
        runtime.run("architect", 1, {}, AgentAssemblyContext(False))

    assert raised.value.code == "protected_bundle_unavailable"
    assert model.calls == []


def test_incompatible_schema_contract_fails_before_model_invocation():
    manifest = load_graph_v1_manifest()
    architect_content = next(d for d in manifest.definitions if d.agent_key == "architect")
    builder_content = next(d for d in manifest.definitions if d.agent_key == "builder")
    incompatible = architect_content.model_copy(
        update={"schema_contract": builder_content.schema_contract}
    )
    model = RecordingModelAdapter(_output_for("architect"))
    runtime = packaged_v1_runtime(
        model_adapter=model,
        content_overrides={"architect": incompatible},
    )

    with pytest.raises(PersistedConfigurationUnavailableError) as raised:
        runtime.run("architect", 1, {}, AgentAssemblyContext(False))

    assert raised.value.code == "schema_contract_unavailable"
    assert model.calls == []


def test_databricks_model_adapter_never_binds_legacy_tool_grants():
    """The output schema is the ONLY tool bound (follow-up A): no legacy grant.

    ``data_analyst``'s ``TOOL_GRANTS`` (genie, vector_index) must stay inert:
    the one ``bind_tools`` call carries exactly the output schema, with
    ``tool_choice="auto"``, and nothing else.
    """
    output = _output_for("data_analyst")
    schema = OUTPUT_SCHEMAS["data_analyst"]
    structured_bindings: list[tuple[list[Any], dict[str, Any]]] = []
    prompts: list[str] = []

    def reply(prompt: str):
        prompts.append(prompt)
        return tool_call_reply(schema, output)

    class ChatModel:
        def bind_tools(self, tools, **kwargs):
            structured_bindings.append((list(tools), kwargs))
            return replying(reply)

        def with_structured_output(self, schema):  # pragma: no cover - failure path
            raise AssertionError("forced tool choice must not be bound")

    constructed: list[dict[str, Any]] = []

    def model_factory(**kwargs):
        constructed.append(kwargs)
        return ChatModel()

    adapter = DatabricksModelAdapter(
        model_factory=model_factory,
        client_factory=lambda: object(),
    )

    actual = adapter.invoke(
        agent_key="data_analyst",
        configuration=AgentModelConfiguration(
            endpoint_name="databricks-claude-opus-4-6",
            temperature=0.7,
            max_tokens=60000,
            top_p=0.95,
        ),
        schema=OUTPUT_SCHEMAS["data_analyst"],
        prompt="assembled prompt",
    )

    assert actual == schema.model_validate(output)
    assert structured_bindings == [([schema], {"tool_choice": "auto"})]
    assert prompts == ["assembled prompt"]
    # Sampling values are stored but never sent (follow-up A).
    assert constructed == [
        {
            "model": "databricks-claude-opus-4-6",
            "max_tokens": 60000,
            "workspace_client": constructed[0]["workspace_client"],
        }
    ]


def test_agent_runtime_is_the_only_prompt_and_model_invocation_owner():
    import src.core.skills as skills
    import src.services.agent_resolution as agent_resolution

    assert not hasattr(skills, "call_skill")
    assert not hasattr(skills, "_with_conditional_instructions")
    assert not hasattr(agent_resolution, "assemble_skill_prompt")
    assert not hasattr(agent_resolution, "get_structured_model")


def test_runtime_and_nodes_have_no_prompt_serialization_or_binding_bypass():
    import inspect

    import src.services.agent_runtime as agent_runtime
    import src.services.graph.nodes as nodes

    runtime_source = inspect.getsource(agent_runtime)
    node_source = inspect.getsource(nodes)
    assert "json.dumps(payload" not in runtime_source
    assert "json.dumps(payload" not in node_source
    assert runtime_source.count("with_structured_output(") == 0
    assert runtime_source.count(".bind_tools(") == 1
    assert "with_structured_output(" not in node_source
    assert ".bind_tools(" not in node_source


# ---------------------------------------------------------------------------
# Task 6: the deck-brief condition's negative case on the runtime path, and the
# scope guarantee Task 6's manual ``rg`` check asserts, made executable.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expects_deck_brief"),
    [
        ({"position": 2}, False),
        ({"position": 2, "deck_brief": None}, False),
        ({"position": 2, "deck_brief": ""}, False),
        ({"position": 2, "deck_brief": {}}, False),
        ({"position": 2, "deck_brief": {"argument": "Revenue compounds"}}, True),
    ],
)
def test_runtime_deck_brief_stage_tracks_payload_truthiness(payload, expects_deck_brief):
    """Catches an unconditional or key-presence-only deck-brief stage in the runtime.

    The positive case alone cannot see a condition forced true, so every falsey
    payload shape is asserted to omit the stage.
    """
    model = RecordingModelAdapter(_output_for("build_reviewer"))
    runtime = packaged_v1_runtime(model_adapter=model)

    runtime.run("build_reviewer", 1, payload, AgentAssemblyContext(design_system_active=False))

    prompt = model.calls[0].prompt
    assert (DECK_BRIEF_REVIEW in prompt) is expects_deck_brief
    assert prompt.count(DECK_BRIEF_REVIEW) == int(expects_deck_brief)
    if not expects_deck_brief:
        assert prompt == _expected_prompt("build_reviewer", payload, design_system_active=False)


@pytest.mark.parametrize("agent_key", ["architect", "data_analyst", "builder", "fixer"])
def test_non_build_reviewer_roles_never_render_the_deck_brief_stage(agent_key):
    """Catches a deck-brief stage that leaks onto a role whose rules never declare it."""
    model = RecordingModelAdapter(_output_for(agent_key))
    runtime = packaged_v1_runtime(model_adapter=model)

    runtime.run(
        agent_key,
        1,
        {"position": 2, "deck_brief": {"argument": "Revenue compounds"}},
        AgentAssemblyContext(design_system_active=False),
    )

    assert DECK_BRIEF_REVIEW not in model.calls[0].prompt


def test_prompt_assembler_is_the_only_payload_serializer_and_adapter_the_only_binder():
    """The executable form of Task 6's scope check over the three owning modules.

    Call sites are counted from the parsed AST rather than by substring, because
    the assembler also carries the serialization signature as *displayed* protected
    text: a textual count conflates the two and would go quiet if a real call site
    were added while a display literal was removed.
    """
    import ast
    import inspect

    import src.services.agent_runtime as agent_runtime
    import src.services.graph.nodes as nodes
    import src.services.prompt_assembler as prompt_assembler

    sources = {
        "agent_runtime": inspect.getsource(agent_runtime),
        "nodes": inspect.getsource(nodes),
        "prompt_assembler": inspect.getsource(prompt_assembler),
    }

    def payload_serializations(source: str) -> int:
        found = 0
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "dumps":
                continue
            owner = node.func.value
            if not isinstance(owner, ast.Name) or owner.id != "json":
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Name) and first.id == "payload":
                found += 1
        return found

    def structured_bindings(source: str) -> int:
        return sum(
            1
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"with_structured_output", "bind_tools"}
        )

    assert {name: payload_serializations(source) for name, source in sources.items()} == {
        "agent_runtime": 0,
        "nodes": 0,
        # Exactly one owned serialization per rules format version, and no more.
        "prompt_assembler": 2,
    }
    assert {name: structured_bindings(source) for name, source in sources.items()} == {
        "agent_runtime": 1,
        "nodes": 0,
        "prompt_assembler": 0,
    }

    # The same guarantee Task 6's ``rg`` check states, in its textual form: neither
    # the runtime nor the graph nodes mention either owned operation at all.
    for name in ("agent_runtime", "nodes"):
        assert "json.dumps(payload" not in sources[name]
    assert "with_structured_output(" not in sources["nodes"]
    assert "with_structured_output(" not in sources["prompt_assembler"]
    assert ".bind_tools(" not in sources["nodes"]
    assert ".bind_tools(" not in sources["prompt_assembler"]
    # The assembler still declares the binding as data, which is not a call site.
    assert 'langchain.with_structured_output"' in sources["prompt_assembler"]


def test_agent_runtime_construction_still_fails_closed_on_contract_material_drift(
    monkeypatch,
):
    """Correction 13: swapping the private v1-only registry keeps the check running.

    ``AgentRuntime.__init__`` used to construct a module-private v1-only registry
    (deleted with the compatibility runtime in #271), whose constructor re-derived
    and compared all seven v1 digests.  It now constructs the one public
    ``AgentSchemaRegistry``, which must still fail closed on material drift — and
    does so for v1 *and* v2 material.
    """
    from types import MappingProxyType

    import src.services.agent_schema_registry as registry_module
    from src.services.agent_schema_registry import SchemaContractMaterialChangedError

    drifted = dict(registry_module._V1_DIGESTS)
    drifted["architect"] = "0" * 64
    monkeypatch.setattr(registry_module, "_V1_DIGESTS", MappingProxyType(drifted))

    with pytest.raises(SchemaContractMaterialChangedError, match="architect"):
        packaged_v1_runtime(
            model_adapter=RecordingModelAdapter(_output_for("architect"))
        )


# ---------------------------------------------------------------------------
# #266 Task 5: one structured-output binding helper shared by the runtime
# adapter and the saved-candidate probe.  Recording factories only; no test
# here constructs a real client or reaches Databricks.
# ---------------------------------------------------------------------------


class _RecordingChatModel:
    """Records the one ``bind_tools`` binding, then answers with a tool call.

    ``output`` is the tool call's arguments (a mapping or a model instance); the
    reply goes through production's ``PydanticToolsParser`` like a provider's.
    """

    def __init__(self, events: list[tuple[str, Any]], output: Any) -> None:
        self._events = events
        self._output = output

    def bind_tools(self, tools, **kwargs):
        (schema,) = tools
        self._events.append(("bind_tools", schema, kwargs))

        def reply(prompt: str):
            self._events.append(("invoke", prompt))
            return tool_call_reply(schema, self._output)

        return replying(reply)

    def with_structured_output(self, schema):  # pragma: no cover - failure path
        raise AssertionError("forced tool choice must not be bound")


def _recording_factories(output: Any):
    events: list[tuple[str, Any]] = []
    runtime_client = object()

    def model_factory(**kwargs):
        events.append(("model_factory", kwargs))
        return _RecordingChatModel(events, output)

    def client_factory():
        events.append(("client_factory", None))
        return runtime_client

    return events, runtime_client, model_factory, client_factory


def _record_helper(monkeypatch) -> list[dict[str, Any]]:
    import src.services.agent_runtime as agent_runtime

    helper_calls: list[dict[str, Any]] = []
    original = agent_runtime.bind_structured_output_model

    def _recording_helper(**kwargs):
        helper_calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(agent_runtime, "bind_structured_output_model", _recording_helper)
    return helper_calls


_SAVED_CONFIGURATION = AgentModelConfiguration(
    endpoint_name="saved exact endpoint-name",
    temperature=0.25,
    max_tokens=321,
    top_p=0.75,
)


def test_structured_output_runtime_adapter_binds_through_the_extracted_helper(monkeypatch):
    """Catches the runtime adapter keeping a private binding beside the helper."""
    helper_calls = _record_helper(monkeypatch)
    output = _output_for("data_analyst")
    events, runtime_client, model_factory, client_factory = _recording_factories(output)
    adapter = DatabricksModelAdapter(model_factory=model_factory, client_factory=client_factory)

    actual = adapter.invoke(
        agent_key="data_analyst",
        configuration=_SAVED_CONFIGURATION,
        schema=OUTPUT_SCHEMAS["data_analyst"],
        prompt="assembled prompt",
    )

    assert actual == OUTPUT_SCHEMAS["data_analyst"].model_validate(output)
    assert len(helper_calls) == 1
    assert helper_calls[0]["configuration"] is _SAVED_CONFIGURATION
    assert helper_calls[0]["schema"] is OUTPUT_SCHEMAS["data_analyst"]
    # Follow-up A: no temperature / top_p sent; schema bound once, tool_choice auto.
    assert events == [
        ("client_factory", None),
        (
            "model_factory",
            {
                "model": "saved exact endpoint-name",
                "max_tokens": 321,
                "workspace_client": runtime_client,
            },
        ),
        ("bind_tools", OUTPUT_SCHEMAS["data_analyst"], {"tool_choice": "auto"}),
        ("invoke", "assembled prompt"),
    ]


def test_structured_output_runtime_and_model_endpoint_probe_share_one_helper(monkeypatch):
    """Catches the probe binding its own structured model instead of the runtime's.

    Both paths are driven with the same recording factories: each must pass the
    exact saved endpoint as ``model`` and the runtime-identity client as
    ``workspace_client``, and bind before invoking, through the one helper.
    """
    from src.services.model_endpoint_probe import (
        DatabricksStructuredOutputProbe,
        _StructuredOutputProbeResponse,
    )

    helper_calls = _record_helper(monkeypatch)
    runtime_output = _output_for("architect")
    runtime_events, runtime_client, runtime_factory, runtime_client_factory = (
        _recording_factories(runtime_output)
    )
    probe_events, probe_client, probe_factory, probe_client_factory = _recording_factories(
        _StructuredOutputProbeResponse(result="ok")
    )

    DatabricksModelAdapter(
        model_factory=runtime_factory, client_factory=runtime_client_factory
    ).invoke(
        agent_key="architect",
        configuration=_SAVED_CONFIGURATION,
        schema=OUTPUT_SCHEMAS["architect"],
        prompt="runtime prompt",
    )
    DatabricksStructuredOutputProbe(
        model_factory=probe_factory, client_factory=probe_client_factory
    ).probe(_SAVED_CONFIGURATION)

    assert [call["schema"] for call in helper_calls] == [
        OUTPUT_SCHEMAS["architect"],
        _StructuredOutputProbeResponse,
    ]
    assert [call["configuration"] for call in helper_calls] == [
        _SAVED_CONFIGURATION,
        _SAVED_CONFIGURATION,
    ]
    runtime_kwargs = runtime_events[1][1]
    probe_kwargs = probe_events[1][1]
    assert runtime_kwargs["workspace_client"] is runtime_client
    assert probe_kwargs["workspace_client"] is probe_client
    for kwargs in (runtime_kwargs, probe_kwargs):
        assert kwargs["model"] == "saved exact endpoint-name"
        assert kwargs["max_tokens"] == 321
        for sampling in ("temperature", "top_p", "top_k"):
            assert sampling not in kwargs
    assert [event[0] for event in probe_events] == [
        "client_factory",
        "model_factory",
        "bind_tools",
        "invoke",
    ]
    assert probe_events[2] == (
        "bind_tools",
        _StructuredOutputProbeResponse,
        {"tool_choice": "auto"},
    )


def test_structured_output_probe_defaults_are_the_runtime_adapters_factories():
    """Catches a second production model factory or client source for the probe."""
    from src.services.model_endpoint_probe import DatabricksStructuredOutputProbe

    probe = DatabricksStructuredOutputProbe()

    assert probe._model_factory is DatabricksModelAdapter._default_model_factory
    assert probe._client_factory is DatabricksModelAdapter._default_client_factory


def test_structured_output_binding_has_one_call_site_and_the_probe_has_none():
    """Extends the one-binding guard to the probe module (correction 11).

    The existing guards scan only the runtime, nodes and assembler, so a probe
    that bound ``with_structured_output`` itself would pass them unseen.
    """
    import ast
    import inspect

    import src.services.agent_runtime as agent_runtime
    import src.services.model_endpoint_probe as model_endpoint_probe

    def binding_calls(source: str, attr: str = "bind_tools") -> int:
        return sum(
            1
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        )

    runtime_source = inspect.getsource(agent_runtime)
    probe_source = inspect.getsource(model_endpoint_probe)
    helper_source = inspect.getsource(agent_runtime.bind_structured_output_model)
    assert binding_calls(runtime_source) == 1
    assert binding_calls(helper_source) == 1
    assert binding_calls(probe_source) == 0
    for source in (runtime_source, helper_source, probe_source):
        assert binding_calls(source, "with_structured_output") == 0
    assert "with_structured_output" not in probe_source
    assert "bind_tools" not in probe_source
    assert "ChatDatabricks" not in probe_source
    assert "agent_runtime.bind_structured_output_model(" in probe_source


def test_structured_output_saved_configuration_is_the_runtime_conversion():
    """Catches the probe and the runtime converting saved sampling values differently."""
    from decimal import Decimal

    from src.services.agent_runtime import saved_model_configuration
    from src.services.graph_definition_manifest import ModelConfiguration

    saved = ModelConfiguration(
        endpoint_name="exact saved name",
        temperature=Decimal("0.3"),
        max_tokens=77,
        top_p=Decimal("0.9"),
    )

    configuration = saved_model_configuration(saved)

    assert configuration == AgentModelConfiguration(
        endpoint_name="exact saved name", temperature=0.3, max_tokens=77, top_p=0.9
    )
    assert type(configuration.temperature) is float
    assert type(configuration.top_p) is float
    assert type(configuration.max_tokens) is int


def test_structured_output_runtime_adapter_still_collapses_permission_denied():
    """Catches the extraction changing the runtime's provider conversion.

    Only the probe classifies ``PermissionDenied`` separately; the runtime keeps
    mapping it, like every provider failure, to ``ModelProviderUnavailableError``.
    """
    from databricks.sdk.errors import PermissionDenied

    from src.services.agent_runtime import ModelProviderUnavailableError

    class DeniedChatModel:
        def bind_tools(self, tools, **kwargs):
            raise PermissionDenied("denied")

    adapter = DatabricksModelAdapter(
        model_factory=lambda **_kwargs: DeniedChatModel(),
        client_factory=lambda: object(),
    )

    with pytest.raises(ModelProviderUnavailableError):
        adapter.invoke(
            agent_key="architect",
            configuration=_SAVED_CONFIGURATION,
            schema=OUTPUT_SCHEMAS["architect"],
            prompt="p",
        )


# ---------------------------------------------------------------------------
# #267 Task 3: ``AgentRuntime.run_candidate`` runs a saved DRAFT candidate
# through the same private ``_run_resolved`` path as ``run`` (Corrections 12,
# 13, 14, 15, 27, 31, 33, 34).  New names are read off the module, so each test
# fails on its own while the feature is absent rather than collapsing the file.
# ---------------------------------------------------------------------------

_CANDIDATE_ENDPOINT = "databricks-claude-opus-4-6"


def _manifest_content(agent_key: str) -> DefinitionContent:
    return next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == agent_key
    )


def _candidate(agent_key: str, *, v2_assembly: bool = False, v2_schema: bool = False):
    """A saved-draft-shaped candidate: validated content that is no release's."""
    data = _manifest_content(agent_key).model_dump(mode="python")
    data["prompt_text"] = f"{agent_key} draft candidate prompt"
    if v2_assembly:
        data["protected_assembly"] = V2_PROTECTED_ASSEMBLY_IDENTITY.model_dump()
        data["assembly_rules"] = AssemblyRulesV2(
            format_version=2,
            custom_blocks=(
                CustomTextBlock.model_validate(
                    {
                        "kind": "custom_text",
                        "block_id": "00000000-0000-0000-0000-000000000267",
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": f"{agent_key} candidate custom block",
                    }
                ),
            ),
        ).model_dump(mode="python")
    if v2_schema:
        data["schema_contract"] = {
            "version": 2,
            "digest": AgentSchemaRegistry().identity_for(agent_key, 2).digest,
        }
        data["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": ["diagnostic_notes"],
        }
    content = DefinitionContent.model_validate(data)
    return content, definition_content_hash(content)


class _LoaderMustNotResolve:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        self.calls.append((graph_release_id, agent_key))
        raise AssertionError("a candidate run must never resolve a release")


class _StaticLoader:
    def __init__(self, definition: ResolvedDefinition) -> None:
        self.definition = definition
        self.calls: list[tuple[int, str]] = []

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        self.calls.append((graph_release_id, agent_key))
        return self.definition


def _candidate_runtime(adapter: Any = None):
    adapter = adapter if adapter is not None else DeterministicFakeModelAdapter()
    sink = RecordingAgentInvocationIdentitySink()
    loader = _LoaderMustNotResolve()
    runtime = AgentRuntime(
        persisted_release_loader=loader,
        model_adapter=adapter,
        identity_sink=sink,
    )
    return runtime, adapter, sink, loader


def test_candidate_run_sentinels_are_negative_runtime_identity_constants():
    """Correction 27: ``-1`` never collides with a SERIAL id; they live in the runtime."""
    import src.services.persisted_graph_release as persisted_graph_release

    assert runtime_module.CANDIDATE_RUN_GRAPH_VERSION == -1
    assert runtime_module.CANDIDATE_RUN_GRAPH_RELEASE_ID == -1
    assert runtime_module.CANDIDATE_RUN_REVISION_ID == -1
    assert not hasattr(persisted_graph_release, "CANDIDATE_RUN_GRAPH_RELEASE_ID")


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
def test_run_candidate_runs_every_role_through_the_fake_and_bypasses_the_identity_sink(
    agent_key,
):
    runtime, adapter, sink, loader = _candidate_runtime()
    content, candidate_hash = _candidate(agent_key)
    payload = {"z": 2, "a": 1}

    outcome = runtime.run_candidate(
        agent_key, content, candidate_hash, payload, AgentAssemblyContext(False)
    )

    assert outcome.status == "completed"
    assert outcome.error is None
    assert outcome.error_detail is None
    assert type(outcome.result.output) is OUTPUT_SCHEMAS[agent_key]
    assert outcome.result.output == OUTPUT_SCHEMAS[agent_key].model_validate(
        fake_output(agent_key)
    )
    # The raw keys the provider actually supplied, observed before validation.
    assert outcome.raw_output == fake_output(agent_key)
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call.agent_key == agent_key
    assert f"{agent_key} draft candidate prompt" in call.prompt
    _assert_composed_schema(call.schema, agent_key, 1)
    assert outcome.result.diagnostics.assembled_prompt == call.prompt
    # The runtime's own identity sink is never handed a candidate run: a draft
    # has no release or revision identity to record (Task 3 ruling R1).
    assert sink.calls == []
    assert sink.successes == []
    assert loader.calls == []


@pytest.mark.parametrize("agent_key", ["foreman", "nope", "Architect"])
def test_run_candidate_rejects_an_unknown_or_deterministic_role_first(agent_key):
    """Correction 14: the same typed error as ``run``, before any other check."""
    runtime, adapter, sink, loader = _candidate_runtime()
    content, _ = _candidate("architect")

    with pytest.raises(UnknownAgentKeyError, match=agent_key):
        # A mismatched role AND a wrong hash: the role check must win.
        runtime.run_candidate(
            agent_key, content, "0" * 64, {}, AgentAssemblyContext(False)
        )

    assert adapter.calls == []
    assert sink.calls == []
    assert loader.calls == []


def test_run_candidate_rejects_content_for_another_role_before_the_hash():
    runtime, adapter, sink, _ = _candidate_runtime()
    content, _ = _candidate("builder")

    with pytest.raises(ValueError, match="candidate_content.agent_key does not match"):
        runtime.run_candidate("architect", content, "0" * 64, {}, AgentAssemblyContext(False))

    assert adapter.calls == []
    assert sink.calls == []


def test_run_candidate_rejects_a_hash_that_does_not_match_the_content():
    runtime, adapter, sink, _ = _candidate_runtime()
    content, candidate_hash = _candidate("architect")
    other, other_hash = _candidate("architect", v2_assembly=True)
    assert other_hash != candidate_hash

    with pytest.raises(ValueError, match="^candidate_hash does not match candidate_content$"):
        runtime.run_candidate("architect", content, other_hash, {}, AgentAssemblyContext(False))

    assert adapter.calls == []
    assert sink.calls == []


@pytest.mark.parametrize(
    "context",
    [
        AgentAssemblyContext(False, "owner-session", ""),
        AgentAssemblyContext(False, "", "actor-session"),
    ],
)
def test_run_candidate_refuses_a_session_identity(context):
    """A test run has no session: none reaches the identity sink or the model."""
    runtime, adapter, sink, _ = _candidate_runtime()
    content, candidate_hash = _candidate("architect")

    with pytest.raises(ValueError, match="candidate runs carry no session identity"):
        runtime.run_candidate("architect", content, candidate_hash, {}, context)

    assert adapter.calls == []
    assert sink.calls == []


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
@pytest.mark.parametrize("design_system_active", [False, True])
@pytest.mark.parametrize("v2_assembly", [False, True])
def test_candidate_prompt_schema_and_configuration_equal_the_production_path(
    agent_key, design_system_active, v2_assembly
):
    """The same content gives the same prompt bytes through ``run`` and ``run_candidate``."""
    content, candidate_hash = _candidate(agent_key, v2_assembly=v2_assembly)
    payload = {"position": 2, "deck_brief": {"argument": "Revenue compounds"}, "a": [1]}
    context = AgentAssemblyContext(design_system_active)

    production_adapter = DeterministicFakeModelAdapter()
    production = AgentRuntime(
        persisted_release_loader=_StaticLoader(
            ResolvedDefinition(
                graph_version=5,
                graph_release_id=9,
                agent_key=agent_key,
                agent_definition_revision_id=11,
                content_hash=candidate_hash,
                content=content,
            )
        ),
        model_adapter=production_adapter,
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    production_result = production.run(agent_key, 9, dict(payload), context)
    runtime, candidate_adapter, _, _ = _candidate_runtime()
    outcome = runtime.run_candidate(agent_key, content, candidate_hash, dict(payload), context)

    assert outcome.status == "completed"
    produced, candidate = production_adapter.calls[0], candidate_adapter.calls[0]
    assert candidate.prompt == produced.prompt
    assert candidate.prompt.encode("utf-8") == produced.prompt.encode("utf-8")
    assert candidate.configuration == produced.configuration
    assert candidate.schema.model_json_schema() == produced.schema.model_json_schema()
    diagnostics = outcome.result.diagnostics
    assert diagnostics.assembly_stages == production_result.diagnostics.assembly_stages
    assert diagnostics.schema_contract == production_result.diagnostics.schema_contract
    assert diagnostics.protected_prompt == production_result.diagnostics.protected_prompt


def test_a_v2_overlay_candidate_binds_the_composed_schema_now():
    """Correction 13: v2 overlays are reachable today; there is no Phase B."""
    runtime, adapter, sink, _ = _candidate_runtime()
    content, candidate_hash = _candidate("architect", v2_schema=True)

    outcome = runtime.run_candidate(
        "architect", content, candidate_hash, {"x": 1}, AgentAssemblyContext(False)
    )

    assert outcome.status == "completed"
    _assert_composed_schema(adapter.calls[0].schema, "architect", 2)
    assert outcome.result.diagnostics.schema_contract.version == 2
    assert sink.calls == []


def test_a_v1_candidate_with_an_overlay_is_an_assembly_error_before_the_model():
    """Correction 13: the v1-scoped overlay guard is live and stays."""
    runtime, adapter, sink, _ = _candidate_runtime()
    v2_content, _ = _candidate("architect", v2_schema=True)
    content = v2_content.model_copy(
        update={
            "schema_contract": ContentIdentity(
                version=1, digest=EXPECTED_SCHEMA_DIGESTS["architect"]
            )
        }
    )

    outcome = runtime.run_candidate(
        "architect",
        content,
        definition_content_hash(content),
        {"x": 1},
        AgentAssemblyContext(False),
    )

    assert outcome.status == "assembly_error"
    assert outcome.error_detail == "schema_contract_unavailable"
    assert isinstance(outcome.error, PersistedConfigurationUnavailableError)
    assert outcome.result is None
    assert outcome.raw_output is None
    assert adapter.calls == []
    assert sink.calls == []


def test_an_unavailable_protected_bundle_is_an_assembly_error_before_the_model():
    runtime, adapter, sink, _ = _candidate_runtime()
    content = _manifest_content("architect").model_copy(
        update={"protected_assembly": ContentIdentity(version=999, digest="0" * 64)}
    )

    outcome = runtime.run_candidate(
        "architect",
        content,
        definition_content_hash(content),
        {},
        AgentAssemblyContext(False),
    )

    assert (outcome.status, outcome.error_detail) == (
        "assembly_error",
        "protected_bundle_unavailable",
    )
    assert adapter.calls == []
    assert sink.calls == []


@pytest.mark.parametrize(
    ("mode", "status", "detail", "error_type"),
    [
        (
            "provider_unavailable",
            "model_error",
            f"endpoint_unavailable:{_CANDIDATE_ENDPOINT}",
            PinnedInvocationEndpointError,
        ),
        (
            "structured_output_unsupported",
            "model_error",
            f"structured_output_unsupported:{_CANDIDATE_ENDPOINT}",
            NotImplementedError,
        ),
        (
            "provider_parse_error",
            "incomplete",
            "invalid_output:ValidationError",
            Exception,
        ),
    ],
)
def test_a_failing_model_call_is_classified_and_does_not_escape(
    mode, status, detail, error_type
):
    """Correction 15/33/34: parse errors and ``NotImplementedError`` are outcomes."""
    runtime, adapter, sink, _ = _candidate_runtime(DeterministicFakeModelAdapter(mode=mode))
    content, candidate_hash = _candidate("architect")

    outcome = runtime.run_candidate(
        "architect", content, candidate_hash, {}, AgentAssemblyContext(False)
    )

    assert (outcome.status, outcome.error_detail) == (status, detail)
    assert isinstance(outcome.error, error_type)
    assert outcome.result is None
    assert outcome.raw_output is None
    assert len(adapter.calls) == 1
    assert sink.calls == []


def test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one():
    runtime, _, _, _ = _candidate_runtime(
        DeterministicFakeModelAdapter(mode="provider_unavailable")
    )
    content, candidate_hash = _candidate("architect")

    outcome = runtime.run_candidate(
        "architect", content, candidate_hash, {}, AgentAssemblyContext(False)
    )

    assert outcome.error.graph_release_id == -1
    assert outcome.error.agent_definition_revision_id == -1


def test_an_output_parser_exception_is_incomplete():
    from langchain_core.exceptions import OutputParserException

    class _Parser:
        def invoke(self, **_kwargs):
            raise OutputParserException("unparseable provider text")

    runtime, _, _, _ = _candidate_runtime(_Parser())
    content, candidate_hash = _candidate("architect")

    outcome = runtime.run_candidate(
        "architect", content, candidate_hash, {}, AgentAssemblyContext(False)
    )

    assert (outcome.status, outcome.error_detail) == (
        "incomplete",
        "invalid_output:OutputParserException",
    )


def test_classification_reads_the_exception_type_never_its_text():
    """Provider prose must not steer the evidence status (I-4).

    A parser exception with bland text is still ``incomplete``, and an ordinary
    exception whose text *reads* like a parse failure is still unexpected.
    """
    from langchain_core.exceptions import OutputParserException

    class _Raises:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def invoke(self, **_kwargs):
            raise self.error

    content, candidate_hash = _candidate("architect")
    outcomes = {}
    for label, error in (
        ("bland_parser", OutputParserException("x")),
        ("parse_sounding", RuntimeError("could not parse output: 1 validation error")),
    ):
        runtime, _, _, _ = _candidate_runtime(_Raises(error))
        outcome = runtime.run_candidate(
            "architect", content, candidate_hash, {}, AgentAssemblyContext(False)
        )
        outcomes[label] = (outcome.status, outcome.error_detail)

    assert outcomes == {
        "bland_parser": ("incomplete", "invalid_output:OutputParserException"),
        "parse_sounding": ("model_error", "unexpected_error:RuntimeError"),
    }


def test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name():
    class _Boom:
        def invoke(self, **_kwargs):
            raise RuntimeError("provider text https://secret-host/token=abc")

    runtime, _, _, _ = _candidate_runtime(_Boom())
    content, candidate_hash = _candidate("architect")

    outcome = runtime.run_candidate(
        "architect", content, candidate_hash, {}, AgentAssemblyContext(False)
    )

    assert (outcome.status, outcome.error_detail) == (
        "model_error",
        "unexpected_error:RuntimeError",
    )
    assert isinstance(outcome.error, RuntimeError)


@pytest.mark.parametrize("v2_schema", [False, True])
def test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete(v2_schema):
    """Correction 15: the observer sees the raw keys before ``validate_output`` rejects them."""
    runtime, adapter, sink, _ = _candidate_runtime(
        DeterministicFakeModelAdapter(mode="invalid_optional_field")
    )
    content, candidate_hash = _candidate("architect", v2_schema=v2_schema)

    outcome = runtime.run_candidate(
        "architect", content, candidate_hash, {}, AgentAssemblyContext(False)
    )

    assert outcome.status == "incomplete"
    assert outcome.error_detail == "invalid_output:AgentOutputValidationError"
    assert isinstance(outcome.error, AgentOutputValidationError)
    assert [issue.code for issue in outcome.error.issues] == [
        "output_invalid_optional_field" if v2_schema else "output_undeclared_top_level_field"
    ]
    assert outcome.result is None
    assert outcome.raw_output == fake_output("architect", **INVALID_OPTIONAL_FIELD)
    assert sink.calls == []


def test_run_still_raises_the_validation_error_it_always_raised():
    """``run`` passes no observer and classifies nothing: its errors are unchanged."""
    content, candidate_hash = _candidate("architect", v2_schema=True)
    runtime = AgentRuntime(
        persisted_release_loader=_StaticLoader(
            ResolvedDefinition(5, 9, "architect", 11, candidate_hash, content)
        ),
        model_adapter=DeterministicFakeModelAdapter(mode="invalid_optional_field"),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )

    with pytest.raises(AgentOutputValidationError):
        runtime.run("architect", 9, {}, AgentAssemblyContext(False))


def _function_source(function) -> Any:
    import ast
    import inspect
    import textwrap

    return ast.parse(textwrap.dedent(inspect.getsource(function)))


def _self_method_calls(tree) -> list[Any]:
    import ast

    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    ]


def test_run_candidate_delegates_to_run_resolved_and_never_to_run():
    """Correction 12: one shared private path; no release resolution, no own binding."""
    import ast

    # run_candidate -> _run_observed (the #267 Task 4 observation seam) -> _run_resolved.
    tree = _function_source(AgentRuntime.run_candidate)
    methods = [call.func.attr for call in _self_method_calls(tree)]
    assert methods == ["_run_observed"]
    observed = _function_source(AgentRuntime._run_observed)
    assert [call.func.attr for call in _self_method_calls(observed)] == ["_run_resolved"]
    names = set()
    for part in (tree, observed):
        names |= {
            node.id for node in ast.walk(part) if isinstance(node, ast.Name)
        } | {node.attr for node in ast.walk(part) if isinstance(node, ast.Attribute)}
    for forbidden in (
        "run",
        "bind_structured_output_model",
        "saved_model_configuration",
        "with_structured_output",
        "bind_tools",
        "_write_locked_content",
        "_persisted_release_loader",
    ):
        assert forbidden not in names


def test_production_run_passes_no_raw_output_observer():
    """Correction 15: ``run`` hands ``_run_resolved`` its three arguments and nothing else."""
    calls = [
        call
        for call in _self_method_calls(_function_source(AgentRuntime.run))
        if call.func.attr == "_run_resolved"
    ]
    assert len(calls) == 1
    assert len(calls[0].args) == 3
    assert calls[0].keywords == []


def _src_python_files():
    from pathlib import Path

    root = Path(runtime_module.__file__).resolve().parents[2]
    return root, sorted((root / "src").rglob("*.py"))


def _modules_referencing(name: str) -> set[str]:
    import ast

    root, files = _src_python_files()
    found: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == name) or (
                isinstance(node, ast.Name) and node.id == name
            ) or (isinstance(node, ast.alias) and node.name == name):
                found.add(path.relative_to(root).as_posix())
                break
    return found


def test_run_candidate_is_reachable_only_from_the_agent_test_workbench():
    """Spec §7.1: a candidate run cannot be used by a production conversation."""
    assert _modules_referencing("run_candidate") <= {"src/services/agent_test_workbench.py"}


def test_the_bounded_test_runtime_is_reachable_only_from_the_workbench_and_its_route():
    """Correction 33: no graph node can pick up the test runtime's transport bound."""
    assert _modules_referencing("get_agent_test_runtime") - {
        "src/services/agent_runtime.py"
    } <= {
        "src/services/agent_test_workbench.py",
        "src/api/routes/agent_definitions.py",
    }


def test_no_module_binds_a_structured_model_outside_the_one_helper():
    """Correction 12/31: one ``bind_tools(`` in ``src``, two helper callers.

    Follow-up A: the binding is ``bind_tools([schema], tool_choice="auto")``;
    ``with_structured_output(`` (forced tool choice) appears nowhere in ``src``.
    """
    import ast

    root, files = _src_python_files()
    bindings: dict[str, int] = {}
    helper_callers: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in {"with_structured_output", "bind_tools"}:
                bindings[(module, name)] = bindings.get((module, name), 0) + 1
            if name == "bind_structured_output_model":
                helper_callers.add(module)
    assert bindings == {("src/services/agent_runtime.py", "bind_tools"): 1}
    assert helper_callers == {
        "src/services/agent_runtime.py",
        "src/services/model_endpoint_probe.py",
    }

    workbench = (root / "src/services/agent_test_workbench.py").read_text(encoding="utf-8")
    for forbidden in (
        "with_structured_output",
        "bind_tools",
        "bind_structured_output_model(",
        "ChatDatabricks",
    ):
        assert forbidden not in workbench


def _drive_adapter_kwargs(adapter: DatabricksModelAdapter) -> dict[str, Any]:
    output = _output_for("architect")
    events, runtime_client, model_factory, client_factory = _recording_factories(output)
    adapter._model_factory = model_factory
    adapter._client_factory = client_factory
    adapter.invoke(
        agent_key="architect",
        configuration=_SAVED_CONFIGURATION,
        schema=OUTPUT_SCHEMAS["architect"],
        prompt="p",
    )
    kwargs = next(value for name, value in events if name == "model_factory")
    assert kwargs.pop("workspace_client") is runtime_client
    return kwargs


#: What the one binding constructs the model with: the saved temperature and
#: top_p are stored but never sent (follow-up A).
_SAVED_MODEL_KWARGS = {
    "model": "saved exact endpoint-name",
    "max_tokens": 321,
}


def test_databricks_model_adapter_forwards_transport_options_to_the_one_binding():
    adapter = DatabricksModelAdapter(transport_options={"timeout": 1.5, "max_retries": 0})

    assert _drive_adapter_kwargs(adapter) == {
        **_SAVED_MODEL_KWARGS,
        "timeout": 1.5,
        "max_retries": 0,
    }


def test_the_agent_test_runtime_bounds_its_model_call_to_120_seconds_and_no_retry():
    from src.services.agent_runtime import (
        LoggingAgentInvocationIdentitySink,
        get_agent_runtime,
    )
    from src.services.persisted_graph_release import PersistedGraphReleaseLoader

    get_agent_test_runtime = runtime_module.get_agent_test_runtime
    get_agent_test_runtime.cache_clear()
    get_agent_runtime.cache_clear()
    try:
        runtime = get_agent_test_runtime()
        assert runtime is get_agent_test_runtime()
        assert runtime is not get_agent_runtime()
        assert runtime_module.TEST_RUN_TIMEOUT_SECONDS == 120.0
        assert runtime_module.TEST_RUN_MAX_RETRIES == 0
        assert isinstance(runtime._persisted_release_loader, PersistedGraphReleaseLoader)
        assert isinstance(runtime._identity_sink, LoggingAgentInvocationIdentitySink)
        assert type(runtime._model_adapter) is DatabricksModelAdapter
        assert _drive_adapter_kwargs(runtime._model_adapter) == {
            **_SAVED_MODEL_KWARGS,
            "timeout": 120.0,
            "max_retries": 0,
        }
    finally:
        get_agent_test_runtime.cache_clear()
        get_agent_runtime.cache_clear()


def test_the_production_runtime_adapter_still_hands_no_transport_options():
    from src.services.agent_runtime import get_agent_runtime

    get_agent_runtime.cache_clear()
    try:
        assert _drive_adapter_kwargs(get_agent_runtime()._model_adapter) == _SAVED_MODEL_KWARGS
    finally:
        get_agent_runtime.cache_clear()


# --- #267 Task 4 fix round 1: the public observation hook (I-1) -------------


def test_run_published_baseline_is_reachable_only_from_the_agent_test_workbench():
    """Like ``run_candidate``: no production conversation can reach it (spec §7.1)."""
    assert _modules_referencing("run_published_baseline") <= {
        "src/services/agent_test_workbench.py"
    }


def test_no_module_outside_the_runtime_touches_its_model_adapter():
    """I-1: nothing swaps or wraps a runtime's private adapter from outside."""
    assert _modules_referencing("_model_adapter") == {"src/services/agent_runtime.py"}


def test_no_module_imports_a_private_name_from_the_runtime():
    import ast

    root, files = _src_python_files()
    offenders: set[tuple[str, str]] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.services.agent_runtime":
                for alias in node.names:
                    if alias.name.startswith("_"):
                        offenders.add((path.relative_to(root).as_posix(), alias.name))
    assert offenders == set()


def test_run_published_baseline_resolves_exactly_as_run_does():
    """The role check and the loader try/except are ``run``'s, statement for statement."""
    import ast

    def resolution(function) -> list[str]:
        body = _function_source(function).body[0].body
        statements = [stmt for stmt in body if isinstance(stmt, (ast.If, ast.Try))]
        return [ast.dump(stmt) for stmt in statements]

    assert resolution(AgentRuntime.run_published_baseline) == resolution(AgentRuntime.run)
    assert len(resolution(AgentRuntime.run)) == 2


def _baseline_runtime(adapter):
    content = _manifest_content("architect")
    loader = SimpleNamespace(
        resolve=lambda graph_release_id, agent_key: ResolvedDefinition(
            graph_version=3,
            graph_release_id=graph_release_id,
            agent_key=agent_key,
            agent_definition_revision_id=41,
            content_hash=definition_content_hash(content),
            content=content,
        )
    )
    sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=loader, model_adapter=adapter, identity_sink=sink
    )
    return runtime, sink


def test_run_published_baseline_hands_the_model_runs_prompt_and_records_the_real_identity():
    from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter

    run_adapter = DeterministicFakeModelAdapter()
    run_runtime, _ = _baseline_runtime(run_adapter)
    run_runtime.run("architect", 7, {"message": "m"}, AgentAssemblyContext(False))

    adapter = DeterministicFakeModelAdapter()
    runtime, sink = _baseline_runtime(adapter)
    observation = RunObservation()
    outcome = runtime.run_published_baseline(
        "architect", 7, {"message": "m"}, AgentAssemblyContext(False), observation=observation
    )

    assert outcome.status == "completed"
    assert adapter.calls[0].prompt == run_adapter.calls[0].prompt
    assert observation.prompt == adapter.calls[0].prompt
    assert observation.raw_output == outcome.raw_output
    assert observation.model_latency_ms is not None and observation.model_latency_ms >= 0
    assert [(c.graph_release_id, c.agent_definition_revision_id) for c in sink.calls] == [
        (7, 41)
    ]


def test_an_observation_keeps_the_prompt_and_duration_of_a_failed_model_call():
    from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter

    adapter = DeterministicFakeModelAdapter(mode="provider_unavailable")
    runtime, _ = _baseline_runtime(adapter)
    observation = RunObservation()

    outcome = runtime.run_published_baseline(
        "architect", 7, {"message": "m"}, AgentAssemblyContext(False), observation=observation
    )

    assert outcome.status == "model_error"
    assert observation.prompt == adapter.calls[0].prompt
    assert observation.model_latency_ms is not None
    assert observation.raw_output is None


def test_run_published_baseline_raises_loader_failures_as_run_does():
    from sqlalchemy.exc import OperationalError

    def _fail(graph_release_id, agent_key):
        raise OperationalError("SELECT 1", {}, Exception("down"))

    runtime = AgentRuntime(
        persisted_release_loader=SimpleNamespace(resolve=_fail),
        model_adapter=SimpleNamespace(),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    with pytest.raises(PersistedConfigurationUnavailableError) as caught:
        runtime.run_published_baseline("architect", 7, {}, AgentAssemblyContext(False))
    assert caught.value.code == "lakebase_unavailable"
    with pytest.raises(UnknownAgentKeyError):
        runtime.run_published_baseline("foreman", 7, {}, AgentAssemblyContext(False))


# ---------------------------------------------------------------------------
# #267 whole-branch fix I-1: a test run records the provider's token usage.
#
# The REAL ``ChatDatabricks`` (databricks-langchain 0.9.0) is driven over an
# ``httpx.MockTransport``.  Measured: it reports usage in the AIMessage's
# ``response_metadata["usage"]`` (``prompt_tokens`` / ``completion_tokens``)
# and leaves ``usage_metadata`` unset.  Only an observed test run reads it;
# production ``run`` binds exactly as before.
# ---------------------------------------------------------------------------


def _real_chat_adapter(monkeypatch, usage):
    from tests.fixtures.mock_chat_completions import (
        MockChatCompletionsWorkspace,
        install_mock_gateway_transport,
    )

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace(fake_output("architect"), usage=usage)
    adapter = DatabricksModelAdapter(
        client_factory=lambda: workspace,
        transport_options={
            "timeout": runtime_module.TEST_RUN_TIMEOUT_SECONDS,
            "max_retries": runtime_module.TEST_RUN_MAX_RETRIES,
        },
    )
    return adapter, workspace


def _observed_real_runs(monkeypatch, usage):
    """One candidate run and one baseline rerun, each with its own observation."""
    adapter, workspace = _real_chat_adapter(monkeypatch, usage)
    runtime, _ = _baseline_runtime(adapter)
    content, candidate_hash = _candidate("architect")
    candidate_observation = RunObservation()
    baseline_observation = RunObservation()

    candidate = runtime.run_candidate(
        "architect",
        content,
        candidate_hash,
        {"message": "m"},
        AgentAssemblyContext(False),
        observation=candidate_observation,
    )
    baseline = runtime.run_published_baseline(
        "architect",
        7,
        {"message": "m"},
        AgentAssemblyContext(False),
        observation=baseline_observation,
    )
    assert len(workspace.requests) == 2
    return (candidate, candidate_observation), (baseline, baseline_observation)


def test_production_adapter_sends_the_stored_name_to_the_gateway_chat_route(monkeypatch):
    """Spec §6.1: the real ChatDatabricks posts to {host}/ai-gateway/mlflow/v1, stored name unchanged."""
    from tests.fixtures.mock_chat_completions import (
        MOCK_CHAT_HOST,
        MockChatCompletionsWorkspace,
        install_mock_gateway_transport,
    )

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace(fake_output("architect"), usage=None)
    adapter = DatabricksModelAdapter(client_factory=lambda: workspace)

    adapter.invoke(
        agent_key="architect",
        configuration=AgentModelConfiguration(
            endpoint_name="databricks-claude-opus-4-6",
            temperature=0.7,
            max_tokens=60000,
            top_p=0.95,
        ),
        schema=OUTPUT_SCHEMAS["architect"],
        prompt="assembled prompt",
    )

    assert len(workspace.requests) == 1
    request = workspace.requests[0]
    assert request.url.host == MOCK_CHAT_HOST
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"
    assert json.loads(request.content)["model"] == "databricks-claude-opus-4-6"


def test_the_graph_request_sends_no_sampling_and_auto_tool_choice(monkeypatch):
    """Follow-up A: newer Claude models 400 on ``temperature`` and on forced tool choice.

    The real ``ChatDatabricks`` request body carries the output schema as the
    one tool, ``tool_choice == "auto"``, the saved ``max_tokens`` — and no
    ``temperature``, ``top_p`` or ``top_k`` although the configuration stores them.
    """
    from tests.fixtures.mock_chat_completions import (
        MockChatCompletionsWorkspace,
        install_mock_gateway_transport,
    )

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace(fake_output("architect"), usage=None)
    adapter = DatabricksModelAdapter(client_factory=lambda: workspace)

    actual = adapter.invoke(
        agent_key="architect",
        configuration=AgentModelConfiguration(
            endpoint_name="system.ai.claude-opus-5-5",
            temperature=0.7,
            max_tokens=60000,
            top_p=0.95,
        ),
        schema=OUTPUT_SCHEMAS["architect"],
        prompt="assembled prompt",
    )

    assert actual == OUTPUT_SCHEMAS["architect"].model_validate(fake_output("architect"))
    (request,) = workspace.requests
    sent = json.loads(request.content)
    assert sent["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in sent["tools"]] == ["ArchitectOutput"]
    assert sent["max_tokens"] == 60000
    for sampling in ("temperature", "top_p", "top_k"):
        assert sampling not in sent


def test_a_real_provider_reply_without_a_tool_call_is_the_typed_invalid_output(monkeypatch):
    """Follow-up A: ``tool_choice="auto"`` lets a model answer in prose instead.

    The parser then yields ``None``; the binding turns that into an
    ``OutputParserException`` so a candidate run lands in the existing
    ``incomplete`` / ``invalid_output:`` classification instead of a
    ``NoneType`` crash further down.
    """
    from tests.fixtures.mock_chat_completions import (
        MockChatCompletionsWorkspace,
        install_mock_gateway_transport,
    )

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace(
        fake_output("architect"), usage=None, tool_call=False
    )
    adapter = DatabricksModelAdapter(client_factory=lambda: workspace)
    runtime, _ = _baseline_runtime(adapter)
    content, candidate_hash = _candidate("architect")

    outcome = runtime.run_candidate(
        "architect",
        content,
        candidate_hash,
        {"message": "m"},
        AgentAssemblyContext(False),
        observation=RunObservation(),
    )

    assert len(workspace.requests) == 1
    assert outcome.status == "incomplete"
    assert outcome.error_detail == "invalid_output:OutputParserException"


def test_the_binding_raises_the_parser_error_when_no_tool_is_called():
    """The None-guard itself, on the adapter: prose instead of a tool call raises."""
    from langchain_core.exceptions import OutputParserException

    class ProseChatModel:
        def bind_tools(self, tools, **kwargs):
            return replying(lambda prompt: no_tool_call_reply())

    adapter = DatabricksModelAdapter(
        model_factory=lambda **_kwargs: ProseChatModel(),
        client_factory=lambda: object(),
    )

    with pytest.raises(OutputParserException):
        adapter.invoke(
            agent_key="architect",
            configuration=_SAVED_CONFIGURATION,
            schema=OUTPUT_SCHEMAS["architect"],
            prompt="p",
        )


def test_an_observed_real_provider_run_records_the_reported_token_usage(monkeypatch):
    """I-1: the counts an endpoint reports reach the observation, for both run kinds."""
    from tests.fixtures.mock_chat_completions import (
        MOCK_COMPLETION_TOKENS,
        MOCK_PROMPT_TOKENS,
        MOCK_USAGE,
    )

    for outcome, observation in _observed_real_runs(monkeypatch, MOCK_USAGE):
        assert outcome.status == "completed"
        assert outcome.raw_output == fake_output("architect")
        assert (observation.input_tokens, observation.output_tokens) == (
            MOCK_PROMPT_TOKENS,
            MOCK_COMPLETION_TOKENS,
        )
        assert type(observation.input_tokens) is int
        assert type(observation.output_tokens) is int


def test_an_observed_real_provider_run_without_usage_records_none(monkeypatch):
    """P9: an endpoint that reports no usage leaves both counts unset ("not reported")."""
    for outcome, observation in _observed_real_runs(monkeypatch, None):
        assert outcome.status == "completed"
        assert (observation.input_tokens, observation.output_tokens) == (None, None)


def test_a_fresh_observation_has_no_token_usage():
    observation = RunObservation()

    assert (observation.input_tokens, observation.output_tokens) == (None, None)


def test_production_run_binds_exactly_as_before_and_reads_no_usage(monkeypatch):
    """I-1 guard: usage capture never reaches production ``run``.

    Production ``run`` over the real provider, whose endpoint DOES report usage:
    the helper must return exactly the plain ``bind_tools([schema],
    tool_choice="auto") | parser | none-guard`` chain (no ``include_raw``, no
    callback wrapper), and the bound model must be invoked with the prompt alone.
    """
    from databricks_langchain import ChatDatabricks
    from langchain_core.runnables import RunnableSequence

    from tests.fixtures.mock_chat_completions import MOCK_USAGE

    bindings: list[tuple[tuple, dict, Any]] = []
    original_binding = ChatDatabricks.bind_tools

    def _recording_binding(self, *args, **kwargs):
        bound = original_binding(self, *args, **kwargs)
        bindings.append((args, kwargs, bound))
        return bound

    monkeypatch.setattr(ChatDatabricks, "bind_tools", _recording_binding)
    helper_returns: list[Any] = []
    original_helper = runtime_module.bind_structured_output_model

    def _recording_helper(**kwargs):
        bound = original_helper(**kwargs)
        helper_returns.append(bound)
        return bound

    monkeypatch.setattr(runtime_module, "bind_structured_output_model", _recording_helper)
    adapter, workspace = _real_chat_adapter(monkeypatch, MOCK_USAGE)
    runtime, _ = _baseline_runtime(adapter)

    result = runtime.run("architect", 7, {"message": "m"}, AgentAssemblyContext(False))

    assert result.output == OUTPUT_SCHEMAS["architect"].model_validate(fake_output("architect"))
    assert len(workspace.requests) == 1
    assert len(bindings) == 1
    args, kwargs, bound = bindings[0]
    assert kwargs == {"tool_choice": "auto"}
    # One positional argument: a one-tool list holding the (composed) output schema.
    assert len(args) == 1
    (bound_schema,) = args[0]
    assert issubclass(bound_schema, OUTPUT_SCHEMAS["architect"])
    assert len(helper_returns) == 1
    # The plain chain: its first step IS the bound model, and no callback-carrying
    # ``with_config`` wrapper sits around it.
    assert type(helper_returns[0]) is RunnableSequence
    assert helper_returns[0].first is bound
    assert len(helper_returns[0].steps) == 3


def test_a_fake_adapter_reporting_usage_fills_only_an_observed_run():
    """The fake reports usage through the runtime's one seam; ``run`` ignores it."""
    adapter = DeterministicFakeModelAdapter(usage=(11, 7))
    runtime, _ = _baseline_runtime(adapter)
    content, candidate_hash = _candidate("architect")
    observation = RunObservation()

    production = runtime.run("architect", 7, {"message": "m"}, AgentAssemblyContext(False))
    outcome = runtime.run_candidate(
        "architect",
        content,
        candidate_hash,
        {"message": "m"},
        AgentAssemblyContext(False),
        observation=observation,
    )

    assert production.output == outcome.result.output
    assert (observation.input_tokens, observation.output_tokens) == (11, 7)

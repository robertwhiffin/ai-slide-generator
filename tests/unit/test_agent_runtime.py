"""Behavioral contract for the model-driven Graph Node runtime.

The expected prompts below reproduce the shipped pre-runtime assembly rules from
their independent code-owned inputs.  They deliberately do not call a production
prompt helper: the test must disagree if AgentRuntime changes ordering, separators,
serialization, model settings, or schema selection during the prefactor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, field_validator

from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills import load_skill
from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import (
    MODEL_DRIVEN_AGENT_KEYS,
    AgentAssemblyContext,
    AgentModelConfiguration,
    AgentRuntime,
    CodeOwnedAgentDefinitionSource,
    DatabricksModelAdapter,
    IncompatibleSchemaContractError,
    ProtectedPromptBundleUnavailableError,
    ProtectedPromptIdentity,
    UnknownAgentKeyError,
    _canonical_digest,
    _schema_contract_material,
)
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS

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
    def __init__(self, output: BaseModel) -> None:
        self.output = output
        self.calls: list[ModelCall] = []

    def invoke(
        self,
        *,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        self.calls.append(ModelCall(configuration, schema, prompt))
        return self.output


class StaticDefinitionSource:
    def __init__(self, definition: Any) -> None:
        self.definition = definition

    def resolve(self, agent_key: str) -> Any:
        return self.definition


def _output_for(agent_key: str) -> BaseModel:
    return OUTPUT_SCHEMAS[agent_key].model_construct()


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
    runtime = AgentRuntime.compatibility(model_adapter=model)
    payload = _payload_for(agent_key)

    result = runtime.run(
        agent_key,
        payload,
        AgentAssemblyContext(design_system_active=False),
    )

    assert result.output is output
    assert model.calls == [
        ModelCall(
            configuration=AgentModelConfiguration(
                endpoint_name="databricks-claude-opus-4-6",
                temperature=0.7,
                max_tokens=60000,
                top_p=0.95,
            ),
            schema=OUTPUT_SCHEMAS[agent_key],
            prompt=_expected_prompt(
                agent_key,
                payload,
                design_system_active=False,
            ),
        )
    ]
    assert result.diagnostics.agent_key == agent_key
    assert result.diagnostics.assembled_prompt == model.calls[0].prompt
    assert result.diagnostics.model_configuration == model.calls[0].configuration
    assert result.diagnostics.protected_prompt.version == 1
    assert result.diagnostics.protected_prompt.digest == EXPECTED_PROTECTED_PROMPT_DIGEST
    assert result.diagnostics.schema_contract.agent_key == agent_key
    assert result.diagnostics.schema_contract.version == 1
    assert result.diagnostics.schema_contract.digest == EXPECTED_SCHEMA_DIGESTS[agent_key]
    assert result.diagnostics.latency_ms >= 0


def test_design_system_prompt_preserves_precedence_and_omits_frame_constraints():
    output = _output_for("builder")
    model = RecordingModelAdapter(output)
    runtime = AgentRuntime.compatibility(model_adapter=model)
    payload = {"position": 3}

    runtime.run(
        "builder",
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
    runtime = AgentRuntime.compatibility(model_adapter=model)
    payload = {"position": 2, "deck_brief": {"argument": "Revenue compounds"}}

    runtime.run(
        "build_reviewer",
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


def test_code_owned_contract_identities_are_stable_literals():
    source = CodeOwnedAgentDefinitionSource()

    definitions = {key: source.resolve(key) for key in MODEL_DRIVEN_AGENT_KEYS}

    assert set(definitions) == set(EXPECTED_SCHEMA_DIGESTS)
    assert {item.protected_prompt.digest for item in definitions.values()} == {
        EXPECTED_PROTECTED_PROMPT_DIGEST
    }
    assert {
        key: definition.schema_contract.digest
        for key, definition in definitions.items()
    } == EXPECTED_SCHEMA_DIGESTS


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
    runtime = AgentRuntime.compatibility(model_adapter=model)

    with pytest.raises(UnknownAgentKeyError, match=agent_key):
        runtime.run(agent_key, {}, AgentAssemblyContext(False))

    assert model.calls == []


def test_unavailable_protected_bundle_fails_before_model_invocation():
    definition = CodeOwnedAgentDefinitionSource().resolve("architect")
    unavailable = replace(
        definition,
        protected_prompt=ProtectedPromptIdentity(version=999, digest="0" * 64),
    )
    model = RecordingModelAdapter(_output_for("architect"))
    runtime = AgentRuntime.compatibility(
        model_adapter=model,
        definition_source=StaticDefinitionSource(unavailable),
    )

    with pytest.raises(ProtectedPromptBundleUnavailableError, match="999"):
        runtime.run("architect", {}, AgentAssemblyContext(False))

    assert model.calls == []


def test_incompatible_schema_contract_fails_before_model_invocation():
    source = CodeOwnedAgentDefinitionSource()
    definition = source.resolve("architect")
    incompatible = replace(
        definition,
        schema_contract=source.resolve("builder").schema_contract,
    )
    model = RecordingModelAdapter(_output_for("architect"))
    runtime = AgentRuntime.compatibility(
        model_adapter=model,
        definition_source=StaticDefinitionSource(incompatible),
    )

    with pytest.raises(IncompatibleSchemaContractError, match="architect"):
        runtime.run("architect", {}, AgentAssemblyContext(False))

    assert model.calls == []


def test_databricks_model_adapter_never_binds_legacy_tool_grants():
    output = _output_for("data_analyst")

    class StructuredModel:
        def invoke(self, prompt: str) -> BaseModel:
            assert prompt == "assembled prompt"
            return output

    class ChatModel:
        def bind_tools(self, tools):  # pragma: no cover - failure path
            raise AssertionError(f"legacy tool grants must stay inert: {tools}")

        def with_structured_output(self, schema):
            assert schema is OUTPUT_SCHEMAS["data_analyst"]
            return StructuredModel()

    constructed: list[dict[str, Any]] = []

    def model_factory(**kwargs):
        constructed.append(kwargs)
        return ChatModel()

    adapter = DatabricksModelAdapter(
        model_factory=model_factory,
        client_factory=lambda: object(),
    )

    actual = adapter.invoke(
        configuration=AgentModelConfiguration(
            endpoint_name="databricks-claude-opus-4-6",
            temperature=0.7,
            max_tokens=60000,
            top_p=0.95,
        ),
        schema=OUTPUT_SCHEMAS["data_analyst"],
        prompt="assembled prompt",
    )

    assert actual is output
    assert constructed == [
        {
            "endpoint": "databricks-claude-opus-4-6",
            "temperature": 0.7,
            "max_tokens": 60000,
            "top_p": 0.95,
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

"""One invocation seam for Tellr's seven model-driven Graph Nodes.

The current adapter reads the existing legacy ``Skill`` records and exposes them as
code-owned Agent Definitions. That source is temporary: persisted Graph Releases
replace it in later work. Prompt assembly, schema resolution, model construction,
invocation, and diagnostics already live behind :class:`AgentRuntime`, so changing
the definition source does not spread those concerns back across graph nodes.

Foreman is deliberately absent.  It is deterministic routing code, not an Agent
Definition, and an attempt to resolve it fails as an unknown model-driven role.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import textwrap
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Protocol, cast

from pydantic import BaseModel

from src.core.defaults import DEFAULT_CONFIG
from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE, UNTRUSTED_DATA_NOTICE
from src.core.skills import load_skill
from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW, build_instructions
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS

MODEL_DRIVEN_AGENT_KEYS = (
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)
_MODEL_DRIVEN_AGENT_KEY_SET = frozenset(MODEL_DRIVEN_AGENT_KEYS)

_PROTECTED_PROMPT_VERSION = 1
_PROTECTED_PROMPT_DIGEST = (
    "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852"
)
_SCHEMA_CONTRACT_VERSION = 1
_SCHEMA_CONTRACT_DIGESTS = {
    "architect": "a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
    "data_analyst": "610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281",
    "builder": "fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387",
    "fixer": "7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297",
    "build_reviewer": "50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d",
    "fix_reviewer": "31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df",
    "deck_reviewer": "56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467",
}


class AgentRuntimeError(RuntimeError):
    """Base class for failures at the AgentRuntime interface."""


class UnknownAgentKeyError(AgentRuntimeError):
    """The requested key is not one of the seven model-driven roles."""


class ProtectedPromptBundleUnavailableError(AgentRuntimeError):
    """A definition names protected prompt material this deployment cannot resolve."""


class IncompatibleSchemaContractError(AgentRuntimeError):
    """A definition names a schema contract that is not valid for its role."""


class RuntimeContractIdentityError(AgentRuntimeError):
    """Code-owned contract material changed without an explicit identity update."""


@dataclass(frozen=True)
class ProtectedPromptIdentity:
    version: int
    digest: str


@dataclass(frozen=True)
class SchemaContractIdentity:
    agent_key: str
    version: int
    digest: str


@dataclass(frozen=True)
class AgentModelConfiguration:
    endpoint_name: str
    temperature: float
    max_tokens: int
    top_p: float


@dataclass(frozen=True)
class AgentAssemblyContext:
    design_system_active: bool


@dataclass(frozen=True)
class AgentDefinition:
    agent_key: str
    definition_version: int
    prompt_text: str
    model_configuration: AgentModelConfiguration
    protected_prompt: ProtectedPromptIdentity
    schema_contract: SchemaContractIdentity
    legacy_tool_grants: tuple[str, ...]


@dataclass(frozen=True)
class AgentInvocationDiagnostics:
    agent_key: str
    definition_version: int
    assembled_prompt: str
    model_configuration: AgentModelConfiguration
    protected_prompt: ProtectedPromptIdentity
    schema_contract: SchemaContractIdentity
    latency_ms: float


@dataclass(frozen=True)
class AgentInvocationResult:
    output: BaseModel
    diagnostics: AgentInvocationDiagnostics


class AgentDefinitionSource(Protocol):
    def resolve(self, agent_key: str) -> AgentDefinition: ...


class AgentModelAdapter(Protocol):
    def invoke(
        self,
        *,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel: ...


@dataclass(frozen=True)
class _ProtectedPromptBundle:
    identity: ProtectedPromptIdentity
    slide_frame_constraints: str
    design_system_precedence: str
    build_reviewer_deck_brief: str


def _canonical_digest(material: Any) -> str:
    serialized = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _protected_prompt_material() -> dict[str, Any]:
    """Return every code-owned input covered by protected prompt identity v1."""
    return {
        "build_reviewer_criteria": build_instructions(),
        "build_reviewer_deck_brief": DECK_BRIEF_REVIEW,
        "design_system_precedence": DESIGN_SYSTEM_PRECEDENCE,
        "payload_serialization": {
            "default": "str",
            "format": "json",
            "indent": 2,
        },
        "slide_frame_constraints": _SLIDE_FRAME_CONSTRAINTS,
        "structured_output_binding": "langchain.with_structured_output",
        "untrusted_data_notice": UNTRUSTED_DATA_NOTICE,
    }


def _schema_contract_material(agent_key: str, schema: type[BaseModel]) -> dict[str, Any]:
    return {
        "agent_key": agent_key,
        "qualified_name": f"{schema.__module__}.{schema.__qualname__}",
        "json_schema": schema.model_json_schema(mode="validation"),
        "model_configurations": _schema_configuration_material(schema),
        "validators": _schema_validator_material(schema),
    }


def _schema_configuration_material(schema: type[BaseModel]) -> list[dict[str, Any]]:
    """Return Pydantic validation configuration for every model in the contract."""
    configurations: dict[tuple[str, str], dict[str, Any]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            model = node.get("cls")
            config = node.get("config")
            if (
                isinstance(model, type)
                and issubclass(model, BaseModel)
                and isinstance(config, dict)
            ):
                qualified_name = f"{model.__module__}.{model.__qualname__}"
                item = {
                    "qualified_name": qualified_name,
                    "config": config,
                }
                configurations[(qualified_name, _canonical_digest(config))] = item
            for value in node.values():
                visit(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                visit(value)

    visit(schema.__pydantic_core_schema__)
    return [configurations[key] for key in sorted(configurations)]


def _schema_validator_material(schema: type[BaseModel]) -> list[dict[str, str]]:
    """Return stable source identities for validators in a Pydantic contract tree."""
    validators: dict[tuple[str, str, str], dict[str, str]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                visit(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                visit(value)
            return
        if not callable(node) or isinstance(node, type):
            return

        function = getattr(node, "__func__", node)
        module = getattr(function, "__module__", "")
        if module != schema.__module__ and not module.startswith("src."):
            return
        qualified_name = getattr(function, "__qualname__", repr(function))
        try:
            source = textwrap.dedent(inspect.getsource(function)).strip()
        except (OSError, TypeError):
            return
        key = (module, qualified_name, source)
        validators[key] = {
            "module": module,
            "qualified_name": qualified_name,
            "source": source,
        }

    visit(schema.__pydantic_core_schema__)
    return [validators[key] for key in sorted(validators)]


class _ProtectedPromptBundleRegistry:
    def __init__(self) -> None:
        actual_digest = _canonical_digest(_protected_prompt_material())
        if actual_digest != _PROTECTED_PROMPT_DIGEST:
            raise RuntimeContractIdentityError(
                "Protected prompt material changed without an identity update: "
                f"expected {_PROTECTED_PROMPT_DIGEST}, calculated {actual_digest}"
            )
        self._current = _ProtectedPromptBundle(
            identity=ProtectedPromptIdentity(
                version=_PROTECTED_PROMPT_VERSION,
                digest=_PROTECTED_PROMPT_DIGEST,
            ),
            slide_frame_constraints=_SLIDE_FRAME_CONSTRAINTS,
            design_system_precedence=DESIGN_SYSTEM_PRECEDENCE,
            build_reviewer_deck_brief=DECK_BRIEF_REVIEW,
        )

    def resolve(self, identity: ProtectedPromptIdentity) -> _ProtectedPromptBundle:
        if identity != self._current.identity:
            raise ProtectedPromptBundleUnavailableError(
                "Protected prompt bundle is unavailable: "
                f"version={identity.version}, digest={identity.digest}"
            )
        return self._current


class _SchemaContractRegistry:
    def __init__(self) -> None:
        self._contracts: dict[str, tuple[SchemaContractIdentity, type[BaseModel]]] = {}
        for agent_key in MODEL_DRIVEN_AGENT_KEYS:
            schema = OUTPUT_SCHEMAS[agent_key]
            actual_digest = _canonical_digest(
                _schema_contract_material(agent_key, schema)
            )
            expected_digest = _SCHEMA_CONTRACT_DIGESTS[agent_key]
            if actual_digest != expected_digest:
                raise RuntimeContractIdentityError(
                    f"Schema contract for {agent_key!r} changed without an identity "
                    f"update: expected {expected_digest}, calculated {actual_digest}"
                )
            identity = SchemaContractIdentity(
                agent_key=agent_key,
                version=_SCHEMA_CONTRACT_VERSION,
                digest=expected_digest,
            )
            self._contracts[agent_key] = (identity, schema)

    def identity_for(self, agent_key: str) -> SchemaContractIdentity:
        return self._contracts[agent_key][0]

    def resolve(
        self,
        agent_key: str,
        identity: SchemaContractIdentity,
    ) -> type[BaseModel]:
        expected_identity, schema = self._contracts[agent_key]
        if identity != expected_identity:
            raise IncompatibleSchemaContractError(
                f"Schema contract is incompatible with agent {agent_key!r}: "
                f"received agent={identity.agent_key!r}, version={identity.version}, "
                f"digest={identity.digest}; expected agent={expected_identity.agent_key!r}, "
                f"version={expected_identity.version}, digest={expected_identity.digest}"
            )
        return schema


class CodeOwnedAgentDefinitionSource:
    """Temporary adapter from shipped Python skill records to Agent Definitions."""

    def __init__(self) -> None:
        self._schemas = _SchemaContractRegistry()
        self._protected_prompt = ProtectedPromptIdentity(
            version=_PROTECTED_PROMPT_VERSION,
            digest=_PROTECTED_PROMPT_DIGEST,
        )

    def resolve(self, agent_key: str) -> AgentDefinition:
        if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET:
            raise UnknownAgentKeyError(
                f"Unknown model-driven agent key {agent_key!r}; "
                f"expected one of {list(MODEL_DRIVEN_AGENT_KEYS)!r}"
            )

        skill = load_skill(agent_key)
        expected_schema = OUTPUT_SCHEMAS[agent_key]
        if skill.output_schema is not expected_schema:
            raise IncompatibleSchemaContractError(
                f"Code-owned Agent Definition {agent_key!r} binds "
                f"{skill.output_schema!r}, not canonical schema {expected_schema!r}"
            )

        llm = cast(dict[str, Any], DEFAULT_CONFIG["llm"])
        return AgentDefinition(
            agent_key=agent_key,
            definition_version=skill.version,
            prompt_text=skill.instructions,
            model_configuration=AgentModelConfiguration(
                endpoint_name=str(llm["endpoint"]),
                temperature=float(llm["temperature"]),
                max_tokens=int(llm["max_tokens"]),
                top_p=float(llm["top_p"]),
            ),
            protected_prompt=self._protected_prompt,
            schema_contract=self._schemas.identity_for(agent_key),
            legacy_tool_grants=tuple(skill.tool_grants),
        )


class DatabricksModelAdapter:
    """Invoke one structured Databricks model without binding any tools."""

    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model_factory = model_factory or self._default_model_factory
        self._client_factory = client_factory or self._default_client_factory

    @staticmethod
    def _default_model_factory(**kwargs: Any) -> Any:
        from databricks_langchain import ChatDatabricks  # type: ignore[import-untyped]

        return ChatDatabricks(**kwargs)

    @staticmethod
    def _default_client_factory() -> Any:
        from src.core.databricks_client import get_system_client

        return get_system_client()

    def invoke(
        self,
        *,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        model = self._model_factory(
            endpoint=configuration.endpoint_name,
            temperature=configuration.temperature,
            max_tokens=configuration.max_tokens,
            top_p=configuration.top_p,
            workspace_client=self._client_factory(),
        )
        structured_model = model.with_structured_output(schema)
        return structured_model.invoke(prompt)


class AgentRuntime:
    """Resolve and execute one model-driven Agent Definition."""

    def __init__(
        self,
        *,
        definition_source: AgentDefinitionSource,
        model_adapter: AgentModelAdapter,
    ) -> None:
        self._definition_source = definition_source
        self._model_adapter = model_adapter
        self._protected_prompts = _ProtectedPromptBundleRegistry()
        self._schema_contracts = _SchemaContractRegistry()

    @classmethod
    def compatibility(
        cls,
        *,
        model_adapter: AgentModelAdapter | None = None,
        definition_source: AgentDefinitionSource | None = None,
    ) -> AgentRuntime:
        """Build the temporary runtime backed by current code-owned definitions."""
        return cls(
            definition_source=definition_source or CodeOwnedAgentDefinitionSource(),
            model_adapter=model_adapter or DatabricksModelAdapter(),
        )

    def run(
        self,
        agent_key: str,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
    ) -> AgentInvocationResult:
        if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET:
            raise UnknownAgentKeyError(
                f"Unknown model-driven agent key {agent_key!r}; "
                f"expected one of {list(MODEL_DRIVEN_AGENT_KEYS)!r}"
            )

        definition = self._definition_source.resolve(agent_key)
        if definition.agent_key != agent_key:
            raise UnknownAgentKeyError(
                f"Definition source returned {definition.agent_key!r} for requested "
                f"agent key {agent_key!r}"
            )

        protected_prompt = self._protected_prompts.resolve(
            definition.protected_prompt
        )
        schema = self._schema_contracts.resolve(
            agent_key,
            definition.schema_contract,
        )
        prompt = self._assemble_prompt(
            definition,
            protected_prompt,
            payload,
            assembly_context,
        )

        started = time.perf_counter()
        output = self._model_adapter.invoke(
            configuration=definition.model_configuration,
            schema=schema,
            prompt=prompt,
        )
        latency_ms = (time.perf_counter() - started) * 1000

        return AgentInvocationResult(
            output=output,
            diagnostics=AgentInvocationDiagnostics(
                agent_key=agent_key,
                definition_version=definition.definition_version,
                assembled_prompt=prompt,
                model_configuration=definition.model_configuration,
                protected_prompt=definition.protected_prompt,
                schema_contract=definition.schema_contract,
                latency_ms=latency_ms,
            ),
        )

    @staticmethod
    def _assemble_prompt(
        definition: AgentDefinition,
        protected_prompt: _ProtectedPromptBundle,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
    ) -> str:
        instructions = definition.prompt_text
        if definition.agent_key == "build_reviewer" and payload.get("deck_brief"):
            instructions = "\n\n".join(
                [instructions, protected_prompt.build_reviewer_deck_brief]
            )

        parts = [instructions]
        if not assembly_context.design_system_active:
            parts.append(protected_prompt.slide_frame_constraints)
        if assembly_context.design_system_active:
            parts.append(protected_prompt.design_system_precedence)
        parts.append(json.dumps(payload, indent=2, default=str))
        return "\n\n".join(parts)


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime:
    """Return the process-wide immutable compatibility runtime."""
    return AgentRuntime.compatibility()

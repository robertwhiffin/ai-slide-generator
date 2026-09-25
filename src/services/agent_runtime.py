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
import logging
import textwrap
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Protocol, cast

import httpx
import openai
import requests
from databricks.sdk.errors import (
    Aborted,
    DeadlineExceeded,
    InternalError,
    NotFound,
    OperationFailed,
    PermissionDenied,
    ResourceDoesNotExist,
    Unauthenticated,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from src.core.databricks_client import DatabricksClientError
from src.core.defaults import DEFAULT_CONFIG
from src.core.skills import load_skill
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime_identity import (
    AgentInvocationIdentity,
    AgentInvocationIdentitySink,
    LoggingAgentInvocationIdentitySink,
    RecordingAgentInvocationIdentitySink,
)
from src.services.agent_schema_registry import (
    AgentSchemaRegistry,
    SchemaOverlayValidationError,
)
from src.services.agent_schema_types import (
    JsonValue,
    SchemaContractIdentity,
    ValidatedAgentOutput,
    freeze_json_containers,
)
from src.services.graph_configuration_content import GraphConfigurationIntegrityError
from src.services.graph_definition_manifest import (
    AssemblyRules,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
    schema_contract_identity,
)
from src.services.persisted_graph_release import (
    PersistedConfigurationUnavailableError,
    PersistedGraphReleaseLoader,
    PersistedRuntimeError,
    PinnedInvocationEndpointError,
    ResolvedDefinition,
    ResolvedDefinitionLoader,
)
from src.services.prompt_assembler import (
    PromptAssembler,
    PromptAssemblyRejected,
    ProtectedAssemblyBundleUnavailable,
    ResolvedPromptStage,
)

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


class IncompatibleSchemaContractError(AgentRuntimeError):
    """A definition names a schema contract that is not valid for its role."""


class RuntimeContractIdentityError(AgentRuntimeError):
    """Code-owned contract material changed without an explicit identity update."""


class ModelProviderUnavailableError(AgentRuntimeError):
    """A pinned serving endpoint or its transport is unavailable."""


@dataclass(frozen=True)
class ProtectedPromptIdentity:
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
    """The fourth and last argument every production ``run(...)`` call passes.

    ``design_system_active`` steers prompt assembly.  The two session IDs do
    not: ``PromptAssembler`` reads only ``design_system_active`` off this object,
    so they reach the identity sink and nothing else — never the prompt, never
    the model.  They ride here rather than on a fifth parameter because
    ``AgentRuntime.run``'s arity is pinned at four positional arguments and zero
    keywords across all ten call sites by #265's
    ``test_every_production_runtime_call_passes_all_four_pinned_arguments``.
    """

    design_system_active: bool
    # See AgentInvocationIdentity for why these default rather than being required.
    root_session_id: str = ""
    actor_session_id: str = ""


@dataclass(frozen=True)
class AgentDefinition:
    agent_key: str
    definition_version: int
    prompt_text: str
    model_configuration: AgentModelConfiguration
    protected_prompt: ProtectedPromptIdentity
    schema_contract: SchemaContractIdentity
    legacy_tool_grants: tuple[str, ...]
    assembly_rules: AssemblyRules


@dataclass(frozen=True)
class AgentInvocationDiagnostics:
    agent_key: str
    definition_version: int
    assembled_prompt: str
    model_configuration: AgentModelConfiguration
    protected_prompt: ProtectedPromptIdentity
    schema_contract: SchemaContractIdentity
    assembly_stages: tuple[ResolvedPromptStage, ...]
    latency_ms: float
    additional_fields: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the optional projection recursively (#260's standing rule).

        The runtime copies the registry's already-frozen mapping in, so this is
        normally a re-freeze of frozen values.  It is unconditional so that any
        other construction site cannot hand diagnostics a mutable container.
        """
        object.__setattr__(
            self,
            "additional_fields",
            freeze_json_containers(dict(self.additional_fields)),
        )


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
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel: ...


def _canonical_digest(material: Any) -> str:
    serialized = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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


class _SchemaContractRegistry:
    """Fail-closed v1 identity table for the temporary code-owned definition source.

    Resolution moved to the one public ``AgentSchemaRegistry`` in #264 Task 3, so
    this retains only the construction-time digest check and ``identity_for``; it has
    no ``resolve`` any more, which stops an unreachable second contract check from
    reading as a live guard.
    """

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
        persisted_v1 = next(
            definition
            for definition in load_graph_v1_manifest().definitions
            if definition.agent_key == agent_key
        )
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
            assembly_rules=persisted_v1.assembly_rules,
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
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        # ``agent_key`` is deliberately a separate selection seam.  In particular,
        # Build Reviewer and Fix Reviewer have the same output schema.
        del agent_key
        provider_errors = (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.APIStatusError,
            DatabricksClientError,
            NotFound,
            PermissionDenied,
            Unauthenticated,
            ResourceDoesNotExist,
            InternalError,
            Aborted,
            DeadlineExceeded,
            OperationFailed,
            requests.exceptions.RequestException,
            httpx.HTTPError,
            ConnectionError,
            TimeoutError,
            OSError,
        )
        try:
            model = self._model_factory(
                endpoint=configuration.endpoint_name,
                temperature=configuration.temperature,
                max_tokens=configuration.max_tokens,
                top_p=configuration.top_p,
                workspace_client=self._client_factory(),
            )
            structured_model = model.with_structured_output(schema)
            return structured_model.invoke(prompt)
        except provider_errors as original_error:
            raise ModelProviderUnavailableError(
                "pinned model provider unavailable"
            ) from original_error


TEST_COMPATIBILITY_GRAPH_RELEASE_ID = 1
TEST_COMPATIBILITY_GRAPH_VERSION = 1


class CompatibilityResolvedDefinitionLoader:
    """Test-only bridge from legacy code-owned records to persisted content."""

    def __init__(self, source: CodeOwnedAgentDefinitionSource) -> None:
        self._source = source

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        if graph_release_id != TEST_COMPATIBILITY_GRAPH_RELEASE_ID:
            raise ValueError("compatibility runtime requires graph release 1")
        definition = self._source.resolve(agent_key)
        content = DefinitionContent.model_validate(
            {
                "agent_key": definition.agent_key,
                "definition_version": definition.definition_version,
                "prompt_text": definition.prompt_text,
                "model": definition.model_configuration.__dict__,
                "schema_overlay": {
                    "field_overrides": {},
                    "additional_optional_fields": [],
                },
                "assembly_rules": definition.assembly_rules,
                "protected_assembly": definition.protected_prompt.__dict__,
                "schema_contract": {
                    "version": definition.schema_contract.version,
                    "digest": definition.schema_contract.digest,
                },
            }
        )
        return ResolvedDefinition(
            graph_version=TEST_COMPATIBILITY_GRAPH_VERSION,
            graph_release_id=TEST_COMPATIBILITY_GRAPH_RELEASE_ID,
            agent_key=agent_key,
            agent_definition_revision_id=definition.definition_version,
            content_hash=definition_content_hash(content),
            content=content,
        )


def _supplied_output_keys(provider_output: BaseModel) -> Mapping[str, Any]:
    """Convert one provider result into the raw top-level keys it actually supplied.

    ``exclude_unset`` is load-bearing and not a tidiness choice: the registry tells
    an *absent* optional key from an explicitly supplied ``null`` by raw key
    presence, so a field left at its declared ``None`` default must not arrive as
    an explicit null.  ``mode="python"`` keeps native leaves for the re-validation
    that follows rather than stringifying them for a JSON boundary this value never
    crosses.
    """
    return provider_output.model_dump(mode="python", exclude_unset=True)


class AgentRuntime:
    """Resolve and execute one model-driven Agent Definition."""

    def __init__(
        self,
        *,
        persisted_release_loader: ResolvedDefinitionLoader,
        model_adapter: AgentModelAdapter,
        identity_sink: AgentInvocationIdentitySink,
    ) -> None:
        self._persisted_release_loader = persisted_release_loader
        self._model_adapter = model_adapter
        self._identity_sink = identity_sink
        self._prompt_assembler = PromptAssembler()
        self._schema_registry = AgentSchemaRegistry()

    @classmethod
    def compatibility(
        cls,
        *,
        model_adapter: AgentModelAdapter | None = None,
        definition_source: AgentDefinitionSource | None = None,
        identity_sink: AgentInvocationIdentitySink | None = None,
    ) -> AgentRuntime:
        """Build the temporary runtime backed by current code-owned definitions."""
        return cls(
            persisted_release_loader=CompatibilityResolvedDefinitionLoader(
                cast(
                    CodeOwnedAgentDefinitionSource,
                    definition_source or CodeOwnedAgentDefinitionSource(),
                )
            ),
            model_adapter=model_adapter or DatabricksModelAdapter(),
            identity_sink=identity_sink or RecordingAgentInvocationIdentitySink(),
        )

    def run(
        self,
        agent_key: str,
        graph_release_id: int,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
    ) -> AgentInvocationResult:
        try:
            definition = self._persisted_release_loader.resolve(graph_release_id, agent_key)
        except PersistedRuntimeError:
            raise
        except SQLAlchemyError as exc:
            raise PersistedConfigurationUnavailableError(code="lakebase_unavailable") from exc
        except (GraphConfigurationIntegrityError, ValidationError, TypeError) as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc
        return self._run_resolved(definition, payload, assembly_context)

    def _run_resolved(
        self,
        definition: ResolvedDefinition,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
    ) -> AgentInvocationResult:
        try:
            content = DefinitionContent.model_validate(definition.content.model_dump(mode="python"))
            if content.agent_key != definition.agent_key:
                raise ValueError("resolved definition role does not match its content")
            schema_identity = schema_contract_identity(
                definition.agent_key, content.schema_contract
            )
            if schema_identity.version == _SCHEMA_CONTRACT_VERSION and (
                content.schema_overlay.field_overrides
                or content.schema_overlay.additional_optional_fields
            ):
                raise IncompatibleSchemaContractError(
                    "Schema contract version 1 requires an empty schema overlay"
                )
            self._prompt_assembler.resolve_bundle(content.protected_assembly)
            protected_prompt = ProtectedPromptIdentity(
                version=content.protected_assembly.version,
                digest=content.protected_assembly.digest,
            )
            composed = self._schema_registry.compose(
                definition.agent_key, schema_identity, content.schema_overlay
            )
            assembled = self._prompt_assembler.assemble(
                definition=content,
                payload=payload,
                context=assembly_context,
            )
        except ProtectedAssemblyBundleUnavailable as exc:
            raise PersistedConfigurationUnavailableError(
                code="protected_bundle_unavailable"
            ) from exc
        except PromptAssemblyRejected as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc
        except IncompatibleSchemaContractError as exc:
            raise PersistedConfigurationUnavailableError(
                code="schema_contract_unavailable"
            ) from exc
        except SchemaOverlayValidationError as exc:
            if any(
                issue.code == "overlay_schema_contract_unavailable" for issue in exc.issues
            ):
                raise PersistedConfigurationUnavailableError(
                    code="schema_contract_unavailable"
                ) from exc
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc
        except (ValidationError, ValueError, TypeError) as exc:
            raise PersistedConfigurationUnavailableError(
                code="invalid_persisted_definition"
            ) from exc

        configuration = AgentModelConfiguration(
            endpoint_name=content.model.endpoint_name,
            temperature=float(content.model.temperature),
            max_tokens=int(content.model.max_tokens),
            top_p=float(content.model.top_p),
        )
        prompt = assembled.prompt
        identity = AgentInvocationIdentity(
            graph_version=definition.graph_version,
            graph_release_id=definition.graph_release_id,
            agent_key=definition.agent_key,
            agent_definition_revision_id=definition.agent_definition_revision_id,
            content_hash=definition.content_hash,
            # From the context, never from the payload: the release above came
            # from the resolved definition, so the trace records the release the
            # caller pinned and the root/actor pair that caller is acting for.
            root_session_id=assembly_context.root_session_id,
            actor_session_id=assembly_context.actor_session_id,
        )

        def callback() -> ValidatedAgentOutput:
            try:
                provider_output = self._model_adapter.invoke(
                    agent_key=definition.agent_key,
                    configuration=configuration,
                    schema=composed.model,
                    prompt=prompt,
                )
            except ModelProviderUnavailableError as exc:
                raise PinnedInvocationEndpointError(
                    endpoint_name=content.model.endpoint_name,
                    graph_release_id=definition.graph_release_id,
                    agent_definition_revision_id=definition.agent_definition_revision_id,
                ) from exc
            return self._schema_registry.validate_output(
                composed, _supplied_output_keys(provider_output)
            )

        started = time.perf_counter()
        validated = self._identity_sink.invoke(identity, callback)
        latency_ms = (time.perf_counter() - started) * 1000

        return AgentInvocationResult(
            output=validated.canonical_output,
            diagnostics=AgentInvocationDiagnostics(
                agent_key=definition.agent_key,
                definition_version=definition.agent_definition_revision_id,
                assembled_prompt=prompt,
                model_configuration=configuration,
                protected_prompt=protected_prompt,
                schema_contract=schema_identity,
                assembly_stages=assembled.stages,
                latency_ms=latency_ms,
                additional_fields=validated.additional_fields,
            ),
        )


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime:
    """Return the process-wide immutable persisted-release runtime."""
    from src.core.database import get_session_local

    return AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=get_session_local()),
        model_adapter=DatabricksModelAdapter(),
        identity_sink=LoggingAgentInvocationIdentitySink(logger=logging.getLogger(__name__)),
    )

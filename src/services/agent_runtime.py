"""One invocation seam for Tellr's seven model-driven Graph Nodes.

Agent Definitions are resolved only from persisted Graph Releases in Lakebase,
through a :class:`~src.services.persisted_graph_release.ResolvedDefinitionLoader`
(``PersistedGraphReleaseLoader`` in production).  There is no code-owned
definition source: prompt assembly, schema resolution, model construction,
invocation, and diagnostics all live behind :class:`AgentRuntime` and act only on
the resolved, persisted content.

Foreman is deliberately absent.  It is deterministic routing code, not an Agent
Definition, and an attempt to resolve it fails as an unknown model-driven role.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Literal, Protocol

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
from pydantic_core import to_jsonable_python
from sqlalchemy.exc import SQLAlchemyError

from src.core.databricks_client import DatabricksClientError

# ``RecordingAgentInvocationIdentitySink`` is an explicit re-export: tests import
# it from this module (C14).
from src.services.agent_runtime_identity import (
    AgentInvocationIdentity,
    AgentInvocationIdentitySink,
    LoggingAgentInvocationIdentitySink,
)
from src.services.agent_runtime_identity import (
    RecordingAgentInvocationIdentitySink as RecordingAgentInvocationIdentitySink,
)
from src.services.agent_schema_registry import (
    V1_SCHEMA_IDENTITIES,
    AgentOutputValidationError,
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
    DefinitionContent,
    ModelConfiguration,
    definition_content_hash,
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
logger = logging.getLogger(__name__)


class AgentRuntimeError(RuntimeError):
    """Base class for failures at the AgentRuntime interface."""


class UnknownAgentKeyError(AgentRuntimeError):
    """The requested key is not one of the seven model-driven roles."""


class IncompatibleSchemaContractError(AgentRuntimeError):
    """A definition names a schema contract that is not valid for its role."""


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


class AgentModelAdapter(Protocol):
    def invoke(
        self,
        *,
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel: ...


def saved_model_configuration(model: ModelConfiguration) -> AgentModelConfiguration:
    """Convert one saved model record to the configuration a model is built with.

    The runtime and the #266 saved-candidate probe both use this, so a probe
    exercises exactly the sampling values a persisted invocation would.
    """
    return AgentModelConfiguration(
        endpoint_name=model.endpoint_name,
        temperature=float(model.temperature),
        max_tokens=int(model.max_tokens),
        top_p=float(model.top_p),
    )


def bind_structured_output_model(
    *,
    model_factory: Callable[..., Any],
    workspace_client: Any,
    configuration: AgentModelConfiguration,
    schema: type[BaseModel],
    transport_options: Mapping[str, Any] | None = None,
) -> Any:
    """The one structured-output binding seam; it returns the bound model.

    Both ``DatabricksModelAdapter.invoke`` and the #266 saved-candidate probe
    construct their model here, with the exact configured endpoint and the
    caller's runtime-identity ``workspace_client``, then bind ``schema``.  It
    catches nothing: each caller owns its own failure classification, so the
    probe can still tell a permission denial from a transport failure while the
    runtime keeps collapsing both.  ``transport_options`` is a request bound
    for the two admin-request callers only: the #266 probe, and the #267
    test-run adapter built by ``get_agent_test_runtime``.  The production
    runtime adapter passes none.

    Only while a #267 test run's model call is in flight (its ``RunObservation``
    is the observed run) is the bound model given a callback that records the
    provider's reported token usage onto that observation.  The binding itself
    is unchanged — no ``include_raw`` — so parsing and its errors are
    production's; production ``run`` observes nothing and gets exactly
    the plain structured-output binding of ``schema``.
    """
    model = model_factory(
        endpoint=configuration.endpoint_name,
        temperature=configuration.temperature,
        max_tokens=configuration.max_tokens,
        top_p=configuration.top_p,
        workspace_client=workspace_client,
        **(transport_options or {}),
    )
    structured_model = model.with_structured_output(schema)
    observation = _OBSERVED_TEST_RUN.get()
    if observation is None:
        return structured_model
    return structured_model.with_config(callbacks=[_token_usage_callback(observation)])


def _token_count(value: Any) -> int | None:
    """A provider-reported count, or ``None``: only a non-negative ``int`` is a count."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _reported_token_usage(message: Any) -> tuple[int | None, int | None]:
    """The (input, output) token counts one provider message reports, if any.

    ``ChatDatabricks`` (databricks-langchain 0.9.0) leaves LangChain's standard
    ``usage_metadata`` unset and reports the completion's ``usage`` in
    ``response_metadata["usage"]`` (measured over a mock transport, #267 I-1);
    the standard field is still read first, then the OpenAI-style mappings.
    """
    usage_metadata = getattr(message, "usage_metadata", None)
    if isinstance(usage_metadata, Mapping):
        return (
            _token_count(usage_metadata.get("input_tokens")),
            _token_count(usage_metadata.get("output_tokens")),
        )
    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        for key in ("usage", "token_usage"):
            usage = response_metadata.get(key)
            if isinstance(usage, Mapping):
                return (
                    _token_count(usage.get("prompt_tokens")),
                    _token_count(usage.get("completion_tokens")),
                )
    return None, None


def _token_usage_callback(observation: RunObservation) -> Any:
    """A LangChain callback that copies the provider's reported usage onto ``observation``.

    ``langchain_core`` is imported lazily, like the chat model that fires it.
    """
    from langchain_core.callbacks import BaseCallbackHandler

    class _TokenUsageCallback(BaseCallbackHandler):
        def on_llm_end(self, response: Any, **kwargs: Any) -> None:
            del kwargs
            for generations in response.generations:
                for generation in generations:
                    input_tokens, output_tokens = _reported_token_usage(
                        getattr(generation, "message", None)
                    )
                    if input_tokens is not None or output_tokens is not None:
                        _record_token_usage(observation, input_tokens, output_tokens)
                        return

    return _TokenUsageCallback()


class DatabricksModelAdapter:
    """Invoke one structured Databricks model without binding any tools."""

    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] | None = None,
        client_factory: Callable[[], Any] | None = None,
        transport_options: Mapping[str, Any] | None = None,
    ) -> None:
        self._model_factory = model_factory or self._default_model_factory
        self._client_factory = client_factory or self._default_client_factory
        # ``None`` (production) hands the model factory exactly the kwargs it
        # always had; only ``get_agent_test_runtime`` bounds the call (#267 C33).
        self._transport_options = (
            dict(transport_options) if transport_options is not None else None
        )

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
            structured_model = bind_structured_output_model(
                model_factory=self._model_factory,
                workspace_client=self._client_factory(),
                configuration=configuration,
                schema=schema,
                transport_options=self._transport_options,
            )
            return structured_model.invoke(prompt)
        except provider_errors as original_error:
            raise ModelProviderUnavailableError(
                "pinned model provider unavailable"
            ) from original_error


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


#: The identity of a #267 candidate run: a saved DRAFT is no Graph Release and
#: no Agent Definition Revision, so none is claimed.  ``-1`` can never be a real
#: SERIAL id, so a log record or a ``PinnedInvocationEndpointError`` carrying it
#: is unmistakably a candidate run (Correction 27).  These are runtime identity,
#: not loader state, and ``run(-1, ...)`` still fails as an absent release.
CANDIDATE_RUN_GRAPH_VERSION = -1
CANDIDATE_RUN_GRAPH_RELEASE_ID = -1
CANDIDATE_RUN_REVISION_ID = -1

CandidateRunStatus = Literal["completed", "assembly_error", "model_error", "incomplete"]


@dataclass(frozen=True)
class CandidateRunOutcome:
    """What one candidate run produced, with every failure classified.

    ``run_candidate`` raises only for a caller contract violation (an unknown
    role, content for another role, a hash that does not match, a session
    identity).  Everything that happens once the run starts is returned here, so
    a failed run is still evidence rather than an unhandled 500 (#267 C15/C16).

    * ``result`` is set only when ``status == "completed"``.
    * ``raw_output`` is the JSON-safe top-level keys the provider actually
      supplied, observed before ``validate_output``; ``None`` when the provider
      returned nothing (an assembly, provider or parse failure).
    * ``error_detail`` is a code or ``<code>:<endpoint>`` / ``<code>:<Class>``,
      never exception text or provider payload.
    """

    status: CandidateRunStatus
    result: AgentInvocationResult | None
    raw_output: Mapping[str, Any] | None
    error: Exception | None
    error_detail: str | None


class RunObservation:
    """What one #267 test run handed the model, and what came back.

    A public, test-run-only recorder: ``run_candidate`` and
    ``run_published_baseline`` fill it when given one.  ``prompt`` is the exact
    assembled prompt passed to the model adapter (``None`` when assembly failed
    before the call); ``raw_output`` is the JSON-safe top-level keys the provider
    supplied, observed before validation; ``model_latency_ms`` is the adapter
    call's duration, recorded whether it returned or raised.
    ``input_tokens``/``output_tokens`` are the provider's reported usage for
    the call, each ``None`` when the provider reported none (#267 I-1, P9).
    ``run`` never takes one, so production behaviour is unchanged.
    """

    def __init__(self) -> None:
        self.prompt: str | None = None
        self.raw_output: dict[str, Any] | None = None
        self.model_latency_ms: float | None = None
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None


#: The observation of the #267 test run whose model call is in flight, set only
#: around that one adapter call by ``_run_resolved``; ``None`` everywhere else,
#: including every production ``run``.
_OBSERVED_TEST_RUN: ContextVar[RunObservation | None] = ContextVar(
    "observed_test_run", default=None
)


def _record_token_usage(
    observation: RunObservation, input_tokens: Any, output_tokens: Any
) -> None:
    observation.input_tokens = _token_count(input_tokens)
    observation.output_tokens = _token_count(output_tokens)


def report_model_token_usage(*, input_tokens: Any, output_tokens: Any) -> None:
    """Record token usage for the test run whose model call is in flight.

    The seam for a model adapter other than the Databricks one (a test double)
    to report usage exactly as the binding helper's callback does.  Outside an
    observed test-run call it does nothing, so production is unaffected.
    """
    observation = _OBSERVED_TEST_RUN.get()
    if observation is not None:
        _record_token_usage(observation, input_tokens, output_tokens)


def _is_provider_parse_error(error: Exception) -> bool:
    """A structured-output parser rejected the provider's response.

    ``langchain_core`` is imported lazily: the runtime module stays import-light,
    and the chat model that raises this type is itself imported lazily.
    """
    if isinstance(error, ValidationError):
        return True
    try:
        from langchain_core.exceptions import OutputParserException
    except ImportError:  # pragma: no cover - the provider stack is always installed
        return False
    return isinstance(error, OutputParserException)


def classify_test_run_failure(
    error: Exception, *, endpoint_name: str
) -> tuple[CandidateRunStatus, str]:
    """Map one failure out of ``_run_resolved`` to (status, detail) — #267 C16/C33.

    Pre-invocation failures reach here already converted by ``_run_resolved``
    into ``PersistedConfigurationUnavailableError``, so a bare ``ValidationError``
    can only have come from the provider call.
    """
    if isinstance(error, PersistedConfigurationUnavailableError):
        return "assembly_error", error.code
    if isinstance(error, PinnedInvocationEndpointError):
        return "model_error", f"endpoint_unavailable:{endpoint_name}"
    if isinstance(error, NotImplementedError):
        return "model_error", f"structured_output_unsupported:{endpoint_name}"
    if isinstance(error, AgentOutputValidationError) or _is_provider_parse_error(error):
        return "incomplete", f"invalid_output:{type(error).__name__}"
    return "model_error", f"unexpected_error:{type(error).__name__}"


class _PassThroughIdentitySink:
    """Run the callback and record nothing: the sink for a candidate run."""

    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], ValidatedAgentOutput],
    ) -> ValidatedAgentOutput:
        del identity
        return callback()


_PASS_THROUGH_IDENTITY_SINK = _PassThroughIdentitySink()

#: The one log record a candidate run writes, and its EXACT fields: the role,
#: the outcome status, the code part of ``error_detail`` and the exception class
#: name.  No release/revision id (a draft has none), no endpoint, payload, prompt,
#: output or exception text — the #266 probe's standard.
CANDIDATE_RUN_LOG_MESSAGE = "agent_candidate_run"


def _log_candidate_run(agent_key: str, outcome: CandidateRunOutcome) -> None:
    logger.info(
        CANDIDATE_RUN_LOG_MESSAGE,
        extra={
            "agent_key": agent_key,
            "status": outcome.status,
            "error_code": (
                outcome.error_detail.split(":", 1)[0] if outcome.error_detail else None
            ),
            "error_class": (
                type(outcome.error).__name__ if outcome.error is not None else None
            ),
        },
    )


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

    def run(
        self,
        agent_key: str,
        graph_release_id: int,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
    ) -> AgentInvocationResult:
        # The role-key contract is the runtime's, not a loader's: checked before
        # resolution so every loader (the production one did a bare dict lookup)
        # raises the typed error, no session is opened, and it cannot be mapped
        # into a persisted-configuration failure by the handlers below.
        if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET:
            raise UnknownAgentKeyError(
                f"Unknown model-driven agent key {agent_key!r}; "
                f"expected one of {list(MODEL_DRIVEN_AGENT_KEYS)!r}"
            )
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

    def run_candidate(
        self,
        agent_key: str,
        candidate_content: DefinitionContent,
        candidate_hash: str,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
        *,
        observation: RunObservation | None = None,
    ) -> CandidateRunOutcome:
        """Run one saved DRAFT candidate through ``run``'s own private path.

        This is not ``run``: a draft is no release, so nothing is resolved and
        the loader is never touched.  After the caller-contract checks (role,
        then the content's role, then the hash) the candidate is wrapped in the
        sentinel identity and handed to the same ``_run_resolved`` production
        uses — the same revalidation, assembly, schema composition and adapter
        — so its prompt bytes equal production's for the same content.  The
        production identity log is bypassed: the run writes one
        ``agent_candidate_run`` record of its own, carrying the role, status,
        error code and error class only.  Only the #267 test workbench may call
        this (spec §7.1).
        """
        if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET:
            raise UnknownAgentKeyError(
                f"Unknown model-driven agent key {agent_key!r}; "
                f"expected one of {list(MODEL_DRIVEN_AGENT_KEYS)!r}"
            )
        if candidate_content.agent_key != agent_key:
            raise ValueError("candidate_content.agent_key does not match agent_key")
        if definition_content_hash(candidate_content) != candidate_hash:
            raise ValueError("candidate_hash does not match candidate_content")
        if assembly_context.root_session_id or assembly_context.actor_session_id:
            # A test run belongs to no conversation: the identity sink must not
            # be handed a session it could attribute the run to.
            raise ValueError("candidate runs carry no session identity")

        resolved = ResolvedDefinition(
            graph_version=CANDIDATE_RUN_GRAPH_VERSION,
            graph_release_id=CANDIDATE_RUN_GRAPH_RELEASE_ID,
            agent_key=agent_key,
            agent_definition_revision_id=CANDIDATE_RUN_REVISION_ID,
            content_hash=candidate_hash,
            content=candidate_content,
        )
        outcome = self._run_observed(
            resolved,
            payload,
            assembly_context,
            observation=observation,
            # A draft has no release or revision identity, so the runtime's
            # identity sink (the production invocation log) never sees a
            # candidate run (Task 3 ruling R1).  The pass-through sink keeps
            # nothing, so the lru_cached test runtime cannot grow.
            identity_sink=_PASS_THROUGH_IDENTITY_SINK,
        )
        _log_candidate_run(agent_key, outcome)
        return outcome

    def run_published_baseline(
        self,
        agent_key: str,
        graph_release_id: int,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
        *,
        observation: RunObservation | None = None,
    ) -> CandidateRunOutcome:
        """Rerun a published definition for a #267 baseline: ``run``, observed.

        Resolution mirrors ``run`` exactly (the role check, the loader and its
        error mapping, pinned equal to ``run``'s by an AST test), so a loader
        failure raises just as it does from ``run``.  From there it is the same
        ``_run_resolved`` with the production identity sink — a baseline is a
        genuine invocation of published content — and every run failure is
        classified into the outcome instead of raised.  Only the #267 test
        workbench may call this.
        """
        if agent_key not in _MODEL_DRIVEN_AGENT_KEY_SET:
            raise UnknownAgentKeyError(
                f"Unknown model-driven agent key {agent_key!r}; "
                f"expected one of {list(MODEL_DRIVEN_AGENT_KEYS)!r}"
            )
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
        return self._run_observed(
            definition,
            payload,
            assembly_context,
            observation=observation,
            identity_sink=None,
        )

    def _run_observed(
        self,
        definition: ResolvedDefinition,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
        *,
        observation: RunObservation | None,
        identity_sink: AgentInvocationIdentitySink | None,
    ) -> CandidateRunOutcome:
        """``_run_resolved`` with the raw output observed and failures classified."""
        record = observation if observation is not None else RunObservation()

        def observe(raw: Mapping[str, Any]) -> None:
            record.raw_output = to_jsonable_python(dict(raw), fallback=str)

        try:
            result = self._run_resolved(
                definition,
                payload,
                assembly_context,
                _raw_output_observer=observe,
                _identity_sink=identity_sink,
                _observation=record,
            )
        except Exception as error:  # noqa: BLE001 - every run failure is evidence
            status, detail = classify_test_run_failure(
                error, endpoint_name=definition.content.model.endpoint_name
            )
            return CandidateRunOutcome(
                status=status,
                result=None,
                raw_output=record.raw_output,
                error=error,
                error_detail=detail,
            )
        return CandidateRunOutcome(
            status="completed",
            result=result,
            raw_output=record.raw_output,
            error=None,
            error_detail=None,
        )

    def _run_resolved(
        self,
        definition: ResolvedDefinition,
        payload: dict[str, Any],
        assembly_context: AgentAssemblyContext,
        *,
        _raw_output_observer: Callable[[Mapping[str, Any]], None] | None = None,
        _identity_sink: AgentInvocationIdentitySink | None = None,
        _observation: RunObservation | None = None,
    ) -> AgentInvocationResult:
        try:
            content = DefinitionContent.model_validate(definition.content.model_dump(mode="python"))
            if content.agent_key != definition.agent_key:
                raise ValueError("resolved definition role does not match its content")
            schema_identity = schema_contract_identity(
                definition.agent_key, content.schema_contract
            )
            # The registry's frozen v1 contract admits no schema overlay.
            v1_version = V1_SCHEMA_IDENTITIES[definition.agent_key].version
            if schema_identity.version == v1_version and (
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

        configuration = saved_model_configuration(content.model)
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
            # Private and keyword-only, like the raw observer: ``run`` passes
            # none.  A test run records the exact prompt sent and the call's
            # duration, whether the adapter returns or raises (#267 Task 4).
            if _observation is not None:
                _observation.prompt = prompt
            # Only a test run's own call is observed for token usage (I-1).
            usage_scope = (
                _OBSERVED_TEST_RUN.set(_observation) if _observation is not None else None
            )
            invoke_started = time.perf_counter()
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
            finally:
                if usage_scope is not None:
                    _OBSERVED_TEST_RUN.reset(usage_scope)
                if _observation is not None:
                    _observation.model_latency_ms = (
                        time.perf_counter() - invoke_started
                    ) * 1000
            supplied = _supplied_output_keys(provider_output)
            # Private and keyword-only: ``run`` passes none, so production
            # behaviour and error types are unchanged.  A candidate run records
            # the raw keys here, before validation can reject them (#267 C15).
            if _raw_output_observer is not None:
                _raw_output_observer(supplied)
            return self._schema_registry.validate_output(composed, supplied)

        started = time.perf_counter()
        sink = _identity_sink if _identity_sink is not None else self._identity_sink
        validated = sink.invoke(identity, callback)
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


TEST_RUN_TIMEOUT_SECONDS = 120.0
TEST_RUN_MAX_RETRIES = 0


@lru_cache(maxsize=1)
def get_agent_test_runtime() -> AgentRuntime:
    """Return the runtime for #267 test runs: production's, with a bounded call.

    A test run's model call happens inside one admin HTTP request, so it must
    not inherit the provider client's default window of minutes per attempt
    with retries (the defect #266 closed for its probe).  Only the transport is
    bounded; loader, sink, sampling values, prompt and schema are production's.
    It is referenced only by the test workbench and its route (#267 C33).
    """
    from src.core.database import get_session_local

    return AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=get_session_local()),
        model_adapter=DatabricksModelAdapter(
            transport_options={
                "timeout": TEST_RUN_TIMEOUT_SECONDS,
                "max_retries": TEST_RUN_MAX_RETRIES,
            }
        ),
        identity_sink=LoggingAgentInvocationIdentitySink(logger=logging.getLogger(__name__)),
    )

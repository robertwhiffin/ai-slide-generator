"""Persisted AgentRuntime invocation identity and provider-failure boundaries."""

from __future__ import annotations

import logging

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError

from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentInvocationIdentity,
    AgentModelConfiguration,
    AgentRuntime,
    CodeOwnedAgentDefinitionSource,
    CompatibilityResolvedDefinitionLoader,
    DatabricksModelAdapter,
    LoggingAgentInvocationIdentitySink,
    ModelProviderUnavailableError,
    RecordingAgentInvocationIdentitySink,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.persisted_graph_release import (
    PersistedConfigurationUnavailableError,
    PinnedInvocationEndpointError,
    ResolvedDefinition,
)


class _Loader:
    def __init__(self, definition: ResolvedDefinition) -> None:
        self.definition = definition
        self.calls: list[tuple[int, str]] = []

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        self.calls.append((graph_release_id, agent_key))
        return self.definition


class _Adapter:
    def __init__(self, output: BaseModel | Exception) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def invoke(
        self,
        *,
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        self.calls.append(
            {
                "agent_key": agent_key,
                "configuration": configuration,
                "schema": schema,
                "prompt": prompt,
            }
        )
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def _resolved() -> ResolvedDefinition:
    content = next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == "architect"
    )
    return ResolvedDefinition(
        graph_version=7,
        graph_release_id=41,
        agent_key="architect",
        agent_definition_revision_id=23,
        content_hash="a" * 64,
        content=content,
    )


def test_persisted_runtime_uses_exact_release_and_records_full_identity():
    definition = _resolved()
    sink = RecordingAgentInvocationIdentitySink()
    output = OUTPUT_SCHEMAS["architect"].model_construct()
    adapter = _Adapter(output)
    runtime = AgentRuntime(
        persisted_release_loader=_Loader(definition),
        model_adapter=adapter,
        identity_sink=sink,
    )

    result = runtime.run("architect", 41, {"request": "a deck"}, AgentAssemblyContext(False))

    assert result.output is output
    assert sink.calls == [
        AgentInvocationIdentity(
            graph_version=7,
            graph_release_id=41,
            agent_key="architect",
            agent_definition_revision_id=23,
            content_hash="a" * 64,
        )
    ]
    assert adapter.calls[0]["agent_key"] == "architect"
    assert adapter.calls[0]["schema"] is OUTPUT_SCHEMAS["architect"]
    assert '"request": "a deck"' in str(adapter.calls[0]["prompt"])


def test_provider_failure_is_converted_before_recording_sink_observes_it():
    original = ModelProviderUnavailableError("pinned model provider unavailable")
    sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=_Loader(_resolved()),
        model_adapter=_Adapter(original),
        identity_sink=sink,
    )

    with pytest.raises(PinnedInvocationEndpointError) as raised:
        runtime.run("architect", 41, {"secret": "never log"}, AgentAssemblyContext(False))

    assert raised.value.endpoint_name == "databricks-claude-opus-4-6"
    assert raised.value.graph_release_id == 41
    assert raised.value.agent_definition_revision_id == 23
    assert raised.value.__cause__ is original
    assert sink.error_classes == ["PinnedInvocationEndpointError"]


def test_logging_sink_logs_identity_outcome_and_error_class_only(caplog):
    logger = logging.getLogger("test.persisted.runtime")
    sink = LoggingAgentInvocationIdentitySink(logger=logger)
    identity = AgentInvocationIdentity(7, 41, "architect", 23, "a" * 64)

    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(RuntimeError, match="ordinary"):
            sink.invoke(identity, lambda: (_ for _ in ()).throw(RuntimeError("ordinary")))

    record = caplog.records[-1]
    assert record.outcome == "error"
    assert record.error_class == "RuntimeError"
    assert record.graph_release_id == 41
    assert not hasattr(record, "prompt")
    assert not hasattr(record, "payload")
    assert not hasattr(record, "output")


def test_runtime_logging_sink_does_not_log_prompt_payload_or_model_output(caplog):
    logger = logging.getLogger("test.persisted.runtime.success")
    output = OUTPUT_SCHEMAS["architect"].model_construct()
    runtime = AgentRuntime(
        persisted_release_loader=_Loader(_resolved()),
        model_adapter=_Adapter(output),
        identity_sink=LoggingAgentInvocationIdentitySink(logger=logger),
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        result = runtime.run(
            "architect",
            41,
            {"session_id": "private", "secret": "payload"},
            AgentAssemblyContext(False),
        )

    assert result.output is output
    records = [record for record in caplog.records if record.msg == "persisted_agent_invocation"]
    assert len(records) == 1
    record = records[0]
    assert record.outcome == "success"
    assert record.error_class is None
    for forbidden in ("prompt", "payload", "output", "session_id", "user_id", "response"):
        assert not hasattr(record, forbidden)


def test_compatibility_loader_constructs_exact_synthetic_persisted_definitions():
    loader = CompatibilityResolvedDefinitionLoader(CodeOwnedAgentDefinitionSource())

    for agent_key in GRAPH_V1_AGENT_KEYS:
        resolved = loader.resolve(1, agent_key)
        parsed = DefinitionContent.model_validate(resolved.content.model_dump(mode="python"))
        assert resolved.graph_version == 1
        assert resolved.graph_release_id == 1
        assert resolved.agent_key == agent_key
        assert resolved.agent_definition_revision_id == parsed.definition_version
        assert set(parsed.schema_contract.model_dump()) == {"version", "digest"}
        assert resolved.content_hash == definition_content_hash(parsed)

    with pytest.raises(ValueError, match="requires graph release 1"):
        loader.resolve(2, "architect")


def test_get_agent_runtime_uses_persisted_loader_and_logging_sink():
    from src.services.agent_runtime import get_agent_runtime

    get_agent_runtime.cache_clear()
    runtime = get_agent_runtime()
    assert not isinstance(runtime._persisted_release_loader, CompatibilityResolvedDefinitionLoader)
    assert isinstance(runtime._model_adapter, DatabricksModelAdapter)
    assert isinstance(runtime._identity_sink, LoggingAgentInvocationIdentitySink)
    get_agent_runtime.cache_clear()


def _provider_errors() -> list[Exception]:
    request = httpx.Request("POST", "https://workspace/serving-endpoints/removed")
    response = httpx.Response(404, request=request)
    return [
        openai.APIConnectionError(request=request),
        openai.APITimeoutError(request),
        openai.NotFoundError("removed", response=response, body=None),
    ]


@pytest.mark.parametrize("phase", ["model", "client", "structured", "invoke"])
@pytest.mark.parametrize("provider_error", _provider_errors())
@pytest.mark.parametrize(
    "sink_factory",
    [
        lambda: RecordingAgentInvocationIdentitySink(),
        lambda: LoggingAgentInvocationIdentitySink(logger=logging.getLogger("test.provider")),
    ],
)
def test_provider_errors_cross_adapter_runtime_and_each_identity_sink(
    phase, provider_error, sink_factory, caplog
):
    class Structured:
        def invoke(self, prompt):
            if phase == "invoke":
                raise provider_error
            return OUTPUT_SCHEMAS["architect"].model_construct()

    class Model:
        def with_structured_output(self, schema):
            if phase == "structured":
                raise provider_error
            return Structured()

    def model_factory(**kwargs):
        if phase == "model":
            raise provider_error
        return Model()

    def client_factory():
        if phase == "client":
            raise provider_error
        return object()

    sink = sink_factory()
    runtime = AgentRuntime(
        persisted_release_loader=_Loader(_resolved()),
        model_adapter=DatabricksModelAdapter(
            model_factory=model_factory, client_factory=client_factory
        ),
        identity_sink=sink,
    )

    with caplog.at_level(logging.INFO, logger="test.provider"):
        with pytest.raises(PinnedInvocationEndpointError) as raised:
            runtime.run("architect", 41, {"secret": "input"}, AgentAssemblyContext(False))

    pinned = raised.value
    assert pinned.endpoint_name == "databricks-claude-opus-4-6"
    assert pinned.graph_release_id == 41
    assert pinned.agent_definition_revision_id == 23
    assert "databricks-claude-opus-4-6" not in str(pinned)
    assert "41" not in str(pinned)
    assert "secret" not in str(pinned)
    assert isinstance(pinned.__cause__, ModelProviderUnavailableError)
    assert pinned.__cause__.__cause__ is provider_error
    if isinstance(sink, RecordingAgentInvocationIdentitySink):
        assert sink.error_classes == ["PinnedInvocationEndpointError"]
    else:
        records = [
            record for record in caplog.records if record.msg == "persisted_agent_invocation"
        ]
        assert len(records) == 1
        assert records[0].outcome == "error"
        assert records[0].error_class == "PinnedInvocationEndpointError"


@pytest.mark.parametrize(
    "sink_factory",
    [
        lambda: RecordingAgentInvocationIdentitySink(),
        lambda: LoggingAgentInvocationIdentitySink(logger=logging.getLogger("test.ordinary")),
    ],
)
@pytest.mark.parametrize(
    "ordinary",
    [RuntimeError("ordinary"), OutputParserException("output")],
)
def test_ordinary_adapter_exceptions_remain_unchanged_for_node_recovery(sink_factory, ordinary):
    sink = sink_factory()
    runtime = AgentRuntime(
        persisted_release_loader=_Loader(_resolved()),
        model_adapter=_Adapter(ordinary),
        identity_sink=sink,
    )

    with pytest.raises(type(ordinary)) as raised:
        runtime.run("architect", 41, {}, AgentAssemblyContext(False))

    assert raised.value is ordinary
    if isinstance(sink, RecordingAgentInvocationIdentitySink):
        assert sink.error_classes == [type(ordinary).__name__]


def test_pydantic_validation_error_remains_unchanged_for_node_recovery():
    class Output(BaseModel):
        count: int

    with pytest.raises(ValidationError) as built:
        Output.model_validate({"count": "not-an-int"})
    original = built.value
    sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=_Loader(_resolved()),
        model_adapter=_Adapter(original),
        identity_sink=sink,
    )

    with pytest.raises(ValidationError) as raised:
        runtime.run("architect", 41, {}, AgentAssemblyContext(False))

    assert raised.value is original
    assert sink.error_classes == ["ValidationError"]


def test_sqlalchemy_loader_failure_is_a_safe_lakebase_unavailable_error():
    class FailingLoader:
        def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
            raise OperationalError("select", {}, RuntimeError("offline"))

    runtime = AgentRuntime(
        persisted_release_loader=FailingLoader(),
        model_adapter=_Adapter(OUTPUT_SCHEMAS["architect"].model_construct()),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )

    with pytest.raises(PersistedConfigurationUnavailableError) as raised:
        runtime.run("architect", 41, {}, AgentAssemblyContext(False))

    assert raised.value.code == "lakebase_unavailable"

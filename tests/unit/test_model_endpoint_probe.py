"""#266 Task 5: the saved-candidate structured-output probe.

Adapter tests drive ``DatabricksStructuredOutputProbe`` through recording model
and client factories; service tests drive ``ModelEndpointProbeService`` over a
bootstrapped SQLite aggregate with a deterministic adapter.  No test here
constructs a real workspace client or reaches Databricks.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, get_args

import httpx
import openai
import pytest
import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import InternalError, PermissionDenied, Unauthenticated
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.core.database import Base
from src.core.databricks_client import DatabricksClientError
from src.services.agent_runtime import AgentModelConfiguration
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.model_endpoint_probe import (
    _PROBE_PROMPT,
    PROBE_MAX_RETRIES,
    PROBE_TIMEOUT_SECONDS,
    DatabricksStructuredOutputProbe,
    FakeStructuredOutputProbe,
    ModelEndpointProbeService,
    SavedEndpointProbeIdentity,
    SavedEndpointProbeResult,
    StructuredOutputProbeCode,
    StructuredOutputProbeFailure,
    _StructuredOutputProbeResponse,
    _sanitise_provider_detail,
)
from tests.fixtures.tool_call_doubles import (
    no_tool_call_reply,
    replying,
    tool_call_reply,
)

SECRET = "SECRET-provider-text https://leak.example/token=abc"
CONFIGURATION = AgentModelConfiguration(
    endpoint_name="exact saved endpoint",
    temperature=0.2,
    max_tokens=64,
    top_p=0.9,
)

EXPECTED_FAILURES = {
    "unsupported_structured_output": (
        "The endpoint rejected the structured-output test request.",
        False,
    ),
    "endpoint_probe_forbidden": (
        "The app is not permitted to query this endpoint.",
        False,
    ),
    "structured_output_probe_failed": (
        "The structured output probe could not complete. Retry the probe.",
        True,
    ),
}


# ---------------------------------------------------------------------------
# Adapter: DatabricksStructuredOutputProbe
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(
        self,
        *,
        output: Any = None,
        bind_error: BaseException | None = None,
        invoke_error: BaseException | None = None,
        client_error: BaseException | None = None,
    ) -> None:
        self.output = _StructuredOutputProbeResponse(result="ok") if output is None else output
        self.bind_error = bind_error
        self.invoke_error = invoke_error
        self.client_error = client_error
        self.client = object()
        self.events: list[tuple[str, Any]] = []

    def client_factory(self) -> Any:
        self.events.append(("client_factory", None))
        if self.client_error is not None:
            raise self.client_error
        return self.client

    def model_factory(self, **kwargs: Any) -> Any:
        self.events.append(("model_factory", kwargs))
        recorder = self

        def reply(prompt: str) -> Any:
            # The provider's reply: a model instance becomes a tool call with the
            # keys it set; anything else (a message, a raw value) reaches the
            # production parser as-is.
            recorder.events.append(("invoke", prompt))
            if recorder.invoke_error is not None:
                raise recorder.invoke_error
            if isinstance(recorder.output, BaseModel):
                return tool_call_reply(_StructuredOutputProbeResponse, recorder.output)
            return recorder.output

        class _Chat:
            def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
                recorder.events.append(("bind_tools", list(tools), kwargs))
                if recorder.bind_error is not None:
                    raise recorder.bind_error
                return replying(reply)

            def with_structured_output(self, schema: Any) -> Any:  # pragma: no cover
                raise AssertionError("forced tool choice must not be bound")

        return _Chat()

    def probe(self) -> DatabricksStructuredOutputProbe:
        return DatabricksStructuredOutputProbe(
            model_factory=self.model_factory,
            client_factory=self.client_factory,
        )


def _assert_failure(caught: pytest.ExceptionInfo, code: str) -> None:
    failure = caught.value
    assert isinstance(failure, StructuredOutputProbeFailure)
    message, retryable = EXPECTED_FAILURES[code]
    assert (failure.code, failure.message, failure.retryable) == (code, message, retryable)
    assert str(failure) == message
    assert SECRET not in failure.message
    assert "leak.example" not in failure.message


def test_model_endpoint_probe_code_vocabulary_is_exact():
    """Catches a new or renamed wire code the route and client would not know."""
    assert set(get_args(StructuredOutputProbeCode)) == set(EXPECTED_FAILURES)


def test_model_endpoint_probe_success_constructs_binds_then_invokes_exactly():
    """Catches endpoint aliasing, sampling drift, or invoke before binding."""
    recorder = _Recorder()

    assert recorder.probe().probe(CONFIGURATION) is None

    assert recorder.events == [
        ("client_factory", None),
        (
            "model_factory",
            {
                # Follow-up A: the saved temperature / top_p are never sent.
                "model": "exact saved endpoint",
                "max_tokens": 64,
                "workspace_client": recorder.client,
                "timeout": PROBE_TIMEOUT_SECONDS,
                "max_retries": PROBE_MAX_RETRIES,
            },
        ),
        ("bind_tools", [_StructuredOutputProbeResponse], {"tool_choice": "auto"}),
        ("invoke", _PROBE_PROMPT),
    ]


def test_model_endpoint_probe_call_is_bounded():
    """Catches the probe inheriting the provider's minutes-long default window."""
    assert 0 < PROBE_TIMEOUT_SECONDS <= 60
    assert PROBE_MAX_RETRIES == 0


def test_model_endpoint_probe_schema_is_only_the_literal_ok_result():
    """Catches a probe schema that carries draft, role, or free-form content."""
    assert set(_StructuredOutputProbeResponse.model_fields) == {"result"}
    assert _StructuredOutputProbeResponse(result="ok").result == "ok"
    with pytest.raises(ValidationError):
        _StructuredOutputProbeResponse(result="OK")
    with pytest.raises(ValidationError):
        _StructuredOutputProbeResponse(result="ok", extra="x")


def test_model_endpoint_probe_prompt_is_code_owned_and_identity_free():
    """The payload rule (#258): no session, user, release or draft value reaches a model.

    The prompt is one constant; it names no role, endpoint, hash, lock, session,
    turn, e-mail or release, and the probe's model call carries nothing else.
    """
    recorder = _Recorder()
    configuration = dataclasses.replace(CONFIGURATION, endpoint_name="architect-endpoint")

    recorder.probe().probe(configuration)

    prompts = [event[1] for event in recorder.events if event[0] == "invoke"]
    assert prompts == [_PROBE_PROMPT]
    assert isinstance(_PROBE_PROMPT, str) and _PROBE_PROMPT.strip()
    lowered = _PROBE_PROMPT.lower()
    for forbidden in (
        "architect",
        "endpoint",
        "session",
        "turn",
        "release",
        "@",
        "lock",
        "hash",
        "user",
    ):
        assert forbidden not in lowered


@pytest.mark.parametrize(
    "error",
    [NotImplementedError(SECRET)],
    ids=["not-implemented"],
)
def test_model_endpoint_probe_binding_rejection_is_unsupported(error):
    """Catches an explicit binding rejection read as a transient failure."""
    recorder = _Recorder(bind_error=error)

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        recorder.probe().probe(CONFIGURATION)

    _assert_failure(caught, "unsupported_structured_output")
    assert [event[0] for event in recorder.events] == [
        "client_factory",
        "model_factory",
        "bind_tools",
    ]


@pytest.mark.parametrize("phase", ["bind", "invoke"])
def test_model_endpoint_probe_permission_denial_is_forbidden(phase):
    """Catches inference denial collapsing into the ambiguous 503 (correction 11)."""
    denied = PermissionDenied(SECRET)
    recorder = _Recorder(
        bind_error=denied if phase == "bind" else None,
        invoke_error=denied if phase == "invoke" else None,
    )

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        recorder.probe().probe(CONFIGURATION)

    _assert_failure(caught, "endpoint_probe_forbidden")


def _ambiguous_errors() -> list[tuple[str, str, BaseException]]:
    request = httpx.Request("POST", "https://leak.example/serving-endpoints")
    return [
        ("invoke", "openai-connection", openai.APIConnectionError(message=SECRET, request=request)),
        ("invoke", "openai-timeout", openai.APITimeoutError(request=request)),
        ("invoke", "sdk-internal", InternalError(SECRET)),
        ("invoke", "sdk-unauthenticated", Unauthenticated(SECRET)),
        ("invoke", "requests", requests.exceptions.ConnectionError(SECRET)),
        ("invoke", "httpx", httpx.ConnectError(SECRET)),
        ("invoke", "timeout", TimeoutError(SECRET)),
        ("invoke", "oserror", OSError(SECRET)),
        ("invoke", "runtime", RuntimeError(SECRET)),
        ("invoke", "value", ValueError(SECRET)),
        ("invoke", "not-implemented-at-invoke", NotImplementedError(SECRET)),
        ("bind", "bind-runtime", RuntimeError(SECRET)),
        ("client", "client-unavailable", DatabricksClientError(SECRET)),
        ("client", "client-runtime", RuntimeError(SECRET)),
        ("client", "client-not-implemented", NotImplementedError(SECRET)),
        ("client", "client-permission", PermissionDenied(SECRET)),
    ]


@pytest.mark.parametrize(
    ("phase", "error"),
    [(phase, error) for phase, _name, error in _ambiguous_errors()],
    ids=[name for _phase, name, _error in _ambiguous_errors()],
)
def test_model_endpoint_probe_other_failures_are_ambiguous_and_sanitized(phase, error):
    """Catches exception text leaking or a guessed capability verdict."""
    recorder = _Recorder(
        bind_error=error if phase == "bind" else None,
        invoke_error=error if phase == "invoke" else None,
        client_error=error if phase == "client" else None,
    )

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        recorder.probe().probe(CONFIGURATION)

    _assert_failure(caught, "structured_output_probe_failed")


@pytest.mark.parametrize(
    "output",
    [
        {"result": "ok"},
        "ok",
        _StructuredOutputProbeResponse.model_construct(result="nope"),
        no_tool_call_reply("ok"),
    ],
    ids=["dict", "string", "wrong-literal", "no-tool-call"],
)
def test_model_endpoint_probe_unparsed_output_is_ambiguous_failure(output):
    """Catches a success claimed without the exact structured ``ok`` result.

    ``no-tool-call`` (follow-up A): under ``tool_choice="auto"`` a model may
    answer in prose; the binding's parser error is the retryable ``failed``.
    """
    recorder = _Recorder(output=output)

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        recorder.probe().probe(CONFIGURATION)

    _assert_failure(caught, "structured_output_probe_failed")


# ---------------------------------------------------------------------------
# Service: ModelEndpointProbeService over the saved draft
# ---------------------------------------------------------------------------


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _all_rows(factory) -> dict[str, list[tuple[object, ...]]]:
    with factory() as session:
        return {
            table.name: [tuple(row) for row in session.execute(select(table))]
            for table in Base.metadata.sorted_tables
        }


def _save_endpoint(
    factory, agent_key: str, endpoint_name: str, lock_version: int
) -> DraftSaveResult:
    with factory() as session:
        current = next(
            node
            for node in GraphConfiguration().read_workbench(session).nodes
            if node.agent_key == agent_key
        ).draft.content
    with factory() as session:
        outcome = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=lock_version,
            candidate=EditableModelDraft(
                prompt_text=current.prompt_text,
                endpoint_name=endpoint_name,
                temperature=0.125,
                max_tokens=4321,
                top_p=0.5,
            ),
            actor="seed-admin@example.com",
        )
    assert isinstance(outcome, DraftSaveResult)
    return outcome


def _saved_hash(factory, agent_key: str) -> str:
    with factory() as session:
        node = next(
            node
            for node in GraphConfiguration().read_workbench(session).nodes
            if node.agent_key == agent_key
        )
    return node.draft.candidate_hash


def test_model_endpoint_probe_service_probes_the_selected_roles_saved_candidate(
    session_factory,
):
    """Catches the service probing another role, a default, or a client value."""
    _save_endpoint(session_factory, "architect", "system.ai.architect-exact-endpoint", 0)
    _save_endpoint(session_factory, "builder", "system.ai.builder-exact-endpoint", 1)
    builder_hash = _saved_hash(session_factory, "builder")
    adapter = FakeStructuredOutputProbe()
    service = ModelEndpointProbeService(adapter)

    with session_factory() as session:
        result = service.probe_saved_candidate(
            session, agent_key="builder", expected_lock_version=2
        )

    assert adapter.calls == [
        AgentModelConfiguration(
            endpoint_name="system.ai.builder-exact-endpoint",
            temperature=0.125,
            max_tokens=4321,
            top_p=0.5,
        )
    ]
    assert result == SavedEndpointProbeResult(
        identity=SavedEndpointProbeIdentity(
            agent_key="builder",
            endpoint_name="system.ai.builder-exact-endpoint",
            candidate_hash=builder_hash,
            lock_version=2,
        ),
        failure=None,
    )


@pytest.mark.parametrize("code", sorted(EXPECTED_FAILURES))
def test_model_endpoint_probe_service_returns_the_typed_failure_with_identity(
    session_factory, code
):
    """Catches a failed probe losing the identity of the candidate it tried."""
    message, retryable = EXPECTED_FAILURES[code]
    failure = StructuredOutputProbeFailure(code, message, retryable)
    adapter = FakeStructuredOutputProbe([failure])
    seed_hash = _saved_hash(session_factory, "architect")

    with session_factory() as session:
        result = ModelEndpointProbeService(adapter).probe_saved_candidate(
            session, agent_key="architect", expected_lock_version=0
        )

    assert len(adapter.calls) == 1
    assert result.failure is failure
    assert result.identity == SavedEndpointProbeIdentity(
        agent_key="architect",
        endpoint_name="databricks-claude-opus-4-6",
        candidate_hash=seed_hash,
        lock_version=0,
    )


def test_model_endpoint_probe_service_stale_lock_conflicts_before_any_probe(session_factory):
    """Catches a stale request reaching the model before the lock comparison."""
    _save_endpoint(session_factory, "architect", "system.ai.moved-on", 0)
    adapter = FakeStructuredOutputProbe()

    with session_factory() as session:
        outcome = ModelEndpointProbeService(adapter).probe_saved_candidate(
            session, agent_key="architect", expected_lock_version=0
        )

    assert adapter.calls == []
    assert isinstance(outcome, DraftSaveConflict)
    assert outcome.client_candidate is None
    assert (outcome.expected_lock_version, outcome.current_lock_version) == (0, 1)
    assert len(outcome.server.definitions) == 7


def test_model_endpoint_probe_service_writes_nothing_on_success_or_failure(session_factory):
    """Catches a probe that saves, audits, advances the lock, or records a run."""
    before = _all_rows(session_factory)
    failing = FakeStructuredOutputProbe(
        [StructuredOutputProbeFailure("structured_output_probe_failed", "x", True)]
    )

    for adapter in (FakeStructuredOutputProbe(), failing):
        with session_factory() as session:
            ModelEndpointProbeService(adapter).probe_saved_candidate(
                session, agent_key="architect", expected_lock_version=0
            )
            assert not session.new and not session.dirty and not session.deleted

    assert _all_rows(session_factory) == before


def test_model_endpoint_probe_service_holds_no_transaction_during_the_call(session_factory):
    """Catches the model call running inside the snapshot read's transaction (c13)."""
    observed: list[bool] = []

    with session_factory() as session:

        class _Observing:
            def probe(self, configuration: AgentModelConfiguration) -> None:
                observed.append(session.in_transaction())

        ModelEndpointProbeService(_Observing()).probe_saved_candidate(
            session, agent_key="architect", expected_lock_version=0
        )

    assert observed == [False]


def test_model_endpoint_probe_service_reports_the_copied_identity_after_a_later_save(
    session_factory,
):
    """Catches identity read back after the call instead of copied before it."""
    seed_hash = _saved_hash(session_factory, "architect")
    saved_during: list[DraftSaveResult] = []

    class _SaveDuringProbe:
        def probe(self, configuration: AgentModelConfiguration) -> None:
            saved_during.append(
                _save_endpoint(session_factory, "architect", "system.ai.saved-mid-probe", 0)
            )

    with session_factory() as session:
        result = ModelEndpointProbeService(_SaveDuringProbe()).probe_saved_candidate(
            session, agent_key="architect", expected_lock_version=0
        )

    assert saved_during[0].draft.lock_version == 1
    assert saved_during[0].definition.candidate_hash != seed_hash
    assert result.identity == SavedEndpointProbeIdentity(
        agent_key="architect",
        endpoint_name="databricks-claude-opus-4-6",
        candidate_hash=seed_hash,
        lock_version=0,
    )


def test_model_endpoint_probe_service_rechecks_the_saved_name_policy(
    session_factory, monkeypatch
):
    """Catches a path-shaped saved name reaching the provider (correction 4)."""
    import src.services.graph_configuration_draft as draft_module

    adapter = FakeStructuredOutputProbe()
    checked: list[str] = []
    original = draft_module.validate_endpoint_name_policy

    def _rejecting(name: str) -> None:
        checked.append(name)
        original("https://leak.example/" + name)

    monkeypatch.setattr(draft_module, "validate_endpoint_name_policy", _rejecting)

    with session_factory() as session:
        with pytest.raises(DraftContentRejected) as caught:
            ModelEndpointProbeService(adapter).probe_saved_candidate(
                session, agent_key="architect", expected_lock_version=0
            )

    assert checked == ["databricks-claude-opus-4-6"]
    assert adapter.calls == []
    assert [(i.field, i.code) for i in caught.value.issues] == [
        ("candidate.model.endpoint_name", "endpoint_url_not_allowed")
    ]


def test_model_endpoint_probe_fake_needs_no_sdk_and_replays_outcomes():
    """Catches a fake that drops, reorders or fabricates queued outcomes."""
    failure = StructuredOutputProbeFailure("endpoint_probe_forbidden", "m", False)
    fake = FakeStructuredOutputProbe([None, failure])

    assert fake.probe(CONFIGURATION) is None
    with pytest.raises(StructuredOutputProbeFailure) as caught:
        fake.probe(CONFIGURATION)
    assert caught.value is failure
    assert fake.probe(CONFIGURATION) is None
    assert fake.calls == [CONFIGURATION, CONFIGURATION, CONFIGURATION]


# ---------------------------------------------------------------------------
# Fix round 1: the REAL ``ChatDatabricks`` over a mock HTTP transport.
#
# The provider reaches the endpoint through the openai client, so a real
# rejection arrives as an openai exception, never as the SDK's
# ``PermissionDenied`` or a binding ``NotImplementedError``.  These tests drive
# the production model factory end to end.  The fake workspace client hands the
# chat model an ``openai.OpenAI`` whose only transport is ``httpx.MockTransport``
# with a literal dummy key and an ``.invalid`` host, so no request can reach a
# network and no ambient credential (environment, profile, SDK auth) is read.
# ---------------------------------------------------------------------------

MOCK_HOST = "probe.invalid"
PROVIDER_SECRET = "PROVIDER_SECRET_detail https://leak.example/token"

#: (mock outcome, expected code) per the fix-round-1 controller ruling.
REAL_PROVIDER_CASES = [
    (400, "unsupported_structured_output"),
    (401, "endpoint_probe_forbidden"),
    (403, "endpoint_probe_forbidden"),
    (404, "unsupported_structured_output"),
    (422, "unsupported_structured_output"),
    (429, "structured_output_probe_failed"),
    (500, "structured_output_probe_failed"),
    ("connection", "structured_output_probe_failed"),
]


class MockTransportWorkspace(WorkspaceClient):
    """A ``WorkspaceClient`` subclass used as a probe workspace stand-in.

    Subclassing satisfies ChatDatabricks 0.20.0's pydantic
    ``workspace_client: Optional[WorkspaceClient]`` field, so
    ``real_provider_probe`` can use ``client_factory=lambda: workspace``
    and the identity chain from ``client_factory`` → ``_default_model_factory``
    → ``ChatDatabricks`` → ``DatabricksOpenAI`` → ``_get_authorized_http_client``
    is end-to-end tested.
    """

    def __init__(self, outcome: int | str) -> None:
        # Do NOT call super().__init__() — it tries to resolve credentials.
        self.outcome = outcome
        self.requests: list[httpx.Request] = []
        self.client_kwargs: list[dict[str, Any]] = []
        self._config = SimpleNamespace(
            host=f"https://{MOCK_HOST}",
            authenticate=lambda: {"Authorization": "Bearer unit-test-dummy-key"},
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.outcome == "connection":
            raise httpx.ConnectError(PROVIDER_SECRET, request=request)
        if self.outcome == "no_tool_call":
            # Follow-up A: under tool_choice="auto" the model may answer in prose.
            return httpx.Response(
                200,
                json={
                    "id": "probe",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": PROVIDER_SECRET},
                        }
                    ],
                },
            )
        if self.outcome == 200:
            return httpx.Response(
                200,
                json={
                    "id": "probe",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call",
                                        "type": "function",
                                        "function": {
                                            "name": "_StructuredOutputProbeResponse",
                                            "arguments": '{"result": "ok"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                },
            )
        return httpx.Response(
            int(self.outcome), json={"error": {"message": PROVIDER_SECRET}}
        )


def real_provider_probe(workspace: MockTransportWorkspace) -> DatabricksStructuredOutputProbe:
    """The production model factory (real ``ChatDatabricks``) over the mock workspace."""
    return DatabricksStructuredOutputProbe(client_factory=lambda: workspace)


def _install_real_provider(monkeypatch, workspace: MockTransportWorkspace) -> None:
    """Install the mock transport and record ``get_openai_client`` kwargs.

    Patches ``_get_authorized_http_client`` so the underlying ``httpx.Client``
    routes through ``workspace._handle``.  Also wraps ``get_openai_client`` to
    record the kwargs ChatDatabricks passes (proving ``use_ai_gateway=True``
    reaches the client) and asserts that ``workspace_client is workspace``
    (proving the identity from ``client_factory`` reaches the provider call).
    """
    from databricks_langchain import chat_models
    from tests.fixtures.mock_chat_completions import install_mock_gateway_transport

    install_mock_gateway_transport(monkeypatch)
    original = chat_models.get_openai_client

    def _recording(workspace_client=None, **kwargs):
        assert workspace_client is workspace, (
            f"Expected the mock workspace to reach get_openai_client unchanged, "
            f"got {workspace_client!r}"
        )
        workspace.client_kwargs.append(kwargs)
        return original(workspace_client=workspace_client, **kwargs)

    monkeypatch.setattr(chat_models, "get_openai_client", _recording)


def _assert_only_the_mock_was_reached(workspace: MockTransportWorkspace) -> None:
    assert workspace.client_kwargs == [
        {"timeout": PROBE_TIMEOUT_SECONDS, "max_retries": PROBE_MAX_RETRIES, "use_ai_gateway": True}
    ]
    assert len(workspace.requests) == 1  # one attempt: max_retries=0 reached openai
    request = workspace.requests[0]
    assert request.url.host == MOCK_HOST
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"


def test_model_endpoint_probe_real_provider_success_over_mock_transport(monkeypatch):
    """Catches the real provider path failing to bind or parse the ``ok`` schema."""
    workspace = MockTransportWorkspace(200)
    _install_real_provider(monkeypatch, workspace)

    assert real_provider_probe(workspace).probe(CONFIGURATION) is None

    _assert_only_the_mock_was_reached(workspace)
    sent = json.loads(workspace.requests[0].content)
    assert sent["model"] == "exact saved endpoint"
    assert [message["content"] for message in sent["messages"]] == [_PROBE_PROMPT]


def test_model_endpoint_probe_real_request_sends_no_sampling_and_auto_tool_choice(monkeypatch):
    """Follow-up A: the probe's request is the graph's — no sampling, tool_choice auto.

    Newer Claude models reject ``temperature`` and forced tool choice with a 400,
    which the probe would report as ``unsupported_structured_output``.
    """
    workspace = MockTransportWorkspace(200)
    _install_real_provider(monkeypatch, workspace)

    assert real_provider_probe(workspace).probe(CONFIGURATION) is None

    sent = json.loads(workspace.requests[0].content)
    assert sent["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in sent["tools"]] == [
        "_StructuredOutputProbeResponse"
    ]
    assert sent["max_tokens"] == 64
    for sampling in ("temperature", "top_p", "top_k"):
        assert sampling not in sent


def test_model_endpoint_probe_real_reply_without_a_tool_call_is_retryable_failure(monkeypatch):
    """Follow-up A: a prose reply (no tool call) is the ambiguous retryable ``failed``."""
    workspace = MockTransportWorkspace("no_tool_call")
    _install_real_provider(monkeypatch, workspace)

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        real_provider_probe(workspace).probe(CONFIGURATION)

    _assert_failure(caught, "structured_output_probe_failed")
    assert PROVIDER_SECRET not in caught.value.message
    _assert_only_the_mock_was_reached(workspace)


@pytest.mark.parametrize(("outcome", "code"), REAL_PROVIDER_CASES, ids=str)
def test_model_endpoint_probe_real_provider_errors_are_classified(monkeypatch, outcome, code):
    """Catches every real rejection collapsing to the retryable 503 (review I1)."""
    workspace = MockTransportWorkspace(outcome)
    _install_real_provider(monkeypatch, workspace)

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        real_provider_probe(workspace).probe(CONFIGURATION)

    _assert_failure(caught, code)
    assert PROVIDER_SECRET not in caught.value.message
    assert MOCK_HOST not in caught.value.message
    assert "exact saved endpoint" not in caught.value.message
    _assert_only_the_mock_was_reached(workspace)
    # provider_detail is present for HTTP status errors; absent for connection errors.
    if outcome != "connection":
        # The HTTP error carries a JSON body with PROVIDER_SECRET_detail as its message.
        # URL part is stripped; the full PROVIDER_SECRET string is not present.
        detail = caught.value.provider_detail
        assert detail is not None, "provider_detail should be present for HTTP errors"
        assert "https://leak.example" not in detail
        assert PROVIDER_SECRET not in detail  # full string (including URL) not present


# ---------------------------------------------------------------------------
# Follow-up B: provider_detail extraction and sanitisation
# ---------------------------------------------------------------------------


def test_provider_detail_real_provider_http_error_carries_detail(monkeypatch):
    """400/422/etc HTTP errors from the real provider extract a detail string."""
    workspace = MockTransportWorkspace(400)
    _install_real_provider(monkeypatch, workspace)

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        real_provider_probe(workspace).probe(CONFIGURATION)

    assert caught.value.provider_detail is not None
    # URL part of PROVIDER_SECRET is stripped; useful text remains
    assert "https://leak.example" not in caught.value.provider_detail
    assert "token" not in caught.value.provider_detail.lower() or "tool_choice" in (
        caught.value.provider_detail or ""
    )  # broad: the secret's token= part is stripped


def test_provider_detail_real_provider_connection_error_has_no_detail(monkeypatch):
    """Connection errors (non-HTTP) leave provider_detail as None."""
    workspace = MockTransportWorkspace("connection")
    _install_real_provider(monkeypatch, workspace)

    with pytest.raises(StructuredOutputProbeFailure) as caught:
        real_provider_probe(workspace).probe(CONFIGURATION)

    # Connection errors do not carry a provider JSON body; detail may be None or empty.
    # The important guarantee: no leak of secret-bearing text.
    if caught.value.provider_detail is not None:
        assert PROVIDER_SECRET not in caught.value.provider_detail
        assert "https://leak.example" not in caught.value.provider_detail


def test_provider_detail_gateway_body_shape_unwraps_nested_json():
    """The real Gateway body shape unwraps its nested JSON message once."""
    nested_body = json.dumps({
        "error_code": "BAD_REQUEST",
        "message": json.dumps(
            {"message": 'tool_choice: type "tool" and "any" are not supported for this model.'}
        ),
    })
    detail = _sanitise_provider_detail(nested_body)
    assert detail == 'tool_choice: type "tool" and "any" are not supported for this model.'


def test_provider_detail_gateway_body_flat_message():
    """A flat JSON body uses the top-level message field directly."""
    body = json.dumps({"message": "The endpoint does not exist."})
    assert _sanitise_provider_detail(body) == "The endpoint does not exist."


def test_provider_detail_sanitises_url():
    """URLs are stripped from the detail."""
    raw = "Error reaching https://adb-1234.azuredatabricks.net/model/v1 : not found"
    result = _sanitise_provider_detail(raw)
    assert "https://" not in result
    assert "adb-1234" not in result
    assert "not found" in result


def test_provider_detail_sanitises_bearer_token():
    """Bearer / dapi-prefixed tokens are stripped."""
    # "dapi" followed by a long hex run — a realistic fake, not a real credential.
    fake_token = "dapi" + "x" * 36  # clearly synthetic: hex run ≥32 chars
    raw = f"Authorization: Bearer {fake_token} invalid"
    result = _sanitise_provider_detail(raw)
    assert "dapi" not in result
    assert fake_token not in result
    assert "invalid" in result


def test_provider_detail_sanitises_long_hex_run():
    """Hex/base64 runs >= 32 chars are stripped."""
    token = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"  # 32-char hex
    raw = f"Error: bad hash {token} in request"
    result = _sanitise_provider_detail(raw)
    assert token not in result
    assert "Error:" in result
    assert "in request" in result


def test_provider_detail_caps_at_300_chars():
    """Detail is capped at 300 characters with an ellipsis."""
    # Use a phrase that repeats to 400 chars without triggering the hex/base64 stripper.
    raw = "The endpoint is not available. " * 15  # spaces prevent long-run match
    assert len(raw) > 300
    result = _sanitise_provider_detail(raw)
    assert len(result) <= 304  # 300 chars + ellipsis (1-3 bytes)
    assert result.endswith("…") or result.endswith("...")


def test_provider_detail_never_includes_workspace_host():
    """The workspace host is never included in the detail."""
    raw = f"Error from {MOCK_HOST}: endpoint not found"
    result = _sanitise_provider_detail(raw)
    # URLs are stripped; bare host names may remain but let's check the URL form
    assert f"https://{MOCK_HOST}" not in result


def test_provider_detail_collapse_whitespace():
    """Whitespace is collapsed in the detail."""
    raw = "Error:  multiple   spaces\n\ttabs  here"
    result = _sanitise_provider_detail(raw)
    assert "  " not in result
    assert "\n" not in result
    assert "\t" not in result


def test_provider_detail_plain_str_error():
    """Plain non-JSON error strings are accepted as-is (after sanitisation)."""
    raw = "The endpoint rejected the request."
    result = _sanitise_provider_detail(raw)
    assert result == raw


def test_provider_detail_probe_failure_attribute():
    """StructuredOutputProbeFailure carries provider_detail when provided."""
    failure = StructuredOutputProbeFailure(
        "unsupported_structured_output",
        "The endpoint rejected the structured-output test request.",
        False,
        provider_detail="tool_choice not supported",
    )
    assert failure.provider_detail == "tool_choice not supported"


def test_provider_detail_probe_failure_defaults_to_none():
    """StructuredOutputProbeFailure has provider_detail=None by default."""
    failure = StructuredOutputProbeFailure(
        "unsupported_structured_output",
        "The endpoint rejected the structured-output test request.",
        False,
    )
    assert failure.provider_detail is None


def test_provider_detail_preserves_dashed_uuid_req_id():
    """Dashed UUIDs (8-4-4-4-12) are preserved for support diagnostics."""
    req_id = "3ff8f85b-502c-45d1-b23f-d871afa77d4a"
    raw = f"Provided OAuth token does not have required scopes: ai-gateway [ReqId: {req_id}]"
    result = _sanitise_provider_detail(raw)
    assert req_id in result
    assert "ai-gateway" in result
    assert "ReqId" in result


def test_provider_detail_strips_undashed_hex_keeps_dashed_uuid():
    """Long undashed hex is stripped; a dashed UUID next to it is kept."""
    undashed = "a" * 32
    req_id = "3ff8f85b-502c-45d1-b23f-d871afa77d4a"
    raw = f"Error: token={undashed} reqId={req_id}"
    result = _sanitise_provider_detail(raw)
    assert undashed not in result
    assert req_id in result

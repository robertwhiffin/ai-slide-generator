"""#266 Task 5: the saved-candidate structured-output probe.

Adapter tests drive ``DatabricksStructuredOutputProbe`` through recording model
and client factories; service tests drive ``ModelEndpointProbeService`` over a
bootstrapped SQLite aggregate with a deterministic adapter.  No test here
constructs a real workspace client or reaches Databricks.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any, get_args

import httpx
import openai
import pytest
import requests
from databricks.sdk.errors import InternalError, PermissionDenied, Unauthenticated
from pydantic import ValidationError
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
        "This endpoint does not support structured output.",
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

        class _Structured:
            def invoke(self, prompt: str) -> Any:
                recorder.events.append(("invoke", prompt))
                if recorder.invoke_error is not None:
                    raise recorder.invoke_error
                return recorder.output

        class _Chat:
            def with_structured_output(self, schema: Any) -> Any:
                recorder.events.append(("with_structured_output", schema))
                if recorder.bind_error is not None:
                    raise recorder.bind_error
                return _Structured()

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
                "endpoint": "exact saved endpoint",
                "temperature": 0.2,
                "max_tokens": 64,
                "top_p": 0.9,
                "workspace_client": recorder.client,
                "timeout": PROBE_TIMEOUT_SECONDS,
                "max_retries": PROBE_MAX_RETRIES,
            },
        ),
        ("with_structured_output", _StructuredOutputProbeResponse),
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

    prompts = [value for name, value in recorder.events if name == "invoke"]
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
    assert [name for name, _ in recorder.events] == [
        "client_factory",
        "model_factory",
        "with_structured_output",
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
    response = httpx.Response(400, request=request)
    return [
        ("invoke", "openai-connection", openai.APIConnectionError(message=SECRET, request=request)),
        ("invoke", "openai-timeout", openai.APITimeoutError(request=request)),
        (
            "invoke",
            "openai-400",
            openai.BadRequestError(SECRET, response=response, body=None),
        ),
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
    ],
    ids=["dict", "string", "wrong-literal"],
)
def test_model_endpoint_probe_unparsed_output_is_ambiguous_failure(output):
    """Catches a success claimed without the exact structured ``ok`` result."""
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
    _save_endpoint(session_factory, "architect", "architect exact endpoint", 0)
    _save_endpoint(session_factory, "builder", "builder exact endpoint", 1)
    builder_hash = _saved_hash(session_factory, "builder")
    adapter = FakeStructuredOutputProbe()
    service = ModelEndpointProbeService(adapter)

    with session_factory() as session:
        result = service.probe_saved_candidate(
            session, agent_key="builder", expected_lock_version=2
        )

    assert adapter.calls == [
        AgentModelConfiguration(
            endpoint_name="builder exact endpoint",
            temperature=0.125,
            max_tokens=4321,
            top_p=0.5,
        )
    ]
    assert result == SavedEndpointProbeResult(
        identity=SavedEndpointProbeIdentity(
            agent_key="builder",
            endpoint_name="builder exact endpoint",
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
    _save_endpoint(session_factory, "architect", "moved on", 0)
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
                _save_endpoint(session_factory, "architect", "saved mid-probe", 0)
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

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import httpx
import openai
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from src.api.schemas.streaming import StreamEventType
from src.api.services.chat_service import ChatService
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphRelease,
    GraphReleaseAgent,
)
from src.database.models.session import SharedDeckMutationEvent, UserSession
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentRuntime,
    DatabricksModelAdapter,
)
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_configuration_content import (
    definition_content_from_row,
    definition_content_values,
    revision_from_definition,
)
from src.services.persisted_graph_release import (
    GraphReleaseIncompleteError,
    GraphReleaseNotFoundError,
    PersistedConfigurationUnavailableError,
    PersistedGraphReleaseLoader,
    PersistedRuntimeError,
    PinnedInvocationEndpointError,
)

pytestmark = pytest.mark.postgres

SAFE_ERROR = "Pinned graph configuration is unavailable"
SAFE_METADATA = {"code": "pinned_graph_configuration_unavailable"}


class _AdapterThatMustNotRun:
    def __init__(self) -> None:
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("the model adapter ran before persisted validation")


@pytest.fixture
def runtime_catalog(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    v1_id = GraphConfiguration().bootstrap_v1(factory).release_id

    with factory.begin() as db:
        v1 = db.get(GraphRelease, v1_id)
        mappings = list(
            db.scalars(select(GraphReleaseAgent).where(GraphReleaseAgent.graph_release_id == v1_id))
        )
        closed_at = max(
            datetime.now(timezone.utc),
            v1.effective_from + timedelta(microseconds=1),
        )
        v1.effective_to = closed_at
        v2 = GraphRelease(
            version_number=2,
            previous_release_id=v1_id,
            release_note="newer active release that must never be a fallback",
            published_by="task-6-test@example.com",
            published_at=closed_at,
            effective_from=closed_at,
        )
        db.add(v2)
        db.flush()
        db.add_all(
            GraphReleaseAgent(
                graph_release_id=v2.id,
                agent_key=mapping.agent_key,
                agent_definition_revision_id=mapping.agent_definition_revision_id,
            )
            for mapping in mappings
        )
        v2_id = v2.id

    return postgres_engine, factory, v1_id, v2_id


def _assert_no_active_release_fallback(engine, operation):
    active_release_queries = []

    def record_active_release_query(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = " ".join(statement.lower().split())
        if "graph_release" in normalized and "effective_to is null" in normalized:
            active_release_queries.append(statement)

    event.listen(engine, "before_cursor_execute", record_active_release_query)
    try:
        result = operation()
    finally:
        event.remove(engine, "before_cursor_execute", record_active_release_query)

    assert active_release_queries == []
    return result


def _closed_release(
    factory,
    *,
    base_release_id: int,
    version_number: int,
    replacement: AgentDefinitionRevision | None = None,
) -> int:
    now = datetime.now(timezone.utc) + timedelta(seconds=version_number)
    with factory.begin() as db:
        base_mappings = list(
            db.scalars(
                select(GraphReleaseAgent).where(
                    GraphReleaseAgent.graph_release_id == base_release_id
                )
            )
        )
        if replacement is not None:
            db.add(replacement)
            db.flush()
        release = GraphRelease(
            version_number=version_number,
            previous_release_id=base_release_id,
            release_note=f"task 6 failure release {version_number}",
            published_by="task-6-test@example.com",
            published_at=now,
            effective_from=now,
            effective_to=now + timedelta(seconds=1),
        )
        db.add(release)
        db.flush()
        for mapping in base_mappings:
            revision_id = mapping.agent_definition_revision_id
            if replacement is not None and mapping.agent_key == replacement.agent_key:
                revision_id = replacement.id
            db.add(
                GraphReleaseAgent(
                    graph_release_id=release.id,
                    agent_key=mapping.agent_key,
                    agent_definition_revision_id=revision_id,
                )
            )
        release_id = release.id
    return release_id


def _base_revision(factory, release_id: int, agent_key: str):
    with factory() as db:
        return db.execute(
            select(AgentDefinitionRevision)
            .join(
                GraphReleaseAgent,
                GraphReleaseAgent.agent_definition_revision_id == AgentDefinitionRevision.id,
            )
            .where(GraphReleaseAgent.graph_release_id == release_id)
            .where(GraphReleaseAgent.agent_key == agent_key)
        ).scalar_one()


def _malformed_typed_revision(factory, release_id: int, agent_key: str):
    base = _base_revision(factory, release_id, agent_key)
    values = definition_content_values(definition_content_from_row(base))
    assembly_rules = copy.deepcopy(values["assembly_rules"])
    assembly_rules["format_version"] = 999
    values["assembly_rules"] = assembly_rules
    return AgentDefinitionRevision(
        **values,
        content_hash="1" * 64,
        created_by="task-6-test@example.com",
    )


def _wrong_hash_revision(factory, release_id: int, agent_key: str):
    base = _base_revision(factory, release_id, agent_key)
    return AgentDefinitionRevision(
        **definition_content_values(definition_content_from_row(base)),
        content_hash="2" * 64,
        created_by="task-6-test@example.com",
    )


def _protected_contract_revision(factory, release_id: int, agent_key: str):
    base = _base_revision(factory, release_id, agent_key)
    content = definition_content_from_row(base)
    content = content.model_copy(
        update={
            "protected_assembly": content.protected_assembly.model_copy(
                update={"version": 999, "digest": "3" * 64}
            )
        }
    )
    return revision_from_definition(
        content,
        actor="task-6-test@example.com",
        timestamp=datetime.now(timezone.utc),
    )


def _removed_endpoint_revision(factory, release_id: int, agent_key: str):
    base = _base_revision(factory, release_id, agent_key)
    content = definition_content_from_row(base)
    content = content.model_copy(
        update={
            "model": content.model.model_copy(update={"endpoint_name": "removed-task-6-endpoint"})
        }
    )
    return revision_from_definition(
        content,
        actor="task-6-test@example.com",
        timestamp=datetime.now(timezone.utc),
    )


def _safe_event_from_graph_seam(
    monkeypatch,
    failure: PersistedRuntimeError,
    *,
    expected_release_id: int,
    session_factory=None,
):
    from src.api.services import chat_service as chat_service_module

    session_id = "task-6-safe-envelope"
    if session_factory is not None:
        with session_factory.begin() as db:
            db.add(
                UserSession(
                    session_id=session_id,
                    graph_release_id=expected_release_id,
                    created_by="task-6-test@example.com",
                )
            )
        monkeypatch.setattr("src.core.database.get_session_local", lambda: session_factory)

    def fail_graph(*_args, **_kwargs):
        raise failure

    log_calls = []

    def identity_safe_error(message, *args, **kwargs):
        log_calls.append((message, args, kwargs))

    monkeypatch.setattr(chat_service_module.logger, "error", identity_safe_error)
    monkeypatch.setattr("src.services.graph.builder.invoke_graph", fail_graph)
    events = []
    with pytest.raises(type(failure)) as raised:
        for item in ChatService()._send_message_streaming_graph(
            session_id,
            "a prompt that must not leak",
        ):
            events.append(item)

    assert raised.value is failure
    assert len(events) == 1
    event_item = events[0]
    assert event_item.type is StreamEventType.ERROR
    assert event_item.error == SAFE_ERROR
    assert event_item.metadata == SAFE_METADATA
    public = event_item.model_dump(mode="json", exclude_none=True)
    rendered = repr(public)
    for forbidden in (
        type(failure).__name__,
        "graph_release_id",
        "removed-task-6-endpoint",
        "a prompt that must not leak",
        "payload",
        "output",
    ):
        assert forbidden not in rendered
    assert log_calls == [
        (
            "pinned_graph_configuration_unavailable",
            (),
            {
                "extra": {
                    "error_class": type(failure).__name__,
                    "graph_release_id": expected_release_id,
                }
            },
        )
    ]


@pytest.mark.parametrize("failure_kind", ["nonexistent", "incomplete"])
def test_real_loader_failures_escape_as_the_safe_graph_event_without_active_fallback(
    runtime_catalog, monkeypatch, failure_kind
):
    engine, factory, v1_id, active_v2_id = runtime_catalog
    loader = PersistedGraphReleaseLoader(session_factory=factory)
    if failure_kind == "nonexistent":
        requested_release_id = active_v2_id + 100_000
        expected = GraphReleaseNotFoundError
    else:
        now = datetime.now(timezone.utc) + timedelta(seconds=10)
        with factory.begin() as db:
            release = GraphRelease(
                version_number=3,
                previous_release_id=v1_id,
                release_note="deliberately incomplete closed release",
                published_by="task-6-test@example.com",
                published_at=now,
                effective_from=now,
                effective_to=now + timedelta(seconds=1),
            )
            db.add(release)
            db.flush()
            requested_release_id = release.id
        expected = GraphReleaseIncompleteError

    def load_failure():
        with pytest.raises(expected) as raised:
            loader.resolve(requested_release_id, "architect")
        return raised.value

    failure = _assert_no_active_release_fallback(engine, load_failure)
    _safe_event_from_graph_seam(
        monkeypatch,
        failure,
        expected_release_id=requested_release_id,
        session_factory=(factory if failure_kind == "incomplete" else None),
    )
    assert requested_release_id != active_v2_id


def test_unavailable_protected_contract_is_safe_and_never_falls_back(runtime_catalog, monkeypatch):
    engine, factory, v1_id, active_v2_id = runtime_catalog
    release_id = _closed_release(
        factory,
        base_release_id=v1_id,
        version_number=3,
        replacement=_protected_contract_revision(factory, v1_id, "architect"),
    )
    adapter = _AdapterThatMustNotRun()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter,
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )

    def invoke_failure():
        with pytest.raises(PersistedConfigurationUnavailableError) as raised:
            runtime.run("architect", release_id, {}, AgentAssemblyContext(False))
        return raised.value

    failure = _assert_no_active_release_fallback(engine, invoke_failure)
    assert failure.code == "protected_bundle_unavailable"
    assert adapter.calls == []
    assert release_id != active_v2_id
    _safe_event_from_graph_seam(
        monkeypatch,
        failure,
        expected_release_id=release_id,
        session_factory=factory,
    )


def test_database_failure_is_safe_and_does_not_attempt_an_active_release(
    runtime_catalog, monkeypatch
):
    engine, _factory, v1_id, _active_v2_id = runtime_catalog

    def unavailable_factory():
        raise RuntimeError("database credentials must not leak")

    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=unavailable_factory),
        model_adapter=_AdapterThatMustNotRun(),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )

    def invoke_failure():
        with pytest.raises(PersistedConfigurationUnavailableError) as raised:
            runtime.run("architect", v1_id, {}, AgentAssemblyContext(False))
        return raised.value

    failure = _assert_no_active_release_fallback(engine, invoke_failure)
    assert failure.code == "lakebase_unavailable"
    _safe_event_from_graph_seam(
        monkeypatch,
        failure,
        expected_release_id=v1_id,
        session_factory=_factory,
    )


def test_removed_pinned_endpoint_is_safe_and_is_attempted_exactly_once(
    runtime_catalog, monkeypatch
):
    engine, factory, v1_id, active_v2_id = runtime_catalog
    release_id = _closed_release(
        factory,
        base_release_id=v1_id,
        version_number=3,
        replacement=_removed_endpoint_revision(factory, v1_id, "architect"),
    )
    request = httpx.Request("POST", "https://workspace/removed-task-6-endpoint")
    response = httpx.Response(404, request=request)
    removed = openai.NotFoundError("removed", response=response, body=None)
    endpoint_attempts = []

    class Structured:
        def invoke(self, _prompt):
            raise removed

    class Model:
        def with_structured_output(self, _schema):
            return Structured()

    def model_factory(**kwargs):
        endpoint_attempts.append(kwargs["endpoint"])
        return Model()

    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=DatabricksModelAdapter(
            model_factory=model_factory,
            client_factory=lambda: object(),
        ),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )

    def invoke_failure():
        with pytest.raises(PinnedInvocationEndpointError) as raised:
            runtime.run("architect", release_id, {}, AgentAssemblyContext(False))
        return raised.value

    failure = _assert_no_active_release_fallback(engine, invoke_failure)
    assert endpoint_attempts == ["removed-task-6-endpoint"]
    assert failure.endpoint_name == "removed-task-6-endpoint"
    assert failure.graph_release_id == release_id != active_v2_id
    _safe_event_from_graph_seam(
        monkeypatch,
        failure,
        expected_release_id=release_id,
        session_factory=factory,
    )


@pytest.mark.parametrize(
    ("node_name", "agent_key", "revision_factory"),
    [
        ("builder", "builder", _malformed_typed_revision),
        ("deck_reviewer", "deck_reviewer", _wrong_hash_revision),
    ],
)
def test_persisted_corruption_escapes_later_node_recovery(
    runtime_catalog,
    graph_turn_env,
    monkeypatch,
    node_name,
    agent_key,
    revision_factory,
):
    from src.services.graph import nodes

    engine, factory, v1_id, active_v2_id = runtime_catalog
    release_id = _closed_release(
        factory,
        base_release_id=v1_id,
        version_number=3,
        replacement=revision_factory(factory, v1_id, agent_key),
    )
    adapter = _AdapterThatMustNotRun()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter,
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: runtime)

    if node_name == "builder":

        def invoke_node():
            return nodes.builder_node(
                {
                    "position": 0,
                    "session_id": graph_turn_env.session_id,
                    "turn_id": "task-6-builder",
                    "graph_release_id": release_id,
                }
            )

    else:
        nodes.write_deck_level_columns(
            graph_turn_env.session_id,
            title="Persisted deck",
        )
        nodes.SlideWriter().write_slide(
            graph_turn_env.session_id,
            0,
            "<div class='slide'>persisted</div>",
        )
        # MIRROR THE STATE'S RELEASE INTO THE CONTENT DATABASE AND PIN THE
        # SESSION TO IT.
        #
        # `deck_reviewer_node`'s post-commit deck-level write now records
        # collaboration evidence, and `record_shared_deck_mutation` validates the
        # state's release BOTH against the content database and against the
        # session's own persisted pin. This fixture deliberately splits the two:
        # the runtime catalog is the PostgreSQL `postgres_engine`, while
        # `graph_turn_env`'s deck and session live in its own SQLite database. So
        # the release id the state carries did not exist on the content side and
        # the session was pinned to a different release; attribution refused with
        # `mutation actor pin does not match its persisted pin`, the node swallowed
        # that into a user-visible notice, and the "no message" assertion below
        # failed for a reason with nothing to do with persisted corruption.
        #
        # Production never has that split — one database holds catalog and
        # content — and `invoke_graph` always puts the session's own persisted
        # pin into state. So the fixture was what diverged, and this restores the
        # invariant the writer is entitled to assume rather than relaxing it.
        mirrored_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        with graph_turn_env.factory() as content_db:
            content_db.add(
                GraphRelease(
                    id=release_id,
                    version_number=3,
                    previous_release_id=None,
                    release_note="content-side mirror of the corrupted release",
                    published_by="task-6-test@example.com",
                    published_at=mirrored_at,
                    effective_from=mirrored_at,
                    # Closed, so the content database still has exactly one
                    # active release and no lookup there can drift to this one.
                    effective_to=mirrored_at + timedelta(seconds=1),
                )
            )
            owner = content_db.scalar(
                select(UserSession).where(
                    UserSession.session_id == graph_turn_env.session_id
                )
            )
            owner.graph_release_id = release_id
            content_db.commit()
        state = {
            "session_id": graph_turn_env.session_id,
            "graph_release_id": release_id,
            "turn_id": "task-6-deck-reviewer",
            "initiated_by": "task-6-test@example.com",
        }

        def invoke_node():
            return nodes.deck_reviewer_node(state)

    messages_before = list(graph_turn_env.messages())
    with pytest.raises(PersistedRuntimeError):
        _assert_no_active_release_fallback(engine, invoke_node)

    assert adapter.calls == []
    assert graph_turn_env.messages() == messages_before
    assert release_id != active_v2_id

    if node_name == "deck_reviewer":
        # The post-commit deck-level write DID run and DID record its evidence
        # against the state's exact release. Without this the assertion above
        # would also be satisfied by a write that never happened, and by the
        # attribution refusal this fixture used to provoke — whose only symptom
        # was the notice, so suppressing the notice would have hidden it.
        with graph_turn_env.factory() as content_db:
            recorded = [
                (event.operation, event.graph_release_id, event.graph_version)
                for event in content_db.scalars(
                    select(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id)
                )
            ]
        assert recorded == [("write_deck_level", release_id, 3)]

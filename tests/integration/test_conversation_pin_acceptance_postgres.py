"""Final real-PostgreSQL acceptance for immutable conversation graph pins.

The graph, checkpointer, release loader, runtime, identity sink, migrations,
models, and session creation path are production objects.  The only replaced
production boundary is ``AgentModelAdapter``: one global ordered deque supplies
typed model outputs so an invocation with the wrong role or at the wrong point
in the three-turn machine fails immediately.
"""

from __future__ import annotations

import contextlib
import copy
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.api.services.session_manager import SessionManager
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphRelease,
    GraphReleaseAgent,
)
from src.database.models.session import UserSession
from src.domain.finding import DeckReviewOutput, SlideReviewOutput
from src.domain.skill_io import (
    AnalystOutput,
    ArchitectOutput,
    BuilderOutput,
    DataRequest,
    FixerOutput,
)
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.graph.builder import build_graph, invoke_graph
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_configuration_content import (
    definition_content_from_row,
    revision_from_definition,
)
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.integration.conftest_stub_skills import (
    builder_html,
    fixed_html,
    make_deck_spec,
    objective_finding,
)

pytestmark = pytest.mark.postgres

UNSAFE_HTML = '<img src="https://attacker.com/b.png">'
SAFE_HTML = builder_html(0)
SAFE_FIXED_HTML = fixed_html(0)
ACTOR = "conversation-pin-acceptance@example.com"

A1_ROLES = (
    "architect",
    "data_analyst",
    "architect",
    "builder",
    "builder",
    "build_reviewer",
    "fixer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)
A2_ROLES = (
    "architect",
    "build_reviewer",
    "builder",
    "build_reviewer",
    "deck_reviewer",
)
B1_ROLES = A1_ROLES


class _OrderedAdapter:
    """One serial model-output machine shared by all three graph turns."""

    def __init__(self, entries):
        self.entries = deque(entries)
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def invoke(self, *, agent_key, configuration, schema, prompt):
        with self._lock:
            assert self.entries, f"unexpected adapter invocation for {agent_key!r}"
            expected_role, output = self.entries[0]
            assert agent_key == expected_role, (
                f"adapter order mismatch: expected {expected_role!r}, got {agent_key!r}"
            )
            assert isinstance(output, schema), (
                f"{agent_key!r} output is {type(output).__name__}, not {schema.__name__}"
            )
            self.entries.popleft()
            self.calls.append(agent_key)
            return output


def _database_context(factory):
    @contextlib.contextmanager
    def managed_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return managed_session


def _publish_v2(factory, v1_id: int) -> int:
    """Test-publish a complete V2 with a distinct revision for every role."""
    with factory.begin() as db:
        v1 = db.get(GraphRelease, v1_id)
        assert v1 is not None and v1.effective_to is None
        v1_mappings = list(
            db.scalars(
                select(GraphReleaseAgent)
                .where(GraphReleaseAgent.graph_release_id == v1_id)
                .order_by(GraphReleaseAgent.agent_key)
            )
        )
        assert len(v1_mappings) == 7

        closed_at = max(
            datetime.now(timezone.utc),
            v1.effective_from + timedelta(microseconds=1),
        )
        v1.effective_to = closed_at
        v2 = GraphRelease(
            version_number=2,
            previous_release_id=v1.id,
            release_note="Conversation pin acceptance V2",
            published_by=ACTOR,
            published_at=closed_at,
            effective_from=closed_at,
        )
        db.add(v2)
        db.flush()

        for mapping in v1_mappings:
            prior = db.get(AgentDefinitionRevision, mapping.agent_definition_revision_id)
            assert prior is not None and prior.agent_key == mapping.agent_key
            prior_content = definition_content_from_row(prior)
            v2_content = prior_content.model_copy(
                update={
                    "definition_version": prior_content.definition_version + 1,
                    "prompt_text": prior_content.prompt_text
                    + f"\n\nPersisted acceptance V2 role: {mapping.agent_key}.",
                }
            )
            revision = revision_from_definition(
                v2_content,
                actor=ACTOR,
                timestamp=closed_at,
            )
            db.add(revision)
            db.flush()
            db.add(
                GraphReleaseAgent(
                    graph_release_id=v2.id,
                    agent_key=mapping.agent_key,
                    agent_definition_revision_id=revision.id,
                )
            )
        v2_id = v2.id
    return v2_id


def _release_mapping(factory, release_id: int):
    with factory() as db:
        rows = db.execute(
            select(GraphReleaseAgent.agent_key, AgentDefinitionRevision)
            .join(
                AgentDefinitionRevision,
                AgentDefinitionRevision.id == GraphReleaseAgent.agent_definition_revision_id,
            )
            .where(GraphReleaseAgent.graph_release_id == release_id)
        ).all()
    assert len(rows) == 7
    mapping = {role: (revision.id, revision.content_hash) for role, revision in rows}
    assert set(mapping) == {
        "architect",
        "data_analyst",
        "builder",
        "build_reviewer",
        "fixer",
        "fix_reviewer",
        "deck_reviewer",
    }
    assert all(len(content_hash) == 64 for _revision_id, content_hash in mapping.values())
    return mapping


def _first_turn_outputs():
    return [
        (
            "architect",
            ArchitectOutput(
                intent="ask_data",
                message="need data",
                data_request=DataRequest(metric="revenue"),
            ),
        ),
        (
            "data_analyst",
            AnalystOutput(
                outcome="success",
                synthesis="fixture synthesis",
                sources=["fixture://source"],
            ),
        ),
        (
            "architect",
            ArchitectOutput(intent="build", message="build", deck_spec=make_deck_spec(1)),
        ),
        ("builder", BuilderOutput(position=0, html=UNSAFE_HTML, scripts="")),
        ("builder", BuilderOutput(position=0, html=SAFE_HTML, scripts="")),
        (
            "build_reviewer",
            SlideReviewOutput(
                slide_index=0,
                verdict="surfaced",
                findings=[objective_finding(0)],
            ),
        ),
        (
            "fixer",
            FixerOutput(position=0, html=UNSAFE_HTML, scripts="", changed=True),
        ),
        (
            "fixer",
            FixerOutput(position=0, html=SAFE_FIXED_HTML, scripts="", changed=True),
        ),
        (
            "fix_reviewer",
            SlideReviewOutput(slide_index=0, verdict="clean", findings=[]),
        ),
        ("deck_reviewer", DeckReviewOutput(findings=[])),
    ]


def _second_turn_outputs():
    changed_spec = make_deck_spec(1)
    changed_spec = changed_spec.model_copy(update={"audience": "Changed audience"})
    return [
        (
            "architect",
            ArchitectOutput(
                intent="edit",
                message="change audience",
                deck_spec=changed_spec,
                target_positions=[0],
            ),
        ),
        (
            "build_reviewer",
            SlideReviewOutput(
                slide_index=0,
                verdict="surfaced",
                findings=[objective_finding(0)],
            ),
        ),
        ("builder", BuilderOutput(position=0, html=SAFE_HTML, scripts="")),
        (
            "build_reviewer",
            SlideReviewOutput(slide_index=0, verdict="clean", findings=[]),
        ),
        ("deck_reviewer", DeckReviewOutput(findings=[])),
    ]


def _expected_identities(session_id, turn, roles, release_id, mapping):
    return [
        (
            session_id,
            turn,
            role,
            release_id,
            mapping[role][0],
            mapping[role][1],
        )
        for role in roles
    ]


def _actual_identities(session_id, turn, calls):
    return [
        (
            session_id,
            turn,
            identity.agent_key,
            identity.graph_release_id,
            identity.agent_definition_revision_id,
            identity.content_hash,
        )
        for identity in calls
    ]


def _assert_send_segment(sent, starts, release_id):
    builder_segment = sent["builder"][starts["builder"] :]
    reviewer_segment = sent["build_reviewer"][starts["build_reviewer"] :]
    assert len(builder_segment) == 1
    assert len(reviewer_segment) == 1
    assert [payload["graph_release_id"] for payload in builder_segment] == [release_id]
    assert [payload["graph_release_id"] for payload in reviewer_segment] == [release_id]


def test_persisted_conversation_pins_drive_three_real_compiled_graph_turns(
    postgres_engine, monkeypatch
):
    from src.services.graph import routers

    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    v1_id = GraphConfiguration().bootstrap_v1(factory).release_id
    v1_mapping = _release_mapping(factory, v1_id)
    manager = SessionManager()
    managed_session = _database_context(factory)

    for target in (
        "src.api.services.session_manager.get_db_session",
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
        "src.services.graph.nodes.get_db_session",
    ):
        monkeypatch.setattr(target, managed_session)
    monkeypatch.setattr("src.services.identity_provider.resolve_display_names", lambda emails: {})

    session_a = "acceptance-conversation-a"
    created_a = manager.create_session(
        session_id=session_a,
        created_by=ACTOR,
        graph_capable=True,
    )
    assert created_a["graph_version"] == 1
    assert created_a["active_graph_version"] == 1
    assert created_a["is_older_than_active"] is False

    v2_id = _publish_v2(factory, v1_id)
    v2_mapping = _release_mapping(factory, v2_id)
    assert v2_id != v1_id
    assert v2_mapping.keys() == v1_mapping.keys()
    assert all(v2_mapping[role] != v1_mapping[role] for role in v1_mapping)

    session_b = "acceptance-conversation-b"
    created_b = manager.create_session(
        session_id=session_b,
        created_by=ACTOR,
        graph_capable=True,
    )
    assert created_b["graph_version"] == 2
    assert created_b["active_graph_version"] == 2
    assert created_b["is_older_than_active"] is False

    entries = _first_turn_outputs() + _second_turn_outputs() + _first_turn_outputs()
    assert tuple(role for role, _output in entries) == A1_ROLES + A2_ROLES + B1_ROLES
    adapter = _OrderedAdapter(entries)
    identity_sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter,
        identity_sink=identity_sink,
    )
    monkeypatch.setattr("src.services.graph.nodes.get_agent_runtime", lambda: runtime)

    sent = {"builder": [], "build_reviewer": []}
    saved_send = routers.Send

    def recording_send(node, arg):
        sent[node].append(copy.deepcopy(arg))
        return saved_send(node, arg)

    monkeypatch.setattr(routers, "Send", recording_send)
    graph = build_graph(checkpointer=SqlAlchemyCheckpointSaver(session_factory=factory))
    monkeypatch.setattr("src.services.graph.builder.get_session_local", lambda: factory)
    monkeypatch.setattr("src.services.graph.builder.get_graph", lambda: graph)

    segments = (
        (session_a, 1, A1_ROLES, v1_id, v1_mapping, "build A"),
        (session_a, 2, A2_ROLES, v1_id, v1_mapping, "change audience"),
        (session_b, 1, B1_ROLES, v2_id, v2_mapping, "build B"),
    )
    consumed = 0
    for session_id, turn, roles, release_id, mapping, message in segments:
        sink_start = len(identity_sink.calls)
        send_starts = {node: len(payloads) for node, payloads in sent.items()}
        result = invoke_graph(
            session_id,
            {
                "architect_message": message,
                "graph_release_id": v2_id if release_id == v1_id else v1_id,
            },
            principal=ACTOR,
        )

        segment_calls = identity_sink.calls[sink_start:]
        expected_graph_version = 1 if release_id == v1_id else 2
        assert [identity.graph_version for identity in segment_calls] == [
            expected_graph_version
        ] * len(roles)
        assert _actual_identities(session_id, turn, segment_calls) == _expected_identities(
            session_id, turn, roles, release_id, mapping
        )
        assert result["graph_release_id"] == release_id
        assert adapter.calls[consumed : consumed + len(roles)] == list(roles)
        consumed += len(roles)
        _assert_send_segment(sent, send_starts, release_id)

    assert not adapter.entries
    assert len(identity_sink.calls) == len(A1_ROLES + A2_ROLES + B1_ROLES)
    assert all(identity.agent_key != "foreman" for identity in identity_sink.calls)

    with factory() as db:
        a_row = db.scalar(select(UserSession).where(UserSession.session_id == session_a))
        b_row = db.scalar(select(UserSession).where(UserSession.session_id == session_b))
        active = db.scalar(select(GraphRelease).where(GraphRelease.effective_to.is_(None)))
        old = db.get(GraphRelease, v1_id)
        assert a_row is not None and a_row.graph_release_id == v1_id
        assert b_row is not None and b_row.graph_release_id == v2_id
        assert old is not None and old.version_number == 1 and old.effective_to is not None
        assert active is not None and active.id == v2_id and active.version_number == 2

    projected_a = manager.get_session(session_a)
    projected_b = manager.get_session(session_b)
    assert (
        projected_a["graph_version"],
        projected_a["active_graph_version"],
        projected_a["is_older_than_active"],
    ) == (1, 2, True)
    assert (
        projected_b["graph_version"],
        projected_b["active_graph_version"],
        projected_b["is_older_than_active"],
    ) == (2, 2, False)

    session_c = "acceptance-conversation-c"
    created_c = manager.create_session(
        session_id=session_c,
        created_by=ACTOR,
        graph_capable=True,
    )
    assert created_c["graph_version"] == 2
    with factory() as db:
        pins = dict(
            db.execute(
                select(UserSession.session_id, UserSession.graph_release_id).where(
                    UserSession.session_id.in_((session_a, session_b, session_c))
                )
            ).all()
        )
    assert pins == {session_a: v1_id, session_b: v2_id, session_c: v2_id}

"""#271 Task 7: release identity through the shipped graph-mode seam, across three releases.

AC8, AC4 and AC5.  Task 6's lifecycle journey runs to ``S16`` over real PostgreSQL,
so three Graph Versions exist with ids that are NOT their version numbers:

* v1 = id 1 (``old-root`` is pinned to it);
* v2 = id 3, now NON-active (``new-root``): architect on protected assembly v2
  with a custom block, builder on schema contract v2 with ``diagnostic_notes``;
* v3 = id 4, active (``post-rollback-root``): a rollback that restores v1's
  seven revisions under a new version number.

Then one first graph turn per conversation goes in through the SHIPPED entry
point, ``ChatService.send_message_streaming(..., engine_mode="graph")``, with
``graph_chat_env``'s patch recipe (``test_graph_mode_turn.py``) adapted to the
PostgreSQL factory, and the tripwire from Task 6 still armed.

Stages (labelled through Task 6's ``stage()``)
----------------------------------------------
* ``S13`` ``[#261]``: each turn's final checkpoint, every ``Send`` payload to
  ``builder`` and ``build_reviewer``, and every production
  ``persisted_agent_invocation`` log record carry exactly the conversation's pin,
  and the (revision id, content hash) the database maps for that role.  The log
  records carry exactly the allow-list and no prose or session id.  No prompt
  carries a session id, a principal, the turn id or an identity key name.
* ``S17`` ``[#265]``: every persisted revision's protected bundle and schema
  contract resolve, and the non-active v2 executed with ITS bundles (the composed
  v2 builder schema, the v2 architect custom block) while v3 executed with v1's.

The only replaced production boundaries are the chat model and the naming
model.  The model adapter is the real ``DatabricksModelAdapter`` (C8): its model
factory returns a ``ChatModel`` double that answers from one ordered deque and
RAISES on ``bind_tools``, so AC5 ("no tools") is asserted on every model call of
every turn, not vacuously on a recording adapter that has no tool path.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from src.api.schemas.streaming import StreamEventType
from src.api.services.chat_service import ChatService
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.core.permission_context import PermissionContext, set_permission_context
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import AgentDefinitionRevision
from src.services.agent_runtime import AgentRuntime, DatabricksModelAdapter
from src.services.agent_runtime_identity import LoggingAgentInvocationIdentitySink
from src.services.agent_schema_registry import AgentSchemaRegistry
from src.services.agent_schema_types import SchemaContractIdentity
from src.services.graph.builder import build_graph
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import schema_contract_identity
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from src.services.prompt_assembler import PromptAssembler
from tests.fixtures.log_records import STANDARD_LOG_RECORD_ATTRS, rendered_record
from tests.integration.graph_lifecycle_journey import (  # noqa: F401 (fixtures)
    ADMIN,
    ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST,
    BUILDER_SCHEMA_CONTRACT_V2_DIGEST,
    CONTRIBUTOR,
    CUSTOM_BLOCK_TEXT,
    OWNER,
    STAGES,
    Stage,
    acceptance_stack,
    lifecycle_journey,
    require,
    stage,
)
from tests.integration.test_conversation_pin_acceptance_postgres import (
    A1_ROLES,
    _first_turn_outputs,
    _release_mapping,
)

pytestmark = pytest.mark.postgres

S13 = Stage(
    "S13",
    "turns on pinned releases",
    "#261",
    'ChatService.send_message_streaming(engine_mode="graph")',
)
S17 = Stage(
    "S17",
    "historical bundles",
    "#265",
    "AgentRuntime over PersistedGraphReleaseLoader",
)


def _in_stage(journey, current: Stage):
    """Run a Task 7 stage body under Task 6's attribution (``journey.in_stage``)."""
    return journey.in_stage(current)


MESSAGE = "USE AGENT MODE build a deck"
#: The production identity sink's logger (``get_agent_runtime``'s ``__name__``).
RUNTIME_LOGGER = "src.services.agent_runtime"
#: Every wait in this file is bounded by this (the turn consumer's join).
TURN_TIMEOUT_SECONDS = 120.0
DIAGNOSTIC_NOTE = "Lifecycle diagnostic prose: the builder kept one idea per slide."

#: The exact extra-field set of a SUCCESS ``persisted_agent_invocation`` record
#: (``_LOGGED_IDENTITY_FIELDS`` plus the three outcome fields), as a literal.
SUCCESS_RECORD_FIELDS = frozenset(
    {
        "graph_version",
        "graph_release_id",
        "agent_key",
        "agent_definition_revision_id",
        "content_hash",
        "outcome",
        "error_class",
        "additional_field_names",
    }
)
#: Identity key names no model prompt may carry.
FORBIDDEN_PROMPT_KEYS = (
    "graph_release_id",
    "session_id",
    "turn_id",
    "initiated_by",
    "root_session_id",
    "actor_session_id",
)
PINNED_CONVERSATIONS = ("old-root", "new-root", "post-rollback-root")


class _MonolithReached(AssertionError):  # noqa: N818 (mirrors test_graph_mode_turn)
    """Raised if a graph-mode turn ever reaches the monolith's agent build."""


class _ToolBindingAttempted(AssertionError):  # noqa: N818
    """Raised by the ``ChatModel`` double when anything tries to bind tools (AC5)."""


# ---------------------------------------------------------------------------
# The model boundary: the real DatabricksModelAdapter over a ChatModel double
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCall:
    agent_key: str
    schema: type[BaseModel]
    prompt: str


class _StructuredModel:
    def __init__(self, answer: BaseModel, prompts: list[str]) -> None:
        self._answer = answer
        self._prompts = prompts

    def invoke(self, prompt: str) -> BaseModel:
        self._prompts.append(prompt)
        return self._answer


class _ToolFreeChatModel:
    """A LangChain ``ChatModel`` double: ``with_structured_output`` only.

    ``bind_tools`` (with any tool list, the empty one included) raises and is
    recorded; so is any other attribute read, so a new binding path cannot slip
    past as an unrecorded ``MagicMock``-style success.
    """

    def __init__(self, adapter: _ToolFreeOrderedAdapter, answer: dict[str, Any]) -> None:
        object.__setattr__(self, "_adapter", adapter)
        object.__setattr__(self, "_answer", answer)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        self._adapter.tool_bindings.append(repr(tools))
        raise _ToolBindingAttempted(f"graph runtime bound tools: {tools!r}")

    def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> Any:
        self._adapter.method_calls.append(("with_structured_output", schema, kwargs))
        # Mirror a real structured-output parser: an instance of the BOUND schema.
        return _StructuredModel(schema.model_validate(self._answer), self._adapter.chat_prompts)

    def __getattr__(self, name: str) -> Any:
        self._adapter.method_calls.append((name, None, {}))
        raise _ToolBindingAttempted(f"unexpected ChatModel attribute {name!r}")


class _ToolFreeOrderedAdapter:
    """One ordered model-output machine behind the real ``DatabricksModelAdapter``.

    ``invoke`` checks the role order (A1) and the bound schema's role, records the
    call, then delegates to a real ``DatabricksModelAdapter`` whose model factory
    builds the ``ChatModel`` double answering with the popped output.  When the
    bound (composed) schema offers ``diagnostic_notes`` the answer supplies it.
    """

    def __init__(self) -> None:
        self.entries: deque[tuple[str, BaseModel]] = deque()
        self.calls: list[ModelCall] = []
        self.tool_bindings: list[str] = []
        self.method_calls: list[tuple[str, Any, dict]] = []
        self.chat_prompts: list[str] = []
        self.factory_kwargs: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._local = threading.local()
        self._databricks = DatabricksModelAdapter(
            model_factory=self._model_factory,
            client_factory=lambda: object(),
        )

    def load(self, entries: list[tuple[str, BaseModel]]) -> None:
        assert not self.entries, f"unconsumed model outputs: {[r for r, _ in self.entries]}"
        self.entries.extend(entries)

    def _model_factory(self, **kwargs: Any) -> _ToolFreeChatModel:
        self.factory_kwargs.append(kwargs)
        return _ToolFreeChatModel(self, self._local.answer)

    def invoke(self, *, agent_key, configuration, schema, prompt):
        with self._lock:
            assert self.entries, f"unexpected adapter invocation for {agent_key!r}"
            expected_role, output = self.entries[0]
            assert agent_key == expected_role, (
                f"adapter order mismatch: expected {expected_role!r}, got {agent_key!r}"
            )
            assert issubclass(schema, type(output)), (
                f"{agent_key!r} output is {type(output).__name__}, not {schema.__name__}"
            )
            self.entries.popleft()
            self.calls.append(ModelCall(agent_key, schema, prompt))
        answer = output.model_dump(mode="python", exclude_unset=True)
        if "diagnostic_notes" in schema.model_fields:
            answer["diagnostic_notes"] = [DIAGNOSTIC_NOTE]
        self._local.answer = answer
        return self._databricks.invoke(
            agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt
        )


# ---------------------------------------------------------------------------
# The turn driver (Task 8 reuses it)
# ---------------------------------------------------------------------------


@dataclass
class TurnRecord:
    session_id: str
    pin: int
    seeded_release_id: int
    events: list[Any]
    calls: list[ModelCall]
    records: list[logging.LogRecord]
    sends: dict[str, list[dict]]
    initial: dict[str, Any]
    checkpoint: dict[str, Any]


@dataclass
class GraphTurnDriver:
    """``graph_chat_env``'s recipe over the journey's PostgreSQL factory."""

    journey: Any
    adapter: _ToolFreeOrderedAdapter
    checkpointer: SqlAlchemyCheckpointSaver
    caplog: Any
    service: ChatService = field(default_factory=ChatService)
    sent: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    initials: list[dict[str, Any]] = field(default_factory=list)
    next_seed: int | None = None

    def drive(self, session_id: str, *, seed_release_id: int) -> TurnRecord:
        """One first graph turn on ``session_id``, the graph input seeded with a wrong release."""
        pin = self.journey.pin_of(session_id)
        assert pin is not None and seed_release_id != pin, (session_id, pin, seed_release_id)
        self.adapter.load(_first_turn_outputs())
        call_start = len(self.adapter.calls)
        record_start = len(self.caplog.records)
        send_start = {node: len(payloads) for node, payloads in self.sent.items()}
        initial_start = len(self.initials)
        self.next_seed = seed_release_id

        set_current_user(OWNER)
        set_permission_context(PermissionContext(user_name=OWNER))
        events: list[Any] = []
        errors: list[BaseException] = []
        context = contextvars.copy_context()

        def consume() -> None:
            try:
                for event in self.service.send_message_streaming(
                    session_id=session_id,
                    message=MESSAGE,
                    is_first_message_override=False,
                    engine_mode="graph",
                ):
                    events.append(event)
            except BaseException as exc:  # noqa: BLE001 (re-raised below)
                errors.append(exc)

        consumer = threading.Thread(target=lambda: context.run(consume), daemon=True)
        consumer.start()
        consumer.join(TURN_TIMEOUT_SECONDS)
        assert not consumer.is_alive(), (
            f"the graph turn on {session_id!r} did not finish within {TURN_TIMEOUT_SECONDS}s"
        )
        if errors:
            raise errors[0]
        self.next_seed = None
        failed = [
            (event.error, event.metadata) for event in events if event.type == StreamEventType.ERROR
        ]
        assert failed == [], f"the graph turn on {session_id!r} failed: {failed}"

        latest = self.checkpointer.get_tuple({"configurable": {"thread_id": session_id}})
        assert latest is not None, f"no checkpoint persisted for {session_id!r}"
        records = [
            record
            for record in self.caplog.records[record_start:]
            if record.name == RUNTIME_LOGGER and record.getMessage() == "persisted_agent_invocation"
        ]
        initials = self.initials[initial_start:]
        assert len(initials) == 1, initials
        return TurnRecord(
            session_id=session_id,
            pin=pin,
            seeded_release_id=seed_release_id,
            events=events,
            calls=self.adapter.calls[call_start:],
            records=records,
            sends={
                node: payloads[send_start.get(node, 0) :] for node, payloads in self.sent.items()
            },
            initial=initials[0],
            checkpoint=dict(latest.checkpoint.get("channel_values") or {}),
        )


def open_turn_driver(journey, monkeypatch, caplog) -> GraphTurnDriver:
    """Patch the graph-mode seam onto the journey's database; return the driver.

    ``graph_chat_env``'s recipe, adapted: the graph's own database accessors go to
    the journey's PostgreSQL factory (``SessionManager`` and
    ``src.core.database.get_db_session`` are already bound by the journey), the
    naming model and settings are stubbed, the monolith is booby-trapped, and the
    runtime is production's, over ``PersistedGraphReleaseLoader`` with the
    production ``LoggingAgentInvocationIdentitySink``.
    """
    from src.services.graph import builder, routers

    factory = journey.factory

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

    for target in (
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
        "src.services.graph.nodes.get_db_session",
    ):
        monkeypatch.setattr(target, managed_session)
    monkeypatch.setattr("src.services.identity_provider.resolve_display_names", lambda emails: {})
    monkeypatch.setattr("src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None))
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title", lambda message, model: None
    )
    monkeypatch.setattr(
        "src.api.services.session_naming.build_session_title_model", MagicMock()
    )

    def explode(*args, **kwargs):
        raise _MonolithReached("a graph-mode turn reached _build_agent_for_session")

    monkeypatch.setattr(ChatService, "_build_agent_for_session", explode)

    adapter = _ToolFreeOrderedAdapter()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter,
        identity_sink=LoggingAgentInvocationIdentitySink(logger=logging.getLogger(RUNTIME_LOGGER)),
    )
    monkeypatch.setattr("src.services.graph.nodes.get_agent_runtime", lambda: runtime)
    caplog.set_level(logging.INFO, logger=RUNTIME_LOGGER)

    checkpointer = SqlAlchemyCheckpointSaver(session_factory=factory)
    graph = build_graph(checkpointer=checkpointer)
    monkeypatch.setattr(builder, "get_session_local", lambda: factory)
    monkeypatch.setattr(builder, "get_graph", lambda: graph)

    driver = GraphTurnDriver(
        journey=journey, adapter=adapter, checkpointer=checkpointer, caplog=caplog
    )

    saved_send = routers.Send

    def recording_send(node, arg):
        driver.sent[node].append(copy.deepcopy(arg))
        return saved_send(node, arg)

    monkeypatch.setattr(routers, "Send", recording_send)

    real_invoke_graph = builder.invoke_graph

    def seeding_invoke_graph(session_id, initial=None, **kwargs):
        # ``_send_message_streaming_graph`` imports ``invoke_graph`` lazily from
        # the builder, so this is the reachable seam for the graph INPUT.
        seeded = dict(initial or {})
        if driver.next_seed is not None:
            seeded["graph_release_id"] = driver.next_seed
        driver.initials.append(dict(seeded))
        return real_invoke_graph(session_id, seeded, **kwargs)

    monkeypatch.setattr(builder, "invoke_graph", seeding_invoke_graph)
    return driver


# ---------------------------------------------------------------------------
# Shared journey + turns
# ---------------------------------------------------------------------------


def _prose_strings() -> list[str]:
    """Every free-text leaf of the fake model outputs, plus the diagnostic note.

    "Prose" is a string leaf holding whitespace, markup or a URI; enumerated
    values (``build``, ``clean``, ``surfaced``) are role vocabulary, not output
    prose, and ``build`` is a substring of the allow-listed ``agent_key``
    ``builder``.
    """
    leaves: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            if any(marker in value for marker in (" ", "<", "://")):
                leaves.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for _role, output in _first_turn_outputs():
        visit(output.model_dump(mode="python"))
    return sorted(set(leaves) | {DIAGNOSTIC_NOTE})


@dataclass
class PinnedTurns:
    journey: Any
    driver: GraphTurnDriver
    turns: dict[str, TurnRecord]
    releases: dict[int, int]  # release id -> version number
    mappings: dict[int, dict[str, tuple[int, str]]]  # release id -> role -> (rev, hash)


def _run_pinned_turns(journey, monkeypatch, caplog, *, driving: Stage) -> PinnedTurns:
    """Run the journey to S16, then one first graph turn per pinned conversation.

    ``driving`` labels a failure while the turns run: ``S13`` when the test is
    about identity, ``S17`` when it is about bundles, so a turn that cannot
    execute a historical bundle is blamed on the bundle stage.
    """
    journey.run_to("S16")
    v1_id, v2_id, v3_id = (journey.state[k] for k in ("v1_id", "v2_id", "v3_id"))
    s16 = STAGES["S16"]
    require(s16, (v1_id, v2_id, v3_id) == (1, 3, 4), f"release ids {(v1_id, v2_id, v3_id)}")
    pins = {session: journey.pin_of(session) for session in PINNED_CONVERSATIONS}
    require(
        s16,
        pins == {"old-root": v1_id, "new-root": v2_id, "post-rollback-root": v3_id},
        f"pins are {pins}",
    )
    releases = {release_id: version for release_id, version, _active in journey.releases()}
    require(s16, releases == {v1_id: 1, v2_id: 2, v3_id: 3}, f"releases are {releases}")

    driver = open_turn_driver(journey, monkeypatch, caplog)
    #: Each turn's graph input is seeded with a DIFFERENT release than its pin.
    seeds = {"old-root": v2_id, "new-root": v3_id, "post-rollback-root": v1_id}
    turns: dict[str, TurnRecord] = {}
    with _in_stage(journey, driving):
        for session_id in PINNED_CONVERSATIONS:
            turns[session_id] = driver.drive(session_id, seed_release_id=seeds[session_id])
    mappings = {rid: _release_mapping(journey.factory, rid) for rid in (v1_id, v2_id, v3_id)}
    return PinnedTurns(journey, driver, turns, releases, mappings)


def _all_session_ids(journey) -> list[str]:
    return sorted(journey.pins())


# ---------------------------------------------------------------------------
# S13: state, fan-out, resolution, log contract, prompts, tools
# ---------------------------------------------------------------------------


def test_every_pinned_release_drives_its_own_revisions_through_state_fan_out_and_traces(
    lifecycle_journey,  # noqa: F811 (the imported fixture)
    monkeypatch,
    caplog,
) -> None:
    run = _run_pinned_turns(lifecycle_journey, monkeypatch, caplog, driving=S13)
    journey, adapter = run.journey, run.driver.adapter
    v1_id, v2_id, v3_id = (journey.state[k] for k in ("v1_id", "v2_id", "v3_id"))
    session_ids = _all_session_ids(journey)
    assert {"old-root", "new-root", "post-rollback-root", "mid-root", "control-legacy"} <= set(
        session_ids
    ) and len(session_ids) == 7, session_ids
    prose = _prose_strings()
    assert len(prose) >= 6, prose  # non-vacuous: messages, synthesis, source, HTML

    with _in_stage(journey, S13):
        # v3 restores v1's revisions under a new version number.
        assert run.mappings[v3_id] == run.mappings[v1_id]
        changed = {
            role
            for role in run.mappings[v1_id]
            if run.mappings[v2_id][role] != run.mappings[v1_id][role]
        }
        assert changed == {"architect", "builder", "fixer"}, changed

        for session_id, turn in run.turns.items():
            pin = turn.pin
            version = run.releases[pin]
            mapping = run.mappings[pin]
            where = f"{session_id} (pin id {pin}, v{version})"

            # The turn ran on the graph to completion.
            types_ = [event.type for event in turn.events]
            assert StreamEventType.ERROR not in types_, (where, [e.error for e in turn.events])
            assert types_[-1] == StreamEventType.COMPLETE, (where, types_)

            # (state) the seed reached the graph input and was overwritten.
            assert turn.initial == {
                "architect_message": MESSAGE,
                "graph_release_id": turn.seeded_release_id,
            }, where
            assert turn.seeded_release_id != pin
            assert turn.checkpoint["session_id"] == session_id, where
            assert turn.checkpoint["graph_release_id"] == pin, (
                where,
                turn.checkpoint["graph_release_id"],
            )
            turn_id = turn.checkpoint["turn_id"]
            assert isinstance(turn_id, str) and turn_id, where

            # (fan-out) every Send carries the pin.
            assert set(turn.sends) == {"builder", "build_reviewer"}, (where, sorted(turn.sends))
            assert [p["graph_release_id"] for p in turn.sends["builder"]] == [pin], where
            assert [p["graph_release_id"] for p in turn.sends["build_reviewer"]] == [pin], where

            # The model saw exactly A1, in order, through the real adapter.
            assert [call.agent_key for call in turn.calls] == list(A1_ROLES), where

            # (resolution) one production record per model call, exact identities.
            identities = [
                (
                    r.agent_key,
                    r.graph_release_id,
                    r.graph_version,
                    r.agent_definition_revision_id,
                    r.content_hash,
                )
                for r in turn.records
            ]
            assert identities == [
                (role, pin, version, mapping[role][0], mapping[role][1]) for role in A1_ROLES
            ], where
            if session_id == "post-rollback-root":
                assert version == 3
                assert [i[3] for i in identities] == [run.mappings[v1_id][r][0] for r in A1_ROLES]

            # (log contract) the exact allow-list; names only; no prose, no session id.
            for record in turn.records:
                extras = {
                    k: v for k, v in vars(record).items() if k not in STANDARD_LOG_RECORD_ATTRS
                }
                assert set(extras) == SUCCESS_RECORD_FIELDS, (where, sorted(extras))
                assert (record.outcome, record.error_class) == ("success", None), where
                expected_names = (
                    ["diagnostic_notes"] if (version, record.agent_key) == (2, "builder") else []
                )
                assert type(record.additional_field_names) is list, where
                assert record.additional_field_names == expected_names, (
                    where,
                    record.agent_key,
                    record.additional_field_names,
                )
                rendered = rendered_record(record)
                leaked = [s for s in prose + session_ids if s in rendered]
                assert leaked == [], (where, record.agent_key, leaked)

            # (no identifiers to the model)
            forbidden = [*session_ids, ADMIN, OWNER, CONTRIBUTOR, turn_id, *FORBIDDEN_PROMPT_KEYS]
            for call in turn.calls:
                leaked = [token for token in forbidden if token in call.prompt]
                assert leaked == [], (where, call.agent_key, leaked)

        # (no tools, AC5) through the real DatabricksModelAdapter, every call.
        total_calls = len(A1_ROLES) * len(PINNED_CONVERSATIONS)
        assert len(adapter.calls) == total_calls
        assert adapter.tool_bindings == []
        assert [name for name, _schema, _kw in adapter.method_calls] == [
            "with_structured_output"
        ] * total_calls
        assert [schema for _name, schema, _kw in adapter.method_calls] == [
            call.schema for call in adapter.calls
        ]
        assert adapter.chat_prompts == [call.prompt for call in adapter.calls]
        assert not adapter.entries

        # (no fabricated ids) across every record the turns emitted.
        all_records = [r for turn in run.turns.values() for r in turn.records]
        assert len(all_records) == total_calls
        assert {r.graph_release_id for r in all_records} == {v1_id, v2_id, v3_id}
        assert {(r.graph_release_id, r.graph_version) for r in all_records} == {
            (v1_id, 1),
            (v2_id, 2),
            (v3_id, 3),
        }
        assert journey.tripwire.reads == []


# ---------------------------------------------------------------------------
# S17: every readable release executes with its own bundles
# ---------------------------------------------------------------------------


def test_every_readable_release_executes_with_its_own_bundles_after_it_stops_being_active(
    lifecycle_journey,  # noqa: F811 (the imported fixture)
    monkeypatch,
    caplog,
) -> None:
    run = _run_pinned_turns(lifecycle_journey, monkeypatch, caplog, driving=S17)
    journey = run.journey
    v1_id, v2_id, v3_id = (journey.state[k] for k in ("v1_id", "v2_id", "v3_id"))

    with _in_stage(journey, S17):
        # v2 is readable but no longer active.
        assert journey.releases() == [(v1_id, 1, False), (v2_id, 2, False), (v3_id, 3, True)]

        # Every persisted revision's bundles resolve by exact version and digest.
        assembler, registry = PromptAssembler(), AgentSchemaRegistry()
        with journey.factory() as db:
            rows = list(
                db.scalars(select(AgentDefinitionRevision).order_by(AgentDefinitionRevision.id))
            )
        assert len(rows) == 10, [(r.id, r.agent_key) for r in rows]  # 7 at v1 + 3 at v2
        bundles: dict[int, tuple[str, int, int]] = {}
        for row in rows:
            content = definition_content_from_row(row)
            protected = assembler.resolve_bundle(content.protected_assembly)
            assert (protected.identity.version, protected.identity.digest) == (
                content.protected_assembly.version,
                content.protected_assembly.digest,
            ), row.agent_key
            identity = schema_contract_identity(row.agent_key, content.schema_contract)
            assert registry.identity_for(row.agent_key, identity.version) == SchemaContractIdentity(
                row.agent_key, content.schema_contract.version, content.schema_contract.digest
            ), row.agent_key
            registry.compose(row.agent_key, identity, content.schema_overlay)
            bundles[row.id] = (
                row.agent_key,
                content.protected_assembly.version,
                content.schema_contract.version,
            )

        v2_map, v3_map = run.mappings[v2_id], run.mappings[v3_id]
        # v2 holds architect on protected v2 and builder on schema v2, as literals.
        assert bundles[v2_map["architect"][0]] == ("architect", 2, 1)
        assert bundles[v2_map["builder"][0]] == ("builder", 1, 2)
        with journey.factory() as db:
            architect_v2 = db.get(AgentDefinitionRevision, v2_map["architect"][0])
            builder_v2 = db.get(AgentDefinitionRevision, v2_map["builder"][0])
            assert architect_v2.protected_assembly_digest == ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST
            assert builder_v2.schema_contract_digest == BUILDER_SCHEMA_CONTRACT_V2_DIGEST
        # v3 (the rollback) holds every role on the v1 bundles.
        assert {bundles[rev][1:] for rev, _hash in v3_map.values()} == {(1, 1)}

        def bound(session_id: str, role: str) -> list[type[BaseModel]]:
            return [c.schema for c in run.turns[session_id].calls if c.agent_key == role]

        def prompts(session_id: str, role: str) -> list[str]:
            return [c.prompt for c in run.turns[session_id].calls if c.agent_key == role]

        # The non-active v2 executed with ITS bundles: the composed v2 builder
        # schema and the v2 architect assembly carrying the custom block.
        assert len(bound("new-root", "builder")) == 2
        assert all("diagnostic_notes" in s.model_fields for s in bound("new-root", "builder"))
        assert all(CUSTOM_BLOCK_TEXT in p for p in prompts("new-root", "architect"))
        # v3 and v1 executed with the v1 bundles: no optional field, no custom block.
        for session_id in ("post-rollback-root", "old-root"):
            assert len(bound(session_id, "builder")) == 2, session_id
            assert all(
                "diagnostic_notes" not in s.model_fields for s in bound(session_id, "builder")
            ), session_id
            assert not any(CUSTOM_BLOCK_TEXT in p for p in prompts(session_id, "architect")), (
                session_id
            )
        assert journey.tripwire.reads == []

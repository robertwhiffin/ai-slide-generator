"""#271 Task 8: explicit Lakebase-contract failures preserve conversation state (AC3, AC2).

Two halves, both over real PostgreSQL.

Every creator needs a pin (AC2)
-------------------------------
On a fresh database where Graph Version 1 was never bootstrapped, each of the
seven graph-capable creators (#269's ``CREATORS``) refuses with
``ActiveGraphReleaseUnavailableError`` through ``_create`` (C38/C51), writes no
``user_sessions`` row and reads no code-owned definition (the AC1 tripwire).
The five creators reachable over HTTP answer 503 "No active Graph Release
available" through the shipped sessions and chat routers.  (The refusals are
landed #261/#262 behaviour: this is a regression pin, C18.5.)

Explicit invocation failures preserve conversation state (AC3)
--------------------------------------------------------------
Task 6's journey runs to ``S12`` (v1 = id 1, v2 = id 3 active, ``new-root``
pinned to v2).  Task 7's turn driver then drives one SUCCESSFUL first graph turn
on ``new-root`` so the conversation has messages, a deck, slides and a
checkpoint.  ``_conversation_state`` is captured, one failure is installed, and
a second turn goes in through the shipped ``ChatService.send_message_streaming``.
Each failure must surface as exactly the safe ``pinned_graph_configuration_
unavailable`` event, raise the exact typed error, never call the model for the
failing role on a substitute definition, never query the active release while a
release is being selected, and leave the conversation state exactly as it was
apart from what is documented (``_expected_after_failed_turn``): the turn's own
user message (C47(e)), the narration of nodes that completed before a later-node
failure, and the failed turn's appended checkpoints.

The three engine-mode sites fail closed over the shipped chat router (C24/C47):
``/chat/stream`` and ``/chat/async`` answer the typed 503 ``lakebase_unavailable``
with the session lock released, and the SSE re-resolve emits the safe event.

Cases already landed in ``test_persisted_graph_runtime_failures_postgres.py``
(C18.1/C38) at the loader and runtime level, and not repeated here: nonexistent
and incomplete releases, an unknown protected contract, a raising session
factory, a removed pinned endpoint, and persisted corruption escaping later-node
recovery.  This file adds the shipped-seam delta: the same failure families
driven through a real compiled graph turn (which needs C52: a typed error raised
inside a LangGraph node used to reach the chat seam as ``TypeError``), plus the
engine-mode fail-closed sites (C24/C47) and the legacy null-pin conversation.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.api.routes import chat as chat_routes
from src.api.routes import sessions as sessions_routes
from src.api.schemas.streaming import StreamEventType
from src.api.services import job_queue
from src.core.database import get_db
from src.core.permission_context import PermissionContext, set_permission_context
from src.core.user_context import set_current_user
from src.database.models.deck_contributor import DeckContributor
from src.database.models.graph_checkpoint import GraphCheckpoint
from src.database.models.graph_configuration import GraphDraft, GraphRelease
from src.database.models.session import (
    SessionMessage,
    SessionSlide,
    SessionSlideDeck,
    UserSession,
)
from src.domain.conversation_engine import AGENT_MODE_PHRASE
from src.services import agent_schema_registry
from src.services.agent_runtime import AgentRuntime, ModelProviderUnavailableError
from src.services.agent_runtime_identity import LoggingAgentInvocationIdentitySink
from src.services.conversation_pins import ActiveGraphReleaseUnavailableError
from src.services.persisted_graph_release import (
    GraphReleaseNotFoundError,
    PersistedConfigurationUnavailableError,
    PersistedGraphReleaseLoader,
    PinnedInvocationEndpointError,
)
from tests.integration.graph_lifecycle_journey import (  # noqa: F401 (fixtures)
    ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST,
    OWNER,
    SONNET,
    CodeDefaultTripwire,
    acceptance_stack,
    lifecycle_journey,
)
from tests.integration.test_conversation_pin_acceptance_postgres import (
    A1_ROLES,
    _first_turn_outputs,
    _release_mapping,
)
from tests.integration.test_graph_lifecycle_runtime_postgres import (
    MESSAGE,
    RUNTIME_LOGGER,
    TURN_TIMEOUT_SECONDS,
    GraphTurnDriver,
    open_turn_driver,
)
from tests.integration.test_graph_release_rollback_acceptance_postgres import (
    _session_manager_on,
)
from tests.integration.test_mixed_release_creation_postgres import (
    CREATORS,
    _create,
    _creator_patches,
)

pytestmark = pytest.mark.postgres

SAFE_EVENT = job_queue.pinned_graph_configuration_error_event_payload()
ACTOR = "actor@example.com"
SOURCE_OWNER = "owner@example.com"


# ---------------------------------------------------------------------------
# The conversation state (the Produces interface)
# ---------------------------------------------------------------------------


def _digest(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, bytes)):
        value = json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _conversation_state(factory: sessionmaker, session_id: str) -> dict[str, Any]:
    """Everything a failed turn must leave alone, for one conversation.

    The message rows (id, role, content hash), the latest checkpoint id (and the
    whole root-namespace checkpoint chain: id, parent, blob hash), the deck row
    and its slide rows (ids and content hashes), the pin, and
    ``graph_draft.lock_version``.
    """
    with factory() as db:
        session = db.scalar(select(UserSession).where(UserSession.session_id == session_id))
        assert session is not None, session_id
        messages = [
            (row.id, row.role, _digest(row.content))
            for row in db.scalars(
                select(SessionMessage)
                .where(SessionMessage.session_id == session.id)
                .order_by(SessionMessage.id)
            )
        ]
        checkpoints = [
            (row.checkpoint_id, row.parent_checkpoint_id, _digest(row.checkpoint_blob))
            for row in db.scalars(
                select(GraphCheckpoint)
                .where(GraphCheckpoint.thread_id == session_id, GraphCheckpoint.checkpoint_ns == "")
                .order_by(GraphCheckpoint.checkpoint_id)
            )
        ]
        deck = db.scalar(select(SessionSlideDeck).where(SessionSlideDeck.session_id == session.id))
        deck_row = (
            None
            if deck is None
            else (
                deck.id,
                _digest(deck.title),
                _digest(deck.html_content),
                _digest(deck.deck_json),
                deck.slide_count,
            )
        )
        slides = [
            (row.position, row.id, row.slide_id, _digest(row.html), _digest(row.scripts))
            for row in db.scalars(
                select(SessionSlide)
                .where(SessionSlide.session_id == session.id)
                .order_by(SessionSlide.position)
            )
        ]
        lock_version = db.scalar(select(GraphDraft.lock_version).where(GraphDraft.id == 1))
        return {
            "messages": messages,
            "latest_checkpoint_id": checkpoints[-1][0] if checkpoints else None,
            "checkpoints": checkpoints,
            "deck": deck_row,
            "slides": slides,
            "pin": session.graph_release_id,
            "graph_draft_lock_version": lock_version,
        }


def _expected_after_failed_turn(
    driver: GraphTurnDriver,
    session_id: str,
    before: dict[str, Any],
    *,
    narration: tuple[str, ...] = (),
) -> dict[str, Any]:
    """``before`` plus exactly what a failed turn is DOCUMENTED to leave, nothing else.

    * **This turn's user message** (C47(e)): ``send_message_streaming`` persists
      it before the graph (or the engine re-resolve) runs.  Asserted to be one
      new ``role='user'`` row carrying ``MESSAGE``.
    * **Assistant narration of nodes that COMPLETED before the failure**
      (``narration``: content hashes, in order).  Nodes commit as they finish,
      so a failure at a later node (the removed fixer endpoint) leaves the
      earlier nodes' messages.  A failure at the first model call leaves none.
    * **The failed turn's own checkpoints.**  LangGraph writes the turn's input
      checkpoint before the first node runs.  They are only APPENDED: every
      checkpoint from before is byte-identical, each new one descends from the
      previous latest, and the new latest still carries exactly the pin.

    Everything else (earlier messages, the deck row, every slide row, the pin
    and ``graph_draft.lock_version``) must be byte-identical.
    """
    after = _conversation_state(driver.journey.factory, session_id)
    prior = len(before["messages"])
    assert after["messages"][:prior] == before["messages"], after["messages"]
    appended = after["messages"][prior:]
    assert [(role, digest) for _id, role, digest in appended] == [
        ("user", _digest(MESSAGE)),
        *(("assistant", digest) for digest in narration),
    ], appended

    chain = before["checkpoints"]
    assert set(chain) <= set(after["checkpoints"]), after["checkpoints"]
    new = [row for row in after["checkpoints"] if row not in chain]
    if new:
        by_id = {row[0]: row for row in after["checkpoints"]}
        latest = before["latest_checkpoint_id"]
        for checkpoint_id, parent_id, _blob in sorted(new):
            assert parent_id == latest, (checkpoint_id, parent_id, latest)
            latest = checkpoint_id
        assert latest == after["latest_checkpoint_id"] and latest in by_id
        tip = driver.checkpointer.get_tuple(
            {"configurable": {"thread_id": session_id, "checkpoint_id": latest}}
        )
        assert tip.checkpoint["channel_values"]["graph_release_id"] == before["pin"]
    return {
        **before,
        "messages": before["messages"] + appended,
        "checkpoints": after["checkpoints"] if new else before["checkpoints"],
        "latest_checkpoint_id": after["latest_checkpoint_id"]
        if new
        else before["latest_checkpoint_id"],
    }


# ---------------------------------------------------------------------------
# The active-release statement spy
# ---------------------------------------------------------------------------


class ActiveReleaseSpy:
    """Records every statement that reads the active release while armed.

    Armed only around the two places a release is SELECTED for a turn: the pin
    load (``invoke_graph``'s ``pin_loader``) and every ``AgentRuntime.run``.  The
    architect's session-contract read goes through ``SessionManager.get_session``,
    whose public projection legitimately reads the active release to compute
    ``is_older_than_active`` and selects nothing, so it is outside the window.
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        self.armed = False
        self.statements: list[str] = []

    def armed_call(self, function: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            previous, self.armed = self.armed, True
            try:
                return function(*args, **kwargs)
            finally:
                self.armed = previous

        return call

    def __call__(self, _conn, _cursor, statement, _params, _context, _executemany) -> None:
        if not self.armed:
            return
        normalized = " ".join(statement.lower().split())
        if "graph_release" in normalized and "effective_to is null" in normalized:
            self.statements.append(normalized)

    @contextlib.contextmanager
    def listening(self) -> Iterator[ActiveReleaseSpy]:
        event.listen(self.engine, "before_cursor_execute", self)
        try:
            yield self
        finally:
            event.remove(self.engine, "before_cursor_execute", self)


# ---------------------------------------------------------------------------
# Failing turns through the shipped seam
# ---------------------------------------------------------------------------


@dataclass
class FailedTurn:
    events: list[Any]
    error: BaseException | None
    calls: list[str]  # adapter roles invoked during this turn
    log_records: list[logging.LogRecord]


def _drive_failing_turn(
    driver: GraphTurnDriver,
    session_id: str,
    *,
    spy: ActiveReleaseSpy | None = None,
    outputs: list | None = None,
) -> FailedTurn:
    """One graph turn on ``session_id`` that is expected to fail.

    The same seam as Task 7's ``GraphTurnDriver.drive`` (a context-copied
    consumer thread, bounded join), but it returns the events and the error
    instead of asserting success.  ``spy`` is armed around the pin load and every
    ``AgentRuntime.run`` (see :class:`ActiveReleaseSpy`).
    """
    from src.services.graph import builder

    adapter = driver.adapter
    adapter.entries.clear()
    if outputs:
        adapter.entries.extend(outputs)
    call_start = len(adapter.calls)
    record_start = len(driver.caplog.records)

    events: list[Any] = []
    errors: list[BaseException] = []
    set_current_user(OWNER)
    set_permission_context(PermissionContext(user_name=OWNER))
    context = contextvars.copy_context()

    from src.services import conversation_pins

    patched = builder.invoke_graph

    def spied_invoke_graph(*args, **kwargs):
        if spy is not None:
            kwargs["pin_loader"] = spy.armed_call(conversation_pins.load_conversation_pin)
        return patched(*args, **kwargs)

    def consume() -> None:
        try:
            for item in driver.service.send_message_streaming(
                session_id=session_id,
                message=MESSAGE,
                is_first_message_override=False,
                engine_mode="graph",
            ):
                events.append(item)
        except BaseException as exc:  # noqa: BLE001 (returned to the caller)
            errors.append(exc)

    run_patch = (
        patch.object(AgentRuntime, "run", spy.armed_call(AgentRuntime.run))
        if spy is not None
        else contextlib.nullcontext()
    )
    with patch.object(builder, "invoke_graph", spied_invoke_graph), run_patch:
        consumer = threading.Thread(target=lambda: context.run(consume), daemon=True)
        consumer.start()
        consumer.join(TURN_TIMEOUT_SECONDS)
    assert not consumer.is_alive(), f"the failing turn on {session_id!r} did not finish"
    adapter.entries.clear()
    return FailedTurn(
        events=events,
        error=errors[0] if errors else None,
        calls=[call.agent_key for call in adapter.calls[call_start:]],
        log_records=list(driver.caplog.records[record_start:]),
    )


def _assert_one_safe_event(turn: FailedTurn) -> None:
    public = [item.model_dump(mode="json", exclude_none=True) for item in turn.events]
    errors = [item for item in turn.events if item.type == StreamEventType.ERROR]
    assert len(errors) == 1, public
    assert job_queue.is_pinned_graph_configuration_error_event(errors[0]), public
    assert turn.events[-1] is errors[0], public
    assert not any(item.type == StreamEventType.COMPLETE for item in turn.events), public
    rendered = repr(public)
    for forbidden in ("Traceback", "TypeError", "super(type", "graph_release_id", SONNET):
        assert forbidden not in rendered, rendered


def _safe_log_classes(turn: FailedTurn) -> list[tuple[str, Any]]:
    return [
        (record.error_class, record.graph_release_id)
        for record in turn.log_records
        if record.getMessage() == "pinned_graph_configuration_unavailable"
    ]


def _replace_runtime(monkeypatch, driver: GraphTurnDriver, loader) -> AgentRuntime:
    runtime = AgentRuntime(
        persisted_release_loader=loader,
        model_adapter=driver.adapter,
        identity_sink=LoggingAgentInvocationIdentitySink(logger=logging.getLogger(RUNTIME_LOGGER)),
    )
    monkeypatch.setattr("src.services.graph.nodes.get_agent_runtime", lambda: runtime)
    return runtime


@dataclass
class PinnedFailureStage:
    journey: Any
    driver: GraphTurnDriver
    spy: ActiveReleaseSpy
    v2_id: int
    before: dict[str, Any]


@pytest.fixture
def pinned_failure_stage(lifecycle_journey, monkeypatch, caplog) -> Iterator[PinnedFailureStage]:  # noqa: F811
    """``run_to("S12")``, one successful ``new-root`` turn, then the state snapshot."""
    journey = lifecycle_journey.run_to("S12")
    v2_id = journey.state["v2_id"]
    assert (journey.state["v1_id"], v2_id) == (1, 3), journey.state
    assert journey.pin_of("new-root") == v2_id
    caplog.set_level(logging.INFO)
    # The safe log's release id falls back to the persisted pin through the
    # production ``src.core.database.get_session_local`` (``_pinned_graph_failure
    # _release_id``); point it at the journey's database.
    monkeypatch.setattr("src.core.database.get_session_local", lambda: journey.factory)
    driver = open_turn_driver(journey, monkeypatch, caplog)
    first = driver.drive("new-root", seed_release_id=journey.state["v1_id"])
    assert first.checkpoint["graph_release_id"] == v2_id
    engine = journey.factory.kw["bind"]
    before = _conversation_state(journey.factory, "new-root")
    assert before["pin"] == v2_id
    assert before["deck"] is not None and before["slides"], before
    assert before["latest_checkpoint_id"] is not None, before
    with ActiveReleaseSpy(engine).listening() as spy:
        yield PinnedFailureStage(journey, driver, spy, v2_id, before)
    assert journey.tripwire.reads == []


# ---------------------------------------------------------------------------
# AC3: explicit invocation failures on a pinned conversation
# ---------------------------------------------------------------------------


class _LostReleaseLoader:
    """A loader whose pinned release row is gone (the pin is non-null by FK)."""

    def __init__(self) -> None:
        self.requested: list[tuple[int, str]] = []

    def resolve(self, graph_release_id: int, agent_key: str):
        self.requested.append((graph_release_id, agent_key))
        raise GraphReleaseNotFoundError(graph_release_id)


def test_a_lost_pinned_release_fails_the_turn_safely_and_preserves_state(
    pinned_failure_stage, monkeypatch
):
    stage = pinned_failure_stage
    loader = _LostReleaseLoader()
    _replace_runtime(monkeypatch, stage.driver, loader)

    turn = _drive_failing_turn(stage.driver, "new-root", spy=stage.spy)

    assert type(turn.error) is GraphReleaseNotFoundError, turn.error
    assert turn.error.args == (stage.v2_id,)
    _assert_one_safe_event(turn)
    assert loader.requested == [(stage.v2_id, "architect")]
    assert turn.calls == []
    assert _safe_log_classes(turn) == [("GraphReleaseNotFoundError", stage.v2_id)]
    assert stage.spy.statements == []
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(stage.driver, "new-root", stage.before)


class _UnavailableSession:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def execute(self, _statement):
        raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))


def _factory_that_raises():
    raise OperationalError("connect", {}, Exception("could not connect to server"))


@pytest.mark.parametrize("failure_point", ["session_factory", "statement"])
def test_lakebase_unavailable_fails_the_turn_without_an_active_release_query(
    pinned_failure_stage, monkeypatch, failure_point
):
    """A FRESH loader (C18.4): the turn driver's cached release would be served from memory.

    ``session_factory`` raises inside the loader's session boundary;
    ``statement`` opens a session whose statement raises, which reaches the
    runtime's own ``SQLAlchemyError`` branch.  Neither may fall back to any
    release: the spy sees every statement the graph turn issues.
    """
    stage = pinned_failure_stage
    opened: list[str] = []

    def unavailable_factory():
        opened.append(failure_point)
        if failure_point == "session_factory":
            return _factory_that_raises()
        return _UnavailableSession()

    _replace_runtime(
        monkeypatch, stage.driver, PersistedGraphReleaseLoader(session_factory=unavailable_factory)
    )

    turn = _drive_failing_turn(stage.driver, "new-root", spy=stage.spy)

    assert type(turn.error) is PersistedConfigurationUnavailableError, turn.error
    assert turn.error.code == "lakebase_unavailable"
    assert isinstance(turn.error.__cause__, OperationalError)
    _assert_one_safe_event(turn)
    assert opened == [failure_point]
    assert turn.calls == []
    assert _safe_log_classes(turn) == [("PersistedConfigurationUnavailableError", stage.v2_id)]
    assert stage.spy.statements == []
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(stage.driver, "new-root", stage.before)


def test_a_removed_pinned_endpoint_is_attempted_once_and_names_the_exact_pin(
    pinned_failure_stage, monkeypatch
):
    """Fixer on v2 is pinned to sonnet (S06); that exact endpoint is gone."""
    stage = pinned_failure_stage
    adapter = stage.driver.adapter
    real_invoke = adapter.invoke
    attempts: list[tuple[str, str]] = []

    def removed_fixer_endpoint(*, agent_key, configuration, schema, prompt):
        if agent_key == "fixer":
            attempts.append((agent_key, configuration.endpoint_name))
            raise ModelProviderUnavailableError(f"endpoint {configuration.endpoint_name} removed")
        return real_invoke(
            agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt
        )

    monkeypatch.setattr(adapter, "invoke", removed_fixer_endpoint)
    fixer_revision_id = _release_revision(stage.journey.factory, stage.v2_id, "fixer")

    turn = _drive_failing_turn(
        stage.driver, "new-root", spy=stage.spy, outputs=_first_turn_outputs()
    )

    assert type(turn.error) is PinnedInvocationEndpointError, turn.error
    assert turn.error.endpoint_name == SONNET == "databricks-claude-sonnet-4-5"
    assert turn.error.graph_release_id == stage.v2_id
    assert turn.error.agent_definition_revision_id == fixer_revision_id
    _assert_one_safe_event(turn)
    assert attempts == [("fixer", SONNET)]
    assert turn.calls == list(A1_ROLES[: A1_ROLES.index("fixer")])  # nothing after fixer
    assert _safe_log_classes(turn) == [("PinnedInvocationEndpointError", stage.v2_id)]
    assert stage.spy.statements == []
    # Fixer is the seventh model call, so the nodes before it completed and
    # committed their narration: the same outputs as the successful first turn,
    # hence the same first three assistant rows.  Nothing from the fixer on is
    # written, and the deck and slide rows are untouched.
    first_turn_narration = tuple(
        digest for _id, role, digest in stage.before["messages"] if role == "assistant"
    )[:3]
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(
        stage.driver, "new-root", stage.before, narration=first_turn_narration
    )


def _release_revision(factory, release_id: int, agent_key: str) -> int:
    return _release_mapping(factory, release_id)[agent_key][0]


def test_an_unavailable_historical_protected_bundle_is_never_substituted(
    pinned_failure_stage, monkeypatch
):
    """v2's architect is on protected assembly (2, fb651a0d…); drop only that bundle (C32)."""
    stage = pinned_failure_stage
    runtime = _replace_runtime(
        monkeypatch,
        stage.driver,
        PersistedGraphReleaseLoader(session_factory=stage.journey.factory),
    )
    removed = runtime._prompt_assembler._bundles.pop((2, ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST))
    assert removed is not None
    assert any(version == 1 for version, _digest in runtime._prompt_assembler._bundles)

    turn = _drive_failing_turn(stage.driver, "new-root", spy=stage.spy)

    assert type(turn.error) is PersistedConfigurationUnavailableError, turn.error
    assert turn.error.code == "protected_bundle_unavailable"
    _assert_one_safe_event(turn)
    assert turn.calls == []  # no v1 substitution reached the model
    assert _safe_log_classes(turn) == [("PersistedConfigurationUnavailableError", stage.v2_id)]
    assert stage.spy.statements == []
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(stage.driver, "new-root", stage.before)


def test_an_unavailable_historical_schema_contract_is_never_substituted(
    pinned_failure_stage, monkeypatch
):
    """v2's builder is on schema contract ("builder", 2); drop only that bundle (C32)."""
    stage = pinned_failure_stage
    bundles = dict(agent_schema_registry.SCHEMA_CONTRACT_BUNDLES)
    assert bundles.pop(("builder", 2)) is not None
    assert ("builder", 1) in bundles
    monkeypatch.setattr(agent_schema_registry, "SCHEMA_CONTRACT_BUNDLES", MappingProxyType(bundles))
    _replace_runtime(
        monkeypatch,
        stage.driver,
        PersistedGraphReleaseLoader(session_factory=stage.journey.factory),
    )

    turn = _drive_failing_turn(
        stage.driver, "new-root", spy=stage.spy, outputs=_first_turn_outputs()
    )

    assert type(turn.error) is PersistedConfigurationUnavailableError, turn.error
    assert turn.error.code == "schema_contract_unavailable"
    _assert_one_safe_event(turn)
    # The builder never reached the model on a substitute (v1) schema.
    assert turn.calls == list(A1_ROLES[: A1_ROLES.index("builder")])
    assert _safe_log_classes(turn) == [("PersistedConfigurationUnavailableError", stage.v2_id)]
    assert stage.spy.statements == []
    # architect, data_analyst, architect completed and narrated before the builder.
    first_turn_narration = tuple(
        digest for _id, role, digest in stage.before["messages"] if role == "assistant"
    )[:3]
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(
        stage.driver, "new-root", stage.before, narration=first_turn_narration
    )


def test_a_legacy_null_pin_conversation_runs_no_graph_turn_and_is_never_pinned(
    pinned_failure_stage,
):
    """C37's control conversation: created with the default body, so its pin is null."""
    stage = pinned_failure_stage
    factory = stage.journey.factory
    before = _conversation_state(factory, "control-legacy")
    assert before["pin"] is None
    assert before["latest_checkpoint_id"] is None

    turn = _drive_failing_turn(stage.driver, "control-legacy", spy=stage.spy)

    assert type(turn.error) is PersistedConfigurationUnavailableError, turn.error
    assert turn.error.code == "conversation_pin_unavailable"
    _assert_one_safe_event(turn)
    assert turn.calls == []
    assert _safe_log_classes(turn) == [("ConversationPinMissingError", None)]
    assert stage.spy.statements == []
    after = _conversation_state(factory, "control-legacy")
    assert after == _expected_after_failed_turn(stage.driver, "control-legacy", before)
    assert after["checkpoints"] == []  # the pin load refused before any graph step
    assert after["pin"] is None
    assert stage.journey.pin_of("control-legacy") is None


# ---------------------------------------------------------------------------
# AC3 / C24: engine-mode resolution fails CLOSED at all three chat sites
# ---------------------------------------------------------------------------


class _BlippingResolver:
    """The REAL ``resolve_engine_mode``, whose database read fails on chosen calls.

    Failing call numbers (1-based) run the real resolver under a
    ``get_db_session`` that raises ``OperationalError`` at the database
    boundary; every other call runs it unmodified against the journey database.
    """

    def __init__(self, real: Callable[[str | None], str], fail_on: set[int]) -> None:
        self.real = real
        self.fail_on = fail_on
        self.calls: list[tuple[str | None, str]] = []

    def __call__(self, session_id: str | None) -> str:
        number = len(self.calls) + 1
        if number not in self.fail_on:
            mode = self.real(session_id)
            self.calls.append((session_id, mode))
            return mode
        self.calls.append((session_id, "raised"))

        @contextlib.contextmanager
        def unavailable():
            raise OperationalError("SELECT", {}, Exception("server closed the connection"))
            yield  # pragma: no cover

        with patch("src.core.database.get_db_session", unavailable):
            return self.real(session_id)


def _is_processing(factory, session_id: str) -> bool:
    with factory() as db:
        return db.scalar(
            select(UserSession.is_processing).where(UserSession.session_id == session_id)
        )


def _chat_requests(factory, session_id: str) -> list[tuple[str, str | None]]:
    from src.database.models.session import ChatRequest as ChatRequestRow

    with factory() as db:
        internal = db.scalar(select(UserSession.id).where(UserSession.session_id == session_id))
        return [
            (row.status, row.error_message)
            for row in db.scalars(
                select(ChatRequestRow)
                .where(ChatRequestRow.session_id == internal)
                .order_by(ChatRequestRow.id)
            )
        ]


@pytest.fixture
def chat_route_stage(pinned_failure_stage, monkeypatch):
    """The shipped chat router on the journey's app, as the conversation owner."""
    from src.api.services import chat_service as chat_service_module

    stage = pinned_failure_stage
    app = stage.journey.admin.app
    app.include_router(chat_routes.router)
    enqueued: list[tuple[str, dict]] = []

    async def record_enqueue(request_id: str, payload: dict) -> None:
        enqueued.append((request_id, payload))

    monkeypatch.setattr(chat_routes, "enqueue_job", record_enqueue)
    monkeypatch.setattr(chat_routes, "get_chat_service", lambda: stage.driver.service)
    set_current_user(OWNER)
    set_permission_context(PermissionContext(user_name=OWNER))
    return stage, chat_service_module, enqueued


def _assert_typed_503(response) -> None:
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": chat_routes.ENGINE_MODE_UNAVAILABLE_DETAIL}
    assert response.json()["detail"]["code"] == "lakebase_unavailable"
    for leaked in ("server closed", "OperationalError", "Traceback", "graph_release"):
        assert leaked not in response.text, response.text


def test_the_stream_route_answers_503_releases_the_lock_and_runs_no_engine(
    chat_route_stage, monkeypatch
):
    stage, chat_service_module, _enqueued = chat_route_stage
    resolver = _BlippingResolver(chat_service_module.resolve_engine_mode, fail_on={1})
    monkeypatch.setattr(chat_service_module, "resolve_engine_mode", resolver)
    adapter_calls = len(stage.driver.adapter.calls)

    response = stage.journey.admin.post(
        "/api/chat/stream", json={"session_id": "new-root", "message": MESSAGE}
    )

    _assert_typed_503(response)
    assert resolver.calls == [("new-root", "raised")]
    assert _is_processing(stage.journey.factory, "new-root") is False
    assert len(stage.driver.adapter.calls) == adapter_calls  # no graph, no monolith
    # Nothing was persisted: the route failed before the service ran.
    assert _conversation_state(stage.journey.factory, "new-root") == stage.before


def test_the_async_route_answers_503_releases_the_lock_and_enqueues_nothing(
    chat_route_stage, monkeypatch
):
    stage, chat_service_module, enqueued = chat_route_stage
    resolver = _BlippingResolver(chat_service_module.resolve_engine_mode, fail_on={1})
    monkeypatch.setattr(chat_service_module, "resolve_engine_mode", resolver)

    response = stage.journey.admin.post(
        "/api/chat/async", json={"session_id": "new-root", "message": MESSAGE}
    )

    _assert_typed_503(response)
    assert resolver.calls == [("new-root", "raised")]
    assert enqueued == []
    assert _is_processing(stage.journey.factory, "new-root") is False
    # C47(e): the user message and the chat_requests row were persisted BEFORE
    # resolution and stay; the request row is left pending (no job was queued).
    assert _chat_requests(stage.journey.factory, "new-root") == [("pending", None)]
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(stage.driver, "new-root", stage.before)


def test_the_sse_re_resolve_fails_closed_with_the_safe_event_on_the_real_route(
    chat_route_stage, monkeypatch
):
    """C47(d): the route's resolution succeeds, the service's re-resolve blips."""
    stage, chat_service_module, _enqueued = chat_route_stage
    resolver = _BlippingResolver(chat_service_module.resolve_engine_mode, fail_on={2})
    monkeypatch.setattr(chat_service_module, "resolve_engine_mode", resolver)
    adapter_calls = len(stage.driver.adapter.calls)

    response = stage.journey.admin.post(
        "/api/chat/stream", json={"session_id": "new-root", "message": MESSAGE}
    )

    assert response.status_code == 200, response.text
    body = response.text
    assert resolver.calls == [("new-root", "graph"), ("new-root", "raised")]
    data = [
        json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")
    ]
    assert [{k: v for k, v in item.items() if v not in (None, "")} for item in data] == [
        SAFE_EVENT
    ], body
    assert "server closed" not in body and "OperationalError" not in body
    assert _is_processing(stage.journey.factory, "new-root") is False
    assert len(stage.driver.adapter.calls) == adapter_calls  # no graph, no monolith
    after = _conversation_state(stage.journey.factory, "new-root")
    assert after == _expected_after_failed_turn(stage.driver, "new-root", stage.before)


# ---------------------------------------------------------------------------
# AC2: every graph-capable creator refuses without an active release
# ---------------------------------------------------------------------------


def _seed_legacy_sources(factory) -> None:
    """Null-pin legacy sources for the copy creators, on a never-bootstrapped database.

    The duplicate source carries the agent-mode marker and a deck (C2/C18.2), so
    the duplicate is graph-capable and must select a release.
    """
    with factory.begin() as db:
        contributor_source = UserSession(
            session_id="contributor-source", created_by=SOURCE_OWNER, title="legacy source"
        )
        duplicate_source = UserSession(
            session_id="duplicate-source", created_by=SOURCE_OWNER, title="legacy source"
        )
        db.add_all([contributor_source, duplicate_source])
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=duplicate_source.id,
                title="legacy source",
                html_content="<div>legacy</div>",
                slide_count=1,
                deck_json='{"slides":[{"html":"<div>legacy</div>"}]}',
            )
        )
        db.add(
            SessionMessage(
                session_id=duplicate_source.id,
                role="user",
                content=f"{AGENT_MODE_PHRASE} duplicate",
            )
        )
        db.add(
            DeckContributor(
                user_session_id=contributor_source.id,
                identity_type="USER",
                identity_id="actor-id",
                identity_name=ACTOR,
                permission_level="CAN_VIEW",
            )
        )
        db.add(
            DeckContributor(
                user_session_id=duplicate_source.id,
                identity_type="USER",
                identity_id="actor-id",
                identity_name=ACTOR,
                permission_level="CAN_VIEW",
            )
        )


def _session_rows(factory) -> list[tuple[str, int | None]]:
    with factory() as db:
        return [
            (row.session_id, row.graph_release_id)
            for row in db.scalars(select(UserSession).order_by(UserSession.id))
        ]


@pytest.fixture
def unbootstrapped(postgres_engine, monkeypatch):
    """A fresh database where Graph Version 1 was never bootstrapped, tripwire armed."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    _seed_legacy_sources(factory)
    with factory() as db:
        assert db.scalars(select(GraphRelease)).all() == []
    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    yield factory, tripwire
    assert tripwire.reads == []


@pytest.mark.parametrize("creator", CREATORS)
def test_every_graph_capable_creator_refuses_without_an_active_release(unbootstrapped, creator):
    """All seven through ``_create`` raise the typed error, never HTTP (C51)."""
    factory, tripwire = unbootstrapped
    before = _session_rows(factory)
    assert before == [("contributor-source", None), ("duplicate-source", None)]

    with _creator_patches(factory), pytest.raises(ActiveGraphReleaseUnavailableError):
        _create(factory, creator)

    assert _session_rows(factory) == before
    assert tripwire.reads == []
    with factory() as db:
        assert db.scalars(select(GraphRelease)).all() == []


_NO_ACTIVE = (503, {"detail": "No active Graph Release available"})

#: creator -> (method, path, body, expected (status, json)).
ROUTE_CREATORS = {
    "explicit-root": (
        "POST",
        "/api/sessions",
        {"session_id": "route-root", "graph_capable": True},
        _NO_ACTIVE,
    ),
    "chat-generated-id": (
        "POST",
        "/api/chat/stream",
        {"message": f"{AGENT_MODE_PHRASE} go"},
        _NO_ACTIVE,
    ),
    "chat-supplied-id": (
        "POST",
        "/api/chat/async",
        {"session_id": "route-supplied", "message": f"{AGENT_MODE_PHRASE} go"},
        _NO_ACTIVE,
    ),
    # Fix round 1 (was a FINDING pinned at 500): the contribute route reads the
    # PARENT through ``SessionManager.get_session`` first, whose public
    # projection requires an active release.  With none, that read now surfaces
    # as the same typed refusal as every other creator, not a generic 500.
    "contributor": (
        "POST",
        "/api/sessions/contributor-source/contribute",
        None,
        _NO_ACTIVE,
    ),
    "duplicate": (
        "POST",
        "/api/sessions/duplicate-source/duplicate",
        None,
        _NO_ACTIVE,
    ),
}


@pytest.mark.parametrize("creator", sorted(ROUTE_CREATORS))
def test_every_route_creator_answers_503_without_an_active_release(
    unbootstrapped, monkeypatch, creator
):
    """The five creators reachable over HTTP, through the shipped routers (C51)."""
    factory, tripwire = unbootstrapped
    before = _session_rows(factory)

    app = FastAPI()
    app.include_router(sessions_routes.router)
    app.include_router(chat_routes.router)

    def _override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr("src.api.routes.chat.get_default_design_system_id", lambda: None)
    monkeypatch.setattr("src.api.routes.chat.get_default_slide_style_id", lambda: None)
    monkeypatch.setattr(chat_routes, "get_chat_service", MagicMock(side_effect=AssertionError))
    method, path, body, (status, expected) = ROUTE_CREATORS[creator]
    with _session_manager_on(factory) as manager:
        import src.api.services.session_manager as session_manager_module

        monkeypatch.setattr(
            "src.core.database.get_db_session", session_manager_module.get_db_session
        )
        monkeypatch.setattr("src.api.services.chat_service.get_session_manager", lambda: manager)
        set_current_user(ACTOR)
        set_permission_context(PermissionContext(user_name=ACTOR))
        try:
            with TestClient(app) as client:
                response = client.request(method, path, json=body)
        finally:
            set_permission_context(None)
            set_current_user(None)

    assert response.status_code == status, response.text
    assert response.json() == expected
    assert _session_rows(factory) == before
    assert tripwire.reads == []

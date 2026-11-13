# ruff: noqa: F811 — the conftest_graph fixture is imported, then requested by name.
"""Task 8: stop and rollback, accepted through REAL graph turns.

Every turn here runs the shipped path end to end:

    POST /api/chat/async            (the real route: lock, request row, snapshot,
                                     user message, deck-mode lock)
      -> job_queue.enqueue_job      (the real one, on the runners' event loop)
      -> job_queue.worker           (ONE real runner: concurrency 1, the default)
      -> process_chat_request       (real)
      -> ChatService graph limb     (real: consumer loop, liveness poll, seal,
                                     save point, title thread)
      -> invoke_graph               (real) over the COMPILED graph (real) with the
                                     real SqlAlchemyCheckpointSaver
      -> every node and writer      (real: SlideWriter, deck-level writer, deck
                                     review store, messages, progress, checkpoints)
    POST /api/chat/cancel/{id}      (the real stop route)
    GET  /api/chat/poll/{id}        (the real poll)

Only what reaches a Databricks workspace is replaced: ``AgentRuntime`` (the
``SkillStub`` of ``graph_env_threadsafe``, answering with the deterministic fakes
``architect_build`` / ``builder_out``-shaped outputs / ``review_out``), the brand
resolvers (the same fixture), the title model (``generate_session_title``), and the
request-log / usage-event background writers (no-ops, so "nothing changed" can
compare every table).

Thin wrappers observe real functions and call them unchanged: ``invoke_graph`` and
``process_chat_request`` (when each turn's graph thread and job ended),
``SlideWriter.write_slide`` and ``record_chat_request_progress`` (what landed, and
when a slide's pipeline was wholly done), ``rename_session`` (the title thread) and
``generation_rollback.roll_back_generation`` (the job's own rollbacks).  So a test
waits on an ``Event`` or ``Condition``, never on a sleep.  A model call is held
inside the graph by a :class:`Gate` (an ``Event`` pair), so a test can stop the turn
while the graph thread is provably still inside it.

"Exact" means the whole database: every row of every table is read before Enter,
at the moment of the stop, and after it, and compared with the established
all-table helpers of ``tests/unit/test_generation_rollback.py``
(``_assert_rolled_back_to_enter``: every table as at Enter, except the request's own
row, the deck's ``version``/``updated_at``, ``last_activity`` and the append-only
mutation log, each of which is checked exactly).  The one table the plan rules may
keep a stopped turn's row is ``deck_reviews`` (content-addressed; "Rulings from plan
review"), and only the race test reaches the deck reviewer; it checks that row
exactly instead.

``STOP_POLL_SECONDS`` is lowered to 0.05 s so a stopped job frees its runner fast;
nothing else depends on timing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

import src.core.checkpointer as checkpointer_module
from src.api.main import app
from src.api.services import chat_service as chat_service_module
from src.api.services import job_queue
from src.api.services.job_queue import PINNED_GRAPH_CONFIGURATION_ERROR
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import (
    PENDING_SLIDE_TEXT,
    SlideWriter,
    is_placeholder_record,
)
from src.core.checkpointer import get_checkpointer
from src.database.models.session import UserSession
from src.domain.deck_spec import DeckSpec
from src.domain.finding import DeckReviewOutput
from src.domain.skill_io import ArchitectOutput, BuilderOutput
from src.domain.slide_operations import SlideContent, SlideOperation
from src.services import generation_rollback
from src.services.agent_runtime import ModelProviderUnavailableError
from src.services.deck_review_store import compute_deck_digest
from src.services.generation_fence import TurnFencedError
from src.services.graph import builder as graph_builder
from src.services.graph.event_emitter import (
    chat_request_id_var,
    get_chat_request_id,
    set_event_emitter,
)
from src.services.graph.nodes import _conversation
from src.services.persisted_graph_release import PinnedInvocationEndpointError
from tests.unit.conftest_graph import (  # noqa: F401 -- graph_env_threadsafe is a fixture
    architect_build,
    graph_env_threadsafe,
    review_out,
)
from tests.unit.test_generation_rollback import (
    RollbackEnv,
    _assert_lock,
    _assert_rolled_back_to_enter,
    _assert_tables_equal,
    _messages_tagged,
    _one,
    _tables,
)

#: ``graph_env_threadsafe``'s session creator: the person chatting in the app.
OWNER = "owner@example.com"

#: The longest any single wait may take before the test fails.
WAIT = 30.0

#: A stopped job must give its runner back within this long of the stop, while its
#: graph thread is still blocked (Task 6's budget, with STOP_POLL_SECONDS at 0.05).
RUNNER_RELEASE_BUDGET = 3.0

#: What generate_session_title returns (the title thread of a first message).
GENERATED_TITLE = "MK-GENERATED-TITLE"

EARLIER_MESSAGE = "MK-EARLIER build me a four-slide deck"
STOPPED_MESSAGE = "MK-STOPPED this is the message the user regrets"


# ---------------------------------------------------------------------------
# The deterministic model outputs
# ---------------------------------------------------------------------------


def _slide(tag: str) -> Dict[str, Any]:
    return {
        "purpose": f"MK-{tag}",
        "content_brief": f"brief {tag}",
        "assumes": f"assumes {tag}",
        "hands_off": f"hands-off {tag}",
        "data_references": [],
    }


def _spec(tags: Sequence[str], *, title: str) -> DeckSpec:
    """An unpinned spec whose slide ``i`` has purpose ``MK-<tags[i]>``."""
    return DeckSpec(
        title=title,
        audience="Stub audience",
        purpose="Stub purpose",
        argument="Stub argument",
        call_to_action="Stub CTA",
        narrative_arc=["open", "middle", "close"],
        design_contract={"design_system_id": None, "template_id": None, "slide_style_id": None},
        resolved_data={"synthesis": "Stub synthesis", "figures": [], "gaps": []},
        slides=[{"position": p, **_slide(tag)} for p, tag in enumerate(tags)],
    )


def _content(tag: str) -> SlideContent:
    return SlideContent(**_slide(tag))


def built_html(tag: str) -> str:
    """What the fake builder writes for the slide whose purpose is ``MK-<tag>``."""
    return f"<div class='slide'><h1>MK-{tag}</h1><p>built {tag}</p></div>"


def built_scripts(tag: str) -> str:
    return f"window.mkBuilt = 'MK-{tag}';"


def _tag_of(payload: dict) -> str:
    return payload["slide_spec"]["purpose"].removeprefix("MK-")


#: The four slides an earlier, completed turn built: the "edit" starting point.
EARLIER_TAGS = ("A", "B", "C", "D")
EARLIER_SPEC = _spec(EARLIER_TAGS, title="MK-EARLIER-SPEC")

#: The edit that moves, deletes and rewrites (and inserts): on [A, B, C, D],
#: rewrite A as A2 and B as B2, delete C, move D after A, insert NEW after B.
#: Composed deck: [A2, D, B2, NEW]; built: A2 (0), B2 (2), NEW (3); D only moves.
EDIT_OPERATIONS = [
    SlideOperation(op="update", position=0, slides=[_content("A2")]),
    SlideOperation(op="update", position=1, slides=[_content("B2")]),
    SlideOperation(op="delete", position=2),
    SlideOperation(op="move", position=3, after_position=0),
    SlideOperation(op="insert", after_position=1, slides=[_content("NEW")]),
]
EDIT_REPLY = "MK-EDIT-REPLY Reworking the deck."
EDITED_HTMLS = [built_html("A2"), built_html("D"), built_html("B2"), built_html("NEW")]


def edit_answer() -> ArchitectOutput:
    return ArchitectOutput(intent="edit", message=EDIT_REPLY, operations=EDIT_OPERATIONS)


def _forbidden_403() -> PinnedInvocationEndpointError:
    """What the runtime raises when the model endpoint answers 403: the provider's
    ``PermissionDeniedError``, collapsed into ``ModelProviderUnavailableError`` and
    then ``PinnedInvocationEndpointError`` (``agent_runtime._run_resolved``)."""
    request = httpx.Request("POST", "https://example.invalid/serving-endpoints/mk/invocations")
    response = httpx.Response(403, request=request, json={"error_code": "PERMISSION_DENIED"})
    provider = openai.PermissionDeniedError(
        "Error code: 403 - PERMISSION_DENIED", response=response, body=None
    )
    try:
        try:
            raise provider
        except openai.PermissionDeniedError as exc:
            raise ModelProviderUnavailableError("the model endpoint refused the call") from exc
    except ModelProviderUnavailableError as exc:
        try:
            raise PinnedInvocationEndpointError(
                endpoint_name="mk-builder-endpoint",
                graph_release_id=1,
                agent_definition_revision_id=1,
            ) from exc
        except PinnedInvocationEndpointError as pinned:
            return pinned


# ---------------------------------------------------------------------------
# Synchronisation: gates, and observers of the real functions
# ---------------------------------------------------------------------------


class Gate:
    """Holds a model call inside the graph until the test releases it."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.release = threading.Event()
        self.passed = threading.Event()
        self._held = 0
        self._cond = threading.Condition()

    def hold(self) -> None:
        with self._cond:
            self._held += 1
            self._cond.notify_all()
        assert self.release.wait(WAIT), f"the test never released the {self.name} gate"
        self.passed.set()

    def wait_entered(self, count: int = 1) -> None:
        """Until *count* calls are held here."""
        with self._cond:
            reached = self._cond.wait_for(lambda: self._held >= count, WAIT)
        assert reached, f"the graph never reached the {self.name} gate {count} time(s)"


class Models:
    """The fake skills, wired into ``graph_env_threadsafe``'s ``SkillStub``.

    ``architect`` answers the architect (a value, or a callable of the payload).
    ``on_build[tag]`` runs inside the builder for the slide ``MK-<tag>`` before it
    answers: it may hold on a gate or raise.  Every builder answers
    ``built_html(tag)`` / ``built_scripts(tag)``.
    """

    def __init__(self, skills) -> None:
        self.skills = skills
        self.architect: Any = None
        self.on_build: Dict[str, Callable[[], None]] = {}
        self.builder_returned: List[str] = []
        self._lock = threading.Lock()
        skills.set("architect", self._architect)
        skills.set("builder", self._builder)
        skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
        skills.set("deck_reviewer", DeckReviewOutput(findings=[]))

    def _architect(self, payload: dict) -> ArchitectOutput:
        answer = self.architect
        return answer(payload) if callable(answer) else answer

    def _builder(self, payload: dict) -> BuilderOutput:
        tag = _tag_of(payload)
        hook = self.on_build.get(tag)
        if hook is not None:
            hook()
        with self._lock:
            self.builder_returned.append(tag)
        return BuilderOutput(
            position=payload["position"], html=built_html(tag), scripts=built_scripts(tag)
        )

    def architect_payloads(self) -> List[dict]:
        return [c["payload"] for c in self.skills.calls_for("architect")]


class SlideWrites:
    """Every ``SlideWriter.write_slide`` call: its html and how it ended."""

    def __init__(self, monkeypatch) -> None:
        self.entries: List[tuple] = []
        self._cond = threading.Condition()
        real = SlideWriter.write_slide

        def write_slide(writer, session_id, position, html, *args, **kwargs):
            reviewed = (
                kwargs.get("verification_record") if "verification_record" in kwargs
                else (args[1] if len(args) > 1 else None)
            ) is not None
            try:
                real(writer, session_id, position, html, *args, **kwargs)
            except BaseException as exc:
                self._add((html, reviewed, type(exc).__name__))
                raise
            self._add((html, reviewed, "committed"))

        monkeypatch.setattr(SlideWriter, "write_slide", write_slide)

    def _add(self, entry: tuple) -> None:
        with self._cond:
            self.entries.append(entry)
            self._cond.notify_all()

    def wait_for(self, predicate: Callable[[List[tuple]], bool]) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: predicate(self.entries), WAIT)

    def reviewed_and_committed(self, html: str) -> bool:
        return (html, True, "committed") in self.entries


class Progress:
    """Every turn-progress write (``record_chat_request_progress``) that returned.

    A slide pipeline's last write is its ``done`` progress, made AFTER its reviewed
    row commits; a test that reads the turn's end state must wait for it, or that
    write can land between the read and the rollback (it updates the request row).
    """

    def __init__(self, monkeypatch) -> None:
        self.returned: List[tuple] = []
        self._cond = threading.Condition()
        real = SessionManager.record_chat_request_progress

        def record_chat_request_progress(manager, request_id, seq, progress):
            try:
                return real(manager, request_id, seq, progress)
            finally:
                with self._cond:
                    self.returned.append((request_id, progress))
                    self._cond.notify_all()

        monkeypatch.setattr(
            SessionManager, "record_chat_request_progress", record_chat_request_progress
        )

    def wait_done(self, rid: str, positions: Sequence[int]) -> bool:
        def reported() -> bool:
            return any(
                r == rid and set(positions) <= set(p["slides"].get("done") or ())
                for r, p in self.returned
            )

        with self._cond:
            return self._cond.wait_for(reported, WAIT)


class Titles:
    """Every ``rename_session`` the title thread makes, and how it ended."""

    def __init__(self, monkeypatch) -> None:
        self.ended: Dict[str, str] = {}
        self.done = threading.Event()
        real = SessionManager.rename_session

        def rename_session(manager, session_id, title, *args, **kwargs):
            rid = kwargs.get("request_id")
            try:
                out = real(manager, session_id, title, *args, **kwargs)
            except BaseException as exc:
                if rid is not None:
                    self.ended[rid] = type(exc).__name__
                    self.done.set()
                raise
            if rid is not None:
                self.ended[rid] = "committed"
                self.done.set()
            return out

        monkeypatch.setattr(SessionManager, "rename_session", rename_session)


class Turns:
    """When each turn's job (``process_chat_request``) and graph thread
    (``invoke_graph``) ended, and what they raised."""

    def __init__(self) -> None:
        self._events: Dict[tuple, threading.Event] = {}
        self._lock = threading.Lock()
        self.job_raised: Dict[str, Optional[BaseException]] = {}
        self.graph_raised: Dict[str, Optional[BaseException]] = {}
        self.graph_thread: Dict[str, threading.Thread] = {}

    def event(self, kind: str, rid: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault((kind, rid), threading.Event())

    def wait_job(self, rid: str, timeout: float = WAIT) -> bool:
        return self.event("job", rid).wait(timeout)

    def wait_graph(self, rid: str, timeout: float = WAIT) -> bool:
        return self.event("graph", rid).wait(timeout)

    def graph_alive(self, rid: str) -> bool:
        thread = self.graph_thread.get(rid)
        return thread is not None and thread.is_alive() and not self.event("graph", rid).is_set()


class Rollbacks:
    """Every ``roll_back_generation`` the JOB makes (its failure paths), with the
    whole database just before it ran (the turn's end state)."""

    def __init__(self, monkeypatch, engine) -> None:
        self.calls: List[Dict[str, Any]] = []
        real = generation_rollback.roll_back_generation

        def roll_back_generation(request_id, **kwargs):
            call = {"request_id": request_id, "kwargs": kwargs, "at_turn_end": _tables(engine)}
            self.calls.append(call)
            call["result"] = real(request_id, **kwargs)
            return call["result"]

        monkeypatch.setattr(generation_rollback, "roll_back_generation", roll_back_generation)


class Runners:
    """The real job runners (``job_queue.start_workers``) on their own event loop.

    The route's ``enqueue_job`` is forwarded here, so the real ``enqueue_job`` runs
    on this loop (the queue is bound to it) in the route's own context (the signed-in
    user travels into the job exactly as in the app).
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.tasks: List[asyncio.Task] = []

    def start(self, monkeypatch, count: int) -> None:
        self.thread.start()

        async def make_queue() -> asyncio.Queue:
            return asyncio.Queue()

        queue = asyncio.run_coroutine_threadsafe(make_queue(), self.loop).result(WAIT)
        monkeypatch.setattr(job_queue, "job_queue", queue)
        self.tasks = asyncio.run_coroutine_threadsafe(
            job_queue.start_workers(count), self.loop
        ).result(WAIT)

    async def enqueue(self, request_id: str, payload: dict) -> None:
        future = asyncio.run_coroutine_threadsafe(
            job_queue.enqueue_job(request_id, payload), self.loop
        )
        await asyncio.wrap_future(future)

    def stop(self) -> None:
        if self.tasks:
            asyncio.run_coroutine_threadsafe(
                job_queue.stop_workers(self.tasks), self.loop
            ).result(WAIT)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(WAIT)


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


class StopEnv:
    def __init__(self, env, client: TestClient, rb: RollbackEnv, models: Models,
                 turns: Turns, writes: SlideWrites, progress: Progress, titles: Titles,
                 rollbacks: Rollbacks, runners: Runners) -> None:
        self.env = env
        self.client = client
        self.rb = rb
        self.models = models
        self.turns = turns
        self.writes = writes
        self.progress = progress
        self.titles = titles
        self.rollbacks = rollbacks
        self.runners = runners
        self.session_id = env.session_id
        self.gates: List[Gate] = []

    def gate(self, name: str) -> Gate:
        """A gate the fixture releases at teardown if the test did not."""
        g = Gate(name)
        self.gates.append(g)
        return g

    def wait_landed(self, rid: str, landed: Dict[str, int]) -> None:
        """Wait until each ``{tag: position}`` slide's pipeline is wholly done: its
        reviewed row committed, then its ``done`` progress written."""
        assert self.writes.wait_for(
            lambda _entries: all(
                self.writes.reviewed_and_committed(built_html(tag)) for tag in landed
            )
        ), f"{sorted(landed)} never landed; the turn is not mid-build"
        assert self.progress.wait_done(rid, list(landed.values())), (
            f"{sorted(landed)} landed but their pipelines never reported done"
        )

    # -- routes ----------------------------------------------------------------

    def submit_raw(self, message: str, session_id: Optional[str] = None) -> httpx.Response:
        return self.client.post(
            "/api/chat/async",
            json={"session_id": session_id or self.session_id, "message": message},
        )

    def submit(self, message: str, session_id: Optional[str] = None) -> str:
        resp = self.submit_raw(message, session_id)
        assert resp.status_code == 200, (resp.status_code, resp.text)
        return resp.json()["request_id"]

    def cancel(self, rid: str) -> httpx.Response:
        return self.client.post(f"/api/chat/cancel/{rid}")

    def poll(self, rid: str) -> Dict[str, Any]:
        resp = self.client.get(f"/api/chat/poll/{rid}")
        assert resp.status_code == 200, (resp.status_code, resp.text)
        body = resp.json()
        body.pop("revision_mark")
        return body

    # -- turns -----------------------------------------------------------------

    def complete_turn(self, message: str, architect: Any, session_id: Optional[str] = None) -> str:
        """One whole turn that completes; returns its request id."""
        self.models.architect = architect
        rid = self.submit(message, session_id)
        assert self.turns.wait_job(rid), "the turn never finished"
        assert self.turns.wait_graph(rid), "the turn's graph thread never ended"
        row = self.rb.request_row(rid)
        assert (row["status"], row["error_message"]) == ("completed", None), row
        return rid

    def seed_earlier_deck(self, session_id: Optional[str] = None) -> str:
        """An earlier, completed first generation: the four-slide deck A, B, C, D."""
        rid = self.complete_turn(
            EARLIER_MESSAGE,
            architect_build(EARLIER_SPEC, message="MK-EARLIER-REPLY Building your deck."),
            session_id,
        )
        sid = session_id or self.session_id
        assert self.rb.slide_htmls(sid) == [built_html(t) for t in EARLIER_TAGS]
        return rid

    def new_session(self) -> str:
        session_id = f"stop-{uuid.uuid4().hex[:10]}"
        db = self.env.factory()
        try:
            db.add(
                UserSession(
                    session_id=session_id,
                    created_by=OWNER,
                    graph_release_id=self.rb.release_id,
                )
            )
            db.commit()
        finally:
            db.close()
        return session_id

    # -- reads -----------------------------------------------------------------

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.rb.tables()

    def stop_and_free_runner(self, rid: str) -> httpx.Response:
        """POST the stop; the job must give its runner back while the graph thread
        is still held inside the turn."""
        resp = self.cancel(rid)
        stopped_at = time.monotonic()
        assert resp.status_code == 200, (resp.status_code, resp.text)
        assert resp.json() == {"outcome": "cancelled", "status": "cancelled"}
        self.assert_runner_freed(rid, stopped_at)
        return resp

    def assert_runner_freed(self, rid: str, ended_at: float) -> None:
        """The job ended within the budget of *ended_at*, quietly, while its graph
        thread is still held inside the turn."""
        assert self.turns.wait_job(rid, RUNNER_RELEASE_BUDGET), (
            f"the ended job did not free its runner within {RUNNER_RELEASE_BUDGET} s"
        )
        assert time.monotonic() - ended_at < RUNNER_RELEASE_BUDGET
        assert self.turns.job_raised[rid] is None, self.turns.job_raised[rid]
        assert self.turns.graph_alive(rid), (
            "the graph thread was not still held when the runner came back; "
            "the test proved nothing about the runner"
        )


@pytest.fixture
def stop_env(graph_env_threadsafe, monkeypatch) -> Iterator[StopEnv]:
    env = graph_env_threadsafe
    factory = env.factory

    # Every get_db_session (writers, fence, rollback, routes' get_db) and the
    # checkpointer onto the fixture's file-backed database.
    monkeypatch.setattr("src.core.database.get_session_local", lambda: factory)
    monkeypatch.setattr("src.services.graph.builder.get_session_local", lambda: factory)
    monkeypatch.setattr(checkpointer_module, "get_session_local", lambda: factory)
    monkeypatch.setattr(checkpointer_module, "_checkpointer", None)
    monkeypatch.setattr(chat_service_module, "_chat_service_instance", None)
    # The compiled graph over the one saver the rollback reads and prunes.
    graph = graph_builder.build_graph(checkpointer=get_checkpointer())
    monkeypatch.setattr(graph_builder, "get_graph", lambda: graph)

    monkeypatch.setattr("src.api.middleware.request_logging._enqueue_log", lambda entry: None)
    monkeypatch.setattr("src.api.services.usage_events._submit", lambda *a, **k: None)
    monkeypatch.setattr("src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None))
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title",
        lambda message, model: GENERATED_TITLE,
    )
    monkeypatch.setattr("src.api.services.session_naming.build_session_title_model", MagicMock())
    monkeypatch.setattr(job_queue, "STOP_POLL_SECONDS", 0.05)

    turns = Turns()
    real_invoke = graph_builder.invoke_graph

    def invoke_graph(session_id, initial=None, *, request_id=None, **kwargs):
        turns.graph_thread[request_id] = threading.current_thread()
        try:
            out = real_invoke(session_id, initial, request_id=request_id, **kwargs)
        except BaseException as exc:
            turns.graph_raised[request_id] = exc
            raise
        else:
            turns.graph_raised[request_id] = None
            return out
        finally:
            turns.event("graph", request_id).set()

    monkeypatch.setattr(graph_builder, "invoke_graph", invoke_graph)

    real_process = job_queue.process_chat_request

    async def process_chat_request(request_id, payload):
        try:
            await real_process(request_id, payload)
        except BaseException as exc:
            turns.job_raised[request_id] = exc
            raise
        else:
            turns.job_raised[request_id] = None
        finally:
            turns.event("job", request_id).set()

    monkeypatch.setattr(job_queue, "process_chat_request", process_chat_request)

    with factory() as db:
        release_id = db.query(UserSession.graph_release_id).filter(
            UserSession.session_id == env.session_id
        ).scalar()
    rb = RollbackEnv(env.engine, factory, release_id, 1)
    models = Models(env.skills)
    writes = SlideWrites(monkeypatch)
    progress = Progress(monkeypatch)
    titles = Titles(monkeypatch)
    rollbacks = Rollbacks(monkeypatch, env.engine)

    runners = Runners()
    job_queue.jobs.clear()
    job_queue.shutdown_chat_executor()
    assert job_queue.chat_job_concurrency() == 1, "the default is one runner per process"
    runners.start(monkeypatch, job_queue.chat_job_concurrency())
    monkeypatch.setattr("src.api.routes.chat.enqueue_job", runners.enqueue)

    monkeypatch.setenv("DEV_USER_ID", OWNER)
    stop = None
    try:
        with TestClient(app) as client:
            stop = StopEnv(
                env, client, rb, models, turns, writes, progress, titles, rollbacks, runners
            )
            yield stop
    finally:
        # Let every held graph thread go, so none outlives the database.
        for held in stop.gates if stop is not None else []:
            held.release.set()
        for thread in list(turns.graph_thread.values()):
            thread.join(WAIT)
        runners.stop()
        job_queue.shutdown_chat_executor()
        job_queue.jobs.clear()


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


def _session(tables, session_id: str) -> Dict[str, Any]:
    return _one(tables["user_sessions"], session_id=session_id)


def _thread_checkpoints(tables, session_id: str) -> List[Dict[str, Any]]:
    return [c for c in tables["graph_checkpoints"] if c["thread_id"] == session_id]


def _assert_cancelled_poll(stop: StopEnv, rid: str, *, slides: Optional[list] = None) -> None:
    body = stop.poll(rid)
    expected = {
        "status": "cancelled",
        "events": [],
        "last_message_id": 0,
        "result": None,
        "error": None,
        "slide_cursor": body["slide_cursor"],
        "slides": body["slides"],
        "slide_revisions": body["slide_revisions"],
        "turn_progress": None,
        "rollback": "rolled_back",
    }
    assert body == expected
    if slides is not None:
        assert [s["html"] for s in body["slides"]] == slides


# ===========================================================================
# 1. Stop during planning, on a first generation
# ===========================================================================


def test_stop_during_planning_first_generation_restores_empty(stop_env):
    """The architect is still thinking (its model call has not returned) on the
    session's first message.  The stop leaves an empty deck, an empty chat, the
    title and the deck mode as before; the held graph thread's later writes are all
    refused; and sending again is a fresh first generation that knows nothing of
    the stopped message."""
    stop = stop_env
    sid = stop.session_id
    planning = stop.gate("architect")

    def think_then_build(payload):
        planning.hold()
        return architect_build(_spec(("X0", "X1", "X2"), title="MK-STOPPED-SPEC"))

    stop.models.architect = think_then_build
    before = stop.tables()
    assert _session(before, sid)["deck_mode"] is None
    title_before = _session(before, sid)["title"]
    assert title_before != GENERATED_TITLE

    rid = stop.submit(STOPPED_MESSAGE)
    planning.wait_entered()
    # The title thread ran in parallel and renamed the session: the restore must
    # put the old title back, not merely outrun it.
    assert stop.titles.done.wait(WAIT), "the title thread never renamed the session"
    at_turn_end = stop.tables()
    assert stop.titles.ended[rid] == "committed"
    assert _session(at_turn_end, sid)["title"] == GENERATED_TITLE
    assert _session(at_turn_end, sid)["deck_mode"] == "agent"
    assert [m["content"] for m in _messages_tagged(at_turn_end, rid)] == [STOPPED_MESSAGE]
    assert _thread_checkpoints(at_turn_end, sid), "the turn wrote no checkpoint; nothing to prune"
    assert at_turn_end["session_slides"] == [] and at_turn_end["session_slide_decks"] == []

    stop.stop_and_free_runner(rid)

    after = stop.tables()
    _assert_rolled_back_to_enter(
        stop.rb, before, at_turn_end, after,
        rid=rid, actor_sid=sid, owner_sid=sid,
        terminal_status="cancelled", error_message=None, deck_existed=False,
    )
    assert _session(after, sid)["title"] == title_before
    assert _session(after, sid)["deck_mode"] is None
    _assert_lock(stop.rb, sid, held_by=None)
    _assert_cancelled_poll(stop, rid, slides=[])

    # The architect answers now: its build (the deck-level write, the reply, the
    # builders) is refused at the first write, and the graph thread ends without
    # dispatching a single builder.
    calls_at_stop = len(stop.env.skills.calls)
    planning.release.set()
    assert stop.turns.wait_graph(rid), "the abandoned graph thread never ended"
    _assert_tables_equal(after, stop.tables())
    assert stop.env.skills.calls[calls_at_stop:] == [], "the abandoned architect built"
    assert isinstance(stop.turns.graph_raised[rid], TurnFencedError), (
        f"the abandoned graph did not end on a refused write: {stop.turns.graph_raised[rid]!r}"
    )

    # Sending again: a fresh first generation (the title thread runs again) whose
    # architect sees only the new message and no deck.
    again = "MK-AGAIN a different deck, please"
    rid2 = stop.complete_turn(
        again, architect_build(_spec(("Y0", "Y1"), title="MK-AGAIN-SPEC"))
    )
    assert stop.rb.slide_htmls(sid) == [built_html("Y0"), built_html("Y1")]
    # The title thread runs only on a first message, and it ran (the deck-level
    # writer may also set the session title to the deck's, so the title itself is
    # whichever landed last).
    assert stop.titles.ended[rid2] == "committed"
    assert _session(stop.tables(), sid)["title"] in (GENERATED_TITLE, "MK-AGAIN-SPEC")
    payload = stop.models.architect_payloads()[-1]
    assert payload["conversation"] == [{"role": "user", "content": again}]
    assert payload["current_deck_spec"] is None
    assert payload["committed_slide_count"] == 0
    assert "MK-STOPPED" not in json.dumps(payload, default=str)


# ===========================================================================
# 2. Stop after the architect committed the layout, before any builder wrote
# ===========================================================================


def test_stop_after_layout_commit_before_builders_restores(stop_env):
    """Review Focus 4.  The edit's layout is committed (D moved, C deleted, NEW's
    pending placeholder inserted, the composed Spec written, the reply said) and
    every builder is held in its model call: the progress still says nothing was
    built.  The stop is still a full restore."""
    stop = stop_env
    sid = stop.session_id
    stop.seed_earlier_deck()
    builders = stop.gate("builders")
    for tag in ("A2", "B2", "NEW"):
        stop.models.on_build[tag] = builders.hold
    stop.models.architect = edit_answer()
    before = stop.tables()

    rid = stop.submit(STOPPED_MESSAGE)
    builders.wait_entered(3)
    at_turn_end = stop.tables()
    htmls = stop.rb.slide_htmls(sid)
    assert htmls[:3] == [built_html("A"), built_html("D"), built_html("B")], (
        "the layout was not committed before the builders ran; the test proves nothing"
    )
    assert PENDING_SLIDE_TEXT in htmls[3], "NEW's pending placeholder was not inserted"
    spec = DeckSpec.from_json(stop.rb.deck_row(sid)["deck_spec_json"])
    assert [s.purpose for s in spec.slides] == ["MK-A2", "MK-D", "MK-B2", "MK-NEW"]
    assert EDIT_REPLY in [m["content"] for m in _messages_tagged(at_turn_end, rid)]
    rebuilt = {built_html("A2"), built_html("B2"), built_html("NEW")}
    assert not any(e[0] in rebuilt for e in stop.writes.entries), "a builder wrote"

    stop.stop_and_free_runner(rid)

    after = stop.tables()
    _assert_rolled_back_to_enter(
        stop.rb, before, at_turn_end, after,
        rid=rid, actor_sid=sid, owner_sid=sid,
        terminal_status="cancelled", error_message=None, deck_existed=True,
    )
    assert stop.rb.slide_htmls(sid) == [built_html(t) for t in EARLIER_TAGS]
    _assert_lock(stop.rb, sid, held_by=None)
    _assert_cancelled_poll(stop, rid)

    builders.release.set()
    assert stop.turns.wait_graph(rid), "the abandoned graph thread never ended"
    _assert_tables_equal(after, stop.tables())


# ===========================================================================
# 3. Stop mid-build on an edit that moved, deleted and rewrote slides
# ===========================================================================


def test_stop_mid_build_on_edit_restores_exactly(stop_env):
    """A2 and NEW are built, reviewed and committed; B2's builder is still in its
    model call.  After the stop, the deck, Spec, styles, slide rows, messages and
    checkpoints are exactly as before Enter, and the next turn's architect sees no
    trace of the stopped request: its conversation is the earlier one plus the new
    message, and its deck is the earlier deck."""
    stop = stop_env
    sid = stop.session_id
    stop.seed_earlier_deck()
    b2 = stop.gate("builder B2")
    stop.models.on_build["B2"] = b2.hold
    stop.models.architect = edit_answer()
    before = stop.tables()
    conversation_before = _conversation(sid)
    spec_before = stop.rb.deck_row(sid)["deck_spec_json"]

    rid = stop.submit(STOPPED_MESSAGE)
    b2.wait_entered()
    stop.wait_landed(rid, {"A2": 0, "NEW": 3})
    at_turn_end = stop.tables()
    htmls = stop.rb.slide_htmls(sid)
    assert htmls[0] == built_html("A2") and htmls[1] == built_html("D")
    assert htmls[2] == built_html("B"), "B2 must still be in flight"
    assert htmls[3] == built_html("NEW")

    stop.stop_and_free_runner(rid)

    after = stop.tables()
    _assert_rolled_back_to_enter(
        stop.rb, before, at_turn_end, after,
        rid=rid, actor_sid=sid, owner_sid=sid,
        terminal_status="cancelled", error_message=None, deck_existed=True,
    )
    assert stop.rb.slide_htmls(sid) == [built_html(t) for t in EARLIER_TAGS]
    assert stop.rb.deck_row(sid)["deck_spec_json"] == spec_before
    _assert_cancelled_poll(stop, rid)

    b2.release.set()
    assert stop.turns.wait_graph(rid), "the abandoned graph thread never ended"
    _assert_tables_equal(after, stop.tables())

    # The next turn: the architect discusses, and what it is handed is the deck and
    # the conversation as they were before the stopped Enter.
    nxt = "MK-NEXT what does slide 2 say?"
    stop.complete_turn(nxt, ArchitectOutput(intent="discuss", message="MK-NEXT-REPLY"))
    payload = stop.models.architect_payloads()[-1]
    assert payload["message"] == nxt
    assert payload["conversation"] == [
        *conversation_before,
        {"role": "user", "content": nxt},
    ]
    assert payload["current_deck_spec"] == json.loads(spec_before)
    assert payload["committed_slide_count"] == len(EARLIER_TAGS)
    trace = json.dumps(payload, default=str)
    for marker in ("MK-STOPPED", "MK-EDIT-REPLY", "MK-A2", "MK-B2", "MK-NEW"):
        assert marker not in trace, f"the next turn's architect still sees {marker}"
    # That turn's save point is taken from this process's deck cache: it must hold
    # the restored deck, not the stopped turn's.
    pk = stop.rb.pk(sid)
    newest = [v for v in stop.tables()["slide_deck_versions"] if v["session_id"] == pk][-1]
    saved = json.loads(newest["deck_json"])
    assert [s["html"] for s in saved["slides"]] == [built_html(t) for t in EARLIER_TAGS]
    assert newest["deck_spec_json"] == spec_before
    assert "MK-STOPPED" not in (newest["chat_history_json"] or "")


# ===========================================================================
# 4. A builder (and the title) that answer after the stop change nothing
# ===========================================================================


@pytest.mark.parametrize("kind", ["first_generation", "edit"])
def test_late_builder_write_after_stop_changes_nothing(stop_env, monkeypatch, caplog, kind):
    """Two slides landed; the third slide's builder (and, on a first message, the
    title model) is still in its call when the stop lands.  Each answers afterwards.

    * On a first generation the late slide's position is empty, so its pipeline
      writes a draft first; on the edit, B2's position holds a real slide again
      once the deck is restored (C, at index 2), so no draft is written.
    * Either way: not one row of any table changes, no write commits, the late
      title's rename is refused, and the abandoned graph thread ends quietly
      (Task 6: an INFO "Abandoned graph turn ended", no ERROR) WITHOUT starting
      another model call -- the spec's "it must exit without side effects", and
      C8's reason for fencing the draft write: "a further build-reviewer model
      call follows"."""
    stop = stop_env
    sid = stop.session_id
    if kind == "edit":
        stop.seed_earlier_deck()
        late, landed = "B2", {"A2": 0, "NEW": 3}
        stop.models.architect = edit_answer()
    else:
        late, landed = "X1", {"X0": 0, "X2": 2}
        stop.models.architect = architect_build(
            _spec(("X0", "X1", "X2"), title="MK-STOPPED-SPEC")
        )
    held = stop.gate(f"builder {late}")
    stop.models.on_build[late] = held.hold
    title = stop.gate("title model") if kind == "first_generation" else None

    def slow_title(message, model):
        title.hold()
        return GENERATED_TITLE

    monkeypatch.setattr("src.api.services.chat_service.generate_session_title", slow_title)
    before = stop.tables()

    rid = stop.submit(STOPPED_MESSAGE)
    held.wait_entered()
    if title is not None:
        title.wait_entered()
    stop.wait_landed(rid, landed)
    at_turn_end = stop.tables()
    by_position = {
        r["position"]: r["html"]
        for r in at_turn_end["session_slides"]
        if r["session_id"] == stop.rb.pk(sid)
    }
    assert all(by_position.get(p) == built_html(tag) for tag, p in landed.items()), by_position

    stop.stop_and_free_runner(rid)
    after = stop.tables()
    _assert_rolled_back_to_enter(
        stop.rb, before, at_turn_end, after,
        rid=rid, actor_sid=sid, owner_sid=sid,
        terminal_status="cancelled", error_message=None, deck_existed=kind == "edit",
    )

    calls_at_stop = len(stop.env.skills.calls)
    writes_at_stop = len(stop.writes.entries)
    caplog.clear()
    caplog.set_level(logging.INFO)
    held.release.set()
    if title is not None:
        title.release.set()
    assert stop.turns.wait_graph(rid), "the abandoned graph thread never ended"
    if title is not None:
        assert stop.titles.done.wait(WAIT), "the late title never reached rename_session"
        assert stop.titles.ended[rid] == "TurnFencedError"
    assert late in stop.models.builder_returned, f"{late}'s builder never answered"

    # Nothing of the abandoned turn reached the database.
    late_writes = stop.writes.entries[writes_at_stop:]
    assert not any(outcome == "committed" for _, _, outcome in late_writes), late_writes
    _assert_tables_equal(after, stop.tables())
    _assert_cancelled_poll(stop, rid, slides=None if kind == "edit" else [])

    # And it ended quietly, without another (paid) model call.
    calls_after_stop = [
        (c["name"], c["payload"].get("position")) for c in stop.env.skills.calls[calls_at_stop:]
    ]
    errors = [
        f"{r.name}: {r.getMessage()}" for r in caplog.records if r.levelno >= logging.ERROR
    ]
    assert calls_after_stop == [], (
        f"the abandoned turn called the model again after the stop: {calls_after_stop}; "
        f"its late writes: {late_writes}; ERROR logs: {errors}"
    )
    assert errors == [], f"the abandoned turn logged ERRORs after the stop: {errors}"
    assert any(
        r.getMessage() == "Abandoned graph turn ended" for r in caplog.records
    ), "the abandoned graph thread did not end on the quiet (INFO) path"


# ===========================================================================
# 5. Sending straight after a stop starts at once
# ===========================================================================


def test_resend_after_stop_starts_immediately(stop_env):
    """One runner per process.  The first turn's graph thread is held in X1's
    builder.  The sender stops and sends again at once: the second turn is accepted
    and reaches ``running`` (its architect is called) while the first graph thread
    is STILL held, so it was not queued behind the abandoned turn.  When the first
    thread finally answers, nothing of it lands on the second turn's deck."""
    stop = stop_env
    sid = stop.session_id
    x1 = stop.gate("builder X1")
    stop.models.on_build["X1"] = x1.hold
    stop.models.architect = architect_build(_spec(("X0", "X1", "X2"), title="MK-STOPPED-SPEC"))

    rid1 = stop.submit(STOPPED_MESSAGE)
    x1.wait_entered()
    stop.stop_and_free_runner(rid1)

    second_running = threading.Event()
    seen: List[tuple] = []

    def second_architect(payload):
        # Every request other than the stopped one, as the second turn's graph sees
        # them (the job may start before the route's answer reaches the test).
        seen.extend(
            (r["request_id"], r["status"])
            for r in stop.tables()["chat_requests"]
            if r["request_id"] != rid1
        )
        second_running.set()
        return architect_build(_spec(("Y0", "Y1"), title="MK-SECOND-SPEC"))

    stop.models.architect = second_architect
    sent_at = time.monotonic()
    rid2 = stop.submit("MK-SECOND try again")
    assert second_running.wait(RUNNER_RELEASE_BUDGET), (
        "the second turn did not start while the first graph thread was held: it "
        "waited behind the abandoned turn"
    )
    assert time.monotonic() - sent_at < RUNNER_RELEASE_BUDGET
    assert seen == [(rid2, "running")]
    assert stop.turns.graph_alive(rid1), "the first graph thread was not still held"
    assert not x1.passed.is_set()

    assert stop.turns.wait_job(rid2), "the second turn never finished"
    assert stop.rb.request_row(rid2)["status"] == "completed"
    assert stop.rb.slide_htmls(sid) == [built_html("Y0"), built_html("Y1")]
    _assert_lock(stop.rb, sid, held_by=None)
    finished = stop.tables()

    x1.release.set()
    assert stop.turns.wait_graph(rid1), "the abandoned graph thread never ended"
    _assert_tables_equal(finished, stop.tables())
    assert stop.rb.request_row(rid1)["status"] == "cancelled"


# ===========================================================================
# 6. A forced failure mid-build rolls back exactly like a stop
# ===========================================================================


def test_forced_failure_mid_build_rolls_back(stop_env):
    """The same edit; A2 and NEW are committed, then B2's model endpoint answers
    403.  The turn fails, and the deck, Spec, styles, rows, messages and checkpoints
    go back to Enter exactly as a stop would put them; the request ends ``error``
    with ``rollback_outcome='rolled_back'``."""
    stop = stop_env
    sid = stop.session_id
    stop.seed_earlier_deck()

    def forbidden_after_the_others_landed():
        # Inside the turn (a fanned builder): the request id is the turn's own.
        stop.wait_landed(get_chat_request_id(), {"A2": 0, "NEW": 3})
        raise _forbidden_403()

    stop.models.on_build["B2"] = forbidden_after_the_others_landed
    stop.models.architect = edit_answer()
    before = stop.tables()

    rid = stop.submit(STOPPED_MESSAGE)
    assert stop.turns.wait_job(rid), "the failed turn never finished"
    assert stop.turns.wait_graph(rid)

    assert [c["request_id"] for c in stop.rollbacks.calls] == [rid], (
        "the job did not roll the failed turn back (exactly once)"
    )
    call = stop.rollbacks.calls[0]
    assert call["kwargs"] == {
        "terminal_status": "error",
        "error_message": PINNED_GRAPH_CONFIGURATION_ERROR,
        "refuse_on_foreign_change": False,
    }
    assert call["result"] is generation_rollback.RollbackResult.ROLLED_BACK
    at_turn_end = call["at_turn_end"]
    assert [
        r["html"] for r in sorted(
            (r for r in at_turn_end["session_slides"] if r["session_id"] == stop.rb.pk(sid)),
            key=lambda r: r["position"],
        )
    ][:2] == [built_html("A2"), built_html("D")], "the failure was not mid-build"

    after = stop.tables()
    _assert_rolled_back_to_enter(
        stop.rb, before, at_turn_end, after,
        rid=rid, actor_sid=sid, owner_sid=sid,
        terminal_status="error", error_message=PINNED_GRAPH_CONFIGURATION_ERROR,
        deck_existed=True,
    )
    assert stop.rb.slide_htmls(sid) == [built_html(t) for t in EARLIER_TAGS]
    _assert_lock(stop.rb, sid, held_by=None)
    body = stop.poll(rid)
    assert (body["status"], body["error"], body["rollback"], body["result"]) == (
        "error", PINNED_GRAPH_CONFIGURATION_ERROR, "rolled_back", None
    )
    assert body["turn_progress"] is None


# ===========================================================================
# 7. A placeholder slide is a success, not a failure
# ===========================================================================


def test_placeholder_slide_is_success_not_failure(stop_env):
    """X1's builder fails with an ordinary error: the slide becomes a placeholder
    and the turn reaches the end.  That generation commits as it does today -- the
    request ``completed``, nothing rolled back, the snapshot gone, the lock freed,
    a save point made -- and a stop that arrives afterwards is "already finished"
    and changes nothing."""
    stop = stop_env
    sid = stop.session_id

    def broken():
        raise RuntimeError("MK-INJECTED the builder produced nothing usable")

    stop.models.on_build["X1"] = broken
    rid = stop.complete_turn(
        STOPPED_MESSAGE, architect_build(_spec(("X0", "X1", "X2"), title="MK-PLACEHOLDER-SPEC"))
    )

    assert stop.rollbacks.calls == [], "a turn with a placeholder slide was rolled back"
    row = stop.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "completed", None, None
    )
    tables = stop.tables()
    assert tables["generation_snapshots"] == []
    _assert_lock(stop.rb, sid, held_by=None)
    slides = sorted(
        (r for r in tables["session_slides"] if r["session_id"] == stop.rb.pk(sid)),
        key=lambda r: r["position"],
    )
    assert [r["html"] for r in slides][0::2] == [built_html("X0"), built_html("X2")]
    assert is_placeholder_record(json.loads(slides[1]["verification_record"]))
    assert not is_placeholder_record(json.loads(slides[0]["verification_record"]))
    versions = [v for v in tables["slide_deck_versions"] if v["session_id"] == stop.rb.pk(sid)]
    assert [v["description"] for v in versions] == ["Generated 3 slide(s)"]
    assert stop.poll(rid)["status"] == "completed"

    resp = stop.cancel(rid)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"outcome": "already_finished", "status": "completed"}
    _assert_tables_equal(tables, stop.tables())


# ===========================================================================
# 8. Completion and a stop released together: exactly one wins
# ===========================================================================


RACE_ITERATIONS = 20


def _deck_view(tables, session_id: str) -> Dict[str, Any]:
    """Everything a turn changes on one session's deck, with ids and clocks dropped."""
    pk = _session(tables, session_id)["id"]
    deck = [r for r in tables["session_slide_decks"] if r["session_id"] == pk]
    return {
        "deck": {
            c: deck[0][c] for c in generation_rollback.DECK_CONTENT_COLUMNS
        } if deck else None,
        "slides": [
            (r["position"], r["html"], r["scripts"], r["verification_record"],
             r["deck_spec_slide"])
            for r in sorted(
                (r for r in tables["session_slides"] if r["session_id"] == pk),
                key=lambda r: r["position"],
            )
        ],
        "messages": [
            (m["role"], m["message_type"], m["content"])
            for m in tables["session_messages"] if m["session_id"] == pk
        ],
        "versions": [
            v["description"] for v in tables["slide_deck_versions"] if v["session_id"] == pk
        ],
        "checkpoints": len(_thread_checkpoints(tables, session_id)),
        "deck_mode": _session(tables, session_id)["deck_mode"],
        "title": _session(tables, session_id)["title"],
        "lock": (
            _session(tables, session_id)["is_processing"],
            _session(tables, session_id)["processing_request_id"],
        ),
        "snapshots": [
            s for s in tables["generation_snapshots"] if s["owner_session_pk"] == pk
        ],
    }


def test_complete_and_cancel_race_has_one_winner(stop_env, monkeypatch):
    """Review Focus 2, 20 times over.  The edit has built every slide and its graph
    thread has ended.  The job's commit point (``seal_generation``) and the stop
    (``roll_back_generation``, from the stop route) each open their transaction and
    are then released together from one ``threading.Barrier``, right before each
    takes its claim on the request row: whichever claims first wins.  Each run has
    exactly one outcome: either the stop won (``cancelled``, and every table is as at
    Enter) or the completion won (``already_finished``, and the deck is the completed
    deck, identical to a run nobody stopped) -- never a mix."""
    stop = stop_env

    # The control: the same edit on a fresh session, completed with no stop.
    control_sid = stop.new_session()
    stop.seed_earlier_deck(control_sid)
    stop.complete_turn(STOPPED_MESSAGE, edit_answer(), control_sid)
    completed_view = _deck_view(stop.tables(), control_sid)
    assert [s[1] for s in completed_view["slides"]] == EDITED_HTMLS

    race: Dict[str, Any] = {}
    race_lock = threading.Lock()
    real_seal = generation_rollback.seal_generation
    real_claim = generation_rollback.claim_turn_row

    def seal_generation(request_id):
        if request_id == race.get("rid"):
            # Every graph write is done: this is the turn's end state.
            race["at_turn_end"] = _tables(stop.env.engine)
            race["sealed_by"] = threading.current_thread().name
        sealed = real_seal(request_id)
        if request_id == race.get("rid") and race.get("forced"):
            # The forced order: the seal has committed; hold the job here, before
            # it completes, until the stop's claim has returned.
            race["sealed"].set()
            race["held"] = race["stop_claimed"].wait(WAIT)
        return sealed

    def claim_turn_row(db, request_id):
        with race_lock:
            arrive = request_id == race.get("rid") and race["arrivals"] < 2
            if arrive:
                race["arrivals"] += 1
        forced_stop = (
            arrive
            and race.get("forced")
            and threading.current_thread().name != race.get("sealed_by")
        )
        if forced_stop:
            # The forced order: the stop claims only once the seal has returned.
            race["waited_for_seal"] = race["sealed"].wait(WAIT)
        elif arrive and not race.get("forced"):
            race["barrier"].wait()
        claimed = real_claim(db, request_id)
        if arrive:
            side = "seal" if threading.current_thread().name == race.get("sealed_by") else "stop"
            with race_lock:
                race["claims"].append((side, claimed))
        if forced_stop:
            race["stop_claimed"].set()
        return claimed

    # Both are reached through generation_rollback's module globals (the graph
    # limb imports seal_generation lazily; seal_generation and _roll_back both call
    # claim_turn_row), and by nothing else a turn runs.
    monkeypatch.setattr(generation_rollback, "seal_generation", seal_generation)
    monkeypatch.setattr(generation_rollback, "claim_turn_row", claim_turn_row)

    # One FORCED run first: the seal commits, then the job is held right after it
    # until the stop's claim has returned.  The stop so claims a turn that is still
    # running but sealed, which it must leave alone.  The barrier runs below let the
    # seal win this way only by chance; here it is every run, so a seal that left
    # its snapshot active (and let this stop roll a finished turn back) is red every
    # time.
    sid = stop.new_session()
    stop.seed_earlier_deck(sid)
    stop.models.architect = edit_answer()
    race.clear()
    race.update(
        forced=True,
        arrivals=0,
        claims=[],
        sealed=threading.Event(),
        stop_claimed=threading.Event(),
    )
    rid = stop.submit(STOPPED_MESSAGE, sid)
    race["rid"] = rid
    resp = stop.cancel(rid)
    assert stop.turns.wait_job(rid), "the forced job never finished"
    assert stop.turns.wait_graph(rid)
    assert stop.turns.job_raised[rid] is None, stop.turns.job_raised[rid]
    assert race.get("waited_for_seal") is True, "the forced stop never saw the seal return"
    assert race.get("held") is True, "the forced job was not held until the stop had claimed"
    assert sorted(race["claims"]) == [("seal", True), ("stop", True)], race["claims"]
    assert resp.status_code == 200, (resp.status_code, resp.text)
    body = resp.json()
    assert body["outcome"] == "already_finished", (
        f"a stop that claimed a SEALED turn changed it: {body}"
    )
    assert body["status"] in ("running", "completed"), body
    row = stop.rb.request_row(rid)
    assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
        "completed", None, None
    )
    after = stop.tables()
    assert after["generation_snapshots"] == []
    assert _deck_view(after, sid) == completed_view
    assert stop.rb.slide_htmls(sid) == EDITED_HTMLS
    assert stop.rollbacks.calls == [], "the job rolled the forced turn back itself"
    _assert_lock(stop.rb, sid, held_by=None)

    outcomes: List[str] = []
    for _ in range(RACE_ITERATIONS):
        sid = stop.new_session()
        stop.seed_earlier_deck(sid)
        before = stop.tables()
        earlier_view = _deck_view(before, sid)
        stop.models.architect = edit_answer()
        race.clear()
        race.update(barrier=threading.Barrier(2, timeout=WAIT), arrivals=0, claims=[])

        rid = stop.submit(STOPPED_MESSAGE, sid)
        race["rid"] = rid
        # The stop is sent at once; its claim waits at the barrier for the seal's.
        resp = stop.cancel(rid)
        assert stop.turns.wait_job(rid), "the racing job never finished"
        assert stop.turns.wait_graph(rid)
        assert stop.turns.job_raised[rid] is None, stop.turns.job_raised[rid]
        assert race["arrivals"] == 2, "the seal and the stop did not both reach the barrier"
        after = stop.tables()
        view = _deck_view(after, sid)
        row = stop.rb.request_row(rid)

        assert resp.status_code == 200, (resp.status_code, resp.text)
        body = resp.json()
        if body == {"outcome": "cancelled", "status": "cancelled"}:
            outcomes.append("cancelled")
            assert sorted(race["claims"]) == [("seal", False), ("stop", True)], race["claims"]
            # The deck reviewer ran before the seal, so this turn saved one deck
            # review, keyed by the EDITED deck's digest.  The plan's ruling
            # ("deck_reviews stay", Rulings round 1) keeps it: a content-addressed
            # review of content the restored deck no longer has.  Every review that
            # existed at Enter is untouched.
            enter_reviews = before["deck_reviews"]
            assert after["deck_reviews"][: len(enter_reviews)] == enter_reviews
            added = after["deck_reviews"][len(enter_reviews):]
            assert [r["deck_digest"] for r in added] == [compute_deck_digest(EDITED_HTMLS)]
            assert compute_deck_digest(stop.rb.slide_htmls(sid)) != added[0]["deck_digest"]
            _assert_rolled_back_to_enter(
                stop.rb, dict(before, deck_reviews=after["deck_reviews"]),
                race["at_turn_end"], after,
                rid=rid, actor_sid=sid, owner_sid=sid,
                terminal_status="cancelled", error_message=None, deck_existed=True,
            )
            assert view == earlier_view
            assert stop.rb.slide_htmls(sid) == [built_html(t) for t in EARLIER_TAGS]
        else:
            assert body["outcome"] == "already_finished", body
            # The stop claimed between the seal and the completion (the turn still
            # "running", sealed), or found it already "completed"; either way it
            # changed nothing.
            assert body["status"] in ("running", "completed"), body
            outcomes.append("completed")
            claims = dict(race["claims"])
            assert sorted(claims) == ["seal", "stop"] and claims["seal"] is True, race["claims"]
            if not claims["stop"]:
                assert body["status"] == "completed", body
            assert (row["status"], row["error_message"], row["rollback_outcome"]) == (
                "completed", None, None
            )
            assert after["generation_snapshots"] == []
            assert view == completed_view
            assert stop.rb.slide_htmls(sid) == EDITED_HTMLS
        assert stop.rollbacks.calls == [], "the job rolled a raced turn back itself"
        _assert_lock(stop.rb, sid, held_by=None)

    assert len(outcomes) == RACE_ITERATIONS
    print(f"\nrace outcomes: {outcomes.count('cancelled')} cancelled, "
          f"{outcomes.count('completed')} completed")


# ===========================================================================
# 9. (beyond the brief) The other two rollback triggers, on a real turn
# ===========================================================================


#: ``mark_timed_out_jobs_once``'s text for a graph turn (existing copy, exact).
GRAPH_TIMEOUT_TEXT = "Generation exceeded maximum duration (20 minutes)"


@pytest.mark.parametrize("trigger", ["hard_timeout", "restart_recovery"])
def test_timeout_or_recovery_mid_build_rolls_back(stop_env, trigger):
    """The spec's "a hard timeout rolls back" and "a forced restart mid-build is
    rolled back by recovery", on the same mid-build edit as the stop: A2 and NEW
    committed, B2's builder still in its call.

    * ``hard_timeout``: the job's in-memory start is 20 minutes and a second ago,
      and the timeout sweep (``mark_timed_out_jobs_once``) runs on the runners' loop.
    * ``restart_recovery``: the recovery sweep (``recover_orphaned_generations``, run
      at startup and every minute) runs with its clock 181 s ahead, so the sender's
      lock reads as not refreshed for longer than ``ORPHAN_AFTER_SECONDS``: the job
      looks dead, as after a restart.

    Either way the deck goes back to Enter exactly as a stop puts it (``error``,
    ``rolled_back``), the job frees its runner while the graph thread is held, and
    the graph thread's late answer changes nothing."""
    stop = stop_env
    sid = stop.session_id
    stop.seed_earlier_deck()
    b2 = stop.gate("builder B2")
    stop.models.on_build["B2"] = b2.hold
    stop.models.architect = edit_answer()
    before = stop.tables()

    rid = stop.submit(STOPPED_MESSAGE)
    b2.wait_entered()
    stop.wait_landed(rid, {"A2": 0, "NEW": 3})
    at_turn_end = stop.tables()

    if trigger == "hard_timeout":
        job_queue.jobs[rid]["started_at"] = datetime.utcnow() - timedelta(
            seconds=job_queue.GRAPH_JOB_HARD_TIMEOUT_SECONDS + 1
        )
        marked = asyncio.run_coroutine_threadsafe(
            job_queue.mark_timed_out_jobs_once(), stop.runners.loop
        ).result(WAIT)
        assert marked == 1
        error_message = GRAPH_TIMEOUT_TEXT
        assert [c["request_id"] for c in stop.rollbacks.calls] == [rid]
    else:
        handled = generation_rollback.recover_orphaned_generations(
            now=datetime.utcnow()
            + timedelta(seconds=generation_rollback.ORPHAN_AFTER_SECONDS + 1)
        )
        assert handled == 1
        error_message = generation_rollback.GENERATION_INTERRUPTED_MESSAGE
    ended_at = time.monotonic()

    after = stop.tables()
    _assert_rolled_back_to_enter(
        stop.rb, before, at_turn_end, after,
        rid=rid, actor_sid=sid, owner_sid=sid,
        terminal_status="error", error_message=error_message, deck_existed=True,
    )
    assert stop.rb.slide_htmls(sid) == [built_html(t) for t in EARLIER_TAGS]
    _assert_lock(stop.rb, sid, held_by=None)
    stop.assert_runner_freed(rid, ended_at)
    _assert_tables_equal(after, stop.tables())
    body = stop.poll(rid)
    assert (body["status"], body["error"], body["rollback"], body["events"]) == (
        "error", error_message, "rolled_back", []
    )

    b2.release.set()
    assert stop.turns.wait_graph(rid), "the abandoned graph thread never ended"
    _assert_tables_equal(after, stop.tables())

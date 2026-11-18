"""The turn's deadline, from the job runner (chat concurrency, Task 5).

A turn's model calls must never start a retry wait that runs past the turn's hard
timeout, so the runner puts the deadline in ``model_calls``' context variable
(``set_turn_deadline`` / ``turn_deadline``, a ``time.monotonic()`` value).  The clock
is the one the timeout sweeper enforces: the job entry's ``started_at`` (set by
``worker()`` when a runner takes the job, on the ``datetime.utcnow()`` clock) plus
``job_hard_timeout_seconds(engine_mode)``:

    deadline = time.monotonic() + job_hard_timeout_seconds(engine_mode) - elapsed

where ``elapsed`` is the time since ``started_at``, or 0 when the job has no entry
(a direct call, e.g. recovery) or an entry with no ``started_at``.

Rules pinned here:

* both of ``process_chat_request``'s branches -- a payload carrying the enqueuer's
  ``_context``, and the no-context fallback -- install the same deadline;
* the elapsed time is read from ``started_at``, never ``queued_at``;
* a monolith job (every MCP job included) gets the monolith limit;
* the deadline is set inside the JOB's context, never the runner coroutine's, so one
  job's deadline does not leak into the next job run by the same runner;
* ``turn_deadline`` is ``_run_streaming_generator``'s trailing parameter, passed
  positionally (as every argument before it is);
* it reaches the graph's own thread through the real ``ChatService`` graph limb.

The REAL ``_run_streaming_generator`` runs (PLAN-CORRECTIONS C14).  The chat
service, the session manager and the snapshot check are stubbed: no database, no
model.  Remaining seconds are checked to within 5 s.
"""

import asyncio
import contextvars
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import job_queue
from src.services import model_calls
from tests.unit.test_stage_slide_wiring import _service_double, _service_env

_GET_CHAT_SERVICE = "src.api.services.chat_service.get_chat_service"
_GET_SESSION_MANAGER = "src.api.services.session_manager.get_session_manager"
_HAS_SNAPSHOT = "src.services.generation_rollback.has_generation_snapshot"
_INVOKE_GRAPH = "src.services.graph.builder.invoke_graph"

_TOLERANCE_SECONDS = 5.0
_RID = "req-deadline"

#: The limits, spelled out: a test that read them from job_queue would follow a
#: changed constant instead of pinning it.
_GRAPH_LIMIT = 1200.0
_MONOLITH_LIMIT = 600.0


class _DeadlineRecorder:
    """Stands in for the chat service: records the deadline each turn runs under."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def send_message_streaming(self, **kwargs):
        # Read when the generator is first advanced: inside _run_streaming_generator,
        # in the job's context, exactly where the real service would read it.
        self.calls.append(
            {
                "request_id": kwargs.get("request_id"),
                "deadline": model_calls.turn_deadline(),
                "now": time.monotonic(),
                "kwargs": kwargs,
            }
        )
        yield StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})

    def remaining(self, request_id: str) -> float:
        """Seconds the turn had left when its service ran; fails on no deadline."""
        seen = [call for call in self.calls if call["request_id"] == request_id]
        assert len(seen) == 1, f"{request_id} reached the chat service {len(seen)} times"
        return _remaining(seen[0]["deadline"], seen[0]["now"])


def _remaining(deadline: Any, now: float) -> float:
    assert deadline is not None, "the turn ran with no deadline (turn_deadline() is None)"
    assert isinstance(deadline, float), f"the turn's deadline is not a float: {deadline!r}"
    return deadline - now


def _assert_about(remaining: float, expected: float) -> None:
    assert remaining == pytest.approx(expected, abs=_TOLERANCE_SECONDS), (
        f"the turn had {remaining:.1f} s left; expected about {expected:.0f} s"
    )


@pytest.fixture(autouse=True)
def _clean_queue():
    """No tracked jobs, no chat pool, and no deadline in the test's own context."""
    job_queue.jobs.clear()
    # Another test file's direct process_chat_request call may have left a pool.
    job_queue.shutdown_chat_executor()
    model_calls.set_turn_deadline(None)
    yield
    job_queue.shutdown_chat_executor()
    job_queue.jobs.clear()
    model_calls.set_turn_deadline(None)


@pytest.fixture
def service():
    """The recording chat service, with the job's other collaborators stubbed."""
    recorder = _DeadlineRecorder()
    with (
        patch(_GET_CHAT_SERVICE, return_value=recorder),
        patch(_GET_SESSION_MANAGER, return_value=MagicMock()),
        # No database here: a graph job finds no generation snapshot.
        patch(_HAS_SNAPSHOT, return_value=False),
    ):
        yield recorder


def _job_context() -> contextvars.Context:
    """The enqueuer's context, as ``enqueue_job`` captures it, carrying no deadline."""
    ctx = contextvars.copy_context()
    ctx.run(model_calls.set_turn_deadline, None)
    return ctx


def _seed(
    request_id: str,
    engine_mode: Optional[str],
    *,
    started_ago: Optional[float],
    queued_ago: float = 300.0,
) -> None:
    """The job's entry as ``enqueue_job`` and then ``worker()`` leave it.

    ``queued_at`` is always earlier than ``started_at``, so a deadline counted from
    the wrong timestamp is visible.  ``started_ago=None`` is a job no runner has
    taken (``enqueue_job``'s entry alone).
    """
    now = datetime.utcnow()
    entry: Dict[str, Any] = {
        "status": "pending",
        "session_id": "s-1",
        "engine_mode": engine_mode,
        "queued_at": now - timedelta(seconds=queued_ago),
    }
    if started_ago is not None:
        entry["status"] = "running"
        entry["started_at"] = now - timedelta(seconds=started_ago)
    job_queue.jobs[request_id] = entry


def _payload(engine_mode: Optional[str] = "graph", *, with_context: bool = True) -> dict:
    """A chat job's payload; ``engine_mode=None`` has no key (as MCP builds it)."""
    payload: Dict[str, Any] = {
        "session_id": "s-1",
        "message": "build",
        "slide_context": None,
        "is_first_message": False,
        "image_ids": None,
    }
    if engine_mode is not None:
        payload["engine_mode"] = engine_mode
    if with_context:
        payload["_context"] = _job_context()
    return payload


def _run_job(request_id: str, payload: dict) -> None:
    asyncio.run(job_queue.process_chat_request(request_id, payload))


# --- the deadline each turn gets -------------------------------------------------------


def test_a_graph_turn_runs_with_the_hard_timeout_as_its_deadline(service):
    """Taken by a runner 100 s ago: 1200 - 100 s left, counted from ``started_at``."""
    _seed(_RID, "graph", started_ago=100.0)
    _run_job(_RID, _payload("graph"))
    _assert_about(service.remaining(_RID), _GRAPH_LIMIT - 100.0)


@pytest.mark.parametrize("started_ago", [0.0, 100.0], ids=["started-now", "started-100s-ago"])
def test_a_monolith_turn_gets_its_own_limit(service, started_ago):
    _seed(_RID, "monolith", started_ago=started_ago)
    _run_job(_RID, _payload("monolith"))
    _assert_about(service.remaining(_RID), _MONOLITH_LIMIT - started_ago)


def test_an_mcp_job_gets_the_monolith_limit(service):
    """MCP's real shape: ``mode`` and ``correlation_id``, and no ``engine_mode`` key."""
    payload = _payload(None)
    payload.update({"mode": "generate", "correlation_id": "c-1"})
    _seed(_RID, None, started_ago=0.0)
    _run_job(_RID, payload)
    _assert_about(service.remaining(_RID), _MONOLITH_LIMIT)
    assert service.calls[0]["kwargs"]["engine_mode"] == "monolith"


@pytest.mark.parametrize("with_context", [True, False], ids=["ctx", "no-ctx"])
def test_a_direct_call_without_a_job_entry_gets_the_full_limit(service, with_context):
    """The recovery path: ``process_chat_request`` called with no ``jobs`` entry."""
    assert _RID not in job_queue.jobs
    _run_job(_RID, _payload("graph", with_context=with_context))
    _assert_about(service.remaining(_RID), _GRAPH_LIMIT)


def test_a_job_no_runner_has_taken_gets_the_full_limit(service):
    """An entry with no ``started_at``: elapsed is 0, not the time since it was queued."""
    _seed(_RID, "graph", started_ago=None, queued_ago=300.0)
    _run_job(_RID, _payload("graph"))
    _assert_about(service.remaining(_RID), _GRAPH_LIMIT)


@pytest.mark.parametrize(
    "engine_mode, started_ago, expected",
    [
        ("graph", 100.0, _GRAPH_LIMIT - 100.0),
        ("monolith", 0.0, _MONOLITH_LIMIT),
        ("monolith", 100.0, _MONOLITH_LIMIT - 100.0),
    ],
    ids=["graph-started-100s-ago", "monolith-started-now", "monolith-started-100s-ago"],
)
def test_the_no_context_fallback_also_gets_a_deadline(service, engine_mode, started_ago, expected):
    """A payload without ``_context`` gets the same deadline as one with it."""
    _seed(_RID, engine_mode, started_ago=started_ago)
    _run_job(_RID, _payload(engine_mode, with_context=False))
    _assert_about(service.remaining(_RID), expected)


# --- one job's deadline is its own ------------------------------------------------------


def test_the_deadline_does_not_leak_between_jobs(service):
    """Two jobs, one after the other, on ONE runner coroutine (as ``worker()`` runs them).

    ``asyncio.run`` runs its coroutine in a copy of the test's context, so a deadline
    set in the runner's context (rather than the job's) is only visible from inside
    that coroutine: it is checked there after each job, and in the test's context too.
    """
    first, second = "req-first", "req-second"

    async def one_runner() -> List[Optional[float]]:
        seen = [model_calls.turn_deadline()]
        _seed(first, "graph", started_ago=100.0)
        await job_queue.process_chat_request(first, _payload("graph"))
        seen.append(model_calls.turn_deadline())
        _seed(second, "monolith", started_ago=0.0)
        await job_queue.process_chat_request(second, _payload("monolith"))
        seen.append(model_calls.turn_deadline())
        return seen

    before, after_first, after_second = asyncio.run(one_runner())
    assert before is None
    assert after_first is None, "the first job's deadline was left in the runner's context"
    assert after_second is None, "the second job's deadline was left in the runner's context"
    assert model_calls.turn_deadline() is None
    _assert_about(service.remaining(first), _GRAPH_LIMIT - 100.0)
    _assert_about(service.remaining(second), _MONOLITH_LIMIT)


# --- _run_streaming_generator takes it, trailing and positional ---------------------------


def test_the_deadline_is_the_trailing_positional_argument():
    """Both call sites pass every argument positionally: the deadline comes last.

    Run in a copied context, so the deadline the function sets cannot reach this
    test's own context (or the next test's).
    """
    recorder = _DeadlineRecorder()
    deadline = time.monotonic() + 777.0
    leading = ("s-1", "build", None, _RID, False, None)

    def call() -> None:
        try:
            job_queue._run_streaming_generator(recorder, *leading, "graph", None, deadline)
        except TypeError as exc:
            if "positional argument" in str(exc):
                pytest.fail(f"_run_streaming_generator takes no trailing deadline: {exc}")
            raise

    contextvars.copy_context().run(call)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["deadline"] == deadline
    kwargs = recorder.calls[0]["kwargs"]
    assert kwargs["engine_mode"] == "graph"
    assert kwargs["stage_slide"] is None
    assert model_calls.turn_deadline() is None


# --- it reaches the graph's own thread --------------------------------------------------


def test_the_deadline_reaches_the_graphs_own_thread():
    """Through the real ``ChatService`` graph limb, onto the thread ``invoke_graph`` runs on.

    Spec §3: the deadline reaches slide pipelines the way ``chat_request_id_var``
    does, by the contexts the graph limb copies.
    """
    seen: Dict[str, Any] = {}

    def invoke_graph(session_id, initial=None, **kwargs):
        seen["deadline"] = model_calls.turn_deadline()
        seen["now"] = time.monotonic()
        seen["thread"] = threading.current_thread().name
        return {}

    chat_service = _service_double()
    _seed(_RID, "graph", started_ago=100.0)
    with (
        _service_env(),
        # Inside _service_env, so this stub replaces its recorder.
        patch(_INVOKE_GRAPH, invoke_graph),
        patch(_GET_CHAT_SERVICE, return_value=chat_service),
        patch(_GET_SESSION_MANAGER, return_value=MagicMock()),
        patch(_HAS_SNAPSHOT, return_value=False),
    ):
        _run_job(_RID, _payload("graph"))

    assert "thread" in seen, "the graph limb never reached invoke_graph"
    assert not seen["thread"].startswith("chat-job"), (
        f"invoke_graph ran on the job's thread ({seen['thread']}), not the graph's own"
    )
    _assert_about(_remaining(seen["deadline"], seen["now"]), _GRAPH_LIMIT - 100.0)

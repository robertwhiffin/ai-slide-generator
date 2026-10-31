"""Chat job concurrency inside one uvicorn process.

Each uvicorn process (``UVICORN_WORKERS``, default 4) used to run ONE chat job at
a time: a second turn that landed on the same process waited, ``pending``, until
the first finished (measured 2026-10-31: an agent turn queued 3 m 45 s behind a
legacy run).  ``start_workers`` now runs ``chat_job_concurrency()`` job runners
per process over the process's one queue.

Chat jobs hold a thread for minutes, so they run on a dedicated pool, never the
loop's default executor: the API's request handlers (the chat poll among them)
``asyncio.to_thread`` onto that default pool, and long jobs parked there would
starve them.
"""

import asyncio
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services import job_queue

_USER = contextvars.ContextVar("test_user", default=None)


class _BlockingGenerator:
    """Stands in for ``_run_streaming_generator``: blocks each job until released."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started: list[str] = []
        self.active = 0
        self.peak = 0
        self.threads: dict[str, str] = {}
        self.users: dict[str, object] = {}
        self.release: dict[str, threading.Event] = {}

    def gate(self, request_id: str) -> threading.Event:
        with self.lock:
            return self.release.setdefault(request_id, threading.Event())

    def __call__(
        self,
        chat_service,
        session_id,
        message,
        slide_context,
        request_id,
        is_first_message=False,
        image_ids=None,
        engine_mode="monolith",
    ):
        with self.lock:
            self.started.append(request_id)
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.threads[request_id] = threading.current_thread().name
            self.users[request_id] = _USER.get()
        try:
            assert self.gate(request_id).wait(10), f"{request_id} was never released"
        finally:
            with self.lock:
                self.active -= 1
        return [StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []})]


@pytest.fixture
def env(monkeypatch):
    """A fresh queue, no tracked jobs, and the job's collaborators stubbed out."""
    monkeypatch.setattr(job_queue, "job_queue", asyncio.Queue())
    job_queue.jobs.clear()
    gen = _BlockingGenerator()
    manager = MagicMock()
    with (
        patch.object(job_queue, "_run_streaming_generator", gen),
        patch("src.api.services.session_manager.get_session_manager", return_value=manager),
        patch("src.api.services.chat_service.get_chat_service", return_value=MagicMock()),
    ):
        yield gen, manager
    for event in gen.release.values():
        event.set()
    job_queue.shutdown_chat_executor()
    job_queue.jobs.clear()


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


def _payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "message": "build",
        "slide_context": None,
        "is_first_message": True,
        "image_ids": None,
        "engine_mode": "graph",
    }


def _statuses(manager) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for call in manager.update_chat_request_status.call_args_list:
        seen.setdefault(call.args[0], []).append(call.args[1])
    return seen


# --- how many runners ------------------------------------------------------------


def test_default_concurrency_is_four(monkeypatch):
    monkeypatch.delenv(job_queue.CHAT_JOB_CONCURRENCY_ENV, raising=False)
    assert job_queue.chat_job_concurrency() == 4


@pytest.mark.parametrize("raw, expected", [("1", 1), ("6", 6), (" 3 ", 3)])
def test_concurrency_comes_from_the_environment(monkeypatch, raw, expected):
    monkeypatch.setenv(job_queue.CHAT_JOB_CONCURRENCY_ENV, raw)
    assert job_queue.chat_job_concurrency() == expected


@pytest.mark.parametrize("raw", ["0", "-2", "four", "", "2.5"])
def test_an_unusable_value_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv(job_queue.CHAT_JOB_CONCURRENCY_ENV, raw)
    assert job_queue.chat_job_concurrency() == job_queue.DEFAULT_CHAT_JOB_CONCURRENCY


def test_a_huge_value_is_capped(monkeypatch):
    monkeypatch.setenv(job_queue.CHAT_JOB_CONCURRENCY_ENV, "500")
    assert job_queue.chat_job_concurrency() == job_queue.MAX_CHAT_JOB_CONCURRENCY


def test_the_env_var_name_is_stable():
    """Deploy configs set it by name; renaming it would silently drop the setting."""
    assert job_queue.CHAT_JOB_CONCURRENCY_ENV == "TELLR_CHAT_JOB_CONCURRENCY"


# --- runners run jobs side by side -------------------------------------------------


@pytest.mark.asyncio
async def test_two_runners_run_two_jobs_at_once(env):
    gen, manager = env
    tasks = await job_queue.start_workers(2)
    try:
        await job_queue.enqueue_job("req-a", _payload("s-a"))
        await job_queue.enqueue_job("req-b", _payload("s-b"))
        await _until(lambda: len(gen.started) == 2)
        assert gen.peak == 2, "the second job waited for the first"
        assert job_queue.jobs["req-b"]["status"] == "running"
        gen.gate("req-a").set()
        gen.gate("req-b").set()
        await _until(lambda: not job_queue.jobs)
        statuses = _statuses(manager)
        assert statuses["req-a"][-1] == "completed"
        assert statuses["req-b"][-1] == "completed"
    finally:
        await job_queue.stop_workers(tasks)


@pytest.mark.asyncio
async def test_one_runner_still_runs_jobs_in_order(env):
    """TELLR_CHAT_JOB_CONCURRENCY=1 keeps today's serial behaviour."""
    gen, manager = env
    tasks = await job_queue.start_workers(1)
    try:
        await job_queue.enqueue_job("req-a", _payload("s-a"))
        await job_queue.enqueue_job("req-b", _payload("s-b"))
        await _until(lambda: gen.started == ["req-a"])
        await asyncio.sleep(0.3)
        assert gen.started == ["req-a"], "a single runner started a second job"
        assert job_queue.jobs["req-b"]["status"] == "pending"
        gen.gate("req-a").set()
        await _until(lambda: gen.started == ["req-a", "req-b"])
        gen.gate("req-b").set()
        await _until(lambda: not job_queue.jobs)
        assert gen.peak == 1
    finally:
        await job_queue.stop_workers(tasks)


@pytest.mark.asyncio
async def test_more_jobs_than_runners_queue_and_all_finish(env):
    gen, manager = env
    tasks = await job_queue.start_workers(2)
    try:
        for i in range(5):
            await job_queue.enqueue_job(f"req-{i}", _payload(f"s-{i}"))
        await _until(lambda: len(gen.started) == 2)
        await asyncio.sleep(0.2)
        assert len(gen.started) == 2 and gen.peak == 2
        for i in range(5):
            gen.gate(f"req-{i}").set()
        await _until(lambda: not job_queue.jobs)
        assert sorted(gen.started) == [f"req-{i}" for i in range(5)]
        assert gen.peak <= 2
        assert all(s[-1] == "completed" for s in _statuses(manager).values())
    finally:
        await job_queue.stop_workers(tasks)


@pytest.mark.asyncio
async def test_a_failing_job_frees_its_runner(env):
    gen, manager = env

    def boom(*args, **kwargs):
        raise RuntimeError("model down")

    tasks = await job_queue.start_workers(1)
    try:
        with patch.object(job_queue, "_run_streaming_generator", boom):
            await job_queue.enqueue_job("req-bad", _payload("s-bad"))
            await _until(lambda: "req-bad" not in job_queue.jobs)
        await job_queue.enqueue_job("req-good", _payload("s-good"))
        await _until(lambda: gen.started == ["req-good"])
        gen.gate("req-good").set()
        await _until(lambda: not job_queue.jobs)
        statuses = _statuses(manager)
        assert statuses["req-bad"][-1] == "error"
        assert statuses["req-good"][-1] == "completed"
    finally:
        await job_queue.stop_workers(tasks)


# --- the thread pool ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_jobs_never_occupy_the_default_executor(env):
    """With a one-thread default pool, a request handler's to_thread still runs
    while two chat jobs are blocked."""
    gen, manager = env
    loop = asyncio.get_running_loop()
    default = ThreadPoolExecutor(max_workers=1, thread_name_prefix="default")
    loop.set_default_executor(default)
    tasks = await job_queue.start_workers(2)
    try:
        await job_queue.enqueue_job("req-a", _payload("s-a"))
        await job_queue.enqueue_job("req-b", _payload("s-b"))
        await _until(lambda: len(gen.started) == 2)
        result = await asyncio.wait_for(asyncio.to_thread(lambda: "handled"), 2)
        assert result == "handled"
        assert all(name.startswith("chat-job") for name in gen.threads.values()), gen.threads
    finally:
        for event in gen.release.values():
            event.set()
        await job_queue.stop_workers(tasks)
        default.shutdown(wait=False)


@pytest.mark.asyncio
async def test_the_chat_pool_matches_the_runner_count(env):
    tasks = await job_queue.start_workers(3)
    try:
        assert job_queue.get_chat_executor()._max_workers == 3
    finally:
        await job_queue.stop_workers(tasks)


def test_a_direct_call_without_workers_still_has_a_pool(env, monkeypatch):
    """Recovery and the existing wiring tests call process_chat_request directly."""
    gen, manager = env
    monkeypatch.setenv(job_queue.CHAT_JOB_CONCURRENCY_ENV, "2")
    gen.gate("req-direct").set()
    asyncio.run(job_queue.process_chat_request("req-direct", _payload("s-d")))
    assert gen.started == ["req-direct"]
    assert gen.threads["req-direct"].startswith("chat-job")


@pytest.mark.asyncio
async def test_the_enqueuers_context_reaches_the_job(env):
    """User auth travels in the context captured at enqueue time."""
    gen, manager = env
    tasks = await job_queue.start_workers(2)
    try:
        token = _USER.set("alice@example.com")
        try:
            await job_queue.enqueue_job("req-ctx", _payload("s-ctx"))
        finally:
            _USER.reset(token)
        await _until(lambda: "req-ctx" in gen.users)
        assert gen.users["req-ctx"] == "alice@example.com"
        gen.gate("req-ctx").set()
        await _until(lambda: not job_queue.jobs)
    finally:
        await job_queue.stop_workers(tasks)


# --- shutdown ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_workers_cancels_every_runner(env):
    tasks = await job_queue.start_workers(3)
    assert len(tasks) == 3
    await job_queue.stop_workers(tasks)
    assert all(t.done() for t in tasks)

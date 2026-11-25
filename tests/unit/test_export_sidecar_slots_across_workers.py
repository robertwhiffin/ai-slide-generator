"""The export sidecars' slots are the container's, not each worker's.

The app runs several uvicorn worker processes in one container
(``packages/databricks-tellr-app/databricks_tellr_app/run.py``, ``UVICORN_WORKERS``), and the
kernel does not balance requests across them. Measured on a deployed app with four workers
and one slot each: three of four simultaneous exports landed on one worker while the others
idled, so they queued behind each other there, and one was refused (429) at its 60 s wait.
What a slot protects, memory, is the container's, and so now are the slots:
``UVICORN_WORKERS`` x ``TELLR_SIDECAR_CONCURRENCY`` of them, files of one directory each held
with ``fcntl.flock`` (``src/services/sidecar_slots.py``), which ``run.py`` names in the
environment of every worker it starts.

The coherence cases run real separate processes, each the export wrapper in a fresh
interpreter with the container's environment, whose sidecar is a stub that records its run:
of N + 1 exports at once exactly N run together, and the last waits and then runs, or is
refused (``HuashuBusyError``, which the routes answer 429) once its wait bound passes; and a
process killed while it holds a slot frees it, since the kernel drops the lock with the
descriptors its death closes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from src.services import pptx_from_html_huashu, sidecar_slots
from tests.fixtures.export_snapshot_support import requires_node

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = REPO_ROOT / "packages" / "databricks-tellr-app" / "databricks_tellr_app" / "run.py"
# The variable run.py names the workers' shared slot directory in (sidecar_slots.SLOTS_DIR_ENV).
SLOTS_DIR_ENV = "TELLR_SIDECAR_SLOTS_DIR"
# How many workers share the container's slots: run.py's own setting, which it passes on.
WORKERS_ENV = "UVICORN_WORKERS"

# How long a fresh interpreter may take to import the wrapper and say it is ready.
PROCESS_START_SECONDS = 60
# A recorded sidecar run, and one longer than a short wait bound and a refusal.
RUN_SECONDS = 2
LONG_RUN_SECONDS = 5
# A wait that outlasts every run ahead of it, and one shorter than any.
LONG_WAIT_SECONDS = 30
SHORT_WAIT_SECONDS = 1
# A refusal at the wait bound comes within this past it; a freed slot is taken within it.
WAIT_SLACK_SECONDS = 1.5
# The longest any group of exports here may take to answer.
EXPORTS_ANSWER_WITHIN_SECONDS = 90
# How long the killed-holder case lets its export wait before the holder is killed.
HELD_FOR_SECONDS = 2

# The export's sidecar: it reads the payload, records its start and end, and writes a deck.
STUB_RECORDED_RUN = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const record = (event) => fs.appendFileSync(
  %(runs)s, JSON.stringify({ pid: process.pid, event, at: Date.now() / 1000 }) + '\\n'
);
record('start');
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
fs.writeFileSync(process.argv[2], 'PK');
record('end');
console.error('__HUASHU_RESULT__ ' + JSON.stringify({ totalSlides: 1, succeeded: 1, failed: [] }));
"""

# One worker's exports: the wrapper imported as a worker imports it, its bounds read from the
# environment, its sidecar the stub (argv[1]). It says it is ready (argv[2]), waits for the
# word (argv[3]), runs argv[4] exports at once, each in a thread as the threadpool runs them,
# and prints each one's outcome.
EXPORT_PROCESS = """
import json
import sys
import threading
import time
from pathlib import Path

from src.services import pptx_from_html_huashu as wrapper

wrapper.SIDECAR_SCRIPT = Path(sys.argv[1])
wrapper.is_available = lambda: True
ready, go, count = Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
outcomes = []


def export():
    asked = time.time()
    try:
        pptx, failures = wrapper.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
        built = (pptx, failures) == (b"PK", [])
        outcome = "built" if built else f"unexpected {pptx!r} {failures!r}"
    except wrapper.HuashuBusyError:
        outcome = "busy"
    outcomes.append({"outcome": outcome, "asked": asked, "answered": time.time()})


ready.write_text("ready", encoding="utf-8")
while not go.exists():
    time.sleep(0.01)
threads = [threading.Thread(target=export) for _ in range(count)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(json.dumps(outcomes))
"""

# A worker that takes one of the container's slots through the wrapper's own slots, says so
# (argv[1]), and holds it until it is killed.
HOLDER_PROCESS = """
import sys
import time
from pathlib import Path

from src.services import pptx_from_html_huashu as wrapper

assert wrapper._sidecar_slots.acquire(blocking=False), "the container's slot was not free"
Path(sys.argv[1]).write_text("held", encoding="utf-8")
time.sleep(600)
"""

# Appended to EXPORT_PROCESS: once its exports are answered, the worker says so beside its
# ready file and stays alive, as a worker does, until it is killed.
KEPT_ALIVE = """
(ready.parent / "exported").write_text("exported", encoding="utf-8")
time.sleep(600)
"""

# A worker's own view of its bounds and its summary line, as its environment sets them.
BOUNDS_PROCESS = """
import json

from src.services import pptx_from_html_huashu as wrapper

places = 0
while wrapper._sidecar_admissions.acquire(blocking=False):
    places += 1
line = wrapper._ExportSummary(target="pptx", slides=1).line()
summary = json.loads(line.removeprefix(wrapper.EXPORT_SUMMARY_PREFIX))
print(json.dumps({"places": places, "summary": summary}))
"""


@dataclass(frozen=True)
class _Container:
    """One container's exports: their shared environment, their stub sidecar and its run log."""

    env: dict[str, str]
    stub: Path
    runs: Path
    scratch: Path


def _container(
    tmp_path: Path, *, workers: int, wait: float, run_seconds: float, queue: int | None = None
) -> _Container:
    """A container of ``workers`` workers at one slot each, as run.py starts them."""
    slots = tmp_path / "slots"
    slots.mkdir(mode=0o700)
    runs = tmp_path / "runs.jsonl"
    stub = tmp_path / "stub_recorded_run.mjs"
    stub.write_text(
        STUB_RECORDED_RUN % {"runs": json.dumps(str(runs)), "ms": int(run_seconds * 1000)},
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("TELLR_SIDECAR_") and key != WORKERS_ENV
    }
    env.update(
        PYTHONPATH=str(REPO_ROOT),
        ENVIRONMENT="test",
        TELLR_SIDECAR_CONCURRENCY="1",
        TELLR_SIDECAR_WAIT_SECONDS=str(wait),
        **{WORKERS_ENV: str(workers), SLOTS_DIR_ENV: str(slots)},
    )
    if queue is not None:
        env["TELLR_SIDECAR_QUEUE"] = str(queue)
    return _Container(env=env, stub=stub, runs=runs, scratch=tmp_path)


def _start(container: _Container, script: str, *arguments: object) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script, *(str(argument) for argument in arguments)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=REPO_ROOT,
        env=container.env,
        start_new_session=True,
    )


def _wait_for(path: Path, process: subprocess.Popen, what: str) -> None:
    deadline = time.monotonic() + PROCESS_START_SECONDS
    while not path.exists():
        if process.poll() is not None:
            pytest.fail(f"{what} exited {process.returncode}: {process.stderr.read()[-3000:]}")
        assert time.monotonic() < deadline, f"{what} never got ready"
        time.sleep(0.02)


def _end(processes: list[subprocess.Popen], runs: Path) -> None:
    """Every process here killed, and every recorded sidecar run that never ended."""
    for process in processes:
        if process.poll() is None:
            _kill_group(process.pid)
        process.wait()
    for _, end, pid in _recorded(runs):
        if end is None:
            _kill_group(pid)


def _kill_group(pid: int) -> None:
    """SIGKILL the process group ``pid`` leads; one gone, or a zombie (macOS: EPERM), is passed."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _recorded(runs: Path) -> list[tuple[float, float | None, int]]:
    """Each recorded sidecar run, ``(start, end or None, pid)``, in the order they started."""
    if not runs.exists():
        return []
    events: dict[int, dict[str, float]] = {}
    for line in runs.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        events.setdefault(entry["pid"], {})[entry["event"]] = entry["at"]
    return sorted((run["start"], run.get("end"), pid) for pid, run in events.items())


def _runs(runs: Path) -> list[tuple[float, float]]:
    recorded = _recorded(runs)
    assert all(end is not None for _, end, _ in recorded), f"a run never ended: {recorded}"
    return [(start, end) for start, end, _ in recorded]


def _most_at_once(runs: list[tuple[float, float]]) -> int:
    """The most runs that ran at one moment (one that ends as another starts is not with it)."""
    moments = sorted([(start, 1) for start, _ in runs] + [(end, -1) for _, end in runs])
    running = most = 0
    for _, change in moments:
        running += change
        most = max(most, running)
    return most


def _exports(container: _Container, per_worker: list[int]) -> list[dict]:
    """Exports sent at once to the container's workers, ``per_worker[i]`` to worker i.

    Each worker is a fresh interpreter; all are ready before any export is sent. Returns
    every export's outcome, in the order they were answered.
    """
    go = container.scratch / "go"
    readies = [container.scratch / f"ready-{index}" for index in range(len(per_worker))]
    processes: list[subprocess.Popen] = []
    try:
        for ready, count in zip(readies, per_worker):
            processes.append(_start(container, EXPORT_PROCESS, container.stub, ready, go, count))
        for index, (ready, process) in enumerate(zip(readies, processes)):
            _wait_for(ready, process, f"worker {index}")
        go.write_text("go", encoding="utf-8")
        outcomes: list[dict] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=EXPORTS_ANSWER_WITHIN_SECONDS)
            assert process.returncode == 0, stderr[-3000:]
            outcomes.extend(json.loads(stdout.strip().splitlines()[-1]))
        return sorted(outcomes, key=lambda outcome: outcome["answered"])
    finally:
        _end(processes, container.runs)


@requires_node
class TestTheContainersSlotsAgreeAcrossWorkers:
    """Real separate processes on one slot directory: N slots, N + 1 exports at once."""

    def test_two_slots_three_workers_two_run_at_once_and_the_third_waits_then_runs(
        self, tmp_path: Path
    ) -> None:
        container = _container(tmp_path, workers=2, wait=LONG_WAIT_SECONDS, run_seconds=RUN_SECONDS)

        outcomes = _exports(container, [1, 1, 1])

        assert [outcome["outcome"] for outcome in outcomes] == ["built"] * 3, outcomes
        runs = _runs(container.runs)
        assert _most_at_once(runs) == 2, f"not two at once: {runs}"
        (first, second, third) = runs
        assert third[0] >= min(first[1], second[1]), f"the third did not wait for a slot: {runs}"

    def test_three_exports_on_one_worker_of_two_two_run_at_once(self, tmp_path: Path) -> None:
        """Requests are not balanced: with every export on one worker, the container's slots
        still all run, and the export past them waits for one."""
        container = _container(tmp_path, workers=2, wait=LONG_WAIT_SECONDS, run_seconds=RUN_SECONDS)

        outcomes = _exports(container, [3])

        assert [outcome["outcome"] for outcome in outcomes] == ["built"] * 3, outcomes
        assert _most_at_once(_runs(container.runs)) == 2, _runs(container.runs)

    def test_the_last_export_is_refused_at_its_wait_bound_while_the_slots_are_held(
        self, tmp_path: Path
    ) -> None:
        container = _container(
            tmp_path, workers=2, wait=SHORT_WAIT_SECONDS, run_seconds=LONG_RUN_SECONDS
        )

        outcomes = _exports(container, [1, 1, 1])

        assert [outcome["outcome"] for outcome in outcomes] == ["busy", "built", "built"], outcomes
        refused = outcomes[0]
        waited = refused["answered"] - refused["asked"]
        assert SHORT_WAIT_SECONDS - 0.1 <= waited < SHORT_WAIT_SECONDS + WAIT_SLACK_SECONDS, (
            f"refused after {waited:.2f}s, the bound {SHORT_WAIT_SECONDS}s"
        )
        runs = _runs(container.runs)
        assert len(runs) == 2, f"the refused export ran a sidecar: {runs}"
        assert refused["answered"] < min(end for _, end in runs), "refused once a slot was free"

    def test_a_worker_killed_holding_the_slot_frees_it(self, tmp_path: Path) -> None:
        """One slot, held by a worker; an export waits on another; the holder is killed: the
        export takes the slot at once and runs."""
        container = _container(tmp_path, workers=1, wait=LONG_WAIT_SECONDS, run_seconds=RUN_SECONDS)
        held = tmp_path / "held"
        ready, go = tmp_path / "ready", tmp_path / "go"
        holder = _start(container, HOLDER_PROCESS, held)
        processes = [holder]
        try:
            _wait_for(held, holder, "the holder")
            worker = _start(container, EXPORT_PROCESS, container.stub, ready, go, 1)
            processes.append(worker)
            _wait_for(ready, worker, "the export's worker")
            go.write_text("go", encoding="utf-8")
            time.sleep(HELD_FOR_SECONDS)
            assert _recorded(container.runs) == [], "the export ran while the slot was held"

            killed_at = time.time()
            _kill_group(holder.pid)
            stdout, stderr = worker.communicate(timeout=EXPORTS_ANSWER_WITHIN_SECONDS)
        finally:
            _end(processes, container.runs)

        assert worker.returncode == 0, stderr[-3000:]
        (outcome,) = json.loads(stdout.strip().splitlines()[-1])
        assert outcome["outcome"] == "built", outcome
        ((started, _),) = _runs(container.runs)
        assert killed_at <= started < killed_at + WAIT_SLACK_SECONDS, (
            f"the run started {started - killed_at:+.2f}s from the holder's death"
        )


@requires_node
class TestAWorkerLetsInEveryOneOfTheContainersSlots:
    def test_three_exports_on_one_worker_of_three_all_run_at_once(self, tmp_path: Path) -> None:
        """The measured case, at most three contending: every export on one of the workers,
        no queue, and each runs in one of the container's slots."""
        container = _container(
            tmp_path, workers=3, wait=LONG_WAIT_SECONDS, run_seconds=RUN_SECONDS, queue=0
        )

        outcomes = _exports(container, [3])

        assert [outcome["outcome"] for outcome in outcomes] == ["built"] * 3, outcomes
        assert _most_at_once(_runs(container.runs)) == 3, _runs(container.runs)


def _bounds(tmp_path: Path, *, workers: int | None, queue: int) -> dict:
    """What a fresh worker with these settings reads: its export places and its summary line."""
    container = _container(tmp_path, workers=workers or 1, wait=60, run_seconds=0, queue=queue)
    env = dict(container.env)
    if workers is None:
        del env[WORKERS_ENV]
    result = subprocess.run(
        [sys.executable, "-c", BOUNDS_PROCESS],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=PROCESS_START_SECONDS,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestTheContainersSlotCount:
    @pytest.mark.parametrize(
        ("environ", "slots"),
        [
            ({}, 1),
            ({"UVICORN_WORKERS": "4"}, 4),
            ({"UVICORN_WORKERS": "4", "TELLR_SIDECAR_CONCURRENCY": "2"}, 8),
            ({"UVICORN_WORKERS": "1"}, 1),
            ({"UVICORN_WORKERS": "0"}, 1),
            ({"UVICORN_WORKERS": "-3"}, 1),
            ({"UVICORN_WORKERS": "four"}, 1),
        ],
        ids=["alone", "four workers", "four at two", "one worker", "zero", "negative", "a word"],
    )
    def test_it_is_the_workers_times_the_concurrency(self, environ: dict, slots: int) -> None:
        """A process run.py did not start runs alone: one worker."""
        assert pptx_from_html_huashu.sidecar_slot_count(environ) == slots

    def test_a_worker_count_that_is_no_whole_number_from_one_is_warned_about(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING", logger=pptx_from_html_huashu.__name__):
            pptx_from_html_huashu.sidecar_workers({"UVICORN_WORKERS": "four"})
        assert any("UVICORN_WORKERS='four'" in record.message for record in caplog.records)

    def test_the_default_bounds_of_a_four_worker_app_are_within_both_limits(self) -> None:
        slots = pptx_from_html_huashu.sidecar_slot_count({"UVICORN_WORKERS": "4"})
        assert pptx_from_html_huashu.sidecar_bounds_warnings(
            slots,
            pptx_from_html_huashu.sidecar_queue({}),
            pptx_from_html_huashu.sidecar_wait_seconds({}),
        ) == []

    def test_a_worker_has_a_place_for_every_slot_and_its_queue(self, tmp_path: Path) -> None:
        """Four workers' four slots and a queue of 15: a worker lets 19 exports in, and its
        summary line says the container runs 4 sidecars at once."""
        read = _bounds(tmp_path, workers=4, queue=15)

        assert read["places"] == 4 + 15, read
        assert read["summary"]["sidecarConcurrency"] == 4, read
        assert read["summary"]["queueBound"] == 15, read

    def test_the_slots_are_shared_where_run_py_names_a_directory_and_else_are_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SLOTS_DIR_ENV, str(tmp_path))
        first, second = (pptx_from_html_huashu._container_slots(1) for _ in range(2))
        assert first.acquire(blocking=False)
        assert not second.acquire(blocking=False), "two workers' slots were not the container's"
        first.release()

        monkeypatch.delenv(SLOTS_DIR_ENV)
        first, second = (pptx_from_html_huashu._container_slots(1) for _ in range(2))
        assert first.acquire(blocking=False) and second.acquire(blocking=False)
        first.release()
        second.release()

    def test_a_process_run_py_did_not_start_has_one_slot(self, tmp_path: Path) -> None:
        read = _bounds(tmp_path, workers=None, queue=15)

        assert read["places"] == 1 + 15, read
        assert read["summary"]["sidecarConcurrency"] == 1, read

    @requires_node
    def test_a_process_run_py_did_not_start_leaves_no_slot_files_once_killed(
        self, tmp_path: Path
    ) -> None:
        """Its slots are its own, so no file holds them: a worker killed after an export
        (SIGKILL runs no exit handler) leaves nothing of them in its temporary directory."""
        container = _container(tmp_path, workers=1, wait=LONG_WAIT_SECONDS, run_seconds=0)
        temporary = tmp_path / "tmp"
        temporary.mkdir()
        env = {**container.env, "TMPDIR": str(temporary)}
        for name in (WORKERS_ENV, SLOTS_DIR_ENV):
            env.pop(name)
        ready, go = tmp_path / "ready", tmp_path / "go"
        worker = subprocess.Popen(
            [sys.executable, "-c", EXPORT_PROCESS + KEPT_ALIVE, str(container.stub), str(ready)]
            + [str(go), "1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO_ROOT,
            env=env,
            start_new_session=True,
        )
        exported = tmp_path / "exported"
        try:
            _wait_for(ready, worker, "the worker")
            go.write_text("go", encoding="utf-8")
            _wait_for(exported, worker, "the export")
        finally:
            _end([worker], container.runs)

        assert len(_runs(container.runs)) == 1
        left = sorted(path.name for path in temporary.iterdir())
        assert left == [], f"a killed worker left {left} in its temporary directory"


def _run_module() -> ModuleType:
    """run.py, loaded from its file: the app package is not installed in the test venv."""
    spec = importlib.util.spec_from_file_location("tellr_app_run_under_test", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRunSharesTheSlotsWithItsWorkers:
    """run.py names one slot directory and its worker count in its workers' environment.

    uvicorn starts each worker as a fresh interpreter (multiprocessing's spawn), which
    inherits the environment run.py has when it calls ``uvicorn.run``.
    """

    @pytest.fixture
    def started(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        """What ``uvicorn.run`` was called with, and the environment it was called in."""
        for name in (WORKERS_ENV, SLOTS_DIR_ENV):
            monkeypatch.setenv(name, "")
            monkeypatch.delenv(name)
        run = _run_module()
        seen: dict = {}

        def fake_run(app: str, **options: object) -> None:
            directory = os.environ.get(SLOTS_DIR_ENV)
            mode = Path(directory).stat().st_mode if directory else None
            seen.update(
                app=app,
                workers=options.get("workers"),
                env_workers=os.environ.get(WORKERS_ENV),
                directory=directory,
                directory_mode=None if mode is None else stat.S_IMODE(mode),
            )

        monkeypatch.setattr(run.uvicorn, "run", fake_run)
        seen["run"] = run
        return seen

    def test_its_workers_share_one_slot_directory_and_know_their_count(
        self, started: dict
    ) -> None:
        started["run"].main()

        assert started["workers"] == 4 and started["env_workers"] == "4", started
        assert started["directory_mode"] == 0o700, f"no private slot directory: {started}"
        assert not Path(started["directory"]).exists(), "the slot directory outlived the server"
        assert SLOTS_DIR_ENV not in os.environ

    def test_a_worker_count_it_is_given_is_the_one_its_workers_read(
        self, started: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(WORKERS_ENV, "2")

        started["run"].main()

        assert started["workers"] == 2 and started["env_workers"] == "2", started

    def test_a_directory_the_environment_names_is_kept(
        self, started: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SLOTS_DIR_ENV, str(tmp_path))

        started["run"].main()

        assert started["directory"] == str(tmp_path), started
        assert tmp_path.is_dir() and os.environ[SLOTS_DIR_ENV] == str(tmp_path)

    def test_it_names_the_directory_where_the_workers_read_it(self, started: dict) -> None:
        """run.py writes the variable's name itself, so as not to import src.services."""
        assert started["run"].SIDECAR_SLOTS_DIR_ENV == sidecar_slots.SLOTS_DIR_ENV == SLOTS_DIR_ENV

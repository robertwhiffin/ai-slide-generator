"""#319 — a poll on ANOTHER worker process sees the running turn's stage.

Production runs several uvicorn worker processes (``UVICORN_WORKERS``, default
4).  The graph turn runs in the worker whose in-memory ``job_queue`` took
``POST /chat/async``, and ``GET /chat/poll`` can land on any worker.  So the
stage the placeholder shows must round-trip the database: anything a turn kept
in process memory (a module-level dict, a ``SessionManager`` attribute, the
tracker itself) is visible to one worker only, and the other three would serve
``None`` for the whole turn — the multi-worker bug class
(``.claude/skills/tellr-code-review`` §1).

The proof uses a REAL second OS process, not a second object in this one: the
child is a fresh interpreter with none of this process's modules, monkeypatches
or ContextVars, and it reads the row through the real ``get_db_session`` against
the same file-backed SQLite database.  It runs twice:

* before any report — the request exists but has no stage yet (``None``), which
  also proves the child is reading THIS database (it finds the request);
* after three reports and a late, older write — it sees ``seq 3``, so the stage
  crossed the process boundary and the regression was refused in the database,
  not merely in this process's tracker.

Model: ``tests/integration/test_layer4_multi_worker.py``'s child scripts
(``_run_slides_since_cursor_in_subprocess``), which run on PostgreSQL in CI; this
one always runs, on SQLite.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import get_session_manager
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter
from src.services.graph.progress import (
    SlideProgressStage,
    TurnPhase,
    report_phase,
    report_slide,
    turn_progress_scope,
    turn_progress_var,
)
from tests.unit.conftest_graph import graph_env_threadsafe  # noqa: F401 — fixture

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The child's whole program.  A fresh interpreter: DATABASE_URL is the only
#: thing that connects it to the parent's database.  The singletons are reset
#: explicitly so a future fork-mode runner cannot hand the child the parent's
#: engine or SessionManager and mask the test.
_CHILD_SCRIPT = (
    "import sys, os, json\n"
    f"sys.path.insert(0, {repr(str(_REPO_ROOT))})\n"
    "os.environ['DATABASE_URL'] = os.environ['_TELLR_TEST_DB_URL']\n"
    "os.environ['ENVIRONMENT'] = 'test'\n"
    "os.environ['DATABRICKS_HOST'] = ''\n"
    "os.environ['DATABRICKS_TOKEN'] = ''\n"
    "import src.core.database as db_mod\n"
    "db_mod._engine = None\n"
    "db_mod._session_local = None\n"
    "import src.api.services.session_manager as sm_mod\n"
    "sm_mod._session_manager = None\n"
    "from src.api.services.session_manager import SessionManager\n"
    "row = SessionManager().get_chat_request(os.environ['_TELLR_TEST_RID'])\n"
    "print(json.dumps({\n"
    "    'pid': os.getpid(),\n"
    "    'found': row is not None,\n"
    "    'turn_progress': None if row is None else row['turn_progress'],\n"
    "}))\n"
)


@pytest.fixture(autouse=True)
def _no_turn_state_leaks():
    """Clear every turn ContextVar this suite touches, before AND after each test."""
    turn_progress_var.set(None)
    set_event_emitter(None)
    set_chat_request_id(None)
    yield
    turn_progress_var.set(None)
    set_event_emitter(None)
    set_chat_request_id(None)


def _poll_from_another_process(db_url: str, request_id: str) -> Dict[str, Any]:
    """What another worker's ``get_chat_request`` reads; parsed off its LAST stdout line."""
    result = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "_TELLR_TEST_DB_URL": db_url,
            "_TELLR_TEST_RID": request_id,
            "DATABASE_URL": db_url,
            "ENVIRONMENT": "test",
            "DATABRICKS_HOST": "",
            "DATABRICKS_TOKEN": "",
        },
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        raise RuntimeError(
            f"the child process failed (returncode={result.returncode}):\n"
            f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-4000:]}"
        )
    return json.loads(lines[-1])


def _drain(q: queue.Queue) -> List[Any]:
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


def test_a_poll_on_another_worker_process_sees_the_running_turns_stage(
    graph_env_threadsafe,
):
    env = graph_env_threadsafe
    manager = get_session_manager()
    request_id = manager.create_chat_request(env.session_id)
    db_url = f"sqlite:///{env.engine.url.database}"
    parent_pid = os.getpid()

    q: queue.Queue = queue.Queue()
    set_event_emitter(q)
    set_chat_request_id(request_id)
    with turn_progress_scope() as progress:
        # -- another worker, before the turn has reported anything ------------
        before = _poll_from_another_process(db_url, request_id)
        assert before["pid"] != parent_pid, (
            "the 'other worker' ran in this process; nothing here is cross-process"
        )
        assert before["found"] is True, (
            "the child could not find the request at all, so it is reading a "
            "different database and its None below would prove nothing"
        )
        assert before["turn_progress"] is None, (
            f"the child saw a stage before any was reported: {before['turn_progress']!r}"
        )

        # -- this worker's turn reports three stages ---------------------------
        assert report_phase(TurnPhase.PLANNING) is True
        assert report_phase(
            TurnPhase.BUILDING, covered=[0, 1, 2], dispatched=[0, 1, 2]
        ) is True
        assert report_slide(0, SlideProgressStage.REVIEWING) is True
        latest = progress.snapshot()

        snapshots = [
            e.turn_progress for e in _drain(q) if e.type is StreamEventType.TURN_PROGRESS
        ]
        assert [s["seq"] for s in snapshots] == [1, 2, 3]
        assert snapshots[-1] == latest

        # -- a slow pipeline thread's seq-2 write lands late -------------------
        older = snapshots[1]
        assert manager.record_chat_request_progress(request_id, 2, older) is False, (
            "the late seq-2 write was stored: either it overwrote the newer seq-3 "
            "snapshot, or the turn's three reports never reached the row at all "
            "(an empty row accepts any seq)"
        )

        # -- another worker, mid-turn ------------------------------------------
        after = _poll_from_another_process(db_url, request_id)

    assert after["pid"] != parent_pid
    assert after["pid"] != before["pid"], "the two reads were not two processes"
    assert after["found"] is True
    seen = after["turn_progress"]
    assert seen is not None, (
        "another worker sees no stage for a turn that has reported three: the "
        "stage did not round-trip the database"
    )
    assert seen["seq"] == 3, (
        f"another worker sees seq {seen['seq']}; the late seq-2 write regressed "
        "the row, or the newest report never reached it"
    )
    assert seen["phase"] == "building"
    assert seen["slides"]["reviewing"] == [0]
    assert seen == latest, (
        "another worker's stage is not the running turn's latest snapshot:\n"
        f"  this worker: {latest!r}\n  other worker: {seen!r}"
    )

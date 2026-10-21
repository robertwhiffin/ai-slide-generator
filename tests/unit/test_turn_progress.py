"""#319 — the graph turn's stage summary (``src/services/graph/progress.py``).

The tracker is what the chat placeholder renders from on BOTH transports: the
``turn_progress`` SSE event (queued inside the tracker lock) and the turn's
``chat_requests`` row (written outside it).  This suite pins, at the tracker
level:

* **No tracker, no effect.**  Outside ``turn_progress_scope()`` every report is a
  no-op that returns ``False`` — that is the whole of the legacy-mode guarantee.
* **The wire shape** of the event and of the snapshot it carries.
* **The merge rules** (D3): the phase rank never decreases but rank-0 phases
  alternate; a slide's stage only moves strictly forward; ``covered`` only grows;
  a report that changes nothing publishes nothing (no heartbeats).
* **Lock discipline**, deterministically, not by luck: the emit is inside the
  lock (queue order == ``seq`` order) and the persist is outside it (a slow write
  never stalls another slide).  Every wait is bounded, so a sabotaged tracker
  fails these tests instead of hanging them.
* **The persist sink** and the **scope lifetime**.

Threads here never inherit a context on their own (Python < 3.14 starts a thread
in an EMPTY context), so every worker thread runs in ``copy_context().run`` taken
at spawn — the same thing LangGraph's executor does for every task, and the
reason a copy must share the one tracker object.
"""

from __future__ import annotations

import contextvars
import copy
import json
import logging
import queue
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest
import src.services.graph.progress as progress_module
from src.services.graph.progress import (
    SlideProgressStage,
    TurnPhase,
    get_turn_progress,
    report_phase,
    report_slide,
    report_slides,
    turn_progress_scope,
    turn_progress_var,
)

from src.api.schemas.streaming import StreamEventType
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter

BUILDING = SlideProgressStage.BUILDING
REVIEWING = SlideProgressStage.REVIEWING
FIXING = SlideProgressStage.FIXING
DONE = SlideProgressStage.DONE

#: The stage order, written out independently of the module's own ``STAGE_RANK``
#: so a wrong rank table cannot also be the yardstick it is measured with.
_RANK = {"building": 1, "reviewing": 2, "fixing": 3, "done": 4}

_STAGE_KEYS = ("building", "reviewing", "fixing", "done")

#: Upper bound on every thread join / event wait in this file.
_WAIT_S = 2.0

_FRONTEND_API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "services" / "api.ts"


# ---------------------------------------------------------------------------
# fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_turn_state_leaks():
    """Clear the tracker, the emitter and the request id before AND after each test.

    Before, so a value leaked by an earlier test in this worker cannot make a
    report here land in someone else's tracker; after, so nothing set here leaks
    into a later test that asserts the no-tracker path.
    """
    turn_progress_var.set(None)
    set_event_emitter(None)
    set_chat_request_id(None)
    yield
    turn_progress_var.set(None)
    set_event_emitter(None)
    set_chat_request_id(None)


@pytest.fixture
def emitter() -> queue.Queue:
    q: queue.Queue = queue.Queue()
    set_event_emitter(q)
    return q


class _RecordingSessionManager:
    """Stands in for ``SessionManager``; records every progress write.

    ``on_record`` runs AFTER the call is recorded, so a test can block or raise
    inside the write while still seeing that it was attempted.
    """

    def __init__(self, on_record: Callable[[str, int, Dict[str, Any]], None] | None = None):
        self.calls: List[tuple] = []
        self._lock = threading.Lock()
        self._on_record = on_record

    def record_chat_request_progress(self, request_id, seq, snapshot) -> None:
        with self._lock:
            # Deep-copied: a tracker that mutated a published snapshot in place
            # would otherwise rewrite what this fake "stored".
            self.calls.append((request_id, seq, copy.deepcopy(snapshot)))
        if self._on_record is not None:
            self._on_record(request_id, seq, snapshot)


def _install(monkeypatch, fake: _RecordingSessionManager) -> _RecordingSessionManager:
    monkeypatch.setattr("src.services.graph.progress.get_session_manager", lambda: fake)
    return fake


@pytest.fixture
def fake_sm(monkeypatch) -> _RecordingSessionManager:
    return _install(monkeypatch, _RecordingSessionManager())


def _drain(emitter: queue.Queue) -> list:
    events = []
    while True:
        try:
            events.append(emitter.get_nowait())
        except queue.Empty:
            return events


def _drain_progress(emitter: queue.Queue) -> List[Dict[str, Any]]:
    """Every queued event's snapshot, in queue order.  Everything queued must be one."""
    events = _drain(emitter)
    assert all(e.type is StreamEventType.TURN_PROGRESS for e in events), [e.type for e in events]
    return [e.turn_progress for e in events]


def _start(target: Callable, *args) -> threading.Thread:
    """Run *target* in a daemon thread, inside a copy of the CURRENT context.

    The copy is taken here, at spawn, exactly as LangGraph's executor takes one
    per task: it shares the tracker object, the emitter queue and the request id.
    Each thread gets its own copy (one ``Context`` cannot be entered twice at once).
    """
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(target, *args), daemon=True)
    thread.start()
    return thread


def _ranks(snapshot: Dict[str, Any]) -> Dict[int, int]:
    """position -> stage rank in *snapshot*; asserts the stage lists are disjoint."""
    ranks: Dict[int, int] = {}
    for stage in _STAGE_KEYS:
        for position in snapshot["slides"][stage]:
            assert position not in ranks, f"slide {position} is in two stage lists: {snapshot}"
            ranks[position] = _RANK[stage]
    return ranks


def _slides(total=0, building=(), reviewing=(), fixing=(), done=()) -> Dict[str, Any]:
    return {
        "total": total,
        "building": list(building),
        "reviewing": list(reviewing),
        "fixing": list(fixing),
        "done": list(done),
    }


# ---------------------------------------------------------------------------
# no tracker, the event, the wire shape
# ---------------------------------------------------------------------------


def test_reports_without_a_tracker_are_noops_and_never_raise(emitter, fake_sm):
    # A request id is bound and a session manager is reachable, so the only thing
    # standing between these reports and both sinks is the missing tracker.
    set_chat_request_id("req-no-tracker")
    assert get_turn_progress() is None

    assert report_phase(TurnPhase.PLANNING) is False
    assert report_phase(TurnPhase.BUILDING, covered=[0, 1], dispatched=[0]) is False
    assert report_slide(0, DONE) is False
    assert report_slides([0, 1, 2], DONE) is False
    # Junk cannot raise on this path either: progress is never a precondition.
    assert report_phase("not-a-phase") is False
    assert report_slide("x", "not-a-stage") is False
    assert report_slides(["x"], "not-a-stage") is False

    assert _drain(emitter) == []
    assert fake_sm.calls == []
    assert get_turn_progress() is None


def test_the_first_report_publishes_seq_one_as_a_turn_progress_event(emitter):
    with turn_progress_scope():
        assert report_phase(TurnPhase.PLANNING) is True

    events = _drain(emitter)
    assert len(events) == 1
    event = events[0]
    assert event.type is StreamEventType.TURN_PROGRESS
    # test_graph_builder.py groups a turn's events by metadata["node"].
    assert event.metadata == {"node": "progress"}
    assert event.turn_progress == {"seq": 1, "phase": "planning", "slides": _slides()}

    sse = event.to_sse()
    assert sse.startswith("event: turn_progress\n")
    data_line = sse.split("\n")[1]
    assert data_line.startswith("data: ")
    payload = json.loads(data_line[len("data: ") :])
    assert payload["type"] == "turn_progress"
    assert payload["turn_progress"]["seq"] == 1
    assert payload["turn_progress"]["phase"] == "planning"


def test_the_snapshot_shape_is_the_wire_contract(emitter):
    # The frontend conformance test pins these literals on the TS side.
    assert {s.value for s in SlideProgressStage} == set(_STAGE_KEYS)
    assert {p.value for p in TurnPhase} == {
        "planning",
        "gathering_data",
        "checking_slides",
        "building",
        "reviewing_deck",
    }

    with turn_progress_scope() as progress:
        # Dispatched in DESCENDING order, and moved on out of order, so a stage
        # list that is not explicitly sorted shows up as unsorted.
        descending = list(range(9, -1, -1))
        report_phase(TurnPhase.BUILDING, covered=descending, dispatched=descending)
        for position in (9, 7, 8, 6):
            report_slide(position, DONE)
        report_slide(5, FIXING)
        report_slide(4, FIXING)
        report_slide(3, REVIEWING)
        snap = progress.snapshot()

    assert snap == {
        "seq": 8,
        "phase": "building",
        "slides": _slides(
            total=10, building=[0, 1, 2], reviewing=[3], fixing=[4, 5], done=[6, 7, 8, 9]
        ),
    }
    assert set(snap) == {"seq", "phase", "slides"}
    assert set(snap["slides"]) == {"total"} | {s.value for s in SlideProgressStage}
    # Plain JSON scalars on the wire, not enum members that happen to compare equal.
    assert type(snap["seq"]) is int
    assert type(snap["phase"]) is str
    assert type(snap["slides"]["total"]) is int
    lists = [snap["slides"][stage] for stage in _STAGE_KEYS]
    for positions in lists:
        assert all(type(p) is int for p in positions)
        assert positions == sorted(set(positions)), positions  # ascending, no repeats
    for i, left in enumerate(lists):
        for right in lists[i + 1 :]:
            assert not set(left) & set(right), (left, right)
    assert json.loads(json.dumps(snap)) == snap
    # What was published is what the tracker holds.
    assert _drain_progress(emitter)[-1] == snap


def test_the_ts_stream_event_declares_the_turn_progress_field():
    """The client reads ``event.turn_progress``; the field must be on the TS interface.

    Read as text (TS types are erased at runtime), like the slide_ready field pin in
    test_slide_release.py.  ``tsc`` alone does not hold it: test files are excluded
    from the app build, so dropping the field together with its import compiles.
    """
    source = _FRONTEND_API_TS.read_text()
    assert "import type { TurnProgress } from '../types/turnProgress';" in source
    interface = source.split("export interface StreamEvent {", 1)[1].split("}", 1)[0]
    assert "turn_progress?: TurnProgress | null;" in interface, (
        "the StreamEvent interface no longer declares turn_progress"
    )


# ---------------------------------------------------------------------------
# merge rules
# ---------------------------------------------------------------------------


def test_the_phase_rank_never_decreases(emitter):
    with turn_progress_scope() as progress:
        assert report_phase(TurnPhase.BUILDING) is True
        assert [s["phase"] for s in _drain_progress(emitter)] == ["building"]

        for late in (TurnPhase.PLANNING, TurnPhase.GATHERING_DATA, TurnPhase.CHECKING_SLIDES):
            assert report_phase(late) is False, late
        assert _drain(emitter) == []
        assert progress.snapshot()["seq"] == 1
        assert progress.snapshot()["phase"] == "building"

        assert report_phase(TurnPhase.REVIEWING_DECK) is True
        assert [(s["seq"], s["phase"]) for s in _drain_progress(emitter)] == [(2, "reviewing_deck")]

        for late in (TurnPhase.BUILDING, TurnPhase.PLANNING):
            assert report_phase(late) is False, late
        assert _drain(emitter) == []
        snap = progress.snapshot()

    assert snap["seq"] == 2
    assert snap["phase"] == "reviewing_deck"


def test_planning_rank_phases_alternate_freely(emitter):
    # ask_data -> data_analyst -> architect loops, and the architect checks the
    # committed slides on a brief change: all rank 0, all allowed to follow each other.
    order = (
        TurnPhase.PLANNING,
        TurnPhase.GATHERING_DATA,
        TurnPhase.PLANNING,
        TurnPhase.CHECKING_SLIDES,
    )
    with turn_progress_scope():
        results = [report_phase(phase) for phase in order]

    assert results == [True, True, True, True]
    assert [(s["seq"], s["phase"]) for s in _drain_progress(emitter)] == [
        (1, "planning"),
        (2, "gathering_data"),
        (3, "planning"),
        (4, "checking_slides"),
    ]


def test_a_slide_stage_never_regresses(emitter):
    with turn_progress_scope() as progress:
        assert report_slide(0, DONE) is True
        assert report_slide(1, FIXING) is True
        assert len(_drain(emitter)) == 2

        assert report_slide(0, REVIEWING) is False
        assert report_slide(0, BUILDING) is False
        assert report_slide(1, BUILDING) is False
        assert report_slide(1, REVIEWING) is False
        assert report_slides([0, 1], BUILDING) is False
        assert _drain(emitter) == []
        snap = progress.snapshot()

    assert snap["seq"] == 2
    assert snap["slides"] == _slides(total=2, fixing=[1], done=[0])


def test_stages_may_skip_forward(emitter):
    with turn_progress_scope() as progress:
        assert report_slide(0, BUILDING) is True
        assert report_slide(0, DONE) is True  # a placeheld builder: building -> done
        assert report_slide(1, REVIEWING) is True  # first report need not be building
        assert report_slide(1, DONE) is True
        final = progress.snapshot()

    snaps = _drain_progress(emitter)
    assert [s["seq"] for s in snaps] == [1, 2, 3, 4]
    assert snaps[0]["slides"] == _slides(total=1, building=[0])
    assert snaps[1]["slides"] == _slides(total=1, done=[0])
    assert snaps[2]["slides"] == _slides(total=2, reviewing=[1], done=[0])
    assert final["slides"] == _slides(total=2, done=[0, 1])


def test_a_repeated_report_publishes_nothing(emitter, fake_sm):
    set_chat_request_id("req-1")

    with turn_progress_scope() as progress:
        assert report_slide(0, REVIEWING) is True
        assert report_slide(0, REVIEWING) is False
        assert report_slides([0], REVIEWING) is False
        # The slide report already made the phase building and covered slide 0.
        assert report_phase(TurnPhase.BUILDING, covered=[0]) is False
        assert progress.snapshot()["seq"] == 1

    assert [s["seq"] for s in _drain_progress(emitter)] == [1]
    assert [seq for _, seq, _ in fake_sm.calls] == [1]  # no heartbeat write either

    with turn_progress_scope() as progress:
        assert report_phase(TurnPhase.PLANNING) is True
        assert report_phase(TurnPhase.PLANNING) is False
        assert progress.snapshot()["seq"] == 1

    assert [(s["seq"], s["phase"]) for s in _drain_progress(emitter)] == [(1, "planning")]
    assert [seq for _, seq, _ in fake_sm.calls] == [1, 1]


def test_covered_only_grows_and_total_counts_unreported_slides(emitter):
    with turn_progress_scope() as progress:
        assert report_phase(TurnPhase.BUILDING, covered=[0, 1, 2, 3, 4], dispatched=[0, 1]) is True
        first = progress.snapshot()
        assert first["phase"] == "building"
        assert first["slides"] == _slides(total=5, building=[0, 1])

        # A later wake passes only the still-outstanding subset: nothing shrinks.
        assert report_phase(TurnPhase.BUILDING, covered=[3, 4], dispatched=[3, 4]) is True
        assert progress.snapshot()["slides"] == _slides(total=5, building=[0, 1, 3, 4])

        # A staged position nobody declared covered still counts.
        assert report_slide(7, REVIEWING) is True
        assert progress.snapshot()["slides"] == _slides(
            total=6, building=[0, 1, 3, 4], reviewing=[7]
        )

        # Coverage alone is a change, and counts.
        assert report_phase(TurnPhase.BUILDING, covered=[8]) is True
        assert progress.snapshot()["slides"]["total"] == 7

    assert [s["slides"]["total"] for s in _drain_progress(emitter)] == [5, 5, 6, 7]


def test_a_slide_report_raises_the_phase_to_building_and_no_further(emitter):
    # From no phase at all.
    with turn_progress_scope() as progress:
        assert report_slide(0, BUILDING) is True
        assert progress.snapshot()["phase"] == "building"
    _drain(emitter)

    with turn_progress_scope() as progress:
        assert report_phase(TurnPhase.PLANNING) is True
        assert report_slide(0, BUILDING) is True
        assert progress.snapshot()["phase"] == "building"

        assert report_phase(TurnPhase.REVIEWING_DECK) is True
        assert report_slide(0, DONE) is True
        final = progress.snapshot()

    # The slide change and the phase raise are ONE snapshot, not two.
    assert [(s["seq"], s["phase"]) for s in _drain_progress(emitter)] == [
        (1, "planning"),
        (2, "building"),
        (3, "reviewing_deck"),
        (4, "reviewing_deck"),
    ]
    assert final["phase"] == "reviewing_deck"
    assert final["slides"] == _slides(total=1, done=[0])


# ---------------------------------------------------------------------------
# report_slides
# ---------------------------------------------------------------------------


def test_report_slides_publishes_one_snapshot_for_many_slides(emitter, fake_sm):
    set_chat_request_id("req-1")

    with turn_progress_scope():
        assert report_slides([0, 1, 2], DONE) is True

    snaps = _drain_progress(emitter)
    assert len(snaps) == 1
    assert snaps[0]["seq"] == 1
    assert snaps[0]["phase"] == "building"
    assert snaps[0]["slides"] == _slides(total=3, done=[0, 1, 2])
    assert len(fake_sm.calls) == 1
    assert fake_sm.calls[0] == ("req-1", 1, snaps[0])


def test_report_slides_with_no_positions_publishes_nothing(emitter, fake_sm):
    set_chat_request_id("req-1")

    with turn_progress_scope() as progress:
        assert report_slides([], DONE) is False
        assert report_slides(iter(()), DONE) is False
        assert progress.snapshot() == {"seq": 0, "phase": None, "slides": _slides()}

    assert _drain(emitter) == []
    assert fake_sm.calls == []


# ---------------------------------------------------------------------------
# concurrency and lock discipline
# ---------------------------------------------------------------------------


def test_concurrent_reports_reach_the_queue_in_seq_order_and_never_regress(emitter, fake_sm):
    set_chat_request_id("req-stress")
    positions = list(range(15))
    barrier = threading.Barrier(len(positions), timeout=5)
    errors: list = []

    def walk(position: int) -> None:
        try:
            rng = random.Random(position)
            barrier.wait()
            stages = [BUILDING, REVIEWING] + ([FIXING] if position % 3 == 0 else []) + [DONE]
            for stage in stages:
                report_slide(position, stage)
                time.sleep(rng.uniform(0, 0.002))
        except BaseException as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    def regress() -> None:
        # Late, stale REVIEWING reports racing the walkers: none may move a slide back.
        try:
            rng = random.Random(1000)
            for _ in range(3):
                for position in positions:
                    time.sleep(rng.uniform(0, 0.002))
                    report_slide(position, REVIEWING)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    with turn_progress_scope() as progress:
        threads = [_start(walk, p) for p in positions] + [_start(regress)]
        for thread in threads:
            thread.join(timeout=10)
        assert not [t for t in threads if t.is_alive()], "a reporting thread is stuck"
        final = progress.snapshot()

    assert errors == []
    snaps = _drain_progress(emitter)
    # Every slide makes at least reviewing + done (+ fixing): the order checks below
    # run over a real interleaving, not an empty or trivial stream.
    assert len(snaps) >= 2 * len(positions)
    assert [s["seq"] for s in snaps] == list(range(1, len(snaps) + 1))

    previous_ranks: Dict[int, int] = {}
    previous_done = previous_total = 0
    for snap in snaps:
        assert snap["phase"] == "building"
        ranks = _ranks(snap)
        for position, rank in previous_ranks.items():
            assert ranks.get(position, 0) >= rank, (position, previous_ranks, snap)
        assert len(snap["slides"]["done"]) >= previous_done
        assert snap["slides"]["total"] >= previous_total
        previous_ranks = ranks
        previous_done = len(snap["slides"]["done"])
        previous_total = snap["slides"]["total"]

    assert snaps[-1] == final
    assert final["slides"] == _slides(total=15, done=positions)

    # Every published snapshot was written exactly once, under this request, and
    # the write carried that snapshot (commit ORDER is free: persist is unlocked).
    by_seq = {s["seq"]: s for s in snaps}
    assert sorted(seq for _, seq, _ in fake_sm.calls) == list(range(1, len(snaps) + 1))
    for request_id, seq, snapshot in fake_sm.calls:
        assert request_id == "req-stress"
        assert snapshot == by_seq[seq]


def test_queue_order_is_seq_order_even_when_an_emit_is_slow(emitter, monkeypatch):
    """A's emit of seq 1 stalls; B's report must still queue AFTER it.

    With the emit inside the lock, B cannot even take a seq until A has queued, so
    the queue reads [1, 2].  With the emit moved after the ``with``, B takes seq 2,
    queues it, and A's stalled seq 1 lands behind it: [2, 1].
    """
    real_emit = progress_module.emit_event
    a_in_emit = threading.Event()
    b_done = threading.Event()

    def slow_first_emit(event):
        if (event.turn_progress or {}).get("seq") == 1:
            a_in_emit.set()
            b_done.wait(timeout=0.3)  # bounded: B can never set it while A holds the lock
        return real_emit(event)

    monkeypatch.setattr(progress_module, "emit_event", slow_first_emit)
    results: Dict[str, bool] = {}

    def run_a() -> None:
        results["a"] = report_slide(0, BUILDING)

    def run_b() -> None:
        results["b"] = report_slide(1, BUILDING)
        b_done.set()

    with turn_progress_scope():
        a = _start(run_a)
        b = None
        try:
            assert a_in_emit.wait(timeout=_WAIT_S), "A never reached its emit"
            b = _start(run_b)
            b.join(timeout=_WAIT_S)
            a.join(timeout=_WAIT_S)
            assert not a.is_alive() and not b.is_alive()
        finally:
            b_done.set()
            a.join(timeout=_WAIT_S)
            if b is not None:
                b.join(timeout=_WAIT_S)

    assert results == {"a": True, "b": True}
    assert [(s["seq"], s["slides"]["building"]) for s in _drain_progress(emitter)] == [
        (1, [0]),
        (2, [0, 1]),
    ]


def test_a_slow_persist_does_not_block_another_slides_report(emitter, monkeypatch):
    """A's write of seq 1 hangs; B's report must complete regardless.

    With ``_persist`` outside the lock, A holds nothing while it writes, so B takes
    the lock, queues seq 2 and returns.  With ``_persist`` inside the ``with``, B
    waits on the lock for as long as A's write hangs.
    """
    set_chat_request_id("req-1")
    a_in_persist = threading.Event()
    release_a = threading.Event()

    def block_the_first_write(_request_id, seq, _snapshot) -> None:
        if seq == 1:
            a_in_persist.set()
            release_a.wait(timeout=5)  # bounded: the finally below releases it early

    fake = _install(monkeypatch, _RecordingSessionManager(on_record=block_the_first_write))
    results: Dict[str, bool] = {}

    def run(name: str, position: int) -> None:
        results[name] = report_slide(position, BUILDING)

    with turn_progress_scope():
        a = _start(run, "a", 0)
        b = None
        try:
            assert a_in_persist.wait(timeout=_WAIT_S), "A never reached its write"
            b = _start(run, "b", 1)
            b.join(timeout=_WAIT_S)
            assert not b.is_alive(), "B waited on A's write: the persist runs under the lock"
            assert a.is_alive(), "A should still be inside its write"
            assert results == {"b": True}
            assert [s["seq"] for s in _drain_progress(emitter)] == [1, 2]
        finally:
            release_a.set()
            a.join(timeout=_WAIT_S)
            if b is not None:
                b.join(timeout=_WAIT_S)

    assert not a.is_alive()
    assert results == {"a": True, "b": True}
    assert sorted((rid, seq) for rid, seq, _ in fake.calls) == [("req-1", 1), ("req-1", 2)]


# ---------------------------------------------------------------------------
# persist sink
# ---------------------------------------------------------------------------


def test_persist_receives_each_snapshot_with_its_seq(emitter, fake_sm):
    set_chat_request_id("req-1")

    with turn_progress_scope():
        assert report_slide(0, BUILDING) is True
        assert report_slide(0, REVIEWING) is True

    snap1, snap2 = _drain_progress(emitter)
    assert fake_sm.calls == [("req-1", 1, snap1), ("req-1", 2, snap2)]
    assert [type(seq) for _, seq, _ in fake_sm.calls] == [int, int]
    assert snap1["slides"]["building"] == [0]
    assert snap2["slides"]["reviewing"] == [0]


def test_persist_is_skipped_without_a_request_id(emitter, fake_sm):
    # The autouse fixture left the request id None: the SSE path and the sweeper.
    with turn_progress_scope():
        assert report_slide(0, BUILDING) is True

    assert fake_sm.calls == []
    assert [s["seq"] for s in _drain_progress(emitter)] == [1]


def test_a_failing_persist_is_logged_and_never_raises(emitter, monkeypatch, caplog):
    set_chat_request_id("req-1")

    def database_down(_request_id, _seq, _snapshot) -> None:
        raise RuntimeError("database is down")

    fake = _install(monkeypatch, _RecordingSessionManager(on_record=database_down))

    with caplog.at_level(logging.WARNING, logger="src.services.graph.progress"):
        with turn_progress_scope():
            # True, not False: the failure is absorbed by the persist sink itself,
            # not by the report wrapper giving up on the whole report.
            assert report_slide(0, BUILDING) is True
            assert report_slide(0, REVIEWING) is True

    assert [seq for _, seq, _ in fake.calls] == [1, 2]
    assert [s["seq"] for s in _drain_progress(emitter)] == [1, 2]
    warnings = [
        r
        for r in caplog.records
        if r.name == "src.services.graph.progress" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 2, [r.getMessage() for r in caplog.records]
    for record in warnings:
        assert "persist" in record.getMessage().lower()
        assert record.exc_info is not None and record.exc_info[0] is RuntimeError


# ---------------------------------------------------------------------------
# the report wrappers never raise
# ---------------------------------------------------------------------------


def test_a_raising_tracker_never_escapes_any_report_wrapper(emitter, monkeypatch, caplog):
    """Fire-and-forget at the wrapper: a tracker that raises is logged, never raised.

    Each of the three wrappers needs its own ``try`` — the deck-level proof
    (test_turn_progress_graph.py) never reaches ``report_slides`` unless a slide
    stalls, so this pins all three directly.
    """
    attempts: List[Dict[str, Any]] = []

    def exploding_report(self, **kwargs):
        attempts.append(kwargs)
        raise RuntimeError("the progress tracker exploded")

    monkeypatch.setattr(progress_module.TurnProgress, "report", exploding_report)

    with caplog.at_level(logging.WARNING, logger="src.services.graph.progress"):
        with turn_progress_scope():
            assert report_phase(TurnPhase.BUILDING, covered=[0], dispatched=[0]) is False
            assert report_slide(0, REVIEWING) is False
            assert report_slides([0, 1], DONE) is False

    # Entry: every call really reached the broken tracker.
    assert len(attempts) == 3, attempts
    assert _drain(emitter) == []
    warnings = [
        r
        for r in caplog.records
        if r.name == "src.services.graph.progress" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 3, [r.getMessage() for r in caplog.records]
    for record in warnings:
        assert record.exc_info is not None and record.exc_info[0] is RuntimeError


def test_junk_reports_inside_a_scope_are_dropped_and_never_raise(emitter, fake_sm):
    set_chat_request_id("req-1")

    with turn_progress_scope() as progress:
        assert report_phase("not-a-phase") is False
        assert report_phase(TurnPhase.BUILDING, dispatched=["x"]) is False
        assert report_slide("x", BUILDING) is False
        assert report_slide(0, "not-a-stage") is False
        assert report_slides(["x"], DONE) is False
        assert report_slides([0], "not-a-stage") is False
        assert progress.snapshot() == {"seq": 0, "phase": None, "slides": _slides()}

    assert _drain(emitter) == []
    assert fake_sm.calls == []


# ---------------------------------------------------------------------------
# scope lifetime
# ---------------------------------------------------------------------------


def test_a_scope_installs_a_fresh_tracker_that_copied_contexts_share_and_removes_it_on_exit(
    emitter,
):
    assert get_turn_progress() is None

    with turn_progress_scope() as progress:
        assert get_turn_progress() is progress
        assert progress.snapshot()["seq"] == 0
        # A copied context — what LangGraph hands every task — reports into the
        # SAME tracker the parent sees.
        assert contextvars.copy_context().run(report_slide, 0, BUILDING) is True
        assert get_turn_progress().snapshot()["seq"] == 1
        assert get_turn_progress().snapshot()["slides"]["building"] == [0]

    assert get_turn_progress() is None
    assert turn_progress_var.get() is None
    # Nothing after the scope can report into the finished turn.
    assert report_slide(1, BUILDING) is False
    assert progress.snapshot()["seq"] == 1

    class _BoomError(Exception):
        pass

    with pytest.raises(_BoomError):
        with turn_progress_scope() as failed:
            assert get_turn_progress() is failed
            raise _BoomError()
    assert get_turn_progress() is None
    assert report_slide(2, BUILDING) is False

    with turn_progress_scope() as first:
        assert first.snapshot()["seq"] == 0
        assert report_slide(0, DONE) is True
    with turn_progress_scope() as second:
        assert second is not first
        assert second is not progress
        assert second.snapshot() == {"seq": 0, "phase": None, "slides": _slides()}
    assert first.snapshot()["seq"] == 1
    assert get_turn_progress() is None

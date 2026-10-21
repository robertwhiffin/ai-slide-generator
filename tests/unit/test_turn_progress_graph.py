"""#319 — the graph reports its stages, proved on compiled-graph turns.

``test_turn_progress.py`` pins the tracker on its own.  This suite pins that the
REAL nodes report into it at the right moments (D18), through the compiled
graph, against a real file-backed database — so every stage below is one a
user's placeholder would actually have shown:

* a whole build turn walks ``planning -> building -> reviewing_deck`` and each
  slide walks its own ``building -> reviewing -> [fixing] -> done``;
* three concurrent interleavings, each held open on a barrier or a bounded poll
  so the snapshot is taken while the slides really are in flight — including a
  slide that is waiting for one of the five fix slots, which already reads
  ``fixing``;
* every pipeline return reports ``done`` (a failed builder, a transient review
  failure, the normal end), and a tracker that raises never costs a deck;
* the other turn shapes (discuss, a data request, an edit, a deck-level brief
  change, placeheld stalls) and the ``chat_requests`` row the poll reads.

The harness runs ``graph.invoke`` directly (``test_slide_pipeline._run``) inside
its own ``with turn_progress_scope() as progress:`` and reads the tracker or
drains the queue before the block exits: ``invoke_graph``'s scope removes the
tracker when the invoke ends (D19), so nothing can be read off it afterwards.
``invoke_graph``'s own scope is pinned in ``test_graph_builder.py``.

Every wait is bounded, so a sabotaged report fails these tests instead of
hanging them.
"""

from __future__ import annotations

import contextvars
import json
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import pytest
from sqlalchemy import text

from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import get_session_manager
from src.api.services.slide_repository import is_placeholder_record
from src.domain.skill_io import AnalystOutput, ArchitectOutput
from src.services.foreman_service import CAP
from src.services.graph import nodes
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter
from src.services.graph.progress import (
    SlideProgressStage,
    get_turn_progress,
    turn_progress_scope,
    turn_progress_var,
)
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — fixtures
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    graph_env_threadsafe,
    make_spec,
    review_out,
)
from tests.unit.test_deck_level_spec_change import (
    _audience_changed,
    _run_architect,
    _seed_rows,
    brief_aware_reviewer,
)
from tests.unit.test_deck_level_spec_change import _persist as _persist_spec
from tests.unit.test_graph_nodes import _edit_out, _revised
from tests.unit.test_slide_pipeline import BARRIER_TIMEOUT_S, _run, _transient, _wire

#: A slide's stages in pipeline order, written out independently of the
#: module's enum so a renamed or reordered stage cannot also be the yardstick.
STAGES = ("building", "reviewing", "fixing", "done")

#: How long the fix-slot test's fixers hold their slots.  Deliberately LONGER
#: than the test's own poll (``BARRIER_TIMEOUT_S``): if the fixers gave their
#: slots back first, the waiting slide would enter its fix round and read
#: ``fixing`` for the wrong reason, and the sabotage could pass by luck.
FIXER_HOLD_S = 3 * BARRIER_TIMEOUT_S


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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _drain(q: queue.Queue) -> list:
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


def _progress_events(events) -> list:
    return [e for e in events if e.type is StreamEventType.TURN_PROGRESS]


def _snapshots(events) -> List[Dict[str, Any]]:
    return [e.turn_progress for e in _progress_events(events)]


def _dedupe(values) -> list:
    out: list = []
    for value in values:
        if not out or out[-1] != value:
            out.append(value)
    return out


def _stage_of(snapshot: Dict[str, Any], position: int) -> Optional[str]:
    for stage in STAGES:
        if position in snapshot["slides"][stage]:
            return stage
    return None


def _history(snapshots, position: int) -> List[str]:
    """One position's deduplicated stage across the snapshots, in queue order."""
    return _dedupe(
        stage
        for stage in (_stage_of(snap, position) for snap in snapshots)
        if stage is not None
    )


def _phases(snapshots) -> List[str]:
    return _dedupe(snap["phase"] for snap in snapshots)


def _wait_until(predicate: Callable[[], bool], timeout: float = BARRIER_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _run_turn(env):
    """One compiled-graph turn inside a scope: (every queued event, the final snapshot)."""
    q: queue.Queue = queue.Queue()
    set_event_emitter(q)
    with turn_progress_scope() as progress:
        _run(env)
        events = _drain(q)
        final = progress.snapshot()
    return events, final


def _record_phase_during(env, skill: str, seen: Dict[str, List[Optional[str]]]) -> None:
    """Wrap *skill*'s handler so it records the turn's phase as its model is called.

    The model call is most of a planning, data or deck-review stage, so the phase
    the placeholder shows DURING it is the one that matters.
    """
    inner = env.skills._handlers[skill]

    def handler(payload):
        seen.setdefault(skill, []).append(get_turn_progress().snapshot()["phase"])
        return inner(payload) if callable(inner) else inner

    env.skills.set(skill, handler)


def _empty_slides(total: int, **lists) -> Dict[str, Any]:
    slides: Dict[str, Any] = {"total": total}
    for stage in STAGES:
        slides[stage] = list(lists.get(stage, []))
    return slides


# ---------------------------------------------------------------------------
# A full build turn
# ---------------------------------------------------------------------------


class TestABuildTurn:
    def test_a_build_turn_walks_planning_building_reviewing_deck_in_order(
        self, graph_env_threadsafe
    ):
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(1,))

        events, final = _run_turn(env)

        progress_events = _progress_events(events)
        snaps = _snapshots(events)
        assert snaps, "the turn reported no stage at all"
        assert [s["seq"] for s in snaps] == list(range(1, len(snaps) + 1)), (
            "seq must rise by exactly 1 per published snapshot, in queue order"
        )
        assert _phases(snaps) == ["planning", "building", "reviewing_deck"]
        assert snaps[-1] == final
        assert final["phase"] == "reviewing_deck"
        assert final["slides"] == _empty_slides(3, done=[0, 1, 2])
        assert all(e.metadata == {"node": "progress"} for e in progress_events)
        assert len(env.skills.calls_for("deck_reviewer")) == 1

    def test_each_slide_walks_its_real_stages(self, graph_env_threadsafe):
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(1,))

        events, _ = _run_turn(env)

        snaps = _snapshots(events)
        assert _history(snaps, 0) == ["building", "reviewing", "done"]
        assert _history(snaps, 1) == ["building", "reviewing", "fixing", "done"]
        assert _history(snaps, 2) == ["building", "reviewing", "done"]
        # Entry: slide 1 really was the one fixed.
        assert [c["payload"]["position"] for c in env.skills.calls_for("fixer")] == [1]

    def test_a_deck_bigger_than_one_batch_counts_its_queued_slides(
        self, graph_env_threadsafe
    ):
        """D18: the foreman reports every COVERED position, not just its batch, so
        the total (the "(D of T done)" suffix) is the deck's size from the first
        batch on, while a queued slide is counted but not named."""
        env = graph_env_threadsafe
        positions = tuple(range(CAP + 1))
        _wire(env, positions)

        events, final = _run_turn(env)

        building = [s for s in _snapshots(events) if s["phase"] == "building"]
        assert building, "the turn never reported building"
        first = building[0]
        assert first["slides"]["total"] == CAP + 1
        assert first["slides"]["building"] == list(range(CAP))
        assert _stage_of(first, CAP) is None, "a queued slide was named"
        assert final["slides"] == _empty_slides(CAP + 1, done=list(positions))


# ---------------------------------------------------------------------------
# Concurrent interleavings: the summary is true WHILE slides are in flight
# ---------------------------------------------------------------------------


class TestConcurrentSlides:
    def test_three_slides_build_at_once_and_the_summary_says_so(
        self, graph_env_threadsafe
    ):
        """The barrier opens only once all three builders are running; its action
        reads the tracker at that instant, from inside a fanned task."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2))
        captured: Dict[str, Any] = {}

        def capture():
            captured["snapshot"] = get_turn_progress().snapshot()

        barrier = threading.Barrier(3, action=capture, timeout=BARRIER_TIMEOUT_S)

        def builder(payload):
            barrier.wait()
            return builder_out(payload)

        env.skills.set("builder", builder)

        _run_turn(env)

        assert "snapshot" in captured, (
            "the three builders never met at the barrier (or no tracker was "
            "visible inside the fanned task)"
        )
        snap = captured["snapshot"]
        assert snap["phase"] == "building"
        assert snap["slides"] == _empty_slides(3, building=[0, 1, 2])

    def test_three_slides_review_at_once_and_the_summary_says_so(
        self, graph_env_threadsafe
    ):
        """The same, held at the build reviewer: every draft is written and all
        three slides are under review together."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2))
        captured: Dict[str, Any] = {}

        def capture():
            captured["snapshot"] = get_turn_progress().snapshot()

        barrier = threading.Barrier(3, action=capture, timeout=BARRIER_TIMEOUT_S)

        def reviewer(payload):
            barrier.wait()
            return review_out(payload["position"])

        env.skills.set("build_reviewer", reviewer)

        _run_turn(env)

        assert "snapshot" in captured, (
            "the three build reviews never met at the barrier (or no tracker was "
            "visible inside the fanned task)"
        )
        snap = captured["snapshot"]
        assert snap["phase"] == "building"
        assert snap["slides"] == _empty_slides(3, reviewing=[0, 1, 2])

    def test_a_finished_slide_and_a_building_slide_coexist_truthfully(
        self, graph_env_threadsafe
    ):
        """Slide 1's builder cannot return until slide 0 reads done, so the
        capture is a moment where one slide is finished and the other building."""
        env = graph_env_threadsafe
        _wire(env, (0, 1))
        captured: Dict[str, Any] = {}

        def builder(payload):
            if payload["position"] == 1:
                tracker = get_turn_progress()
                if not _wait_until(lambda: 0 in tracker.snapshot()["slides"]["done"]):
                    raise RuntimeError("slide 0 never read done while slide 1 built")
                captured["snapshot"] = tracker.snapshot()
            return builder_out(payload)

        env.skills.set("builder", builder)

        _run_turn(env)

        assert "snapshot" in captured, (
            "slide 1's builder never saw slide 0 reach done (or no tracker was "
            "visible inside the fanned task)"
        )
        snap = captured["snapshot"]
        assert snap["phase"] == "building"
        assert snap["slides"] == _empty_slides(2, building=[1], done=[0])

    def test_a_slide_waiting_for_a_fix_slot_already_reads_fixing(
        self, graph_env_threadsafe
    ):
        """Six flagged slides, five fix slots, every fixer held.

        Once five fixers are running, the sixth slide is in its fix round but
        waiting for a slot.  It must already read ``fixing`` (D18): a FIXING
        report made only once the slot is acquired leaves it reading
        ``reviewing`` for as long as the other five hold their slots.
        """
        env = graph_env_threadsafe
        positions = tuple(range(6))
        _wire(env, positions, flagged=positions)
        assert nodes.FIX_CONCURRENCY == 5
        release = threading.Event()

        def fixer(payload):
            release.wait(timeout=FIXER_HOLD_S)
            return fixer_out(payload)

        env.skills.set("fixer", fixer)
        q: queue.Queue = queue.Queue()
        set_event_emitter(q)
        outcome: Dict[str, Any] = {}

        with turn_progress_scope() as progress:

            def turn():
                # This turn's own five slots, exactly as invoke_graph gives it.
                nodes.reset_fix_slots()
                try:
                    _run(env)
                except BaseException as exc:  # surfaced in the test thread below
                    outcome["error"] = exc

            # A copy of THIS context, so the turn's tasks share the scope's tracker.
            runner = threading.Thread(
                target=contextvars.copy_context().run, args=(turn,), daemon=True
            )
            runner.start()
            try:
                five_fixing = _wait_until(
                    lambda: len(env.skills.calls_for("fixer")) >= 5
                )
                all_read_fixing = five_fixing and _wait_until(
                    lambda: progress.snapshot()["slides"]["fixing"] == list(positions)
                )
                held = progress.snapshot()
                in_fixer = sorted(
                    c["payload"]["position"] for c in env.skills.calls_for("fixer")
                )
            finally:
                release.set()
                runner.join(timeout=4 * BARRIER_TIMEOUT_S)
            assert not runner.is_alive(), "the turn did not finish after the release"
            final = progress.snapshot()

        assert "error" not in outcome, outcome.get("error")
        assert five_fixing, "five fixers never ran at once"
        waiting = sorted(set(positions) - set(in_fixer))
        assert len(in_fixer) == 5 and len(waiting) == 1, (
            f"expected five slides in the fixer and one waiting for a slot; "
            f"in the fixer: {in_fixer}"
        )
        assert all_read_fixing, (
            f"slide {waiting[0]} was waiting for a fix slot and read "
            f"{_stage_of(held, waiting[0])!r}, not 'fixing': {held}"
        )
        assert held["slides"] == _empty_slides(6, fixing=list(positions))
        assert final["slides"]["done"] == list(positions)
        assert len(env.skills.calls_for("fixer")) == 6


# ---------------------------------------------------------------------------
# Failure paths: every pipeline return reports done, and progress never fails a deck
# ---------------------------------------------------------------------------


class TestFailurePaths:
    def test_a_failed_builder_goes_straight_to_done(self, graph_env_threadsafe):
        """C1: the shape of ``test_slide_pipeline``'s failed-builder test.  The
        builder's model raises, ``builder_node`` placeholds and carries no record,
        so the pipeline ends at its FIRST return."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(0, 2))

        def builder(payload):
            if payload["position"] == 1:
                raise RuntimeError("model exploded")
            return builder_out(payload)

        env.skills.set("builder", builder)

        events, final = _run_turn(env)

        snaps = _snapshots(events)
        rows = {r.position: r for r in env.rows()}
        assert is_placeholder_record(json.loads(rows[1].verification_record))
        assert _history(snaps, 1) == ["building", "done"]
        assert final["slides"]["done"] == [0, 1, 2]

    def test_a_transient_review_failure_keeps_the_draft_and_reaches_done(
        self, graph_env_threadsafe
    ):
        """The pipeline's SECOND return: the review's transient fault keeps the
        unreviewed draft and the slide is finished."""
        env = graph_env_threadsafe
        _wire(env, (0, 1))
        clean = env.skills._handlers["build_reviewer"]
        env.skills.set(
            "build_reviewer",
            lambda p: _transient("opus")(p) if p["position"] == 1 else clean(p),
        )

        events, final = _run_turn(env)

        rows = {r.position: r for r in env.rows()}
        assert rows[1].html == "<div class='slide'>slide 1</div>"
        assert rows[1].verification_record in (None, "", "{}", "null")
        snaps = _snapshots(events)
        assert _history(snaps, 1) == ["building", "reviewing", "done"]
        assert final["slides"]["done"] == [0, 1]

    def test_a_raising_progress_tracker_never_fails_a_deck(
        self, graph_env_threadsafe, monkeypatch
    ):
        """Fire-and-forget at deck level: every report reaches a tracker that
        raises, and the deck is built, reviewed, fixed and deck-reviewed anyway."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(1,))
        attempts: List[Dict[str, Any]] = []

        def exploding_report(self, **kwargs):
            attempts.append(kwargs)
            raise RuntimeError("the progress tracker exploded")

        monkeypatch.setattr(
            "src.services.graph.progress.TurnProgress.report", exploding_report
        )
        set_event_emitter(queue.Queue())

        with turn_progress_scope():
            _run(env)

        # Entry: the reports really reached the broken tracker — the phase
        # reports AND the pipeline's per-slide reports — or this proves nothing.
        assert any(a.get("phase") is not None for a in attempts), attempts
        assert any(
            SlideProgressStage.REVIEWING in (a.get("stages") or {}).values()
            for a in attempts
        ), "no per-slide report reached the tracker"
        rows = env.rows()
        assert sorted(r.position for r in rows) == [0, 1, 2]
        assert all(r.verification_record for r in rows), "a slide was never reviewed"
        assert {r.position: r.html for r in rows}[1] == "<div class='slide'>fixed 1</div>"
        assert len(env.skills.calls_for("deck_reviewer")) == 1


# ---------------------------------------------------------------------------
# Other turn shapes
# ---------------------------------------------------------------------------


class TestOtherTurnShapes:
    def test_a_discuss_turn_reports_planning_only(self, graph_env_threadsafe):
        env = graph_env_threadsafe
        env.skills.set(
            "architect", ArchitectOutput(intent="discuss", message="Let's talk.")
        )

        events, _ = _run_turn(env)

        snaps = _snapshots(events)
        assert len(snaps) == 1, snaps
        assert snaps[0]["phase"] == "planning"
        assert snaps[0]["slides"]["total"] == 0
        assert env.skills.calls_for("builder") == []

    def test_a_data_request_turn_gathers_between_two_planning_passes(
        self, graph_env_threadsafe
    ):
        """D11/D18: and each phase is reported at its node's ENTRY, so it is the
        label for that node's whole model call, not only for the moment after it."""
        env = graph_env_threadsafe
        _wire(env, (0, 1))
        architect_calls = {"n": 0}

        def architect(payload):
            architect_calls["n"] += 1
            if architect_calls["n"] == 1:
                return ArchitectOutput(
                    intent="ask_data",
                    message="Fetching the numbers.",
                    data_request={"metric": "weekly active users"},
                )
            return architect_build(make_spec((0, 1)))

        env.skills.set("architect", architect)
        env.skills.set(
            "data_analyst",
            AnalystOutput(
                outcome="success", synthesis="WAU is 1.2m.", sources=["genie:wau"]
            ),
        )
        phase_in_model_call: Dict[str, List[Optional[str]]] = {}
        for skill in ("architect", "data_analyst", "deck_reviewer"):
            _record_phase_during(env, skill, phase_in_model_call)

        events, final = _run_turn(env)

        assert len(env.skills.calls_for("data_analyst")) == 1
        assert _phases(_snapshots(events)) == [
            "planning",
            "gathering_data",
            "planning",
            "building",
            "reviewing_deck",
        ]
        assert final["slides"]["done"] == [0, 1]
        # A report made after the model call returns would leave the stage
        # mislabelled for almost all of it: "Generating slides..." while the
        # architect first plans, "Planning the deck…" while the data is fetched,
        # "Finishing the slides…" while the narrative is reviewed.
        assert phase_in_model_call == {
            "architect": ["planning", "planning"],
            "data_analyst": ["gathering_data"],
            "deck_reviewer": ["reviewing_deck"],
        }

    def test_an_edit_turn_counts_only_its_targets(self, graph_env_threadsafe):
        """D9: the edit's coverage is its target, so editing slide 2 (position 1)
        reads "Building slide 2…", never "Building 3 slides…"."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2))
        env.seed_slides(
            [
                "<div class='slide'>a</div>",
                "<div class='slide'>b</div>",
                "<div class='slide'>c</div>",
            ]
        )
        _persist_spec(env, make_spec((0, 1, 2)))
        env.skills.set(
            "architect",
            _edit_out(_revised(make_spec((0, 1, 2)), {1: "three stat cards"}), [1]),
        )

        events, final = _run_turn(env)

        # Entry: the turn really was an edit of slide 1 alone.
        assert [c["payload"]["position"] for c in env.skills.calls_for("builder")] == [1]
        building = [s for s in _snapshots(events) if s["phase"] == "building"]
        assert building, "the edit never reported building"
        assert building[0]["slides"]["total"] == 1
        assert building[0]["slides"]["building"] == [1]
        assert final["phase"] == "reviewing_deck"
        assert final["slides"] == _empty_slides(1, done=[1])

    def test_a_deck_level_brief_change_reports_checking_the_slides(self, graph_env):
        """D12: the architect re-reviews every committed slide against a new
        audience, serially, and the placeholder says so for the whole pass."""
        env = graph_env
        _persist_spec(env, make_spec(positions=(0, 1, 2)))
        _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
        review = brief_aware_reviewer({2})
        phase_during_review: List[Optional[str]] = []

        def reviewer(payload):
            phase_during_review.append(get_turn_progress().snapshot()["phase"])
            return review(payload)

        env.skills.set("build_reviewer", reviewer)
        q: queue.Queue = queue.Queue()

        with turn_progress_scope():
            updates = _run_architect(env, _audience_changed(), emitter=q)
            snaps = _snapshots(_drain(q))

        # Entry: the re-review really ran, over every committed slide.
        assert updates["target_positions"] == [2]
        assert phase_during_review == ["checking_slides"] * 3
        assert _phases(snaps) == ["planning", "checking_slides"]

    def test_placeheld_stalled_positions_are_done_in_one_snapshot(
        self, graph_env, monkeypatch
    ):
        """D4: one snapshot and one row write for the whole placeheld set."""
        env = graph_env
        turn = "turn-1"
        monkeypatch.setattr(
            nodes, "_placehold_failed_position", lambda position, **kw: True
        )
        writes: List[tuple] = []

        class _RecordingManager:
            def record_chat_request_progress(self, request_id, seq, progress):
                writes.append((request_id, seq))
                return True

        monkeypatch.setattr(
            "src.services.graph.progress.get_session_manager",
            lambda: _RecordingManager(),
        )
        set_chat_request_id("req-placeholder")
        state = env.state(
            turn_id=turn,
            deck_spec=make_spec((0, 1)),
            foreman_wakes=scoped(turn, [[0, 1], []]),
            dispatched_at=scoped(turn, {0: time.time(), 1: time.time()}),
        )
        q: queue.Queue = queue.Queue()
        set_event_emitter(q)

        with turn_progress_scope():
            updates = nodes.placeholder_node(state)
            events = _progress_events(_drain(q))

        assert updates["placeheld_positions"] == scoped(turn, {0, 1})
        assert len(events) == 1, [e.turn_progress for e in events]
        assert events[0].turn_progress["slides"]["done"] == [0, 1]
        assert writes == [("req-placeholder", 1)]

    def test_a_stalled_position_that_could_not_be_placeheld_is_not_reported_done(
        self, graph_env, monkeypatch
    ):
        """Only what ``placeholder_node`` actually placeheld is done: a position
        with no usable row is not finished, so it must not read as one."""
        env = graph_env
        turn = "turn-1"
        monkeypatch.setattr(
            nodes, "_placehold_failed_position", lambda position, **kw: position == 0
        )
        state = env.state(
            turn_id=turn,
            deck_spec=make_spec((0, 1)),
            foreman_wakes=scoped(turn, [[0, 1], []]),
            dispatched_at=scoped(turn, {0: time.time(), 1: time.time()}),
        )
        q: queue.Queue = queue.Queue()
        set_event_emitter(q)

        with turn_progress_scope() as progress:
            updates = nodes.placeholder_node(state)
            final = progress.snapshot()

        assert updates["placeheld_positions"] == scoped(turn, {0})
        assert final["slides"]["done"] == [0]
        assert _stage_of(final, 1) is None


# ---------------------------------------------------------------------------
# The chat_requests row the poll reads
# ---------------------------------------------------------------------------


class TestTheRequestRow:
    def test_the_turns_stage_lands_on_its_chat_request_row(self, graph_env_threadsafe):
        """The state that survives the turn, on the row every worker's poll reads."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2))
        rid = get_session_manager().create_chat_request(env.session_id)
        set_chat_request_id(rid)

        events, _ = _run_turn(env)

        snaps = _snapshots(events)
        assert snaps, "the turn reported no stage at all"
        last = snaps[-1]
        assert last["phase"] == "reviewing_deck"
        assert last["slides"]["done"] == [0, 1, 2]
        assert get_session_manager().get_chat_request(rid)["turn_progress"] == last
        with env.engine.connect() as conn:
            stored_seq = conn.execute(
                text("SELECT progress_seq FROM chat_requests WHERE request_id = :r"),
                {"r": rid},
            ).scalar_one()
        assert stored_seq == last["seq"]

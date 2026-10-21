"""The graph turn's stage summary, for the chat placeholder (#319).

One ``TurnProgress`` per turn, installed by ``invoke_graph`` through
:func:`turn_progress_scope` for exactly the duration of ``graph.invoke``.  It is
set BEFORE the invoke for the same reason the fix slots are: LangGraph copies
the calling context into every task and a copy shares the OBJECT, so the
architect, the foreman and every concurrent ``slide_pipeline_node`` report into
one tracker.  A ``ContextVar.set()`` inside a node would die with that node's
context copy (see ``event_emitter.advance_slide_cursor``), which is why the
tracker is created once per turn and never replaced inside it.  Unlike the fix
slots it does NOT outlive the turn: the scope resets the var with its token in a
``finally``, so a caller that runs ``invoke_graph`` in its own context — every
test does — is left with no tracker, and nothing after the invoke can report.

Monotonic, precisely
--------------------
* ``phase`` has a rank: planning, gathering_data and checking_slides share rank 0
  (the architect and the analyst may alternate in one turn), building is 1,
  reviewing_deck is 2.  A report whose rank is LOWER than the current one is
  ignored.
* Each slide's stage has a rank: building 1 < reviewing 2 < fixing 3 < done 4.  A
  report applies only when its rank is HIGHER; stages may be skipped forward.
* An applied slide report raises the phase to building if it is below that.
* ``covered`` only grows; ``total`` counts every covered or staged position.
* ``seq`` rises by one per report that changed something; a no-op report
  publishes nothing (no heartbeats — the label is never timer-driven).

Two sinks, and why each is ordered as it is
-------------------------------------------
* SSE: the event is queued INSIDE the lock, so the queue carries snapshots in
  strictly increasing ``seq`` order (``Queue.put`` on the unbounded queue never
  blocks).
* Polling: the snapshot is written to the turn's ``chat_requests`` row OUTSIDE
  the lock, by ``SessionManager.record_chat_request_progress``'s conditional
  UPDATE, so commits may land in any order and the row still never goes
  backwards.  A write never blocks another slide on the tracker lock; it blocks
  only its own thread, and on PostgreSQL for at most ``lock_timeout`` (2 s) on
  the row lock.  The poll reads that row, so every worker process serves the
  same stage.

With no tracker (outside ``invoke_graph``: a layer-1 test calling a node
directly, the monolith) every report is a no-op.  Nothing here raises: progress
is a side channel, never a precondition for building a deck.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import get_session_manager
from src.services.graph.event_emitter import emit_event, get_chat_request_id

logger = logging.getLogger(__name__)


# The two enums are read as TEXT by
# frontend/src/utils/turnProgress.conformance.test.ts: keep each class body to
# `NAME = "value"` lines only — no docstring, no blank line inside the class.
class TurnPhase(str, Enum):
    PLANNING = "planning"
    GATHERING_DATA = "gathering_data"
    CHECKING_SLIDES = "checking_slides"
    BUILDING = "building"
    REVIEWING_DECK = "reviewing_deck"


class SlideProgressStage(str, Enum):
    BUILDING = "building"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    DONE = "done"


PHASE_RANK: Dict[TurnPhase, int] = {
    TurnPhase.PLANNING: 0,
    TurnPhase.GATHERING_DATA: 0,
    TurnPhase.CHECKING_SLIDES: 0,
    TurnPhase.BUILDING: 1,
    TurnPhase.REVIEWING_DECK: 2,
}

STAGE_RANK: Dict[SlideProgressStage, int] = {
    SlideProgressStage.BUILDING: 1,
    SlideProgressStage.REVIEWING: 2,
    SlideProgressStage.FIXING: 3,
    SlideProgressStage.DONE: 4,
}


class TurnProgress:
    """One turn's stage summary.  Thread-safe; every merge is monotonic."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._phase: Optional[TurnPhase] = None
        self._covered: set = set()
        self._stages: Dict[int, SlideProgressStage] = {}

    def report(
        self,
        *,
        phase: Optional[TurnPhase] = None,
        covered: Iterable[int] = (),
        stages: Optional[Mapping[int, SlideProgressStage]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Merge one report; publish and return the new snapshot, or None if nothing changed."""
        with self._lock:
            changed = False
            if phase is not None:
                phase = TurnPhase(phase)
                if phase != self._phase and (
                    self._phase is None or PHASE_RANK[phase] >= PHASE_RANK[self._phase]
                ):
                    self._phase = phase
                    changed = True
            for position in covered:
                position = int(position)
                if position not in self._covered:
                    self._covered.add(position)
                    changed = True
            stage_applied = False
            for position, stage in (stages or {}).items():
                position, stage = int(position), SlideProgressStage(stage)
                current = self._stages.get(position)
                if current is None or STAGE_RANK[stage] > STAGE_RANK[current]:
                    self._stages[position] = stage
                    stage_applied = True
                if position not in self._covered:
                    self._covered.add(position)
                    changed = True
            if stage_applied:
                changed = True
                if self._phase is None or PHASE_RANK[self._phase] < PHASE_RANK[TurnPhase.BUILDING]:
                    self._phase = TurnPhase.BUILDING
            if not changed:
                return None
            self._seq += 1
            snapshot = self._snapshot_locked()
            # INSIDE the lock: the SSE queue then carries snapshots in seq order.
            emit_event(
                StreamEvent(
                    type=StreamEventType.TURN_PROGRESS,
                    turn_progress=snapshot,
                    metadata={"node": "progress"},
                )
            )
        # OUTSIDE the lock: a slow or failing write must not stall another slide.
        _persist(snapshot)
        return snapshot

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> Dict[str, Any]:
        slides: Dict[str, Any] = {"total": len(self._covered)}
        for stage in SlideProgressStage:
            slides[stage.value] = sorted(
                position for position, current in self._stages.items() if current == stage
            )
        return {
            "seq": self._seq,
            "phase": self._phase.value if self._phase is not None else None,
            "slides": slides,
        }


#: This turn's tracker — set only inside ``turn_progress_scope()`` (i.e. inside
#: ``invoke_graph``'s invoke); ``None`` everywhere else.
turn_progress_var: ContextVar[Optional[TurnProgress]] = ContextVar(
    "graph_turn_progress", default=None
)


@contextmanager
def turn_progress_scope() -> Iterator[TurnProgress]:
    """Install a fresh tracker for the ``with`` block, then remove it, success or failure.

    Enter it in the context that then calls ``graph.invoke``: LangGraph copies that
    context into every task, and a copy shares the object.  Never enter it inside a
    node — a set there would fork the tracker per task.
    """
    progress = TurnProgress()
    token = turn_progress_var.set(progress)
    try:
        yield progress
    finally:
        turn_progress_var.reset(token)


def get_turn_progress() -> Optional[TurnProgress]:
    return turn_progress_var.get()


def report_phase(
    phase: TurnPhase,
    *,
    covered: Iterable[int] = (),
    dispatched: Iterable[int] = (),
) -> bool:
    """Report a turn phase (and, for building, the covered and dispatched slides).  Never raises."""
    try:
        progress = turn_progress_var.get()
        if progress is None:
            return False
        stages = {int(p): SlideProgressStage.BUILDING for p in dispatched}
        return progress.report(phase=phase, covered=covered, stages=stages) is not None
    except Exception:
        logger.warning("Turn progress could not be recorded; continuing", exc_info=True)
        return False


def report_slide(position: int, stage: SlideProgressStage) -> bool:
    """Report one slide's stage.  Never raises."""
    try:
        progress = turn_progress_var.get()
        if progress is None:
            return False
        return progress.report(stages={int(position): stage}) is not None
    except Exception:
        logger.warning("Turn progress could not be recorded; continuing", exc_info=True)
        return False


def report_slides(positions: Iterable[int], stage: SlideProgressStage) -> bool:
    """Report several slides reaching one stage as ONE snapshot and one write.  Never raises."""
    try:
        progress = turn_progress_var.get()
        if progress is None:
            return False
        stages = {int(p): stage for p in positions}
        if not stages:
            return False
        return progress.report(stages=stages) is not None
    except Exception:
        logger.warning("Turn progress could not be recorded; continuing", exc_info=True)
        return False


def _persist(snapshot: Dict[str, Any]) -> None:
    """Write *snapshot* to this turn's chat request, when there is one.  Never raises."""
    request_id = get_chat_request_id()
    if not request_id:
        return  # the SSE path and the sweeper have no request row
    try:
        get_session_manager().record_chat_request_progress(
            request_id, int(snapshot["seq"]), snapshot
        )
    except Exception:
        logger.warning(
            "Could not persist turn progress; polling clients keep the previous stage",
            exc_info=True,
        )

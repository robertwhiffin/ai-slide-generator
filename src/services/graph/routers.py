"""Conditional-edge routers.

Four rules, each measured, and each one has produced a real defect:

1. **A router takes ``(state)`` or ``(state, config)`` only.**  An extra
   positional parameter raises ``TypeError`` at invoke time, and the config
   parameter must be **named** ``config``.
2. **``Send`` objects are RETURNED from a router**, never written into state.
3. **A router must never read a payload key off state.**  A router hanging off a
   ``Send``-reached node sees PLAIN STATE, once per branch — measured: six
   invocations for six builders, every one with the declared state keys and no
   payload key, so ``state["position"]`` raises ``KeyError``.  Each invocation
   sees only its own branch's write (``slides`` keys ``[0]``, then ``[1]``, …
   never the merged ``[0..5]``), which is precisely what lets the re-fan router
   rebuild each reviewer's payload from ``slides[position]``.
4. **One conditional-edge set per node.**  A static ``add_edge`` alongside
   conditional edges from the same node gives duplicate conflicting edges and a
   ``GraphRecursionError``.

There is deliberately **no ``reviewer_router``**: ``build_reviewer -> foreman``
is a static edge, measured clean.  See ``builder.py`` for the measurements.
"""

from __future__ import annotations

import logging
import time
from typing import List, Union

from langgraph.graph import END
from langgraph.types import Send

from src.services.foreman_service import all_positions_committed, stalled_positions
from src.services.graph.nodes import build_branch_payload
from src.services.graph.state import has_pending_fix, scoped_vals

logger = logging.getLogger(__name__)

#: Every ``ArchitectIntent`` maps to exactly one destination.  ``discuss`` and
#: ``confirm_design_contract`` both END the turn: a confirmation WAITS for the
#: user, so nothing may restyle before they answer.
_INTENT_ROUTES = {
    "discuss": END,
    "ask_data": "data_analyst",
    "build": "foreman",
    "edit": "foreman",
    "confirm_design_contract": END,
}


def architect_router(state: dict) -> str:
    """Route on ``architect_intent`` — the five declared intents, nothing else.

    An unknown or absent intent ends the turn rather than guessing: every intent
    ``ArchitectOutput`` can carry is in the map, so anything else means the
    architect never ran or its output was not parsed, and dispatching builders on
    that basis would spend money on an unknown request.
    """
    intent = state.get("architect_intent")
    destination = _INTENT_ROUTES.get(intent)
    if destination is None:
        logger.error(
            "architect_router saw an unroutable intent %r; ending the turn", intent
        )
        return END
    return destination


def foreman_router(state: dict) -> Union[str, List[Send]]:
    """Fan out the batch ``foreman_node`` decided, or follow its ladder.

    **This router calls ``next_dispatch_batch`` NOWHERE, and that is
    load-bearing** (Ruling C-1).  A conditional-edge router SEES the writes of
    the node it hangs off — measured::

        NODE sees marks = {}
        ROUTER sees marks = {'a': 1}

    So a router that recomputed the batch would run *after* ``foreman_node``
    stamped ``dispatched_at`` for the positions it just decided to dispatch.
    ``next_dispatch_batch`` excludes in-flight positions, every stamped position
    now reads as in-flight, the batch comes back ``[]``, the turn falls through
    to ``END`` — and **the graph builds nothing while every foreman unit test
    stays green.**  A reviewer finding ``next_dispatch_batch`` in this module
    should treat it as a defect.

    There is exactly one producer of the decision (the node) and this router only
    reads it back, out of the last ``foreman_wakes`` entry, so the two cannot
    disagree.

    The remaining limbs mirror the node's ladder and are safe to recompute
    because none of them depends on a write the node made *except* the empty
    wake, which is exactly what makes ``stalled_positions``' limb 1 fire on the
    positions a completed batch left behind.
    """
    wakes = scoped_vals(state, "foreman_wakes")
    batch = wakes[-1] if wakes else []
    if batch:
        return [Send("builder", build_branch_payload(state, p)) for p in batch]

    if has_pending_fix(state):
        return "fixer"
    if stalled_positions(state, time.time()):
        return "placeholder"
    if all_positions_committed(state):
        return "deck_reviewer"
    return END


def build_reviewer_refan_router(state: dict) -> Union[str, List[Send]]:
    """Re-fan one ``build_reviewer`` per built-but-unreviewed position.

    ``builder -> build_reviewer`` **must** be a conditional edge that re-fans.  A
    static edge collapses N branches into ONE invocation receiving plain state
    with no payload — measured: 3 builders produced 1 reviewer invocation — so
    ``payload["position"]`` raises ``KeyError``, there is one review per *batch*
    rather than per slide (breaking both the one-reviewer-writes-one-row
    invariant and the n-not-3n cost model), and the per-slide fix path never
    fires.

    Each invocation sees only its own branch's ``slides`` write, so this returns
    one ``Send`` per invocation and N invocations produce N reviewers.  The
    payload is the record the builder carried forward, which is the only way a
    ``Send``-reached reviewer can see anything at all.

    Positions already in ``reviewed_positions`` are skipped, so a resumed
    checkpoint cannot review the same slide twice.

    **A branch with nothing to review goes to ``placeholder``, NOT to
    ``foreman`` — this is a measured correction to the plan's edge list.**  The
    only way a builder branch has nothing to review is that it placeheld, and
    routing that branch straight to the foreman wakes the foreman **in the same
    superstep as its siblings' reviewers** — i.e. mid-batch, before those
    reviewers' writes land.  Measured on a three-slide turn with position 1's
    builder failing::

        SS3  builder x3                     (1 raises -> placeheld)
        SS4  build_reviewer(0), build_reviewer(2), foreman   <- mid-batch wake
        SS5  foreman (from the reviewers) -> deck_reviewer
             placeholder (from SS4's foreman) -> foreman
        SS6  deck_reviewer  #1   and  foreman -> deck_reviewer
        SS7  deck_reviewer  #2

    **The deck reviewer ran twice** — two deck-level writes, two ``deck_reviews``
    rows and two ``info`` messages for one turn.  Worse in principle: that
    mid-batch foreman appends an EMPTY wake, which erases the exclusion set
    ``stalled_positions``' limb 1 relies on, so it routes to the placeholder for
    positions whose reviewers are still running.  (No live slide is actually
    placeheld, because ``placeholder_node`` re-evaluates ``stalled_positions``
    one superstep later, when those writes have landed — which is exactly why
    the predicate lives in the node and not in the router's decision.)

    Routing to ``placeholder`` fixes both: the placeholder node runs in the
    reviewers' superstep, no-ops when nothing is stalled (the real wake list
    still excludes the live batch), and reaches the foreman through its own
    static edge — so the foreman wakes ONCE, after the barrier, however the
    branches split.  It also keeps the all-builders-failed case reaching deck
    review, which routing to ``END`` would not: the post-commit ``slide_count`` /
    ``html_content`` / ``scripts_content`` write would never happen and the deck
    would read as ``0 slides``, silently.
    """
    slides = scoped_vals(state, "slides")
    reviewed = scoped_vals(state, "reviewed_positions")
    sends = [
        Send("build_reviewer", dict(record))
        for position, record in sorted(slides.items())
        if record is not None and position not in reviewed
    ]
    return sends or "placeholder"


def fixer_router(state: dict) -> str:
    """Route the fixer's output to its reviewer, or back to the foreman.

    ``fix_target`` is the fixer's record of what it dispatched; ``None`` means it
    found no candidate (or its own fallback already landed the original), so
    there is nothing to review.
    """
    return "fix_reviewer" if state.get("fix_target") is not None else "foreman"

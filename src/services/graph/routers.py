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

There is deliberately **no router after a slide**: ``slide_pipeline ->
foreman`` is a static edge, so every pipeline in a batch reaches the foreman in
one superstep and it wakes once.  See ``builder.py``.
"""

from __future__ import annotations

import logging
import time
from typing import List, Union

from langgraph.graph import END
from langgraph.types import Send

from src.services.foreman_service import all_positions_committed, stalled_positions
from src.services.graph.nodes import build_branch_payload
from src.services.graph.state import scoped_vals

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

    # A describe-only turn may re-describe the deck but must not rebuild it.
    # ws4d's arc-review sweeper runs with no emitter and nobody watching, so a
    # "build" or "edit" intent here would dispatch builders whose reviewers
    # OVERWRITE the hand-edits that scheduled the review.  A post-hoc check
    # cannot help: invoke_graph is synchronous and the rows land before it
    # returns, so the only safe place is the edge that would dispatch them.
    #
    # Gated on the DESTINATION, not on the intent literal, so a sixth intent
    # added to _INTENT_ROUTES with "foreman" as its destination is covered the
    # day it lands rather than the day someone remembers this branch.
    #
    # The architect's own deck-level write has already happened by now, inside
    # the node: that is exactly what the sweeper wants (the re-described
    # deck_spec is persisted) and it touches no slide row.
    if destination == "foreman" and scoped_vals(state, "describe_only"):
        logger.info(
            "architect_router: describe-only turn, so intent %r ends the turn "
            "instead of dispatching builders",
            intent,
            extra={"session_id": state.get("session_id")},
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
        return [Send("slide_pipeline", build_branch_payload(state, p)) for p in batch]

    if stalled_positions(state, time.time()):
        return "placeholder"
    if all_positions_committed(state):
        return "deck_reviewer"
    return END

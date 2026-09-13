"""Turn-scoped state contract for the LangGraph deck-generation graph.

This module is the single source of truth for every key the graph reads and
writes.  Every key written by two or more concurrent branches MUST carry a
reducer; every single-writer key carries none.  The runtime silently drops
undeclared keys — ``GraphState`` is exhaustive.

Turn-scoping
------------
Most mutable keys are turn-scoped: each value is wrapped in
``{"turn": turn_id, "vals": value}``.  The reducers below discard the
accumulated value whenever the incoming ``turn_id`` differs from the stored one,
so turn 2 starts fresh even though the LangGraph checkpointer carries all of
turn 1's state forward.

``scoped_vals`` is the READ side of the same mechanism.  It checks the
wrapper's turn against ``state["turn_id"]`` BEFORE any reducer fires.  Without
that check, turn 2 reads turn 1's ``landed_positions``,
``next_dispatch_batch`` returns ``[]``, ``all_positions_committed`` is true,
and the graph goes straight to deck review having built NOTHING.

Tombstone hazard (``has_pending_fix``, ``stalled_positions``)
-------------------------------------------------------------
``turn_scoped_merge`` cannot delete a key: it can only set a value to ``None``
as a tombstone.  Two callers depend on this:

  ``has_pending_fix`` (implemented here) — must check for non-None values, not
  dict truthiness.  ``bool({0: None})`` is ``True``; routing on that loops the
  graph forever until ``GraphRecursionError``.

  ``stalled_positions`` (implemented in ``src/services/foreman_service.py``) —
  must skip ``None`` timestamps in ``dispatched_at`` for the same reason.  A
  dispatched position whose builder completed carries ``{position: None}``, not
  an absent key.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from src.domain.deck_spec import DeckSpec
from src.domain.finding import Finding


def scoped(turn_id: str, value: Any) -> dict:
    """Wrap a value with the turn it belongs to.

    Returns ``{"turn": turn_id, "vals": value}``.  Pass this to every
    turn-scoped key write; the three reducers below recognise the wrapper.
    """
    return {"turn": turn_id, "vals": value}


# Per-key empty values for every key read through scoped_vals.
# This is a CLOSED mapping, never a suffix heuristic.  A heuristic returning
# {} for anything not ending in "positions" would hand emitted_style_blocks'
# list reducer a dict — survivable only by accident (round-3 finding 24).
_EMPTY_FOR: dict[str, Any] = {
    "landed_positions":     set(),
    "placeheld_positions":  set(),
    "reviewed_positions":   set(),
    "slides":               {},
    "dispatched_at":        {},
    "fix_map":              {},
    "fixed":                {},
    "emitted_style_blocks": [],
    "foreman_wakes":        [],
}


def scoped_vals(state: dict, key: str) -> Any:
    """Read a turn-scoped key, discarding a value from a previous turn.

    The turn comparison is HERE, not only in the reducers.  Reducers fire on a
    WRITE, but every foreman read happens BEFORE any write in the turn — so
    without this check turn 2 reads turn 1's landed positions,
    ``next_dispatch_batch`` returns ``[]``, ``all_positions_committed`` is
    true, and the graph goes straight to deck review having built NOTHING.

    Raises ``KeyError`` for any key not in ``_EMPTY_FOR``.  An unknown key is
    a programmer error; silence here would hide it rather than surface it
    early.
    """
    empty = _EMPTY_FOR[key]  # KeyError for unregistered keys — intentional
    wrapper = (state or {}).get(key)
    if not isinstance(wrapper, dict):
        return empty
    if wrapper.get("turn") != (state or {}).get("turn_id"):
        return empty  # stale: value belongs to a previous turn
    return wrapper.get("vals", empty)


# ---------------------------------------------------------------------------
# Turn-scoped reducers
# ---------------------------------------------------------------------------

def turn_scoped_union(a: Any, b: Any) -> Any:
    """Merge two turn-scoped set wrappers; discard on a turn change.

    Within a turn: returns a wrapper whose vals is ``a_vals | b_vals``.
    On a turn change (b carries a different turn): discards a, returns b.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    if a.get("turn") != b.get("turn"):
        # New turn — discard the accumulated value; start fresh from b.
        return b
    return {
        "turn": b["turn"],
        "vals": (a.get("vals") or set()) | (b.get("vals") or set()),
    }


def turn_scoped_merge(a: Any, b: Any) -> Any:
    """Merge two turn-scoped dict wrappers; discard on a turn change.

    Within a turn: returns ``{**a_vals, **b_vals}``.
    On a turn change: discards a, returns b.

    Cannot delete a key — a completed entry is tombstoned as
    ``{key: None}``.  See the tombstone hazard note in the module docstring.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    if a.get("turn") != b.get("turn"):
        return b
    merged = dict(a.get("vals") or {})
    merged.update(b.get("vals") or {})
    return {"turn": b["turn"], "vals": merged}


def turn_scoped_concat(a: Any, b: Any) -> Any:
    """Merge two turn-scoped list wrappers; discard on a turn change.

    Within a turn: returns ``a_vals + b_vals``.
    On a turn change: discards a, returns b.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    if a.get("turn") != b.get("turn"):
        return b
    return {
        "turn": b["turn"],
        "vals": (a.get("vals") or []) + (b.get("vals") or []),
    }


# ---------------------------------------------------------------------------
# GraphState — the exhaustive contract
# ---------------------------------------------------------------------------

class GraphState(TypedDict, total=False):
    """Exhaustive state contract for the deck-generation LangGraph graph.

    Single-writer keys carry NO reducer (a reducer would silently merge where
    the semantics are "replace").  Fan-in keys (written by concurrent branches)
    MUST carry a reducer or the runtime raises
    ``InvalidUpdateError: At key 'x': Can receive only one value per step``.

    Undeclared keys returned by a node are silently dropped.  This is why this
    class is exhaustive: a key omitted here is invisible to every node that
    reads it, causing silent wrong-path behaviour rather than an error.
    """

    # -- single-writer keys (no reducer) ------------------------------------

    # Set once per session by invoke_graph.
    session_id: str

    # Set at the start of each turn by invoke_graph.
    turn_id: str

    # Set by invoke_graph from its principal argument or get_current_user().
    # Carried in state AND in build_branch_payload, so a fanned branch writes
    # an author without re-reading a ContextVar (row-write rule under C4).
    initiated_by: str

    # Set by architect_node when a fix turn is triggered.
    fix_target: Optional[int]

    # Set by architect_node; updated in-place on each architect pass.
    deck_spec: Optional[DeckSpec]

    # Set by architect_node; the human-readable intent narrative.
    architect_intent: Optional[str]

    # Written by architect_node AND data_analyst_node.
    # No reducer: the two never run in the same superstep.  The analyst returns
    # {"architect_message": out.synthesis} on a static edge back to the
    # architect; that is how the analyst's synthesis reaches the architect,
    # because GraphState declares no analyst-specific key and the runtime
    # silently drops undeclared ones.  (Ruling C-7, corrections §11.)
    architect_message: Optional[str]

    # Set by architect_node (target slide positions for this turn).
    target_positions: Optional[list[int]]

    # Set by architect_node from deck_spec.title — deterministic (ws4b B1.4).
    title: Optional[str]

    # Resolved brand bytes written once per turn by architect_node (C6/§L5).
    # These four keys are what build_branch_payload extracts section HTML from
    # and copies style prose out of; without them in state each builder would
    # re-resolve from the DB inside its own branch.
    token_css: Optional[str]
    deterministic_css: Optional[str]
    template_layout_html: Optional[str]
    resolved_style: Optional[str]

    # True when a design system resolved to compiled content this turn.
    # Written once by architect_node from resolve_style_source(...).design_system_active.
    # Single-writer, NO reducer.  Must be a plain bool (not a NamedTuple) because
    # GraphState crosses the SqlAlchemyCheckpointSaver on turn 2, and langgraph
    # warns on — and will eventually block — deserialising unregistered types
    # from checkpoint (Ruling C-21, corrections §46).  build_branch_payload
    # copies this scalar into the Send payload so fanned branches can call
    # call_skill / assemble_skill_prompt without touching the DB again.
    design_system_active: Optional[bool]

    # Set by architect_node; resolved deterministically before fan-out.
    # Chart.js CDN default and deck <meta> are known before any builder runs.
    external_scripts: Optional[list[str]]
    head_meta: Optional[str]

    # Set by deck_reviewer_node post-commit (derived from SlideDeck(...).scripts,
    # not read from state).
    scripts_content: Optional[str]

    # Set by deck_reviewer_node (from SlideDeck.knit(), post-commit).
    knitted_html: Optional[str]

    # Set by architect_node or exception handlers.
    error_state: Optional[dict]

    # -- fan-in keys (reducer required) ------------------------------------

    # Append-only log of review findings across ALL turns.
    # NOT turn-scoped: a finding is stamped with its id and persisted at the
    # moment its row is written, so the channel is an accumulation log rather
    # than turn state.  Turn 2 inherits turn 1's entries permanently (the
    # state-accumulation fact from runtime-facts.md).  No node may read
    # state["findings"] as *this turn's* findings: each reviewer node reads
    # only its own return value to persist.
    findings: Annotated[list[Finding], operator.add]

    # Turn-scoped set keys — positions committed, placeheld, or reviewed this turn.
    landed_positions: Annotated[Any, turn_scoped_union]
    placeheld_positions: Annotated[Any, turn_scoped_union]
    reviewed_positions: Annotated[Any, turn_scoped_union]

    # Turn-scoped dict keys — slide content, dispatch timestamps, fix state.
    # turn_scoped_merge CANNOT delete a key; completed entries are tombstoned
    # as {key: None}.  See the tombstone hazard note in the module docstring.
    slides: Annotated[Any, turn_scoped_merge]
    dispatched_at: Annotated[Any, turn_scoped_merge]
    fix_map: Annotated[Any, turn_scoped_merge]
    fixed: Annotated[Any, turn_scoped_merge]

    # Turn-scoped list keys — style blocks and foreman wake signals.
    # emitted_style_blocks: each element is a CSS text string, NEVER
    # <style>-wrapped markup (deck_css_aggregator silently drops wrapped blocks).
    emitted_style_blocks: Annotated[Any, turn_scoped_concat]
    foreman_wakes: Annotated[Any, turn_scoped_concat]


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def has_pending_fix(state: dict) -> bool:
    """Return True iff fix_map contains at least one non-tombstone entry.

    NEVER test ``bool(state.get("fix_map"))`` here.  ``turn_scoped_merge``
    cannot delete keys — a completed fix is tombstoned as ``{position: None}``.
    ``bool({0: None})`` is ``True``, which routes to the fixer forever, causing
    ``min()`` to raise ``ValueError`` on an empty candidate set and the graph
    to loop to ``GraphRecursionError``.
    """
    fix_map = scoped_vals(state, "fix_map")
    return any(v is not None for v in fix_map.values())

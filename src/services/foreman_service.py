"""Scheduling policy — pure functions over GraphState for the foreman node.

No class, no instance state.  The checkpointer is the only home for turn
state (PRD §12.1: a bare ``self.sessions = {}`` is this pattern under a
different name, and both have the same fatal flaw — the second worker
reading stale per-instance dicts while the checkpointer has current values).

Constants
---------
CAP = 15
    Maximum concurrent builder branches.  ``next_dispatch_batch`` never
    returns more than ``CAP - in_flight_count`` positions.

RELEASE_TIMEOUT_S = 300
    Elapsed-seconds threshold for limb 2 of ``stalled_positions``
    (the resumed-checkpoint case).

Turn coverage
-------------
An edit turn sets ``state["target_positions"]``; a build turn leaves it
``None``.  All five functions derive their covered position set from
``_covered_positions(state)``, which returns ``sorted(target_positions)``
for an edit turn and ``sorted(s.position for s in deck_spec.slides)`` for
a build turn.  If ``deck_spec`` is absent (before the architect runs),
``_covered_positions`` returns ``[]``.  If ``target_positions`` is an
empty list, the turn covers nothing — ``all_positions_committed`` is
vacuously True and ``next_dispatch_batch`` returns ``[]``.

In-flight predicate
-------------------
A position is *in-flight* when it has a non-``None`` entry in
``dispatched_at`` AND is neither in ``landed_positions`` nor
``placeheld_positions``.  This predicate is defined once, in
``_in_flight``, and used by ``next_dispatch_batch`` (both the counting
rule and the filtering rule) and by ``stalled_positions`` (the tombstone
guard).

``dispatched_at`` uses ``turn_scoped_merge``, which cannot delete a key:
a completed builder tombstones its entry as ``{position: None}``.
``_in_flight`` therefore checks ``ts is not None``, never ``ts`` alone.
An erroneous truthiness check (``if ts``) would treat ``None`` as
in-flight and either suppress a dispatchable position from the next batch
or falsely report it as stalled — the same failure mode documented in
``has_pending_fix``.

stalled_positions — two-limb predicate
---------------------------------------
C4 calls ``stalled_positions`` **after** it has appended an empty wake
entry for the current invocation, making ``foreman_wakes[-1] == []``.
That is what makes limb 1 fire on positions left over from a completed
batch.  This is C4's obligation, not this module's.

Limb 1 (no elapsed-time gate): a position is stalled immediately when it
has a non-``None`` ``dispatched_at`` entry, is NOT in the most recent
``foreman_wakes`` batch, and is neither landed nor placeheld.  Applies
only when ``foreman_wakes`` is non-empty.  The superstep barrier
guarantees every position outside the current batch has already completed
(all builders in that batch finished before the barrier released the
foreman wake), so elapsed time is irrelevant.  Gating limb 1 on the
timeout makes the whole branch unreachable in practice — the elapsed time
since a batch completed is always small, so the turn falls through to END
with slides missing, no placeholder, no error_state, and nothing in chat.

Limb 2 (elapsed-time gate, resumed-checkpoint case): a position has a
non-``None`` ``dispatched_at`` entry and there are NO wake records at all
in this turn (``foreman_wakes == []``).  A second worker on the same
thread_id may still be building that position (the timestamp predates this
process), so we wait for the full timeout before placeholding.

A landed or placeheld position is never stalled on either limb.

When ``foreman_wakes`` is empty, all dispatched positions fall to limb 2
(the "no wake at all" case IS limb 2, not limb 1 with an empty exclusion
set — the defensible reading documented in the brief).  When
``foreman_wakes`` is non-empty, positions in the most recent batch are
guarded (not stalled), and positions outside it are stalled immediately.
"""

from __future__ import annotations

from src.services.graph.state import scoped_vals

CAP: int = 15
RELEASE_TIMEOUT_S: float = 300


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _covered_positions(state: dict) -> list[int]:
    """Return all positions this turn covers, sorted ascending.

    Edit turn (``target_positions`` is not None): covers only
    ``state["target_positions"]``.

    Build turn (``target_positions`` is None): covers every position in
    ``deck_spec.slides``, identified by ``SlideSpec.position`` (NOT list
    index — the two diverge after a delete or a partial rebuild).

    Returns ``[]`` if neither a target list nor a deck_spec is available
    (e.g. before the architect node has committed the spec on the very
    first foreman wake of a session).
    """
    target = (state or {}).get("target_positions")
    if target is not None:
        # Edit turn: covers exactly target_positions (may be empty list).
        return sorted(target)
    deck_spec = (state or {}).get("deck_spec")
    if deck_spec is None:
        return []
    return sorted(s.position for s in deck_spec.slides)


def _in_flight(
    pos: int,
    dispatched_at: dict,
    landed: set,
    placeheld: set,
) -> bool:
    """True iff ``pos`` was dispatched this turn and has not yet committed.

    A non-``None`` timestamp means the position was dispatched and its
    builder has not yet written a result (landed or placeholder).  A
    ``None`` entry is a tombstone — the in-flight marker was explicitly
    cleared without committing (so the position is outstanding but
    dispatchable again in the next batch, e.g. after a builder failure
    that clears the marker).

    The check ``ts is not None`` is INTENTIONAL and LOAD-BEARING.  See the
    tombstone hazard note in the module docstring.  Using truthiness
    (``if ts``) treats ``None`` as in-flight and either suppresses a
    re-dispatchable position from the next batch or reports a false stall.
    """
    ts = dispatched_at.get(pos)
    return ts is not None and pos not in landed and pos not in placeheld


# ---------------------------------------------------------------------------
# Public scheduling functions
# ---------------------------------------------------------------------------

def outstanding_positions(state: dict) -> list[int]:
    """Positions not yet committed (neither landed nor placeheld), ascending.

    Includes in-flight positions.  This is the full outstanding set;
    ``next_dispatch_batch`` removes in-flight entries before forming the
    next dispatch batch.

    A placeholder counts as committed (§5.5, §I): ``placeheld_positions``
    is part of the committed set, not an exception to it.
    """
    covered = _covered_positions(state)
    landed = scoped_vals(state, "landed_positions")
    placeheld = scoped_vals(state, "placeheld_positions")
    committed = landed | placeheld
    return [p for p in covered if p not in committed]


def next_dispatch_batch(state: dict, cap: int = CAP) -> list[int]:
    """Next batch of positions to dispatch, ascending, within the cap.

    Three rules, and the failure behind each:

    1. **Ascending order is load-bearing, not tidiness.**
       ``releasable_positions`` requires all covered positions < n to be
       committed before n can be released.  Dispatching from the end would
       leave position 0 unstarted while every high position finished, and
       the user would see nothing while the buffer fills.

    2. **In-flight positions are never re-dispatched.**
       The foreman re-runs on a partially completed batch (some builders
       still running).  A batch derived from ``outstanding_positions``
       alone would re-dispatch the siblings still running — duplicating LLM
       spend and racing two writers onto the same slide row.

    3. **In-flight is subtracted from the cap.**
       The cap bounds *concurrent* builders.  Dispatching ``cap`` fresh
       positions while N are in-flight allows up to ``cap + N`` concurrent
       builders, silently exceeding the intended limit.
    """
    covered = _covered_positions(state)
    landed = scoped_vals(state, "landed_positions")
    placeheld = scoped_vals(state, "placeheld_positions")
    dispatched_at = scoped_vals(state, "dispatched_at")
    committed = landed | placeheld

    outstanding = [p for p in covered if p not in committed]

    # Rule 3: count in-flight to subtract from cap.
    in_flight_count = sum(
        1 for p in outstanding
        if _in_flight(p, dispatched_at, landed, placeheld)
    )
    available_slots = cap - in_flight_count
    if available_slots <= 0:
        return []

    # Rule 2: exclude in-flight from candidates.  Rule 1: outstanding is
    # already ascending, so the first available_slots entries are the
    # lowest outstanding non-in-flight positions.
    dispatchable = [
        p for p in outstanding
        if not _in_flight(p, dispatched_at, landed, placeheld)
    ]
    return dispatchable[:available_slots]


def releasable_positions(state: dict) -> list[int]:
    """Longest committed prefix of covered positions (ascending).

    A position is releasable iff it is committed (landed or placeheld) AND
    every lower covered position is also committed.  The first uncommitted
    covered position breaks the prefix; nothing after it is releasable.

    A placeholder counts as committed (§5.5, §I): ``placeheld_positions``
    is inside the committed set.  One terminal builder failure must not
    keep the prefix frozen forever — the deck must eventually reach review.
    """
    covered = _covered_positions(state)  # already ascending
    landed = scoped_vals(state, "landed_positions")
    placeheld = scoped_vals(state, "placeheld_positions")
    committed = landed | placeheld

    result = []
    for p in covered:
        if p in committed:
            result.append(p)
        else:
            break  # gap found — nothing past this point is releasable
    return result


def stalled_positions(
    state: dict,
    now: float,
    timeout_s: float = RELEASE_TIMEOUT_S,
) -> list[int]:
    """Positions stalled under the two-limb predicate.

    See the module docstring for the full rationale.  Summary:

    Limb 1 (immediate, no elapsed-time gate):
        ``has_wakes and pos not in most_recent_batch and pos in dispatched_at
        with non-None ts and pos not in committed``
        The superstep barrier guarantees completion of all prior batches,
        so elapsed time is IRRELEVANT.  Do NOT gate this limb on
        ``now - ts > timeout_s`` — that makes it unreachable in practice.

    Limb 2 (timeout-gated, resumed-checkpoint case):
        ``not has_wakes and pos in dispatched_at with non-None ts and
        pos not in committed and now - ts > timeout_s``
        A second worker may be live; wait for the full timeout.

    The ``_in_flight`` helper encapsulates the shared non-None + not-committed
    guard for both limbs (tombstone safety).
    """
    landed = scoped_vals(state, "landed_positions")
    placeheld = scoped_vals(state, "placeheld_positions")
    dispatched_at = scoped_vals(state, "dispatched_at")
    foreman_wakes = scoped_vals(state, "foreman_wakes")

    has_wakes = len(foreman_wakes) > 0
    # The most recent foreman_wakes entry is the batch C4 just dispatched
    # (or an empty batch if C4 found nothing to send).  Positions inside
    # this batch are still live; positions outside it are stalled.
    most_recent_batch: set[int] = set(foreman_wakes[-1]) if has_wakes else set()

    result: list[int] = []
    for pos, ts in dispatched_at.items():
        # _in_flight checks ts is not None AND not committed.
        if not _in_flight(pos, dispatched_at, landed, placeheld):
            # tombstone (ts is None) or already committed — never stalled
            continue

        if has_wakes:
            # Limb 1: outside the most recent batch → stalled immediately.
            if pos not in most_recent_batch:
                result.append(pos)
            # else: in the live batch — not stalled (barrier has not fired
            # for this batch yet, so the builder may still be running).
        else:
            # Limb 2: no wakes at all in this turn → timeout-gated.
            if now - ts > timeout_s:
                result.append(pos)

    return sorted(result)


def all_positions_committed(state: dict) -> bool:
    """True iff every covered position is landed or placeheld.

    A placeholder counts as committed (§5.5, §I), so a terminal builder
    failure does not strand the turn permanently.  ``len(landed) ==
    len(spec.slides)`` is the wrong predicate: one failure would mean deck
    review never fires and the turn never ends.

    Returns True vacuously for an empty covered set (no deck_spec yet, or
    an empty target_positions list in an edit turn).
    """
    covered = _covered_positions(state)
    if not covered:
        return True
    landed = scoped_vals(state, "landed_positions")
    placeheld = scoped_vals(state, "placeheld_positions")
    committed = landed | placeheld
    return all(p in committed for p in covered)

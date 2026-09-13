"""Unit tests for ``src/services/foreman_service.py``.

C2 owns the scheduling policy — five pure functions of GraphState, no class
and no instance state.  These tests pin the **policy**, and they pass whether
or not the wiring between these functions and C4 is correct; that is exactly
why C5 exists.

Test scope, matching the plan's test-intent list
-------------------------------------------------
outstanding_positions
  - includes in-flight positions
  - excludes landed and placeheld (both count as committed)
  - ascending order

next_dispatch_batch
  - first batch of a 31-slide deck is [0..14] (cap = 15)
  - a 15-slide deck dispatches entirely in one wake (the common case)
  - second batch continues ascending after some land
  - in-flight positions are excluded from candidates (duplicate-dispatch
    protection)
  - in-flight is subtracted from the cap (real-cap rule)
  - ascending re-entry: a low position with its in-flight marker cleared
    (tombstone ``None``) is dispatched ahead of higher unstarted positions
    (the property "retries need no special case"; no retry_count involved —
    Ruling C-14 deleted that key)
  - edit turn dispatches only target_positions

releasable_positions
  - emits only the committed prefix; stops at the first gap
  - extends when the gap position commits
  - a placeholder releases and counts as committed

stalled_positions
  - limb 1: dispatched position outside the most recent foreman_wakes batch
    is stalled at zero elapsed time (NO timeout check)
  - limb 1: position inside the most recent batch is NOT stalled at zero
    elapsed time (live-batch guard)
  - limb 2: dispatched position with no wakes at all is NOT stalled below
    timeout, stalled above it
  - a landed position is never stalled (on either limb)
  - a tombstone (dispatched_at entry == None) is never treated as in-flight
    or stalled

all_positions_committed
  - False while any covered position is outstanding
  - True when all are landed or placeheld
  - placeholder counts as committed (deck review gate must fire)
  - vacuously True for an empty spec

Sabotage targets (verified during development; output in the task report)
---------
  S1 (required by plan): remove the in-flight subtraction from
      ``next_dispatch_batch`` cap calculation →
      ``test_cap_counts_inflight`` and
      ``test_inflight_excluded_from_dispatch`` both go red.
  S2: gate limb 1 of ``stalled_positions`` on
      ``now - ts > timeout_s`` →
      ``TestStalledPositions::test_limb1_stalls_at_zero_elapsed_time``
      goes red.
  S3: remove the ``ts is not None`` guard in ``_in_flight`` (treat None as
      in-flight) →
      ``TestNextDispatchBatch::test_tombstone_treated_as_dispatchable``
      goes red.

Decisions this file settles
---------------------------
- ``target_positions = None`` → build turn; ``target_positions = [...]``
  (including an empty list) → edit turn covering those positions.
- Limb 1 fires only when ``foreman_wakes`` is non-empty.  When it is empty,
  ALL dispatched positions fall to limb 2 (timeout-gated).
- Tests model C4's contract: limb 1 scenarios pass a ``foreman_wakes``
  list whose last entry is ``[]`` (C4's empty wake recorded before calling
  ``stalled_positions``), not the previous batch.
"""

from __future__ import annotations

import pytest

from src.domain.deck_spec import (
    DeckSpec,
    DesignContractRef,
    ResolvedData,
    SlideSpec,
)
from src.services.foreman_service import (
    CAP,
    RELEASE_TIMEOUT_S,
    all_positions_committed,
    next_dispatch_batch,
    outstanding_positions,
    releasable_positions,
    stalled_positions,
)
from src.services.graph.state import scoped


# ---------------------------------------------------------------------------
# Test-state builder helpers
# ---------------------------------------------------------------------------

def _slide(position: int) -> SlideSpec:
    return SlideSpec(
        position=position,
        purpose="test",
        content_brief="test",
        assumes="test",
        hands_off="test",
        data_references=[],
    )


def _spec(positions: list[int]) -> DeckSpec:
    """Minimal DeckSpec with the given slide positions."""
    return DeckSpec(
        title="Test Deck",
        audience="test",
        purpose="test",
        argument="test",
        call_to_action="test",
        narrative_arc=["test"],
        design_contract=DesignContractRef(),
        resolved_data=ResolvedData(synthesis="test", figures=[], gaps=[]),
        slides=[_slide(p) for p in positions],
    )


def _state(
    *,
    turn_id: str = "t1",
    positions: list[int] | None = None,
    target_positions: list[int] | None = None,
    landed: set[int] | None = None,
    placeheld: set[int] | None = None,
    dispatched_at: dict[int, float | None] | None = None,
    foreman_wakes: list[list[int]] | None = None,
) -> dict:
    """Build a minimal GraphState dict for foreman_service tests.

    ``positions`` is the slide-position list for the deck_spec (build
    turn).  ``target_positions`` triggers an edit-turn path instead.
    Omitting both gives a state with no deck_spec and no target_positions,
    so covered positions = [].

    All per-key defaults match the empty values from ``_EMPTY_FOR``:
    sets → empty set, dicts → empty dict, lists → empty list.
    """
    state: dict = {"turn_id": turn_id}

    if target_positions is not None:
        # Edit turn: target_positions is set (even if empty list)
        state["target_positions"] = target_positions
    elif positions is not None:
        state["deck_spec"] = _spec(positions)
        # no target_positions key → build turn

    if landed:
        state["landed_positions"] = scoped(turn_id, set(landed))
    if placeheld:
        state["placeheld_positions"] = scoped(turn_id, set(placeheld))
    if dispatched_at is not None:
        state["dispatched_at"] = scoped(turn_id, dict(dispatched_at))
    if foreman_wakes is not None:
        state["foreman_wakes"] = scoped(turn_id, list(foreman_wakes))

    return state


# ---------------------------------------------------------------------------
# TestOutstandingPositions
# ---------------------------------------------------------------------------

class TestOutstandingPositions:
    """outstanding_positions returns covered - committed, ascending, with
    in-flight positions included."""

    def test_all_outstanding_when_nothing_committed(self):
        state = _state(positions=[0, 1, 2])
        assert outstanding_positions(state) == [0, 1, 2]

    def test_excludes_landed_positions(self):
        state = _state(positions=[0, 1, 2, 3], landed={0, 2})
        assert outstanding_positions(state) == [1, 3]

    def test_excludes_placeheld_positions(self):
        state = _state(positions=[0, 1, 2, 3], placeheld={1, 3})
        assert outstanding_positions(state) == [0, 2]

    def test_excludes_both_landed_and_placeheld(self):
        state = _state(positions=[0, 1, 2, 3, 4], landed={0, 2}, placeheld={4})
        assert outstanding_positions(state) == [1, 3]

    def test_includes_inflight_positions(self):
        """outstanding_positions INCLUDES in-flight; next_dispatch_batch
        excludes them — the distinction matters so both are tested.
        """
        # position 1 is dispatched (in-flight marker set) but not committed
        state = _state(
            positions=[0, 1, 2],
            dispatched_at={1: 1000.0},
        )
        assert outstanding_positions(state) == [0, 1, 2]

    def test_result_is_ascending(self):
        # Spec slides are given in non-ascending order;
        # outstanding_positions must sort them.
        state = _state(positions=[4, 1, 2, 0, 3], landed={1, 3})
        assert outstanding_positions(state) == [0, 2, 4]

    def test_empty_when_all_committed(self):
        state = _state(positions=[0, 1], landed={0}, placeheld={1})
        assert outstanding_positions(state) == []

    def test_empty_spec_returns_empty(self):
        state = _state()  # no positions, no target_positions
        assert outstanding_positions(state) == []


# ---------------------------------------------------------------------------
# TestNextDispatchBatch
# ---------------------------------------------------------------------------

class TestNextDispatchBatch:
    """next_dispatch_batch: ascending, in-flight excluded, in-flight subtracted
    from cap."""

    def test_first_batch_of_31_is_0_through_14(self):
        """First wake on a 31-slide deck fills to cap=15 starting from 0."""
        state = _state(positions=list(range(31)))
        batch = next_dispatch_batch(state)
        assert batch == list(range(15))

    def test_15_slide_deck_dispatches_entirely_in_one_wake(self):
        """A 15-slide deck fully dispatches in one go — the common fast path."""
        state = _state(positions=list(range(15)))
        batch = next_dispatch_batch(state)
        assert batch == list(range(15))

    def test_second_batch_continues_ascending_after_landing(self):
        """After positions 0-14 land, the next wake dispatches 15-29."""
        state = _state(
            positions=list(range(30)),
            landed=set(range(15)),
        )
        batch = next_dispatch_batch(state)
        assert batch == list(range(15, 30))

    def test_inflight_excluded_from_dispatch(self):
        """Positions already in-flight must never be re-dispatched.

        Without this guard, the foreman re-running on a partial batch would
        duplicate LLM spend and race two writers on the same slide row.
        """
        # positions 0-4 in-flight; 5-14 available
        state = _state(
            positions=list(range(20)),
            dispatched_at={p: 1000.0 for p in range(5)},
        )
        batch = next_dispatch_batch(state)
        # 5 in-flight, 15 cap → 10 slots; next 10 unstarted positions
        assert batch == list(range(5, 15))
        assert not any(p in batch for p in range(5)), (
            "in-flight positions must not appear in the next dispatch batch"
        )

    def test_cap_counts_inflight(self):
        """In-flight positions count against the cap.

        Dispatching cap fresh positions while N are in-flight allows up to
        cap + N concurrent builders — silently violating the limit.
        """
        # 10 in-flight; cap=15 → only 5 slots available
        state = _state(
            positions=list(range(30)),
            dispatched_at={p: 1000.0 for p in range(10)},
        )
        batch = next_dispatch_batch(state)
        assert len(batch) == 5, (
            f"With 10 in-flight and cap=15, only 5 slots remain; got {batch}"
        )
        assert batch == list(range(10, 15))

    def test_returns_empty_when_all_slots_occupied(self):
        """No dispatch when in-flight count equals cap."""
        state = _state(
            positions=list(range(20)),
            dispatched_at={p: 1000.0 for p in range(CAP)},
        )
        assert next_dispatch_batch(state) == []

    def test_ascending_reentry_dispatches_cleared_position_before_unstarted(self):
        """Ascending order re-enters a cleared (tombstoned) low position before
        higher unstarted positions — no retry_count needed.

        Retries need no special case beyond clearing the in-flight marker
        (``dispatched_at[pos] = None`` tombstone).  A failed position is
        still outstanding, so ascending order re-enters it ahead of higher
        unstarted positions by construction.  This test pins that property
        with a low position whose in-flight marker was cleared and higher
        unstarted positions behind it.
        """
        # position 0: outstanding, in-flight marker cleared (tombstone)
        # positions 3 and 7: unstarted (no dispatched_at entry)
        state = _state(
            positions=[0, 3, 7],
            dispatched_at={0: None},  # cleared marker
        )
        batch = next_dispatch_batch(state, cap=1)
        assert batch == [0], (
            "Position 0 with a cleared in-flight marker must appear before "
            "higher unstarted positions (ascending re-entry property)"
        )

    def test_tombstone_treated_as_dispatchable(self):
        """A tombstone (None) entry is NOT in-flight and IS dispatchable.

        Using truthiness (``if ts``) would treat None as in-flight, silently
        suppressing a re-enterable position from every subsequent batch.
        """
        # position 1: tombstone (not in-flight, dispatchable)
        # position 2: real timestamp (in-flight, NOT dispatchable)
        state = _state(
            positions=[0, 1, 2],
            landed={0},
            dispatched_at={1: None, 2: 1000.0},
        )
        # cap=2: 1 in-flight (pos 2) → 1 available slot → dispatches [1]
        batch = next_dispatch_batch(state, cap=2)
        assert batch == [1], (
            "Tombstone position 1 must be dispatchable; "
            "in-flight position 2 must be excluded"
        )

    def test_edit_turn_dispatches_only_target_positions(self):
        """An edit turn covers only target_positions, not the full deck."""
        # Full spec has 10 slides, but the edit targets only positions 3 and 7
        state = _state(
            positions=list(range(10)),  # deck_spec present but irrelevant
            target_positions=[3, 7],
        )
        # target_positions overrides deck_spec: only 3 and 7 are covered
        state["deck_spec"] = _spec(list(range(10)))
        batch = next_dispatch_batch(state)
        assert set(batch) == {3, 7}
        assert batch == [3, 7]

    def test_empty_spec_dispatches_nothing(self):
        """An empty covered set never dispatches anything."""
        state = _state()  # no deck_spec, no target_positions
        assert next_dispatch_batch(state) == []

    def test_partial_batch_when_few_outstanding(self):
        """When fewer than cap positions are outstanding, returns them all."""
        state = _state(positions=list(range(5)))
        batch = next_dispatch_batch(state)
        assert batch == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# TestReleasablePositions
# ---------------------------------------------------------------------------

class TestReleasablePositions:
    """releasable_positions: longest committed prefix, ascending."""

    def test_empty_when_nothing_committed(self):
        state = _state(positions=[0, 1, 2, 3])
        assert releasable_positions(state) == []

    def test_prefix_stops_at_first_gap(self):
        """Positions after the first uncommitted one are not yet releasable."""
        state = _state(positions=[0, 1, 2, 3, 4], landed={0, 1}, placeheld={})
        # Position 2 is not committed → prefix stops after 1
        assert releasable_positions(state) == [0, 1]

    def test_extends_when_gap_commits(self):
        """When the gap position commits, the prefix extends to the next gap."""
        state = _state(positions=[0, 1, 2, 3], landed={0, 1, 2, 3})
        assert releasable_positions(state) == [0, 1, 2, 3]

    def test_inner_gap_stops_prefix(self):
        """A gap at position 2 stops the prefix even if 3 and 4 are committed."""
        state = _state(positions=[0, 1, 2, 3, 4], landed={0, 1, 3, 4})
        assert releasable_positions(state) == [0, 1]

    def test_placeholder_releases_and_counts_as_committed(self):
        """A placeholder counts as committed — a terminal failure must not
        freeze the prefix or prevent deck review.
        """
        # position 1 is placeheld (placeholder), not landed
        state = _state(positions=[0, 1, 2], landed={0}, placeheld={1})
        # 0 landed, 1 placeheld → both committed; 2 outstanding → prefix [0,1]
        assert releasable_positions(state) == [0, 1]

    def test_all_committed_returns_all(self):
        state = _state(positions=[0, 1, 2], landed={0, 2}, placeheld={1})
        assert releasable_positions(state) == [0, 1, 2]

    def test_empty_spec_returns_empty(self):
        state = _state()
        assert releasable_positions(state) == []


# ---------------------------------------------------------------------------
# TestStalledPositions
# ---------------------------------------------------------------------------

class TestStalledPositions:
    """stalled_positions: two-limb predicate; limb 1 has NO elapsed-time gate."""

    # -----------
    # Limb 1 tests — requires has_wakes = True
    # -----------

    def test_limb1_stalls_at_zero_elapsed_time(self):
        """Dispatched position outside the most recent batch is stalled
        immediately — no timeout check.

        This is the critical property corrections §3 exists to preserve.
        C4 appends an empty wake BEFORE calling stalled_positions; the state
        here models that: foreman_wakes[-1] == [] (the current empty batch).
        Position 1 was in the PREVIOUS batch [0,1,2] but not in the current
        empty batch [], so limb 1 fires regardless of elapsed time.
        """
        state = _state(
            positions=[0, 1, 2],
            landed={0, 2},
            dispatched_at={1: 1_000_000.0},   # dispatched at t=1_000_000
            foreman_wakes=[[0, 1, 2], []],    # prev batch, then current empty
        )
        # Only 1 second has elapsed — far below timeout — but limb 1 fires
        result = stalled_positions(state, now=1_000_001.0)
        assert result == [1], (
            "Limb 1 must stall at zero elapsed time; gating on timeout makes "
            "this branch unreachable in practice (corrections §3)"
        )

    def test_limb1_does_not_stall_position_inside_most_recent_batch(self):
        """A position inside the most recent foreman_wakes batch is NOT stalled.

        The most recent batch contains live builders (their superstep is still
        running).  Stalling them would incorrectly placeholder a slide being
        written right now.
        """
        # Most recent batch [0,1,2] still live — position 1 is inside it
        state = _state(
            positions=[0, 1, 2],
            landed={0, 2},
            dispatched_at={1: 1_000_000.0},
            foreman_wakes=[[0, 1, 2]],   # most recent batch includes pos 1
        )
        result = stalled_positions(state, now=1_000_001.0)
        assert result == [], (
            "Position inside the most recent batch must not be stalled"
        )

    def test_limb1_stalls_position_outside_non_empty_batch(self):
        """With a non-empty most-recent batch, positions NOT in that batch are
        stalled immediately by limb 1."""
        # Batch was [2, 3]; position 0 was dispatched in an earlier batch
        state = _state(
            positions=[0, 1, 2, 3],
            landed={1},
            dispatched_at={0: 1_000_000.0, 2: 1_000_001.0, 3: 1_000_001.0},
            foreman_wakes=[[0, 1], [2, 3]],   # most recent = [2, 3]
        )
        result = stalled_positions(state, now=1_000_002.0)
        assert result == [0], (
            "Position 0 outside the most recent batch [2,3] must be stalled; "
            "2 and 3 are inside the live batch and must not be stalled"
        )

    # -----------
    # Limb 2 tests — requires has_wakes = False
    # -----------

    def test_limb2_not_stalled_below_timeout(self):
        """No wakes, dispatched_at present, elapsed time < timeout → not stalled."""
        state = _state(
            positions=[0],
            dispatched_at={0: 0.0},
            foreman_wakes=[],   # no wakes in this turn → limb 2
        )
        result = stalled_positions(state, now=100.0, timeout_s=RELEASE_TIMEOUT_S)
        assert result == [], (
            "Limb 2 must not stall below the timeout "
            f"(elapsed={100.0}, timeout={RELEASE_TIMEOUT_S})"
        )

    def test_limb2_stalled_above_timeout(self):
        """No wakes, dispatched_at present, elapsed time > timeout → stalled."""
        state = _state(
            positions=[0],
            dispatched_at={0: 0.0},
            foreman_wakes=[],
        )
        result = stalled_positions(state, now=RELEASE_TIMEOUT_S + 1.0)
        assert result == [0], (
            "Limb 2 must stall after the timeout elapses"
        )

    def test_limb2_custom_timeout(self):
        """timeout_s parameter is honoured on limb 2."""
        state = _state(
            positions=[0],
            dispatched_at={0: 0.0},
            foreman_wakes=[],
        )
        assert stalled_positions(state, now=60.0, timeout_s=30.0) == [0]
        assert stalled_positions(state, now=20.0, timeout_s=30.0) == []

    # -----------
    # Never-stalled invariants
    # -----------

    def test_landed_position_never_stalled(self):
        """A landed position is committed and must never appear as stalled,
        on either limb."""
        state = _state(
            positions=[0, 1],
            landed={0},
            dispatched_at={0: 1_000_000.0, 1: 1_000_000.0},
            foreman_wakes=[[0, 1], []],   # limb 1 scenario
        )
        result = stalled_positions(state, now=1_000_001.0)
        assert 0 not in result, "Landed position 0 must never be stalled"

    def test_placeheld_position_never_stalled(self):
        """A placeheld position is committed and must never appear as stalled."""
        state = _state(
            positions=[0, 1],
            placeheld={0},
            dispatched_at={0: 1_000_000.0, 1: 1_000_000.0},
            foreman_wakes=[[0, 1], []],
        )
        result = stalled_positions(state, now=1_000_001.0)
        assert 0 not in result, "Placeheld position 0 must never be stalled"

    def test_tombstone_never_stalled_or_treated_as_inflight(self):
        """A tombstone (None) entry in dispatched_at is NOT in-flight and
        must never appear in stalled_positions.

        Using truthiness would treat None as a live timestamp, falsely
        reporting the position as stalled and triggering an erroneous
        placeholder for a position whose in-flight marker was already
        cleared.
        """
        state = _state(
            positions=[0, 1, 2],
            dispatched_at={0: None, 1: 1_000_000.0},  # 0: tombstone, 1: live
            foreman_wakes=[[0, 1], []],
        )
        result = stalled_positions(state, now=1_000_001.0)
        assert 0 not in result, (
            "Position 0 has a tombstone (None) entry — not in-flight, not stalled"
        )
        assert result == [1], "Position 1 outside the current batch must be stalled"

    def test_no_dispatched_positions_returns_empty(self):
        state = _state(positions=[0, 1, 2], foreman_wakes=[[], []])
        assert stalled_positions(state, now=99999.0) == []

    def test_result_is_sorted(self):
        """Result is sorted ascending regardless of dispatched_at iteration order."""
        state = _state(
            positions=[0, 1, 2, 3],
            dispatched_at={3: 100.0, 0: 100.0, 2: 100.0},
            foreman_wakes=[[0, 1, 2, 3], []],  # all in prev batch, none in current
        )
        result = stalled_positions(state, now=101.0)
        assert result == sorted(result)
        assert result == [0, 2, 3]


# ---------------------------------------------------------------------------
# TestAllPositionsCommitted
# ---------------------------------------------------------------------------

class TestAllPositionsCommitted:
    """all_positions_committed: True iff every covered position is committed."""

    def test_false_when_any_outstanding(self):
        state = _state(positions=[0, 1, 2], landed={0, 1})
        assert all_positions_committed(state) is False

    def test_true_when_all_landed(self):
        state = _state(positions=[0, 1, 2], landed={0, 1, 2})
        assert all_positions_committed(state) is True

    def test_placeholder_satisfies_committed(self):
        """A placeholder counts as committed — a terminal failure must not
        prevent deck review from firing.

        ``len(landed) == len(spec.slides)`` would return False here, leaving
        the turn stranded permanently.
        """
        state = _state(positions=[0, 1, 2], landed={0, 2}, placeheld={1})
        assert all_positions_committed(state) is True

    def test_false_when_only_inflight(self):
        """In-flight positions (dispatched but not committed) are still
        outstanding — the deck is not ready for review."""
        state = _state(
            positions=[0, 1, 2],
            landed={0, 2},
            dispatched_at={1: 1000.0},  # in-flight
        )
        assert all_positions_committed(state) is False

    def test_true_vacuously_for_empty_spec(self):
        """An empty covered set is vacuously committed (no slides to build)."""
        state = _state()
        assert all_positions_committed(state) is True

    def test_true_for_empty_target_positions_edit_turn(self):
        """An edit turn with an empty target list covers nothing and is
        vacuously committed."""
        state = _state(target_positions=[])
        assert all_positions_committed(state) is True

    def test_edit_turn_only_checks_target_positions(self):
        """An edit turn must not check deck_spec slides — only target_positions."""
        # deck_spec has positions 0-9, but edit only targets [3, 7]
        state = _state(
            positions=list(range(10)),
            target_positions=[3, 7],
            landed={3, 7},
        )
        # Positions 0-2, 4-6, 8-9 are NOT in this turn's scope
        assert all_positions_committed(state) is True

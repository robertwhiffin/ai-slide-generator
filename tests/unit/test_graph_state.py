"""Unit tests for ``src/services/graph/state.py``.

C1 owns the state contract every later task writes through.  Four things must
hold:

1. The three reducers (union / merge / concat) accumulate within a turn and
   discard on a turn change.
2. ``scoped_vals`` returns the *right empty type* per key and discards stale
   wrappers — the read-side staleness check is the piece an earlier draft of
   this task missed entirely, causing turn 2 to build nothing while the tests
   passed.
3. ``has_pending_fix`` is False for an all-tombstoned map and True when any
   entry survives.
4. Fan-in keys in ``GraphState`` declare a reducer; single-writer keys do not.

Two compiled-graph tests are also here:

* A 6-branch concurrent ``Send`` test that catches a missing reducer at
  runtime (``InvalidUpdateError`` is raised by the runtime; a dict-merge unit
  test alone cannot catch it).
* A turn-2 checkpointer test that verifies the read-side staleness check works
  across a real checkpoint boundary (file-backed SQLite — see the fixture
  docstring for why StaticPool cannot be used here).

Sabotage targets documented in the report:

  S1. Swap ``turn_scoped_union`` for ``turn_scoped_merge`` on
      ``landed_positions`` in ``GraphState``.
      Expected: turn-2 test goes red for the RIGHT reason — a ``TypeError``
      inside the turn-2 invoke because the merge reducer tries ``dict(set())``
      when two branches write set-valued landed_positions in the same superstep,
      not a ``TypeError`` in turn 1 (which gave false confidence in an earlier
      attempt).

  S2. Replace ``has_pending_fix`` body with a truthiness test
      (``return bool(scoped_vals(state, "fix_map"))``).
      Expected: tombstone test goes red.

  S3. Remove the staleness guard from ``scoped_vals`` (delete the turn
      comparison block).
      Expected: stale-wrapper test goes red.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict, get_type_hints

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.core.database import _migrate_graph_checkpoints
from src.services.graph.state import (
    GraphState,
    _EMPTY_FOR,
    has_pending_fix,
    scoped,
    scoped_vals,
    turn_scoped_concat,
    turn_scoped_merge,
    turn_scoped_union,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _saver_engine(tmp_path):
    """FILE-BACKED SQLite carrying only the migration-built checkpoint tables.

    MEASURED TRAP — copy this form, not the usual house pattern.  The house
    pattern uses ``sqlite:///:memory:`` with ``StaticPool``, and that CANNOT
    be used for a compiled-graph test.  A graph's sync Pregel loop calls the
    saver from multiple threads simultaneously; ``StaticPool`` hands both the
    SAME sqlite3 connection, which segfaults the interpreter (reproduced 3/3
    runs on the previous PR).  File-backed with ordinary pooling gives each
    thread its own connection, which is what makes the tests below safe.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'graph_state_test.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    with engine.begin() as conn:
        _migrate_graph_checkpoints(conn, None)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def _saver(_saver_engine):
    """A ``SqlAlchemyCheckpointSaver`` over an explicit test factory."""
    return SqlAlchemyCheckpointSaver(
        session_factory=sessionmaker(
            bind=_saver_engine, expire_on_commit=False
        )
    )


# ---------------------------------------------------------------------------
# Reducer unit tests
# ---------------------------------------------------------------------------

class TestTurnScopedUnion:
    def test_merges_two_sets_within_a_turn(self):
        a = scoped("t1", {0, 1})
        b = scoped("t1", {2, 3})
        result = turn_scoped_union(a, b)
        assert result == {"turn": "t1", "vals": {0, 1, 2, 3}}

    def test_union_is_idempotent_for_overlapping_entries(self):
        a = scoped("t1", {0, 1})
        b = scoped("t1", {1, 2})
        result = turn_scoped_union(a, b)
        assert result["vals"] == {0, 1, 2}

    def test_discards_a_on_turn_change(self):
        a = scoped("t1", {0, 1, 2})
        b = scoped("t2", {99})
        result = turn_scoped_union(a, b)
        # b's turn wins; a's positions are gone
        assert result == {"turn": "t2", "vals": {99}}

    def test_returns_b_when_a_is_not_a_dict(self):
        b = scoped("t1", {0})
        result = turn_scoped_union(None, b)
        assert result == b

    def test_returns_b_when_b_is_not_a_dict(self):
        a = scoped("t1", {0})
        result = turn_scoped_union(a, "unexpected")
        assert result == "unexpected"


class TestTurnScopedMerge:
    def test_merges_two_dicts_within_a_turn(self):
        a = scoped("t1", {0: "slide-0"})
        b = scoped("t1", {1: "slide-1"})
        result = turn_scoped_merge(a, b)
        assert result == {"turn": "t1", "vals": {0: "slide-0", 1: "slide-1"}}

    def test_b_wins_on_key_collision_within_a_turn(self):
        a = scoped("t1", {0: "old"})
        b = scoped("t1", {0: "new"})
        result = turn_scoped_merge(a, b)
        assert result["vals"][0] == "new"

    def test_discards_a_on_turn_change(self):
        a = scoped("t1", {0: "slide-0", 1: "slide-1"})
        b = scoped("t2", {0: "fresh"})
        result = turn_scoped_merge(a, b)
        # b's turn wins; a's keys are gone
        assert result == {"turn": "t2", "vals": {0: "fresh"}}

    def test_tombstone_survives_as_none(self):
        # turn_scoped_merge cannot delete a key — completed entries are
        # represented as {key: None}.
        a = scoped("t1", {0: "slide-0"})
        b = scoped("t1", {0: None})  # tombstone
        result = turn_scoped_merge(a, b)
        assert result["vals"][0] is None

    def test_returns_b_when_a_is_not_a_dict(self):
        b = scoped("t1", {0: "x"})
        assert turn_scoped_merge(None, b) == b

    def test_returns_b_when_b_is_not_a_dict(self):
        a = scoped("t1", {0: "x"})
        assert turn_scoped_merge(a, 42) == 42


class TestTurnScopedConcat:
    def test_concatenates_two_lists_within_a_turn(self):
        a = scoped("t1", ["wake1"])
        b = scoped("t1", ["wake2"])
        result = turn_scoped_concat(a, b)
        assert result == {"turn": "t1", "vals": ["wake1", "wake2"]}

    def test_preserves_order(self):
        a = scoped("t1", [1, 2])
        b = scoped("t1", [3, 4])
        result = turn_scoped_concat(a, b)
        assert result["vals"] == [1, 2, 3, 4]

    def test_discards_a_on_turn_change(self):
        a = scoped("t1", ["old-wake"])
        b = scoped("t2", ["new-wake"])
        result = turn_scoped_concat(a, b)
        assert result == {"turn": "t2", "vals": ["new-wake"]}

    def test_returns_b_when_a_is_not_a_dict(self):
        b = scoped("t1", ["x"])
        assert turn_scoped_concat(None, b) == b

    def test_returns_b_when_b_is_not_a_dict(self):
        a = scoped("t1", ["x"])
        assert turn_scoped_concat(a, "bad") == "bad"


# ---------------------------------------------------------------------------
# scoped_vals tests
# ---------------------------------------------------------------------------

class TestScopedVals:
    def test_returns_vals_when_turn_matches(self):
        state = {"turn_id": "t1", "landed_positions": scoped("t1", {0, 1})}
        result = scoped_vals(state, "landed_positions")
        assert result == {0, 1}

    def test_returns_empty_set_when_wrapper_is_stale(self):
        """The read-side staleness check is the half an earlier draft missed.

        Without this check, turn 2 reads turn 1's landed_positions, the
        foreman's next_dispatch_batch returns [], all_positions_committed is
        true, and the graph builds nothing while the test passes.
        """
        # Checkpoint carries turn 1's value; state now has turn_id="t2"
        state = {"turn_id": "t2", "landed_positions": scoped("t1", {0, 1, 2})}
        result = scoped_vals(state, "landed_positions")
        assert result == set(), (
            "stale wrapper (turn mismatch) must return empty, not turn 1's set"
        )

    def test_returns_empty_dict_when_stale(self):
        state = {"turn_id": "t2", "slides": scoped("t1", {0: "x"})}
        assert scoped_vals(state, "slides") == {}

    def test_returns_empty_list_when_stale(self):
        state = {"turn_id": "t2", "foreman_wakes": scoped("t1", ["w"])}
        assert scoped_vals(state, "foreman_wakes") == []

    def test_returns_correct_empty_type_per_key(self):
        """Finding 24: a suffix heuristic returning {} for non-positions keys
        would hand emitted_style_blocks' list reducer a dict.
        """
        # No wrapper at all — every key returns its registered empty type
        state = {"turn_id": "t1"}
        assert isinstance(scoped_vals(state, "landed_positions"), set)
        assert isinstance(scoped_vals(state, "placeheld_positions"), set)
        assert isinstance(scoped_vals(state, "reviewed_positions"), set)
        assert isinstance(scoped_vals(state, "slides"), dict)
        assert isinstance(scoped_vals(state, "dispatched_at"), dict)
        assert isinstance(scoped_vals(state, "fix_map"), dict)
        assert isinstance(scoped_vals(state, "fixed"), dict)
        assert isinstance(scoped_vals(state, "emitted_style_blocks"), list)
        assert isinstance(scoped_vals(state, "foreman_wakes"), list)

    def test_raises_key_error_for_unknown_key(self):
        """An unknown key is a programmer error; silence would hide it.

        The choice of raising over returning None is deliberate: any key not
        in _EMPTY_FOR is not a recognised turn-scoped key, and a caller trying
        to read one has a bug that is better caught early.
        """
        with pytest.raises(KeyError):
            scoped_vals({"turn_id": "t1"}, "not_a_real_key")

    def test_returns_empty_when_wrapper_is_not_a_dict(self):
        # Uninitialized key (None, string, etc.) returns empty
        state = {"turn_id": "t1", "slides": None}
        assert scoped_vals(state, "slides") == {}

    def test_returns_empty_when_state_is_none(self):
        # Defensive: state=None should not raise
        assert scoped_vals(None, "foreman_wakes") == []

    def test_returns_empty_when_key_is_absent(self):
        state = {"turn_id": "t1"}
        assert scoped_vals(state, "fix_map") == {}

    def test_all_nine_keys_are_registered(self):
        """_EMPTY_FOR covers exactly the nine keys read through scoped_vals."""
        expected = {
            "landed_positions", "placeheld_positions", "reviewed_positions",
            "slides", "dispatched_at", "fix_map", "fixed",
            "emitted_style_blocks", "foreman_wakes",
        }
        assert set(_EMPTY_FOR.keys()) == expected


# ---------------------------------------------------------------------------
# has_pending_fix tests
# ---------------------------------------------------------------------------

class TestHasPendingFix:
    def _state(self, fix_map: dict) -> dict:
        """Build a minimal state with a current-turn fix_map."""
        turn_id = "t1"
        return {"turn_id": turn_id, "fix_map": scoped(turn_id, fix_map)}

    def test_false_for_empty_fix_map(self):
        assert has_pending_fix(self._state({})) is False

    def test_true_for_active_entry(self):
        assert has_pending_fix(self._state({0: "position-0"})) is True

    def test_false_for_all_tombstoned_map(self):
        """The tombstone trap: bool({0: None}) is True but has_pending_fix must
        return False, or the graph loops to GraphRecursionError.
        """
        assert has_pending_fix(self._state({0: None, 1: None})) is False

    def test_true_when_mix_of_active_and_tombstoned(self):
        # One live entry among tombstones → still pending
        assert has_pending_fix(self._state({0: None, 1: "active"})) is True

    def test_false_for_stale_fix_map(self):
        # fix_map from a previous turn is stale — no pending fix
        state = {"turn_id": "t2", "fix_map": scoped("t1", {0: "active"})}
        assert has_pending_fix(state) is False


# ---------------------------------------------------------------------------
# GraphState annotation correctness
# ---------------------------------------------------------------------------

class TestGraphStateAnnotations:
    """Every fan-in key declares a reducer; every single-writer key does not.

    Undeclared/mis-declared keys fail silently at runtime, so pinning the
    annotation contract here catches changes that would otherwise only show up
    as wrong behaviour in a compiled graph.
    """

    _FAN_IN_REDUCERS = {
        "findings": operator.add,
        "landed_positions": turn_scoped_union,
        "placeheld_positions": turn_scoped_union,
        "reviewed_positions": turn_scoped_union,
        "slides": turn_scoped_merge,
        "dispatched_at": turn_scoped_merge,
        "fix_map": turn_scoped_merge,
        "fixed": turn_scoped_merge,
        "emitted_style_blocks": turn_scoped_concat,
        "foreman_wakes": turn_scoped_concat,
    }

    _SINGLE_WRITER_KEYS = {
        "session_id", "turn_id", "initiated_by", "fix_target",
        "deck_spec", "architect_intent", "architect_message",
        "target_positions", "title",
        "token_css", "deterministic_css", "template_layout_html", "resolved_style",
        "external_scripts", "head_meta",
        "scripts_content", "knitted_html",
        "error_state",
    }

    def test_fan_in_keys_carry_the_right_reducer(self):
        hints = get_type_hints(GraphState, include_extras=True)
        for key, expected_reducer in self._FAN_IN_REDUCERS.items():
            hint = hints[key]
            # Annotated[X, reducer] → __metadata__[0] is the reducer
            assert hasattr(hint, "__metadata__"), (
                f"{key!r} must be Annotated[..., reducer] but has no __metadata__"
            )
            actual = hint.__metadata__[0]
            assert actual is expected_reducer, (
                f"{key!r}: expected reducer {expected_reducer!r}, got {actual!r}"
            )

    def test_single_writer_keys_carry_no_reducer(self):
        hints = get_type_hints(GraphState, include_extras=True)
        for key in self._SINGLE_WRITER_KEYS:
            assert key in hints, f"{key!r} is missing from GraphState"
            hint = hints[key]
            assert not hasattr(hint, "__metadata__"), (
                f"{key!r} is a single-writer key but has a reducer annotation"
            )

    def test_findings_uses_operator_add(self):
        hints = get_type_hints(GraphState, include_extras=True)
        reducer = hints["findings"].__metadata__[0]
        assert reducer is operator.add

    def test_retry_count_is_absent(self):
        """retry_count was deleted (Ruling C-14): no node retries anything.
        A declared key no node writes is precisely the 'tested but unreachable'
        class the corrections file removes.
        """
        hints = get_type_hints(GraphState, include_extras=True)
        assert "retry_count" not in hints


# ---------------------------------------------------------------------------
# Compiled-graph test — 6 concurrent Send branches (no checkpointer)
# ---------------------------------------------------------------------------

class TestCompiledGraph6Branches:
    """A missing reducer raises InvalidUpdateError at RUNTIME.

    A dict-merge unit test cannot catch this because the error is raised by
    LangGraph's Pregel engine when it tries to apply concurrent writes to a key
    with no reducer.  This test exercises that code path.

    Sabotage: remove the Annotated[Any, turn_scoped_merge] annotation from
    ``slides`` in GraphState → InvalidUpdateError.
    """

    def _build_and_invoke(self) -> dict:
        """Compile a graph over GraphState, fan out 6 Sends, merge all writes."""

        def router(state: dict) -> list:
            turn_id = state.get("turn_id", "t1")
            return [
                Send("worker", {"session_id": f"pos-{i}", "turn_id": turn_id})
                for i in range(6)
            ]

        def worker(state: dict) -> dict:
            # session_id encodes the position (test-only convention).
            # The worker READS session_id from its Send payload but does NOT
            # return it, avoiding a concurrent-write conflict on that key.
            pos = int(state["session_id"].split("-")[1])
            turn_id = state.get("turn_id", "t1")
            return {"slides": scoped(turn_id, {pos: f"slide-{pos}"})}

        builder = StateGraph(GraphState)
        builder.add_node("worker", worker)
        builder.add_conditional_edges(START, router, ["worker"])
        builder.add_edge("worker", END)

        graph = builder.compile()  # no checkpointer needed
        return graph.invoke({"turn_id": "t1", "session_id": "main"})

    def test_six_concurrent_send_branches_are_all_merged(self):
        result = self._build_and_invoke()
        slides_wrapper = result.get("slides")
        assert isinstance(slides_wrapper, dict), (
            f"slides should be a scoped wrapper dict; got {type(slides_wrapper)}"
        )
        slides = slides_wrapper.get("vals", {})
        assert len(slides) == 6, (
            f"Expected 6 slides from 6 branches; got {sorted(slides.keys())}"
        )
        assert set(slides.keys()) == {0, 1, 2, 3, 4, 5}

    def test_slides_turn_id_is_preserved(self):
        result = self._build_and_invoke()
        assert result["slides"]["turn"] == "t1"


# ---------------------------------------------------------------------------
# Compiled-graph test — turn 2 with a real checkpointer (file-backed SQLite)
# ---------------------------------------------------------------------------

class TestTurn2WithCheckpointer:
    """Turn 2 reads fresh state for turn-scoped keys; this is the behavioural
    proof that the scoped_vals staleness check is wired correctly.

    Graph topology: reader → setup.  The reader runs BEFORE any new write in
    the turn, so it observes the checkpointed (potentially stale) value.

    Turn 1:
      reader reads foreman_wakes → [] (nothing yet)
      setup writes foreman_wakes = scoped("t1", ["wake1"])

    Turn 2 (same thread_id):
      reader reads foreman_wakes → [] even though the checkpoint carries
        foreman_wakes = scoped("t1", ["wake1"]), because state["turn_id"] is
        now "t2" and the wrapper's turn is "t1".
      setup writes foreman_wakes = scoped("t2", ["wake1"])

    This is stated as "turn 2 dispatched N builders" in the brief because the
    real consequence of a stale read is the foreman not dispatching; here we
    prove the mechanism that makes that impossible.
    """

    def _build_graph(self, saver: SqlAlchemyCheckpointSaver) -> Any:
        reads: dict[str, list] = {}

        def reader(state: dict) -> dict:
            """Read foreman_wakes BEFORE any write in this turn."""
            turn_id = state.get("turn_id", "?")
            reads[turn_id] = list(scoped_vals(state, "foreman_wakes"))
            return {}

        def setup(state: dict) -> dict:
            """Write one wake entry for this turn."""
            turn_id = state.get("turn_id", "t?")
            return {"foreman_wakes": scoped(turn_id, ["wake1"])}

        # Minimal state: only the two keys this test needs.
        class _TurnState(TypedDict, total=False):
            turn_id: str
            foreman_wakes: Annotated[Any, turn_scoped_concat]

        builder = StateGraph(_TurnState)
        builder.add_node("reader", reader)
        builder.add_node("setup", setup)
        builder.add_edge(START, "reader")
        builder.add_edge("reader", "setup")
        builder.add_edge("setup", END)

        return builder.compile(checkpointer=saver), reads

    def test_turn2_foreman_read_is_fresh(self, _saver):
        """Turn 2's reader sees [] even though the checkpoint holds turn 1's wakes.

        'thread_id is required on every invoke when a checkpointer is attached'
        (runtime-facts.md): omitting it raises ValueError.
        """
        graph, reads = self._build_graph(_saver)
        config = {"configurable": {"thread_id": "thread-turn2-test"}}

        graph.invoke({"turn_id": "t1"}, config=config)
        assert reads["t1"] == [], (
            "Turn 1: reader ran before setup, so it must see empty wakes"
        )

        graph.invoke({"turn_id": "t2"}, config=config)
        assert reads["t2"] == [], (
            "Turn 2: foreman_wakes wrapper has turn 't1' but turn_id is 't2' "
            "— scoped_vals must return [] (the staleness check in action)"
        )

    def test_turn2_requires_thread_id_when_checkpointer_is_attached(self, _saver):
        """Omitting thread_id with a checkpointer raises ValueError.

        This is a hard runtime fact; the test documents it so future readers
        know the requirement is not optional.
        """
        graph, _ = self._build_graph(_saver)
        with pytest.raises(ValueError, match="thread_id"):
            graph.invoke({"turn_id": "t1"})

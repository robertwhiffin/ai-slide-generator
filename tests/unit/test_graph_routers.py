"""C4 — the conditional-edge routers and ``build_branch_payload``.

The two blocking corrections are pinned here:

* ``foreman_router`` takes its batch from the LAST ``foreman_wakes`` entry and
  calls ``next_dispatch_batch`` nowhere.  Every state in
  ``TestForemanRouterTakesTheBatchFromTheLastWake`` carries ``dispatched_at``
  stamps for the wake's positions — exactly what ``foreman_node`` writes — so a
  router that recomputed the batch would see them as in-flight and return the
  wrong destination.  That is the failure that builds nothing while every
  scheduler unit test stays green.
* ``build_branch_payload`` looks the ``SlideSpec`` up by POSITION.  The specs
  here are deliberately non-contiguous (``0, 5, 9``): with ``0..n-1`` positions
  index and position coincide and an index-based lookup cannot be caught.
"""

from __future__ import annotations

import inspect
import time
from typing import get_args

import pytest
from langgraph.graph import END
from langgraph.types import Send

from src.domain.skill_io import ArchitectIntent
from src.services.graph import routers
from src.services.graph.nodes import build_branch_payload
from src.services.graph.routers import (
    architect_router,
    build_reviewer_refan_router,
    fixer_router,
    foreman_router,
)
from src.services.graph.state import scoped
from tests.unit.conftest_graph import TEMPLATE_LAYOUT, make_spec

TURN = "turn-1"


def _dispatch_state(spec, wake, stamped):
    """The state a router sees after ``foreman_node`` dispatched *wake*."""
    now = time.time()
    return {
        "session_id": "sess-1",
        "turn_id": TURN,
        "initiated_by": "user@example.com",
        "deck_spec": spec,
        "template_layout_html": TEMPLATE_LAYOUT,
        "deterministic_css": ":root { --brand: #123456; }",
        "resolved_style": "STYLE",
        "design_system_active": True,
        "foreman_wakes": scoped(TURN, [list(wake)]),
        "dispatched_at": scoped(TURN, {p: now for p in stamped}),
    }


# ---------------------------------------------------------------------------
# architect_router
# ---------------------------------------------------------------------------


class TestArchitectRouter:
    @pytest.mark.parametrize(
        "intent,expected",
        [
            ("discuss", END),
            ("ask_data", "data_analyst"),
            ("build", "foreman"),
            ("edit", "foreman"),
            ("confirm_design_contract", END),
        ],
    )
    def test_maps_every_declared_intent(self, intent, expected):
        assert architect_router({"architect_intent": intent}) == expected

    def test_every_architect_intent_literal_is_routed(self):
        """No intent may be unroutable: the union is closed and the map must cover it."""
        for intent in get_args(ArchitectIntent):
            assert intent in routers._INTENT_ROUTES, intent

    def test_confirm_design_contract_ends_the_turn(self):
        """A confirmation WAITS for the user — nothing may restyle before they answer."""
        assert architect_router({"architect_intent": "confirm_design_contract"}) is END

    @pytest.mark.parametrize("intent", [None, "", "rebuild_everything"])
    def test_unroutable_intent_ends_the_turn(self, intent):
        assert architect_router({"architect_intent": intent}) is END


# ---------------------------------------------------------------------------
# foreman_router — blocking correction 1
# ---------------------------------------------------------------------------


class TestForemanRouterTakesTheBatchFromTheLastWake:
    def test_full_batch_fans_out_even_though_every_position_reads_in_flight(self):
        """The router sees foreman_node's OWN dispatched_at stamps.

        ``next_dispatch_batch`` on this state returns ``[]`` — all three
        positions are stamped, so all three read as in-flight.  Reading the last
        wake instead is the only way three builders get dispatched.
        """
        spec = make_spec((0, 1, 2))
        state = _dispatch_state(spec, [0, 1, 2], [0, 1, 2])

        result = foreman_router(state)

        assert isinstance(result, list)
        assert [s.node for s in result] == ["builder"] * 3
        assert [s.arg["position"] for s in result] == [0, 1, 2]

    def test_partial_batch_fans_out_the_wake_s_positions_not_the_recomputed_ones(self):
        """A recomputing router would dispatch position 1 — the one NOT in the wake."""
        spec = make_spec((0, 1, 2))
        state = _dispatch_state(spec, [0, 2], [0, 2])

        result = foreman_router(state)

        assert [s.arg["position"] for s in result] == [0, 2]

    def test_module_never_names_next_dispatch_batch(self):
        """Ruling C-1, checked on the source: the token must not appear at all."""
        source = inspect.getsource(routers)
        code_lines = [
            line
            for line in source.splitlines()
            if "next_dispatch_batch" in line and not line.lstrip().startswith("#")
        ]
        prose_only = [
            line
            for line in code_lines
            if line.lstrip().startswith("*")
            or "``next_dispatch_batch``" in line
        ]
        assert code_lines == prose_only, (
            "foreman_router must never call next_dispatch_batch (Ruling C-1); "
            f"offending lines: {[c for c in code_lines if c not in prose_only]}"
        )

    def test_returns_sends_rather_than_writing_them_into_state(self):
        spec = make_spec((0,))
        result = foreman_router(_dispatch_state(spec, [0], [0]))
        assert all(isinstance(item, Send) for item in result)


class TestForemanRouterLadderOnAnEmptyWake:
    def _empty_wake_state(self, spec, **overrides):
        state = {
            "session_id": "sess-1",
            "turn_id": TURN,
            "deck_spec": spec,
            "foreman_wakes": scoped(TURN, [[]]),
        }
        state.update(overrides)
        return state

    def test_pending_fix_routes_to_the_fixer(self):
        spec = make_spec((0,))
        state = self._empty_wake_state(
            spec, fix_map=scoped(TURN, {0: {"original_html": "<p>x</p>"}})
        )
        assert foreman_router(state) == "fixer"

    def test_tombstoned_fix_map_is_not_a_pending_fix(self):
        """``bool({0: None})`` is True; routing on it loops to GraphRecursionError."""
        spec = make_spec((0,))
        state = self._empty_wake_state(
            spec,
            fix_map=scoped(TURN, {0: None}),
            landed_positions=scoped(TURN, {0}),
        )
        assert foreman_router(state) == "deck_reviewer"

    def test_leftover_from_a_completed_batch_routes_to_the_placeholder(self):
        """Limb 1 at ZERO elapsed time: the position is outside the (empty) wake."""
        spec = make_spec((0, 1))
        state = self._empty_wake_state(
            spec,
            dispatched_at=scoped(TURN, {0: time.time(), 1: time.time()}),
            landed_positions=scoped(TURN, {0}),
        )
        assert foreman_router(state) == "placeholder"

    def test_all_committed_routes_to_deck_review(self):
        spec = make_spec((0, 1))
        state = self._empty_wake_state(
            spec, landed_positions=scoped(TURN, {0, 1})
        )
        assert foreman_router(state) == "deck_reviewer"

    def test_a_placeholder_counts_as_committed(self):
        spec = make_spec((0, 1))
        state = self._empty_wake_state(
            spec,
            landed_positions=scoped(TURN, {0}),
            placeheld_positions=scoped(TURN, {1}),
            dispatched_at=scoped(TURN, {0: time.time(), 1: time.time()}),
        )
        assert foreman_router(state) == "deck_reviewer"

    def test_no_wake_at_all_still_routes_the_ladder(self):
        """The very first wake of a session: no wakes recorded, nothing built."""
        spec = make_spec((0,))
        assert foreman_router({"turn_id": TURN, "deck_spec": spec}) is END


# ---------------------------------------------------------------------------
# The re-fan
# ---------------------------------------------------------------------------


class TestBuildReviewerRefan:
    def _branch_state(self, positions, reviewed=()):
        return {
            "turn_id": TURN,
            "slides": scoped(
                TURN,
                {
                    p: {"position": p, "html": f"<p>{p}</p>", "scripts": ""}
                    for p in positions
                },
            ),
            "reviewed_positions": scoped(TURN, set(reviewed)),
        }

    def test_one_send_per_unreviewed_position_with_the_builder_s_own_record(self):
        result = build_reviewer_refan_router(self._branch_state([3]))
        assert [s.node for s in result] == ["build_reviewer"]
        assert result[0].arg["position"] == 3
        assert result[0].arg["html"] == "<p>3</p>"

    def test_a_merged_view_still_produces_one_send_per_position(self):
        """Guards the one-reviewer-writes-one-row invariant and the n-not-3n cost."""
        result = build_reviewer_refan_router(self._branch_state([0, 1, 2]))
        assert [s.arg["position"] for s in result] == [0, 1, 2]

    def test_reviewed_positions_are_skipped(self):
        result = build_reviewer_refan_router(
            self._branch_state([0, 1], reviewed=[0])
        )
        assert [s.arg["position"] for s in result] == [1]

    def test_nothing_to_review_goes_to_the_placeholder_not_the_foreman(self):
        """Measured: routing a placeheld branch to the foreman wakes it MID-BATCH,
        in the same superstep as its siblings' reviewers, and the deck reviewer
        then runs twice. See the router's docstring for the superstep trace."""
        assert build_reviewer_refan_router(self._branch_state([])) == "placeholder"
        assert (
            build_reviewer_refan_router(self._branch_state([0], reviewed=[0]))
            == "placeholder"
        )

    def test_router_never_reads_a_payload_key_off_state(self):
        """``state["position"]`` raises KeyError — a router sees plain state only."""
        state = self._branch_state([1])
        assert "position" not in state
        assert build_reviewer_refan_router(state)[0].arg["position"] == 1


# ---------------------------------------------------------------------------
# fixer_router, and the router that must not exist
# ---------------------------------------------------------------------------


class TestFixerRouter:
    def test_a_dispatched_fix_goes_to_its_reviewer(self):
        assert fixer_router({"fix_target": 2}) == "fix_reviewer"

    def test_position_zero_is_a_real_target(self):
        """``if state.get("fix_target"):`` would send position 0 to the foreman."""
        assert fixer_router({"fix_target": 0}) == "fix_reviewer"

    def test_no_candidate_returns_to_the_foreman(self):
        assert fixer_router({"fix_target": None}) == "foreman"
        assert fixer_router({}) == "foreman"


def test_no_reviewer_router_is_defined():
    """Measured: wiring one raises InvalidUpdateError on ``fix_target``."""
    assert not hasattr(routers, "reviewer_router")


@pytest.mark.parametrize(
    "router",
    [architect_router, foreman_router, build_reviewer_refan_router, fixer_router],
)
def test_router_signature_is_state_or_state_config(router):
    """An extra positional parameter raises TypeError; the second must be ``config``."""
    params = list(inspect.signature(router).parameters)
    assert params[0] == "state"
    assert len(params) <= 2
    if len(params) == 2:
        assert params[1] == "config"


# ---------------------------------------------------------------------------
# build_branch_payload
# ---------------------------------------------------------------------------


class TestBuildBranchPayload:
    def test_slide_spec_is_looked_up_by_position_not_list_index(self):
        """Positions 0/5/9: an index lookup briefs the wrong slide or raises."""
        spec = make_spec((0, 5, 9))
        state = _dispatch_state(spec, [5], [5])

        payload = build_branch_payload(state, 5)

        assert payload["position"] == 5
        assert payload["slide_spec"]["purpose"] == "purpose-5"
        assert payload["assumes"] == "assumes-5"
        assert payload["hands_off"] == "hands-off-5"

    def test_the_highest_position_is_reachable(self):
        """``spec.slides[9]`` is an IndexError; ``slide_at(9)`` is the last slide."""
        spec = make_spec((0, 5, 9))
        payload = build_branch_payload(_dispatch_state(spec, [9], [9]), 9)
        assert payload["slide_spec"]["content_brief"] == "brief-9"

    def test_a_position_the_spec_does_not_carry_raises_naming_it(self):
        spec = make_spec((0, 5, 9))
        with pytest.raises(ValueError, match="position 4"):
            build_branch_payload(_dispatch_state(spec, [4], [4]), 4)

    def test_no_deck_spec_raises(self):
        state = _dispatch_state(make_spec((0,)), [0], [0])
        state["deck_spec"] = None
        with pytest.raises(ValueError, match="no.*deck_spec"):
            build_branch_payload(state, 0)

    def test_section_css_is_the_deterministic_css_whole(self):
        """§M5: the section CSS is carried WHOLE, never pruned."""
        spec = make_spec((0,))
        state = _dispatch_state(spec, [0], [0])
        payload = build_branch_payload(state, 0)
        assert payload["section_css"] == state["deterministic_css"]

    def test_section_html_is_extracted_from_the_layout_in_state(self):
        spec = make_spec((0, 1), template_section_index=1)
        payload = build_branch_payload(_dispatch_state(spec, [0], [0]), 0)
        assert "Section B" in payload["section_html"]
        assert "Section A" not in payload["section_html"]

    def test_no_section_index_and_no_layout_carry_empty_markup(self):
        spec = make_spec((0,), template_section_index=None)
        state = _dispatch_state(spec, [0], [0])
        assert build_branch_payload(state, 0)["section_html"] == ""

    def test_out_of_range_section_index_does_not_kill_the_branch(self):
        spec = make_spec((0,), template_section_index=99)
        assert build_branch_payload(_dispatch_state(spec, [0], [0]), 0)[
            "section_html"
        ] == ""

    def test_resolved_data_comes_from_the_deck_spec_not_a_state_key(self):
        """§11: resolved_data is NOT a GraphState key and must not become one."""
        spec = make_spec((0,))
        state = _dispatch_state(spec, [0], [0])
        assert "resolved_data" not in state
        payload = build_branch_payload(state, 0)
        assert payload["resolved_data"]["synthesis"] == "Stub synthesis"

    def test_the_principal_travels_in_the_payload(self):
        """The re-fanned reviewer writes the row and needs a non-NULL author."""
        spec = make_spec((0,))
        payload = build_branch_payload(_dispatch_state(spec, [0], [0]), 0)
        assert payload["initiated_by"] == "user@example.com"

    def test_every_value_is_json_native(self):
        """Ruling C-21: nothing but JSON-native types enters a Send payload."""
        spec = make_spec((0,), design_system_id=7, template_id=3)
        payload = build_branch_payload(_dispatch_state(spec, [0], [0]), 0)

        def assert_native(value, path="payload"):
            if isinstance(value, dict):
                for key, item in value.items():
                    assert isinstance(key, (str, int)), f"{path}: key {key!r}"
                    assert_native(item, f"{path}.{key}")
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    assert_native(item, f"{path}[{index}]")
            else:
                assert value is None or isinstance(
                    value, (str, int, float, bool)
                ), f"{path} is {type(value).__name__}"

        assert_native(payload)
        assert payload["design_contract"] == {
            "design_system_id": 7,
            "template_id": 3,
            "slide_style_id": None,
        }
        assert payload["design_system_active"] is True

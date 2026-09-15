"""ws4d D6c / §4.6 — a spec change, through the COMPILED graph.

Two behaviours the unit suite cannot reach, because both are statements about the
graph and not about a node's return value:

*   **A design-contract confirmation dispatches no builder.**  On its own that is
    an absence assertion — it passes if the turn never ran at all — so every
    guard here is paired with proof that the turn HAPPENED and reached the
    router: the architect was called exactly once, an intent came back, and
    ``foreman_wakes`` is empty because the FOREMAN never woke rather than because
    the graph never started.  :func:`test_a_build_turn_in_this_environment_does_
    dispatch_builders` is the other half of that pair: it proves this environment
    can dispatch builders at all, so "no builder" means something.
*   **Confirming rebuilds every position.**  Asserted by IDENTITY — the exact
    positions the builder skill was called for — never by count.  A count
    assertion passes when the wrong set of the right size rebuilds, and the case
    that matters is precisely a set substitution: the architect asked for
    ``[1]`` and coverage must widen to ``[0, 1, 2]``.

``resolve_style_source`` is stubbed here and nowhere else in this file's setup.
The fixture's own note explains why it normally is not: it touches no database
for an UNPINNED deck, and every spec that suite builds is unpinned.  These
scenarios are about a PINNED contract by construction, and the real resolver
reads through ``src.core.database.get_db_session``, which this fixture does not
redirect — so leaving it live would send a test at whatever database the
environment happens to point at.
"""

from __future__ import annotations

import pytest

from src.api.services.deck_level_writer import write_deck_level_columns
from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.domain.skill_io import ArchitectOutput
from tests.integration.conftest_stub_skills import builder_html

pytestmark = pytest.mark.integration

OWNER = "owner@example.com"


def _spec(positions=(0, 1, 2), **contract) -> DeckSpec:
    return DeckSpec(
        title="Quarterly Review",
        audience="the engineering leads",
        purpose="agree the Q4 plan",
        argument="the platform work paid off",
        call_to_action="approve the Q4 headcount",
        narrative_arc=["open", "evidence", "close"],
        design_contract=contract,
        resolved_data={"synthesis": "stub", "figures": [], "gaps": []},
        slides=[
            {
                "position": p,
                "purpose": f"purpose-{p}",
                "content_brief": f"brief-{p}",
                "assumes": f"assumes-{p}",
                "hands_off": f"hands-off-{p}",
                "data_references": [],
                "template_section_index": None,
            }
            for p in positions
        ],
    )


@pytest.fixture
def stub_style(monkeypatch):
    """Neutralise brand resolution — see the module docstring."""
    from src.services.agent_resolution import ResolvedStyle

    monkeypatch.setattr(
        "src.services.agent_resolution.resolve_style_source",
        lambda config: ResolvedStyle(
            slide_style="STUB STYLE PROSE",
            design_system_active=False,
            design_system_compiled=None,
            template_pinned=False,
            image_guidelines=None,
        ),
    )


def _persist_spec(session_id: str, spec: DeckSpec) -> None:
    write_deck_level_columns(session_id, deck_spec=spec.to_json(), modified_by=OWNER)


def _architect_returns(env, out: ArchitectOutput) -> None:
    """Shadow the recorder's architect handler for this turn only."""
    env.recorder._skill_architect = lambda payload: out


# ---------------------------------------------------------------------------
# A design-contract confirmation dispatches no builder
# ---------------------------------------------------------------------------


def test_a_design_contract_confirmation_dispatches_no_builder(
    graph_turn_env, stub_style
):
    env = graph_turn_env
    _persist_spec(env.session_id, _spec(slide_style_id=5))
    _architect_returns(
        env,
        ArchitectOutput(
            intent="confirm_design_contract",
            message="I can move this deck onto the Acme design system.",
            proposed_design_contract=DesignContractRef(design_system_id=9),
        ),
    )

    state = env.run(initial={"architect_message": "put this on the Acme brand"})

    # The turn HAPPENED and reached the router — without these three the
    # no-builder assertion below is satisfied by a turn that never ran.
    assert env.recorder.counts("architect") == 1
    assert state["architect_intent"] == "confirm_design_contract"
    assert env.wakes(state) == [], "the foreman woke on a confirmation turn"

    # ...and nothing was built or restyled.
    assert env.recorder.counts("builder") == 0
    assert env.recorder.counts("build_reviewer") == 0
    assert env.recorder.counts("deck_reviewer") == 0
    assert env.rows() == []

    # §L4: the message names the slide style confirming would drop.
    assert "slide style" in state["architect_message"].lower()
    assert "5" in state["architect_message"]

    # The proposal is NOT committed: the persisted spec still carries the style.
    persisted = DeckSpec.model_validate_json(env.deck_row().deck_spec_json)
    assert persisted.design_contract.slide_style_id == 5
    assert persisted.design_contract.design_system_id is None


def test_a_build_turn_in_this_environment_does_dispatch_builders(graph_turn_env):
    """The pair for the assertion above: this environment CAN dispatch builders,
    so "no builder was dispatched" is a statement about the confirmation and not
    about the harness."""
    env = graph_turn_env
    env.recorder.configure(slide_count=3)

    state = env.run()

    assert env.recorder.positions("builder") == [0, 1, 2]
    assert env.wakes(state)[0] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Confirming rebuilds every position
# ---------------------------------------------------------------------------


def test_applying_a_design_contract_change_rebuilds_every_position(
    graph_turn_env, stub_style
):
    """The architect asked for slide 1; a restyle affects all three.

    Identity, not count: ``[0, 1, 2]``, and every row carries the builder's fresh
    HTML rather than whatever was there before.
    """
    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _architect_returns(
        env,
        ArchitectOutput(
            intent="edit",
            message="Moving to the Acme brand and touching up slide 1.",
            target_positions=[1],
            deck_spec=_spec(slide_style_id=42),
        ),
    )

    state = env.run(initial={"architect_message": "use the Acme brand"})

    assert state["target_positions"] == [0, 1, 2]
    assert env.recorder.positions("builder") == [0, 1, 2]
    assert env.recorder.positions("build_reviewer") == [0, 1, 2]
    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1, 2]
    for position in (0, 1, 2):
        assert rows[position].html == builder_html(position)


def test_an_edit_turn_with_no_contract_change_rebuilds_only_its_target(
    graph_turn_env, stub_style
):
    """The paired direction, and the one that fails if the override is
    unconditional: without a contract change an edit turn must stay narrow, or
    every edit becomes the blanket rebuild-all §4.6 rejected."""
    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _architect_returns(
        env,
        ArchitectOutput(
            intent="edit",
            message="Touching up slide 1.",
            target_positions=[1],
            deck_spec=_spec(),
        ),
    )

    state = env.run(initial={"architect_message": "tidy up slide 1"})

    assert state["target_positions"] == [1]
    assert env.recorder.positions("builder") == [1]
    assert sorted(env.rows_by_position()) == [1]

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


# ---------------------------------------------------------------------------
# A deck-level change: re-review all, rebuild only failures (Option 2)
#
# Every stub here keys its verdict on the NEW brief being visible in the review
# payload, never on the position.  That is deliberate and it is the whole reason
# these tests can see the mechanism: the first version of this suite failed slides
# by position for `overflow` — an objective DESIGN criterion no spec edit can
# cause — and stayed green while the deck-level fields never reached the reviewer
# at all and the failing rule ignored the one criterion that could express
# "no longer serves the brief".  A stub that can only fail when it was SHOWN the
# new brief reddens on both of those defects, and on a pass scored against the
# OLD spec.
# ---------------------------------------------------------------------------

NEW_AUDIENCE = "the CFO, not engineers"
HAND_EDITED = "<div class='slide'><h1>HAND EDITED BY A HUMAN</h1></div>"
COMMITTED = {
    0: HAND_EDITED,
    1: "<div class='slide'><h1>COMMITTED ONE</h1></div>",
    2: "<div class='slide'><h1>COMMITTED TWO</h1></div>",
}


def _seed_committed_rows(env) -> None:
    """Three committed rows with distinctive HTML, position 0 hand-edited.

    Distinctive per position on purpose: "rebuilt only failures" is an IDENTITY
    claim, and a marker per row is what makes a wrong-set-of-the-right-size
    substitution visible.
    """
    import uuid

    from src.database.models.session import SessionSlide, UserSession

    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        for position, html in COMMITTED.items():
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    slide_id=str(uuid.uuid4()),
                    html=html,
                    scripts="",
                )
            )
        db.commit()
    finally:
        db.close()


def _brief_aware_reviewer(env, failing) -> None:
    """Fail *failing* only when the payload shows the NEW brief AND committed html.

    Two conditions, each load-bearing:

    * ``deck_brief["audience"] == NEW_AUDIENCE`` — a pass that shows the reviewer
      no brief, or the OLD spec's brief, cannot produce a finding, so both
      defects redden here rather than passing silently.
    * the html is one of the COMMITTED markups — so a post-build review of a
      REBUILT slide is always clean.  Keying on position instead would make a
      rebuilt slide fail its own review too, opening a fix round and conflating
      "which positions rebuilt" with "which positions were fixed".
    """
    from src.domain.finding import CRITERIA, Finding, SlideReviewOutput

    committed_htmls = set(COMMITTED.values())
    # brief_not_delivered is the only criterion that can express "no longer serves
    # the brief"; it is subjective, which is exactly why the objective-only rule
    # made this pass inert.
    criterion = "brief_not_delivered"
    assert CRITERIA[criterion].category != "design", (
        "a design criterion is not reachable from a spec change; a stub using one "
        "makes every test over it vacuous"
    )

    def _review(payload):
        position = payload["position"]
        brief = payload.get("deck_brief") or {}
        is_rereview = payload.get("html") in committed_htmls
        saw_the_new_brief = brief.get("audience") == NEW_AUDIENCE
        findings = (
            [
                Finding(
                    id="stub-unstamped",
                    slide_index=position,
                    category=CRITERIA[criterion].category,
                    criterion=criterion,
                    message="still written for engineers, not the CFO",
                    objective=CRITERIA[criterion].objective,
                )
            ]
            if is_rereview and saw_the_new_brief and position in failing
            else []
        )
        return SlideReviewOutput(
            slide_index=position,
            verdict="surfaced" if findings else "clean",
            findings=findings,
        )

    env.recorder._skill_build_reviewer = _review


def _rereviewed_positions(env) -> list:
    """Positions whose review payload carried COMMITTED html — i.e. the re-review."""
    committed_htmls = set(COMMITTED.values())
    return sorted(
        call["payload"]["position"]
        for call in env.recorder.calls_for("build_reviewer")
        if call["payload"].get("html") in committed_htmls
    )


def _audience_changed_build(env) -> None:
    _architect_returns(
        env,
        ArchitectOutput(
            intent="build",
            message="Retargeting the whole deck at the CFO.",
            deck_spec=_spec().model_copy(update={"audience": NEW_AUDIENCE}),
        ),
    )


def test_a_deck_level_change_re_reviews_all_and_rebuilds_only_failures(
    graph_turn_env, stub_style
):
    """The headline behaviour, asserted four ways at once.

    The re-review ran over EVERY position — without that, "rebuilt only failures"
    is vacuously true because a pass that reviews nothing has no failures.  Every
    re-review payload carried the NEW brief.  Only position 2 rebuilt, by
    identity.  And positions 0 and 1 are BYTE-IDENTICAL afterwards, position 0
    being the hand-edited one, which is the whole reason §4.6 rejected a blanket
    rebuild-all.
    """
    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _seed_committed_rows(env)
    _brief_aware_reviewer(env, {2})
    _audience_changed_build(env)

    state = env.run(initial={"architect_message": "this is for the CFO now"})

    assert _rereviewed_positions(env) == [0, 1, 2], "the re-review skipped a slide"
    briefs = [
        call["payload"].get("deck_brief")
        for call in env.recorder.calls_for("build_reviewer")
        if call["payload"].get("html") in set(COMMITTED.values())
    ]
    assert all(b and b.get("audience") == NEW_AUDIENCE for b in briefs), briefs
    assert state["target_positions"] == [2]
    assert env.recorder.positions("builder") == [2]

    rows = env.rows_by_position()
    assert rows[0].html == HAND_EDITED
    assert rows[1].html == COMMITTED[1]
    assert rows[2].html == builder_html(2)


def test_a_deck_level_change_nothing_contradicts_rebuilds_nothing_and_completes(
    graph_turn_env, stub_style
):
    """Every slide still fits: no builder runs, every row is byte-identical, and
    the turn still reaches deck review rather than hanging or erroring."""
    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _seed_committed_rows(env)
    _brief_aware_reviewer(env, set())
    _audience_changed_build(env)

    state = env.run(initial={"architect_message": "this is for the CFO now"})

    assert _rereviewed_positions(env) == [0, 1, 2]
    assert state["target_positions"] == []
    assert env.recorder.counts("builder") == 0
    assert env.recorder.counts("deck_reviewer") == 1
    assert state.get("error_state") is None

    rows = env.rows_by_position()
    for position, html in COMMITTED.items():
        assert rows[position].html == html


def test_a_deck_level_change_everything_contradicts_rebuilds_every_position(
    graph_turn_env, stub_style
):
    """The other extreme: when every slide really does contradict the new brief,
    the selective path converges on the rebuild-all it refused to assume."""
    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _seed_committed_rows(env)
    _brief_aware_reviewer(env, {0, 1, 2})
    _audience_changed_build(env)

    state = env.run(initial={"architect_message": "this is for the CFO now"})

    assert _rereviewed_positions(env) == [0, 1, 2]
    assert state["target_positions"] == [0, 1, 2]
    assert env.recorder.positions("builder") == [0, 1, 2]
    rows = env.rows_by_position()
    for position in (0, 1, 2):
        assert rows[position].html == builder_html(position)


def test_the_re_review_costs_one_model_call_per_committed_slide(
    graph_turn_env, stub_style
):
    """The accepted cost of Option 2, pinned as a number so a regression that
    turned it quadratic would be visible.

    Serial and linear: N committed slides means N review calls inside the one
    architect turn, before any builder runs.
    """
    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _seed_committed_rows(env)
    _brief_aware_reviewer(env, set())
    _audience_changed_build(env)

    env.run(initial={"architect_message": "this is for the CFO now"})

    assert len(_rereviewed_positions(env)) == len(COMMITTED)
    assert env.recorder.counts("build_reviewer") == len(COMMITTED)


def test_both_of_the_architects_utterances_are_persisted_on_a_deck_level_turn(
    graph_turn_env, stub_style
):
    """A deck-level turn is the one turn where the architect speaks TWICE.

    Its reply lands before the spec is classified; the re-review summary is
    composed after, and it is the only place the user is told what the re-review
    decided.  Both take the same two surfaces — a stream event and a persisted
    row — because persisting one and not the other would make the architect
    audible on a plain build turn and mute on a deck-level one, which is the
    original defect moved rather than fixed.

    Both are asserted through ``_conversation``, not merely through the rows: that
    is the architect's own memory, so this pins that next turn it can see both of
    the things it said rather than only the first.
    """
    from src.services.graph.nodes import _conversation

    env = graph_turn_env
    _persist_spec(env.session_id, _spec())
    _seed_committed_rows(env)
    _brief_aware_reviewer(env, {2})
    _audience_changed_build(env)

    env.run(initial={"architect_message": "this is for the CFO now"})

    replayed = [
        turn["content"]
        for turn in _conversation(env.session_id)
        if turn["role"] == "assistant"
    ]
    # ENTRY: the re-review really ran, so "the summary is missing" cannot be
    # confused with "there was no summary to persist".
    assert _rereviewed_positions(env) == [0, 1, 2]
    assert "Retargeting the whole deck at the CFO." in replayed, (
        f"the architect's reply is not in its replayable conversation: {replayed!r}"
    )
    summaries = [text for text in replayed if "re-checked all" in text]
    assert summaries, (
        f"the deck-level re-review summary was never persisted: {replayed!r}"
    )
    assert "Rebuilding 1: [2]" in summaries[0], summaries[0]

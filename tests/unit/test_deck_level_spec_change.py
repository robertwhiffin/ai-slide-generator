"""ws4d D6c / §4.6 — classifying a deck-level spec change, and what follows.

Three subjects, and each one is a place a guard here can be bypassed:

1.  :func:`classify_spec_change` — the pure classifier.  Its whole risk is a
    field list that drifts, so every field of both groups is exercised
    INDIVIDUALLY rather than through one representative: a single-field test
    passes with four of the five deck-level fields unwatched.
2.  The §L4 confirmation message.  The assertion is on the **augmented text in
    both channels** — the returned ``architect_message`` and the emitted
    ``ASSISTANT`` event — because augmenting one alone would show the user a
    sentence the transcript does not contain.
3.  Coverage forcing on a design-contract change.  The sharp case is an **edit**
    turn: the architect asked for one position and the override has to widen it
    to every position.  A build turn cannot distinguish the two, because
    ``_covered_positions`` already derives every spec position when
    ``target_positions`` is ``None``.

``design_contract`` beating ``deck_level`` when both differ is asserted on a spec
that changes BOTH, which is the only shape that can catch the precedence being
written the other way round.
"""

from __future__ import annotations

import logging
import queue

import pytest

from src.api.services.deck_level_writer import write_deck_level_columns
from src.domain.deck_spec import DesignContractRef
from src.domain.skill_io import ArchitectOutput
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import architect_node, classify_spec_change
from tests.unit.conftest_graph import (  # noqa: F401
    finding,
    graph_env,
    make_spec,
    review_out,
)


# ---------------------------------------------------------------------------
# 1. classify_spec_change
# ---------------------------------------------------------------------------


def test_an_identical_spec_is_no_change():
    spec = make_spec()
    assert classify_spec_change(spec, make_spec()) == "none"


def test_no_persisted_spec_is_no_change_so_a_first_build_never_confirms():
    """A brand-new deck has nothing to invalidate and nothing to confirm.

    If this returned ``design_contract`` the very first turn of every pinned deck
    would force a rebuild-all over slides that do not exist yet.
    """
    assert classify_spec_change(make_spec(design_system_id=1), None) == "none"
    assert classify_spec_change(None, make_spec()) == "none"


@pytest.mark.parametrize(
    "before, after",
    [
        # design_system_id, on its own (L3 forbids a template without one).
        ({}, {"design_system_id": 7}),
        ({"design_system_id": 7}, {}),
        # template_id — "pinning or unpinning a template", which is a change to
        # template_id and NOT to any `template_pinned` field: there is no such
        # persisted field anywhere in the contract.
        ({"design_system_id": 7}, {"design_system_id": 7, "template_id": 3}),
        ({"design_system_id": 7, "template_id": 3}, {"design_system_id": 7}),
        (
            {"design_system_id": 7, "template_id": 3},
            {"design_system_id": 7, "template_id": 4},
        ),
        # slide_style_id.
        ({}, {"slide_style_id": 5}),
        ({"slide_style_id": 5}, {}),
        ({"slide_style_id": 5}, {"slide_style_id": 6}),
    ],
)
def test_every_design_contract_field_classifies_as_a_design_contract_change(
    before, after
):
    assert (
        classify_spec_change(make_spec(**after), make_spec(**before))
        == "design_contract"
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("audience", "the CFO, not engineers"),
        ("purpose", "a different decision"),
        ("argument", "a different claim"),
        ("call_to_action", "a different next step"),
        ("narrative_arc", ["opening", "evidence", "conclusion", "coda"]),
    ],
)
def test_every_deck_level_field_classifies_as_a_deck_level_change(field, value):
    persisted = make_spec()
    changed = persisted.model_copy(update={field: value})
    assert classify_spec_change(changed, persisted) == "deck_level"


def test_a_retitle_is_not_a_deck_level_change():
    """``title`` is deliberately outside the field list — renaming a deck
    contradicts no slide, and watching it would re-review a whole deck because
    somebody fixed a typo in its name."""
    persisted = make_spec(title="Q3 Review")
    assert classify_spec_change(make_spec(title="Q3 Business Review"), persisted) == (
        "none"
    )


def test_a_slide_body_change_is_not_a_deck_level_change():
    """Changing the slides is per-slide work the foreman's coverage already does."""
    persisted = make_spec(positions=(0, 1, 2))
    assert classify_spec_change(make_spec(positions=(0, 1, 2, 3)), persisted) == "none"


def test_the_design_contract_wins_when_both_kinds_of_field_differ():
    """The stronger, confirm-first case must win — asserted on a spec that
    changes both, which is the only shape that catches the precedence inverted."""
    persisted = make_spec()
    both = make_spec(design_system_id=7).model_copy(
        update={"audience": "the CFO, not engineers"}
    )
    assert classify_spec_change(both, persisted) == "design_contract"


# ---------------------------------------------------------------------------
# 2. The §L4 confirmation message
# ---------------------------------------------------------------------------


def _persist(env, spec):
    write_deck_level_columns(
        env.session_id, deck_spec=spec.to_json(), modified_by="owner@example.com"
    )


def _drain(q):
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except Exception:
            return events


def _run_architect(env, out, *, emitter=None):
    env.skills.set("architect", out)
    set_event_emitter(emitter)
    try:
        return architect_node(env.state(architect_message="use the Acme brand"))
    finally:
        set_event_emitter(None)


def test_the_confirmation_names_the_slide_style_it_would_drop(graph_env):
    """§L4: one user action mutates two fields, and the user must be TOLD.

    Nothing "clears" the slide style on the deck spec — ``DesignContractRef``'s
    L1 validator REJECTS a spec carrying both ids — so this sentence is the only
    place the loss is visible, and it has to arrive while the user can say no.
    """
    env = graph_env
    _persist(env, make_spec(slide_style_id=5))
    emitter = queue.Queue()

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="confirm_design_contract",
            message="I can switch this deck to the Acme design system.",
            proposed_design_contract=DesignContractRef(design_system_id=9),
        ),
        emitter=emitter,
    )

    message = updates["architect_message"]
    assert updates["architect_intent"] == "confirm_design_contract"
    assert "slide style" in message.lower(), message
    assert "5" in message, message
    # The model's own words survive; the notice is appended, not substituted.
    assert message.startswith("I can switch this deck to the Acme design system.")

    # BOTH channels carry the augmented text. The emit happens inside the node,
    # so a notice added after it would stream one message and persist another.
    assistant = [e for e in _drain(emitter) if e.content is not None]
    assert assistant, "the architect emitted no ASSISTANT event at all"
    assert "slide style" in assistant[0].content.lower(), assistant[0].content
    assert assistant[0].content == message


def test_a_confirmation_that_drops_no_slide_style_says_nothing_about_one(graph_env):
    """The paired negative: an unpinned deck loses nothing, so no notice."""
    env = graph_env
    _persist(env, make_spec())

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="confirm_design_contract",
            message="I can switch this deck to the Acme design system.",
            proposed_design_contract=DesignContractRef(design_system_id=9),
        ),
    )

    assert "slide style" not in updates["architect_message"].lower()


def test_a_proposal_with_no_design_system_drops_no_slide_style(graph_env):
    """A proposal that only swaps one legacy style for another drops nothing:
    the exclusivity §L4 is about is design system vs slide style."""
    env = graph_env
    _persist(env, make_spec(slide_style_id=5))

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="confirm_design_contract",
            message="I can switch you to a different slide style.",
            proposed_design_contract=DesignContractRef(slide_style_id=6),
        ),
    )

    assert "cannot both apply" not in updates["architect_message"]


def test_a_confirmation_commits_nothing_and_restyles_nothing(graph_env):
    """The proposal stays in ``proposed_design_contract``: the persisted spec is
    byte-identical afterwards, so nothing downstream can restyle before the user
    answers."""
    env = graph_env
    _persist(env, make_spec(slide_style_id=5))
    before = env.deck_row().deck_spec_json

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="confirm_design_contract",
            message="Switch to Acme?",
            proposed_design_contract=DesignContractRef(design_system_id=9),
        ),
    )

    assert updates.get("deck_spec") is None
    assert env.deck_row().deck_spec_json == before


# ---------------------------------------------------------------------------
# 3. Coverage forcing (C-4) and the deck-level hole
# ---------------------------------------------------------------------------


def test_a_design_contract_change_widens_an_edit_turn_to_every_position(graph_env):
    """The sharp case. The architect asked for position 1 only; a restyle affects
    every slide, so coverage is forced to all of them.

    Asserted by IDENTITY (the exact position list), not by length: a wrong set of
    the right size passes a count assertion.
    """
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="edit",
            message="Restyling and tweaking slide 1.",
            target_positions=[1],
            deck_spec=make_spec(positions=(0, 1, 2), design_system_id=7),
        ),
    )

    assert updates["target_positions"] == [0, 1, 2]


def test_an_edit_turn_with_no_contract_change_keeps_the_architects_targets(graph_env):
    """The paired direction: without a contract change the override must not
    fire, or every edit turn silently becomes a rebuild-all."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="edit",
            message="Tweaking slide 1.",
            target_positions=[1],
            deck_spec=make_spec(positions=(0, 1, 2)),
        ),
    )

    assert updates["target_positions"] == [1]


def test_pinning_a_template_widens_coverage_too(graph_env):
    """§L4: pinning is what supplies the template's own CSS, so pinning or
    unpinning one is a design-contract change like any other."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2), design_system_id=7))

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="edit",
            message="Pinning the title template and tweaking slide 2.",
            target_positions=[2],
            deck_spec=make_spec(
                positions=(0, 1, 2), design_system_id=7, template_id=3
            ),
        ),
    )

    assert updates["target_positions"] == [0, 1, 2]


def test_a_deck_level_change_with_nothing_committed_leaves_coverage_alone(
    graph_env, caplog
):
    """An unbuilt deck has nothing to score, so coverage stays as the architect
    set it.

    Writing an empty target list here would make the turn cover NOTHING and
    complete vacuously — the failure mode the foreman's own coverage rules warn
    about — which is strictly worse than building what was asked.
    """
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))

    with caplog.at_level(logging.WARNING, logger="src.services.graph.nodes"):
        updates = _run_architect(
            env,
            ArchitectOutput(
                intent="edit",
                message="Retargeting the deck at the CFO.",
                target_positions=[1],
                deck_spec=make_spec(positions=(0, 1, 2)).model_copy(
                    update={"audience": "the CFO, not engineers"}
                ),
            ),
        )

    assert updates["target_positions"] == [1]
    assert env.skills.calls_for("build_reviewer") == []
    assert any(
        "no committed slide to re-review" in record.getMessage()
        for record in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_a_contributor_session_classifies_the_owners_spec(graph_env):
    """Decks are SHARED, and a contributor session's own ``slide_deck`` is None.

    The classification reads the persisted spec through
    ``deck_level_writer.read_deck_spec``, which resolves the OWNER's deck row, so
    a contributor's turn must see the same spec and widen coverage the same way.
    On ws4d Task 4 nineteen standalone-session tests stayed green with owner
    resolution removed — a single-session test cannot see this axis at all.
    """
    from src.database.models.session import UserSession

    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))

    contributor_sid = f"{env.session_id}-contrib"
    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        db.add(
            UserSession(
                session_id=contributor_sid,
                created_by="contributor@example.com",
                parent_session_id=owner.id,
            )
        )
        db.commit()
    finally:
        db.close()

    env.skills.set(
        "architect",
        ArchitectOutput(
            intent="edit",
            message="Moving the deck onto the Acme brand.",
            target_positions=[1],
            deck_spec=make_spec(positions=(0, 1, 2), design_system_id=7),
        ),
    )
    updates = architect_node(
        env.state(session_id=contributor_sid, architect_message="use the Acme brand")
    )

    assert updates["target_positions"] == [0, 1, 2]


def test_the_notice_fires_when_agent_config_has_already_dropped_the_style(graph_env):
    """The case the persisted-spec fallback exists for, and the only one that can
    catch its removal.

    ``AgentConfig``'s serializer ALREADY nulls ``slide_style_id`` the moment a
    design system is selected on the session, so the inbound contract this turn's
    brand was resolved from carries no style while the persisted spec still does.
    That deck is exactly one whose style is about to be dropped — and reading only
    the inbound contract would say nothing at all.
    """
    from src.database.models.session import UserSession

    env = graph_env
    _persist(env, make_spec(slide_style_id=5))

    db = env.factory()
    try:
        session = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        session.agent_config = {"design_system_id": 9}
        db.commit()
    finally:
        db.close()

    updates = _run_architect(
        env,
        ArchitectOutput(
            intent="confirm_design_contract",
            message="Switch this deck to Acme?",
            proposed_design_contract=DesignContractRef(design_system_id=9),
        ),
    )

    assert "slide style" in updates["architect_message"].lower()
    assert "5" in updates["architect_message"]


# ---------------------------------------------------------------------------
# 4. The serial re-review pass (Option 2)
#
# THE GUARD THAT WAS MISSING, and why this section is shaped around it.
#
# The first version of this suite was green over a mechanism that could not work.
# Every "failing" stub returned `overflow` — an OBJECTIVE, DESIGN criterion about
# where pixels land.  No edit to a deck's audience or argument can cause an
# overflow finding, so the suite proved the plumbing while the production path
# could never produce the verdict it was plumbing.  Two real defects hid under it:
# the five deck-level fields never reached the reviewer at all, and the only
# criterion that CAN express "no longer serves the brief" is
# `brief_not_delivered`, which is objective=False and so was not counted.
#
# Two things fix that permanently:
#
#   * SPEC_REACHABLE_CRITERIA is DERIVED from the registry, not listed by hand: a
#     slide-level criterion whose category is not "design".  `rereview_finding`
#     refuses anything outside it AND refuses a criterion the production rule
#     would not count — so a stub cannot manufacture an unreachable failure mode,
#     and cannot assert a reachable one the code ignores.
#   * `brief_aware_reviewer` keys its verdict on the NEW brief being visible IN
#     THE PAYLOAD.  A pass that shows the reviewer nothing, or shows it the OLD
#     spec, produces no finding and reddens — which is what makes "scored against
#     the new spec" a testable claim rather than a comment.
# ---------------------------------------------------------------------------

from src.domain.finding import CRITERIA  # noqa: E402
from src.services.graph.nodes import (  # noqa: E402
    _DECK_LEVEL_FIELDS,
    _REREVIEW_FAILING_CRITERIA,
    rereview_committed_slides,
)

NEW_AUDIENCE = "the CFO, not engineers"
OLD_AUDIENCE = "Stub audience"  # what make_spec() sets

#: The criteria a change to the deck's SPEC can actually cause on one slide:
#: slide-level, and not about rendering.  Derived from the registry so a new
#: criterion is classified the day it lands.  `overflow`, `contrast_failure`,
#: `rogue_colour` and `distorted_image` are all category="design" — the pixels do
#: not move when the audience changes — and the three narrative criteria are
#: level="deck", which belongs to the deck reviewer, not to this per-slide pass.
SPEC_REACHABLE_CRITERIA = frozenset(
    name
    for name, criterion in CRITERIA.items()
    if criterion.level == "slide" and criterion.category != "design"
)

REVIEWER_PAYLOAD_KEYS = {
    "position",
    "slide_spec",
    "resolved_style",
    "section_css",
    "resolved_data",
    "html",
    "scripts",
}


def rereview_finding(position, criterion="brief_not_delivered"):
    """A finding a SPEC change can produce AND that the pass counts as failing.

    Both assertions are the guard.  The first is what was missing: a stub using
    ``overflow`` manufactures a failure mode the production path cannot reach, and
    every test over it is vacuous.  The second catches the mirror defect that
    actually shipped: a reachable criterion the production rule ignores, which is
    exactly ``brief_not_delivered`` under an objective-only rule.
    """
    assert criterion in SPEC_REACHABLE_CRITERIA, (
        f"{criterion!r} is not reachable from a spec change "
        f"(reachable: {sorted(SPEC_REACHABLE_CRITERIA)}). A stub that fails a "
        f"slide for an unreachable reason makes every test over it vacuous."
    )
    item = finding(criterion, slide_index=position)
    assert item.objective or criterion in _REREVIEW_FAILING_CRITERIA, (
        f"{criterion!r} is reachable but the re-review's failing rule would not "
        f"count it, so this stub asserts a verdict the code cannot produce."
    )
    return item


def brief_aware_reviewer(failing_positions, *, expect_audience=NEW_AUDIENCE):
    """A reviewer that can only fail a slide when it was SHOWN the new brief.

    Keyed on ``payload["deck_brief"]["audience"]``, never on the position alone.
    That is what makes two separate defects observable: a payload carrying no
    deck brief at all, and a pass scored against the OLD spec.  Both leave the
    reviewer unable to tell the brief changed, so it returns nothing and every
    "rebuilt only failures" assertion reddens.
    """

    def _review(payload):
        position = payload["position"]
        brief = payload.get("deck_brief") or {}
        saw_the_new_brief = brief.get("audience") == expect_audience
        findings = (
            [rereview_finding(position)]
            if saw_the_new_brief and position in failing_positions
            else []
        )
        return review_out(position, findings)

    return _review


def _seed_rows(env, htmls, placeheld=()):
    """Committed rows with distinctive HTML; *placeheld* get a placeholder record."""
    import json as _json
    import uuid as _uuid

    from src.api.services.slide_repository import PLACEHOLDER_ERROR_KEY
    from src.database.models.session import SessionSlide, UserSession
    from src.utils.slide_hash import compute_slide_hash as _hash

    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        for position, html in enumerate(htmls):
            record = None
            if position in placeheld:
                record = _json.dumps(
                    {_hash(html): {PLACEHOLDER_ERROR_KEY: True, "message": "failed"}}
                )
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(_uuid.uuid4()),
                    slide_id=str(_uuid.uuid4()),
                    html=html,
                    scripts="",
                    verification_record=record,
                )
            )
        db.commit()
    finally:
        db.close()


def _brand():
    return {
        "resolved_style": "STUB STYLE PROSE",
        "deterministic_css": ".slide { color: red; }",
        "design_system_active": False,
        "template_layout_html": "",
    }


def _new_spec(positions=(0, 1, 2)):
    """The spec AFTER a deck-level change — a new audience."""
    return make_spec(positions=positions).model_copy(
        update={"audience": NEW_AUDIENCE}
    )


# -- the reachability guard has teeth ---------------------------------------


def test_a_rendering_criterion_is_not_reachable_from_a_spec_change():
    """The guard that would have caught the whole defect.

    ``overflow`` is objective, so the old rule DID count it — which is why the
    suite was green.  What made it vacuous is that no spec edit can cause it.
    """
    assert "overflow" not in SPEC_REACHABLE_CRITERIA
    assert "brief_not_delivered" in SPEC_REACHABLE_CRITERIA
    with pytest.raises(AssertionError, match="not reachable from a spec change"):
        rereview_finding(0, criterion="overflow")


def test_the_production_rule_counts_the_criterion_the_stubs_use():
    """The mirror guard: a reachable criterion the code ignores.

    This is the defect that shipped — ``brief_not_delivered`` is the only
    criterion that can say "no longer serves the brief" and the objective-only
    rule dropped it on the floor.
    """
    assert "brief_not_delivered" in _REREVIEW_FAILING_CRITERIA
    assert CRITERIA["brief_not_delivered"].objective is False


# -- the reviewer is shown the new brief ------------------------------------


def test_the_re_review_shows_the_reviewer_the_new_deck_brief(graph_env):
    """All five deck-level fields, carrying the NEW values, in the payload.

    Without them the reviewer is asked whether a slide still serves a brief it
    was never told — measured: every one of the five absent from the serialised
    payload, and the pass rebuilt nothing for N serial model calls.
    """
    env = graph_env
    _seed_rows(env, ["<div>COMMITTED ZERO</div>", "<div>COMMITTED ONE</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    payload = env.skills.calls_for("build_reviewer")[0]["payload"]
    assert set(payload) == REVIEWER_PAYLOAD_KEYS | {"deck_brief"}
    brief = payload["deck_brief"]
    assert brief["audience"] == NEW_AUDIENCE, "the reviewer got the OLD audience"
    for field in _DECK_LEVEL_FIELDS:
        assert field in brief, f"{field} is not shown to the reviewer"
        assert brief[field] == getattr(_new_spec((0, 1)), field)


def test_the_brief_shown_is_exactly_the_fields_that_trigger_a_re_review(graph_env):
    """The fields that TRIGGER the pass and the fields the reviewer is SHOWN are
    one tuple, so they cannot drift: a sixth deck-level field added to the
    classifier would otherwise trigger re-reviews the reviewer cannot judge."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    rereview_committed_slides(env.session_id, _new_spec((0,)), _brand())

    brief = env.skills.calls_for("build_reviewer")[0]["payload"]["deck_brief"]
    assert set(brief) == set(_DECK_LEVEL_FIELDS)


def test_the_re_review_scores_the_committed_html_against_the_new_spec(graph_env):
    """What is ON the deck, judged against where the deck is GOING."""
    env = graph_env
    _seed_rows(env, ["<div>COMMITTED ZERO</div>", "<div>COMMITTED ONE</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    calls = env.skills.calls_for("build_reviewer")
    assert [c["payload"]["position"] for c in calls] == [0, 1]
    assert calls[0]["payload"]["html"] == "<div>COMMITTED ZERO</div>"
    assert calls[1]["payload"]["html"] == "<div>COMMITTED ONE</div>"
    assert calls[0]["payload"]["slide_spec"]["position"] == 0
    assert verdicts["reviewed"] == {0, 1}
    assert verdicts["failing"] == set()


# -- the failing rule -------------------------------------------------------


def test_brief_not_delivered_marks_a_slide_as_no_longer_serving_the_brief(graph_env):
    """The verdict this whole pass exists to act on."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer({1}))

    verdicts = rereview_committed_slides(env.session_id, _new_spec(), _brand())

    assert verdicts["failing"] == {1}
    assert verdicts["reviewed"] == {0, 1, 2}


def test_an_objective_finding_still_marks_a_slide_for_rebuild(graph_env):
    """The build path's rule is KEPT, not replaced: an objectively broken slide is
    rebuilt too while we are rebuilding anyway."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("overflow", slide_index=1)] if payload["position"] == 1 else [],
        ),
    )

    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    assert verdicts["failing"] == {1}


def test_an_unrelated_subjective_finding_does_not_force_a_rebuild(graph_env):
    """Only ``brief_not_delivered`` joins the objective rule. ``arc_gap`` is a
    deck-level narrative observation — surfaced, never a reason to discard a
    slide a human may have edited."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("arc_gap", slide_index=1)] if payload["position"] == 1 else [],
        ),
    )

    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    assert verdicts["failing"] == set()
    assert [f["criterion"] for f in verdicts["surfaced"]] == ["arc_gap"]


def test_every_finding_is_surfaced_including_the_subjective_ones(graph_env):
    """Given the criterion that matters here is subjective, discarding
    non-objective findings threw away the only signal the pass can produce."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer({1}))

    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    assert verdicts["surfaced"] == [
        {
            "position": 1,
            "criterion": "brief_not_delivered",
            "message": "stub finding",
            "objective": False,
        }
    ]


# -- the three judgement calls ----------------------------------------------


def test_a_placeholder_fails_by_definition_and_costs_no_model_call(graph_env):
    """There is nothing there to preserve, so paying a model to confirm what the
    row's own marker says would be waste."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"], placeheld={1})
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    assert verdicts["placeheld"] == {1}
    assert verdicts["failing"] == {1}
    assert [
        c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")
    ] == [0]


def test_an_unreviewable_slide_is_left_alone_rather_than_overwritten(graph_env):
    """The recorded tie-break: §4.6 rejected the blanket rebuild-all as
    "expensive and destructive" *because* manual edits matter, so a slide we
    could not judge is preserved rather than rebuilt."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])
    passing = brief_aware_reviewer(set())

    def _review(payload):
        if payload["position"] == 1:
            raise RuntimeError("the reviewer is down")
        return passing(payload)

    env.skills.set("build_reviewer", _review)
    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    assert verdicts["unreviewable"] == {1}
    assert verdicts["failing"] == set()
    assert verdicts["reviewed"] == {0}
    assert verdicts["committed"] == {0, 1}


def test_a_row_the_new_spec_does_not_cover_is_not_re_reviewed(graph_env):
    """A shorter new spec must not pay to review slides it no longer declares."""
    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    verdicts = rereview_committed_slides(env.session_id, _new_spec((0, 1)), _brand())

    assert verdicts["committed"] == {0, 1}
    assert [
        c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")
    ] == [0, 1]


# -- and the narrowing the node does with those verdicts ---------------------


def _audience_changed(positions=(0, 1, 2), targets=None):
    return ArchitectOutput(
        intent="edit" if targets else "build",
        message="Retargeting the deck at the CFO.",
        target_positions=list(targets or []),
        deck_spec=_new_spec(positions),
    )


def test_a_deck_level_change_rebuilds_only_the_slides_that_contradict_it(graph_env):
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer({2}))

    updates = _run_architect(env, _audience_changed())

    assert updates["target_positions"] == [2]


def test_a_deck_level_change_that_nothing_contradicts_rebuilds_nothing(graph_env):
    """The paired direction. Without it, "only failures rebuild" would also pass
    against code that rebuilds everything it reviewed."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    updates = _run_architect(env, _audience_changed())

    assert updates["target_positions"] == []


def test_a_spec_position_with_no_committed_row_joins_the_rebuild_set(graph_env):
    """A slide the new spec adds cannot be "still valid" — there is nothing
    there — so a deck-level change that also adds one must still build it."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    updates = _run_architect(env, _audience_changed(positions=(0, 1, 2)))

    assert updates["target_positions"] == [2]


def test_an_explicit_edit_target_is_rebuilt_even_when_it_passed_review(graph_env):
    """The user asked for that slide. "It still fits the brief" is not a reason
    to refuse them."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer(set()))

    updates = _run_architect(env, _audience_changed(targets=[1]))

    assert updates["target_positions"] == [1]


def test_the_user_is_told_what_was_re_checked_and_what_is_being_rebuilt(graph_env):
    """§4.6: "tell the user first". The emitter is the only user-facing channel —
    nothing persists ``architect_message`` as chat."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", brief_aware_reviewer({2}))
    emitter = queue.Queue()

    _run_architect(env, _audience_changed(), emitter=emitter)

    notices = [
        e
        for e in _drain(emitter)
        if (e.metadata or {}).get("spec_change") == "deck_level"
    ]
    assert len(notices) == 1
    assert notices[0].metadata["reviewed"] == [0, 1, 2]
    assert notices[0].metadata["rebuilding"] == [2]
    assert notices[0].metadata["stale"] is False
    # The subjective finding IS the signal here, so it has to be reportable.
    assert notices[0].metadata["surfaced"] == [
        {
            "position": 2,
            "criterion": "brief_not_delivered",
            "message": "stub finding",
            "objective": False,
        }
    ]
    assert "re-checked all 3" in notices[0].content


def test_a_pass_that_could_judge_nothing_says_so_and_records_the_deck_as_stale(
    graph_env,
):
    """Every re-review failed. The deck is now stale against a brief nothing
    checked it against, and the tie-break that preserves unjudged slides gives
    that staleness no retry path — so it must not read as "every slide still
    fits"."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])

    def _always_raises(payload):
        raise RuntimeError("the reviewer is down")

    env.skills.set("build_reviewer", _always_raises)
    emitter = queue.Queue()

    updates = _run_architect(env, _audience_changed(positions=(0, 1)), emitter=emitter)

    assert updates["target_positions"] == []
    assert updates["error_state"]["code"] == "rereview_judged_nothing"
    assert updates["error_state"]["positions"] == [0, 1]

    notice = [
        e
        for e in _drain(emitter)
        if (e.metadata or {}).get("spec_change") == "deck_level"
    ][0]
    assert notice.metadata["stale"] is True
    assert notice.metadata["reviewed"] == []
    assert "could not check any" in notice.content
    assert "still fits" not in notice.content


def test_a_contributor_session_re_reviews_the_owners_committed_slides(graph_env):
    """Decks are SHARED and a contributor session's own ``slide_deck`` is None.

    The pass reads rows through ``list_slides_in_position_order``, which resolves
    the OWNER's deck — but the axis was untested, and on ws4d Task 4 nineteen
    standalone-session tests stayed green with owner resolution removed.  A
    contributor turn that read no rows would silently re-review nothing, find no
    failures, and report that every slide still fits.
    """
    from src.database.models.session import UserSession

    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])

    contributor_sid = f"{env.session_id}-contrib"
    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        db.add(
            UserSession(
                session_id=contributor_sid,
                created_by="contributor@example.com",
                parent_session_id=owner.id,
            )
        )
        db.commit()
    finally:
        db.close()

    env.skills.set("build_reviewer", brief_aware_reviewer({2}))
    env.skills.set("architect", _audience_changed())
    updates = architect_node(
        env.state(session_id=contributor_sid, architect_message="this is for the CFO")
    )

    assert [
        c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")
    ] == [0, 1, 2]
    assert updates["target_positions"] == [2]


# ---------------------------------------------------------------------------
# 5. The build path's prompt is byte-identical
# ---------------------------------------------------------------------------


def test_the_deck_brief_block_is_added_only_when_a_deck_brief_is_present():
    """The surgical half of the payload widening.

    The build reviewer and the re-review share one criteria block and one output
    schema, so the re-review's extra instruction must not reach the build path.
    ``call_skill`` adds it on the presence of ``deck_brief`` and nothing else.
    """
    from src.core.skills import _with_conditional_instructions, load_skill
    from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW

    skill = load_skill("build_reviewer")
    # Captured BY VALUE, before the call. Comparing skill.instructions afterwards
    # would be inert: an in-place mutation of the frozen registry entry makes both
    # sides of the comparison the same object and every assertion below pass.
    baseline = str(skill.instructions)
    build_payload = {"position": 0, "html": "<div>x</div>", "scripts": ""}

    assert _with_conditional_instructions(skill, build_payload).instructions == baseline
    widened = _with_conditional_instructions(
        skill, {**build_payload, "deck_brief": {"audience": NEW_AUDIENCE}}
    )
    assert DECK_BRIEF_REVIEW in widened.instructions
    assert widened.instructions.startswith(baseline)
    # The registry entry itself is never mutated: two concurrent branches must not
    # be able to see each other's instructions, and the build path that runs after
    # a re-review must get the same prompt as one that runs before it.
    assert load_skill("build_reviewer").instructions == baseline
    assert _with_conditional_instructions(skill, build_payload).instructions == baseline


def test_the_build_paths_assembled_prompt_is_unchanged_by_this_feature():
    """The stronger form: the WHOLE assembled prompt, not just the instructions.

    A build review's prompt must be byte-identical to what it was before §4.6's
    pass existed — so this reconstructs it from the registry's own instructions
    plus the payload and asserts equality with what ``call_skill`` would assemble.
    """
    from src.services.agent_resolution import assemble_skill_prompt
    from src.core.skills import _with_conditional_instructions, load_skill
    from src.core.skills.build_reviewer import DECK_BRIEF_REVIEW

    skill = load_skill("build_reviewer")
    payload = {
        "position": 0,
        "slide_spec": {"position": 0},
        "resolved_style": "STUB",
        "section_css": "",
        "resolved_data": {"synthesis": "s", "figures": [], "gaps": []},
        "html": "<div>x</div>",
        "scripts": "",
    }
    for design_system_active in (False, True):
        assembled = assemble_skill_prompt(
            _with_conditional_instructions(skill, payload),
            payload,
            design_system_active,
        )
        untouched = assemble_skill_prompt(skill, payload, design_system_active)
        assert assembled == untouched
        assert DECK_BRIEF_REVIEW not in assembled

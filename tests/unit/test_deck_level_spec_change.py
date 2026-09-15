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
# ---------------------------------------------------------------------------

REVIEWER_PAYLOAD_KEYS = {
    "position",
    "slide_spec",
    "resolved_style",
    "section_css",
    "resolved_data",
    "html",
    "scripts",
}


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


def test_the_re_review_scores_the_committed_html_with_the_reviewers_own_payload(
    graph_env,
):
    """The pass must judge what is ON THE DECK, against the NEW spec, using the
    shape ``build_reviewer_node`` builds — key for key, or the skill is scored on
    an input it was never written against."""
    from src.services.graph.nodes import rereview_committed_slides

    env = graph_env
    _seed_rows(env, ["<div>COMMITTED ZERO</div>", "<div>COMMITTED ONE</div>"])
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    new_spec = make_spec(positions=(0, 1)).model_copy(
        update={"audience": "the CFO, not engineers"}
    )
    verdicts = rereview_committed_slides(env.session_id, new_spec, _brand())

    calls = env.skills.calls_for("build_reviewer")
    assert [c["payload"]["position"] for c in calls] == [0, 1]
    assert set(calls[0]["payload"]) == REVIEWER_PAYLOAD_KEYS
    # The committed HTML, not the spec's or the builder's.
    assert calls[0]["payload"]["html"] == "<div>COMMITTED ZERO</div>"
    assert calls[1]["payload"]["html"] == "<div>COMMITTED ONE</div>"
    # ...judged against the NEW spec's slide brief and resolved data.
    assert calls[0]["payload"]["slide_spec"]["position"] == 0
    assert verdicts["reviewed"] == {0, 1}
    assert verdicts["failing"] == set()


def test_only_an_objective_finding_marks_a_slide_as_contradicting_the_spec(graph_env):
    """A subjective finding is surfaced, never acted on — the same rule
    ``build_reviewer_node`` applies, and ``_stamp_findings`` re-derives
    ``objective`` from CRITERIA so a model cannot suppress a rebuild by lying."""
    from src.services.graph.nodes import rereview_committed_slides

    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])

    def _review(payload):
        position = payload["position"]
        if position == 1:
            return review_out(position, [finding("overflow", slide_index=1)])
        if position == 2:
            # `arc_gap` is a SUBJECTIVE criterion: surfaced, not acted on.
            return review_out(position, [finding("arc_gap", slide_index=2)])
        return review_out(position)

    env.skills.set("build_reviewer", _review)
    verdicts = rereview_committed_slides(
        env.session_id, make_spec(positions=(0, 1, 2)), _brand()
    )

    assert verdicts["failing"] == {1}
    assert verdicts["reviewed"] == {0, 1, 2}


def test_a_placeholder_fails_by_definition_and_costs_no_model_call(graph_env):
    """There is nothing there to preserve, so paying a model to confirm what the
    row's own marker says would be waste."""
    from src.services.graph.nodes import rereview_committed_slides

    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"], placeheld={1})
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    verdicts = rereview_committed_slides(
        env.session_id, make_spec(positions=(0, 1)), _brand()
    )

    assert verdicts["placeheld"] == {1}
    assert verdicts["failing"] == {1}
    assert [c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")] == [0]


def test_an_unreviewable_slide_is_left_alone_rather_than_overwritten(graph_env):
    """The recorded tie-break: §4.6 rejected the blanket rebuild-all as
    "expensive and destructive" *because* manual edits matter, so a slide we
    could not judge is preserved rather than rebuilt."""
    from src.services.graph.nodes import rereview_committed_slides

    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])

    def _review(payload):
        if payload["position"] == 1:
            raise RuntimeError("the reviewer is down")
        return review_out(payload["position"])

    env.skills.set("build_reviewer", _review)
    verdicts = rereview_committed_slides(
        env.session_id, make_spec(positions=(0, 1)), _brand()
    )

    assert verdicts["unreviewable"] == {1}
    assert verdicts["failing"] == set()
    assert verdicts["reviewed"] == {0}
    assert verdicts["committed"] == {0, 1}


def test_a_row_the_new_spec_does_not_cover_is_not_re_reviewed(graph_env):
    """A shorter new spec must not pay to review slides it no longer declares."""
    from src.services.graph.nodes import rereview_committed_slides

    env = graph_env
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    verdicts = rereview_committed_slides(
        env.session_id, make_spec(positions=(0, 1)), _brand()
    )

    assert verdicts["committed"] == {0, 1}
    assert [c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")] == [0, 1]


# -- and the narrowing the node does with those verdicts ---------------------


def _deck_level_turn(env, out, emitter=None):
    return _run_architect(env, out, emitter=emitter)


def _audience_changed(positions=(0, 1, 2), targets=None):
    spec = make_spec(positions=positions).model_copy(
        update={"audience": "the CFO, not engineers"}
    )
    return ArchitectOutput(
        intent="edit" if targets else "build",
        message="Retargeting the deck at the CFO.",
        target_positions=list(targets or []),
        deck_spec=spec,
    )


def test_a_deck_level_change_rebuilds_only_the_slides_that_contradict_it(graph_env):
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("overflow", slide_index=payload["position"])]
            if payload["position"] == 2
            else [],
        ),
    )

    updates = _deck_level_turn(env, _audience_changed())

    assert updates["target_positions"] == [2]


def test_a_deck_level_change_that_nothing_contradicts_rebuilds_nothing(graph_env):
    """The paired direction. Without it, "only failures rebuild" would also pass
    against code that rebuilds everything it reviewed."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    updates = _deck_level_turn(env, _audience_changed())

    assert updates["target_positions"] == []


def test_a_spec_position_with_no_committed_row_joins_the_rebuild_set(graph_env):
    """A slide the new spec adds cannot be "still valid" — there is nothing
    there — so a deck-level change that also adds one must still build it."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>"])
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    updates = _deck_level_turn(env, _audience_changed(positions=(0, 1, 2)))

    assert updates["target_positions"] == [2]


def test_an_explicit_edit_target_is_rebuilt_even_when_it_passed_review(graph_env):
    """The user asked for that slide. "It still fits the brief" is not a reason
    to refuse them."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

    updates = _deck_level_turn(env, _audience_changed(targets=[1]))

    assert updates["target_positions"] == [1]


def test_the_user_is_told_what_was_re_checked_and_what_is_being_rebuilt(graph_env):
    """§4.6: "tell the user first". The emitter is the only user-facing channel —
    nothing persists ``architect_message`` as chat."""
    env = graph_env
    _persist(env, make_spec(positions=(0, 1, 2)))
    _seed_rows(env, ["<div>zero</div>", "<div>one</div>", "<div>two</div>"])
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("overflow", slide_index=payload["position"])]
            if payload["position"] == 2
            else [],
        ),
    )
    emitter = queue.Queue()

    _deck_level_turn(env, _audience_changed(), emitter=emitter)

    notices = [
        e
        for e in _drain(emitter)
        if (e.metadata or {}).get("spec_change") == "deck_level"
    ]
    assert len(notices) == 1, [e.metadata for e in _drain(emitter)]
    assert notices[0].metadata["reviewed"] == [0, 1, 2]
    assert notices[0].metadata["rebuilding"] == [2]
    assert "re-checked all 3" in notices[0].content

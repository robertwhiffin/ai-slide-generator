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
from tests.unit.conftest_graph import graph_env, make_spec  # noqa: F401


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


def test_a_deck_level_change_is_classified_and_recorded_not_silently_ignored(
    graph_env, caplog
):
    """§4.6's re-review-all pass is unimplemented — measured as impossible inside
    one turn on this topology — so the classification must at least be RECORDED.

    The guard is that the classifier reached the node on this path: without it
    the log line cannot appear.  It also pins that coverage is NOT widened, which
    is what keeps an audience change from becoming the blanket rebuild-all §4.6
    rejected as expensive and destructive.
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
    assert any(
        "re-review-all" in record.getMessage() for record in caplog.records
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

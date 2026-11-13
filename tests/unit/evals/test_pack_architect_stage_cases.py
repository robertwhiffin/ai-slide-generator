"""The architect pack's Stage Slide cases (whole-branch review I2, plan Task 4).

Six cases per split, defined by ``evals/packs/architect/stage_cases.py`` on each split's own deck
and written by that split's generator (``mutations.generate`` / ``heldout.generate``). Each
payload carries a NON-null ``stage_slide`` (``{slide_number, position}``), resolved by the
production helper from the viewer snapshot the browser sends for a slide with no stable id.

Three groups of tests:

* the dataset contract (the factory itself): pinned literally, so a drift in a case is visible;
* the committed and generated trees (the generators' wiring): each case written exactly, its
  payload the production shape with the stage, every other case's stage still null;
* scoring: each reference passes and each should_fail fails the deterministic scorer on the
  case as committed.

Behavioural and offline; no model, no network.
"""
from __future__ import annotations

import json

import pytest
import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case
from evals.harness.scorers import expected_category_score
from evals.packs.architect import stage_cases as sc
from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_numbering import architect_slide_payload, resolve_slide_references
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS, model_payload_for
from src.services.graph.nodes import GENIE_ONE_DATA_SOURCE
from src.services.template_sections import section_inventory

AGENT = "architect"
SPLITS = ("train", "heldout")
STAGE_CASE_IDS = [
    "stage_restyle_deck", "stage_explicit_other", "stage_deictic_title",
    "stage_unqualified_title", "stage_question", "stage_move",
]
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PAYLOAD_KEYS = [
    "conversation", "message", "current_deck_spec", "committed_slide_count",
    "slide_numbering", "slide_references", "stage_slide",
    "previous_deck_review", "available_design_contract", "template_sections",
    "resolved_style", "design_system_library", "deck_style_context", "data_sources",
]
RESTYLE_KEEPS = ["dk-code", "kw", "fn", "str", "cm"]

# ---- the dataset contract, pinned literally ----

#: The model-facing stage each case's payload must carry (production's resolved shape).
STAGE = {
    "train": {
        "stage_restyle_deck": {"slide_number": 6, "position": 5},
        "stage_explicit_other": {"slide_number": 4, "position": 3},
        "stage_deictic_title": {"slide_number": 5, "position": 4},
        "stage_unqualified_title": {"slide_number": 3, "position": 2},
        "stage_question": {"slide_number": 8, "position": 7},
        "stage_move": {"slide_number": 9, "position": 8},
    },
    "heldout": {
        "stage_restyle_deck": {"slide_number": 3, "position": 2},
        "stage_explicit_other": {"slide_number": 2, "position": 1},
        "stage_deictic_title": {"slide_number": 4, "position": 3},
        "stage_unqualified_title": {"slide_number": 6, "position": 5},
        "stage_question": {"slide_number": 5, "position": 4},
        "stage_move": {"slide_number": 6, "position": 5},
    },
}
EXPECT = {
    "train": {
        "stage_restyle_deck": {"intent": "edit", "positions": [], "deck_style_keeps": RESTYLE_KEEPS},
        "stage_explicit_other": {
            "intent": "edit", "positions": [1], "inserted": [], "layout": list(range(10))},
        "stage_deictic_title": {
            "intent": "edit", "positions": [4], "inserted": [], "layout": list(range(10))},
        "stage_unqualified_title": {
            "intent": "edit", "positions": [2], "inserted": [], "layout": list(range(10))},
        "stage_question": {"intent": "discuss"},
        "stage_move": {
            "intent": "edit", "positions": [], "inserted": [],
            "layout": [0, 1, 8, 2, 3, 4, 5, 6, 7, 9]},
    },
    "heldout": {
        "stage_restyle_deck": {"intent": "edit", "positions": [], "deck_style_keeps": RESTYLE_KEEPS},
        "stage_explicit_other": {
            "intent": "edit", "positions": [4], "inserted": [], "layout": list(range(6))},
        "stage_deictic_title": {
            "intent": "edit", "positions": [3], "inserted": [], "layout": list(range(6))},
        "stage_unqualified_title": {
            "intent": "edit", "positions": [5], "inserted": [], "layout": list(range(6))},
        "stage_question": {"intent": "discuss"},
        "stage_move": {
            "intent": "edit", "positions": [], "inserted": [], "layout": [0, 1, 5, 2, 3, 4]},
    },
}
MESSAGES = {
    "train": {
        "stage_restyle_deck": "Make the code blocks dark with light text",
        "stage_explicit_other": (
            "On slide 2, cut the callout down to the two worst pain points: bloated file sizes "
            "and font substitution"
        ),
        "stage_deictic_title": "Give this slide a shorter title: 'Typography that holds'",
        "stage_unqualified_title": "Change the title to 'What HTML slides are'",
        "stage_question": "Why is this slide in the deck?",
        "stage_move": "Move this slide so it comes straight after slide 2",
    },
    "heldout": {
        "stage_restyle_deck": "Switch the code listings to light text on a dark background",
        "stage_explicit_other": "On slide 5, number each step of the evaluation loop",
        "stage_deictic_title": "Retitle this slide 'What structured prompting saves'",
        "stage_unqualified_title": "Change the title to 'Your prompt checklist'",
        "stage_question": "What is this slide trying to show?",
        "stage_move": "Move this slide so it sits right after slide 2",
    },
}
#: The slide references each message resolves (lexical only: the stage is never one of them).
REFERENCED_POSITIONS = {
    "train": {"stage_explicit_other": [1], "stage_move": [1]},
    "heldout": {"stage_explicit_other": [4], "stage_move": [1]},
}
#: What each should_fail gets wrong, as the deterministic scorer reports it.
SHOULD_FAIL_REASON = {
    "stage_restyle_deck": "rebuilds",
    "stage_explicit_other": "rebuilds",
    "stage_deictic_title": "rebuilds",
    "stage_unqualified_title": "Intent mismatch",
    "stage_question": "Intent mismatch",
    "stage_move": "layout",
}


def _modules():
    from evals.packs.architect import heldout as h
    from evals.packs.architect import mutations as m

    return m, h


def _gold(split):
    return case.gold_deck_spec() if split == "train" else case.gold_deck_spec("heldout")


def _factory(split):
    return {c.case_id: c for c in sc.cases(split)}


def _other_messages(split):
    m, h = _modules()
    return set((m.MESSAGES if split == "train" else h.MESSAGES).values()) - set(
        MESSAGES[split].values())


def _expected_payload(split, cid):
    """The production-shaped payload a stage case must carry, built here from the split's own
    fixtures and the production helpers (``architect_node``'s order and allowlist)."""
    m, h = _modules()
    prior_user, prior_assistant = (
        (m.PRIOR_USER, m.PRIOR_ASSISTANT) if split == "train" else (h.PRIOR_USER, h.PRIOR_ASSISTANT))
    msg = MESSAGES[split][cid]
    conversation = [
        {"role": "user", "content": prior_user},
        {"role": "assistant", "content": prior_assistant},
        {"role": "user", "content": msg},
    ]
    deck = sc.current_deck(split, cid)
    slide_keys = architect_slide_payload(
        conversation, msg, [s["position"] for s in deck["slides"]],
        stage_slide={"slide_number": STAGE[split][cid]["slide_number"]}, slide_rows=[],
    )
    return model_payload_for(AGENT, {
        "conversation": conversation,
        "message": msg,
        "current_deck_spec": deck,
        "committed_slide_count": len(deck["slides"]),
        **slide_keys,
        "previous_deck_review": None,
        "available_design_contract": DesignContractRef(
            design_system_id=m.MERIDIAN_ID, template_id=m.MERIDIAN_TEMPLATE,
        ).model_dump(mode="json"),
        "template_sections": section_inventory(m.LAYOUT.read_text()),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_library": m.LIBRARY,
        "deck_style_context": case.meridian_deck_style_context(),
        # Agent-mode Task 7: every train and held-out payload lists Genie One.
        "data_sources": [GENIE_ONE_DATA_SOURCE],
    })


# =========================================================================== the dataset contract

@pytest.mark.parametrize("split", SPLITS)
def test_the_factory_defines_exactly_the_six_cases(split):
    assert list(sc.STAGE_CASE_IDS) == STAGE_CASE_IDS
    assert [c.case_id for c in sc.cases(split)] == STAGE_CASE_IDS
    assert sc.messages(split) == MESSAGES[split]


@pytest.mark.parametrize("split", SPLITS)
def test_the_messages_are_new_and_split_specific(split):
    """No stage message repeats an existing case's message on either split, nor the other split's."""
    other_split = "heldout" if split == "train" else "train"
    for msg in MESSAGES[split].values():
        assert msg not in _other_messages("train") | _other_messages("heldout")
        assert msg not in MESSAGES[other_split].values()


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_contract_is_pinned(split, cid):
    c = _factory(split)[cid]
    assert c.message == MESSAGES[split][cid]
    # The raw viewer snapshot: an eval deck has no rows, so no stable id (older slide data's shape).
    assert c.stage == {"slide_number": STAGE[split][cid]["slide_number"]}
    assert sc.stage_snapshot(split, cid) == c.stage
    assert c.expect == EXPECT[split][cid]
    assert c.kind == "mutation" and c.fault
    assert c.styled == (cid == "stage_restyle_deck")


@pytest.mark.parametrize("split", SPLITS)
def test_no_other_case_has_a_stage(split):
    m, h = _modules()
    for cid in (m.MESSAGES if split == "train" else h.MESSAGES):
        if cid not in STAGE_CASE_IDS:
            assert sc.stage_snapshot(split, cid) is None, cid


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_production_helper_resolves_the_stage(split, cid):
    """The snapshot resolves, through ``slide_numbering`` (never arithmetic), to the pinned stage."""
    deck = sc.current_deck(split, cid)
    got = architect_slide_payload(
        [], MESSAGES[split][cid], [s["position"] for s in deck["slides"]],
        stage_slide=sc.stage_snapshot(split, cid), slide_rows=[],
    )["stage_slide"]
    assert got == STAGE[split][cid]


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_messages_resolve_only_the_slides_they_name(split, cid):
    deck = sc.current_deck(split, cid)
    refs = resolve_slide_references(MESSAGES[split][cid], [s["position"] for s in deck["slides"]])
    positions = sorted({p for r in refs for p in r["positions"]})
    assert positions == REFERENCED_POSITIONS[split].get(cid, [])
    assert STAGE[split][cid]["position"] not in positions


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_current_deck_is_the_split_s_own(split, cid):
    m, h = _modules()
    gold = _gold(split)
    deck = sc.current_deck(split, cid)
    DeckSpec.model_validate(deck)
    if cid == "stage_restyle_deck":
        looks = m.RESTYLE_LOOKS if split == "train" else h.RESTYLE_LOOKS
        assert deck == m._styled_deck(gold, looks)
        assert "dk-code" in deck["slides"][STAGE[split][cid]["position"]]["look"]
    else:
        assert deck == gold


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_reference_passes_and_the_should_fail_fails(split, cid):
    c = _factory(split)[cid]
    deck = sc.current_deck(split, cid)
    ArchitectOutput.model_validate(c.reference)
    ArchitectOutput.model_validate(c.should_fail)
    assert c.should_fail != c.reference
    ok, why = expected_category_score(
        AGENT, c.reference, c.expect, reference=c.reference, current_deck_spec=deck,
        design_system_active=True)
    assert ok, why
    ok, why = expected_category_score(
        AGENT, c.should_fail, c.expect, reference=c.reference, current_deck_spec=deck,
        design_system_active=True)
    assert not ok
    assert SHOULD_FAIL_REASON[cid] in why, why


@pytest.mark.parametrize("split", SPLITS)
def test_each_reference_acts_on_the_slide_the_policy_names(split):
    """What each reference does, against the stage: the policy, case by case."""
    cases = _factory(split)
    stage = {cid: STAGE[split][cid]["position"] for cid in STAGE_CASE_IDS}

    restyle = ArchitectOutput.model_validate(cases["stage_restyle_deck"].reference)
    assert restyle.operations is None and restyle.deck_changes.deck_style is not None
    narrowed = ArchitectOutput.model_validate(cases["stage_restyle_deck"].should_fail)
    assert [(o.op, o.position) for o in narrowed.operations] == [
        ("update", stage["stage_restyle_deck"])]
    assert narrowed.deck_changes is None

    named = EXPECT[split]["stage_explicit_other"]["positions"]
    explicit = ArchitectOutput.model_validate(cases["stage_explicit_other"].reference)
    assert [(o.op, o.position) for o in explicit.operations] == [("update", named[0])]
    wrong = ArchitectOutput.model_validate(cases["stage_explicit_other"].should_fail)
    assert [(o.op, o.position) for o in wrong.operations] == [
        ("update", stage["stage_explicit_other"])]

    for cid in ("stage_deictic_title", "stage_unqualified_title"):
        out = ArchitectOutput.model_validate(cases[cid].reference)
        assert [(o.op, o.position) for o in out.operations] == [("update", stage[cid])]
    slipped = ArchitectOutput.model_validate(cases["stage_deictic_title"].should_fail)
    assert [(o.op, o.position) for o in slipped.operations] == [
        ("update", stage["stage_deictic_title"] + 1)]
    asks = cases["stage_unqualified_title"].should_fail
    assert asks["intent"] == "discuss" and "which slide" in asks["message"].lower()

    question = cases["stage_question"]
    assert question.reference["intent"] == "discuss"
    assert f"Slide {STAGE[split]['stage_question']['slide_number']}" in question.reference["message"]
    assert question.should_fail["intent"] == "edit"
    assert question.should_fail["target_positions"] == [stage["stage_question"]]

    anchor = REFERENCED_POSITIONS[split]["stage_move"][0]
    move = ArchitectOutput.model_validate(cases["stage_move"].reference)
    assert [(o.op, o.position, o.after_position) for o in move.operations] == [
        ("move", stage["stage_move"], anchor)]
    swapped = ArchitectOutput.model_validate(cases["stage_move"].should_fail)
    assert [(o.op, o.position, o.after_position) for o in swapped.operations] == [
        ("move", anchor, stage["stage_move"])]


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize(
    "cid", ["stage_explicit_other", "stage_deictic_title", "stage_unqualified_title"])
def test_an_update_reference_revises_only_its_slide_s_brief(split, cid):
    out = ArchitectOutput.model_validate(_factory(split)[cid].reference)
    (op,) = out.operations
    gold = {s["position"]: s for s in _gold(split)["slides"]}
    old = {k: v for k, v in gold[op.position].items() if k != "position"}
    new = op.slides[0].model_dump()
    assert {k for k in new if new.get(k) != old.get(k)} == {"content_brief"}, op.position
    if cid != "stage_explicit_other":
        title = MESSAGES[split][cid].split("'")[1]
        assert f"'{title}'" in new["content_brief"]


# =========================================================================== the committed trees

def _root(split):
    return case.cases_dir(AGENT, split=split)


def _committed(split, cid):
    d = _root(split) / cid
    assert d.is_dir(), f"{split}: {cid} is not committed (wire stage_cases into the generator)"
    return d


def _load(split, cid):
    _committed(split, cid)
    return case.load_case(AGENT, cid, **case.split_kwargs(split))


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_case_is_committed_with_its_four_files(split, cid):
    d = _committed(split, cid)
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_committed_case_is_the_factory_s(split, cid):
    f = _factory(split)[cid]
    d = _committed(split, cid)
    assert yaml.safe_load((d / "case.yaml").read_text()) == {
        "kind": f.kind, "fault": f.fault, "expect": f.expect, "design_system_active": True,
    }
    assert json.loads((d / "reference.json").read_text()) == f.reference
    assert json.loads((d / "calibration.json").read_text()) == {"should_fail": f.should_fail}


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_committed_payload_carries_the_stage_in_production_shape(split, cid):
    p = _load(split, cid).payload
    assert list(p) == PAYLOAD_KEYS
    assert set(PAYLOAD_KEYS) == set(MODEL_PAYLOAD_KEYS[AGENT]) - {"rejected_edit"}
    assert p["stage_slide"] == STAGE[split][cid]
    assert p == _expected_payload(split, cid)


@pytest.mark.parametrize("split", SPLITS)
def test_the_generator_lists_the_stage_messages(split):
    """Each generator's ``MESSAGES`` carries its split's stage messages, as for every other case."""
    m, h = _modules()
    gen = m if split == "train" else h
    assert {cid: gen.MESSAGES.get(cid) for cid in STAGE_CASE_IDS} == MESSAGES[split]


@pytest.mark.parametrize("split", SPLITS)
def test_every_other_committed_case_still_has_no_stage(split):
    cases = case.load_cases(AGENT, **case.split_kwargs(split))
    others = [c for c in cases if c.case_id not in STAGE_CASE_IDS]
    assert others
    for c in others:
        assert "stage_slide" in c.payload and c.payload["stage_slide"] is None, c.case_id


@pytest.mark.parametrize("split", SPLITS)
@pytest.mark.parametrize("cid", STAGE_CASE_IDS)
def test_the_committed_case_scores_as_the_contract_says(split, cid):
    c = _load(split, cid)
    cal = json.loads((_root(split) / cid / "calibration.json").read_text())["should_fail"]
    ok, why = expected_category_score(
        AGENT, c.reference, c.expect, reference=c.reference,
        current_deck_spec=c.payload["current_deck_spec"], design_system_active=c.design_system_active)
    assert ok, why
    ok, why = expected_category_score(
        AGENT, cal, c.expect, reference=c.reference,
        current_deck_spec=c.payload["current_deck_spec"], design_system_active=c.design_system_active)
    assert not ok and SHOULD_FAIL_REASON[cid] in why, why


@pytest.mark.parametrize("split", SPLITS)
def test_the_generator_writes_the_stage_cases_as_committed(split, tmp_path):
    m, h = _modules()
    (m if split == "train" else h).generate(out_dir=tmp_path)
    for cid in STAGE_CASE_IDS:
        assert (tmp_path / cid).is_dir(), f"{split}: the generator does not write {cid}"
        for name in FILES:
            assert (tmp_path / cid / name).read_bytes() == (_root(split) / cid / name).read_bytes(), (
                split, cid, name)

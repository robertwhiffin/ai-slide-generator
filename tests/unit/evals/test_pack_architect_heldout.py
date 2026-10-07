"""Self-tests for the architect HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec
from src.domain.skill_io import ArchitectOutput, DataRequest
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS
from src.services.template_sections import section_inventory

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "architect"
DECK = "heldout"
CASE_IDS = ["build_request", "edit_request", "ask_data", "confirm_design", "discuss"]
MUTATIONS = ["edit_request", "ask_data", "confirm_design"]
EXPECT = {
    "build_request": {"intent": "build"},
    "edit_request": {"intent": "edit", "positions": [2]},
    "ask_data": {"intent": "ask_data"},
    "confirm_design": {"intent": "confirm_design_contract"},
    "discuss": {"intent": "discuss"},
}
HAS_DECK = {"edit_request", "confirm_design", "discuss"}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
PAYLOAD_KEYS = {
    "conversation", "message", "current_deck_spec", "committed_slide_count",
    "previous_deck_review", "available_design_contract", "template_sections",
    "resolved_style", "design_system_library",
}
LAYOUT = case.EVALS_DIR / "fixtures/meridian/bundle/templates/standard/index.html"
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
CONFIRM_DESIGN_MESSAGE = "Can you re-theme this deck with the Acme design system instead?"
EDIT_POS = 2  # spec "Slide 3" = the four-patterns bullet slide


def _snapshot(root):
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module", autouse=True)
def generated(tmp_path_factory):
    """Generate the pack once into a tmp tree; tests read from it, never rewriting the committed tree."""
    global CASES
    from evals.packs.architect import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _msg(cid):
    return _load(cid).payload["message"]


def test_exactly_the_five_cases():
    cases = case.load_cases(AGENT, root=CASES)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    assert sorted(d.name for d in CASES.iterdir() if d.is_dir()) == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    assert sorted(p.name for p in (CASES / cid).iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = _load(cid)
    assert c.design_system_active is True
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert set(c.payload) == PAYLOAD_KEYS
    assert c.kind == ("mutation" if cid in MUTATIONS else "positive")
    assert (c.fault == "") == (c.kind == "positive")
    assert c.expect == EXPECT[cid]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = _load(cid).payload
    gold = case.gold_deck_spec(DECK)
    assert isinstance(p["message"], str) and p["message"]
    assert p["previous_deck_review"] is None
    assert p["available_design_contract"] == {
        "design_system_id": 3, "template_id": 5, "slide_style_id": None,
    }
    assert p["resolved_style"] == case.meridian_resolved_style()
    assert p["template_sections"] == section_inventory(LAYOUT.read_text())
    assert len(p["template_sections"]) == 4
    if cid in HAS_DECK:
        DeckSpec.model_validate(p["current_deck_spec"])
        assert p["current_deck_spec"] == gold
        assert p["committed_slide_count"] == 6
        assert len(p["conversation"]) == 3
        assert p["conversation"][0]["role"] == "user"
        assert p["conversation"][1]["role"] == "assistant"
    else:
        assert p["current_deck_spec"] is None
        assert p["committed_slide_count"] == 0
        assert len(p["conversation"]) == 1
    assert isinstance(p["committed_slide_count"], int)
    for turn in p["conversation"]:
        assert set(turn) == {"role", "content"}
        assert isinstance(turn["content"], str) and turn["content"]
    assert p["conversation"][-1] == {"role": "user", "content": p["message"]}


@pytest.mark.parametrize("cid", sorted(HAS_DECK))
def test_prior_exchange_is_about_the_prompt_deck_and_not_the_train_text(cid):
    from evals.packs.architect import mutations

    conv = _load(cid).payload["conversation"]
    assert "prompt" in conv[0]["content"].lower()
    assert "prompt" in conv[1]["content"].lower()
    assert conv[0]["content"] != mutations.PRIOR_USER
    assert conv[1]["content"] != mutations.PRIOR_ASSISTANT


@pytest.mark.parametrize("cid", CASE_IDS)
def test_design_system_library(cid):
    lib = _load(cid).payload["design_system_library"]
    assert len(lib) == 2
    by_id = {s["design_system_id"]: s for s in lib}
    assert set(by_id) == {3, 4}
    for s in lib:
        assert {"design_system_id", "name", "description", "is_default", "templates"} <= set(s)
        for t in s["templates"]:
            assert {"template_id", "name", "description"} <= set(t)
    assert by_id[3]["name"] == "Meridian Test Design System"
    assert [t["template_id"] for t in by_id[3]["templates"]] == [5]
    assert by_id[3]["templates"][0]["name"] == "Meridian Standard"
    assert by_id[4]["name"] == "Acme Test Design System"
    assert [t["template_id"] for t in by_id[4]["templates"]] == [7]
    assert by_id[4]["templates"][0]["name"] == "Acme Standard"


def test_messages():
    assert _msg("edit_request") == "On slide 3, show the four patterns as four cards instead of a bullet list"
    assert _msg("confirm_design") == CONFIRM_DESIGN_MESSAGE
    assert "Acme" in CONFIRM_DESIGN_MESSAGE and "design system" in CONFIRM_DESIGN_MESSAGE
    b = _msg("build_request").lower()
    assert "prompt" in b and "optimi" in b
    assert "engineer" in b and "product" in b
    a = _msg("ask_data").lower()
    assert "success rate" in a and "model" in a and "quarter" in a
    assert not re.search(r"\d", a), "ask_data must supply no figures"
    d = _msg("discuss").lower()
    assert "few-shot" in d and "chain-of-thought" in d
    assert d.rstrip().endswith("?")


def test_messages_differ_from_the_train_pack():
    from evals.packs.architect import mutations

    for cid in CASE_IDS:
        assert _msg(cid) != mutations.MESSAGES[cid], cid


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_validates_and_passes(cid):
    c = _load(cid)
    out = ArchitectOutput.model_validate(c.reference)
    assert out.intent == EXPECT[cid]["intent"]
    ok, why = expected_category_score(AGENT, c.reference, c.expect)
    assert ok, why


def test_build_reference_carries_the_deck2_spec():
    ref = _load("build_request").reference
    DeckSpec.model_validate(ref["deck_spec"])
    assert ref["deck_spec"] == case.gold_deck_spec(DECK)


def test_edit_reference_targets_one_zero_based_position():
    ref = _load("edit_request").reference
    assert ref["intent"] == "edit"
    assert ref["target_positions"] == [EDIT_POS]


def test_edit_slide_is_the_four_patterns_bullet_slide_in_deck2():
    brief = case.gold_deck_spec(DECK)["slides"][EDIT_POS]["content_brief"].lower()
    assert "bullet" in brief and "four" in brief


def test_edit_reference_revises_only_the_target_slide_brief():
    ref = _load("edit_request").reference
    DeckSpec.model_validate(ref["deck_spec"])
    gold = case.gold_deck_spec(DECK)
    spec = ref["deck_spec"]
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert len(spec["slides"]) == len(gold["slides"]) == 6
    for pos, (got, want) in enumerate(zip(spec["slides"], gold["slides"])):
        if pos != EDIT_POS:
            assert got == want, pos
    s, g = spec["slides"][EDIT_POS], gold["slides"][EDIT_POS]
    assert {k: v for k, v in s.items() if k != "content_brief"} == {k: v for k, v in g.items() if k != "content_brief"}
    brief = s["content_brief"].lower()
    assert brief != g["content_brief"].lower()
    assert "four cards" in brief or "4 cards" in brief
    assert "bullet slide" not in brief


def test_ask_data_reference_has_a_data_request():
    ref = _load("ask_data").reference
    assert DataRequest.model_validate(ref["data_request"]).metric
    assert not ref.get("deck_spec")


def test_confirm_design_reference_proposes_acme_without_a_deck_spec():
    ref = _load("confirm_design").reference
    assert ref["proposed_design_contract"]["design_system_id"] == 4
    assert ref["proposed_design_contract"]["template_id"] == 7
    assert ref["deck_spec"] is None


def test_confirm_design_reference_warns_every_slide_is_rebuilt():
    msg = _load("confirm_design").reference["message"].lower()
    assert "every slide" in msg and "rebuilt" in msg


def test_discuss_reference_has_no_payload():
    ref = _load("discuss").reference
    assert ref["intent"] == "discuss"
    assert not ref.get("deck_spec")
    assert not ref.get("data_request")
    assert not ref.get("target_positions")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_wrong_and_valid(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    ArchitectOutput.model_validate(bad)
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


@pytest.mark.parametrize("cid", [c for c in CASE_IDS if c != "edit_request"])
def test_calibration_has_the_wrong_intent(cid):
    assert _cal(cid)["should_fail"]["intent"] != EXPECT[cid]["intent"]


def test_edit_calibration_is_the_one_based_off_by_one():
    bad = _cal("edit_request")["should_fail"]
    assert bad["intent"] == "edit"
    assert bad["target_positions"] == [EDIT_POS + 1]


def test_generator_is_idempotent(generated):
    from evals.packs.architect import heldout

    before = dict(generated)
    heldout.generate(out_dir=CASES)
    assert _snapshot(CASES) == before


def test_committed_cases_are_current():
    """Committed cases_heldout tree is byte-identical to a fresh tmp generation (read-only on it)."""
    committed = _snapshot(COMMITTED)
    fresh = _snapshot(CASES)
    missing = set(fresh) - set(committed)
    extra = set(committed) - set(fresh)
    assert not missing and not extra, (
        f"File set mismatch: not committed={sorted(missing)}, stale committed={sorted(extra)}"
    )
    differing = sorted(p for p in fresh if fresh[p] != committed[p])
    assert not differing, f"Committed files differ from generated state: {differing}"

"""Self-tests for the architect eval pack (Task 14). Behavioural; no model, no network."""
import json

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckSpec
from src.domain.skill_io import ArchitectOutput, DataRequest
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS
from src.services.template_sections import section_inventory

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "architect"
CASE_IDS = ["build_request", "edit_request", "ask_data", "confirm_design", "discuss"]
MUTATIONS = ["edit_request", "ask_data", "confirm_design"]
EXPECT = {
    "build_request": {"intent": "build"},
    "edit_request": {"intent": "edit", "positions": [1]},
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


COMMITTED = PACK_DIR / "cases"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module (I9)


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
    from evals.packs.architect import mutations

    CASES = tmp_path_factory.mktemp(AGENT) / "cases"
    mutations.generate(out_dir=CASES)
    return _snapshot(CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def test_exactly_the_five_cases():
    cases = case.load_cases(AGENT, root=CASES)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    dirs = sorted(d.name for d in CASES.iterdir() if d.is_dir())
    assert dirs == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    d = CASES / cid
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.design_system_active is True
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert set(c.payload) == PAYLOAD_KEYS
    assert c.kind == ("mutation" if cid in MUTATIONS else "positive")
    assert (c.fault == "") == (c.kind == "positive")
    assert c.expect == EXPECT[cid]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = case.load_case(AGENT, cid, root=CASES).payload
    gold = case.gold_deck_spec()
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
        assert p["committed_slide_count"] == 10
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
    # Last turn is the current user message.
    assert p["conversation"][-1] == {"role": "user", "content": p["message"]}


@pytest.mark.parametrize("cid", CASE_IDS)
def test_design_system_library(cid):
    lib = case.load_case(AGENT, cid, root=CASES).payload["design_system_library"]
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
    def msg(cid):
        return case.load_case(AGENT, cid, root=CASES).payload["message"]

    assert msg("edit_request") == "On slide 2, replace the bullet list with three stat cards"
    assert msg("confirm_design") == "Switch this deck to the Acme design system"
    assert msg("discuss") == "What's the difference between Reveal.js and Slidev?"
    assert "Q3 revenue by region" in msg("ask_data") and "Q2" in msg("ask_data")
    b = msg("build_request").lower()
    assert "html" in b and "powerpoint" in b


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_validates_and_passes(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    out = ArchitectOutput.model_validate(c.reference)
    assert out.intent == EXPECT[cid]["intent"]
    ok, why = expected_category_score(AGENT, c.reference, c.expect)
    assert ok, why


def test_build_reference_carries_the_gold_spec():
    ref = case.load_case(AGENT, "build_request", root=CASES).reference
    DeckSpec.model_validate(ref["deck_spec"])
    assert ref["deck_spec"] == case.gold_deck_spec()


def test_edit_reference_targets_one_zero_based_position():
    ref = case.load_case(AGENT, "edit_request", root=CASES).reference
    assert ref["target_positions"] == [1]


def test_ask_data_reference_has_a_data_request():
    ref = case.load_case(AGENT, "ask_data", root=CASES).reference
    assert DataRequest.model_validate(ref["data_request"]).metric
    assert not ref.get("deck_spec")


def test_confirm_design_reference_proposes_acme_without_a_deck_spec():
    ref = case.load_case(AGENT, "confirm_design", root=CASES).reference
    assert ref["proposed_design_contract"]["design_system_id"] == 4
    assert ref["proposed_design_contract"]["template_id"] == 7
    assert ref["deck_spec"] is None


def test_discuss_reference_has_no_payload():
    ref = case.load_case(AGENT, "discuss", root=CASES).reference
    assert ref["intent"] == "discuss"
    assert not ref.get("deck_spec")
    assert not ref.get("data_request")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_wrong_and_valid(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)["should_fail"]
    ArchitectOutput.model_validate(bad)
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


@pytest.mark.parametrize("cid", [c for c in CASE_IDS if c != "edit_request"])
def test_calibration_has_the_wrong_intent(cid):
    bad = _cal(cid)["should_fail"]
    assert bad["intent"] != EXPECT[cid]["intent"]


def test_edit_calibration_is_the_one_based_off_by_one():
    bad = _cal("edit_request")["should_fail"]
    assert bad["intent"] == "edit"
    assert set(bad["target_positions"]) == {2}


def test_generator_is_idempotent(generated):
    from evals.packs.architect import mutations

    before = dict(generated)
    mutations.generate(out_dir=CASES)
    assert _snapshot(CASES) == before


def test_committed_cases_are_current():
    """The committed tree is byte-identical to a fresh generation (same file set, same bytes).

    Read-only on the committed tree: the fresh generation lives in the module's tmp tree.
    """
    committed = _snapshot(COMMITTED)
    fresh = _snapshot(CASES)
    missing = set(fresh) - set(committed)
    extra = set(committed) - set(fresh)
    assert not missing and not extra, (
        f"File set mismatch: not committed={sorted(missing)}, stale committed={sorted(extra)}"
    )
    differing = sorted(p for p in fresh if fresh[p] != committed[p])
    assert not differing, f"Committed files differ from generated state: {differing}"


def _prompt():
    return (PACK_DIR / "judge_prompt.md").read_text()


def test_judge_prompt_placeholders():
    text = _prompt()
    assert "{{ outputs }}" in text
    assert "{{ expectations }}" in text


def test_judge_prompt_verdict_before_rationale():
    text = _prompt()
    assert "FIRST" in text and text.index("FIRST") < text.index("rationale", text.index("FIRST"))


def test_judge_prompt_handles_build_and_other_intents():
    text = _prompt().lower()
    assert "build" in text
    for word in ("argument", "arc", "brief"):
        assert word in text
    assert "ballpark" in text or "similar number" in text or "comparable" in text
    assert "example" in text and "template" in text  # reference is an example, not a template
    assert "intent" in text and "consistent" in text
    for other in ("edit", "ask_data", "confirm_design_contract", "discuss"):
        assert other in text


def test_judge_prompt_does_not_require_a_planted_fault():
    text = _prompt().lower()
    assert "pass" in text and "fail" in text
    assert "no deck_spec" in text or "no payload" in text


def test_confirm_design_reference_warns_every_slide_is_rebuilt():
    # src/core/skills/architect.py: a design-contract proposal must "say plainly
    # that every slide will be rebuilt" — the known-good output must do so too.
    msg = case.load_case(AGENT, "confirm_design", root=CASES).reference["message"].lower()
    assert "every slide" in msg and "rebuilt" in msg


def test_edit_slide_is_a_bullet_list_in_the_gold():
    # The edit case is fair only if gold position 1 really is a bullet-list slide.
    assert '<ul class="bullets">' in case.gold_slide(1)
    assert "bullet" in case.gold_deck_spec()["slides"][1]["content_brief"].lower()


def test_judge_prompt_allows_a_revised_deck_spec_on_edit():
    # The builder sees only slide_spec, so an edit that revises the target brief
    # is the better answer; the judge must not fail it as a payload mismatch.
    text = _prompt().lower()
    edit_line = next(l for l in text.splitlines() if l.startswith("- edit:"))
    assert "deck_spec" in edit_line and "acceptable" in edit_line


def test_judge_prompt_fails_a_build_that_misses_the_request():
    text = _prompt().lower()
    build_line = next(l for l in text.splitlines() if l.startswith("- build:"))
    assert "purpose" in build_line and "argument" in build_line
    assert "contradicts the user's request" in build_line


# ---- USER RULING: a content-changing edit must carry the updated deck spec ----

def test_edit_reference_revises_only_the_target_slide_brief():
    ref = case.load_case(AGENT, "edit_request", root=CASES).reference
    assert ref["intent"] == "edit" and ref["target_positions"] == [1]
    DeckSpec.model_validate(ref["deck_spec"])
    gold = case.gold_deck_spec()
    spec = ref["deck_spec"]
    # Every field and every other slide is unchanged ...
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert len(spec["slides"]) == len(gold["slides"])
    for pos, (got, want) in enumerate(zip(spec["slides"], gold["slides"])):
        if pos != 1:
            assert got == want, pos
    # ... and on position 1 only content_brief changes, now asking for three stat cards.
    s1, g1 = spec["slides"][1], gold["slides"][1]
    assert {k: v for k, v in s1.items() if k != "content_brief"} == {k: v for k, v in g1.items() if k != "content_brief"}
    brief = s1["content_brief"].lower()
    assert brief != g1["content_brief"].lower()
    assert "three stat cards" in brief
    assert "in place of the bullet list" in brief
    assert "use bullet points" not in brief


def test_edit_calibration_still_fails_on_the_off_by_one():
    c = case.load_case(AGENT, "edit_request", root=CASES)
    bad = _cal("edit_request")["should_fail"]
    assert bad["target_positions"] == [2]
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert not ok


def test_judge_prompt_fails_an_edit_without_the_updated_deck_spec():
    edit_line = next(l for l in _prompt().lower().splitlines() if l.startswith("- edit:"))
    assert "deck_spec is null" in edit_line and "fail" in edit_line
    assert "does not reflect the requested change" in edit_line
    assert "pass" in edit_line and "delivers the request" in edit_line
    assert "may leave deck_spec null" not in edit_line

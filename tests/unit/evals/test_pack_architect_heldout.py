"""Self-tests for the architect HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import hashlib
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
EXISTING_CASE_IDS = ["build_request", "edit_request", "ask_data", "confirm_design", "discuss"]
# #313: intent and slide-reference cases on deck 2 (plan Appendix H).
NEW_CASE_IDS = ["edit_polite_ordinal", "edit_last_slide", "edit_multi_slide", "discuss_slide_question"]
CASE_IDS = EXISTING_CASE_IDS + NEW_CASE_IDS
MUTATIONS = ["edit_request", "ask_data", "confirm_design"] + NEW_CASE_IDS
EXPECT = {
    "build_request": {"intent": "build"},
    "edit_request": {"intent": "edit", "positions": [2]},
    "ask_data": {"intent": "ask_data"},
    "confirm_design": {"intent": "confirm_design_contract"},
    "discuss": {"intent": "discuss"},
    "edit_polite_ordinal": {"intent": "edit", "positions": [3]},
    "edit_last_slide": {"intent": "edit", "positions": [5]},
    "edit_multi_slide": {"intent": "edit", "positions": [1, 2]},
    "discuss_slide_question": {"intent": "discuss"},
}
HAS_DECK = {"edit_request", "confirm_design", "discuss"} | set(NEW_CASE_IDS)
EDIT_CASES = [c for c in CASE_IDS if EXPECT[c]["intent"] == "edit"]
# Position cases whose calibration is the reference with every target slipped by +1 (D7).
SLIPPED = ["edit_last_slide", "edit_multi_slide"]
# D7: adding the #313 cases leaves the five existing cases byte-identical. Digests of the files at
# 679d2f21. Task 7 regenerates payload.json on purpose and re-pins those five entries.
EXISTING_CASE_SHA256 = {
    "ask_data/calibration.json": "0761dfd021fbf5f9abaa73c0fe33735f16f0d3afce5be5bc46a0d9252f7fd086",
    "ask_data/case.yaml": "507b1f55e8479b02535af8ba1363b7a76bc3ef2d3310849f9af3aca51c17abe6",
    "ask_data/payload.json": "75ffca76ebf5258295ecc8a0eef920955efa6d0e1e809dbfd25bf0e4b75c3c96",
    "ask_data/reference.json": "ac10a07cfa840c55f0b001da058fcfe69788e952eb3fe9fd4b334ecb929e7f9d",
    "build_request/calibration.json": "cdb0f35e3df90091bdff95ab7abbac7648396d6cb2b3aaaa148a8c35b38a4f33",
    "build_request/case.yaml": "02e9256188dad0c24a724a740f8acfa2fe033d9ff87ba3bc8bd0c0a2af47eece",
    "build_request/payload.json": "32cca43ea663ff1b1ded2d261a17b7d2c1e4730529e80d18404d40c085d2d020",
    "build_request/reference.json": "0654e2384ebf821758a19de285f93835cd8671ec22c7d0e43f06a61e55478353",
    "confirm_design/calibration.json": "5ea6b080af5b98f76ee31f9b643e48c4b2f240cc22a293d633fc84e34b75797e",
    "confirm_design/case.yaml": "d927b9058811d5f15b1527bdc02317f051b9386454b5c69e3c0603bea11b643c",
    "confirm_design/payload.json": "ff4ddcc32df99616d17eb4b8b6067e45d5c28a2a7b997eff25ac2fe18b955bf8",
    "confirm_design/reference.json": "1122933fdd9c1de6730cc223afb2e2433707c44142f096292569142430a6b561",
    "discuss/calibration.json": "e01f882c09c3384f9b4565ab26cb72142cfe4a58e1e38eb38ff8f8fe93cfe55d",
    "discuss/case.yaml": "b9ad94d1a9ae20949f243b129567a851d2fee203060316c484e4da3b90fa11ad",
    "discuss/payload.json": "485ed0068396fba19c377fc90f079add1ef23b4c8811df1773e902ad99233777",
    "discuss/reference.json": "5ef4db19eed1ad91be6f450adf2ae4ec98b9718c6549508e32c24f5afcf83d1b",
    "edit_request/calibration.json": "fd4e02823ed246c61f282241df69db24d66d4d4a5bf55bfa7eb7b82fb96517e2",
    "edit_request/case.yaml": "9c7e0a4e6b67b67b46139d1780b4fd0b4fbeddafa574bae1a9c3720cf686c798",
    "edit_request/payload.json": "b6c0c8629eb88e01fed8d07b5baffe68670b5534da20390e36af3aff05db82af",
    "edit_request/reference.json": "0bc3d02b7cd26ed26aadabb564099fac6665e31d2be8ce7d4bae4b05f90d3112",
}
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


def test_exactly_the_pinned_cases():
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
    assert _msg("edit_polite_ordinal") == (
        "Would you mind making the 4th slide lead with the 3-5 iteration rounds?"
    )
    assert _msg("edit_last_slide") == (
        "The final slide should open with the call to action, before the checklist"
    )
    assert _msg("edit_multi_slide") == "Slides 2 and 3 are too dense — drop the callouts on both"
    assert _msg("discuss_slide_question") == "Why does slide 2 come before the techniques?"


@pytest.mark.parametrize("cid", NEW_CASE_IDS)
def test_new_cases_continue_the_existing_prior_exchange(cid):
    prior = _load("edit_request").payload["conversation"][:2]
    assert _load(cid).payload["conversation"][:2] == prior


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


# ---- #313: the edit references revise only their target slides ----

def _by_position(spec):
    return {s["position"]: s for s in spec["slides"]}


@pytest.mark.parametrize("cid", EDIT_CASES)
def test_edit_references_revise_only_their_targets(cid):
    ref = _load(cid).reference
    assert ref["intent"] == "edit"
    targets = EXPECT[cid]["positions"]
    assert sorted(ref["target_positions"]) == targets
    spec = ref["deck_spec"]
    DeckSpec.model_validate(spec)
    gold = case.gold_deck_spec(DECK)
    # Deck-level fields are the gold's ...
    assert {k: v for k, v in spec.items() if k != "slides"} == {k: v for k, v in gold.items() if k != "slides"}
    assert [s["position"] for s in spec["slides"]] == [s["position"] for s in gold["slides"]]
    got, want = _by_position(spec), _by_position(gold)
    for pos in want:
        if pos not in targets:
            assert got[pos] == want[pos], pos  # ... and so is every non-target slide.
            continue
        changed = {k for k in want[pos] if got[pos].get(k) != want[pos][k]} | (set(got[pos]) - set(want[pos]))
        # No held-out target slide's purpose changes (Appendix H): only the brief is revised.
        assert changed == {"content_brief"}, (pos, changed)
    if cid == "edit_request":
        brief = got[EDIT_POS]["content_brief"].lower()
        assert "four cards" in brief or "4 cards" in brief
    elif cid == "edit_polite_ordinal":
        brief = got[3]["content_brief"]
        assert "headline stat" in brief
        assert "leads with typical iteration cycles" in brief
    elif cid == "edit_last_slide":
        brief = got[5]["content_brief"]
        assert "opens with the call to action" in brief
        assert "five-item" in brief
    elif cid == "edit_multi_slide":
        for pos in (1, 2):
            assert got[pos]["content_brief"].endswith("with no callout"), pos
    else:
        pytest.fail(f"no brief markers pinned for {cid}")


def test_new_cases_are_fair_on_the_gold():
    """Each #313 request asks for a real change to what the deck-2 gold slide actually holds."""
    slides = _by_position(case.gold_deck_spec(DECK))
    assert max(slides) == 5 and len(slides) == 6  # "the final slide" is position 5
    # The stat the request names is not already first on the 4th slide.
    stats = slides[3]["content_brief"]
    assert stats.index("iteration cycles") > stats.index("token cost reduction")
    # The final slide puts the checklist before the call to action.
    closing = slides[5]["content_brief"]
    assert closing.index("five-item") < closing.index("call to action")
    assert "callout" in slides[1]["content_brief"]
    assert "callout" in slides[2]["content_brief"]
    assert "techniques" in slides[2]["purpose"]


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


@pytest.mark.parametrize("cid", ["discuss", "discuss_slide_question"])
def test_discuss_reference_has_no_payload(cid):
    ref = _load(cid).reference
    assert ref["intent"] == "discuss"
    assert not ref.get("deck_spec")
    assert not ref.get("data_request")
    assert not ref.get("target_positions")
    assert not ref.get("proposed_design_contract")


def test_slide_question_reference_answers_about_the_named_slide():
    # The message speaks 1-indexed (architect.py SLIDE NUMBERS): slide 2 is deck-2 position 1.
    msg = _load("discuss_slide_question").reference["message"]
    assert "Slide 2" in msg
    assert "techniques" in msg


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_wrong_and_valid(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    ArchitectOutput.model_validate(bad)
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


@pytest.mark.parametrize("cid", [c for c in CASE_IDS if c not in ("edit_request", *SLIPPED)])
def test_calibration_has_the_wrong_intent(cid):
    assert _cal(cid)["should_fail"]["intent"] != EXPECT[cid]["intent"]


def test_polite_ordinal_calibration_asks_instead_of_acting():
    bad = _cal("edit_polite_ordinal")["should_fail"]
    assert bad["intent"] == "discuss"
    assert bad["deck_spec"] is None
    assert bad["target_positions"] == []
    assert bad["data_request"] is None and bad["proposed_design_contract"] is None


def test_slide_question_calibration_acts_instead_of_answering():
    bad = _cal("discuss_slide_question")["should_fail"]
    assert bad["intent"] == "edit"
    assert bad["target_positions"] == [1]
    assert bad["deck_spec"] is None


@pytest.mark.parametrize("cid", SLIPPED)
def test_slipped_calibrations(cid):
    """The realistic wrong answer to a position case: the reference with every target slipped by +1."""
    ref = _load(cid).reference
    bad = _cal(cid)["should_fail"]
    targets = ref["target_positions"]
    assert sorted(targets) == EXPECT[cid]["positions"]
    assert bad["target_positions"] == [p + 1 for p in targets]
    assert {k: v for k, v in bad.items() if k != "target_positions"} == {
        k: v for k, v in ref.items() if k != "target_positions"
    }


def test_edit_calibration_is_the_one_based_off_by_one():
    bad = _cal("edit_request")["should_fail"]
    assert bad["intent"] == "edit"
    assert bad["target_positions"] == [EDIT_POS + 1]


def test_existing_cases_are_byte_identical(generated):
    got = {
        path: hashlib.sha256(data).hexdigest()
        for path, data in generated.items()
        if path.split("/")[0] in EXISTING_CASE_IDS
    }
    assert got == EXISTING_CASE_SHA256


def test_generator_is_idempotent(generated):
    from evals.packs.architect import heldout

    before = dict(generated)
    heldout.generate(out_dir=CASES)
    assert _snapshot(CASES) == before


def test_default_output_is_the_heldout_tree_not_train():
    """generate() with no out_dir must write cases_heldout, never the train cases tree."""
    from evals.packs.architect import heldout, mutations

    assert heldout.CASES_DIR == case.cases_dir(AGENT, split="heldout") == COMMITTED
    assert heldout.CASES_DIR != mutations.CASES_DIR


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

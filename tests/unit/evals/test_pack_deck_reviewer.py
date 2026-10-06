"""Self-tests for the deck_reviewer eval pack (Task 13). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS
from src.utils.graph_safety import spotlight_prior_slides

from evals.harness import case
from evals.harness.scorers import expected_category_score

AGENT = "deck_reviewer"
CASE_IDS = ["clean", "arc_gap_drop_objections", "repetition", "missing_conclusion", "out_of_order"]
MUTATIONS = [c for c in CASE_IDS if c != "clean"]
EXPECT = {
    "clean": {"criteria": [], "positions": []},
    "arc_gap_drop_objections": {"criteria": ["arc_gap"], "positions": [-1]},
    "repetition": {"criteria": ["cross_slide_repetition"], "positions": [-1]},
    "missing_conclusion": {"criteria": ["missing_conclusion"], "positions": [-1]},
    "out_of_order": {"criteria": ["arc_gap"], "positions": [-1]},
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
PAYLOAD_KEYS = {"narrative_arc", "call_to_action", "slide_count", "slides"}


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
    from evals.packs.deck_reviewer import mutations

    CASES = tmp_path_factory.mktemp(AGENT) / "cases"
    mutations.generate(out_dir=CASES)
    return _snapshot(CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _gold(pos):
    return case.gold_slide(pos)


def _gold_all():
    return [_gold(i) for i in range(10)]


def _slides(cid):
    return case.load_case(AGENT, cid, root=CASES).payload["slides"]


def _order(slides, *htmls):
    return [slides.index(h) for h in htmls]


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
    assert set(c.payload) == PAYLOAD_KEYS == set(MODEL_PAYLOAD_KEYS[AGENT])
    assert c.kind == ("positive" if cid == "clean" else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    """Production sends `slides` as ONE spotlighted string, not a list of {position, html}."""
    c = case.load_case(AGENT, cid, root=CASES)
    p = c.payload
    spec = case.gold_deck_spec()
    assert isinstance(p["slides"], str)
    assert isinstance(p["slide_count"], int)
    assert p["narrative_arc"] == spec["narrative_arc"]
    assert p["call_to_action"] == spec["call_to_action"]
    # slide_count agrees with the number of spotlighted slides actually present.
    assert p["slide_count"] == p["slides"].count("<untrusted-data")


EXPECTED_HTMLS = {
    "clean": lambda g: list(g),
    "arc_gap_drop_objections": lambda g: g[:8] + g[9:],
    "missing_conclusion": lambda g: g[:9],
    "out_of_order": lambda g: [g[0], g[1], g[7], g[3], g[4], g[5], g[6], g[2], g[8], g[9]],
}


@pytest.mark.parametrize("cid", list(EXPECTED_HTMLS))
def test_slides_string_is_spotlight_of_the_planned_slide_order(cid):
    g = _gold_all()
    htmls = EXPECTED_HTMLS[cid](g)
    p = case.load_case(AGENT, cid, root=CASES).payload
    assert p["slides"] == spotlight_prior_slides(htmls, None)
    assert p["slide_count"] == len(htmls)


def test_repetition_slides_string_matches_its_own_slide_count():
    p = case.load_case(AGENT, "repetition", root=CASES).payload
    assert p["slide_count"] == 10
    assert p["slides"] != spotlight_prior_slides(_gold_all(), None)
    # 10 slides spotlighted = same number of spotlight blocks as the clean deck.
    clean = case.load_case(AGENT, "clean", root=CASES).payload["slides"]
    assert p["slides"].count("<untrusted-data") == clean.count("<untrusted-data") == 10


def test_clean_is_all_ten_gold_slides():
    p = case.load_case(AGENT, "clean", root=CASES).payload
    assert p["slide_count"] == 10
    assert p["slides"] == spotlight_prior_slides(_gold_all(), None)


def test_arc_gap_drops_the_objections_slide():
    p = case.load_case(AGENT, "arc_gap_drop_objections", root=CASES).payload
    assert p["slide_count"] == 9
    assert _gold(8) not in p["slides"]
    for i in (0, 1, 2, 3, 4, 5, 6, 7, 9):
        assert _gold(i) in p["slides"]


def test_missing_conclusion_drops_the_verdict_slide():
    p = case.load_case(AGENT, "missing_conclusion", root=CASES).payload
    assert p["slide_count"] == 9
    assert _gold(9) not in p["slides"]
    for i in range(9):
        assert _gold(i) in p["slides"]


def test_out_of_order_swaps_positions_two_and_seven():
    p = case.load_case(AGENT, "out_of_order", root=CASES).payload
    s = p["slides"]
    assert p["slide_count"] == 10
    assert _gold(2) in s and _gold(7) in s
    i2, i7 = _order(s, _gold(2), _gold(7))
    assert i7 < i2, "gold 7 should now precede gold 2"
    # Everything else keeps its slot relative to the untouched slides.
    untouched = [_gold(i) for i in (0, 1, 3, 4, 5, 6, 8, 9)]
    pos = _order(s, *untouched)
    assert pos == sorted(pos)
    # Slot check: gold 7 sits between gold 1 and gold 3; gold 2 between gold 6 and gold 8.
    assert _order(s, _gold(1))[0] < i7 < _order(s, _gold(3))[0]
    assert _order(s, _gold(6))[0] < i2 < _order(s, _gold(8))[0]


def test_repetition_plants_a_duplicate_point():
    p = case.load_case(AGENT, "repetition", root=CASES).payload
    s = p["slides"]
    assert p["slide_count"] == 10
    # Gold position 5's content is gone...
    assert _gold(5) not in s
    assert "HTML slides are genuinely interactive" not in s
    # ...and a content block from another gold slide (position 7's bullet list) now appears twice.
    block = re.search(r'<ul class="bullets">.*?</ul>', _gold(7), re.S).group(0)
    assert s.count(block) == 2
    assert s.count(block) > spotlight_prior_slides(_gold_all(), None).count(block)
    # The other eight untouched slides are still present.
    for i in (0, 1, 2, 3, 4, 6, 7, 8, 9):
        assert _gold(i) in s


@pytest.mark.parametrize("cid", CASE_IDS)
def test_expect_matches_brief(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA
        assert CRITERIA[crit].objective is False
        assert crit in ("arc_gap", "cross_slide_repetition", "missing_conclusion")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_shape_and_passes(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    ref = c.reference
    assert set(ref) == {"findings"}
    for f in ref["findings"]:
        Finding.model_validate(f)
        assert f["slide_index"] == -1
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why
    if cid == "clean":
        assert ref["findings"] == []
    else:
        assert {f["criterion"] for f in ref["findings"]} >= set(c.expect["criteria"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_deck_reviewer_shaped(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)["should_fail"]
    assert set(bad) == {"findings"}
    for f in bad["findings"]:
        Finding.model_validate(f)
    assert bad != c.reference


@pytest.mark.parametrize("cid", MUTATIONS)
def test_mutation_calibration_fails_and_misses_the_planted_criterion(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)["should_fail"]
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"
    planted = set(EXPECT[cid]["criteria"])
    assert not (planted & {f["criterion"] for f in bad["findings"]})


def test_clean_calibration_invents_a_deck_finding():
    """Deck criteria are subjective, so the scorer passes extras; the JUDGE must fail this."""
    c = case.load_case(AGENT, "clean", root=CASES)
    bad = _cal("clean")["should_fail"]
    assert c.reference["findings"] == []
    assert len(bad["findings"]) >= 1
    assert "arc_gap" in {f["criterion"] for f in bad["findings"]}


def test_generator_is_idempotent(generated):
    from evals.packs.deck_reviewer import mutations

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


def test_judge_prompt_placeholders():
    text = (PACK_DIR / "judge_prompt.md").read_text()
    assert "{{ outputs }}" in text
    assert "{{ expectations }}" in text


def test_judge_prompt_does_not_fail_the_clean_reference():
    """The judge runs on every row, including `clean`, whose reference has no findings."""
    text = (PACK_DIR / "judge_prompt.md").read_text()
    assert "reference has no findings" in text
    assert "Fail if there are no findings" not in text
    # Verdict first, then rationale.
    assert "FIRST" in text and text.index("FIRST") < text.index("rationale", text.index("FIRST"))


def test_judge_prompt_fails_an_invented_finding_on_the_clean_case():
    text = (PACK_DIR / "judge_prompt.md").read_text().lower()
    i = text.index("reference has no findings")
    window = text[max(0, i - 300): i + 600]
    assert "fail" in window and "pass" in window
    assert any(w in window for w in ("invent", "spurious", "unsupported"))

"""Self-tests for the deck_reviewer HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
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
DECK = "heldout"
CASE_IDS = ["clean", "arc_gap_drop_workflow", "missing_conclusion", "out_of_order", "repetition"]
MUTATIONS = [c for c in CASE_IDS if c != "clean"]
EXPECT = {
    "clean": {"criteria": [], "positions": []},
    "arc_gap_drop_workflow": {"criteria": ["arc_gap"], "positions": [-1]},
    "missing_conclusion": {"criteria": ["missing_conclusion"], "positions": [-1]},
    "out_of_order": {"criteria": ["arc_gap"], "positions": [-1]},
    "repetition": {"criteria": ["cross_slide_repetition"], "positions": [-1]},
}
# Which gold positions appear, in order. "R" marks the replacement slide in `repetition`.
ORDER = {
    "clean": [0, 1, 2, 3, 4, 5],
    "arc_gap_drop_workflow": [0, 1, 2, 3, 5],
    "missing_conclusion": [0, 1, 2, 3, 4],
    "out_of_order": [0, 1, 4, 3, 2, 5],
    "repetition": [0, 1, "R", 3, 4, 5],
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
COMMITTED = PACK_DIR / "cases_heldout"
PAYLOAD_KEYS = {"narrative_arc", "call_to_action", "slide_count", "slides"}
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
BLOCK_RE = re.compile(r'<untrusted-data[^>]*>\n(.*?)\n</untrusted-data>', re.S)
TITLE_RE = re.compile(r'<h[12] class="slide-title"[^>]*>(.*?)</h[12]>', re.S)
BULLETS_RE = re.compile(r'<ul class="bullets">.*?</ul>', re.S)


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
    from evals.packs.deck_reviewer import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _gold(pos):
    return case.gold_slide(pos, DECK)


def _gold_title(pos):
    return TITLE_RE.search(_gold(pos)).group(1)


def _blocks(cid):
    return BLOCK_RE.findall(_load(cid).payload["slides"])


def _identify(block):
    """Map one slide's HTML to its gold position, or 'R' for a non-gold replacement slide."""
    hits = [i for i in range(6) if _gold_title(i) in block]
    assert len(hits) <= 1, f"slide matches several gold titles: {hits}"
    return hits[0] if hits else "R"


def _order(cid):
    return [_identify(b) for b in _blocks(cid)]


def test_gold_titles_are_distinct_markers():
    """Each gold title occurs in exactly one gold slide, so title location identifies a slide."""
    for i in range(6):
        assert sum(_gold_title(i) in _gold(j) for j in range(6)) == 1


def test_exactly_the_five_cases():
    cases = case.load_cases(AGENT, root=CASES, split="heldout")
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    assert sorted(d.name for d in CASES.iterdir() if d.is_dir()) == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    assert sorted(p.name for p in (CASES / cid).iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = _load(cid)
    assert c.design_system_active is True
    assert set(c.payload) == PAYLOAD_KEYS == set(MODEL_PAYLOAD_KEYS[AGENT])
    assert c.kind == ("positive" if cid == "clean" else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_is_the_production_shape(cid):
    p = _load(cid).payload
    spec = case.gold_deck_spec(DECK)
    assert isinstance(p["slides"], str)
    assert isinstance(p["slide_count"], int) and not isinstance(p["slide_count"], bool)
    assert p["narrative_arc"] == spec["narrative_arc"]
    assert len(p["narrative_arc"]) == 5
    assert p["call_to_action"] == spec["call_to_action"]
    assert p["slide_count"] == p["slides"].count("<untrusted-data") == len(ORDER[cid])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_order_is_pinned(cid):
    assert _order(cid) == ORDER[cid]


@pytest.mark.parametrize("cid", [c for c in CASE_IDS if c != "repetition"])
def test_slides_string_is_spotlight_of_the_planned_gold_order(cid):
    htmls = [_gold(i) for i in ORDER[cid]]
    p = _load(cid).payload
    assert p["slides"] == spotlight_prior_slides(htmls, None)
    assert p["slide_count"] == len(htmls)


def test_repetition_other_slides_are_untouched_gold_in_order():
    bl = _blocks("repetition")
    assert len(bl) == 6
    htmls = [_gold(0), _gold(1), bl[2], _gold(3), _gold(4), _gold(5)]
    assert _load("repetition").payload["slides"] == spotlight_prior_slides(htmls, None)


def test_clean_is_all_six_gold_slides():
    p = _load("clean").payload
    assert p["slide_count"] == 6
    assert p["slides"] == spotlight_prior_slides([_gold(i) for i in range(6)], None)


def test_arc_gap_drops_exactly_the_workflow_slide():
    s = _load("arc_gap_drop_workflow").payload["slides"]
    assert _gold_title(4) not in s
    assert '>Workflow<' not in s
    for i in (0, 1, 2, 3, 5):
        assert _gold(i) in s


def test_missing_conclusion_drops_exactly_the_action_plan():
    s = _load("missing_conclusion").payload["slides"]
    assert _gold_title(5) not in s
    assert '>Action Plan<' not in s
    for i in range(5):
        assert _gold(i) in s


def test_out_of_order_swaps_positions_two_and_four():
    s = _load("out_of_order").payload["slides"]
    assert all(_gold(i) in s for i in range(6))
    idx = {i: s.index(_gold(i)) for i in range(6)}
    assert idx[4] < idx[3] < idx[2], "workflow must now precede impact and patterns"
    assert idx[1] < idx[4] and idx[2] < idx[5]
    assert idx[0] < idx[1]


def test_repetition_plants_a_verbatim_duplicate_block():
    p = _load("repetition").payload
    s = p["slides"]
    assert p["slide_count"] == 6
    block = BULLETS_RE.search(_gold(1)).group(0)
    assert s.count(block) == 2
    clean = _load("clean").payload["slides"]
    assert clean.count(block) == 1
    # Gold position 2 is gone entirely, including its distinctive text.
    assert _gold_title(2) not in s
    assert _gold(2) not in s
    assert ">Prompt Design Patterns<" not in s
    # The replacement has its own eyebrow and title, distinct from every gold slide.
    rep = _blocks("repetition")[2]
    assert block in rep
    assert _identify(rep) == "R"
    t = TITLE_RE.search(rep)
    assert t and t.group(1).strip()
    assert all(t.group(1) != _gold_title(i) for i in range(6))
    eb = re.search(r'class="eyebrow"[^>]*>(.*?)<', rep, re.S)
    assert eb and eb.group(1).strip()
    gold_eyebrows = {re.search(r'class="eyebrow"[^>]*>(.*?)<', _gold(i), re.S).group(1) for i in range(6)}
    assert eb.group(1) not in gold_eyebrows
    # Only position 1's block is duplicated; the other untouched slides stay put.
    for i in (0, 1, 3, 4, 5):
        assert _gold(i) in s


@pytest.mark.parametrize("cid", CASE_IDS)
def test_expect_matches_brief(cid):
    c = _load(cid)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA
        assert CRITERIA[crit].objective is False


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_shape_and_passes(cid):
    c = _load(cid)
    ref = c.reference
    assert set(ref) == {"findings"}
    for f in ref["findings"]:
        Finding.model_validate(f)
        assert f["slide_index"] == -1
        crit = CRITERIA[f["criterion"]]
        assert f["category"] == crit.category
        assert f["objective"] == crit.objective
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why
    if cid == "clean":
        assert ref["findings"] == []
    else:
        assert len(ref["findings"]) == 1
        assert ref["findings"][0]["criterion"] == EXPECT[cid]["criteria"][0]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_deck_reviewer_shaped(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    assert set(bad) == {"findings"}
    for f in bad["findings"]:
        Finding.model_validate(f)
    assert bad != c.reference


@pytest.mark.parametrize("cid", MUTATIONS)
def test_mutation_calibration_is_empty_and_fails_the_scorer(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    assert bad == {"findings": []}
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


def test_clean_calibration_invents_a_deck_finding_that_only_the_judge_can_fail():
    c = _load("clean")
    bad = _cal("clean")["should_fail"]
    assert c.reference["findings"] == []
    assert len(bad["findings"]) == 1
    assert bad["findings"][0]["criterion"] == "arc_gap"
    assert bad["findings"][0]["slide_index"] == -1
    # Deck criteria are subjective, so the scorer passes the spurious finding; the judge must fail it.
    ok, _ = expected_category_score(AGENT, bad, c.expect)
    assert ok


@pytest.mark.parametrize("cid", MUTATIONS)
def test_reference_messages_do_not_number_slides(cid):
    for f in _load(cid).reference["findings"]:
        assert f["message"].strip()
        assert not re.search(r"\bslides?\s+(?:#?\d|one|two|three|four|five|six)\b", f["message"], re.I), f["message"]


def _msg(cid):
    return " ".join(f["message"] for f in _load(cid).reference["findings"])


def test_arc_gap_message_names_the_missing_workflow_content():
    m = _msg("arc_gap_drop_workflow").lower()
    assert "workflow" in m or "evaluat" in m or "iterat" in m


def test_missing_conclusion_message_names_the_missing_content():
    m = _msg("missing_conclusion").lower()
    assert "checklist" in m or "action plan" in m or "next steps" in m or "call to action" in m \
        or "call-to-action" in m


def test_out_of_order_message_names_the_slides_by_title():
    m = _msg("out_of_order")
    slides = _load("out_of_order").payload["slides"]
    for t in (_gold_title(4), _gold_title(3), _gold_title(2)):
        assert t in m, (t, m)
        assert t in slides
    # The message must describe the real inversion: workflow now precedes patterns and impact.
    assert m.index(_gold_title(4)) < m.index(_gold_title(2))
    assert re.search(r"\bbefore\b", m)


def test_repetition_message_names_both_slides_by_title():
    m = _msg("repetition")
    rep_title = TITLE_RE.search(_blocks("repetition")[2]).group(1)
    for t in (rep_title, _gold_title(1)):
        assert t in m, (t, m)
        assert t in _load("repetition").payload["slides"]


def test_generator_is_idempotent(generated):
    from evals.packs.deck_reviewer import heldout

    before = dict(generated)
    heldout.generate(out_dir=CASES)
    assert _snapshot(CASES) == before


def test_committed_cases_are_current():
    """Committed cases_heldout is byte-identical to a fresh generation; read-only on the committed tree."""
    committed = _snapshot(COMMITTED)
    fresh = _snapshot(CASES)
    missing = set(fresh) - set(committed)
    extra = set(committed) - set(fresh)
    assert not missing and not extra, f"not committed={sorted(missing)}, stale committed={sorted(extra)}"
    differing = sorted(p for p in fresh if fresh[p] != committed[p])
    assert not differing, f"Committed files differ from generated state: {differing}"

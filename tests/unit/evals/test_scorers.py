import pytest

from evals.harness import render, scorers
from src.domain.finding import CRITERIA

OBJECTIVE = sorted(n for n, c in CRITERIA.items() if c.objective)
SUBJECTIVE = sorted(n for n, c in CRITERIA.items() if not c.objective)
REVIEWERS = ["build_reviewer", "fix_reviewer", "deck_reviewer"]


def _f(criterion, idx):
    return {"criterion": criterion, "slide_index": idx, "objective": CRITERIA[criterion].objective}


def _assert_result(res):
    assert isinstance(res, tuple) and len(res) == 2
    assert isinstance(res[0], bool)
    assert isinstance(res[1], str) and res[1].strip()


# ---- brief Step 1 tests (verbatim) ----

def test_contract_fails_on_none():
    assert scorers.contract_score(None)[0] is False
    assert scorers.contract_score({"html": "x"})[0] is True

def test_expected_category_reviewer_exact_match():
    out = {"findings": [{"criterion": "rogue_colour", "slide_index": 2, "objective": True}], "verdict": "surfaced"}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is True

def test_expected_category_reviewer_extra_objective_finding_fails():
    out = {"findings": [
        {"criterion": "rogue_colour", "slide_index": 2, "objective": True},
        {"criterion": "overflow", "slide_index": 2, "objective": True}]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is False

def test_expected_category_reviewer_missing_planted_criterion_fails():
    assert scorers.expected_category_score("build_reviewer", {"findings": []}, {"criteria": ["overflow"], "positions": [3]})[0] is False

def test_architect_intent_match():
    assert scorers.expected_category_score("architect", {"intent": "build", "target_positions": []}, {"intent": "build"})[0] is True
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [2,3]}, {"intent": "edit", "positions": [3,2]})[0] is True

def test_render_measures_rejects_style_tag_and_overflow():
    clean = render.RenderMeasures(0, 7.0, (), (), True)
    assert scorers.render_measures_score(clean, "<section class='slide'></section>")[0] is True
    assert scorers.render_measures_score(clean, "<style>x</style>")[0] is False
    dirty = render.RenderMeasures(120, 7.0, (), (), True)
    assert scorers.render_measures_score(dirty, "<section></section>")[0] is False
    nil_render = render.RenderMeasures(0, 7.0, (), (), False)
    assert scorers.render_measures_score(nil_render, "<section class='slide'></section>")[0] is False


# ---- added behavioural cases ----

def test_registry_assumptions():
    assert "brief_not_delivered" in SUBJECTIVE
    assert {"overflow", "rogue_colour", "contrast_failure", "source_contradiction"} <= set(OBJECTIVE)


@pytest.mark.parametrize("agent", REVIEWERS)
@pytest.mark.parametrize("crit", OBJECTIVE)
def test_every_objective_criterion_matches_when_planted(agent, crit):
    out = {"findings": [_f(crit, 4)]}
    assert scorers.expected_category_score(agent, out, {"criteria": [crit], "positions": [4]})[0] is True


@pytest.mark.parametrize("planted", OBJECTIVE)
@pytest.mark.parametrize("extra", OBJECTIVE)
def test_any_unplanted_objective_finding_fails(planted, extra):
    if planted == extra:
        pytest.skip("same criterion")
    out = {"findings": [_f(planted, 1), _f(extra, 5)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [planted], "positions": [1]})[0] is False


@pytest.mark.parametrize("extra", SUBJECTIVE)
def test_extra_subjective_finding_still_passes(extra):
    out = {"findings": [_f("rogue_colour", 2), _f(extra, 7)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is True


@pytest.mark.parametrize("crit", OBJECTIVE)
def test_planted_criterion_at_wrong_position_fails(crit):
    out = {"findings": [_f(crit, 5)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [crit], "positions": [2]})[0] is False


def test_planted_criterion_at_right_position_plus_wrong_position_duplicate_passes():
    out = {"findings": [_f("overflow", 2), _f("overflow", 6)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["overflow"], "positions": [2]})[0] is True


def test_multiple_planted_positions_all_required():
    expect = {"criteria": ["overflow"], "positions": [1, 2]}
    both = {"findings": [_f("overflow", 1), _f("overflow", 2)]}
    one = {"findings": [_f("overflow", 1)]}
    assert scorers.expected_category_score("deck_reviewer", both, expect)[0] is True
    assert scorers.expected_category_score("deck_reviewer", one, expect)[0] is False


def test_criterion_at_other_planted_position_is_not_enough():
    # criterion A at position 1 and criterion B at position 2 does not satisfy A@2
    out = {"findings": [_f("overflow", 1), _f("rogue_colour", 2)]}
    expect = {"criteria": ["overflow"], "positions": [2]}
    assert scorers.expected_category_score("build_reviewer", out, expect)[0] is False


@pytest.mark.parametrize("agent", REVIEWERS)
def test_unknown_criterion_fails_and_is_named(agent):
    out = {"findings": [{"criterion": "made_up_criterion", "slide_index": 2, "objective": True}]}
    ok, why = scorers.expected_category_score(agent, out, {"criteria": [], "positions": []})
    assert ok is False
    assert "made_up_criterion" in why


def test_unknown_criterion_fails_even_with_planted_present():
    out = {"findings": [_f("overflow", 3),
                        {"criterion": "made_up_criterion", "slide_index": 1, "objective": False}]}
    ok, why = scorers.expected_category_score("build_reviewer", out, {"criteria": ["overflow"], "positions": [3]})
    assert ok is False
    assert "made_up_criterion" in why


@pytest.mark.parametrize("agent", REVIEWERS)
def test_clean_positive_no_findings_passes(agent):
    assert scorers.expected_category_score(agent, {"findings": []}, {"criteria": [], "positions": []})[0] is True


@pytest.mark.parametrize("crit", OBJECTIVE)
def test_clean_positive_any_objective_finding_fails(crit):
    out = {"findings": [_f(crit, 1)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [], "positions": []})[0] is False


@pytest.mark.parametrize("crit", SUBJECTIVE)
def test_clean_positive_subjective_finding_passes(crit):
    out = {"findings": [_f(crit, 1)]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": [], "positions": []})[0] is True


def test_fix_reviewer_verdict_checked_when_present():
    out = {"findings": [], "verdict": "fixed"}
    base = {"criteria": [], "positions": []}
    assert scorers.expected_category_score("fix_reviewer", out, {**base, "verdict": "fixed"})[0] is True
    assert scorers.expected_category_score("fix_reviewer", out, {**base, "verdict": "surfaced"})[0] is False
    # no verdict expectation -> not checked
    assert scorers.expected_category_score("fix_reviewer", out, base)[0] is True


def test_data_analyst_outcome():
    assert scorers.expected_category_score("data_analyst", {"outcome": "success"}, {"outcome": "success"})[0] is True
    assert scorers.expected_category_score("data_analyst", {"outcome": "missing_data"}, {"outcome": "success"})[0] is False
    assert scorers.expected_category_score("data_analyst", {"outcome": "no_tool"}, {"outcome": "success"})[0] is False


def test_architect_intent_mismatch_fails():
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": []}, {"intent": "build"})[0] is False


def test_architect_edit_positions_compared_as_set():
    expect = {"intent": "edit", "positions": [1, 4, 2]}
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [4, 2, 1]}, expect)[0] is True
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [1, 2]}, expect)[0] is False  # missing
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [1, 2, 4, 5]}, expect)[0] is False  # extra
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [1, 1, 2, 4]}, expect)[0] is True  # dup


@pytest.mark.parametrize("kwargs", [
    dict(overflow_px=1),
    dict(overflow_px=120),
    dict(min_contrast=4.49),
    dict(min_contrast=1.0),
    dict(off_palette=("#ff00ff",)),
    dict(console_errors=("boom",)),
    dict(rendered=False),
    dict(safe_area_px=0.5),
    dict(safe_area_px=19.0),
])
def test_render_measures_each_failure_alone(kwargs):
    base = dict(overflow_px=0, min_contrast=7.0, off_palette=(), console_errors=(), rendered=True)
    m = render.RenderMeasures(**{**base, **kwargs})
    ok, why = scorers.render_measures_score(m, "<section></section>")
    assert ok is False
    assert why.strip()


def test_render_measures_contrast_boundary_passes():
    m = render.RenderMeasures(0, 4.5, (), (), True)
    assert scorers.render_measures_score(m, "<section></section>")[0] is True


def test_render_measures_style_tag_case_insensitive():
    m = render.RenderMeasures(0, 7.0, (), (), True)
    assert scorers.render_measures_score(m, "<STYLE>x</STYLE>")[0] is False


def test_all_scorers_return_bool_and_nonempty_rationale():
    clean = render.RenderMeasures(0, 7.0, (), (), True)
    dirty = render.RenderMeasures(9, 2.0, ("#f0f",), ("e",), False)
    results = [
        scorers.contract_score(None),
        scorers.contract_score({"a": 1}),
        scorers.expected_category_score("architect", {"intent": "build", "target_positions": []}, {"intent": "build"}),
        scorers.expected_category_score("architect", {"intent": "edit", "target_positions": []}, {"intent": "build"}),
        scorers.expected_category_score("data_analyst", {"outcome": "success"}, {"outcome": "success"}),
        scorers.expected_category_score("data_analyst", {"outcome": "no_tool"}, {"outcome": "success"}),
        scorers.expected_category_score("build_reviewer", {"findings": []}, {"criteria": [], "positions": []}),
        scorers.expected_category_score("build_reviewer", {"findings": [_f("overflow", 1)]}, {"criteria": [], "positions": []}),
        scorers.render_measures_score(clean, "<section></section>"),
        scorers.render_measures_score(dirty, "<style></style>"),
    ]
    for r in results:
        _assert_result(r)


# ---- review additions ----

def test_planted_criterion_without_positions_must_still_appear():
    expect = {"criteria": ["arc_gap"]}
    assert scorers.expected_category_score("deck_reviewer", {"findings": []}, expect)[0] is False
    assert scorers.expected_category_score("deck_reviewer", {"findings": [_f("arc_gap", -1)]}, expect)[0] is True


def test_deck_level_position_minus_one():
    out = {"findings": [_f("arc_gap", -1)]}
    assert scorers.expected_category_score("deck_reviewer", out, {"criteria": ["arc_gap"], "positions": [-1]})[0] is True
    assert scorers.expected_category_score("deck_reviewer", out, {"criteria": ["arc_gap"], "positions": [0]})[0] is False


@pytest.mark.parametrize("agent", ["architect", "data_analyst"] + REVIEWERS)
@pytest.mark.parametrize("bad", [None, {}, {"findings": None}])
def test_malformed_structured_scores_fail_not_crash(agent, bad):
    ok, why = scorers.expected_category_score(agent, bad, {"intent": "build", "outcome": "success", "criteria": ["overflow"], "positions": [1]})
    assert ok is False
    assert why.strip()


def test_render_measures_safe_area_intrusion_is_named():
    m = render.RenderMeasures(0, 7.0, (), (), True, 19.4)
    ok, why = scorers.render_measures_score(m, "<section></section>")
    assert ok is False
    assert "19.4" in why and "safe area" in why.lower()


def test_render_measures_safe_area_defaults_clean():
    assert render.RenderMeasures(0, 7.0, (), (), True).safe_area_px == 0.0

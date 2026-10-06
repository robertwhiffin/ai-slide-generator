"""Self-tests for the fix_reviewer eval pack (Task 12). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.domain.deck_spec import SlideSpec
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render
from evals.harness.scorers import expected_category_score

AGENT = "fix_reviewer"
CASE_IDS = [
    "good_fix_accept",
    "fault_left_reject",
    "content_broken_reject",
    "restyle_reject",
    "good_contrast_fix_accept",
]
ACCEPTS = ["good_fix_accept", "good_contrast_fix_accept"]
REJECTS = ["fault_left_reject", "content_broken_reject", "restyle_reject"]
KIND = {cid: ("positive" if cid in ACCEPTS else "mutation") for cid in CASE_IDS}
EXPECT = {
    "good_fix_accept": {"criteria": [], "positions": [], "verdict": "fixed"},
    "fault_left_reject": {"criteria": ["overflow"], "positions": [1], "verdict": "surfaced"},
    "content_broken_reject": {"criteria": ["brief_not_delivered"], "positions": [1], "verdict": "surfaced"},
    "restyle_reject": {"criteria": ["rogue_colour"], "positions": [1], "verdict": "surfaced"},
    "good_contrast_fix_accept": {"criteria": [], "positions": [], "verdict": "fixed"},
}
# The fixer-pack case whose broken slide and finding each case reuses.
FIXER_TWIN = {
    "good_fix_accept": "overflow",
    "fault_left_reject": "overflow",
    "content_broken_reject": "overflow",
    "restyle_reject": "overflow",
    "good_contrast_fix_accept": "contrast_failure",
}
PRODUCTION_KEYS = {
    "position", "finding", "change_summary", "html", "scripts", "original_html",
    "original_scripts", "slide_spec", "resolved_style", "section_css",
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
POS = 1


def _snapshot():
    cases = PACK_DIR / "cases"
    if not cases.exists():
        return {}
    return {
        str(p.relative_to(PACK_DIR)): p.read_bytes()
        for p in sorted(cases.rglob("*"))
        if p.is_file()
    }


# Capture committed state BEFORE any generate() call in this module (packs-facts rule).
_initial_snapshot = _snapshot()


@pytest.fixture(scope="module", autouse=True)
def generated():
    from evals.packs.fix_reviewer import mutations

    mutations.generate()
    return _snapshot()


def _cal(cid):
    return json.loads((PACK_DIR / "cases" / cid / "calibration.json").read_text())["should_fail"]


def _measure(html, scripts=""):
    return render.render_slide(html, scripts, section_css=case.meridian_section_css())


def _after(cid):
    p = case.load_case(AGENT, cid).payload
    return _measure(p["html"], p.get("scripts", ""))


def _before(cid):
    p = case.load_case(AGENT, cid).payload
    return _measure(p["original_html"], p.get("original_scripts", ""))


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _assert_clean(m):
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


def test_exactly_the_five_cases():
    cases = case.load_cases(AGENT)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    dirs = sorted(d.name for d in (PACK_DIR / "cases").iterdir() if d.is_dir())
    assert dirs == sorted(CASE_IDS)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    d = PACK_DIR / "cases" / cid
    assert sorted(p.name for p in d.iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = case.load_case(AGENT, cid)
    assert c.design_system_active is True
    assert c.kind == KIND[cid]
    if c.kind == "mutation":
        assert c.fault
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert set(c.payload) == PRODUCTION_KEYS
    assert "resolved_data" not in c.payload
    assert isinstance(c.payload["original_html"], str) and c.payload["original_html"].strip()
    assert isinstance(c.payload["change_summary"], str) and c.payload["change_summary"].strip()
    assert c.payload["position"] == POS
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    p = case.load_case(AGENT, cid).payload
    spec = SlideSpec.model_validate(p["slide_spec"])
    assert spec.position == POS
    assert p["slide_spec"] == case.gold_deck_spec()["slides"][POS]
    f = Finding.model_validate(p["finding"])
    assert f.slide_index == POS


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reuses_fixer_pack_input_and_finding(cid):
    p = case.load_case(AGENT, cid).payload
    twin = case.load_case("fixer", FIXER_TWIN[cid]).payload
    assert p["original_html"] == twin["html"]
    assert p["finding"] == twin["finding"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_expect_matches_table(cid):
    c = case.load_case(AGENT, cid)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA


@pytest.mark.parametrize("cid", ACCEPTS)
@pytest.mark.usefixtures("requires_chromium")
def test_accept_cases_fix_is_the_gold_and_renders_clean(cid):
    p = case.load_case(AGENT, cid).payload
    assert p["html"] == case.gold_slide(POS)
    assert p["html"] != p["original_html"]
    _assert_clean(_after(cid))


@pytest.mark.usefixtures("requires_chromium")
def test_good_fix_accept_original_overflows():
    assert case.load_case(AGENT, "good_fix_accept").payload["finding"]["criterion"] == "overflow"
    m = _before("good_fix_accept")
    assert m.rendered and m.overflow_px > 0


@pytest.mark.usefixtures("requires_chromium")
def test_good_contrast_fix_accept_original_has_low_contrast():
    assert case.load_case(AGENT, "good_contrast_fix_accept").payload["finding"]["criterion"] == "contrast_failure"
    m = _before("good_contrast_fix_accept")
    assert m.rendered and m.min_contrast < 4.5


@pytest.mark.usefixtures("requires_chromium")
def test_fault_left_html_still_overflows_but_less():
    p = case.load_case(AGENT, "fault_left_reject").payload
    assert p["finding"]["criterion"] == "overflow"
    assert p["html"] != p["original_html"]
    after, before = _after("fault_left_reject"), _before("fault_left_reject")
    assert after.rendered and before.rendered
    assert after.overflow_px > 0
    assert after.overflow_px < before.overflow_px
    # Single-fault: only overflow is planted, so no other objective render fault may appear.
    assert after.off_palette == ()
    assert after.min_contrast >= 4.5
    assert after.console_errors == ()


@pytest.mark.usefixtures("requires_chromium")
def test_content_broken_html_is_clean_but_changes_meaning():
    p = case.load_case(AGENT, "content_broken_reject").payload
    assert p["html"] != case.gold_slide(POS)
    assert _text(p["html"]) != _text(case.gold_slide(POS))
    assert p["html"] != p["original_html"]
    _assert_clean(_after("content_broken_reject"))


@pytest.mark.usefixtures("requires_chromium")
def test_restyle_html_fixes_overflow_but_is_off_palette():
    p = case.load_case(AGENT, "restyle_reject").payload
    assert p["html"] != case.gold_slide(POS)
    m = _after("restyle_reject")
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette, "restyle must introduce an off-palette colour"
    # Single-fault: the recolour must not also drop contrast, or contrast_failure becomes an
    # unplanted objective finding that a correct reviewer raises and the scorer then FAILS.
    assert m.min_contrast >= 4.5, f"restyle also trips contrast_failure ({m.min_contrast:.2f})"
    assert m.console_errors == ()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_is_reviewer_shaped_and_passes_scorer(cid):
    c = case.load_case(AGENT, cid)
    ref = c.reference
    assert ref["slide_index"] == POS
    assert ref["verdict"] in ("clean", "fixed", "surfaced")
    assert ref["verdict"] == c.expect["verdict"]
    for f in ref["findings"]:
        Finding.model_validate(f)
        assert f["slide_index"] == POS
    assert sorted(f["criterion"] for f in ref["findings"]) == sorted(c.expect["criteria"])
    if cid in REJECTS:
        assert ref["findings"] and all(f["message"].strip() for f in ref["findings"])
    else:
        assert ref["findings"] == []
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_is_reviewer_shaped_differs_and_fails_scorer(cid):
    c = case.load_case(AGENT, cid)
    bad = _cal(cid)
    assert bad["slide_index"] == POS
    assert bad["verdict"] in ("clean", "fixed", "surfaced")
    assert isinstance(bad["findings"], list)
    for f in bad["findings"]:
        Finding.model_validate(f)
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"should_fail unexpectedly passes the scorer: {why}"


@pytest.mark.parametrize("cid", ACCEPTS)
def test_accept_should_fail_rejects_a_good_fix(cid):
    bad = _cal(cid)
    assert bad["verdict"] == "surfaced"
    assert bad["findings"]


@pytest.mark.parametrize("cid", REJECTS)
def test_reject_should_fail_accepts_a_bad_fix(cid):
    bad = _cal(cid)
    assert bad["verdict"] == "fixed"
    assert bad["findings"] == []


def test_generator_is_idempotent(generated):
    from evals.packs.fix_reviewer import mutations

    before = dict(generated)
    mutations.generate()
    assert _snapshot() == before


def test_committed_cases_are_current():
    current = _snapshot()
    missing = set(_initial_snapshot) - set(current)
    extra = set(current) - set(_initial_snapshot)
    assert not missing and not extra, f"File set mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
    differing = sorted(p for p in current if current[p] != _initial_snapshot[p])
    assert not differing, f"Committed files differ from generated state: {differing}"


def test_judge_prompt_placeholders():
    text = (PACK_DIR / "judge_prompt.md").read_text()
    assert "{{ outputs }}" in text
    assert "{{ expectations }}" in text


def test_judge_prompt_verdict_first_and_handles_both_kinds():
    text = (PACK_DIR / "judge_prompt.md").read_text()
    assert "FIRST" in text and text.index("FIRST") < text.index("rationale", text.index("FIRST"))
    low = text.lower()
    assert "finding" in low
    # Positives exist: an empty/accepting reference must be handled explicitly.
    assert "reference has no findings" in text
    assert "Fail if there are no findings" not in text
    assert "fixed" in low


def test_judge_prompt_passes_a_correct_accept_and_fails_a_wrong_one():
    text = (PACK_DIR / "judge_prompt.md").read_text()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]
    no_findings = [s for s in sentences if "reference has no findings" in s]
    assert no_findings
    assert any("PASS" in s for s in no_findings), "must PASS a reviewer that accepts the good fix"
    assert any("FAIL" in s for s in sentences if "finding" in s.lower() and "objective" in s.lower()), (
        "must FAIL a reviewer that raises an objective finding against a good fix"
    )

"""Self-tests for the fix_reviewer HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import SlideSpec
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS, model_payload_for

from evals.harness import case, render
from evals.harness.scorers import expected_category_score

AGENT = "fix_reviewer"
DECK = "heldout"
POS = 5  # the Action Plan slide; position 1's "30-50% MORE tokens" would invert resolved_data
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
    "fault_left_reject": {"criteria": ["overflow"], "positions": [POS], "verdict": "surfaced"},
    "content_broken_reject": {"criteria": ["brief_not_delivered"], "positions": [POS], "verdict": "surfaced"},
    "restyle_reject": {"criteria": ["rogue_colour"], "positions": [POS], "verdict": "surfaced"},
    "good_contrast_fix_accept": {"criteria": [], "positions": [], "verdict": "fixed"},
}
# The held-out fixer case whose broken slide and finding each case reuses.
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
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
ROGUE = "#e11d48"


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
    from evals.packs.fix_reviewer import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())["should_fail"]


def _measure(html, scripts=""):
    return render.render_slide(html, scripts, section_css=case.meridian_section_css())


def _after(cid):
    p = _load(cid).payload
    return _measure(p["html"], p.get("scripts", ""))


def _before(cid):
    p = _load(cid).payload
    return _measure(p["original_html"], p.get("original_scripts", ""))


def _gold():
    return case.gold_slide(POS, DECK)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _lis(html):
    return re.findall(r"<li\b.*?</li>", html, re.S)


def _assert_clean(m):
    assert m.rendered
    assert m.overflow_px == 0
    assert m.safe_area_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


def test_exactly_the_five_cases():
    cases = case.load_cases(AGENT, root=CASES)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    assert sorted(d.name for d in CASES.iterdir() if d.is_dir()) == sorted(CASE_IDS)


def test_committed_cases_load_via_heldout_split():
    cases = case.load_cases(AGENT, split=DECK)
    assert sorted(c.case_id for c in cases) == sorted(CASE_IDS)
    for cid in CASE_IDS:
        assert case.load_case(AGENT, cid, split=DECK).design_system_active is True


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_has_four_files(cid):
    assert sorted(p.name for p in (CASES / cid).iterdir()) == sorted(FILES)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_case_contract(cid):
    c = _load(cid)
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
    # The payload passes through the production key filter untouched.
    assert model_payload_for(AGENT, dict(c.payload)) == c.payload


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    p = _load(cid).payload
    spec = SlideSpec.model_validate(p["slide_spec"])
    assert spec.position == POS
    assert p["slide_spec"] == case.gold_deck_spec(DECK)["slides"][POS]
    f = Finding.model_validate(p["finding"])
    assert f.slide_index == POS
    assert f.category == CRITERIA[f.criterion].category
    assert f.objective == CRITERIA[f.criterion].objective


@pytest.mark.parametrize("cid", CASE_IDS)
def test_scripts_are_the_gold_scripts(cid):
    p = _load(cid).payload
    assert p["scripts"] == case.gold_scripts(POS, DECK)
    assert p["original_scripts"] == case.gold_scripts(POS, DECK)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reuses_fixer_heldout_input_and_finding(cid):
    p = _load(cid).payload
    twin = case.load_case("fixer", FIXER_TWIN[cid], split=DECK).payload
    assert p["original_html"] == twin["html"]
    assert p["original_scripts"] == twin["scripts"]
    assert p["finding"] == twin["finding"]
    assert p["position"] == twin["position"] == POS
    assert p["slide_spec"] == twin["slide_spec"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_expect_matches_table(cid):
    c = _load(cid)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA


# ---- the fixed slide, per case ----------------------------------------------------------------

@pytest.mark.parametrize("cid", ACCEPTS)
@pytest.mark.usefixtures("requires_chromium")
def test_accept_cases_fix_is_the_heldout_gold_and_renders_clean(cid):
    p = _load(cid).payload
    assert p["html"] == _gold()
    assert p["html"] != p["original_html"]
    _assert_clean(_after(cid))


@pytest.mark.usefixtures("requires_chromium")
def test_good_fix_accept_original_overflows():
    assert _load("good_fix_accept").payload["finding"]["criterion"] == "overflow"
    m = _before("good_fix_accept")
    assert m.rendered and m.overflow_px > 0


@pytest.mark.usefixtures("requires_chromium")
def test_good_contrast_fix_accept_original_has_low_contrast():
    assert _load("good_contrast_fix_accept").payload["finding"]["criterion"] == "contrast_failure"
    m = _before("good_contrast_fix_accept")
    assert m.rendered and m.min_contrast < 4.5
    assert m.off_palette == ()


@pytest.mark.parametrize("cid", REJECTS)
def test_reject_cases_share_the_overflow_finding(cid):
    assert _load(cid).payload["finding"]["criterion"] == "overflow"


@pytest.mark.usefixtures("requires_chromium")
def test_fault_left_html_still_overflows_but_less():
    p = _load("fault_left_reject").payload
    assert p["html"] != p["original_html"]
    after, before = _after("fault_left_reject"), _before("fault_left_reject")
    assert after.rendered and before.rendered
    assert after.overflow_px > 0
    assert after.overflow_px < before.overflow_px
    # Fewer surplus bullets than the original, but still more than the gold.
    assert len(_lis(_gold())) < len(_lis(p["html"])) < len(_lis(p["original_html"]))
    # Single-fault: overflow is the only planted fault.
    assert after.off_palette == ()
    assert after.min_contrast >= 4.5
    assert after.console_errors == ()


@pytest.mark.usefixtures("requires_chromium")
def test_content_broken_html_is_clean_but_changes_one_bullet():
    p = _load("content_broken_reject").payload
    gold = _gold()
    assert p["html"] != gold
    assert p["html"] != p["original_html"]
    assert _text(p["html"]) != _text(gold)
    g_lis, h_lis = _lis(gold), _lis(p["html"])
    assert len(g_lis) == len(h_lis)
    differing = [i for i, (a, b) in enumerate(zip(g_lis, h_lis)) if a != b]
    assert len(differing) == 1, "exactly one gold checklist bullet is altered"
    # Everything outside that bullet is the gold, byte for byte: a purely content fault.
    i = differing[0]
    assert p["html"].replace(h_lis[i], g_lis[i], 1) == gold
    _assert_clean(_after("content_broken_reject"))


@pytest.mark.usefixtures("requires_chromium")
def test_restyle_html_fixes_overflow_but_is_off_palette():
    p = _load("restyle_reject").payload
    assert p["html"] != _gold()
    assert ROGUE in p["html"].lower()
    assert ROGUE not in _gold().lower()
    assert ROGUE not in p["original_html"].lower()
    assert p["html"].lower().count(ROGUE) >= 2, "recolour spans several elements"
    # Overflow fixed the same way as the gold: same bullet count.
    assert len(_lis(p["html"])) == len(_lis(_gold()))
    m = _after("restyle_reject")
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette, "restyle must introduce an off-palette colour"
    assert all(ROGUE in str(x).lower() for x in m.off_palette), m.off_palette
    # Single-fault: a contrast drop would add an unplanted contrast_failure finding.
    assert m.min_contrast >= 4.5, f"restyle also trips contrast_failure ({m.min_contrast:.2f})"
    assert m.safe_area_px == 0
    assert m.console_errors == ()


# ---- change_summary ---------------------------------------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
def test_change_summary_is_a_real_sentence(cid):
    assert len(_load(cid).payload["change_summary"].split()) >= 5


def test_reject_summaries_describe_overflow_fix_and_omit_the_damage():
    for cid in REJECTS:
        s = _load(cid).payload["change_summary"].lower()
        assert any(w in s for w in ("bullet", "overflow", "fit")), cid
        assert "e11d48" not in s and "recolour" not in s and "restyl" not in s, cid
        assert "revers" not in s and "rewr" not in s and "flipp" not in s, cid


def test_contrast_accept_summary_is_honest_about_contrast():
    assert "contrast" in _load("good_contrast_fix_accept").payload["change_summary"].lower()


# ---- reference & calibration ------------------------------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_is_reviewer_shaped_and_passes_scorer(cid):
    c = _load(cid)
    ref = c.reference
    assert ref["slide_index"] == POS
    assert ref["verdict"] in ("clean", "fixed", "surfaced")
    assert ref["verdict"] == c.expect["verdict"]
    for f in ref["findings"]:
        Finding.model_validate(f)
        assert f["slide_index"] == POS
        assert f["category"] == CRITERIA[f["criterion"]].category
        assert f["objective"] == CRITERIA[f["criterion"]].objective
    assert sorted(f["criterion"] for f in ref["findings"]) == sorted(c.expect["criteria"])
    if cid in REJECTS:
        assert len(ref["findings"]) == 1
        assert len(ref["findings"][0]["message"].split()) >= 10
    else:
        assert ref["findings"] == []
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why


def test_reject_reference_messages_describe_the_planted_fault():
    def msg(cid):
        return _load(cid).reference["findings"][0]["message"].lower()

    assert "overflow" in msg("fault_left_reject") or "bottom" in msg("fault_left_reject")
    assert "still" in msg("fault_left_reject")
    assert "e11d48" in msg("restyle_reject")
    # Names the altered bullet by quoting its bold lead-in.
    p = _load("content_broken_reject").payload
    g_lis, h_lis = _lis(_gold()), _lis(p["html"])
    changed = next(b for a, b in zip(g_lis, h_lis) if a != b)
    gold_li = next(a for a, b in zip(g_lis, h_lis) if a != b)
    lead = _text(re.search(r"<strong[^>]*>(.*?)</strong>", gold_li, re.S).group(1)).lower().rstrip(":")
    assert lead in msg("content_broken_reject")
    assert changed != gold_li


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_is_reviewer_shaped_differs_and_fails_scorer(cid):
    c = _load(cid)
    bad = _cal(cid)
    assert bad["slide_index"] == POS
    assert bad["verdict"] in ("clean", "fixed", "surfaced")
    assert isinstance(bad["findings"], list)
    for f in bad["findings"]:
        Finding.model_validate(f)
        assert f["slide_index"] == POS
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"should_fail unexpectedly passes the scorer: {why}"


@pytest.mark.parametrize("cid", ACCEPTS)
def test_accept_should_fail_rejects_a_good_fix(cid):
    bad = _cal(cid)
    assert bad["verdict"] == "surfaced"
    assert bad["findings"]
    assert all(f["objective"] is True for f in bad["findings"])


@pytest.mark.parametrize("cid", REJECTS)
def test_reject_should_fail_accepts_a_bad_fix(cid):
    bad = _cal(cid)
    assert bad["verdict"] == "fixed"
    assert bad["findings"] == []


# ---- generator --------------------------------------------------------------------------------

def test_generator_is_idempotent(generated):
    from evals.packs.fix_reviewer import heldout

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

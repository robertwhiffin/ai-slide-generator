"""Self-tests for the fixer HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import ResolvedData, SlideSpec
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render

AGENT = "fixer"
DECK = "heldout"
CASE_IDS = ["rogue_colour", "overflow", "contrast_failure", "source_contradiction", "brief_not_delivered"]
SLIDE = 5  # the Action Plan slide; position 1's "30-50% MORE tokens" would invert resolved_data
POSITION = {
    "rogue_colour": SLIDE,
    "overflow": SLIDE,
    "contrast_failure": SLIDE,
    "source_contradiction": 3,
    "brief_not_delivered": SLIDE,
}
# build_reviewer held-out case holding the identical broken input (where one exists).
REVIEWER_TWIN = {
    "rogue_colour": "rogue_colour",
    "overflow": "overflow",
    "source_contradiction": "source_contradiction",
    "brief_not_delivered": "broken_handoff",
}
PAYLOAD_KEYS = {"position", "finding", "html", "scripts", "slide_spec",
                "resolved_style", "section_css", "resolved_data"}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
ROGUE = "#e11d48"
RIGHT_STAT = "30–50%"
WRONG_STAT = "10–15%"


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
    from evals.packs.fixer import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())["should_fail"]


def _measure_html(html, scripts):
    return render.render_slide(html, scripts, section_css=case.meridian_section_css())


def _input_measure(cid):
    p = _load(cid).payload
    return _measure_html(p["html"], p.get("scripts", ""))


def _gold(pos):
    return case.gold_slide(pos, DECK)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _callout_text(html):
    m = re.search(r'<div class="callout"[^>]*>(.*?)</div>', html, re.S)
    assert m, "no callout found"
    return _text(m.group(1))


def _spec_slide(pos):
    return case.gold_deck_spec(DECK)["slides"][pos]


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
    assert c.kind == "mutation"
    assert c.fault
    assert c.expect == {}
    assert set(c.payload) == PAYLOAD_KEYS
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert "corrective_instruction" not in c.payload
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_resolved_data_is_the_deck2_spec_unchanged(cid):
    rd = _load(cid).payload["resolved_data"]
    ResolvedData.model_validate(rd)
    assert rd == case.gold_deck_spec(DECK)["resolved_data"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    c = _load(cid)
    spec = SlideSpec.model_validate(c.payload["slide_spec"])
    assert spec.position == POSITION[cid]
    assert c.payload["position"] == POSITION[cid]
    assert c.payload["slide_spec"] == _spec_slide(POSITION[cid])
    assert POSITION[cid] in case.RENDER_REFERENCE_POSITIONS[DECK]
    assert POSITION[cid] != 4
    assert POSITION[cid] != 1


@pytest.mark.parametrize("cid", CASE_IDS)
def test_scripts_are_the_gold_scripts(cid):
    assert _load(cid).payload["scripts"] == case.gold_scripts(POSITION[cid], DECK)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_finding_is_a_stamped_real_finding(cid):
    p = _load(cid).payload
    f = Finding.model_validate(p["finding"])
    assert f.criterion == cid
    assert f.slide_index == p["position"]
    assert f.category == CRITERIA[cid].category
    assert f.objective == CRITERIA[cid].objective
    assert len(f.message.split()) >= 8


def test_source_contradiction_finding_states_both_values():
    msg = _load("source_contradiction").payload["finding"]["message"]
    assert WRONG_STAT in msg and RIGHT_STAT in msg


def test_rogue_colour_finding_names_the_hex():
    assert "e11d48" in _load("rogue_colour").payload["finding"]["message"].lower()


# ---- twin equality ----------------------------------------------------------------------------

@pytest.mark.parametrize("cid", list(REVIEWER_TWIN))
def test_broken_input_matches_build_reviewer_heldout_twin(cid):
    twin = case.load_case("build_reviewer", REVIEWER_TWIN[cid], split=DECK)
    p = _load(cid).payload
    assert p["html"] == twin.payload["html"]
    assert p["scripts"] == twin.payload["scripts"]
    assert p["position"] == twin.payload["position"]
    assert p["slide_spec"] == twin.payload["slide_spec"]


# ---- each broken input exhibits exactly its fault ---------------------------------------------

@pytest.mark.usefixtures("requires_chromium")
def test_rogue_colour_input_is_off_palette_only():
    html = _load("rogue_colour").payload["html"]
    assert ROGUE in html.lower() and ROGUE not in _gold(SLIDE).lower()
    m = _input_measure("rogue_colour")
    assert m.rendered
    assert m.off_palette
    assert all("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette
    assert m.overflow_px == 0
    assert m.min_contrast >= 4.5


@pytest.mark.usefixtures("requires_chromium")
def test_overflow_input_overflows():
    html = _load("overflow").payload["html"]
    added = html.count("<li") - _gold(SLIDE).count("<li")
    assert 35 <= added <= 45, added
    m = _input_measure("overflow")
    assert m.rendered
    assert m.overflow_px > 0
    assert m.off_palette == ()


@pytest.mark.usefixtures("requires_chromium")
def test_contrast_failure_input_is_contrast_only_with_palette_colours():
    gold = _gold(SLIDE)
    html = _load("contrast_failure").payload["html"]
    assert html != gold
    assert _measure_html(gold, case.gold_scripts(SLIDE, DECK)).min_contrast >= 4.5
    # Text is untouched: the fault is purely styling, and no rogue hex was introduced.
    assert _text(html) == _text(gold)
    assert html.count("#") <= gold.count("#")
    m = _input_measure("contrast_failure")
    assert m.rendered
    assert m.min_contrast < 4.5, m
    assert m.off_palette == (), m
    assert m.overflow_px == 0
    assert m.safe_area_px == 0
    assert m.console_errors == ()


def test_source_contradiction_input_has_wrong_value_only_in_the_stat():
    html, gold = _load("source_contradiction").payload["html"], _gold(3)
    assert html != gold
    assert WRONG_STAT in html and WRONG_STAT not in gold
    assert RIGHT_STAT in gold and RIGHT_STAT not in html
    assert "30-50%" not in html
    assert html.replace(WRONG_STAT, RIGHT_STAT, 1) == gold


def test_brief_not_delivered_input_contradicts_the_handoff():
    html, gold = _load("brief_not_delivered").payload["html"], _gold(SLIDE)
    hands_off = _spec_slide(SLIDE)["hands_off"]
    assert "no new tooling required" in hands_off
    assert "no new tooling required" in _callout_text(gold)
    assert "no new tooling required" not in _callout_text(html)
    assert _callout_text(html) != _callout_text(gold)
    assert re.search(r"\bneeds?\b[^.]*\btooling\b", _callout_text(html), re.I)


@pytest.mark.parametrize("cid", ["source_contradiction", "brief_not_delivered"])
@pytest.mark.usefixtures("requires_chromium")
def test_content_fault_inputs_render_fully_clean(cid):
    _assert_clean(_input_measure(cid))


# ---- reference --------------------------------------------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_is_fixer_shaped_unmutated_gold(cid):
    pos = POSITION[cid]
    ref = _load(cid).reference
    assert set(ref) >= {"position", "html", "scripts", "changed", "change_summary"}
    assert ref["position"] == pos
    assert ref["changed"] is True
    assert isinstance(ref["change_summary"], str) and len(ref["change_summary"].split()) >= 5
    assert ref["html"] == _gold(pos)
    assert ref["scripts"] == case.gold_scripts(pos, DECK)
    assert ref["html"] != _load(cid).payload["html"]


def test_change_summaries_describe_the_specific_fix():
    def s(cid):
        return _load(cid).reference["change_summary"].lower()

    assert "e11d48" in s("rogue_colour")
    assert any(w in s("overflow") for w in ("bullet", "overflow", "fit"))
    assert "contrast" in s("contrast_failure")
    assert "10–15%" in s("source_contradiction") and "30–50%" in s("source_contradiction")
    assert "tooling" in s("brief_not_delivered") or "sprint" in s("brief_not_delivered")


@pytest.mark.parametrize("cid", CASE_IDS)
@pytest.mark.usefixtures("requires_chromium")
def test_reference_renders_fully_clean(cid):
    from evals.harness import scorers

    ref = _load(cid).reference
    m = _measure_html(ref["html"], ref["scripts"])
    _assert_clean(m)
    ok, why = scorers.render_measures_score(m, ref["html"])
    assert ok, why


# ---- calibration ------------------------------------------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_hands_back_the_broken_slide_unchanged(cid):
    c = _load(cid)
    bad = _cal(cid)
    assert set(bad) >= {"position", "html", "scripts", "changed"}
    assert bad["position"] == POSITION[cid]
    assert bad["changed"] is False
    assert bad["html"] == c.payload["html"]
    assert bad["scripts"] == c.payload["scripts"]
    assert bad["html"] != c.reference["html"]
    assert bad != c.reference


@pytest.mark.usefixtures("requires_chromium")
def test_rogue_colour_should_fail_is_still_off_palette():
    bad = _cal("rogue_colour")
    m = _measure_html(bad["html"], bad["scripts"])
    assert any("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette


@pytest.mark.usefixtures("requires_chromium")
def test_overflow_should_fail_still_overflows():
    bad = _cal("overflow")
    assert _measure_html(bad["html"], bad["scripts"]).overflow_px > 0


@pytest.mark.usefixtures("requires_chromium")
def test_contrast_failure_should_fail_still_low_contrast():
    bad = _cal("contrast_failure")
    m = _measure_html(bad["html"], bad["scripts"])
    assert m.min_contrast < 4.5
    assert m.off_palette == ()


def test_source_contradiction_should_fail_keeps_wrong_value():
    bad = _cal("source_contradiction")
    assert WRONG_STAT in bad["html"]
    assert RIGHT_STAT not in bad["html"]


def test_brief_not_delivered_should_fail_keeps_broken_handoff():
    bad = _cal("brief_not_delivered")
    assert "no new tooling required" not in _callout_text(bad["html"])
    assert _text(bad["html"]) != _text(_gold(SLIDE))


# ---- generator --------------------------------------------------------------------------------

def test_generator_is_idempotent(generated):
    from evals.packs.fixer import heldout

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

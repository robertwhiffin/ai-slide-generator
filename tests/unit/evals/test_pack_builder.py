"""Self-tests for the builder eval pack (Task 9). Behavioural; no model, no network."""
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import ResolvedData, SlideSpec
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render

AGENT = "builder"
CASE_IDS = ["gold_bullets", "gold_chart", "gold_stats", "too_much_content", "chart_no_data"]
POSITIVES = {"gold_bullets": 1, "gold_chart": 3, "gold_stats": 9}
MUTATIONS = ["too_much_content", "chart_no_data"]
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT


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
    from evals.packs.builder import mutations

    CASES = tmp_path_factory.mktemp(AGENT) / "cases"
    mutations.generate(out_dir=CASES)
    return _snapshot(CASES)


def _cal(cid):
    import json

    return json.loads((CASES / cid / "calibration.json").read_text())


def _measure(out):
    return render.render_slide(out["html"], out.get("scripts", ""), section_css=case.meridian_section_css())


def _spec_slide(pos):
    return case.gold_deck_spec()["slides"][pos]


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
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()
    assert c.payload["design_system_active"] is True
    assert c.expect == {}
    assert set(c.reference) >= {"position", "html", "scripts"}
    assert c.kind == ("positive" if cid in POSITIVES else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid,pos", POSITIVES.items())
def test_positive_matches_gold(cid, pos):
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.payload["slide_spec"]["position"] == pos
    assert c.payload["position"] == pos
    gold = _spec_slide(pos)
    assert c.payload["slide_spec"]["content_brief"] == gold["content_brief"]
    assert c.payload["slide_spec"]["hands_off"] == gold["hands_off"]
    assert c.reference["position"] == pos
    assert c.reference["html"] == case.gold_slide(pos)
    assert c.reference["scripts"] == case.gold_scripts(pos)


def test_gold_chart_carries_figures():
    c = case.load_case(AGENT, "gold_chart", root=CASES)
    assert c.payload["resolved_data"]["figures"]
    assert "<canvas" in c.reference["html"] and c.reference["scripts"].strip()


@pytest.mark.parametrize("cid", CASE_IDS)
@pytest.mark.usefixtures("requires_chromium")
def test_reference_renders_clean(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    m = _measure(c.reference)
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


def test_chart_no_data_payload_has_empty_figures():
    c = case.load_case(AGENT, "chart_no_data", root=CASES)
    assert c.payload["resolved_data"]["figures"] == []
    gold = _spec_slide(3)
    spec = c.payload["slide_spec"]
    assert spec["position"] == 3 and c.reference["position"] == 3
    assert spec["purpose"] == gold["purpose"]
    assert spec["hands_off"] == gold["hands_off"]
    assert c.payload["hands_off"] == gold["hands_off"]
    # Reference states the point without inventing a chart.
    assert "<canvas" not in c.reference["html"]
    assert not c.reference["scripts"].strip()
    assert c.reference["html"] != case.gold_slide(3)


def test_too_much_content_demands_more_than_gold():
    c = case.load_case(AGENT, "too_much_content", root=CASES)
    gold_brief = _spec_slide(1)["content_brief"]
    brief = c.payload["slide_spec"]["content_brief"]
    assert c.payload["slide_spec"]["position"] == 1
    assert c.reference["position"] == 1
    assert len(brief) > 1.5 * len(gold_brief)
    assert len(re.findall(r"\d+[.)]|^\s*[-*•]|;", brief, re.M)) >= 9 or len(brief.split()) > 2 * len(gold_brief.split())
    assert c.reference["html"] != case.gold_slide(1)
    assert '<style' not in c.reference["html"].lower()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_shape_and_differs(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)["should_fail"]
    assert set(bad) >= {"position", "html", "scripts"}
    assert isinstance(bad["position"], int) and isinstance(bad["html"], str) and isinstance(bad["scripts"], str)
    assert bad != c.reference
    assert bad["position"] == c.reference["position"]


@pytest.mark.parametrize("cid", list(POSITIVES))
@pytest.mark.usefixtures("requires_chromium")
def test_positive_calibration_is_measurably_bad(cid):
    m = _measure(_cal(cid)["should_fail"])
    assert (
        m.overflow_px > 0
        or m.off_palette
        or m.min_contrast < 4.5
        or m.console_errors
        or not m.rendered
    ), m


@pytest.mark.usefixtures("requires_chromium")
def test_too_much_content_calibration_overflows():
    assert _measure(_cal("too_much_content")["should_fail"]).overflow_px > 0


def test_chart_no_data_calibration_fabricates_a_chart():
    bad = _cal("chart_no_data")["should_fail"]
    assert "<canvas" in bad["html"] or bad["scripts"].strip() or re.search(r"\d", bad["html"])


def test_generator_is_idempotent(generated):
    from evals.packs.builder import mutations

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


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    """packs-facts "Real data models": the agent must see production shapes."""
    c = case.load_case(AGENT, cid, root=CASES)
    ResolvedData.model_validate(c.payload["resolved_data"])
    SlideSpec.model_validate(c.payload["slide_spec"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_resolved_data_comes_from_the_gold_deck_spec(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    gold_rd = case.gold_deck_spec()["resolved_data"]
    expected = {**gold_rd, "figures": []} if cid == "chart_no_data" else gold_rd
    assert c.payload["resolved_data"] == expected


@pytest.mark.usefixtures("requires_chromium")
@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_passes_render_measures_including_safe_area(cid):
    """I2: a known-good output must pass the scorer itself, safe area included."""
    from evals.harness import scorers

    ref = case.load_case(AGENT, cid, root=CASES).reference
    m = render.render_slide(ref["html"], ref.get("scripts", ""), section_css=case.meridian_section_css())
    assert m.safe_area_px == 0, m
    ok, why = scorers.render_measures_score(m, ref["html"])
    assert ok, why

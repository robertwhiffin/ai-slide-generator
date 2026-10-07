"""Self-tests for the builder HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import json
import re
from html.parser import HTMLParser

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import ResolvedData, SlideSpec
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render

AGENT = "builder"
DECK = "heldout"
CASE_IDS = ["cover_slide", "bullets_problem", "stat_cards", "too_much_content", "stat_no_data"]
POSITIVES = {"cover_slide": 0, "bullets_problem": 1, "stat_cards": 3}
MUTATIONS = {"too_much_content": 1, "stat_no_data": 3}
POSITION_OF = {**POSITIVES, **MUTATIONS}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
BUILDER_KEYS = {
    "position", "slide_spec", "assumes", "hands_off", "resolved_data",
    "section_html", "section_css", "resolved_style", "design_system_active",
}
PACK_DIR = case.PACKS_DIR / AGENT
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module


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
    from evals.packs.builder import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _measure(out):
    return render.render_slide(out["html"], out.get("scripts", ""), section_css=case.meridian_section_css())


def _spec_slide(pos):
    return case.gold_deck_spec(DECK)["slides"][pos]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _visible_text_sans_page_number(html):
    """Visible text with the footer page number removed.

    Rule: drop the single trailing ``<span>N</span>`` of the slide footer (the page number), then
    take only text nodes (no attributes, no <style>/<script>), so inline ``px`` values do not count.
    """
    html = re.sub(r"<span>\s*\d+\s*</span>(\s*</div>)", r"\1", html, count=1)
    p = _Text()
    p.feed(html)
    return " ".join(p.parts)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


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
    assert set(c.payload) == BUILDER_KEYS
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()
    assert c.payload["design_system_active"] is True
    assert c.expect == {}
    assert set(c.reference) >= {"position", "html", "scripts"}
    assert c.kind == ("positive" if cid in POSITIVES else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    c = _load(cid)
    ResolvedData.model_validate(c.payload["resolved_data"])
    SlideSpec.model_validate(c.payload["slide_spec"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_resolved_data_comes_from_the_deck2_spec(cid):
    gold_rd = case.gold_deck_spec(DECK)["resolved_data"]
    expected = {**gold_rd, "figures": []} if cid == "stat_no_data" else gold_rd
    assert _load(cid).payload["resolved_data"] == expected


@pytest.mark.parametrize("cid", CASE_IDS)
def test_positions_match_and_avoid_position_4(cid):
    pos = POSITION_OF[cid]
    c = _load(cid)
    assert c.payload["position"] == pos
    assert c.payload["slide_spec"]["position"] == pos
    assert c.reference["position"] == pos
    assert _cal(cid)["should_fail"]["position"] == pos
    assert pos in case.RENDER_REFERENCE_POSITIONS[DECK]
    assert pos != 4


def test_render_reference_positions_cover_those_used_and_exclude_4():
    allowed = case.RENDER_REFERENCE_POSITIONS[DECK]
    assert set(POSITION_OF.values()) <= set(allowed)
    assert 4 not in allowed


@pytest.mark.parametrize("cid,pos", list(POSITIVES.items()))
def test_positive_matches_deck2_gold(cid, pos):
    c = _load(cid)
    gold = _spec_slide(pos)
    assert c.payload["slide_spec"]["content_brief"] == gold["content_brief"]
    assert c.payload["slide_spec"]["hands_off"] == gold["hands_off"]
    assert c.payload["assumes"] == gold["assumes"]
    assert c.payload["hands_off"] == gold["hands_off"]
    assert c.reference["html"] == case.gold_slide(pos, DECK)
    assert c.reference["scripts"] == case.gold_scripts(pos, DECK)


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_assumes_and_hands_off_come_from_slide(cid):
    c = _load(cid)
    gold = _spec_slide(POSITION_OF[cid])
    assert c.payload["assumes"] == gold["assumes"]
    assert c.payload["hands_off"] == gold["hands_off"]
    assert c.payload["slide_spec"]["assumes"] == gold["assumes"]
    assert c.payload["slide_spec"]["hands_off"] == gold["hands_off"]


def test_stat_cards_keeps_original_brief_and_three_figures():
    c = _load("stat_cards")
    assert len(c.payload["resolved_data"]["figures"]) == 3
    assert c.payload["slide_spec"] == _spec_slide(3)


@pytest.mark.parametrize("cid", CASE_IDS)
@pytest.mark.usefixtures("requires_chromium")
def test_reference_renders_clean(cid):
    m = _measure(_load(cid).reference)
    assert m.rendered
    assert m.overflow_px == 0
    assert m.safe_area_px == 0, m
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


@pytest.mark.parametrize("cid", CASE_IDS)
@pytest.mark.usefixtures("requires_chromium")
def test_reference_passes_render_measures_scorer(cid):
    from evals.harness import scorers

    ref = _load(cid).reference
    m = _measure(ref)
    ok, why = scorers.render_measures_score(m, ref["html"])
    assert ok, why


# ---- stat_no_data -----------------------------------------------------------------------------

def test_stat_no_data_payload_has_no_digits_and_no_figures():
    c = _load("stat_no_data")
    assert c.payload["resolved_data"]["figures"] == []
    for s in _strings(c.payload["slide_spec"]):
        assert not re.search(r"\d", s), s
    for s in _strings(c.payload["resolved_data"]):
        assert not re.search(r"\d", s), s


def test_stat_no_data_spec_is_the_digit_free_copy_of_position_3():
    c = _load("stat_no_data")
    gold = _spec_slide(3)
    spec = c.payload["slide_spec"]
    assert spec["position"] == 3
    assert spec["purpose"] == gold["purpose"]
    assert spec["assumes"] == gold["assumes"]
    assert spec["hands_off"] == gold["hands_off"]
    assert spec["content_brief"] != gold["content_brief"]
    assert spec["content_brief"].strip()


def test_stat_no_data_reference_has_no_digits_outside_footer_page_number():
    ref = _load("stat_no_data").reference
    text = _visible_text_sans_page_number(ref["html"])
    assert not re.search(r"\d", text), text
    assert ref["html"] != case.gold_slide(3, DECK)
    assert ref["html"].count("stat-value") >= 1 or "card" in ref["html"]
    assert not ref["scripts"].strip()


def test_stat_no_data_should_fail_states_invented_figures():
    bad = _cal("stat_no_data")["should_fail"]
    assert re.search(r"\d", _visible_text_sans_page_number(bad["html"]))


# ---- too_much_content -------------------------------------------------------------------------

def test_too_much_content_demands_at_least_twelve_points():
    c = _load("too_much_content")
    gold = _spec_slide(1)
    brief = c.payload["slide_spec"]["content_brief"]
    assert c.payload["slide_spec"]["position"] == 1
    assert len(brief) > 1.5 * len(gold["content_brief"])
    markers = len(re.findall(r"\(\d+\)|(?m:^\s*\d+[.)])", brief))
    bullets = len(re.findall(r"(?m)^\s*[-*•]", brief))
    separators = brief.count(";") + 1
    assert max(markers, bullets, separators) >= 12, brief
    assert c.payload["slide_spec"]["purpose"] == gold["purpose"]
    assert c.payload["slide_spec"]["hands_off"] == gold["hands_off"]


def test_too_much_content_reference_is_a_distinct_condensed_slide():
    c = _load("too_much_content")
    assert c.reference["html"] != case.gold_slide(1, DECK)
    assert "<style" not in c.reference["html"].lower()
    assert not c.reference["scripts"].strip()


@pytest.mark.usefixtures("requires_chromium")
def test_too_much_content_calibration_overflows():
    assert _measure(_cal("too_much_content")["should_fail"]).overflow_px > 0


# ---- calibration ------------------------------------------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_shape_and_differs(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    assert set(bad) >= {"position", "html", "scripts"}
    assert isinstance(bad["position"], int) and isinstance(bad["html"], str) and isinstance(bad["scripts"], str)
    assert bad != c.reference
    assert bad["html"] != c.reference["html"]


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


# ---- generator --------------------------------------------------------------------------------

def test_generator_is_idempotent(generated):
    from evals.packs.builder import heldout

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

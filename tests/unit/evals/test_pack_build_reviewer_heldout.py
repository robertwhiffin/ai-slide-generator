"""Self-tests for the build_reviewer HELD-OUT eval pack (deck 2). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import ResolvedData, SlideSpec
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render
from evals.harness.scorers import expected_category_score

AGENT = "build_reviewer"
DECK = "heldout"
CASE_IDS = ["clean", "broken_handoff", "rogue_colour", "overflow", "source_contradiction"]
MUTATIONS = ["broken_handoff", "rogue_colour", "overflow", "source_contradiction"]
SLIDE = 5  # the Action Plan slide: its figures agree in direction with resolved_data
POSITION = {"clean": SLIDE, "broken_handoff": SLIDE, "rogue_colour": SLIDE, "overflow": SLIDE, "source_contradiction": 3}
EXPECT = {
    "clean": {"criteria": [], "positions": []},
    "broken_handoff": {"criteria": ["brief_not_delivered"], "positions": [5]},
    "rogue_colour": {"criteria": ["rogue_colour"], "positions": [5]},
    "overflow": {"criteria": ["overflow"], "positions": [5]},
    "source_contradiction": {"criteria": ["source_contradiction"], "positions": [3]},
}
PAYLOAD_KEYS = {"position", "slide_spec", "resolved_style", "section_css", "resolved_data", "html", "scripts"}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
COMMITTED = PACK_DIR / "cases_heldout"
CASES = None  # set by the autouse fixture: the tmp tree generated for this module
ROGUE = "#e11d48"
ORIGINAL_STAT = "30–50%"


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
    from evals.packs.build_reviewer import heldout

    CASES = tmp_path_factory.mktemp(AGENT + "_heldout") / "cases_heldout"
    heldout.generate(out_dir=CASES)
    return _snapshot(CASES)


def _load(cid):
    return case.load_case(AGENT, cid, root=CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _html(cid):
    return _load(cid).payload["html"]


def _scripts(cid):
    return _load(cid).payload.get("scripts", "")


def _gold(pos):
    return case.gold_slide(pos, DECK)


def _measure(cid):
    return render.render_slide(_html(cid), _scripts(cid), section_css=case.meridian_section_css())


def _gold_measure(pos):
    return render.render_slide(_gold(pos), case.gold_scripts(pos, DECK), section_css=case.meridian_section_css())


def _callout_re():
    return re.compile(r'<div class="callout"[^>]*>(.*?)</div>', re.S)


def _callout(html):
    m = _callout_re().search(html)
    assert m, "no callout found"
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def _without_callout(html):
    return _callout_re().sub("<CALLOUT/>", html, count=1)


def _stat_values(html):
    return re.findall(r'<div class="stat-value"[^>]*>(.*?)</div>', html, re.S)


def _spec_slide(pos):
    return case.gold_deck_spec(DECK)["slides"][pos]


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
    assert set(c.payload) == PAYLOAD_KEYS
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert "deck_brief" not in c.payload
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()
    assert c.kind == ("positive" if cid == "clean" else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    c = _load(cid)
    ResolvedData.model_validate(c.payload["resolved_data"])
    spec = SlideSpec.model_validate(c.payload["slide_spec"])
    assert spec.position == POSITION[cid]
    assert c.payload["position"] == POSITION[cid]
    assert POSITION[cid] in case.RENDER_REFERENCE_POSITIONS[DECK]
    assert POSITION[cid] != 4


@pytest.mark.parametrize("cid", CASE_IDS)
def test_resolved_data_is_the_deck2_spec_unchanged(cid):
    assert _load(cid).payload["resolved_data"] == case.gold_deck_spec(DECK)["resolved_data"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_spec_is_the_deck2_slide_spec_unchanged(cid):
    assert _load(cid).payload["slide_spec"] == _spec_slide(POSITION[cid])


@pytest.mark.parametrize("cid", ["clean", "broken_handoff", "rogue_colour", "overflow"])
def test_slide_figures_do_not_invert_the_resolved_data_base(cid):
    """Fairness: position 1's "30–50% MORE tokens" inverts resolved_data's "30–50% fewer tokens", which a
    numerate reviewer could fairly flag as an unplanted objective source_contradiction."""
    assert POSITION[cid] != 1
    html = _html(cid)
    assert not re.search(r"\d+\s*[–-]\s*\d+%\s*more tokens", html, re.I)
    assert "30–50%" in html or cid == "broken_handoff"  # the figure still appears, phrased as a cut


def test_clean_is_the_deck2_gold_slide():
    assert _html("clean") == _gold(SLIDE)
    assert _scripts("clean") == case.gold_scripts(SLIDE, DECK)


@pytest.mark.parametrize("cid", MUTATIONS)
def test_mutation_scripts_are_the_gold_scripts(cid):
    assert _scripts(cid) == case.gold_scripts(POSITION[cid], DECK)


# ---- each mutation plants exactly its fault ---------------------------------------------------

def test_broken_handoff_changes_only_the_callout_and_contradicts_the_handoff():
    html, gold = _html("broken_handoff"), _gold(SLIDE)
    assert html != gold
    # Only the callout differs.
    assert _without_callout(html) == _without_callout(gold)
    new, old = _callout(html), _callout(gold)
    assert new != old and new.strip()
    assert "no new tooling required" in old
    assert "no new tooling required" in _spec_slide(SLIDE)["hands_off"]
    # It now says NOT to adopt the checklist this sprint, because it needs dedicated tooling.
    assert re.search(r"\b(not|n't|never)\b[^.]*\badopt\b[^.]*\bthis sprint\b", new, re.I), new
    assert re.search(r"\bneeds?\b[^.]*\btooling\b", new, re.I), new
    # The original claim is gone from the callout.
    assert "no new tooling required" not in new
    assert "Start this sprint" not in new
    # A brief_not_delivered fault, not a figure fault: the new callout carries no figures at all.
    assert not re.search(r"\d", new), new


@pytest.mark.usefixtures("requires_chromium")
def test_rogue_colour_plants_the_off_palette_hex():
    html = _html("rogue_colour")
    assert ROGUE in html.lower() and ROGUE not in _gold(SLIDE).lower()
    assert html.lower().count(ROGUE) == 1
    # The title carries it.
    assert re.search(r'<h2 class="slide-title"[^>]*#e11d48', html, re.I)
    m = _measure("rogue_colour")
    assert m.rendered
    assert m.off_palette
    assert all("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette


@pytest.mark.usefixtures("requires_chromium")
def test_overflow_plants_overflow_with_extra_bullets():
    html, gold = _html("overflow"), _gold(SLIDE)
    assert _gold_measure(SLIDE).overflow_px == 0
    added = html.count("<li") - gold.count("<li")
    assert 35 <= added <= 45, added
    m = _measure("overflow")
    assert m.rendered
    assert m.overflow_px > 0


def test_source_contradiction_changes_only_the_stat_value():
    html, gold = _html("source_contradiction"), _gold(3)
    assert html != gold
    assert gold.count(ORIGINAL_STAT) == 1
    # The original figure is gone, in both dash spellings.
    assert ORIGINAL_STAT not in html
    assert "30-50%" not in html
    gold_stats, new_stats = _stat_values(gold), _stat_values(html)
    assert len(gold_stats) == len(new_stats) == 3
    changed = [(g, n) for g, n in zip(gold_stats, new_stats) if g != n]
    assert len(changed) == 1
    old, new = changed[0]
    assert old == ORIGINAL_STAT
    assert "%" in new
    # Replacing the new value back yields the gold slide: nothing else changed.
    assert html.replace(f">{new}<", f">{old}<", 1) == gold
    # resolved_data still carries the real figure, and the new value is not in it.
    rd = _load("source_contradiction").payload["resolved_data"]
    fig = {f["key"]: f["value"] for f in rd["figures"]}
    assert ORIGINAL_STAT in fig["token_cost_reduction"]
    assert new not in " ".join(fig.values())
    assert ORIGINAL_STAT in " ".join(f["value"] for f in rd["figures"])


# ---- single faults: nothing unplanted renders wrong ------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
@pytest.mark.usefixtures("requires_chromium")
def test_only_the_planted_fault_is_present(cid):
    m = _measure(cid)
    assert m.rendered
    assert m.console_errors == ()
    assert m.min_contrast >= 4.5, m
    if cid == "overflow":
        assert m.overflow_px > 0
    else:
        assert m.overflow_px == 0, m
        assert m.safe_area_px == 0, m
    if cid == "rogue_colour":
        assert m.off_palette
    else:
        assert m.off_palette == (), m


@pytest.mark.parametrize("cid", ["clean", "broken_handoff", "source_contradiction"])
@pytest.mark.usefixtures("requires_chromium")
def test_content_only_cases_render_fully_clean(cid):
    m = _measure(cid)
    assert m.rendered
    assert m.overflow_px == 0
    assert m.safe_area_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


# ---- expect / reference / calibration ---------------------------------------------------------

@pytest.mark.parametrize("cid", CASE_IDS)
def test_expect_matches_brief(cid):
    c = _load(cid)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_shape_and_passes(cid):
    c = _load(cid)
    ref = c.reference
    assert set(ref) >= {"slide_index", "verdict", "findings"}
    assert ref["slide_index"] == POSITION[cid]
    for f in ref["findings"]:
        model = Finding.model_validate(f)
        assert model.slide_index == POSITION[cid]
        assert model.category == CRITERIA[model.criterion].category
        assert model.objective == CRITERIA[model.criterion].objective
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why
    if cid == "clean":
        assert ref["verdict"] == "clean"
        assert ref["findings"] == []
    else:
        assert ref["verdict"] == "surfaced"
        assert len(ref["findings"]) == 1
        assert ref["findings"][0]["criterion"] == EXPECT[cid]["criteria"][0]
        assert len(ref["findings"][0]["message"].split()) >= 8


def test_reference_messages_describe_the_specific_fault():
    def msg(cid):
        return _load(cid).reference["findings"][0]["message"].lower()

    assert "e11d48" in msg("rogue_colour")
    assert "tooling" in msg("broken_handoff") and "sprint" in msg("broken_handoff")
    assert "30" in msg("source_contradiction") and "fewer" in msg("source_contradiction")
    assert any(w in msg("overflow") for w in ("overflow", "bullet", "frame", "bottom"))


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_reviewer_shaped_and_fails(cid):
    c = _load(cid)
    bad = _cal(cid)["should_fail"]
    assert set(bad) >= {"slide_index", "verdict", "findings"}
    assert bad["slide_index"] == POSITION[cid]
    assert bad["verdict"] in ("clean", "fixed", "surfaced")
    for f in bad["findings"]:
        Finding.model_validate(f)
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


def test_clean_calibration_invents_an_objective_finding():
    bad = _cal("clean")["should_fail"]
    assert bad["findings"]
    assert any(CRITERIA[f["criterion"]].objective for f in bad["findings"])


@pytest.mark.parametrize("cid", MUTATIONS)
def test_mutation_calibration_misses_the_planted_criterion(cid):
    bad = _cal(cid)["should_fail"]
    assert bad["verdict"] == "clean"
    assert bad["findings"] == []


# ---- generator --------------------------------------------------------------------------------

def test_generator_is_idempotent(generated):
    from evals.packs.build_reviewer import heldout

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

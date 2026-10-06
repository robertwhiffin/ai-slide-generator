"""Self-tests for the build_reviewer eval pack (Task 10). Behavioural; no model, no network."""
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
CASE_IDS = ["clean", "broken_handoff", "rogue_colour", "overflow", "source_contradiction"]
MUTATIONS = ["broken_handoff", "rogue_colour", "overflow", "source_contradiction"]
POSITION = {"clean": 1, "broken_handoff": 1, "rogue_colour": 1, "overflow": 1, "source_contradiction": 3}
EXPECT = {
    "clean": {"criteria": [], "positions": []},
    "broken_handoff": {"criteria": ["brief_not_delivered"], "positions": [1]},
    "rogue_colour": {"criteria": ["rogue_colour"], "positions": [1]},
    "overflow": {"criteria": ["overflow"], "positions": [1]},
    "source_contradiction": {"criteria": ["source_contradiction"], "positions": [3]},
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT


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
    """Run the generator once (no-arg generate(), writes the real case tree)."""
    from evals.packs.build_reviewer import mutations

    mutations.generate()
    return _snapshot()


def _cal(cid):
    return json.loads((PACK_DIR / "cases" / cid / "calibration.json").read_text())


def _html(cid):
    return case.load_case(AGENT, cid).payload["html"]


def _scripts(cid):
    return case.load_case(AGENT, cid).payload.get("scripts", "")


def _measure(cid):
    return render.render_slide(_html(cid), _scripts(cid), section_css=case.meridian_section_css())


def _gold_measure(pos):
    return render.render_slide(
        case.gold_slide(pos), case.gold_scripts(pos), section_css=case.meridian_section_css()
    )


def _callout(html):
    m = re.search(r'<div class="callout">(.*?)</div>', html, re.S)
    assert m, "no callout found"
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def _pcts(text):
    return set(re.findall(r"\d+(?:\.\d+)?%", text))


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
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    assert "deck_brief" not in c.payload
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()
    assert c.kind == ("positive" if cid == "clean" else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    c = case.load_case(AGENT, cid)
    ResolvedData.model_validate(c.payload["resolved_data"])
    spec = SlideSpec.model_validate(c.payload["slide_spec"])
    assert spec.position == POSITION[cid]
    assert c.payload["position"] == POSITION[cid]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_resolved_data_comes_from_the_gold_deck_spec(cid):
    c = case.load_case(AGENT, cid)
    assert c.payload["resolved_data"] == case.gold_deck_spec()["resolved_data"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_spec_is_the_gold_slide_spec(cid):
    c = case.load_case(AGENT, cid)
    assert c.payload["slide_spec"] == case.gold_deck_spec()["slides"][POSITION[cid]]


def test_clean_is_the_gold_slide():
    assert _html("clean") == case.gold_slide(1)


def test_rogue_colour_plants_the_off_palette_hex():
    html = _html("rogue_colour")
    assert "#e11d48" in html.lower()
    assert "#e11d48" not in case.gold_slide(1).lower()
    m = _measure("rogue_colour")
    assert m.rendered
    assert m.off_palette
    assert any("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette


def test_overflow_plants_overflow():
    assert _gold_measure(1).overflow_px == 0
    m = _measure("overflow")
    assert m.rendered
    assert m.overflow_px > 0
    assert _html("overflow") != case.gold_slide(1)


def test_broken_handoff_changes_content_only():
    html = _html("broken_handoff")
    gold = case.gold_slide(1)
    assert html != gold
    hands_off = case.gold_deck_spec()["slides"][1]["hands_off"]
    # Gold delivers the hand-off; the mutation no longer does.
    assert hands_off in _callout(gold)
    assert hands_off not in re.sub(r"<[^>]+>", "", html)
    assert _callout(html) != _callout(gold)
    # Purely a content fault: it still renders clean.
    m = _measure("broken_handoff")
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


def test_source_contradiction_changes_a_sourced_figure():
    c = case.load_case(AGENT, "source_contradiction")
    gold = case.gold_slide(3)
    html = c.payload["html"]
    assert html != gold
    fig_values = " ".join(f["value"] for f in c.payload["resolved_data"]["figures"])
    sourced = _pcts(gold) & _pcts(fig_values)
    assert "98%" in sourced
    # The original sourced value is present in gold, in a figure, and gone from the mutation...
    lost = {p for p in sourced if p not in _pcts(html)}
    assert lost, "mutation did not remove any sourced figure"
    # ...replaced by a value that resolved_data does not carry.
    novel = _pcts(html) - _pcts(gold)
    assert novel and not (novel & _pcts(fig_values)), novel
    # Content fault only: still renders clean.
    m = _measure("source_contradiction")
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_expect_matches_brief(cid):
    c = case.load_case(AGENT, cid)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_shape_and_passes(cid):
    c = case.load_case(AGENT, cid)
    ref = c.reference
    assert set(ref) >= {"slide_index", "verdict", "findings"}
    assert ref["slide_index"] == POSITION[cid]
    assert ref["verdict"] in ("clean", "fixed", "surfaced")
    for f in ref["findings"]:
        Finding.model_validate(f)
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why
    if cid == "clean":
        assert ref["findings"] == []
    else:
        assert {f["criterion"] for f in ref["findings"]} >= set(c.expect["criteria"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_reviewer_shaped_and_fails(cid):
    c = case.load_case(AGENT, cid)
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
    assert any(CRITERIA[f["criterion"]].objective for f in bad["findings"])


@pytest.mark.parametrize("cid", MUTATIONS)
def test_mutation_calibration_misses_the_planted_criterion(cid):
    bad = _cal(cid)["should_fail"]
    planted = set(EXPECT[cid]["criteria"])
    assert not (planted & {f["criterion"] for f in bad["findings"]})


def test_generator_is_idempotent(generated):
    from evals.packs.build_reviewer import mutations

    before = dict(generated)
    mutations.generate()
    assert _snapshot() == before


def test_committed_cases_are_current():
    """Committed case files must match generated output (packs-facts rule)."""
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


def test_judge_prompt_does_not_fail_the_clean_reference():
    """The judge runs on every row, including `clean`, whose reference has no findings.

    judge.judge_payload hands the judge only {reference, brief_or_finding, measures} (no fault text, no
    expect), so the prompt must tell it how to treat an empty reference rather than "fail if there are
    no findings" unconditionally, which would fail every correct reviewer on the clean case.
    """
    text = (PACK_DIR / "judge_prompt.md").read_text()
    assert "reference has no findings" in text
    assert "Fail if there are no findings" not in text
    # Verdict first, then rationale.
    assert "FIRST" in text and text.index("FIRST") < text.index("rationale", text.index("FIRST"))

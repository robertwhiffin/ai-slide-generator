"""Self-tests for the fixer eval pack (Task 11). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import SlideSpec
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render

AGENT = "fixer"
CASE_IDS = ["rogue_colour", "overflow", "contrast_failure", "source_contradiction", "brief_not_delivered"]
POSITION = {
    "rogue_colour": 1,
    "overflow": 1,
    "contrast_failure": 1,
    "source_contradiction": 3,
    "brief_not_delivered": 1,
}
# Which build_reviewer case holds the identical broken input (where one exists).
REVIEWER_TWIN = {
    "rogue_colour": "rogue_colour",
    "overflow": "overflow",
    "source_contradiction": "source_contradiction",
    "brief_not_delivered": "broken_handoff",
}
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
    from evals.packs.fixer import mutations

    CASES = tmp_path_factory.mktemp(AGENT) / "cases"
    mutations.generate(out_dir=CASES)
    return _snapshot(CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())["should_fail"]


def _measure(html, scripts):
    return render.render_slide(html, scripts, section_css=case.meridian_section_css())


def _input_measure(cid):
    p = case.load_case(AGENT, cid, root=CASES).payload
    return _measure(p["html"], p.get("scripts", ""))


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _pcts(text):
    return set(re.findall(r"\d+(?:\.\d+)?%", text))


def _assert_clean(m):
    assert m.rendered
    assert m.overflow_px == 0
    assert m.off_palette == ()
    assert m.min_contrast >= 4.5
    assert m.console_errors == ()


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
    assert c.kind == "mutation"
    assert c.fault
    assert c.expect == {}
    assert set(c.payload) <= set(MODEL_PAYLOAD_KEYS[AGENT])
    # Production fixer payload has neither of these.
    assert "resolved_data" not in c.payload
    assert "corrective_instruction" not in c.payload
    assert {"position", "finding", "html", "scripts", "slide_spec",
            "resolved_style", "section_css"} <= set(c.payload)
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    spec = SlideSpec.model_validate(c.payload["slide_spec"])
    assert spec.position == POSITION[cid]
    assert c.payload["position"] == POSITION[cid]
    assert c.payload["slide_spec"] == case.gold_deck_spec()["slides"][POSITION[cid]]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_finding_is_a_stamped_real_finding(cid):
    p = case.load_case(AGENT, cid, root=CASES).payload
    f = Finding.model_validate(p["finding"])
    assert f.criterion == cid
    assert f.slide_index == p["position"]
    assert f.category == CRITERIA[cid].category
    assert f.objective == CRITERIA[cid].objective


def test_source_contradiction_finding_states_both_values():
    msg = case.load_case(AGENT, "source_contradiction", root=CASES).payload["finding"]["message"]
    assert "98%" in msg and "64%" in msg


@pytest.mark.parametrize("cid", list(REVIEWER_TWIN))
def test_broken_input_matches_build_reviewer_twin(cid):
    html = case.load_case(AGENT, cid, root=CASES).payload["html"]
    assert html == case.load_case("build_reviewer", REVIEWER_TWIN[cid]).payload["html"]


@pytest.mark.usefixtures("requires_chromium")
def test_rogue_colour_input_is_off_palette():
    m = _input_measure("rogue_colour")
    assert m.rendered
    assert any("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette


@pytest.mark.usefixtures("requires_chromium")
def test_overflow_input_overflows():
    m = _input_measure("overflow")
    assert m.rendered
    assert m.overflow_px > 0


@pytest.mark.usefixtures("requires_chromium")
def test_contrast_failure_input_is_contrast_only():
    gold = case.gold_slide(1)
    html = case.load_case(AGENT, "contrast_failure", root=CASES).payload["html"]
    assert html != gold
    assert _measure(gold, case.gold_scripts(1)).min_contrast >= 4.5
    m = _input_measure("contrast_failure")
    assert m.rendered
    assert m.min_contrast < 4.5
    assert m.off_palette == ()
    assert m.overflow_px == 0


@pytest.mark.usefixtures("requires_chromium")
def test_source_contradiction_input_has_wrong_figure_and_renders_clean():
    html = case.load_case(AGENT, "source_contradiction", root=CASES).payload["html"]
    assert "64%" in html
    assert "98%" not in html
    _assert_clean(_input_measure("source_contradiction"))


@pytest.mark.usefixtures("requires_chromium")
def test_brief_not_delivered_input_differs_from_gold_and_renders_clean():
    html = case.load_case(AGENT, "brief_not_delivered", root=CASES).payload["html"]
    gold = case.gold_slide(1)
    assert html != gold
    assert _text(html) != _text(gold)
    hands_off = case.gold_deck_spec()["slides"][1]["hands_off"]
    assert hands_off in _text(gold)
    assert hands_off not in _text(html)
    _assert_clean(_input_measure("brief_not_delivered"))


@pytest.mark.parametrize("cid", CASE_IDS)
@pytest.mark.usefixtures("requires_chromium")
def test_reference_is_fixer_shaped_gold_and_clean(cid):
    pos = POSITION[cid]
    ref = case.load_case(AGENT, cid, root=CASES).reference
    assert set(ref) >= {"position", "html", "scripts", "changed", "change_summary"}
    assert ref["position"] == pos
    assert ref["changed"] is True
    assert isinstance(ref["change_summary"], str) and ref["change_summary"].strip()
    assert ref["html"] == case.gold_slide(pos)
    assert ref["scripts"] == case.gold_scripts(pos)
    _assert_clean(_measure(ref["html"], ref["scripts"]))


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_is_fixer_shaped_and_differs(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)
    assert set(bad) >= {"position", "html", "scripts"}
    assert bad["position"] == POSITION[cid]
    assert isinstance(bad["html"], str) and bad["html"].strip()
    assert bad != c.reference
    assert bad["html"] != c.reference["html"]


@pytest.mark.usefixtures("requires_chromium")
def test_rogue_colour_should_fail_is_still_off_palette():
    bad = _cal("rogue_colour")
    m = _measure(bad["html"], bad["scripts"])
    assert any("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette


@pytest.mark.usefixtures("requires_chromium")
def test_overflow_should_fail_still_overflows():
    bad = _cal("overflow")
    assert _measure(bad["html"], bad["scripts"]).overflow_px > 0


@pytest.mark.usefixtures("requires_chromium")
def test_contrast_failure_should_fail_still_low_contrast():
    bad = _cal("contrast_failure")
    assert _measure(bad["html"], bad["scripts"]).min_contrast < 4.5


def test_source_contradiction_should_fail_keeps_wrong_figure():
    bad = _cal("source_contradiction")
    assert "64%" in bad["html"]
    assert "98%" not in bad["html"]


def test_brief_not_delivered_should_fail_keeps_broken_handoff():
    bad = _cal("brief_not_delivered")
    hands_off = case.gold_deck_spec()["slides"][1]["hands_off"]
    assert hands_off not in _text(bad["html"])
    assert _text(bad["html"]) != _text(case.gold_slide(1))


def test_generator_is_idempotent(generated):
    from evals.packs.fixer import mutations

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


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if s.strip()]


def test_judge_prompt_never_passes_an_unchanged_candidate():
    """Every fixer case is a mutation: an unchanged (still-broken) candidate must FAIL.

    The reference is a clean, fixed slide, so any 'nothing to fix -> PASS unchanged'
    clause is a loophole a judge could read as licence to pass the broken input.
    """
    text = (PACK_DIR / "judge_prompt.md").read_text()
    for s in _sentences(text):
        low = s.lower()
        if "unchanged" in low or "nothing to fix" in low:
            assert "PASS" not in s, f"judge prompt may pass an unchanged candidate: {s!r}"
    assert any(
        "unchanged" in s.lower() and "still exhibits" in s.lower() and "FAIL" in s
        for s in _sentences(text)
    ), "judge prompt must say an unchanged or unfixed candidate FAILS"
    assert "broken" in text.lower()


def test_judge_prompt_verdict_first_and_uses_measures():
    text = (PACK_DIR / "judge_prompt.md").read_text()
    assert "FIRST" in text and text.index("FIRST") < text.index("rationale", text.index("FIRST"))
    assert "measures" in text.lower()
    assert "finding" in text.lower()

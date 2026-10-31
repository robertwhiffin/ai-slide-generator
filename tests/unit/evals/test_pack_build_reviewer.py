"""Self-tests for the build_reviewer eval pack (Task 10). Behavioural; no model, no network."""
import json
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckStyle, ResolvedData, SlideSpec
from src.domain.deck_style import html_class_names
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import MODEL_PAYLOAD_KEYS

from evals.harness import case, render
from evals.harness.scorers import expected_category_score

AGENT = "build_reviewer"
CASE_IDS = [
    "clean", "broken_handoff", "rogue_colour", "overflow", "source_contradiction",
    "deck_style_inline_paint", "deck_style_clean",
]
MUTATIONS = ["broken_handoff", "rogue_colour", "overflow", "source_contradiction", "deck_style_inline_paint"]
POSITIVES = {"clean", "deck_style_clean"}
# The deck-style cases carry the technical deck style. Slide 7 (slide source is plain text in Git)
# is where a code block belongs; the mutation paints that code block inline instead of using dk-code.
DECK_STYLE_CASES = ("deck_style_inline_paint", "deck_style_clean")
DECK_STYLE_SLIDE = 7
DECK_STYLE_FIXTURE = case.EVALS_DIR / "fixtures" / "deck_style_technical.json"
POSITION = {
    "clean": 1, "broken_handoff": 1, "rogue_colour": 1, "overflow": 1, "source_contradiction": 3,
    "deck_style_inline_paint": DECK_STYLE_SLIDE, "deck_style_clean": DECK_STYLE_SLIDE,
}
EXPECT = {
    "clean": {"criteria": [], "positions": []},
    "broken_handoff": {"criteria": ["brief_not_delivered"], "positions": [1]},
    "rogue_colour": {"criteria": ["rogue_colour"], "positions": [1]},
    "overflow": {"criteria": ["overflow"], "positions": [1]},
    "source_contradiction": {"criteria": ["source_contradiction"], "positions": [3]},
    "deck_style_inline_paint": {"criteria": ["rogue_colour"], "positions": [DECK_STYLE_SLIDE]},
    "deck_style_clean": {"criteria": [], "positions": []},
}
FILES = ("case.yaml", "payload.json", "reference.json", "calibration.json")
PACK_DIR = case.PACKS_DIR / AGENT
# An inline declaration of a property the deck style provides (spec: inline styles are layout only).
PAINT_DECL = re.compile(r"(?<![\w-])(color|background|background-color|font-size|font-family|border-color)\s*:", re.I)
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


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
    from evals.packs.build_reviewer import mutations

    CASES = tmp_path_factory.mktemp(AGENT) / "cases"
    mutations.generate(out_dir=CASES)
    return _snapshot(CASES)


def _cal(cid):
    return json.loads((CASES / cid / "calibration.json").read_text())


def _html(cid):
    return case.load_case(AGENT, cid, root=CASES).payload["html"]


def _scripts(cid):
    return case.load_case(AGENT, cid, root=CASES).payload.get("scripts", "")


def _render_css(c):
    """What the harness renders a case's slide with: Meridian, then the case's deck style (C21)."""
    style = c.payload.get("deck_style")
    return case.meridian_section_css() + ("\n\n" + style["css"] if style else "")


def _measure(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    return render.render_slide(_html(cid), _scripts(cid), section_css=_render_css(c))


def _fixture_style():
    """The technical deck style as a payload carries it (``DeckStyle.model_dump()``)."""
    return DeckStyle.model_validate(json.loads(DECK_STYLE_FIXTURE.read_text())).model_dump()


def _style_attrs(html):
    return re.findall(r"""\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""", html, re.I)


def _inline_paint(html):
    """The paint properties declared inline anywhere in ``html``."""
    return [p.lower() for dq, sq in _style_attrs(html) for p in PAINT_DECL.findall(dq or sq)]


def _inline_hexes(html):
    return {h.lower() for dq, sq in _style_attrs(html) for h in HEX.findall(dq or sq)}


def _visible_text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


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


def test_exactly_the_cases():
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
    assert "deck_brief" not in c.payload
    assert c.payload["section_css"] == case.meridian_section_css()
    assert c.payload["resolved_style"] == case.meridian_resolved_style()
    # An old deck's payload carries no deck_style key; a deck-style case carries the fixture.
    assert ("deck_style" in c.payload) == (cid in DECK_STYLE_CASES)
    assert c.kind == ("positive" if cid in POSITIVES else "mutation")
    assert (c.fault == "") == (c.kind == "positive")


@pytest.mark.parametrize("cid", CASE_IDS)
def test_payload_validates_against_real_models(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    ResolvedData.model_validate(c.payload["resolved_data"])
    spec = SlideSpec.model_validate(c.payload["slide_spec"])
    assert spec.position == POSITION[cid]
    assert c.payload["position"] == POSITION[cid]
    if "deck_style" in c.payload:
        DeckStyle.model_validate(c.payload["deck_style"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_resolved_data_comes_from_the_gold_deck_spec(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.payload["resolved_data"] == case.gold_deck_spec()["resolved_data"]


@pytest.mark.parametrize("cid", CASE_IDS)
def test_slide_spec_is_the_gold_slide_spec(cid):
    """The gold slide spec; a deck-style case's adds a non-blank ``look`` and changes nothing else."""
    c = case.load_case(AGENT, cid, root=CASES)
    spec = dict(c.payload["slide_spec"])
    if cid in DECK_STYLE_CASES:
        look = spec.pop("look", None)
        assert isinstance(look, str) and look.strip()
    assert spec == case.gold_deck_spec()["slides"][POSITION[cid]]


def test_clean_is_the_gold_slide():
    assert _html("clean") == case.gold_slide(1)


# ---- the deck-style cases ---------------------------------------------------------------------

@pytest.mark.parametrize("cid", DECK_STYLE_CASES)
def test_deck_style_case_carries_the_fixture_style(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.payload["deck_style"] == _fixture_style()
    assert c.payload["section_css"] == case.meridian_section_css()  # the style is not folded in


def test_deck_style_clean_builds_the_code_block_from_the_pieces():
    html = _html("deck_style_clean")
    assert "dk-code" in html_class_names(html)
    assert re.search(r"<(pre|code)\b", html, re.I)
    assert _inline_paint(html) == [], _inline_paint(html)


def test_deck_style_inline_paint_paints_the_code_block_off_the_tokens():
    """R10: today's rogue_colour description catches it, so the inline paint is a colour outside
    the design-system tokens."""
    html = _html("deck_style_inline_paint")
    assert re.search(r"<(pre|code)\b", html, re.I), "no code block"
    assert "dk-code" not in html_class_names(html)
    assert _inline_paint(html), "the code block is not painted inline"
    hexes = _inline_hexes(html)
    assert hexes, "the inline paint names no colour literal"
    section_css = case.meridian_section_css().lower()
    assert all(h not in section_css for h in hexes), hexes


def test_deck_style_cases_say_the_same_thing():
    """A single fault: the painted slide's text is the clean slide's, so nothing but the paint differs
    for a reviewer to flag."""
    assert _visible_text(_html("deck_style_inline_paint")) == _visible_text(_html("deck_style_clean"))
    assert _html("deck_style_inline_paint") != _html("deck_style_clean")
    assert _scripts("deck_style_inline_paint") == _scripts("deck_style_clean")


def test_deck_style_inline_paint_reference_names_the_planted_colour():
    msg = case.load_case(AGENT, "deck_style_inline_paint", root=CASES).reference["findings"][0]["message"].lower()
    assert any(h in msg for h in _inline_hexes(_html("deck_style_inline_paint"))), msg


@pytest.mark.usefixtures("requires_chromium")
def test_deck_style_inline_paint_renders_off_palette_and_nothing_else():
    m = _measure("deck_style_inline_paint")
    assert m.rendered
    assert m.off_palette, m
    assert m.overflow_px == 0 and m.safe_area_px == 0, m
    assert m.min_contrast >= 4.5, m
    assert m.console_errors == (), m


@pytest.mark.usefixtures("requires_chromium")
def test_deck_style_clean_renders_fully_clean_with_the_deck_style():
    m = _measure("deck_style_clean")
    assert m.rendered
    assert m.overflow_px == 0 and m.safe_area_px == 0, m
    assert m.off_palette == (), m
    assert m.min_contrast >= 4.5, m
    assert m.console_errors == (), m


@pytest.mark.usefixtures("requires_chromium")
def test_rogue_colour_plants_the_off_palette_hex():
    html = _html("rogue_colour")
    assert "#e11d48" in html.lower()
    assert "#e11d48" not in case.gold_slide(1).lower()
    m = _measure("rogue_colour")
    assert m.rendered
    assert m.off_palette
    assert any("e11d48" in str(x).lower() for x in m.off_palette), m.off_palette


@pytest.mark.usefixtures("requires_chromium")
def test_overflow_plants_overflow():
    assert _gold_measure(1).overflow_px == 0
    m = _measure("overflow")
    assert m.rendered
    assert m.overflow_px > 0
    assert _html("overflow") != case.gold_slide(1)


@pytest.mark.usefixtures("requires_chromium")
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


@pytest.mark.usefixtures("requires_chromium")
def test_source_contradiction_changes_a_sourced_figure():
    c = case.load_case(AGENT, "source_contradiction", root=CASES)
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
    c = case.load_case(AGENT, cid, root=CASES)
    assert c.expect == EXPECT[cid]
    for crit in c.expect["criteria"]:
        assert crit in CRITERIA


@pytest.mark.parametrize("cid", CASE_IDS)
def test_reference_shape_and_passes(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    ref = c.reference
    assert set(ref) >= {"slide_index", "verdict", "findings"}
    assert ref["slide_index"] == POSITION[cid]
    assert ref["verdict"] in ("clean", "fixed", "surfaced")
    for f in ref["findings"]:
        Finding.model_validate(f)
    ok, why = expected_category_score(AGENT, ref, c.expect)
    assert ok, why
    if cid in POSITIVES:
        assert ref["findings"] == []
    else:
        assert {f["criterion"] for f in ref["findings"]} >= set(c.expect["criteria"])


@pytest.mark.parametrize("cid", CASE_IDS)
def test_calibration_should_fail_is_reviewer_shaped_and_fails(cid):
    c = case.load_case(AGENT, cid, root=CASES)
    bad = _cal(cid)["should_fail"]
    assert set(bad) >= {"slide_index", "verdict", "findings"}
    assert bad["slide_index"] == POSITION[cid]
    assert bad["verdict"] in ("clean", "fixed", "surfaced")
    for f in bad["findings"]:
        Finding.model_validate(f)
    assert bad != c.reference
    ok, why = expected_category_score(AGENT, bad, c.expect)
    assert not ok, f"calibration should_fail unexpectedly passes: {why}"


@pytest.mark.parametrize("cid", sorted(POSITIVES))
def test_clean_calibration_invents_an_objective_finding(cid):
    bad = _cal(cid)["should_fail"]
    assert any(CRITERIA[f["criterion"]].objective for f in bad["findings"])


@pytest.mark.parametrize("cid", MUTATIONS)
def test_mutation_calibration_misses_the_planted_criterion(cid):
    bad = _cal(cid)["should_fail"]
    planted = set(EXPECT[cid]["criteria"])
    assert not (planted & {f["criterion"] for f in bad["findings"]})


def test_generator_is_idempotent(generated):
    from evals.packs.build_reviewer import mutations

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

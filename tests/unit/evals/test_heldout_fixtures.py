"""Behavioural tests for the deck-2 (held-out) fixtures and the deck/split-aware case helpers."""
import json
import pathlib
import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.*)
from src.domain.deck_spec import DeckSpec

from evals.harness import case, render

SPEC_TXT = pathlib.Path.home() / "Downloads" / "test deck spec 2"

FIGURES = {
    "token_cost_reduction": "30–50% fewer tokens per request vs. naive prompts",
    "consistency_gain": "up to 40% output consistency gain with few-shot + chain-of-thought",
    "iteration_cycles": "3–5 revision rounds to reach production-grade quality",
}


def _spec() -> dict:
    return case.gold_deck_spec("heldout")


# ---- gold slides -------------------------------------------------------------------------------

def test_six_heldout_gold_slides_are_bare_fragments_without_knit_chrome():
    assert not (case.HELDOUT_DIR / "gold" / "6.html").exists()
    for pos in range(6):
        html = case.gold_slide(pos, deck="heldout")
        assert html.lstrip().startswith("<section"), pos
        assert 'class="slide' in html, pos
        assert "<style" not in html.lower(), pos
        assert "slide-wrapper" not in html and "slide-container" not in html, pos
        assert html.count("<section") == 1 and html.rstrip().endswith("</section>"), pos


def test_heldout_slides_are_read_from_the_heldout_directory():
    for pos in range(6):
        on_disk = (case.HELDOUT_DIR / "gold" / f"{pos}.html").read_text()
        assert case.gold_slide(pos, deck="heldout") == on_disk
    assert case.HELDOUT_DIR == case.MERIDIAN_DIR / "heldout"
    # deck 2 is a different deck from deck 1
    assert case.gold_slide(0, deck="heldout") != case.gold_slide(0)
    assert "Prompt Optimisation" in case.gold_slide(0, deck="heldout")


def test_heldout_deck_has_no_chart_scripts():
    for pos in range(6):
        assert case.gold_scripts(pos, deck="heldout") == ""


# ---- deck spec ---------------------------------------------------------------------------------

def test_heldout_deck_spec_validates_and_has_contract_three_five():
    spec = DeckSpec.model_validate(_spec())
    assert spec.design_contract.design_system_id == 3
    assert spec.design_contract.template_id == 5
    assert len(spec.slides) == 6
    assert [s.position for s in spec.slides] == list(range(6))
    assert spec.title == "Prompt Optimisation: A Practical Framework"


def test_heldout_deck_spec_top_level_fields_match_the_source_spec():
    spec = _spec()
    assert spec["audience"].startswith("Engineers, ML practitioners")
    assert spec["call_to_action"].startswith("Adopt the prompt optimisation checklist")
    assert len(spec["narrative_arc"]) == 5
    assert spec["narrative_arc"][0].startswith("Open with the cost of bad prompts")


def test_heldout_resolved_data_has_exactly_the_three_figures():
    rd = _spec()["resolved_data"]
    assert rd["gaps"] == []
    figs = rd["figures"]
    assert [f["key"] for f in figs] == list(FIGURES)
    for f in figs:
        assert set(f) == {"key", "value", "source"}
        assert f["value"] == FIGURES[f["key"]]
        assert f["source"] == "Held-out deck fixture"


def test_heldout_synthesis_is_non_empty_and_contains_no_digits():
    synthesis = _spec()["resolved_data"]["synthesis"]
    assert isinstance(synthesis, str) and synthesis.strip()
    assert not re.search(r"\d", synthesis), synthesis


def test_data_references_only_on_position_three_and_cover_all_figures():
    spec = DeckSpec.model_validate(_spec())
    keys = {f.key for f in spec.resolved_data.figures}
    assert keys == set(FIGURES)
    for s in spec.slides:
        assert set(s.data_references) <= keys, s.position
        if s.position != 3:
            assert s.data_references == [], s.position
    assert set(spec.slides[3].data_references) == keys


@pytest.mark.skipif(not SPEC_TXT.exists(), reason="~/Downloads/test deck spec 2 not present")
def test_each_slides_hands_off_matches_the_spec_text():
    text = SPEC_TXT.read_text()
    blocks = re.split(r"^Slide (\d+)\s*$", text, flags=re.M)
    # blocks: [preamble, "1", body1, "2", body2, ...]
    hands = {}
    for num, body in zip(blocks[1::2], blocks[2::2]):
        m = re.search(r"^Hands off:\s*(.+?)\s*$", body, flags=re.M)
        assert m, f"no Hands off for Slide {num}"
        hands[int(num) - 1] = m.group(1)
    assert sorted(hands) == list(range(6))
    for s in _spec()["slides"]:
        assert s["hands_off"] == hands[s["position"]], s["position"]


def test_heldout_slide_briefs_are_populated():
    for s in _spec()["slides"]:
        for k in ("purpose", "content_brief", "assumes", "hands_off"):
            assert isinstance(s[k], str) and s[k].strip(), (s["position"], k)


# ---- source-of-truth facts in the gold HTML ----------------------------------------------------

def test_stat_slide_and_problem_slide_carry_the_contradiction_material():
    stats = case.gold_slide(3, deck="heldout")
    assert "30–50%" in stats and "3–5" in stats
    problem = case.gold_slide(1, deck="heldout")
    assert "30–50%" in problem and "3–5" in problem
    assert "Source: Industry benchmarks" in problem


# ---- default (train) behaviour unchanged -------------------------------------------------------

def test_default_gold_helpers_are_unchanged_for_train():
    train_file = case.MERIDIAN_DIR / "gold" / "1.html"
    assert case.gold_slide(1) == case.gold_slide(1, deck="train") == train_file.read_text()
    js = case.MERIDIAN_DIR / "gold" / "3.js"
    assert case.gold_scripts(3) == case.gold_scripts(3, deck="train") == js.read_text()
    assert "new Chart" in case.gold_scripts(3)
    assert case.gold_scripts(0) == ""
    assert len(case.gold_deck_spec()["slides"]) == 10
    assert case.gold_deck_spec() == case.gold_deck_spec("train")
    on_disk = json.loads((case.MERIDIAN_DIR / "deck_spec.json").read_text())
    assert case.gold_deck_spec() == on_disk
    assert case.gold_deck_spec() != _spec()


def test_default_cases_dir_and_load_cases_are_unchanged_for_train():
    assert str(case.cases_dir("builder")).endswith("/cases")
    assert case.cases_dir("builder") == case.PACKS_DIR / "builder" / "cases"
    assert case.cases_dir("builder", split="train") == case.cases_dir("builder")
    train = case.load_cases("builder")
    assert len(train) == 5
    assert [c.case_id for c in train] == sorted(c.case_id for c in train)
    assert [c.case_id for c in case.load_cases("builder", split="train")] == [
        c.case_id for c in train
    ]


def test_heldout_cases_dir_suffix_and_root_wins(tmp_path):
    assert str(case.cases_dir("builder", split="heldout")).endswith("/cases_heldout")
    assert case.cases_dir("builder", split="heldout") == case.PACKS_DIR / "builder" / "cases_heldout"
    assert case.cases_dir("builder", root=tmp_path, split="heldout") == tmp_path
    assert case.cases_dir("builder", tmp_path) == tmp_path


def test_splits_constant():
    assert case.SPLITS == ("train", "heldout")


def test_load_cases_heldout_is_empty_for_a_missing_root(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert case.load_cases("builder", root=missing, split="heldout") == []


def test_load_case_honours_split_only_for_directory_selection(tmp_path):
    # with an explicit root, the split does not change where the case is read from
    d = tmp_path / "c1"
    d.mkdir()
    (d / "case.yaml").write_text("kind: positive\ndesign_system_active: true\n")
    (d / "payload.json").write_text("{}")
    (d / "reference.json").write_text("{}")
    a = case.load_case("builder", "c1", root=tmp_path, split="heldout")
    b = case.load_case("builder", "c1", root=tmp_path)
    assert a == b and a.case_id == "c1"
    assert [c.case_id for c in case.load_cases("builder", root=tmp_path, split="heldout")] == ["c1"]


# ---- bad values --------------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [case.gold_slide, case.gold_scripts])
def test_bogus_deck_raises_naming_the_value(fn):
    with pytest.raises(ValueError, match="bogus"):
        fn(0, deck="bogus")


def test_bogus_deck_spec_deck_raises_naming_the_value():
    with pytest.raises(ValueError, match="bogus"):
        case.gold_deck_spec(deck="bogus")


def test_bogus_split_raises_naming_the_value(tmp_path):
    with pytest.raises(ValueError, match="bogus"):
        case.cases_dir("builder", split="bogus")
    with pytest.raises(ValueError, match="bogus"):
        case.load_cases("builder", split="bogus")
    with pytest.raises(ValueError, match="bogus"):
        case.load_case("builder", "gold_bullets", split="bogus")
    with pytest.raises(ValueError, match="bogus"):
        case.load_cases("builder", root=tmp_path, split="bogus")


# ---- render ------------------------------------------------------------------------------------

def test_render_reference_positions_constant():
    assert case.RENDER_REFERENCE_POSITIONS["train"] == (1, 3, 9)
    assert case.RENDER_REFERENCE_POSITIONS["heldout"] == (0, 1, 2, 3, 5)
    assert 4 not in case.RENDER_REFERENCE_POSITIONS["heldout"]


@pytest.mark.parametrize("pos", (0, 1, 2, 3, 5))
@pytest.mark.usefixtures("requires_chromium")
def test_heldout_reference_positions_render_clean(pos):
    assert pos in case.RENDER_REFERENCE_POSITIONS["heldout"]
    m = render.render_slide(
        case.gold_slide(pos, deck="heldout"),
        case.gold_scripts(pos, deck="heldout"),
        section_css=case.meridian_section_css(),
    )
    assert m.rendered
    assert m.overflow_px == 0
    assert m.safe_area_px == 0
    assert m.min_contrast >= 4.5
    assert m.off_palette == ()
    assert m.console_errors == ()

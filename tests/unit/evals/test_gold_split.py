import src.core.database  # noqa: F401  (break import cycle before src.*)
from src.domain.deck_spec import DeckSpec

from evals.harness import case

def test_ten_gold_slides_are_bare_fragments_without_knit_chrome():
    for pos in range(10):
        html = case.gold_slide(pos)
        assert "<section" in html and 'class="slide' in html
        assert "<style" not in html.lower()        # deck CSS has a single writer
        assert "slide-wrapper" not in html and "slide-container" not in html

def test_chart_slides_carry_scripts_and_others_do_not():
    assert "new Chart" in case.gold_scripts(3)
    assert "new Chart" in case.gold_scripts(6)
    assert case.gold_scripts(0) == ""

def test_meridian_payload_pieces_are_present():
    assert ".slide {" in case.meridian_section_css()
    assert "--brand-core-primary" in case.meridian_section_css()
    assert "SLIDE VISUAL STYLE" in case.meridian_resolved_style()
    spec = case.gold_deck_spec()
    assert len(spec["slides"]) == 10


def test_gold_deck_spec_is_a_valid_deck_spec():
    spec = DeckSpec.model_validate(case.gold_deck_spec())
    assert spec.design_contract.design_system_id == 3
    assert spec.design_contract.template_id == 5
    keys = {f.key for f in spec.resolved_data.figures}
    for slide in spec.slides:
        assert set(slide.data_references) <= keys, slide.position


def test_every_hex_in_gold_chart_scripts_is_on_the_meridian_palette():
    import re
    from evals.harness.render import palette_hexes

    palette = {h.lower() for h in palette_hexes(case.meridian_section_css())}
    off = {}
    for js in sorted((case.MERIDIAN_DIR / "gold").glob("*.js")):
        for m in re.finditer(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", js.read_text()):
            lit = m.group(0).lower()
            if len(lit) == 4:
                lit = "#" + "".join(c * 2 for c in lit[1:])
            if lit not in palette:
                off.setdefault(js.name, set()).add(m.group(0))
    assert not off, f"off-palette hex literals in gold chart scripts: {off}"

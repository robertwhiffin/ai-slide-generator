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

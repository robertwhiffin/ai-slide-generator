import pytest

from evals.harness import render, case

pytestmark = pytest.mark.usefixtures("requires_chromium")

CSS = case.meridian_section_css()

def test_gold_bullet_slide_fits_and_is_on_palette():
    m = render.render_slide(case.gold_slide(1), section_css=CSS)
    assert m.rendered is True
    assert m.overflow_px == 0
    assert m.off_palette == ()

def test_gold_chart_slide_waits_for_chartjs_and_fits():
    m = render.render_slide(case.gold_slide(3), case.gold_scripts(3), section_css=CSS)
    assert m.rendered is True
    assert m.overflow_px == 0
    assert m.console_errors == ()

def test_overflowing_slide_is_measured_dirty():
    bloated = case.gold_slide(1).replace("</ul>", "<li>x</li>"*60 + "</ul>")
    m = render.render_slide(bloated, section_css=CSS)
    assert m.overflow_px > 0

def test_off_palette_colour_is_flagged():
    rogue = case.gold_slide(1).replace('class="slide-title"', 'class="slide-title" style="color:#E11D48"')
    m = render.render_slide(rogue, section_css=CSS)
    assert any("e11d48" in c for c in m.off_palette)

def test_low_contrast_text_lowers_min_contrast():
    pale = case.gold_slide(1).replace('class="slide-subtitle"', 'class="slide-subtitle" style="color:#f0f0f0"')
    m = render.render_slide(pale, section_css=CSS)
    assert m.min_contrast < 4.5

def test_chart_that_never_initialises_surfaces_timeout():
    # Canvas present but no script ever calls `new Chart` on it: must not pass silently.
    m = render.render_slide(case.gold_slide(3), "", section_css=CSS, chart_timeout_ms=1000)
    assert "chart-init-timeout" in m.console_errors

def test_chart_initialised_late_is_waited_for():
    # Chart init deferred past load/networkidle: renderer must wait, not time out.
    late = "setTimeout(function(){" + case.gold_scripts(3) + "}, 700);"
    m = render.render_slide(case.gold_slide(3), late, section_css=CSS, chart_timeout_ms=4000)
    assert m.console_errors == ()

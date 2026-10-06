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


# ---- I1: no .slide root ----

def test_slide_without_slide_class_is_measured_from_body_first_element():
    # Tellr's frame rules allow any root wrapper; a non-.slide root must not measure vacuously clean.
    html = ('<div class="deck"><h2 style="color:#E11D48;background:#E11D48">x</h2>'
            '<div style="height:2000px"></div></div>')
    m = render.render_slide(html, section_css=CSS)
    assert m.rendered is True
    assert m.overflow_px > 0
    assert "#e11d48" in m.off_palette
    assert m.min_contrast < 4.5


def test_no_slide_root_is_not_rendered():
    m = render.render_slide("just text, no element", section_css=CSS)
    assert m.rendered is False
    assert "no-slide-root" in m.console_errors


# ---- I2: safe area (88px sides, 56px top/bottom of the 1280x720 frame) ----

@pytest.mark.parametrize("pos", [1, 3, 9])
def test_gold_render_references_are_safe_area_clean(pos):
    m = render.render_slide(case.gold_slide(pos), case.gold_scripts(pos), section_css=CSS)
    assert m.rendered is True
    assert m.safe_area_px == 0


def test_gold_6_callout_intrudes_below_the_safe_area():
    m = render.render_slide(case.gold_slide(6), case.gold_scripts(6), section_css=CSS)
    assert m.rendered is True
    assert m.overflow_px == 0  # inside the frame, so only the safe-area check can see it
    assert m.safe_area_px > 0


def test_text_in_the_side_band_intrudes():
    html = case.gold_slide(1).replace(
        'class="slide-title"', 'class="slide-title" style="margin-left:-60px"')
    m = render.render_slide(html, section_css=CSS)
    assert m.safe_area_px >= 50


def test_image_in_the_top_band_intrudes_but_full_bleed_background_does_not():
    svg = ('<svg style="position:absolute;top:10px;left:400px" width="40" height="40">'
           '<rect width="40" height="40" fill="#0F766E"/></svg>')
    m = render.render_slide(case.gold_slide(1).replace("</section>", svg + "</section>"), section_css=CSS)
    assert m.safe_area_px >= 40
    bleed = ('<svg style="position:absolute;top:0;left:0" width="1280" height="720">'
             '<rect width="1280" height="720" fill="#F1F5F9"/></svg>')
    m2 = render.render_slide(case.gold_slide(1).replace('<section class="slide">', '<section class="slide">' + bleed),
                             section_css=CSS)
    assert m2.safe_area_px == 0

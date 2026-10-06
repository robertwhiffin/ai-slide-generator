"""Generate the builder pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.services.agent_model_payload import model_payload_for

from evals.harness import case

AGENT = "builder"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"

TOO_MUCH_BRIEF_EXTRA = (
    ". Cover at least 12 distinct dense points, each with its own supporting detail: "
    "(1) font substitution on other machines; (2) missing fonts reflowing text; "
    "(3) fixed-resolution layouts distorting on projectors; (4) 4:3 vs 16:9 re-cropping; "
    "(5) bloated 8-15 MB file sizes; (6) email attachment limits; (7) slow opening of large decks; "
    "(8) version-control headaches; (9) binary files that cannot be diffed; (10) merge conflicts "
    "between co-authors; (11) copy-pasted master slides drifting out of brand; "
    "(12) accessibility retrofitting after the fact"
)

CHART_NO_DATA_HTML = """<section class="slide">
  <p class="eyebrow">Responsive design</p>
  <h2 class="slide-title">HTML slides adapt to every screen — PowerPoint doesn't</h2>
  <p class="slide-subtitle">One file reflows to fit a laptop, tablet, phone, or projector</p>
  <div class="content">
    <ul class="bullets">
      <li><strong>Fluid layout:</strong> HTML reflows text, charts, and images to fit any viewport — laptop, tablet, phone, or projector</li>
      <li><strong>Fixed canvas trap:</strong> PowerPoint locks every element to one fixed rectangle, cropping or stretching on non-standard screens</li>
      <li><strong>Zero manual work:</strong> no duplicate decks for different devices — one file renders everywhere</li>
    </ul>
    <div class="callout">HTML slides look right on every screen without manual resizing. A device-by-device comparison chart is left out until measured figures are available.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>3</span></div>
</section>
"""

CONDENSED_HTML = """<section class="slide">
  <p class="eyebrow">The Problem</p>
  <h2 class="slide-title">PowerPoint's 30-year-old format still constrains how we persuade and decide</h2>
  <p class="slide-subtitle">Twelve pain points, grouped into three themes</p>
  <div class="grid-3">
    <div class="card">
      <p><strong>Fonts and layout</strong></p>
      <ul class="bullets">
        <li>Fonts swap on other machines</li>
        <li>Missing fonts reflow text</li>
        <li>Layouts distort on projectors</li>
        <li>4:3 vs 16:9 re-crops</li>
      </ul>
    </div>
    <div class="card">
      <p><strong>File size</strong></p>
      <ul class="bullets">
        <li>Average deck is 8–15 MB</li>
        <li>Hits email size limits</li>
        <li>Large decks open slowly</li>
        <li>Masters drift off-brand</li>
      </ul>
    </div>
    <div class="card">
      <p><strong>Collaboration</strong></p>
      <ul class="bullets">
        <li>Version-control headaches</li>
        <li>Binaries can't be diffed</li>
        <li>Co-author merge conflicts</li>
        <li>Accessibility added late</li>
      </ul>
    </div>
  </div>
  <div class="callout">PowerPoint's legacy architecture imposes real limits on presentation quality.</div>
  <div class="slide-footer"><span>Meridian</span><span>1</span></div>
</section>
"""


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _payload(slide, resolved_data):
    return model_payload_for(AGENT, {
        "position": slide["position"],
        "slide_spec": slide,
        "assumes": slide["assumes"],
        "hands_off": slide["hands_off"],
        "resolved_data": resolved_data,
        "section_html": "",
        "section_css": case.meridian_section_css(),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_active": True,
    })


def _bad_slide(pos, filler_items=1):
    """Deliberately wrong: drops the hand-off, uses an off-palette colour, overflows the frame."""
    items = "".join(
        f'<li style="color:#E11D48">Filler point {i}: unrelated detail that goes on and on</li>'
        for i in range(filler_items)
    )
    return (
        '<section class="slide">\n  <h2 class="slide-title">Overview</h2>\n'
        f'  <ul class="bullets">{items}</ul>\n'
        '  <div style="height:900px"></div>\n</section>\n'
    )


def _gold_resolved_data():
    """The canonical gold ``resolved_data`` (a ``ResolvedData`` dump), copied fresh per case."""
    return copy.deepcopy(case.gold_deck_spec()["resolved_data"])


def _without_figures(rd):
    """Per-case mutation: the same gold resolved_data with every figure removed."""
    out = copy.deepcopy(rd)
    out["figures"] = []
    return out


def _write(cid, kind, fault, payload, reference, should_fail):
    d = CASES_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": {}, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate():
    slides = case.gold_deck_spec()["slides"]
    gold_rd = _gold_resolved_data()

    for cid, pos in (("gold_bullets", 1), ("gold_chart", 3), ("gold_stats", 9)):
        ref = {"position": pos, "html": case.gold_slide(pos), "scripts": case.gold_scripts(pos)}
        bad = {"position": pos, "html": _bad_slide(pos), "scripts": ""}
        _write(cid, "positive", "", _payload(slides[pos], gold_rd), ref, bad)

    # too_much_content: the position-1 brief demanding ~12 dense points.
    s1 = dict(slides[1])
    s1["content_brief"] = s1["content_brief"] + TOO_MUCH_BRIEF_EXTRA
    _write(
        "too_much_content", "mutation",
        "content_brief demands 12 dense points; a faithful build overflows the frame",
        _payload(s1, gold_rd),
        {"position": 1, "html": CONDENSED_HTML, "scripts": ""},
        {"position": 1, "html": _bad_slide(1, filler_items=14), "scripts": ""},
    )

    # chart_no_data: position-3 brief, resolved_data emptied.
    fab = case.gold_slide(3)
    _write(
        "chart_no_data", "mutation",
        "resolved_data.figures emptied; a chart would need invented numbers",
        _payload(slides[3], _without_figures(gold_rd)),
        {"position": 3, "html": CHART_NO_DATA_HTML, "scripts": ""},
        {"position": 3, "html": fab, "scripts": case.gold_scripts(3)},
    )


if __name__ == "__main__":
    generate()

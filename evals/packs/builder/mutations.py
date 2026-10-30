"""Generate the builder pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.deck_spec import DeckStyle
from src.services.agent_model_payload import model_payload_for

from evals.harness import case

AGENT = "builder"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"

#: The technical deck style the deck-style cases carry (a ``DeckStyle`` dump, Meridian tokens only).
DECK_STYLE_FIXTURE = case.EVALS_DIR / "fixtures" / "deck_style_technical.json"


def deck_style_fixture() -> dict:
    """The technical deck style as a payload carries it: ``DeckStyle.model_dump()``."""
    return DeckStyle.model_validate(json.loads(DECK_STYLE_FIXTURE.read_text())).model_dump()

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


# ---- deck-style cases: the slide is built from the technical deck style's pieces ----------------

CODE_POSITION = 2
CODE_BRIEF = (
    "Define what HTML slides are — presentations built with HTML, CSS, and JavaScript rendered in a "
    "browser — and show the few lines of HTML one slide is made of. Name leading frameworks (Reveal.js, "
    "Slidev, Marp, Impress.js). Feature the callout stat that 98% of devices have a modern browser, "
    "making every device a presentation engine"
)
CODE_LOOK = (
    "Two columns: the four frameworks as bullets on the left; on the right a dk-code listing of one "
    "slide's HTML source, its tags marked kw and its attribute value str, under a cm comment. The 98% "
    "callout runs full width beneath."
)
CODE_EXPECT = {"deck_style_classes": ["dk-code"]}

# The listing's lines; each piece is (token class or "", text). The reference marks them with the
# deck style's token spans; the should_fail paints the same text inline.
_CODE_LINES = [
    [("cm", "&lt;!-- one slide, plain text --&gt;")],
    [("kw", "&lt;section"), ("", " class="), ("str", '"slide"'), ("kw", "&gt;")],
    [("", "  "), ("kw", "&lt;h2&gt;"), ("", "Your browser is the projector"),
     ("kw", "&lt;/h2&gt;")],
    [("", "  "), ("kw", "&lt;p&gt;"), ("", "Rendered by any modern browser."),
     ("kw", "&lt;/p&gt;")],
    [("kw", "&lt;/section&gt;")],
]
# Off-palette inline paint, as a model ignoring the deck style writes it.
_PAINTED_CODE_STYLE = (
    "margin:0;padding:24px;border-radius:12px;background:#0B1220;color:#E5E7EB;"
    "font-family:monospace;font-size:15px;line-height:1.6;white-space:pre-wrap;"
)
_PAINTED_TOKENS = {"kw": "#93C5FD", "fn": "#F0ABFC", "str": "#FDE68A", "cm": "#9CA3AF"}


def _listing(lines, *, painted=False, pre_style=_PAINTED_CODE_STYLE, tokens=_PAINTED_TOKENS):
    """A ``<pre>`` code listing: the deck style's ``dk-code`` with token spans, or (``painted``) the
    same text painted inline (``pre_style`` on the block, ``tokens`` colours on its spans) with no
    deck-style class. The build_reviewer pack plants its own colours through the same helper."""
    def piece(cls, text):
        if not cls:
            return text
        if painted:
            return f'<span style="color:{tokens[cls]}">{text}</span>'
        return f'<span class="{cls}">{text}</span>'

    body = "\n".join("".join(piece(cls, text) for cls, text in line) for line in lines)
    opening = f'<pre style="{pre_style}">' if painted else '<pre class="dk-code">'
    return f"{opening}{body}</pre>"


def _code_slide(listing):
    return f"""<section class="slide">
  <p class="eyebrow">The Modern Alternative</p>
  <h2 class="slide-title">Your browser is already a presentation engine</h2>
  <p class="slide-subtitle">An HTML slide is a few lines of HTML, CSS, and JavaScript, rendered natively in any browser</p>
  <div class="content">
    <div class="grid-2">
      <ul class="bullets">
        <li><strong>Reveal.js</strong> — the most popular open-source framework, with transitions and plugins</li>
        <li><strong>Slidev</strong> — developer-friendly, Markdown-driven slides powered by Vue</li>
        <li><strong>Marp</strong> — turns Markdown into slide decks with a minimal workflow</li>
        <li><strong>Impress.js</strong> — CSS3 transforms for cinematic, spatial presentations</li>
      </ul>
      {listing}
    </div>
    <div class="callout"><strong>98%</strong> of devices worldwide run a modern browser, so every one of them is already a presentation engine.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>2</span></div>
</section>
"""


TABLE_POSITION = 3
TABLE_BRIEF = (
    "Show that HTML slides adapt fluidly to any screen size — laptop, tablet, phone, or "
    "conference-room projector — while PowerPoint locks content to a fixed canvas. Compare rendering "
    "fidelity by device for HTML slides and PowerPoint in a table, with short commentary on why"
)
TABLE_LOOK = (
    "Two columns: on the left a dk-table of rendering fidelity by device (device, HTML slides, "
    "PowerPoint) with a dk-note naming its source beneath; on the right three commentary bullets. "
    "The hand-off callout runs full width beneath."
)
TABLE_EXPECT = {"deck_style_classes": ["dk-table", "dk-note"]}
_TABLE_ROWS = [("Laptop", "100%", "95%"), ("Tablet", "100%", "60%"),
               ("Phone", "100%", "35%"), ("Projector", "100%", "70%")]


def _fidelity_table(*, painted=False):
    """The device-fidelity table and its source note: the deck style's ``dk-table`` and
    ``dk-note``, or (``painted``) the same text painted inline with off-palette colours."""
    if painted:
        table = '<table style="width:100%;border-collapse:collapse;font-size:18px;">'
        th = '<th style="padding:12px 24px;text-align:left;background:#1D4ED8;color:#FFFFFF;font-size:13px;">'
        td = '<td style="padding:12px 24px;border-bottom:1px solid #CBD5E1;color:#334155;">'
        note = '<p style="margin:0;font-size:13px;color:#64748B;">'
    else:
        table, th, td, note = '<table class="dk-table">', "<th>", "<td>", '<p class="dk-note">'
    head = "".join(f"{th}{h}</th>" for h in ("Device", "HTML slides", "PowerPoint (.pptx)"))
    rows = "\n".join(
        "          <tr>" + "".join(f"{td}{v}</td>" for v in row) + "</tr>" for row in _TABLE_ROWS)
    return f"""<div style="display:flex;flex-direction:column;gap:var(--space-sm);">
        {table}
          <thead><tr>{head}</tr></thead>
          <tbody>
{rows}
          </tbody>
        </table>
        {note}Rendering fidelity by device, from the deck's device comparison.</p>
      </div>"""


def _table_slide(table):
    return f"""<section class="slide">
  <p class="eyebrow">Responsive design</p>
  <h2 class="slide-title">HTML slides adapt to every screen — PowerPoint doesn't</h2>
  <div class="content">
    <div class="grid-2">
      {table}
      <ul class="bullets">
        <li><strong>Fluid layout:</strong> HTML reflows text, charts, and images to fit any viewport</li>
        <li><strong>Fixed canvas trap:</strong> PowerPoint locks every element to a 13.3 × 7.5″ rectangle</li>
        <li><strong>Zero manual work:</strong> one file renders on every device, with no duplicate decks</li>
      </ul>
    </div>
    <div class="callout">HTML slides look perfect on every screen without manual resizing.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>3</span></div>
</section>
"""


# ---- deck_style_icons (Addendum A): the look asks for icons, which only the brand-asset search ---
# supplies. Nothing the builder is given names an asset; the harness binds a fake search over the
# Meridian fake asset index, and the expect lists that index's handles (``brand_assets``).

#: The Meridian fake asset index the harness's fake ``search_brand_assets`` answers from.
ASSET_INDEX = case.MERIDIAN_DIR / "assets.json"


def brand_asset_handles() -> list[str]:
    """Every handle of the fake asset index, in the file's order: a brand-asset case's
    ``expect.brand_assets``."""
    return [row["handle"] for row in json.loads(ASSET_INDEX.read_text())]


def _icon_handle(filename: str) -> str:
    """The fake index's handle for the icon ``icons/<filename>``."""
    rows = json.loads(ASSET_INDEX.read_text())
    (row,) = [r for r in rows if r["kind"] == "icon" and r["filename"] == f"icons/{filename}"]
    return row["handle"]


def _icon(src: str) -> str:
    """A decorative brand icon beside its text: sized inline (layout only), its paint the asset's."""
    return f'<img src="{src}" alt="" style="width:40px;height:40px;flex:none;"/>'


ICONS_POSITION = 7
ICONS_BRIEF = (
    "Show that HTML slide source is plain text: it lives in Git, supports pull requests and diff "
    "reviews, and runs through CI/CD pipelines, each collaboration advantage led by a brand icon. "
    "Contrast typical file sizes in a small table, 8–15 MB .pptx vs. under 1 MB HTML deck. "
    "Distribution is a URL, not a 15 MB email attachment"
)
ICONS_LOOK = (
    "Two columns: on the left three collaboration advantages (version control, CI/CD pipelines, "
    "review before release), each led by a product icon from the brand library; on the right a "
    "dk-table of typical deck size by format with a dk-note naming its source beneath. The callout "
    "runs full width beneath."
)
ICONS_CLASSES = ["dk-table", "dk-note"]
# The advantages, each with the index icon that fits it (the reference) and the asset id a model
# that invents ids instead of searching would write (the should_fail).
_ADVANTAGES = [
    ("icon-integrations.svg", 101, "Version control:",
     "every change is tracked in Git and reviewed line by line in a pull request"),
    ("icon-automation.svg", 102, "CI/CD pipelines:",
     "lint, test and deploy on every merge, with no manual export step"),
    ("icon-security.svg", 103, "Reviewed before release:",
     "nothing reaches the audience until a teammate has approved the diff"),
]


def _icons_slide(srcs) -> str:
    """The collaboration slide with ``srcs`` as its three advantages' icons."""
    items = "\n".join(
        '        <li style="display:flex;align-items:center;gap:var(--space-sm);">'
        f"{_icon(src)}<span><strong>{label}</strong> {text}</span></li>"
        for src, (_, _, label, text) in zip(srcs, _ADVANTAGES)
    )
    return f"""<section class="slide">
  <p class="eyebrow">Collaboration &amp; Distribution</p>
  <h2 class="slide-title">HTML decks live in Git, ship as a URL, and weigh 10× less</h2>
  <div class="content">
    <div class="grid-2">
      <ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:var(--space-md);">
{items}
      </ul>
      <div style="display:flex;flex-direction:column;gap:var(--space-sm);justify-content:center;">
        <table class="dk-table">
          <thead><tr><th>Format</th><th>Typical size</th></tr></thead>
          <tbody>
            <tr><td>PowerPoint (.pptx)</td><td>8–15 MB</td></tr>
            <tr><td>HTML deck</td><td>&lt; 1 MB</td></tr>
          </tbody>
        </table>
        <p class="dk-note">Typical file sizes, from the deck's collaboration comparison.</p>
      </div>
    </div>
    <div class="callout">A URL replaces the 15 MB email attachment, and every edit is reviewable before it ships.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>7</span></div>
</section>
"""


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _payload(slide, resolved_data, deck_style=None):
    """The builder payload; ``deck_style`` (a ``DeckStyle`` dump) is added only when given, so a
    case on an old deck carries no ``deck_style`` key."""
    payload = {
        "position": slide["position"],
        "slide_spec": slide,
        "assumes": slide["assumes"],
        "hands_off": slide["hands_off"],
        "resolved_data": resolved_data,
        "section_html": "",
        "section_css": case.meridian_section_css(),
        "resolved_style": case.meridian_resolved_style(),
        "design_system_active": True,
    }
    if deck_style is not None:
        payload["deck_style"] = deck_style
    return model_payload_for(AGENT, payload)


def _styled_slide(slide, content_brief, look):
    """A gold slide spec re-briefed for the deck style: its place in the arc (purpose, assumes,
    hands_off) is unchanged; the brief may ask for a piece, and ``look`` says how it reads."""
    out = copy.deepcopy(slide)
    out["content_brief"] = content_brief
    out["look"] = look
    return out


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


def _write(out, cid, kind, fault, payload, reference, should_fail, expect=None):
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect if expect is not None else {},
        "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    slides = case.gold_deck_spec()["slides"]
    gold_rd = _gold_resolved_data()

    for cid, pos in (("gold_bullets", 1), ("gold_chart", 3), ("gold_stats", 9)):
        ref = {"position": pos, "html": case.gold_slide(pos), "scripts": case.gold_scripts(pos)}
        bad = {"position": pos, "html": _bad_slide(pos), "scripts": ""}
        _write(out, cid, "positive", "", _payload(slides[pos], gold_rd), ref, bad)

    # too_much_content: the position-1 brief demanding ~12 dense points.
    s1 = dict(slides[1])
    s1["content_brief"] = s1["content_brief"] + TOO_MUCH_BRIEF_EXTRA
    _write(
        out, "too_much_content", "mutation",
        "content_brief demands 12 dense points; a faithful build overflows the frame",
        _payload(s1, gold_rd),
        {"position": 1, "html": CONDENSED_HTML, "scripts": ""},
        {"position": 1, "html": _bad_slide(1, filler_items=14), "scripts": ""},
    )

    # chart_no_data: position-3 brief, resolved_data emptied.
    fab = case.gold_slide(3)
    _write(
        out, "chart_no_data", "mutation",
        "resolved_data.figures emptied; a chart would need invented numbers",
        _payload(slides[3], _without_figures(gold_rd)),
        {"position": 3, "html": CHART_NO_DATA_HTML, "scripts": ""},
        {"position": 3, "html": fab, "scripts": case.gold_scripts(3)},
    )

    # Deck-style cases: the payload carries the technical deck style and the slide spec a look.
    # The reference builds from the pieces; the should_fail paints the same slide inline instead.
    style = deck_style_fixture()
    for cid, pos, brief, look, expect, good, bad in (
        ("deck_style_code", CODE_POSITION, CODE_BRIEF, CODE_LOOK, CODE_EXPECT,
         _code_slide(_listing(_CODE_LINES)), _code_slide(_listing(_CODE_LINES, painted=True))),
        ("deck_style_table", TABLE_POSITION, TABLE_BRIEF, TABLE_LOOK, TABLE_EXPECT,
         _table_slide(_fidelity_table()), _table_slide(_fidelity_table(painted=True))),
    ):
        _write(
            out, cid, "positive", "",
            _payload(_styled_slide(slides[pos], brief, look), gold_rd, deck_style=style),
            {"position": pos, "html": good, "scripts": ""},
            {"position": pos, "html": bad, "scripts": ""},
            expect=expect,
        )

    # deck_style_icons: the reference places the index icons a search finds; the should_fail
    # places the same slide's icons under invented asset ids, as a model that never searched would.
    searched = [_icon_handle(name) for name, *_ in _ADVANTAGES]
    invented = ["{{ds-asset:%d}}" % n for _, n, *_ in _ADVANTAGES]
    _write(
        out, "deck_style_icons", "positive", "",
        _payload(_styled_slide(slides[ICONS_POSITION], ICONS_BRIEF, ICONS_LOOK), gold_rd,
                 deck_style=style),
        {"position": ICONS_POSITION, "html": _icons_slide(searched), "scripts": ""},
        {"position": ICONS_POSITION, "html": _icons_slide(invented), "scripts": ""},
        expect={"deck_style_classes": list(ICONS_CLASSES), "brand_assets": brand_asset_handles()},
    )


if __name__ == "__main__":
    generate()

"""Generate the build_reviewer pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import model_payload_for

from evals.harness import case
from evals.packs.builder import mutations as builder_pack

AGENT = "build_reviewer"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"

ROGUE_HEX = "#E11D48"
WRONG_PCT = "64%"

OLD_CALLOUT = (
    "PowerPoint's legacy architecture imposes real limits on presentation quality"
    " — the format, not the presenter, is the bottleneck."
)
NEW_CALLOUT = (
    "PowerPoint remains a perfectly capable format for modern presentations"
    " — any problems come down to how individual authors use it."
)

MESSAGES = {
    "broken_handoff": (
        "The callout concludes that PowerPoint is a capable format and problems are author error, "
        "which contradicts the brief's hand-off that PowerPoint's legacy architecture imposes "
        "real limits on presentation quality."
    ),
    "rogue_colour": (
        "The slide title is coloured #E11D48, which is not a Meridian palette token; "
        "it should use a var(--brand-core-*) colour."
    ),
    "overflow": (
        "The bullet list has around 40 extra items and runs past the bottom of the slide frame, "
        "so content overflows."
    ),
    "source_contradiction": (
        "The subtitle and callout state that 64% of devices run a modern browser, but resolved_data "
        "says 98% of devices worldwide run a modern browser."
    ),
}


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def _finding(criterion, position, message):
    crit = CRITERIA[criterion]
    return Finding(
        id=f"{criterion}:{position}:0",
        slide_index=position,
        category=crit.category,
        criterion=criterion,
        message=message,
        objective=crit.objective,
    ).model_dump(mode="json")


def _payload(position, html, scripts, *, look=None, deck_style=None):
    """The reviewer payload. A deck-style case gives the slide spec a ``look`` and adds the deck
    style (a ``DeckStyle`` dump); every other case carries neither."""
    deck = case.gold_deck_spec()
    return _review_payload(deck, position, html, scripts, look=look, deck_style=deck_style)


def _review_payload(deck, position, html, scripts, *, look=None, deck_style=None):
    slide_spec = copy.deepcopy(deck["slides"][position])
    if look is not None:
        slide_spec["look"] = look
    payload = {
        "position": position,
        "slide_spec": slide_spec,
        "resolved_style": case.meridian_resolved_style(),
        "section_css": case.meridian_section_css(),
        "resolved_data": copy.deepcopy(deck["resolved_data"]),
        "html": html,
        "scripts": scripts,
    }
    if deck_style is not None:
        payload["deck_style"] = deck_style
    return model_payload_for(AGENT, payload)


def _mutate_broken_handoff(html):
    assert OLD_CALLOUT in html
    return html.replace(OLD_CALLOUT, NEW_CALLOUT)


def _mutate_rogue_colour(html):
    old = '<h2 class="slide-title">'
    assert old in html
    return html.replace(old, f'<h2 class="slide-title" style="color:{ROGUE_HEX}">', 1)


def _mutate_overflow(html):
    extra = "".join(
        f"\n      <li><strong>Extra point {i}:</strong> additional supporting detail that keeps the list growing</li>"
        for i in range(1, 41)
    )
    old = "    </ul>"
    assert old in html
    return html.replace(old, extra + "\n" + old, 1)


def _mutate_source_contradiction(html):
    assert "98%" in html
    return html.replace("98%", WRONG_PCT)


def _write(out, cid, kind, fault, expect, payload, reference, should_fail):
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def _out(position, verdict, findings):
    return {"slide_index": position, "verdict": verdict, "findings": findings}


# ---- deck-style cases ---------------------------------------------------------------------------
# The payload carries the technical deck style. deck_style_clean builds its code block from the
# pieces (dk-code and its token spans); deck_style_inline_paint is the same slide with that block
# painted inline instead, in colours outside the Meridian tokens, so today's rogue_colour
# description catches it (R10). Nothing else differs: the visible text and scripts are identical.
DECK_STYLE_SLIDE = 7  # slide source is plain text in Git: where a code listing belongs
DECK_STYLE_LOOK = (
    "Two columns: four collaboration bullets on the left; on the right a dk-code listing of the git "
    "commands that review and ship a slide change. The file-size callout runs full width beneath."
)
INLINE_PAINT_GROUND = "#1E293B"
INLINE_PAINT_TEXT = "#F8FAFC"
INLINE_PAINT_TOKENS = {"kw": "#7DD3FC", "fn": "#C4B5FD", "str": "#FCD34D", "cm": "#94A3B8"}
INLINE_PAINT_STYLE = (
    "margin:0;padding:var(--space-md);border-radius:var(--radius-md);"
    f"background:{INLINE_PAINT_GROUND};color:{INLINE_PAINT_TEXT};"
    "font-family:ui-monospace, Menlo, monospace;font-size:16px;line-height:1.6;white-space:pre-wrap;"
)
DECK_STYLE_CODE_LINES = [
    [("cm", "# a slide change is reviewed like code")],
    [("kw", "git"), ("", " "), ("fn", "switch"), ("", " -c "), ("str", "retitle-slide-7")],
    [("kw", "git"), ("", " "), ("fn", "diff"), ("", " main -- slides/07.html")],
    [("kw", "git"), ("", " "), ("fn", "push"), ("", " origin "), ("str", "retitle-slide-7")],
]


def inline_paint_message(lines):
    """The reference finding for a code block painted inline: it names exactly the planted colours
    (the ground, the text and the colour of each token class the listing ``lines`` uses)."""
    used = {cls for line in lines for cls, _ in line if cls}
    token_hexes = ", ".join(INLINE_PAINT_TOKENS[k] for k in ("kw", "fn", "str", "cm") if k in used)
    return (
        f"The code block is painted inline, {INLINE_PAINT_GROUND} behind {INLINE_PAINT_TEXT} text "
        f"with {token_hexes} on its tokens, instead of using the deck style's dk-code class. None of "
        "these is a Meridian palette token; the block should use dk-code, whose colours are "
        "var(--brand-*) tokens."
    )


DECK_STYLE_CLEAN_SHOULD_FAIL = (
    "The code block's background and syntax colours are not Meridian palette tokens; it should use "
    "var(--brand-core-*) colours."
)


def _git_slide(listing):
    return f"""<section class="slide">
  <p class="eyebrow">Collaboration &amp; Distribution</p>
  <h2 class="slide-title">HTML decks live in Git, ship as a URL, and weigh 10× less</h2>
  <p class="slide-subtitle">Plain-text source unlocks every modern collaboration workflow</p>
  <div class="content">
    <div class="grid-2">
      <ul class="bullets">
        <li><strong>Version control:</strong> every change is tracked in Git with full history, branching, and blame</li>
        <li><strong>Pull requests &amp; diff reviews:</strong> teammates review exact line-level changes</li>
        <li><strong>CI/CD pipelines:</strong> lint, test, and auto-deploy on every merge</li>
        <li><strong>Distribution is a link:</strong> share a URL instead of attaching a 15 MB file</li>
      </ul>
      {listing}
    </div>
    <div class="callout">An 8–15 MB .pptx becomes an HTML deck under 1 MB: a URL replaces the email attachment, and every edit is reviewable before it ships.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>7</span></div>
</section>
"""


def _write_deck_style_cases(out, payload_for, position, slide, lines):
    """Write ``deck_style_clean`` and ``deck_style_inline_paint`` for one slide template and listing.

    ``payload_for(html)`` builds the case payload (deck style and look included). The clean case's
    should_fail invents an objective rogue_colour against the deck style's own token colours; the
    inline-paint case's should_fail misses the planted rogue_colour.
    """
    clean = slide(builder_pack._listing(lines))
    painted = slide(builder_pack._listing(
        lines, painted=True, pre_style=INLINE_PAINT_STYLE, tokens=INLINE_PAINT_TOKENS))
    _write(
        out, "deck_style_clean", "positive", "", {"criteria": [], "positions": []},
        payload_for(clean),
        _out(position, "clean", []),
        _out(position, "surfaced",
             [_finding("rogue_colour", position, DECK_STYLE_CLEAN_SHOULD_FAIL)]),
    )
    _write(
        out, "deck_style_inline_paint", "mutation",
        f"code block painted inline ({INLINE_PAINT_GROUND} ground, off the Meridian palette) "
        "instead of using the deck style's dk-code",
        {"criteria": ["rogue_colour"], "positions": [position]},
        payload_for(painted),
        _out(position, "surfaced",
             [_finding("rogue_colour", position, inline_paint_message(lines))]),
        _out(position, "clean", []),
    )


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    # clean: the gold slide 1, nothing to flag; the wrong answer invents an overflow.
    html = case.gold_slide(1)
    _write(
        out, "clean", "positive", "", {"criteria": [], "positions": []},
        _payload(1, html, case.gold_scripts(1)),
        _out(1, "clean", []),
        _out(1, "surfaced", [_finding(
            "overflow", 1,
            "The bullet list overflows the bottom of the slide frame.")]),
    )

    mutations = [
        ("broken_handoff", "brief_not_delivered", 1, _mutate_broken_handoff,
         "callout's conclusion contradicts the brief's hand-off"),
        ("rogue_colour", "rogue_colour", 1, _mutate_rogue_colour,
         f"slide title recoloured {ROGUE_HEX}, off the Meridian palette"),
        ("overflow", "overflow", 1, _mutate_overflow,
         "~40 extra bullets appended so content overflows the frame"),
        ("source_contradiction", "source_contradiction", 3, _mutate_source_contradiction,
         f"every 98% in the slide changed to {WRONG_PCT}, contradicting resolved_data"),
    ]
    for cid, criterion, pos, mutate, fault in mutations:
        bad_html = mutate(case.gold_slide(pos))
        _write(
            out, cid, "mutation", fault, {"criteria": [criterion], "positions": [pos]},
            _payload(pos, bad_html, case.gold_scripts(pos)),
            _out(pos, "surfaced", [_finding(criterion, pos, MESSAGES[cid])]),
            _out(pos, "clean", []),
        )

    style = builder_pack.deck_style_fixture()
    _write_deck_style_cases(
        out,
        lambda html: _payload(DECK_STYLE_SLIDE, html, case.gold_scripts(DECK_STYLE_SLIDE),
                              look=DECK_STYLE_LOOK, deck_style=style),
        DECK_STYLE_SLIDE, _git_slide, DECK_STYLE_CODE_LINES,
    )


if __name__ == "__main__":
    generate()

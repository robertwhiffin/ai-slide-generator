"""Generate the builder pack's HELD-OUT cases from the deck-2 gold fixtures. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import copy
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)

from evals.harness import case
from evals.packs.builder import mutations as m

AGENT = m.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"

TOO_MUCH_BRIEF_EXTRA = (
    ". Cover at least 12 distinct dense points, each with its own supporting detail: "
    "(1) the same query giving different answers on each run; (2) manual review of every output; "
    "(3) rework after each inconsistent response; (4) naive prompts burning extra tokens; "
    "(5) token waste scaling with every API call; (6) rising monthly inference bills; "
    "(7) 3-5 revision rounds before production quality; (8) engineering hours lost to trial and error; "
    "(9) no shared record of which prompt version works; (10) regressions when a model is upgraded; "
    "(11) each new use case restarting from scratch; (12) stakeholders losing trust in LLM features"
)

TOO_MUCH_HTML = """<section class="slide">
  <p class="eyebrow">The Problem</p>
  <h2 class="slide-title">Ad-hoc prompting silently drains budget, quality, and velocity</h2>
  <p class="slide-subtitle">Twelve costs, grouped into three themes</p>
  <div class="grid-3">
    <div class="card">
      <p><strong>Inconsistency</strong></p>
      <ul class="bullets">
        <li>Same query, different answers</li>
        <li>Every output needs review</li>
        <li>Rework after each miss</li>
        <li>Trust in features erodes</li>
      </ul>
    </div>
    <div class="card">
      <p><strong>Cost</strong></p>
      <ul class="bullets">
        <li>Naive prompts burn tokens</li>
        <li>Waste scales per API call</li>
        <li>Inference bills keep rising</li>
        <li>Upgrades cause regressions</li>
      </ul>
    </div>
    <div class="card">
      <p><strong>Velocity</strong></p>
      <ul class="bullets">
        <li>Many revision rounds</li>
        <li>Hours lost to trial and error</li>
        <li>No record of what works</li>
        <li>Each use case starts over</li>
      </ul>
    </div>
  </div>
  <div class="callout">Every unoptimised prompt is a recurring tax on spend, consistency, and time-to-value.</div>
  <div class="slide-footer"><span>Meridian</span><span>1</span></div>
</section>
"""

STAT_NO_DATA_BRIEF = (
    "Three-stat card slide showing token cost reduction, output consistency improvement, "
    "and typical iteration cycles to production quality"
)

STAT_NO_DATA_HTML = """<section class="slide">
  <p class="eyebrow">Impact</p>
  <h2 class="slide-title">Structured prompts help on cost, consistency, and convergence</h2>
  <p class="slide-subtitle">Measured figures are not yet available for this deck</p>
  <div class="grid-3" style="flex:1;align-items:stretch;margin-top:var(--space-md);">
    <div class="card" style="display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:var(--space-lg) var(--space-md);">
      <div class="stat-value">Lower</div>
      <div class="stat-label" style="margin-top:var(--space-sm);font-size:var(--fs-body);color:var(--brand-core-text);line-height:1.4;">Token cost per request <span style="display:block;margin-top:4px;font-size:var(--fs-caption);color:var(--brand-core-muted);">figure to be confirmed</span></div>
    </div>
    <div class="card" style="display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:var(--space-lg) var(--space-md);">
      <div class="stat-value" style="color:var(--brand-accents-violet);">Higher</div>
      <div class="stat-label" style="margin-top:var(--space-sm);font-size:var(--fs-body);color:var(--brand-core-text);line-height:1.4;">Output consistency <span style="display:block;margin-top:4px;font-size:var(--fs-caption);color:var(--brand-core-muted);">figure to be confirmed</span></div>
    </div>
    <div class="card" style="display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:var(--space-lg) var(--space-md);">
      <div class="stat-value" style="color:var(--brand-accents-sky);">Fewer</div>
      <div class="stat-label" style="margin-top:var(--space-sm);font-size:var(--fs-body);color:var(--brand-core-text);line-height:1.4;">Iteration cycles <span style="display:block;margin-top:4px;font-size:var(--fs-caption);color:var(--brand-core-muted);">to production-grade quality</span></div>
    </div>
  </div>
  <div class="callout" style="margin-top:auto;">Stat values are left qualitative until sourced figures are supplied.</div>
  <div class="slide-footer"><span>Meridian</span><span>3</span></div>
</section>
"""


# ---- deck-style cases: the slide is built from the technical deck style's pieces ----------------

CODE_POSITION = 2
CODE_BRIEF = (
    "Bullet slide covering the four key patterns — system-prompt framing, few-shot examples, "
    "chain-of-thought reasoning, and structured output formatting — with a short listing of a "
    "structured-output instruction and a callout on when to combine them"
)
CODE_LOOK = (
    "Two columns: the four patterns as bullets on the left; on the right a dk-code listing of a "
    "structured-output instruction, its instruction verb marked kw and its JSON keys and values str, "
    "under a cm comment. The when-to-combine callout runs full width beneath."
)
CODE_EXPECT = {"deck_style_classes": ["dk-code"]}
_CODE_LINES = [
    [("cm", "# structured output: the reply is data")],
    [("kw", "Answer"), ("", " in JSON only:")],
    [("", "{"), ("str", '"label"'), ("", ": "), ("str", '"refund"'), ("", " | "),
     ("str", '"other"'), ("", ",")],
    [("", " "), ("str", '"reason"'), ("", ": "), ("str", '"one sentence"'), ("", "}")],
]


def _code_slide(listing):
    return f"""<section class="slide">
  <p class="eyebrow">Prompt Design Patterns</p>
  <h2 class="slide-title">Four composable patterns cover the vast majority of prompt optimisation needs</h2>
  <div class="content">
    <div class="grid-2">
      <ul class="bullets">
        <li><strong>System-prompt framing</strong> — set the model's role, constraints, and tone up front</li>
        <li><strong>Few-shot examples</strong> — show input/output pairs so the model learns your format</li>
        <li><strong>Chain-of-thought reasoning</strong> — ask the model to think step by step</li>
        <li><strong>Structured output formatting</strong> — request JSON so replies parse without clean-up</li>
      </ul>
      {listing}
    </div>
    <div class="callout"><strong>When to combine:</strong> pair few-shot examples with chain-of-thought for up to 40% better output consistency, then layer patterns as needed.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>2</span></div>
</section>
"""


TABLE_POSITION = 3
TABLE_BRIEF = (
    "Table of the three gains from structured prompting — token cost reduction (30-50%), output "
    "consistency improvement (up to 40%), and typical iteration cycles to production quality "
    "(3-5 rounds) — each with what it is measured against"
)
TABLE_LOOK = (
    "A dk-table of the three gains (dimension, figure, measured against) fills the slide under the "
    "title; the hand-off callout runs beneath it."
)
TABLE_EXPECT = {"deck_style_classes": ["dk-table"]}
_TABLE_ROWS = [
    ("Token cost", "30–50% fewer tokens per request", "naive prompts"),
    ("Output consistency", "up to 40% gain", "few-shot + chain-of-thought vs. none"),
    ("Iteration", "3–5 revision rounds", "reaching production-grade quality"),
]


def _gains_table(*, painted=False):
    """The gains table: the deck style's ``dk-table``, or (``painted``) the same text painted
    inline with off-palette colours."""
    if painted:
        table = '<table style="width:100%;border-collapse:collapse;font-size:18px;">'
        th = '<th style="padding:12px 24px;text-align:left;background:#7C2D12;color:#FFF7ED;font-size:13px;">'
        td = '<td style="padding:12px 24px;border-bottom:1px solid #FED7AA;color:#431407;">'
    else:
        table, th, td = '<table class="dk-table">', "<th>", "<td>"
    head = "".join(f"{th}{h}</th>" for h in ("Dimension", "Gain", "Measured against"))
    rows = "\n".join(
        "        <tr>" + "".join(f"{td}{v}</td>" for v in row) + "</tr>" for row in _TABLE_ROWS)
    return f"""{table}
      <thead><tr>{head}</tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>"""


def _table_slide(table):
    return f"""<section class="slide">
  <p class="eyebrow">Impact</p>
  <h2 class="slide-title">Structured prompts cut costs, boost consistency, and converge fast</h2>
  <div class="content">
    {table}
    <div class="callout">The gains from structured prompting are large and well-documented.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>3</span></div>
</section>
"""


# ---- deck_style_icons (Addendum A, the train generator's shape on deck 2): the look asks for icons
# beside the checklist, which only the brand-asset search supplies.

ICONS_POSITION = 5
ICONS_BRIEF = (
    "A five-item prompt optimisation checklist (define task scope, choose patterns, write eval "
    "criteria, run test suite, document winning prompt), with three brand icons marking how the "
    "team measures, automates and safeguards the work, and a callout stating the call to action: "
    "adopt this checklist for every new LLM feature starting this sprint"
)
ICONS_LOOK = (
    "Two columns: the five steps as a dk-steps checklist on the left; on the right three brand "
    "icons from the design system's library, each beside a one-line caption (measure, automate, "
    "safeguard). The call-to-action callout runs full width beneath."
)
ICONS_CLASSES = ["dk-steps"]
_STEPS = [
    ("Define task scope", "input, output format and constraints"),
    ("Choose prompt patterns", "few-shot, chain-of-thought or structured"),
    ("Write eval criteria", "accuracy, consistency and token efficiency"),
    ("Run your test suite", "edge cases over 3–5 iteration cycles"),
    ("Document the winning prompt", "the prompt, its rationale and its eval results"),
]
# The captions, each with the index icon that fits it.
_PRACTICES = [
    ("icon-analytics.svg", "Measure every prompt change against the eval criteria"),
    ("icon-automation.svg", "Automate the test suite so it runs on every edit"),
    ("icon-security.svg", "Safeguard the winning prompt under review"),
]
# What a model that never searched draws instead of brand icons: a hand-made glyph.
_DRAWN_ICON = (
    '<svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true" style="flex:none;">'
    '<circle cx="20" cy="20" r="16" fill="none" stroke="currentColor" stroke-width="3"/></svg>'
)


def _checklist_slide(icons) -> str:
    """The checklist slide with ``icons`` (one ``<img>`` or glyph per practice) beside its
    captions."""
    steps = "\n".join(
        f"        <li><strong>{name}</strong>: {detail}</li>" for name, detail in _STEPS)
    practices = "\n".join(
        '        <div style="display:flex;align-items:center;gap:var(--space-sm);">'
        f"{icon}<span>{caption}</span></div>"
        for icon, (_, caption) in zip(icons, _PRACTICES)
    )
    return f"""<section class="slide">
  <p class="eyebrow">Action Plan</p>
  <h2 class="slide-title">Adopt this five-step checklist for every new LLM feature</h2>
  <div class="content">
    <div class="grid-2">
      <ol class="dk-steps">
{steps}
      </ol>
      <div style="display:flex;flex-direction:column;gap:var(--space-md);justify-content:center;">
{practices}
      </div>
    </div>
    <div class="callout"><strong>Start this sprint:</strong> apply the checklist to your next LLM feature, with no new tooling required.</div>
  </div>
  <div class="slide-footer"><span>Meridian</span><span>5</span></div>
</section>
"""


def _gold_rd():
    return copy.deepcopy(case.gold_deck_spec(DECK)["resolved_data"])


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    slides = case.gold_deck_spec(DECK)["slides"]
    rd = _gold_rd()

    for cid, pos in (("cover_slide", 0), ("bullets_problem", 1), ("stat_cards", 3)):
        ref = {"position": pos, "html": case.gold_slide(pos, DECK), "scripts": case.gold_scripts(pos, DECK)}
        bad = {"position": pos, "html": m._bad_slide(pos), "scripts": ""}
        m._write(out, cid, "positive", "", m._payload(slides[pos], rd), ref, bad)

    s1 = dict(slides[1])
    s1["content_brief"] = s1["content_brief"] + TOO_MUCH_BRIEF_EXTRA
    m._write(
        out, "too_much_content", "mutation",
        "content_brief demands 12 dense points; a faithful build overflows the frame",
        m._payload(s1, rd),
        {"position": 1, "html": TOO_MUCH_HTML, "scripts": ""},
        {"position": 1, "html": m._bad_slide(1, filler_items=14), "scripts": ""},
    )

    s3 = dict(slides[3])
    s3["content_brief"] = STAT_NO_DATA_BRIEF
    rd_empty = m._without_figures(rd)
    m._write(
        out, "stat_no_data", "mutation",
        "resolved_data.figures emptied and the brief stripped of numbers; stat cards would need invented figures",
        m._payload(s3, rd_empty),
        {"position": 3, "html": STAT_NO_DATA_HTML, "scripts": ""},
        {"position": 3, "html": case.gold_slide(3, DECK), "scripts": case.gold_scripts(3, DECK)},
    )

    # Deck-style cases (the train generator's shape, on deck 2): the payload carries the technical
    # deck style and the slide spec a look; the should_fail paints the same slide inline instead.
    style = m.deck_style_fixture()
    for cid, pos, brief, look, expect, good, bad in (
        ("deck_style_code", CODE_POSITION, CODE_BRIEF, CODE_LOOK, CODE_EXPECT,
         _code_slide(m._listing(_CODE_LINES)), _code_slide(m._listing(_CODE_LINES, painted=True))),
        ("deck_style_table", TABLE_POSITION, TABLE_BRIEF, TABLE_LOOK, TABLE_EXPECT,
         _table_slide(_gains_table()), _table_slide(_gains_table(painted=True))),
    ):
        m._write(
            out, cid, "positive", "",
            m._payload(m._styled_slide(slides[pos], brief, look), rd, deck_style=style),
            {"position": pos, "html": good, "scripts": ""},
            {"position": pos, "html": bad, "scripts": ""},
            expect=expect,
        )

    # deck_style_icons: the reference places the index icons a search finds; the should_fail
    # draws its own glyphs instead and places no brand asset.
    m._write(
        out, "deck_style_icons", "positive", "",
        m._payload(m._styled_slide(slides[ICONS_POSITION], ICONS_BRIEF, ICONS_LOOK), rd,
                   deck_style=style),
        {"position": ICONS_POSITION,
         "html": _checklist_slide([m._icon(m._icon_handle(name)) for name, _ in _PRACTICES]),
         "scripts": ""},
        {"position": ICONS_POSITION, "html": _checklist_slide([_DRAWN_ICON] * len(_PRACTICES)),
         "scripts": ""},
        expect={"deck_style_classes": list(ICONS_CLASSES), "brand_assets": m.brand_asset_handles()},
    )


if __name__ == "__main__":
    generate()

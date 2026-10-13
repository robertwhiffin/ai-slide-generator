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


if __name__ == "__main__":
    generate()

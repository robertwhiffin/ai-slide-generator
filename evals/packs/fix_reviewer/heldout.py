"""Generate the fix_reviewer pack's HELD-OUT cases from the deck-2 gold fixtures. Idempotent.

Reuses the train generator's helpers and the held-out fixer generator, so each case's
``original_html`` and ``finding`` cannot drift from the fixer twin. Every case is on position 5
(the "Action Plan" slide), per the held-out clean-case fairness ruling.
"""
import copy
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.services.agent_model_payload import model_payload_for

from evals.harness import case
from evals.packs.build_reviewer import mutations as br
from evals.packs.fix_reviewer import mutations as frm
from evals.packs.fixer import heldout as fxh
from evals.packs.fixer import mutations as fx

AGENT = frm.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"
POS = fxh.SLIDE  # position 5, "Action Plan"

ROGUE = br.ROGUE_HEX
PARTIAL_EXTRA_BULLETS = 12

OLD_BULLET = (
    '<li><strong style="color: var(--brand-core-ink);">Run your test suite</strong> — Validate against '
    "edge cases across 3–5 iteration cycles to reach production-grade quality</li>"
)
NEW_BULLET = (
    '<li><strong style="color: var(--brand-core-ink);">Run your test suite</strong> — Validate against '
    "edge cases in a single iteration cycle to reach production-grade quality</li>"
)

HONEST_SUMMARIES = {
    "overflow": fxh.SUMMARIES["overflow"],
    "contrast_failure": fxh.SUMMARIES["contrast_failure"],
}
# Reject-case summaries describe only the intended fix; they omit the collateral damage.
OVERFLOW_SUMMARY = HONEST_SUMMARIES["overflow"]

MESSAGES = {
    "fault_left_reject": (
        "The fix removed only some of the surplus bullets; the list still runs past the bottom "
        "of the slide frame, so the overflow is not fixed."
    ),
    "content_broken_reject": (
        "The overflow is gone, but the fix changed the claim in the 'Run your test suite' bullet: the "
        "original says to validate across 3–5 iteration cycles, the fixed slide now says a single "
        "iteration cycle is enough, so the checklist no longer delivers the slide's original advice."
    ),
    "restyle_reject": (
        f"The overflow is gone, but the fix recoloured the eyebrow and title with {ROGUE}, which is "
        "not a Meridian palette token; it should use var(--brand-core-*) colours."
    ),
}


def _payload(fixer_criterion, original_html, html, change_summary):
    deck = case.gold_deck_spec(DECK)
    return model_payload_for(AGENT, {
        "position": POS,
        "finding": fx._finding(fixer_criterion, POS, fxh.MESSAGES[fixer_criterion]),
        "change_summary": change_summary,
        "html": html,
        "scripts": case.gold_scripts(POS, DECK),
        "original_html": original_html,
        "original_scripts": case.gold_scripts(POS, DECK),
        "slide_spec": copy.deepcopy(deck["slides"][POS]),
        "resolved_style": case.meridian_resolved_style(),
        "section_css": case.meridian_section_css(),
    })


def _partial_overflow_fix(html):
    """Overflowing slide with most, but not all, of the surplus bullets removed."""
    extra = "".join(
        f"\n      <li><strong>Extra point {i}:</strong> additional supporting detail that keeps the list growing</li>"
        for i in range(1, PARTIAL_EXTRA_BULLETS + 1)
    )
    old = "    </ul>"
    assert html.count(old) == 1
    return html.replace(old, extra + "\n" + old, 1)


def _break_content(html):
    assert html.count(OLD_BULLET) == 1
    return html.replace(OLD_BULLET, NEW_BULLET)


def _restyle(html):
    out = html
    for old in ('<p class="eyebrow">', '<h2 class="slide-title">'):
        assert out.count(old) == 1
        out = out.replace(old, old[:-1] + f' style="color:{ROGUE}">', 1)
    return out


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    gold = case.gold_slide(POS, DECK)
    overflowing = br._mutate_overflow(gold)
    low_contrast = fxh._mutate_contrast(gold)

    accepts = [
        ("good_fix_accept", "overflow", overflowing,
         "overflow", "The bullet list still overflows the bottom of the slide frame."),
        ("good_contrast_fix_accept", "contrast_failure", low_contrast,
         "contrast_failure", "The callout text still has contrast well below 4.5:1."),
    ]
    for cid, fcrit, original, bad_crit, bad_msg in accepts:
        frm._write(
            out, cid, "positive", "", {"criteria": [], "positions": [], "verdict": "fixed"},
            _payload(fcrit, original, gold, HONEST_SUMMARIES[fcrit]),
            _out("fixed", []),
            _out("surfaced", [frm._finding(bad_crit, POS, bad_msg)]),
        )

    rejects = [
        ("fault_left_reject", "overflow", _partial_overflow_fix(gold),
         f"fix removed only part of the surplus; {PARTIAL_EXTRA_BULLETS} extra bullets remain and the slide still overflows"),
        ("content_broken_reject", "brief_not_delivered", _break_content(gold),
         "overflow fixed, but the test-suite bullet now says a single iteration cycle instead of 3–5 (vs original_html)"),
        ("restyle_reject", "rogue_colour", _restyle(gold),
         f"overflow fixed, but eyebrow and title recoloured {ROGUE}, off the Meridian palette"),
    ]
    for cid, crit, html, fault in rejects:
        frm._write(
            out, cid, "mutation", fault,
            {"criteria": [crit], "positions": [POS], "verdict": "surfaced"},
            _payload("overflow", overflowing, html, OVERFLOW_SUMMARY),
            _out("surfaced", [frm._finding(crit, POS, MESSAGES[cid])]),
            _out("fixed", []),
        )


def _out(verdict, findings):
    return {"slide_index": POS, "verdict": verdict, "findings": findings}


if __name__ == "__main__":
    generate()

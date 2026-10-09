"""Generate the fix_reviewer pack's cases from the Meridian gold deck. Idempotent.

The reviewer is shown a fixer's result: the slide BEFORE (original_html, the fixer-pack broken
slide) and AFTER (html), the finding the fixer was given, and the fixer's own change_summary.
"""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import model_payload_for

from evals.harness import case
from evals.packs.build_reviewer import mutations as br
from evals.packs.fixer import mutations as fx

AGENT = "fix_reviewer"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"
POS = 1

ROGUE = br.ROGUE_HEX
PARTIAL_EXTRA_BULLETS = 12

OLD_BULLET = (
    "<li><strong>Bloated file sizes:</strong> the average corporate .pptx weighs 8–15 MB; "
    "an equivalent HTML deck fits under 1 MB</li>"
)
NEW_BULLET = (
    "<li><strong>Bloated file sizes:</strong> the average corporate .pptx weighs under 1 MB; "
    "an equivalent HTML deck is several times larger</li>"
)

HONEST_SUMMARIES = {
    "overflow": "Removed the surplus bullets so the content fits inside the slide frame.",
    "contrast_failure": "Restored the callout to the surface background so its text meets 4.5:1 contrast.",
}
# Reject-case summaries describe only the intended fix; they omit the collateral damage.
OVERFLOW_SUMMARY = HONEST_SUMMARIES["overflow"]

MESSAGES = {
    "fault_left_reject": (
        "The fix removed only some of the surplus bullets; the list still runs past the bottom "
        "of the slide frame, so the overflow is not fixed."
    ),
    "content_broken_reject": (
        "The overflow is gone, but the fix rewrote the 'Bloated file sizes' bullet: it now says a "
        ".pptx weighs under 1 MB and an HTML deck is larger, reversing the original 8–15 MB versus "
        "under 1 MB claim, so the brief's point is no longer delivered."
    ),
    "restyle_reject": (
        f"The overflow is gone, but the fix recoloured the slide (title, bullets and callout) with "
        f"{ROGUE}, which is not a Meridian palette token; it should use var(--brand-core-*) colours."
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


def _payload(fixer_criterion, original_html, html, change_summary):
    deck = case.gold_deck_spec()
    return model_payload_for(AGENT, {
        "position": POS,
        "finding": _finding(fixer_criterion, POS, fx.MESSAGES[fixer_criterion]),
        "change_summary": change_summary,
        "html": html,
        "scripts": case.gold_scripts(POS),
        "original_html": original_html,
        "original_scripts": case.gold_scripts(POS),
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
    assert old in html
    return html.replace(old, extra + "\n" + old, 1)


def _break_content(html):
    assert OLD_BULLET in html
    return html.replace(OLD_BULLET, NEW_BULLET)


def _restyle(html):
    out = html
    for old, style in (
        ('<h2 class="slide-title">', f'color:{ROGUE}'),
        ('<ul class="bullets">', f'color:{ROGUE}'),
        ('<div class="callout">', f'background:{ROGUE};color:#FFFFFF'),
    ):
        assert old in out
        out = out.replace(old, old[:-1] + f' style="{style}">', 1)
    return out


def _out(verdict, findings):
    return {"slide_index": POS, "verdict": verdict, "findings": findings}


def _write(out, cid, kind, fault, expect, payload, reference, should_fail):
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    gold = case.gold_slide(POS)
    overflowing = br._mutate_overflow(gold)
    low_contrast = fx._mutate_contrast(gold)

    accepts = [
        ("good_fix_accept", "overflow", overflowing,
         "The overflow is fixed; the fix is minimal and nothing else changed.",
         "overflow", "The bullet list still overflows the bottom of the slide frame."),
        ("good_contrast_fix_accept", "contrast_failure", low_contrast,
         "The callout contrast is fixed; the fix is minimal and nothing else changed.",
         "contrast_failure", "The callout text still has contrast well below 4.5:1."),
    ]
    for cid, fcrit, original, _note, bad_crit, bad_msg in accepts:
        _write(
            out, cid, "positive", "", {"criteria": [], "positions": [], "verdict": "fixed"},
            _payload(fcrit, original, gold, HONEST_SUMMARIES[fcrit]),
            _out("fixed", []),
            _out("surfaced", [_finding(bad_crit, POS, bad_msg)]),
        )

    rejects = [
        ("fault_left_reject", "overflow", "overflow", _partial_overflow_fix(gold),
         f"fix removed only part of the surplus; {PARTIAL_EXTRA_BULLETS} extra bullets remain and the slide still overflows"),
        ("content_broken_reject", "brief_not_delivered", "overflow", _break_content(gold),
         "overflow fixed, but the file-size bullet's meaning was reversed vs original_html"),
        ("restyle_reject", "rogue_colour", "overflow", _restyle(gold),
         f"overflow fixed, but title, bullets and callout recoloured {ROGUE}, off the Meridian palette"),
    ]
    for cid, crit, fcrit, html, fault in rejects:
        _write(
            out, cid, "mutation", fault,
            {"criteria": [crit], "positions": [POS], "verdict": "surfaced"},
            _payload(fcrit, overflowing, html, OVERFLOW_SUMMARY),
            _out("surfaced", [_finding(crit, POS, MESSAGES[cid])]),
            _out("fixed", []),
        )


if __name__ == "__main__":
    generate()

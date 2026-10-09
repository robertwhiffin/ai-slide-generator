"""Generate the fixer pack's HELD-OUT cases from the deck-2 gold fixtures. Idempotent.

Reuses the train generator's helpers and the held-out build_reviewer mutators, so the broken slides
of the four shared faults cannot drift from the reviewer twin.
"""
import copy
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.services.agent_model_payload import model_payload_for

from evals.harness import case
from evals.packs.build_reviewer import heldout as br_heldout
from evals.packs.build_reviewer import mutations as br
from evals.packs.fixer import mutations as fx

AGENT = fx.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"
SLIDE = br_heldout.SLIDE  # position 5, "Action Plan"

# Gold 5's callout carries `margin-top: auto`, so the train exact-string edit does not match.
OLD_CALLOUT_OPEN = '<div class="callout" style="margin-top: auto;">'
BAD_CALLOUT_OPEN = (
    '<div class="callout" style="margin-top: auto; background: var(--brand-core-primary-dark); '
    'color: var(--brand-core-ink);">'
)

MESSAGES = {
    "rogue_colour": br_heldout.MESSAGES["rogue_colour"],
    "overflow": br_heldout.MESSAGES["overflow"],
    "contrast_failure": (
        "The callout text is dark ink on a dark teal (primary-dark) background, "
        "so its contrast is well below 4.5:1 and it is hard to read."
    ),
    "source_contradiction": (
        "The first stat card shows 10–15%, but the sourced figure is 30–50% fewer tokens per "
        "request versus naive prompts; change 10–15% back to 30–50%."
    ),
    "brief_not_delivered": br_heldout.MESSAGES["broken_handoff"],
}

SUMMARIES = {
    "rogue_colour": "Removed the off-palette #E11D48 title colour so the title uses the palette default.",
    "overflow": "Removed the surplus bullets so the content fits inside the slide frame.",
    "contrast_failure": "Restored the callout to its default surface background so its text meets 4.5:1 contrast.",
    "source_contradiction": "Corrected the first stat card from 10–15% back to the sourced 30–50%.",
    "brief_not_delivered": (
        "Restored the callout so it tells the team to start using the checklist this sprint "
        "with no new tooling required."
    ),
}


def _payload(criterion, position, html, scripts):
    deck = case.gold_deck_spec(DECK)
    return model_payload_for(AGENT, {
        "position": position,
        "finding": fx._finding(criterion, position, MESSAGES[criterion]),
        "html": html,
        "scripts": scripts,
        "slide_spec": copy.deepcopy(deck["slides"][position]),
        "resolved_style": case.meridian_resolved_style(),
        "section_css": case.meridian_section_css(),
        "resolved_data": copy.deepcopy(deck["resolved_data"]),
    })


def _mutate_contrast(html):
    assert html.count(OLD_CALLOUT_OPEN) == 1
    return html.replace(OLD_CALLOUT_OPEN, BAD_CALLOUT_OPEN, 1)


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    mutations = [
        ("rogue_colour", SLIDE, br_heldout._mutate_rogue_colour,
         f"slide title recoloured {br.ROGUE_HEX}, off the Meridian palette"),
        ("overflow", SLIDE, br._mutate_overflow,
         "~40 extra bullets appended so content overflows the frame"),
        ("contrast_failure", SLIDE, _mutate_contrast,
         "callout set to ink text on the primary-dark background, contrast below 4.5"),
        ("source_contradiction", 3, br_heldout._mutate_source_contradiction,
         "first stat card changed from 30–50% to 10–15%, contradicting resolved_data"),
        ("brief_not_delivered", SLIDE, br_heldout._mutate_broken_handoff,
         "callout says not to adopt the checklist yet as it needs dedicated tooling, contradicting the hand-off"),
    ]
    for cid, pos, mutate, fault in mutations:
        gold, scripts = case.gold_slide(pos, DECK), case.gold_scripts(pos, DECK)
        bad_html = mutate(gold)
        reference = {
            "position": pos, "html": gold, "scripts": scripts,
            "changed": True, "change_summary": SUMMARIES[cid],
        }
        should_fail = {
            "position": pos, "html": bad_html, "scripts": scripts,
            "changed": False, "change_summary": "No change needed.",
        }
        fx._write(out, cid, fault, _payload(cid, pos, bad_html, scripts), reference, should_fail)


if __name__ == "__main__":
    generate()

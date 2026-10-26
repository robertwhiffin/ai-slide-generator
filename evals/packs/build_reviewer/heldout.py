"""Generate the build_reviewer pack's HELD-OUT cases from the deck-2 gold fixtures. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import copy
import pathlib

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.services.agent_model_payload import model_payload_for

from evals.harness import case
from evals.packs.build_reviewer import mutations as m

AGENT = m.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"

# Position 5 ("Action Plan") hosts the clean case and the three slide-level mutations: its figures agree
# in direction with resolved_data. Position 1's "30–50% MORE tokens" bullet inverts the base of
# resolved_data's "30–50% fewer tokens", so a numerate reviewer could fairly raise an unplanted
# objective source_contradiction there.
SLIDE = 5
OLD_CALLOUT = (
    "<strong>Start this sprint:</strong> Apply this checklist to your next LLM feature — no new tooling"
    " required. Structured prompts cut token waste by 30–50% and boost output consistency by up to 40%."
)
NEW_CALLOUT = (
    "<strong>Not yet:</strong> Do not adopt this checklist this sprint — it first needs dedicated"
    " prompt-management tooling to be built before any team can use it."
)
OLD_STAT = '<div class="stat-value">30–50%</div>'
NEW_STAT = '<div class="stat-value">10–15%</div>'

MESSAGES = {
    "broken_handoff": (
        "The callout tells the team not to adopt the checklist this sprint because it first needs "
        "dedicated tooling, which contradicts the brief's hand-off to start using the checklist "
        "this sprint with no new tooling required."
    ),
    "rogue_colour": (
        "The slide title is coloured #E11D48, which is not a Meridian palette token; "
        "it should use a var(--brand-core-*) colour."
    ),
    "overflow": (
        "The bullet list has around 40 extra items and runs past the bottom of the slide frame, "
        "so the content overflows."
    ),
    "source_contradiction": (
        "The first stat card shows 10–15%, but resolved_data says 30–50% fewer tokens per request "
        "versus naive prompts, so the stat value contradicts the source figure."
    ),
}


def _payload(position, html, scripts):
    deck = case.gold_deck_spec(DECK)
    return model_payload_for(AGENT, {
        "position": position,
        "slide_spec": copy.deepcopy(deck["slides"][position]),
        "resolved_style": case.meridian_resolved_style(),
        "section_css": case.meridian_section_css(),
        "resolved_data": copy.deepcopy(deck["resolved_data"]),
        "html": html,
        "scripts": scripts,
    })


def _mutate_broken_handoff(html):
    assert html.count(OLD_CALLOUT) == 1
    return html.replace(OLD_CALLOUT, NEW_CALLOUT)


def _mutate_rogue_colour(html):
    old = '<h2 class="slide-title">'
    assert html.count(old) == 1
    return html.replace(old, f'<h2 class="slide-title" style="color:{m.ROGUE_HEX}">', 1)


def _mutate_source_contradiction(html):
    assert html.count(OLD_STAT) == 1
    return html.replace(OLD_STAT, NEW_STAT)


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    m._write(
        out, "clean", "positive", "", {"criteria": [], "positions": []},
        _payload(SLIDE, case.gold_slide(SLIDE, DECK), case.gold_scripts(SLIDE, DECK)),
        m._out(SLIDE, "clean", []),
        m._out(SLIDE, "surfaced", [m._finding(
            "overflow", SLIDE, "The bullet list overflows the bottom of the slide frame.")]),
    )

    mutations = [
        ("broken_handoff", "brief_not_delivered", SLIDE, _mutate_broken_handoff,
         "callout says not to adopt the checklist yet as it needs dedicated tooling, contradicting the hand-off"),
        ("rogue_colour", "rogue_colour", SLIDE, _mutate_rogue_colour,
         f"slide title recoloured {m.ROGUE_HEX}, off the Meridian palette"),
        ("overflow", "overflow", SLIDE, m._mutate_overflow,
         "~40 extra bullets appended so content overflows the frame"),
        ("source_contradiction", "source_contradiction", 3, _mutate_source_contradiction,
         "first stat card changed from 30–50% to 10–15%, contradicting resolved_data"),
    ]
    for cid, criterion, pos, mutate, fault in mutations:
        bad_html = mutate(case.gold_slide(pos, DECK))
        m._write(
            out, cid, "mutation", fault, {"criteria": [criterion], "positions": [pos]},
            _payload(pos, bad_html, case.gold_scripts(pos, DECK)),
            m._out(pos, "surfaced", [m._finding(criterion, pos, MESSAGES[cid])]),
            m._out(pos, "clean", []),
        )


if __name__ == "__main__":
    generate()

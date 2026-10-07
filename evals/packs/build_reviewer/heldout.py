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

OLD_CALLOUT = (
    "Every unoptimised prompt is a recurring tax — on spend, on consistency, and on time-to-value."
    " These costs compound with every new use case you ship."
)
NEW_CALLOUT = (
    "The costs of ad-hoc prompting are negligible and do not compound"
    " — there is no need to optimise prompts as new use cases ship."
)
OLD_STAT = '<div class="stat-value">30–50%</div>'
NEW_STAT = '<div class="stat-value">10–15%</div>'

MESSAGES = {
    "broken_handoff": (
        "The callout claims the costs of ad-hoc prompting are negligible and do not compound, "
        "which contradicts the brief's hand-off that ad-hoc prompting has real, measurable "
        "costs that compound over time."
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
    assert OLD_CALLOUT in html
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
        _payload(1, case.gold_slide(1, DECK), case.gold_scripts(1, DECK)),
        m._out(1, "clean", []),
        m._out(1, "surfaced", [m._finding(
            "overflow", 1, "The bullet list overflows the bottom of the slide frame.")]),
    )

    mutations = [
        ("broken_handoff", "brief_not_delivered", 1, _mutate_broken_handoff,
         "callout claims ad-hoc prompting costs are negligible, contradicting the brief's hand-off"),
        ("rogue_colour", "rogue_colour", 1, _mutate_rogue_colour,
         f"slide title recoloured {m.ROGUE_HEX}, off the Meridian palette"),
        ("overflow", "overflow", 1, m._mutate_overflow,
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

"""Generate the build_reviewer pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import model_payload_for

from evals.harness import case

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


def _payload(position, html, scripts):
    deck = case.gold_deck_spec()
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


def _write(cid, kind, fault, expect, payload, reference, should_fail):
    d = CASES_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def _out(position, verdict, findings):
    return {"slide_index": position, "verdict": verdict, "findings": findings}


def generate():
    # clean: the gold slide 1, nothing to flag; the wrong answer invents an overflow.
    html = case.gold_slide(1)
    _write(
        "clean", "positive", "", {"criteria": [], "positions": []},
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
            cid, "mutation", fault, {"criteria": [criterion], "positions": [pos]},
            _payload(pos, bad_html, case.gold_scripts(pos)),
            _out(pos, "surfaced", [_finding(criterion, pos, MESSAGES[cid])]),
            _out(pos, "clean", []),
        )


if __name__ == "__main__":
    generate()

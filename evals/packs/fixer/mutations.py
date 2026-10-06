"""Generate the fixer pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json
import pathlib

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import model_payload_for

from evals.harness import case
from evals.packs.build_reviewer import mutations as br

AGENT = "fixer"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"

OLD_CALLOUT_OPEN = '<div class="callout">'
BAD_CALLOUT_OPEN = (
    '<div class="callout" style="background:var(--brand-core-primary-dark);'
    'color:var(--brand-core-ink)">'
)

MESSAGES = {
    "rogue_colour": br.MESSAGES["rogue_colour"],
    "overflow": br.MESSAGES["overflow"],
    "contrast_failure": (
        "The callout text is dark ink on a dark teal (primary-dark) background, "
        "so its contrast is well below 4.5:1 and it is hard to read."
    ),
    "source_contradiction": (
        "The subtitle and callout state that 64% of devices run a modern browser, "
        "but the sourced figure is 98% of devices worldwide; change 64% to 98%."
    ),
    "brief_not_delivered": br.MESSAGES["broken_handoff"],
}

SUMMARIES = {
    "rogue_colour": "Removed the off-palette #E11D48 title colour so the title uses the palette default.",
    "overflow": "Removed the surplus bullets so the content fits inside the slide frame.",
    "contrast_failure": "Restored the callout to the surface background so its text meets 4.5:1 contrast.",
    "source_contradiction": "Corrected the figure from 64% back to the sourced 98%.",
    "brief_not_delivered": "Restored the callout so it delivers the brief's hand-off about PowerPoint's legacy limits.",
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


def _payload(criterion, position, html, scripts):
    deck = case.gold_deck_spec()
    return model_payload_for(AGENT, {
        "position": position,
        "finding": _finding(criterion, position, MESSAGES[criterion]),
        "html": html,
        "scripts": scripts,
        "slide_spec": copy.deepcopy(deck["slides"][position]),
        "resolved_style": case.meridian_resolved_style(),
        "section_css": case.meridian_section_css(),
    })


def _mutate_contrast(html):
    assert OLD_CALLOUT_OPEN in html
    return html.replace(OLD_CALLOUT_OPEN, BAD_CALLOUT_OPEN, 1)


def _write(out, cid, fault, payload, reference, should_fail):
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": "mutation", "fault": fault, "expect": {}, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR
    mutations = [
        ("rogue_colour", 1, br._mutate_rogue_colour,
         f"slide title recoloured {br.ROGUE_HEX}, off the Meridian palette"),
        ("overflow", 1, br._mutate_overflow,
         "~40 extra bullets appended so content overflows the frame"),
        ("contrast_failure", 1, _mutate_contrast,
         "callout set to ink text on the primary-dark background, contrast below 4.5"),
        ("source_contradiction", 3, br._mutate_source_contradiction,
         f"every 98% in the slide changed to {br.WRONG_PCT}, contradicting the sourced figure"),
        ("brief_not_delivered", 1, br._mutate_broken_handoff,
         "callout's conclusion contradicts the brief's hand-off"),
    ]
    for cid, pos, mutate, fault in mutations:
        gold, scripts = case.gold_slide(pos), case.gold_scripts(pos)
        bad_html = mutate(gold)
        reference = {
            "position": pos, "html": gold, "scripts": scripts,
            "changed": True, "change_summary": SUMMARIES[cid],
        }
        # Wrong answer: hands back the broken slide untouched.
        should_fail = {
            "position": pos, "html": bad_html, "scripts": scripts,
            "changed": False, "change_summary": "No change needed.",
        }
        _write(out, cid, fault, _payload(cid, pos, bad_html, scripts), reference, should_fail)


if __name__ == "__main__":
    generate()

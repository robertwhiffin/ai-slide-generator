"""Generate the deck_reviewer pack's HELD-OUT cases from the deck-2 gold fixtures. Idempotent.

Reuses the train generator's helpers; only deck-2 content lives here.
"""
import pathlib
import re

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import model_payload_for
from src.utils.graph_safety import spotlight_prior_slides

from evals.harness import case
from evals.packs.deck_reviewer import mutations as m

AGENT = m.AGENT
DECK = "heldout"
CASES_DIR = case.PACKS_DIR / AGENT / "cases_heldout"

MESSAGES = {
    "arc_gap_drop_workflow": (
        "The deck lacks a workflow or iteration section describing how teams should evaluate and refine "
        "their prompts, creating a gap in the narrative arc where the implementation process is missing."
    ),
    "missing_conclusion": (
        "The deck has no conclusion slide or call-to-action checklist, leaving the audience without "
        "concrete next steps or a checklist to adopt this sprint."
    ),
    "out_of_order": (
        "The slides \"A repeatable evaluate-and-iterate loop drives prompt quality\" and "
        "\"Structured prompts cut costs, boost consistency, and converge fast\" are out of order: "
        "the impact and results are presented before the workflow for achieving them, disrupting the "
        "narrative arc."
    ),
    "repetition": (
        "The \"Key Considerations\" slide repeats the bullet list from \"Ad-hoc prompting silently drains "
        "budget, quality, and velocity\" word for word, creating cross-slide repetition that weakens the narrative."
    ),
}


def _finding(criterion, message):
    """Create a deck-level finding (slide_index = -1)."""
    crit = CRITERIA[criterion]
    return Finding(
        id=f"{criterion}:-1:0",
        slide_index=-1,
        category=crit.category,
        criterion=criterion,
        message=message,
        objective=crit.objective,
    ).model_dump(mode="json")


def _payload(htmls):
    """Build a deck_reviewer payload from a list of slide HTMLs."""
    deck = case.gold_deck_spec(DECK)
    slides_str = spotlight_prior_slides(htmls, None)
    return model_payload_for(AGENT, {
        "narrative_arc": deck["narrative_arc"],
        "call_to_action": deck["call_to_action"],
        "slide_count": len(htmls),
        "slides": slides_str,
    })


def _out(findings):
    """Create a deck_reviewer reference output."""
    return {"findings": findings}


def _write(out, cid, kind, fault, expect, payload, reference, should_fail):
    d = out / cid
    d.mkdir(parents=True, exist_ok=True)
    import json
    import yaml
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    (d / "payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (d / "reference.json").write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n")
    (d / "calibration.json").write_text(json.dumps({"should_fail": should_fail}, indent=2, ensure_ascii=False) + "\n")


def generate(out_dir: pathlib.Path | None = None):
    """Write the cases into ``out_dir`` (default: the committed ``CASES_DIR``)."""
    out = pathlib.Path(out_dir) if out_dir is not None else CASES_DIR

    # clean: all 6 gold slides, no findings
    htmls_clean = [case.gold_slide(i, DECK) for i in range(6)]
    _write(
        out, "clean", "positive", "", {"criteria": [], "positions": []},
        _payload(htmls_clean),
        _out([]),
        _out([_finding("arc_gap", "The narrative arc has a gap.")]),
    )

    # arc_gap_drop_workflow: drop position 4 (workflow), should have 5 slides
    htmls_arc_gap = [case.gold_slide(i, DECK) for i in range(6) if i != 4]
    _write(
        out, "arc_gap_drop_workflow", "mutation",
        "slide 4 (workflow) dropped", {"criteria": ["arc_gap"], "positions": [-1]},
        _payload(htmls_arc_gap),
        _out([_finding("arc_gap", MESSAGES["arc_gap_drop_workflow"])]),
        _out([]),  # should_fail: no findings
    )

    # missing_conclusion: drop position 5 (action plan), should have 5 slides
    htmls_missing_conclusion = [case.gold_slide(i, DECK) for i in range(5)]
    _write(
        out, "missing_conclusion", "mutation",
        "slide 5 (action plan) dropped", {"criteria": ["missing_conclusion"], "positions": [-1]},
        _payload(htmls_missing_conclusion),
        _out([_finding("missing_conclusion", MESSAGES["missing_conclusion"])]),
        _out([]),  # should_fail: no findings
    )

    # out_of_order: swap positions 2 and 4, should have 6 slides
    htmls_out_of_order = [case.gold_slide(i, DECK) for i in range(6)]
    htmls_out_of_order[2], htmls_out_of_order[4] = htmls_out_of_order[4], htmls_out_of_order[2]
    _write(
        out, "out_of_order", "mutation",
        "slides 2 and 4 swapped", {"criteria": ["arc_gap"], "positions": [-1]},
        _payload(htmls_out_of_order),
        _out([_finding("arc_gap", MESSAGES["out_of_order"])]),
        _out([]),  # should_fail: no findings
    )

    # repetition: replace position 2 with a slide containing gold 1's bullets block
    # This creates a cross-slide repetition (the bullets block appears twice)
    gold_1 = case.gold_slide(1, DECK)

    # Extract the bullets block from gold 1
    bullets_block = re.search(r'<ul class="bullets">.*?</ul>', gold_1, re.S).group(0)

    # Create a new slide at position 2 with:
    # - A different eyebrow and title (not the gold position 2 title)
    # - The gold 1 bullets block (creating repetition)
    new_slide_2 = (
        '<section class="slide" data-source="meridian">'
        '<div class="eyebrow">Key Insights</div>'
        '<h2 class="slide-title">Key Considerations</h2>'
        + bullets_block +
        '</section>'
    )

    # Build the slide list: 0-1, new_2, 3-5
    htmls_repetition = (
        [case.gold_slide(i, DECK) for i in range(2)] +
        [new_slide_2] +
        [case.gold_slide(i, DECK) for i in range(3, 6)]
    )

    _write(
        out, "repetition", "mutation",
        "slide 2 replaced with a slide containing gold 1's bullet list",
        {"criteria": ["cross_slide_repetition"], "positions": [-1]},
        _payload(htmls_repetition),
        _out([_finding("cross_slide_repetition", MESSAGES["repetition"])]),
        _out([]),  # should_fail: no findings
    )


if __name__ == "__main__":
    generate()

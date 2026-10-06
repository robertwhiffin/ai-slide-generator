"""Generate the deck_reviewer pack's cases from the Meridian gold deck. Idempotent."""
import copy
import json
import re

import yaml

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from src.domain.finding import CRITERIA, Finding
from src.services.agent_model_payload import model_payload_for
from src.utils.graph_safety import spotlight_prior_slides

from evals.harness import case

AGENT = "deck_reviewer"
CASES_DIR = case.PACKS_DIR / AGENT / "cases"

MESSAGES = {
    "arc_gap_drop_objections": (
        "The deck drops the objections slide, creating a gap in the narrative arc "
        "where the audience's anticipated concerns are not addressed."
    ),
    "missing_conclusion": (
        "The deck has no conclusion or call-to-action slide, leaving the audience "
        "without a clear verdict or next steps."
    ),
    "out_of_order": (
        "Slides 2 and 7 are out of order, disrupting the narrative arc and confusing "
        "the presentation flow."
    ),
    "repetition": (
        "Slide 5 repeats a key point from slide 7, using the same bullet list. "
        "This redundancy weakens the narrative."
    ),
}


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


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
    deck = case.gold_deck_spec()
    slides_str = spotlight_prior_slides(htmls, None)
    return model_payload_for(AGENT, {
        "narrative_arc": deck["narrative_arc"],
        "call_to_action": deck["call_to_action"],
        "slide_count": len(htmls),
        "slides": slides_str,
    })


def _write(cid, kind, fault, expect, payload, reference, should_fail):
    d = CASES_DIR / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(yaml.safe_dump({
        "kind": kind, "fault": fault, "expect": expect, "design_system_active": True,
    }, sort_keys=False))
    _dump(d / "payload.json", payload)
    _dump(d / "reference.json", reference)
    _dump(d / "calibration.json", {"should_fail": should_fail})


def _out(findings):
    """Create a deck_reviewer reference output."""
    return {"findings": findings}


def generate():
    # clean: all 10 gold slides, no findings
    htmls_clean = [case.gold_slide(i) for i in range(10)]
    _write(
        "clean", "positive", "", {"criteria": [], "positions": []},
        _payload(htmls_clean),
        _out([]),
        _out([_finding("arc_gap", "The narrative arc has a gap.")]),
    )

    # arc_gap_drop_objections: drop position 8 (objections), should have 9 slides
    htmls_arc_gap = [case.gold_slide(i) for i in range(10) if i != 8]
    _write(
        "arc_gap_drop_objections", "mutation",
        "slide 8 (objections) dropped", {"criteria": ["arc_gap"], "positions": [-1]},
        _payload(htmls_arc_gap),
        _out([_finding("arc_gap", MESSAGES["arc_gap_drop_objections"])]),
        _out([]),  # should_fail: no findings
    )

    # missing_conclusion: drop position 9 (verdict/CTA), should have 9 slides
    htmls_missing_conclusion = [case.gold_slide(i) for i in range(9)]
    _write(
        "missing_conclusion", "mutation",
        "slide 9 (verdict) dropped", {"criteria": ["missing_conclusion"], "positions": [-1]},
        _payload(htmls_missing_conclusion),
        _out([_finding("missing_conclusion", MESSAGES["missing_conclusion"])]),
        _out([]),  # should_fail: no findings
    )

    # out_of_order: swap positions 2 and 7, should have 10 slides
    htmls_out_of_order = [case.gold_slide(i) for i in range(10)]
    htmls_out_of_order[2], htmls_out_of_order[7] = htmls_out_of_order[7], htmls_out_of_order[2]
    _write(
        "out_of_order", "mutation",
        "slides 2 and 7 swapped", {"criteria": ["arc_gap"], "positions": [-1]},
        _payload(htmls_out_of_order),
        _out([_finding("arc_gap", MESSAGES["out_of_order"])]),
        _out([]),  # should_fail: no findings
    )

    # repetition: replace position 5 with a slide containing gold 7's bullets block
    # This creates a cross-slide repetition (the bullets block appears twice)
    gold_5 = case.gold_slide(5)
    gold_7 = case.gold_slide(7)

    # Extract the bullets block from gold 7
    bullets_block = re.search(r'<ul class="bullets">.*?</ul>', gold_7, re.S).group(0)

    # Create a new slide at position 5 with:
    # - A different eyebrow and title (not "HTML slides are genuinely interactive")
    # - The gold 7 bullets block (creating repetition)
    new_slide_5 = (
        '<section class="slide" data-source="meridian">'
        '<div class="eyebrow">Related Point</div>'
        '<h2 class="slide-title">Key Considerations</h2>'
        + bullets_block +
        '</section>'
    )

    # Build the slide list: 0-4, new_5, 6-9
    htmls_repetition = (
        [case.gold_slide(i) for i in range(5)] +
        [new_slide_5] +
        [case.gold_slide(i) for i in range(6, 10)]
    )

    _write(
        "repetition", "mutation",
        "slide 5 replaced with a slide containing gold 7's bullet list",
        {"criteria": ["cross_slide_repetition"], "positions": [-1]},
        _payload(htmls_repetition),
        _out([_finding("cross_slide_repetition", MESSAGES["repetition"])]),
        _out([]),  # should_fail: no findings
    )


if __name__ == "__main__":
    generate()

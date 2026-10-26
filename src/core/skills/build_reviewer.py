"""Skill body for the build reviewer.

The criteria block is GENERATED from ``CRITERIA`` (src.domain.finding) so that the
prompt and the schema stay in step by construction.  Adding a criterion to the registry
automatically expands the reviewer's checklist without touching this file.
"""

from src.domain.finding import CRITERIA

TOOL_GRANTS: list[str] = []


def _criteria_stage() -> str:
    criteria_lines = "\n".join(
        f"  {name} ({crit.category}, {crit.level}, objective={crit.objective}): {crit.description}"
        for name, crit in CRITERIA.items()
    )
    return "CRITERIA:\n" + criteria_lines


#: Colours the bound template section ships are the design system's decision, not
#: findings.  Without it the reviewer flagged the template's own small coral labels
#: (~3.4:1) and the fixer turned them navy on every content slide (deck-parity
#: devloop, 2026-10-16).  Shipped in the v1 composite and in the v2 target alike.
BOUND_TEMPLATE_COLOURS: str = (
    "BOUND TEMPLATE COLOURS: when the payload carries a non-empty section_html, "
    "every colour that section_html itself ships, through its classes or its own "
    "inline styles and on the ground it ships them on, is the design system's "
    "decision. Do not report those as contrast_failure or rogue_colour. Judge "
    "contrast and colour only where the built slide departs from section_html: a "
    "colour the section does not ship, or shipped text moved onto a different "
    "ground."
)

BUILD_REVIEWER_AUTHORED_PREFIX: str = (
    "You are a build reviewer.  Inspect the built slide against every criterion "
    "below and return a SlideReviewOutput.  "
    "Judge colours, fonts and spacing by the computed cascade the slide renders "
    "with, not by the class names on its elements.  "
    "When the payload carries a non-empty section_html, compare the built HTML "
    "with section_html and with slide_spec.slide_type to decide whether the slide "
    "uses the bound layout section.  "
    "Never propose a replacement colour or layout in a finding message; state "
    "what is wrong and leave the remedy to the fixer."
    "\n\n" + BOUND_TEMPLATE_COLOURS
)
BUILD_REVIEWER_CRITERIA_STAGE: str = _criteria_stage()
BUILD_REVIEWER_V1_AUTHORED_SUFFIX: str = (
    "FINDING RULES:\n"
    "  - Use only the criterion names listed above\n"
    "  - Set criterion to the exact name from the list\n"
    "  - Set category to the value shown in parentheses\n"
    "  - Set objective to the boolean shown\n"
    "  - Set slide_index to the slide's position integer\n"
    "  - Write a concrete, specific message — not a restatement of the description\n\n"
    "VERDICT RULES:\n"
    "  clean    → no findings\n"
    "  surfaced → one or more findings are present\n"
    "  (never emit 'fixed' — that verdict belongs to the fix reviewer)\n\n"
    "Return a SlideReviewOutput with findings and verdict."
)
BUILD_REVIEWER_V2_AUTHORED_SUFFIX: str = BUILD_REVIEWER_V1_AUTHORED_SUFFIX.replace(
    "Use only the criterion names listed above",
    "Use only the criterion names in the protected CRITERIA stage below",
)
BUILD_REVIEWER_AUTHORED_INSTRUCTIONS: str = (
    BUILD_REVIEWER_AUTHORED_PREFIX + "\n\n" + BUILD_REVIEWER_V2_AUTHORED_SUFFIX
)


def build_instructions() -> str:
    """Generate a composite from the live prefix and ``CRITERIA``.

    This is not the shipped Graph Version 1 prompt; see ``INSTRUCTIONS``.
    """
    return (
        BUILD_REVIEWER_AUTHORED_PREFIX
        + "\n\n"
        + _criteria_stage()
        + "\n\n"
        + BUILD_REVIEWER_V1_AUTHORED_SUFFIX
    )


#: Graph Version 1 composite: the bootstrap default.  It must stay byte-identical
#: to the packaged v1 ``prompt_text`` and is the ``source_composite_prompt`` of the
#: v1→v2 transition: persisted v1 definitions only auto-upgrade on an exact match.
#: New criteria reach v2 through ``BUILD_REVIEWER_CRITERIA_STAGE``.
_V1_PREFIX: str = (
    "You are a build reviewer.  Inspect the built slide against every criterion "
    "below and return a SlideReviewOutput."
)
_V1_CRITERIA_STAGE: str = (
    "CRITERIA:\n"
    "  overflow (design, slide, objective=True): Slide content overflows the frame.  "
    "Judge against _SLIDE_FRAME_CONSTRAINTS numbers, never reviewer-invented numbers.\n"
    "  contrast_failure (design, slide, objective=True): Text/background contrast "
    "fails WCAG AA minimum.\n"
    "  rogue_colour (design, slide, objective=True): Colour is outside the resolved "
    "contract — compiled artifact tokens, or the resolved style on the legacy branch.\n"
    "  distorted_image (design, slide, objective=True): Image aspect ratio is distorted.\n"
    "  source_contradiction (content, slide, objective=True): A figure contradicts "
    "resolved_data.  Only assertable against resolved_data; a figure with no cited "
    "source is not this finding.\n"
    "  brief_not_delivered (content, slide, objective=False): The slide does not "
    "deliver what the brief asked for.  The one subjective slide criterion; exercises "
    "the drawer's actionable path with real data rather than only fixtures.\n"
    "  arc_gap (narrative, deck, objective=False): The narrative arc has a gap or "
    "unexplained jump.\n"
    "  cross_slide_repetition (narrative, deck, objective=False): The same point is "
    "made verbatim or near-verbatim on multiple slides.\n"
    "  missing_conclusion (narrative, deck, objective=False): The deck has no "
    "conclusion or call-to-action."
)
INSTRUCTIONS: str = (
    _V1_PREFIX
    + "\n\n"
    + BOUND_TEMPLATE_COLOURS
    + "\n\n"
    + _V1_CRITERIA_STAGE
    + "\n\n"
    + BUILD_REVIEWER_V1_AUTHORED_SUFFIX
)


#: Appended to the build reviewer's instructions **only** when the payload carries
#: a ``deck_brief`` — i.e. only on §4.6's deck-level re-review pass.  The normal
#: build path's prompt is byte-identical without it (``AgentRuntime`` decides).
#:
#: It exists because the two invocations ask genuinely different questions.  The
#: build review asks "is this slide well made?", which the criteria above already
#: cover.  The re-review asks "does this slide still serve the deck's brief, now
#: that the brief has changed?" — and nothing in the criteria block or in
#: ``slide_spec`` tells the reviewer what the brief IS, so without this and the
#: ``deck_brief`` payload key the pass could only ever return rendering findings
#: that no spec edit can cause.  It was shipped once in exactly that state: N
#: serial review calls that found nothing and reported "every slide still fits".
DECK_BRIEF_REVIEW: str = (
    "DECK-BRIEF RE-REVIEW — READ THIS BEFORE APPLYING THE CRITERIA ABOVE.\n"
    "This payload carries `deck_brief`: the deck's audience, purpose, argument, "
    "call_to_action and narrative_arc AS THEY ARE NOW, after a change to the "
    "deck's intent.  The slide's HTML was authored against the PREVIOUS brief.\n\n"
    "Your question on this invocation is therefore NOT whether the slide is well "
    "made.  It is whether the slide still SERVES this brief: whether it speaks to "
    "this audience, advances this argument, carries its share of this narrative "
    "arc, and leads towards this call to action.\n\n"
    "  - If it no longer does, return a `brief_not_delivered` finding and say "
    "CONCRETELY what no longer fits — name the audience or the argument it still "
    "assumes.\n"
    "  - If it still serves the brief, return no finding for that reason.  Do not "
    "invent one: a slide that still fits must survive this pass untouched, "
    "because rebuilding it would discard work a human may have edited by hand.\n\n"
    "Judge the slide against `deck_brief` and `slide_spec`, never against a brief "
    "you infer from the slide's own contents — the slide is the thing under "
    "suspicion, so it cannot also be the standard."
)

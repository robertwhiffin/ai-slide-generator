"""Skill body for the build reviewer.

The criteria block is GENERATED from ``CRITERIA`` (src.domain.finding) so that the
prompt and the schema stay in step by construction.  Adding a criterion to the registry
automatically expands the reviewer's checklist without touching this file.
"""

from src.domain.finding import CRITERIA

TOOL_GRANTS: list[str] = []


def build_instructions() -> str:
    """Generate the build_reviewer instructions from the live CRITERIA registry.

    Called once at module load time to produce INSTRUCTIONS, and available to tests
    that need to verify the generation is dynamic.  The falsifiable test: add a
    criterion to CRITERIA, call this function, and assert the new name appears in the
    result — a hand-written block would not include it.
    """
    criteria_lines = "\n".join(
        f"  {name} ({crit.category}, {crit.level}, "
        f"objective={crit.objective}): {crit.description}"
        for name, crit in CRITERIA.items()
    )
    return (
        "You are a build reviewer.  Inspect the built slide against every criterion "
        "below and return a SlideReviewOutput.\n\n"
        "CRITERIA:\n"
        f"{criteria_lines}\n\n"
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


INSTRUCTIONS: str = build_instructions()


#: Appended to the build reviewer's instructions **only** when the payload carries
#: a ``deck_brief`` — i.e. only on §4.6's deck-level re-review pass.  The normal
#: build path's prompt is byte-identical without it (``call_skill`` decides; see
#: ``_with_conditional_instructions``).
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

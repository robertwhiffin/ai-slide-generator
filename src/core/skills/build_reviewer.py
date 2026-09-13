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

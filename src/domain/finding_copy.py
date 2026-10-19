"""Plain-language copy for review findings (#316).

A reviewer's ``Finding.message`` is written for the fixer: concrete, specific and
technical (hex codes, sizes, contrast ratios).  A deck author needs one calm
sentence pair: what is wrong, and what happened to it.  That text is DERIVED here,
at read time, from fields every finding already carries (``criterion``, the
registry's ``objective``, ``status``) and NEVER from ``message``.

Deliberate, and pinned by tests:

* Nothing here is a ``Finding`` field.  ``Finding`` is nested in the reviewers'
  output schemas, whose digests (``_V1_DIGESTS`` / ``_V2_DIGESTS`` in
  src/services/agent_schema_registry.py) hash the JSON schema; a field, even an
  optional one no model fills, would move them.  Pinned by the schema-digest
  tests and by tests/unit/test_finding_conformance.py (PROJECTION_ONLY_FIELDS).
* Nothing here reaches a model.  ``CRITERIA`` is rendered into the build
  reviewer's prompt; this is a separate mapping so editing copy never edits a
  prompt.  Pinned by tests/unit/test_finding_copy.py.
* Derived, never stored, so findings persisted before this module existed render
  exactly like new ones.

The deck-advisory strings and REVIEWER_DETAILS_SEPARATOR are mirrored in
frontend/src/utils/findingText.ts, which parses the advisory to collapse its
details; tests/unit/test_finding_conformance.py pins the two copies equal.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, NamedTuple

from src.domain.finding import CRITERIA, Finding


class PlainIssue(NamedTuple):
    present: str
    past: str


PLAIN_ISSUES: Mapping[str, PlainIssue] = MappingProxyType(
    {
        "overflow": PlainIssue(
            "Some content runs past the edge of the slide.",
            "Some content ran past the edge of the slide.",
        ),
        "contrast_failure": PlainIssue(
            "Some text is hard to read against its background.",
            "Some text was hard to read against its background.",
        ),
        "rogue_colour": PlainIssue(
            "A colour on this slide is outside the deck's colour scheme.",
            "A colour on this slide was outside the deck's colour scheme.",
        ),
        "distorted_image": PlainIssue(
            "An image looks stretched or squashed.",
            "An image looked stretched or squashed.",
        ),
        "source_contradiction": PlainIssue(
            "A figure on this slide does not match the source data.",
            "A figure on this slide did not match the source data.",
        ),
        "brief_not_delivered": PlainIssue(
            "This slide may not cover everything planned for it.",
            "This slide did not cover everything planned for it.",
        ),
        "off_template_treatment": PlainIssue(
            "This slide's background or colours differ from its template.",
            "This slide's background or colours differed from its template.",
        ),
        "layout_binding_mismatch": PlainIssue(
            "This slide does not use the layout planned for it.",
            "This slide did not use the layout planned for it.",
        ),
        "arc_gap": PlainIssue(
            "The story has a gap or an unexplained jump between slides.",
            "The story had a gap or an unexplained jump between slides.",
        ),
        "cross_slide_repetition": PlainIssue(
            "The same point is made on more than one slide.",
            "The same point was made on more than one slide.",
        ),
        "missing_conclusion": PlainIssue(
            "The deck has no clear conclusion or call to action.",
            "The deck had no clear conclusion or call to action.",
        ),
    }
)

GENERIC_ISSUE = PlainIssue(
    "Something here may need a closer look.",
    "Something here needed a closer look.",
)

FIXED_AUTOMATICALLY = "This was fixed automatically."
ADDRESSED = "This has been addressed."
NOT_FIXED_AUTOMATICALLY = "This was not fixed automatically."
LEFT_FOR_JUDGEMENT = "This is a judgement call, so it was left for you to decide."

#: A deck-wide message cannot say "this slide": a non-deck criterion that reaches
#: the deck advisory gets this line instead.
DECK_GRAIN_ISSUE = "One of the slides may need a closer look."
DECK_ADVISORY_HEADER_PREFIX = "Deck review found "
DECK_ADVISORY_HEADER_SUFFIX = " to look at in how the deck reads as a whole:"
DECK_ADVISORY_CLOSING = (
    "None of these were changed automatically. "
    "Reply here if you'd like any of them addressed."
)
#: Splits a chat message's plain lead from the reviewer's technical text.  Shared
#: with the frontend's Apply/Discuss writer and the chat collapse.
REVIEWER_DETAILS_SEPARATOR = "\n\nReviewer's details:\n"


def plain_issue(criterion: str, *, fixed: bool = False) -> str:
    """One plain sentence naming what is (or was) wrong; generic for an unknown criterion."""
    issue = PLAIN_ISSUES.get(criterion, GENERIC_ISSUE)
    return issue.past if fixed else issue.present


def plain_status(*, objective: bool, fixed: bool) -> str:
    """One plain sentence saying what happened to the finding."""
    if fixed:
        return FIXED_AUTOMATICALLY if objective else ADDRESSED
    return NOT_FIXED_AUTOMATICALLY if objective else LEFT_FOR_JUDGEMENT


def plain_finding_issue(finding: Finding) -> str:
    """The issue sentence alone, tense by status (any status but "fixed" is open)."""
    return plain_issue(finding.criterion, fixed=finding.status == "fixed")


def plain_finding_message(finding: Finding) -> str:
    """The plain-language text the drawer shows for *finding*.

    Reads ``criterion`` and ``status`` only (never ``message``).  Objectivity is
    the registry's when the criterion is known, exactly as ``_stamp_findings``
    re-derives it; the stored value is used only for an unknown criterion.
    """
    fixed = finding.status == "fixed"
    registered = CRITERIA.get(finding.criterion)
    objective = registered.objective if registered is not None else bool(finding.objective)
    return f"{plain_finding_issue(finding)} {plain_status(objective=objective, fixed=fixed)}"


def deck_advisory_issue(criterion: str) -> str:
    """The deck advisory's line for *criterion*: its plain sentence if deck-level, else deck-grain."""
    registered = CRITERIA.get(criterion)
    if registered is not None and registered.level == "deck":
        return plain_issue(criterion)
    return DECK_GRAIN_ISSUE

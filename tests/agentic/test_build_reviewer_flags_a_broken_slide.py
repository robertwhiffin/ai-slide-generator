"""Layer 3: a deliberately-broken slide IS flagged by the build reviewer.

WHY THIS CRITERION IS LEGITIMATE HERE, HAVING BEEN ILLEGITIMATE ELSEWHERE
------------------------------------------------------------------------
This branch has already paid for the inverse of this test.  §4.6's deck-level
re-review shipped with fourteen green tests over a mechanism that could not work,
because every "failing" stub returned an ``overflow`` finding — a *rendering*
criterion that no edit to a deck's brief can ever cause.  The stubbed outcome was
one production could never reach on that path, so the tests measured their own
fixtures.

The diagnostic that catches it: **ask what real input would produce the outcome.**
Here the answer is concrete and common — a slide that puts a long list in a fixed
frame overflows it, and the product's own users hit it constantly (the "cut off" /
"massive long slide" symptom the frame constraints were written for).  So the
criterion is right for *this* path; the rule is that it was checked, not that it
was avoided.

THE NUMBERS COME FROM ONE PLACE
-------------------------------
``_SLIDE_FRAME_CONSTRAINTS`` is the single source of the frame size and the safe
area, imported under its private name (legal, and it modifies no file).  The
``overflow`` criterion in the registry instructs the reviewer to *"judge against
_SLIDE_FRAME_CONSTRAINTS numbers, never reviewer-invented numbers"* — so a fixture
carrying its own hard-coded 1280 or 720 would be inventing exactly the numbers the
criterion forbids, and would go stale silently the day the block changes.
:func:`tests.agentic.payloads.overflowing_slide_html` derives every dimension from
the parsed block.

``design_system_active=False`` is deliberate: that is what makes
``AgentRuntime`` append ``_SLIDE_FRAME_CONSTRAINTS`` to the prompt. A
reviewer that never received the numbers would be judged against numbers it was
never shown, which is unfair by construction.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, frame_constraint_numbers, invoke_agent
from tests.agentic.payloads import (
    build_reviewer_payload,
    overflowing_slide_html,
    slide_spec,
)

pytestmark = LAYER3_MARKS


def test_the_build_reviewer_flags_a_slide_that_does_not_fit_its_frame():
    """The reviewer must return a finding whose ``criterion`` is ``overflow``."""
    from src.domain.finding import CRITERIA

    frame = frame_constraint_numbers()
    html = overflowing_slide_html(frame)

    # The fixture is only worth asserting against if it is really broken: the row
    # stack is twice the frame height, so state that as a precondition rather than
    # trusting the builder function.
    assert str(frame["height"]) in html, (
        "the fixture does not declare the frame height, so nothing about it is "
        "anchored to _SLIDE_FRAME_CONSTRAINTS"
    )

    out = invoke_agent(
        "build_reviewer",
        build_reviewer_payload(
            position=0,
            html=html,
            spec=slide_spec(
                0,
                purpose="list the findings from the last review",
                content_brief="every open finding, one per row",
            ),
        ),
        False,
    )

    criteria = [f.criterion for f in out.findings]
    assert "overflow" in criteria, (
        "the build reviewer did not report `overflow` for a slide whose content "
        f"stack is about twice its {frame['height']}px frame and which does not "
        f"clip. Criteria reported: {criteria or '(none)'}; verdict {out.verdict!r}."
    )

    # Structure as well as outcome: the reported finding must be usable by the
    # nodes downstream.  `objective` is what routes a finding to the fixer, and
    # build_reviewer_node re-derives it from CRITERIA precisely because a model
    # returning the wrong value would silently disable the fix path.
    overflow = next(f for f in out.findings if f.criterion == "overflow")
    assert overflow.slide_index == 0, (
        f"the finding names slide_index={overflow.slide_index}, but the payload's "
        "position was 0; a finding stamped against the wrong slide is attached to "
        "content nobody can see."
    )
    assert overflow.objective is CRITERIA["overflow"].objective, (
        f"the reviewer returned objective={overflow.objective} for `overflow`, but "
        f"the registry says {CRITERIA['overflow'].objective}. Left unchecked this "
        "is how the fix path gets disabled without anything going red."
    )
    assert out.verdict == "surfaced", (
        f"verdict is {out.verdict!r} while findings are present. The reviewer's own "
        "verdict rules make findings and `surfaced` the same event; `clean` with "
        "findings would make the drawer and the verdict disagree."
    )

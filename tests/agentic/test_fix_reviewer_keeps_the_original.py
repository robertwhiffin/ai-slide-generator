"""Layer 3: handed a WORSE "fix", the fix reviewer keeps the original.

WHAT "KEEPS THE ORIGINAL" ACTUALLY MEANS IN THE CODE
---------------------------------------------------
``fix_reviewer_node`` does not read the verdict to decide which HTML ships.  It
re-derives the decision from the findings::

    still_open = [f for f in re_findings if f.criterion == criterion]
    if not still_open:
        winner_html = fixed_html   # the candidate wins
        verdict = "fixed"
    else:
        ...                        # the ORIGINAL is what ships

So the field that governs whether a user keeps their reviewed slide is **whether
the reviewer re-reports the original criterion**, and the verdict is downstream of
it.  Asserting only ``verdict == "surfaced"`` would be a mixed shape/behaviour
check: it could pass because the reviewer noticed some *other* new problem while
silently accepting a candidate that never fixed the reported one.  Both are
asserted, with the ``still_open`` half named as the one that drives production.

THE CANDIDATE IS WORSE IN BOTH AVAILABLE DIRECTIONS
---------------------------------------------------
The fixture hands over a candidate that (a) leaves the reported low-contrast
caption exactly as it was, and (b) makes the title low-contrast too.  A reviewer
doing its job re-reports the original criterion.  Nothing about this is subtle or
adversarial — it is what a fixer that "fixed" the wrong element produces, and the
node's whole reason for existing is that this can happen.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, frame_constraint_numbers, invoke_agent
from tests.agentic.payloads import (
    fix_reviewer_payload,
    slide_spec,
    well_formed_slide_html,
)

pytestmark = LAYER3_MARKS


def test_the_fix_reviewer_re_reports_a_finding_the_candidate_did_not_fix():
    """The candidate left the reported fault in place and added another."""
    from src.domain.finding import Finding, make_finding_id

    frame = frame_constraint_numbers()

    finding = Finding(
        id=make_finding_id("contrast_failure", "layer3-fixture", 0),
        slide_index=0,
        category="design",
        criterion="contrast_failure",
        message=(
            "The source caption is #cccccc on a white background, which fails "
            "WCAG AA. Darken the caption text."
        ),
        objective=True,
    )

    # The candidate: caption untouched (the reported fault survives) and the title
    # dropped to the same failing grey (a new fault of the same criterion).
    candidate = well_formed_slide_html(
        frame, caption_colour="#cccccc", title_colour="#cccccc"
    )

    out = invoke_agent(
        "fix_reviewer",
        fix_reviewer_payload(
            position=0,
            html=candidate,
            finding=finding.model_dump(),
            change_summary="Adjusted the slide styling.",
            spec=slide_spec(
                0,
                purpose="show that adoption doubled",
                content_brief="the headline number with its source",
            ),
        ),
        False,
    )

    still_open = [f for f in out.findings if f.criterion == finding.criterion]
    assert still_open, (
        "the fix reviewer reported no `contrast_failure` for a candidate whose "
        "caption is still #cccccc on white — and whose title now is too. This is "
        "the field fix_reviewer_node branches on: with it empty the candidate "
        "WINS, the reviewed original is discarded and the row is written from the "
        "worse HTML.\n"
        f"criteria reported: {[f.criterion for f in out.findings] or '(none)'}; "
        f"verdict {out.verdict!r}"
    )
    assert out.verdict == "surfaced", (
        f"verdict is {out.verdict!r} while the reported finding is still open. The "
        "fix reviewer's own verdict rules reserve `fixed` for the case where the "
        "original finding was resolved; `fixed` here would tell a user their slide "
        "was corrected when the fault it was flagged for is still on the screen."
    )

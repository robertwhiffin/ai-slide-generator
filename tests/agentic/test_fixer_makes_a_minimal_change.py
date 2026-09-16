"""Layer 3: the fixer's diff is SMALL relative to the finding — it corrects, it does
not re-author.

THE BEHAVIOUR, AND WHY IT NEEDS A MODEL TO TEST
----------------------------------------------
``src/core/skills/fixer.py`` states the disposition in one line: *"DISPOSITION:
MINIMAL CHANGE. Correct only what the finding requires. … A builder authors; you
correct."*  Its own docstring records the reason: hand an authoring agent broken
HTML and it rewrites the slide, undoing work that already passed review and — once
WYSIWYG lands — a user's manual edits.

Nothing structural enforces that.  ``FixerOutput`` accepts any HTML at all, so a
complete rewrite validates exactly as cleanly as a one-token correction.  The only
way to know whether the disposition holds is to hand a real model one narrow
finding and measure what came back, which is why this is layer 3 and not a
contract test.

THE MEASURE, AND THE HONEST STATUS OF ITS THRESHOLD
---------------------------------------------------
``difflib.SequenceMatcher(...).ratio()`` over original and returned HTML: 1.0 is
byte-identical, 0.0 shares nothing.  The fixture isolates the fault to a single
colour value in a slide that is otherwise correct, so the *available* minimal
correction preserves nearly everything.

:data:`_MINIMUM_PRESERVED` is deliberately generous, and it is a **recorded
hypothesis, not a measurement** — this layer has never run against authored
prompts, so nobody has calibrated it.  It is set where only a re-author can fail:
a one-value correction lands near 0.99, while re-authoring the slide from the
brief shares little more than the tag vocabulary.  Calibrate it on the first real
run; do not lower it to make a run pass, which would convert this into a test that
cannot fail.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from tests.agentic.gates import LAYER3_MARKS, frame_constraint_numbers
from tests.agentic.payloads import fixer_payload, slide_spec, well_formed_slide_html

pytestmark = LAYER3_MARKS

#: Fraction of the original HTML a minimal correction must preserve.  See the
#: module docstring: a hypothesis to calibrate, never to lower.
_MINIMUM_PRESERVED = 0.6


def test_the_fixer_corrects_one_colour_without_re_authoring_the_slide():
    """One narrow finding; the returned HTML must still be recognisably the same slide."""
    from src.core.skills import call_skill
    from src.domain.finding import Finding, make_finding_id

    frame = frame_constraint_numbers()
    original = well_formed_slide_html(frame, caption_colour="#cccccc")

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

    out = call_skill(
        "fixer",
        fixer_payload(
            position=0,
            html=original,
            finding=finding.model_dump(),
            spec=slide_spec(
                0,
                purpose="show that adoption doubled",
                content_brief="the headline number with its source",
            ),
        ),
        False,
    )

    assert out.changed is True, (
        "the fixer reported changed=False for an objective contrast finding with a "
        "one-value correction available. The fixer's own prose reserves "
        "changed=False for a finding that is not actionable or HTML it cannot "
        f"parse; change_summary was {out.change_summary!r}"
    )
    assert out.position == finding.slide_index, (
        f"the fixer returned position={out.position} for a finding on slide "
        f"{finding.slide_index}; the fix reviewer writes the row at the position the "
        "fixer names, so a wrong one lands the correction on another slide."
    )

    preserved = SequenceMatcher(None, original, out.html).ratio()
    assert preserved >= _MINIMUM_PRESERVED, (
        f"the fixer preserved {preserved:.2f} of the original HTML, below the "
        f"{_MINIMUM_PRESERVED} floor — that is a re-author, not a correction. The "
        "finding named one colour value on one element in a slide that was "
        "otherwise correct. Do NOT lower the floor to make this pass: the "
        "disposition being tested is the fixer's, and re-authoring discards work "
        "that already passed review, including a user's manual edits.\n"
        f"change_summary was {out.change_summary!r}"
    )

    # The paired direction. Preservation alone is satisfied by a fixer that returns
    # the input untouched — which is the other way to fail this behaviour, and it
    # would pass a ratio floor perfectly.
    assert out.html != original, (
        "the fixer returned the original HTML byte-for-byte while reporting "
        "changed=True. A ratio floor alone cannot tell a minimal correction from no "
        "correction at all; this is the half that can."
    )

"""Layer 3: the architect ASKS which slide rather than picking one — and this is RC10.

ONE TEST, TWO PLACES IT IS OWED
-------------------------------
This is both the first row of E3's behaviour table ("the architect asks rather
than picking when a reference is ambiguous") and **RC10** of the retired-regex
regression checklist.  They are the same behaviour, so they are the same test:
``test_the_architect_asks_which_slide_rather_than_choosing_one`` in this file.  The
retired-regex task references it; it does not write a second one.

RC10'S MEANING, READ OFF THE CODE RATHER THAN THE NAME
-----------------------------------------------------
``src/api/services/chat_service.py`` marks RC10 at nine sites; the sync path's is
the clearest statement of the rule::

    # RC10: Edit intent without clear target - ask for clarification
    if _is_edit and not _slide_refs and not _is_generation:
        ...
        "I'd like to help edit your slides. Could you please specify which slide? ..."

So the shipped bug fix is: an **edit** intent, against an existing multi-slide
deck, carrying **no slide reference**, must produce a *question* — never an edit
applied to a guessed slide, and never a rebuild of the deck.  The monolith
implements it with a regex ahead of the model.  On the graph path there is no
regex: the architect's own intent classification has to carry it, which is why
this rule is asserted through a real model and not in CI.

Pinning the monolith's regex would ship the regression green — the old mechanism
would pass while the new one had no coverage at all.  The monolith's own RC tests
(``tests/unit/test_slide_editing_robustness.py`` and friends) are not reused or
repointed here: they cannot see the graph.

THE ASSERTION, AND WHY IT IS NOT A WORDING CHECK
------------------------------------------------
Three outcomes, all structural:

* ``intent == "discuss"`` — the classification.  ``edit`` is what a guess looks
  like, and ``ArchitectOutput`` *requires* a non-empty ``target_positions`` for
  ``edit``, so a model that guesses must name a position it invented.
* ``target_positions == []`` — nothing was picked.  This is the one that makes the
  test about *asking* rather than about the label: an ``ArchitectOutput`` could
  carry ``discuss`` and still nominate a slide.
* the message contains ``?`` — it asked something.  A question mark is
  punctuation, not phrasing: no expected sentence appears anywhere in this file.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS
from tests.agentic.payloads import architect_payload, deck_spec_dict, slide_spec

pytestmark = LAYER3_MARKS


def test_the_architect_asks_which_slide_rather_than_choosing_one():
    """RC10 on the graph path: edit intent, no slide reference, four slides."""
    from src.core.skills import call_skill

    spec = deck_spec_dict(
        [
            slide_spec(0, purpose="open the argument", content_brief="the headline claim"),
            slide_spec(1, purpose="show the trend", content_brief="a line chart of adoption"),
            slide_spec(2, purpose="show the breakdown", content_brief="a bar chart by region"),
            slide_spec(3, purpose="close", content_brief="the call to action"),
        ],
        title="Adoption through the third quarter",
    )

    out = call_skill(
        "architect",
        architect_payload(
            # Edit intent, no slide reference, and TWO slides carry a chart — so
            # there is genuinely no single referent to infer.
            "make the chart bigger",
            current_deck_spec=spec,
            committed_slide_count=len(spec["slides"]),
        ),
        # False on purpose: the no-design-system path, which is also the path that
        # makes assemble_skill_prompt inject the frame constraints.
        False,
    )

    assert out.intent == "discuss", (
        f"the architect returned intent={out.intent!r} for an edit request with no "
        "slide reference against a four-slide deck. Two of those slides carry a "
        "chart, so any target it names is a guess. RC10 requires it to ask: "
        f"target_positions={out.target_positions}, message={out.message!r}"
    )
    assert out.target_positions == [], (
        f"the architect nominated {out.target_positions} without being told which "
        "slide. Choosing silently is the defect RC10 encodes — the monolith asks "
        "which slide instead (chat_service.py, the RC10 sites)."
    )
    assert "?" in out.message, (
        "the architect's reply contains no question mark, so it did not ask "
        "anything. Only the punctuation is asserted — no phrasing is required "
        f"here. Reply was: {out.message!r}"
    )
    assert out.deck_spec is None, (
        "the architect returned a deck_spec on an ambiguous edit request. RC10's "
        "twin guard in the monolith preserves the existing deck rather than "
        "replacing it; committing a spec here would rebuild every slide."
    )

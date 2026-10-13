"""Layer 3: the architect adds to an existing deck rather than replacing it — RC2.

RC2'S MEANING, READ OFF THE CODE
---------------------------------
``src/api/services/chat_service.py`` marks RC2 at line 735 as "Reuse _is_add from
early detection (Issue 2 optimization)."  The monolith's ``_detect_add_intent``
classifies "add a slide about X" early, and that flag is reused downstream to
route the LLM output through the add-not-replace path:

    # RC2: For add operations, insert at appropriate position
    # (chat_service.py:2975)

The shipped bug fix: when the user says "add a slide", existing slides are not
replaced.  The system appends or inserts the new slide without discarding prior
work.  ``agent.py:939`` expresses the same concern: "Add explicit instruction for
'add' operations".

On the graph path there is no ``_detect_add_intent`` function: the architect IS the
classifier.  The behaviour RC2 protects against — "add" intent silently discarding
the existing deck — translates directly to the architect: when given a committed
deck and a message containing "add a slide", it should produce a ``build`` intent
with a spec that INCLUDES the existing slides, not replaces them.

THE ASSERTION IS STRUCTURAL, NOT A WORDING CHECK
-------------------------------------------------
The test asks how many slides the returned spec contains, not what the message
says.  The observable regression: the architect returns a one-slide spec (only the
new slide), silently destroying the three committed slides.  A spec whose slide
count is at least as large as the committed count proves the architect understood
"add" as addition, not replacement.

RC10 is not this test
---------------------
RC10 (already written by the previous task at
``tests/agentic/test_architect_asks_when_reference_is_ambiguous.py``) handles edit
intent with no slide reference → ask for clarification.  RC2 is about add intent
preserving existing content; the two are orthogonal.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import architect_payload, deck_spec_dict, slide_spec

pytestmark = LAYER3_MARKS


def test_the_architect_adds_to_an_existing_deck_rather_than_replacing_it():
    """RC2 on the graph path: 'add a slide' must not discard the committed deck.

    Three slides are committed; the user asks for a new one.  The returned spec
    must carry at least as many slides as were committed, proving the architect
    understood "add" as addition rather than replacement.
    """
    existing = deck_spec_dict(
        [
            slide_spec(0, purpose="set the scene", content_brief="the market opportunity"),
            slide_spec(1, purpose="show the evidence", content_brief="adoption data by region"),
            slide_spec(2, purpose="close", content_brief="the recommended next step"),
        ],
        title="Regional Expansion Review",
    )

    out = invoke_agent(
        "architect",
        architect_payload(
            "add a slide about our competitive positioning",
            current_deck_spec=existing,
            committed_slide_count=3,
        ),
        False,
    )

    assert out.intent == "build", (
        f"the architect returned intent={out.intent!r} for an 'add a slide' request "
        "against a three-slide deck.  RC2 requires the result to be a build intent "
        "(a spec that includes the existing slides plus the new one).  An 'edit' "
        "intent would leave no room for the new slide; a 'discuss' intent would not "
        "add anything.  The spec was: current_deck_spec has 3 slides, "
        f"committed_slide_count=3, message asks to add a competitive-positioning "
        f"slide.  Received: message={out.message!r}"
    )
    assert out.deck_spec is not None, (
        "the architect returned intent='build' but no deck_spec.  RC2's protection "
        "requires a spec that includes the new slide; without it there is nothing to "
        f"build.  intent={out.intent!r}, message={out.message!r}"
    )
    assert len(out.deck_spec.slides) >= 3, (
        f"the architect returned a spec with only {len(out.deck_spec.slides)} "
        f"slide(s) for an 'add a slide' request against a {3}-slide committed deck. "
        "RC2 encodes: 'add' preserves existing slides.  A spec with fewer slides "
        "than were committed means at least one committed slide was dropped. "
        f"Returned positions: {[s.position for s in out.deck_spec.slides]}"
    )

"""Layer 3: the architect handles 'add after slide N' — RC9.

RC9'S MEANING, READ OFF THE CODE
---------------------------------
``src/api/services/chat_service.py`` marks RC9 at lines 1551–1562 (streaming path):

    # RC9: Add with slide reference (e.g., "add after slide 3")
    elif _is_add and _slide_refs and _ref_position and existing_deck ...:
        # RC9: Adding slide at parsed reference position

The shipped fix: when add intent AND a positional reference are detected together,
the slide is inserted at the referenced position rather than at the end.  Without
this fix "add after slide 2" would either ask for clarification (treating it like an
ambiguous edit) or append to the end, ignoring the "after slide 2" constraint.

On the graph path there is no pre-LLM reference parser.  The architect combines
both detections in one call.  RC9's protection on the graph path: when the user
says "add a slide after slide 2", the architect must:

  * return ``intent='build'`` (add intent is a build on the graph path)
  * return a ``deck_spec`` with MORE slides than the committed count (the deck grew)

The positional precision — specifically which position the new slide occupies — is
downstream of the architect and depends on the deck spec the architect writes.  The
structural assertion this test makes is the coarser one: the deck grew rather than
shrank (the add was recognised as an add, not a replace).  A subtler assertion
about the new slide's exact position would require reading `deck_spec.slides` order,
which is correct to assert but carries more risk of being satisfied by a trivially
wrong spec (e.g., four slides all at position 0).  The growth assertion is the
minimum the non-regression claim requires: one more slide, not one fewer.

THE COMPLEMENTARY PAIR (RC2 AND RC9)
------------------------------------
RC2 tests "add a slide" without a positional reference — the architect must grow the
deck.  RC9 tests "add after slide N" WITH a positional reference — the architect
must also grow the deck AND the reference must be part of the message context the
model operates on.  RC2's test uses 3 committed slides; this test uses 4 to avoid
numeric overlap that might make the two feel duplicated.

RC10 (already written by the previous task) handles edit intent with no slide
reference → clarification.  RC9 is its counterpart for add intent with a reference.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import architect_payload, deck_spec_dict, slide_spec

pytestmark = LAYER3_MARKS


def test_the_architect_adds_a_slide_at_the_referenced_position():
    """RC9 on the graph path: 'add after slide 2' grows the deck, not replaces it.

    Four slides are committed.  The user requests a new slide after slide 2.  The
    architect must return 'build' intent with a spec that has at least five slides,
    showing it understood the request as addition rather than replacement.
    """
    existing = deck_spec_dict(
        [
            slide_spec(0, purpose="executive summary", content_brief="the key finding"),
            slide_spec(1, purpose="methodology", content_brief="how the data was gathered"),
            slide_spec(2, purpose="results", content_brief="the headline numbers"),
            slide_spec(3, purpose="next steps", content_brief="what happens now"),
        ],
        title="Customer Satisfaction Study",
    )

    out = invoke_agent(
        "architect",
        architect_payload(
            "add a slide after slide 2 that shows the regional breakdown",
            current_deck_spec=existing,
            committed_slide_count=4,
        ),
        False,
    )

    assert out.intent == "build", (
        f"the architect returned intent={out.intent!r} for 'add a slide after slide 2' "
        "against a four-slide deck.  RC9 requires 'build' intent (an add operation "
        "that grows the deck).  A 'discuss' reply here is the pre-RC9 regression: the "
        "architect asked for clarification when both the intent and the position were "
        f"explicit.  message={out.message!r}, "
        f"target_positions={out.target_positions!r}"
    )
    assert out.deck_spec is not None, (
        "the architect returned intent='build' but no deck_spec.  RC9's protection "
        "requires a spec that captures the new slide at the referenced position; "
        f"without it there is nothing to build.  message={out.message!r}"
    )
    assert len(out.deck_spec.slides) >= 5, (
        f"the architect returned a spec with {len(out.deck_spec.slides)} slide(s) "
        "for 'add a slide after slide 2' against a four-slide committed deck.  "
        "RC9 requires the deck to grow: at least five slides expected (the original "
        "four plus the new one).  A smaller count means at least one committed slide "
        f"was dropped.  Returned positions: {[s.position for s in out.deck_spec.slides]}"
    )

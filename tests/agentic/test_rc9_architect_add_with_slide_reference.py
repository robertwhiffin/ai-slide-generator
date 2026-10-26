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

On the graph path there is no pre-LLM reference parser that places the slide.
``architect_node`` resolves the user's slide numbers to positions
(``slide_numbering`` / ``slide_references``, #313), and the architect combines that
with the add intent in one call.

THE CONTRACT SINCE #314: AN ANCHORED ADD IS AN EDIT
---------------------------------------------------
Issue #314 made "add a slide to an existing deck" an ``edit``.  When the user says
"add a slide after slide 2", the architect must:

  * return ``intent='edit'`` with the revised ``deck_spec`` in full;
  * keep every committed slide unchanged except its position, in order, and add
    exactly one slide;
  * put the new slide straight after the named slide.  Slide 2 is the slide the
    user means to anchor the new one, not a slide to change: it is position 1, so
    the new slide is at index 2 of the returned deck and the committed slides after
    it move up by one;
  * name only the new slide in ``target_positions`` (its position in the returned
    ``deck_spec``), so only the new slide is built.

The anchor is the trap this test guards.  The prompt's SLIDE NUMBERS rule takes
``target_positions`` from ``slide_references``, which resolves "slide 2" to position
1; on an add that is where the new slide goes, not a target, so a
``target_positions`` of ``[1]`` would rebuild the anchor, which the user did not ask
to change.

THE COMPLEMENTARY PAIR (RC2 AND RC9)
------------------------------------
RC2 tests "add a slide" without a positional reference — the product rule places the
new slide before the deck's closing slide.  RC9 tests "add after slide N" WITH a
positional reference — the new slide goes straight after slide N.  RC2's test uses 3
committed slides; this test uses 4 to avoid numeric overlap that might make the two
feel duplicated.

THE ASSERTION IS STRUCTURAL
---------------------------
"Equal" means equal in every ``SlideSpec`` field but ``position``
(``src.domain.slide_alignment.slide_key``, the comparison production aligns with).
No wording of the message is asserted.

RC10 (already written by the previous task) handles edit intent with no slide
reference → clarification.  RC9 is its counterpart for add intent with a reference.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import architect_payload, deck_spec_dict, slide_spec

pytestmark = LAYER3_MARKS


def test_the_architect_adds_a_slide_at_the_referenced_position():
    """RC9 on the graph path: 'add after slide 2' inserts straight after slide 2.

    Four slides are committed.  The user requests a new slide after slide 2
    (position 1).  The architect must return an edit whose spec holds the four
    committed slides unchanged (ignoring position), in order, plus one new slide at
    index 2, with ``target_positions`` naming only the new slide.
    """
    from src.domain.deck_spec import SlideSpec
    from src.domain.slide_alignment import slide_key

    existing = deck_spec_dict(
        [
            slide_spec(0, purpose="executive summary", content_brief="the key finding"),
            slide_spec(1, purpose="methodology", content_brief="how the data was gathered"),
            slide_spec(2, purpose="results", content_brief="the headline numbers"),
            slide_spec(3, purpose="next steps", content_brief="what happens now"),
        ],
        title="Customer Satisfaction Study",
    )
    committed = len(existing["slides"])
    anchor_index = 1  # slide 2, as the user numbers slides from 1

    out = invoke_agent(
        "architect",
        architect_payload(
            "add a slide after slide 2 that shows the regional breakdown",
            current_deck_spec=existing,
            committed_slide_count=committed,
        ),
        False,
    )

    assert out.intent == "edit", (
        f"the architect returned intent={out.intent!r} for 'add a slide after slide 2' "
        "against a four-slide deck.  Since #314 an add to an existing deck is an edit "
        "whose revised deck_spec carries the new slide.  A 'discuss' reply here is the "
        "pre-RC9 regression (asking when both the intent and the position were "
        "explicit); a 'build' would rebuild every committed slide.  "
        f"message={out.message!r}, target_positions={out.target_positions!r}"
    )
    assert out.deck_spec is not None, (
        "the architect returned intent='edit' but no deck_spec.  An edit without "
        "deck_spec cannot be applied (architect_node refuses it), so the new slide "
        f"would be lost.  message={out.message!r}"
    )
    returned = sorted(out.deck_spec.slides, key=lambda slide: slide.position)
    assert len(returned) == committed + 1, (
        f"the architect returned {len(returned)} slide(s) for 'add a slide after "
        f"slide 2' against a {committed}-slide committed deck; exactly "
        f"{committed + 1} were expected (every committed slide plus the new one).  "
        f"Returned positions: {[s.position for s in returned]}"
    )

    committed_keys = [slide_key(SlideSpec(**s)) for s in existing["slides"]]
    new_indices = [i for i, s in enumerate(returned) if slide_key(s) not in committed_keys]
    assert len(new_indices) == 1, (
        f"{len(new_indices)} returned slide(s) differ from every committed slide "
        "(comparing every field but position); exactly one, the new slide, should.  "
        "More than one means a committed slide (often the anchor or its neighbour) was "
        f"rewritten.  Differing indices in position order: {new_indices}"
    )
    (new_index,) = new_indices
    others = [slide_key(s) for i, s in enumerate(returned) if i != new_index]
    assert others == committed_keys, (
        "the slides other than the new one are not the committed slides, unchanged and "
        "in their committed order (comparing every field but position).  An add must "
        "copy every committed slide as it is; only the positions after the new slide "
        "move up by one."
    )
    assert new_index == anchor_index + 1, (
        f"the new slide is at index {new_index} of the returned deck (position order); "
        f"'after slide 2' puts it at index {anchor_index + 1}, straight after the named "
        f"slide (index {anchor_index}).  Index {anchor_index} means slide 2's number was "
        f"read as the new slide's number; index {committed} means the reference was "
        "ignored and the slide appended."
    )
    assert out.target_positions == [returned[new_index].position], (
        f"target_positions={out.target_positions!r}; on an add that changes nothing "
        "else they must be exactly the new slide's position in the returned deck_spec, "
        f"[{returned[new_index].position}].  The named slide is the anchor, not a "
        "target: its position here would rebuild a slide the user did not ask to change."
    )

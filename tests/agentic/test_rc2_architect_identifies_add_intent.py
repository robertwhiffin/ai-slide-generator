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
deck and a message containing "add a slide", it must keep every committed slide and
add exactly one.

THE CONTRACT SINCE #314: AN ADD IS AN EDIT
------------------------------------------
Issue #314 made "add a slide to an existing deck" an ``edit``: the architect returns
the revised ``deck_spec`` in full with the new ``SlideSpec`` at its position, every
committed slide copied unchanged except that the slides after the new one move up by
one, and ``target_positions`` naming only the new slide, so only the new slide is
built.  (Before #314 an add came back as a ``build``, which rebuilt every slide.)

This message states no place.  The product rule for that case (plan D6): the new
slide goes where it fits the argument, before a closing or call-to-action slide,
unless the new slide is itself a closing slide.  The committed deck ends in a "close"
slide and the new slide is not one, so it goes straight before that closing slide.

THE ASSERTION IS STRUCTURAL, NOT A WORDING CHECK
-------------------------------------------------
The test reads the returned spec's slides, not what the message says.  "Equal"
means equal in every ``SlideSpec`` field but ``position``
(``src.domain.slide_alignment.slide_key``, the comparison production aligns with).
The observable regressions: a one-slide spec (the committed slides destroyed), a
rewritten neighbour, the new slide appended after the close, or ``target_positions``
that would rebuild committed slides.

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
    """RC2 on the graph path: 'add a slide' is an edit that keeps the committed deck.

    Three slides are committed, the last a closing slide; the user asks for a new one
    and states no place.  The returned spec must hold the three committed slides
    unchanged (ignoring position), in order, plus one new slide straight before the
    closing slide, and ``target_positions`` must name only the new slide.
    """
    from src.domain.deck_spec import SlideSpec
    from src.domain.slide_alignment import slide_key

    existing = deck_spec_dict(
        [
            slide_spec(0, purpose="set the scene", content_brief="the market opportunity"),
            slide_spec(1, purpose="show the evidence", content_brief="adoption data by region"),
            slide_spec(2, purpose="close", content_brief="the recommended next step"),
        ],
        title="Regional Expansion Review",
    )
    committed = len(existing["slides"])
    closing_index = committed - 1  # the "close" slide, last in the committed deck

    out = invoke_agent(
        "architect",
        architect_payload(
            "add a slide about our competitive positioning",
            current_deck_spec=existing,
            committed_slide_count=committed,
        ),
        False,
    )

    assert out.intent == "edit", (
        f"the architect returned intent={out.intent!r} for an 'add a slide' request "
        "against a three-slide deck.  Since #314 adding a slide to an existing deck is "
        "an edit: the revised deck_spec carries the new slide, and target_positions "
        "names only it, so only the new slide is built.  A 'build' would rebuild every "
        "committed slide; a 'discuss' would add nothing.  "
        f"target_positions={out.target_positions!r}, message={out.message!r}"
    )
    assert out.deck_spec is not None, (
        "the architect returned intent='edit' but no deck_spec.  An edit without "
        "deck_spec cannot be applied (architect_node refuses it), so the new slide "
        f"would be lost.  message={out.message!r}"
    )
    returned = sorted(out.deck_spec.slides, key=lambda slide: slide.position)
    assert len(returned) == committed + 1, (
        f"the architect returned {len(returned)} slide(s) for one 'add a slide' "
        f"request against a {committed}-slide committed deck; exactly {committed + 1} "
        "were expected (every committed slide plus the new one).  Fewer means a "
        "committed slide was dropped; more means slides were invented.  "
        f"Returned positions: {[s.position for s in returned]}"
    )

    committed_keys = [slide_key(SlideSpec(**s)) for s in existing["slides"]]
    new_indices = [i for i, s in enumerate(returned) if slide_key(s) not in committed_keys]
    assert len(new_indices) == 1, (
        f"{len(new_indices)} returned slide(s) differ from every committed slide "
        "(comparing every field but position); exactly one, the new slide, should.  "
        "More than one means a committed slide was rewritten to fit the new one.  "
        f"Differing indices in position order: {new_indices}"
    )
    (new_index,) = new_indices
    others = [slide_key(s) for i, s in enumerate(returned) if i != new_index]
    assert others == committed_keys, (
        "the slides other than the new one are not the committed slides, unchanged and "
        "in their committed order (comparing every field but position).  An add must "
        "copy every committed slide as it is; only the positions after the new slide "
        "move up by one."
    )
    assert new_index == closing_index, (
        f"the new slide is at index {new_index} of the returned deck (position order); "
        f"the product rule puts it at index {closing_index}, straight before the "
        "closing slide, when the user gives no place and the new slide is not itself "
        "a closing slide.  Index "
        f"{committed} means it was appended after the close."
    )
    assert out.target_positions == [returned[new_index].position], (
        f"target_positions={out.target_positions!r}; on an add that changes nothing "
        "else they must be exactly the new slide's position in the returned deck_spec, "
        f"[{returned[new_index].position}].  Any committed slide's position here would "
        "rebuild that slide."
    )

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

THE CONTRACT: AN ANCHORED ADD IS AN EDIT, ANSWERED AS OPERATIONS
----------------------------------------------------------------
Issue #314 made "add a slide to an existing deck" an ``edit``.  When the user says
"add a slide after slide 2", the resulting deck must:

  * keep every committed slide unchanged except its position, in order, and add
    exactly one slide;
  * have the new slide straight after the named slide.  Slide 2 is the slide the
    user means to anchor the new one, not a slide to change: it is position 1, so
    the new slide is at index 2 of the resulting deck and the committed slides after
    it move up by one;
  * build only the new slide.

Since architect edit operations the prompt answers this with ``operations`` — an
``insert`` with ``after_position`` 1 — and ``architect_node`` composes the deck
itself (``apply_operations`` + ``compose_edit_spec`` over the persisted spec) and
builds exactly the operations' ``rebuild``; the model's ``target_positions`` are
not read on that path.  An answer without ``operations`` or ``deck_changes`` still
takes the #314 full-spec path: the revised ``deck_spec`` in full, and
``target_positions`` naming only the new slide (its position in that spec).  The
test accepts either shape and checks the same property on each.

The anchor is the trap this test guards.  ``slide_references`` resolves "slide 2" to
position 1; on an add that is where the new slide goes, not a slide to change, so
an ``update`` of position 1 — or a ``target_positions`` of ``[1]`` on a full spec —
would rebuild the anchor, which the user did not ask to change.

THE COMPLEMENTARY PAIR (RC2 AND RC9)
------------------------------------
RC2 tests "add a slide" without a positional reference — the product rule places the
new slide before the deck's closing slide.  RC9 tests "add after slide N" WITH a
positional reference — the new slide goes straight after slide N.  RC2's test uses 3
committed slides; this test uses 4 to avoid numeric overlap that might make the two
feel duplicated.

THE ASSERTION IS STRUCTURAL
---------------------------
The test reads the resulting deck — composed from the operations exactly as
production composes them, or the returned spec.
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


def _applied(out, existing):
    """What ``architect_node`` lands for an operations answer, without a database.

    ``apply_operations`` over the payload's own deck, then ``compose_edit_spec`` with
    the answer's ``deck_changes`` — the two pure steps the node's operations path
    runs (``_plan_operations_edit``).  A refusal there would degrade the turn (after
    one retry), so the new slide would not be added: it fails the test, naming the
    problems.
    """
    from src.domain.deck_spec import DeckSpec
    from src.domain.slide_operations import (
        OperationProblems,
        apply_operations,
        compose_edit_spec,
    )

    current = DeckSpec.model_validate(existing)
    result = apply_operations(current.slides, out.operations or [])
    assert not isinstance(result, OperationProblems), (
        "the architect's operations do not apply to the committed deck, so "
        "architect_node would refuse the edit and the new slide would not be added.  "
        f"problems={[(p.code, p.detail) for p in result.problems]!r}, "
        f"operations={out.operations!r}"
    )
    composed = compose_edit_spec(current, result, out.deck_changes)
    assert not isinstance(composed, OperationProblems), (
        "the architect's operations and deck_changes do not compose into a valid "
        "deck, so architect_node would refuse the edit.  "
        f"problems={[(p.code, p.detail) for p in composed.problems]!r}, "
        f"deck_changes={out.deck_changes!r}"
    )
    return result, composed


def test_the_architect_adds_a_slide_at_the_referenced_position():
    """RC9 on the graph path: 'add after slide 2' inserts straight after slide 2.

    Four slides are committed.  The user requests a new slide after slide 2
    (position 1).  The architect must return an edit whose resulting deck holds the
    four committed slides unchanged (ignoring position), in order, plus one new slide
    at index 2, and only the new slide may be built: the operations' ``rebuild`` when
    the answer carries operations, ``target_positions`` when it is a full
    ``deck_spec``.
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
        "whose insert operation (or revised deck_spec) carries the new slide.  A "
        "'discuss' reply here is the pre-RC9 regression (asking when both the intent "
        "and the position were explicit); a 'build' would rebuild every committed "
        f"slide.  message={out.message!r}, operations={out.operations!r}, "
        f"target_positions={out.target_positions!r}"
    )
    committed_keys = [slide_key(SlideSpec(**s)) for s in existing["slides"]]
    new_index = anchor_index + 1

    if out.operations is not None or out.deck_changes is not None:
        # The operations path: production composes the deck and builds `rebuild`,
        # whatever deck_spec or target_positions the answer also carries.
        result, composed = _applied(out, existing)
        returned = list(composed.slides)
        assert len(returned) == committed + 1, (
            f"the architect's operations leave {len(returned)} slide(s) after 'add a "
            f"slide after slide 2' against a {committed}-slide committed deck; exactly "
            f"{committed + 1} were expected (every committed slide plus the new one).  "
            f"operations={out.operations!r}"
        )
        inserted = [i for i, persisted in enumerate(result.layout) if persisted is None]
        assert inserted == [new_index], (
            f"the architect's operations insert new slides at {inserted} of the "
            f"resulting deck (position order); 'after slide 2' puts one new slide at "
            f"index {new_index}, straight after the named slide (index {anchor_index}).  "
            f"Index {anchor_index} means slide 2's number was read as the new slide's "
            f"number; index {committed} means the reference was ignored and the slide "
            f"appended.  operations={out.operations!r}"
        )
        kept = [persisted for persisted in result.layout if persisted is not None]
        assert kept == list(range(committed)), (
            f"the committed slides land in the order {kept}; an add must keep every "
            f"committed slide, in its committed order {list(range(committed))} — "
            "nothing deleted, nothing moved.  "
            f"operations={out.operations!r}"
        )
        others = [slide_key(s) for i, s in enumerate(returned) if i != new_index]
        assert others == committed_keys, (
            "the slides other than the new one are not the committed slides, "
            "unchanged (comparing every field but position): an operation rewrote a "
            "committed slide, often the anchor or its neighbour.  "
            f"operations={out.operations!r}"
        )
        assert list(result.rebuild) == [new_index], (
            f"the architect's operations build {list(result.rebuild)}; on an add that "
            f"changes nothing else they must build exactly the new slide, [{new_index}].  "
            "The named slide is the anchor, not a target: building it would rebuild a "
            f"slide the user did not ask to change.  operations={out.operations!r}"
        )
    else:
        # The full-spec path (#314), unchanged.
        assert out.deck_spec is not None, (
            "the architect returned intent='edit' with neither operations nor a "
            "deck_spec.  Such an edit cannot be applied (architect_node refuses it), "
            f"so the new slide would be lost.  message={out.message!r}"
        )
        returned = sorted(out.deck_spec.slides, key=lambda slide: slide.position)
        assert len(returned) == committed + 1, (
            f"the architect returned {len(returned)} slide(s) for 'add a slide after "
            f"slide 2' against a {committed}-slide committed deck; exactly "
            f"{committed + 1} were expected (every committed slide plus the new one).  "
            f"Returned positions: {[s.position for s in returned]}"
        )

        new_indices = [
            i for i, s in enumerate(returned) if slide_key(s) not in committed_keys
        ]
        assert len(new_indices) == 1, (
            f"{len(new_indices)} returned slide(s) differ from every committed slide "
            "(comparing every field but position); exactly one, the new slide, should.  "
            "More than one means a committed slide (often the anchor or its neighbour) "
            f"was rewritten.  Differing indices in position order: {new_indices}"
        )
        (returned_index,) = new_indices
        others = [slide_key(s) for i, s in enumerate(returned) if i != returned_index]
        assert others == committed_keys, (
            "the slides other than the new one are not the committed slides, unchanged "
            "and in their committed order (comparing every field but position).  An add "
            "must copy every committed slide as it is; only the positions after the new "
            "slide move up by one."
        )
        assert returned_index == new_index, (
            f"the new slide is at index {returned_index} of the returned deck (position "
            f"order); 'after slide 2' puts it at index {new_index}, straight after the "
            f"named slide (index {anchor_index}).  Index {anchor_index} means slide 2's "
            f"number was read as the new slide's number; index {committed} means the "
            "reference was ignored and the slide appended."
        )
        assert out.target_positions == [returned[returned_index].position], (
            f"target_positions={out.target_positions!r}; on an add that changes nothing "
            "else they must be exactly the new slide's position in the returned "
            f"deck_spec, [{returned[returned_index].position}].  The named slide is the "
            "anchor, not a target: its position here would rebuild a slide the user did "
            "not ask to change."
        )

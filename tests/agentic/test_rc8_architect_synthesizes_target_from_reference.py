"""Layer 3: the architect synthesises a target position from a parsed slide reference — RC8.

RC8'S MEANING, READ OFF THE CODE
---------------------------------
``src/api/services/chat_service.py`` marks RC8 at lines 1494-1518 (streaming path):

    # RC8: User said "edit slide 8" - create synthetic context
    # RC8: Creating synthetic slide_context from parsed reference

The shipped fix: when the streaming path detects a text reference like "edit slide 8"
(``_slide_refs`` is non-empty), it synthesises a ``slide_context`` for the agent
rather than asking the user for clarification.  The regression this fixed: "edit
slide 8" prompted a clarification question (RC10 behaviour) even when the reference
was unambiguous.

On the graph path there is no ``slide_context`` synthesised before the LLM call.
The architect IS the synthesis step: it reads the message, sees the text reference,
and aims its edit at the correct 0-indexed position.  When the user writes "edit
slide 8", the architect must:

  * return ``intent='edit'``
  * build the slide at position 7 (0-indexed).

What "build" means depends on the answer's shape, because production reads the two
differently.  Since architect edit operations the prompt answers with ``operations``
(an ``update`` of position 7): ``architect_node`` applies them
(``apply_operations``) and builds exactly their ``rebuild``, ignoring the model's
``target_positions``, so the test applies them the same way and asks whether
persisted position 7 is among the slides rebuilt.  An answer without ``operations``
or ``deck_changes`` takes the full-spec path, where ``target_positions`` is still
read, so there 7 must appear in it.

If it returns ``discuss`` asking for clarification, it exhibits the pre-RC8
regression.  If it returns ``edit`` aimed at the wrong position (e.g., position 8
instead of 7, or an unrelated position), the reference was not parsed correctly.

THE ASSERTION IS STRUCTURAL
----------------------------
The rebuilt positions (or ``target_positions``) are an integer list; the assertion
is that the expected 0-indexed position appears there.  No wording of the message
is asserted.

RC10 IS A DIFFERENT TEST
------------------------
RC10 (``tests/agentic/test_architect_asks_when_reference_is_ambiguous.py``) covers
edit intent with NO slide reference against a multi-slide deck where ambiguity is
genuine.  RC8 covers edit intent WITH an unambiguous reference: the two are the
complementary pair, and together they define when the architect must ask and when
it must act.
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import architect_payload, deck_spec_dict, slide_spec

pytestmark = LAYER3_MARKS


def _rebuilt_positions(out, existing) -> list[int]:
    """The PERSISTED positions an operations answer rebuilds, as production applies it.

    ``apply_operations`` over the payload's own deck, then ``compose_edit_spec`` with
    the answer's ``deck_changes`` (``architect_node``'s ``_plan_operations_edit``).
    ``rebuild`` holds indices of the resulting deck; ``layout`` maps each back to the
    persisted position whose row lands there, so an updated (or replaced) slide is
    reported at its own position and an inserted one not at all.  A refusal would
    degrade the turn (after one retry), so nothing would be edited: it fails the
    test, naming the problems.
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
        "architect_node would refuse the edit and nothing would change.  "
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
    return sorted(
        result.layout[index]
        for index in result.rebuild
        if result.layout[index] is not None
    )


def test_the_architect_targets_the_referenced_slide_without_asking():
    """RC8 on the graph path: 'edit slide 8' edits position 7, not a question.

    Eight slides are committed.  The user names slide 8 explicitly.  The architect
    must classify as 'edit' and aim the edit at position 7 (0-indexed) without asking
    for clarification — the reference is unambiguous.  On an operations answer
    position 7 must be among the slides its operations rebuild; on a full
    ``deck_spec`` answer it must be in ``target_positions``.
    """
    existing = deck_spec_dict(
        [
            slide_spec(i, purpose=f"section {i + 1}", content_brief=f"content for section {i + 1}")
            for i in range(8)
        ],
        title="Annual Operating Plan",
    )

    out = invoke_agent(
        "architect",
        architect_payload(
            "edit slide 8 to include a bar chart of quarterly results",
            current_deck_spec=existing,
            committed_slide_count=8,
        ),
        False,
    )

    assert out.intent == "edit", (
        f"the architect returned intent={out.intent!r} for 'edit slide 8' against an "
        "eight-slide deck.  RC8 requires it to synthesise the target from the "
        "reference and return 'edit', not ask for clarification.  A 'discuss' intent "
        "here is the pre-RC8 regression: the architect asked which slide when told "
        f"explicitly.  operations={out.operations!r}, "
        f"target_positions={out.target_positions!r}, message={out.message!r}"
    )
    if out.operations is not None or out.deck_changes is not None:
        # The operations path: production builds the operations' rebuild and does
        # not read target_positions.
        rebuilt = _rebuilt_positions(out, existing)
        assert 7 in rebuilt, (
            f"the architect's operations rebuild persisted positions {rebuilt} for "
            "'edit slide 8'.  Position 7 (0-indexed) must be among them.  RC8 "
            "encodes: the text reference 'slide 8' maps to 0-indexed position 7 and "
            "that slide is the one edited, not guessed.  A list without 7 means the "
            f"reference was misread or discarded.  operations={out.operations!r}"
        )
    else:
        assert 7 in out.target_positions, (
            f"the architect returned target_positions={out.target_positions!r} for "
            "'edit slide 8'.  Position 7 (0-indexed) must appear in the list.  RC8 "
            "encodes: the text reference 'slide 8' maps to 0-indexed position 7 and "
            "that position is targeted, not guessed.  A position that is not 7 means "
            "the reference was misread or discarded."
        )

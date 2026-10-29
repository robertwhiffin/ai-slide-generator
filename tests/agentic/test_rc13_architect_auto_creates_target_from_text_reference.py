"""Layer 3: the architect derives target_positions from a text reference — RC13.

RC13'S MEANING, READ OFF THE CODE
----------------------------------
``src/api/services/chat_service.py`` marks RC13 at lines 631 and 655 (sync path) and
1218, 1242 (streaming path):

    # RC13: Auto-create slide_context from text reference (sync path)
    if _is_edit and _slide_refs and not slide_context:
        ...
        "RC13: Auto-created slide_context from text reference (sync)"

The shipped fix: when edit intent is detected AND ``_slide_refs`` contains a parsed
position AND no ``slide_context`` was supplied by the frontend, the system creates
a synthetic ``slide_context`` from the reference.  Without this fix, a message like
"make slide 3 more concise" would reach the agent without context and either ask
for clarification or edit the wrong slide.

On the graph path there is no separate ``slide_context`` creation step.  The
architect receives the message and aims its edit directly.  RC13's protection on the
graph path: when the user says something like "make slide 3 more concise" against a
multi-slide deck, the architect must:

  * return ``intent='edit'``
  * build the slide at position 2 (0-indexed).

What "build" means depends on the answer's shape, because production reads the two
differently.  Since architect edit operations the prompt answers with ``operations``
(an ``update`` of position 2): ``architect_node`` applies them
(``apply_operations``) and builds exactly their ``rebuild``, ignoring the model's
``target_positions``, so the test applies them the same way and asks whether
persisted position 2 is among the slides rebuilt.  An answer without ``operations``
or ``deck_changes`` takes the full-spec path, where ``target_positions`` is still
read, so there 2 must appear in it.

If it returns ``discuss`` asking which slide, that is the pre-RC13 regression.

THE DISTINCTION FROM RC8
------------------------
RC8 (``tests/agentic/test_rc8_architect_synthesizes_target_from_reference.py``)
uses the explicit "edit slide N" phrasing as the reference.  RC13 uses a more
natural request ("make slide 3 more concise") where the number is embedded in a
command rather than a pure slide-number reference.  The monolith's code treats both
through the same ``_slide_refs`` mechanism, but the two phrasings represent
different linguistic contexts.  Testing both raises the chance of catching a model
that handles one form but not the other.

RC10 IS THE OPPOSITE CASE
--------------------------
RC10 (``tests/agentic/test_architect_asks_when_reference_is_ambiguous.py``) fires
when there is NO reference and multiple slides could be the target.  RC13 fires when
there IS a reference and the slide is named.  Together they define the boundary: the
architect must ask when ambiguous and must act when given a name.

THE ASSERTION IS STRUCTURAL
----------------------------
The rebuilt positions (or ``target_positions``) are an integer list; the assertion
is that 2 (0-indexed slide 3) appears there.  No message wording is asserted.
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


def test_the_architect_targets_the_named_slide_without_being_asked():
    """RC13 on the graph path: a natural-language slide reference → that slide is edited.

    Six slides are committed.  The user names slide 3 in a natural command.  The
    architect must classify as 'edit' and aim the edit at position 2 (0-indexed)
    without asking for clarification — the slide is explicitly identified.  On an
    operations answer position 2 must be among the slides its operations rebuild; on
    a full ``deck_spec`` answer it must be in ``target_positions``.
    """
    existing = deck_spec_dict(
        [
            slide_spec(0, purpose="context", content_brief="the background"),
            slide_spec(1, purpose="problem", content_brief="what needs solving"),
            slide_spec(2, purpose="solution", content_brief="the proposed approach"),
            slide_spec(3, purpose="evidence", content_brief="supporting data"),
            slide_spec(4, purpose="risks", content_brief="what could go wrong"),
            slide_spec(5, purpose="recommendation", content_brief="the ask"),
        ],
        title="Technology Investment Proposal",
    )

    out = invoke_agent(
        "architect",
        architect_payload(
            "make slide 3 more concise — it is too long for the time we have",
            current_deck_spec=existing,
            committed_slide_count=6,
        ),
        False,
    )

    assert out.intent == "edit", (
        f"the architect returned intent={out.intent!r} for 'make slide 3 more "
        "concise' against a six-slide deck.  RC13 requires it to recognise the "
        "reference and return 'edit', not ask which slide.  A 'discuss' intent here "
        "is the pre-RC13 regression: the architect asked which slide when told "
        f"explicitly.  operations={out.operations!r}, "
        f"target_positions={out.target_positions!r}, message={out.message!r}"
    )
    if out.operations is not None or out.deck_changes is not None:
        # The operations path: production builds the operations' rebuild and does
        # not read target_positions.
        rebuilt = _rebuilt_positions(out, existing)
        assert 2 in rebuilt, (
            f"the architect's operations rebuild persisted positions {rebuilt} for "
            "'make slide 3 more concise'.  Position 2 (0-indexed for slide 3) must be "
            "among them.  RC13 encodes: the text reference 'slide 3' maps to "
            "0-indexed position 2 and that slide is the one edited.  A list without 2 "
            f"means the reference was misread or discarded.  operations={out.operations!r}"
        )
    else:
        assert 2 in out.target_positions, (
            f"the architect returned target_positions={out.target_positions!r} for "
            "'make slide 3 more concise'.  Position 2 (0-indexed for slide 3) must "
            "appear in the list.  RC13 encodes: the text reference 'slide 3' maps to "
            "0-indexed position 2 and that position is targeted.  A list that does not "
            "contain 2 means the reference was misread or discarded."
        )

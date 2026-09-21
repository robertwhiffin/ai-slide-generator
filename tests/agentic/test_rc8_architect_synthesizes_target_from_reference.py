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
and places the correct 0-indexed position in ``target_positions``.  When the user
writes "edit slide 8", the architect must:

  * return ``intent='edit'``
  * include position 7 (0-indexed) in ``target_positions``

If it returns ``discuss`` asking for clarification, it exhibits the pre-RC8
regression.  If it returns ``edit`` with wrong positions (e.g., position 8 instead
of 7, or an unrelated position), the reference was not parsed correctly.

THE ASSERTION IS STRUCTURAL
----------------------------
``target_positions`` is an integer list; the assertion is that the expected
0-indexed position appears there.  No wording of the message is asserted.

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


def test_the_architect_targets_the_referenced_slide_without_asking():
    """RC8 on the graph path: 'edit slide 8' sets target_positions to [7], not a question.

    Eight slides are committed.  The user names slide 8 explicitly.  The architect
    must classify as 'edit' and target position 7 (0-indexed) without asking for
    clarification — the reference is unambiguous.
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
        f"explicitly.  target_positions={out.target_positions!r}, "
        f"message={out.message!r}"
    )
    assert 7 in out.target_positions, (
        f"the architect returned target_positions={out.target_positions!r} for "
        "'edit slide 8'.  Position 7 (0-indexed) must appear in the list.  RC8 "
        "encodes: the text reference 'slide 8' maps to 0-indexed position 7 and "
        "that position is targeted, not guessed.  A position that is not 7 means "
        "the reference was misread or discarded."
    )

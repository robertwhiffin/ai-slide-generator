"""Layer 3: the architect asks add-or-replace when generation intent meets an existing deck — RC12.

RC12'S MEANING, READ OFF THE CODE
----------------------------------
``src/api/services/chat_service.py`` marks RC12 at lines 568–571 (sync path) and
1150 (streaming path):

    # RC12: Generation intent with existing deck - ask add or replace
    if _is_generation and not _is_add and not _is_explicit_replace:
        ...
        "RC12: Clarification needed - generation intent with existing deck (sync)"

The shipped fix: when the user's message looks like a request to generate or build a
new presentation AND a deck already exists in the session, the system asks whether
to add to the existing deck or replace it, rather than silently overwriting the
user's prior work.

On the graph path there is no pre-LLM generation-intent classifier.  The architect
IS the classification.  RC12's protection on the graph path: when the architect
receives a message that is clearly about building a new presentation (e.g. "create a
presentation about X") against a session with committed slides, it must recognise
the ambiguity and return ``discuss`` intent with a clarifying question rather than
immediately issuing a ``build`` intent that would overwrite the existing deck.

The key distinction from RC10
------------------------------
RC10 fires on EDIT intent with no slide reference (ambiguous edit).  RC12 fires on
GENERATION intent with an existing deck (ambiguous overwrite vs. addition).
The two are complementary: together they cover the two shapes of ambiguity the
monolith's early-detection layer guarded against.

RC10 is already written at:
``tests/agentic/test_architect_asks_when_reference_is_ambiguous.py::
test_the_architect_asks_which_slide_rather_than_choosing_one``

THE ASSERTION IS STRUCTURAL
----------------------------
``intent == "discuss"`` plus the presence of ``?`` in the message.  No specific
sentence or phrasing is asserted — a question mark is punctuation, not wording.
The discuss intent is the classification the monolith's equivalent returns;
a ``build`` intent here is the regression (silent overwrite of prior work).
"""

from __future__ import annotations

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import architect_payload, deck_spec_dict, slide_spec

pytestmark = LAYER3_MARKS


def test_the_architect_asks_before_replacing_an_existing_deck():
    """RC12 on the graph path: generation intent + existing deck → clarification question.

    Three slides are committed.  The user sends a plain generation request.  The
    architect must ask whether to add to or replace the existing deck, not issue a
    build intent that would silently overwrite it.
    """
    existing = deck_spec_dict(
        [
            slide_spec(0, purpose="introduce the product", content_brief="what the product does"),
            slide_spec(1, purpose="show traction", content_brief="growth metrics"),
            slide_spec(2, purpose="ask for investment", content_brief="the ask"),
        ],
        title="Seed Round Pitch",
    )

    out = invoke_agent(
        "architect",
        architect_payload(
            "build me a five-slide presentation about our Series A strategy",
            current_deck_spec=existing,
            committed_slide_count=3,
        ),
        False,
    )

    assert out.intent == "discuss", (
        f"the architect returned intent={out.intent!r} for a generation request "
        "against a three-slide committed deck.  RC12 requires the architect to ask "
        "add-or-replace rather than issuing a build that would overwrite the "
        "existing deck.  A 'build' intent here is the pre-RC12 regression: the "
        "user's three slides would be silently discarded.  "
        f"deck_spec={out.deck_spec is not None}, "
        f"target_positions={out.target_positions!r}"
    )
    assert "?" in out.message, (
        "the architect returned intent='discuss' but its message contains no "
        "question mark, so it did not ask the user anything.  RC12 requires a "
        "clarifying question — not a specific sentence, just punctuation showing "
        f"something was asked.  message length: {len(out.message)}"
    )
    assert out.deck_spec is None, (
        "the architect returned a deck_spec on a discuss turn triggered by RC12.  "
        "The clarification must wait for the user's answer before a spec is "
        "committed; returning one here would rebuild the deck before the user "
        f"has said whether they want to replace or add.  deck_spec is set."
    )

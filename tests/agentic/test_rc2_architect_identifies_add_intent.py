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

THE CONTRACT: AN ADD IS AN EDIT, ANSWERED AS OPERATIONS
-------------------------------------------------------
Issue #314 made "add a slide to an existing deck" an ``edit``.  Since architect edit
operations the prompt answers it with ``operations`` (an ``insert`` after the slide
the new one follows) rather than a rewritten deck: ``architect_node`` composes the
next deck itself (``apply_operations`` + ``compose_edit_spec`` over the persisted
spec), keeps every committed slide as it was, and builds exactly the operations'
``rebuild`` — the inserted slide.  The model's ``target_positions`` are not read on
that path.  An answer without ``operations`` or ``deck_changes`` still takes the
#314 full-spec path: the revised ``deck_spec`` in full, every committed slide copied
unchanged but for the positions after the new one, and ``target_positions`` naming
only the new slide.  The test accepts either shape and checks the same property on
each.  (Before #314 an add came back as a ``build``, which rebuilt every slide.)

This message states no place.  The product rule for that case (plan D6): the new
slide goes where it fits the argument, before a closing or call-to-action slide,
unless the new slide is itself a closing slide.  The committed deck ends in a "close"
slide and the new slide is not one, so it goes straight before that closing slide.

THE ASSERTION IS STRUCTURAL, NOT A WORDING CHECK
-------------------------------------------------
The test reads the resulting deck's slides — composed from the operations exactly
as production composes them, or the returned spec's — not what the message says.
"Equal" means equal in every ``SlideSpec`` field but ``position``
(``src.domain.slide_alignment.slide_key``, the comparison production aligns with).
The observable regressions: operations the node would refuse, a deck that lost a
committed slide, a rewritten or moved neighbour, the new slide appended after the
close, or a build (``rebuild``, or ``target_positions`` on a full spec) that would
rebuild committed slides.

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


def test_the_architect_adds_to_an_existing_deck_rather_than_replacing_it():
    """RC2 on the graph path: 'add a slide' is an edit that keeps the committed deck.

    Three slides are committed, the last a closing slide; the user asks for a new one
    and states no place.  The resulting deck must hold the three committed slides
    unchanged (ignoring position), in order, plus one new slide straight before the
    closing slide, and only the new slide may be built: the operations' ``rebuild``
    when the answer carries operations, ``target_positions`` when it is a full
    ``deck_spec``.
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
        "an edit: an insert operation (or a revised deck_spec) carries the new slide, "
        "and only the new slide is built.  A 'build' would rebuild every committed "
        "slide; a 'discuss' would add nothing.  "
        f"operations={out.operations!r}, target_positions={out.target_positions!r}, "
        f"message={out.message!r}"
    )
    committed_keys = [slide_key(SlideSpec(**s)) for s in existing["slides"]]

    if out.operations is not None or out.deck_changes is not None:
        # The operations path: production composes the deck and builds `rebuild`,
        # whatever deck_spec or target_positions the answer also carries.
        result, composed = _applied(out, existing)
        returned = list(composed.slides)
        assert len(returned) == committed + 1, (
            f"the architect's operations leave {len(returned)} slide(s) after one 'add "
            f"a slide' request against a {committed}-slide committed deck; exactly "
            f"{committed + 1} were expected (every committed slide plus the new one).  "
            f"operations={out.operations!r}"
        )
        inserted = [i for i, persisted in enumerate(result.layout) if persisted is None]
        assert inserted == [closing_index], (
            f"the architect's operations insert new slides at {inserted} of the "
            f"resulting deck (position order); the product rule puts one new slide at "
            f"index {closing_index}, straight before the closing slide, when the user "
            "gives no place and the new slide is not itself a closing slide.  Index "
            f"{committed} means it was appended after the close.  "
            f"operations={out.operations!r}"
        )
        kept = [persisted for persisted in result.layout if persisted is not None]
        assert kept == list(range(committed)), (
            f"the committed slides land in the order {kept}; an add must keep every "
            f"committed slide, in its committed order {list(range(committed))} — "
            "nothing deleted, nothing moved.  "
            f"operations={out.operations!r}"
        )
        others = [slide_key(s) for i, s in enumerate(returned) if i != closing_index]
        assert others == committed_keys, (
            "the slides other than the new one are not the committed slides, "
            "unchanged (comparing every field but position): an operation rewrote a "
            "committed slide to fit the new one.  "
            f"operations={out.operations!r}"
        )
        assert list(result.rebuild) == [closing_index], (
            f"the architect's operations build {list(result.rebuild)}; on an add that "
            "changes nothing else they must build exactly the new slide, "
            f"[{closing_index}].  Any other index here would rebuild a committed slide.  "
            f"operations={out.operations!r}"
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
            f"the architect returned {len(returned)} slide(s) for one 'add a slide' "
            f"request against a {committed}-slide committed deck; exactly "
            f"{committed + 1} were expected (every committed slide plus the new one).  "
            "Fewer means a committed slide was dropped; more means slides were "
            f"invented.  Returned positions: {[s.position for s in returned]}"
        )

        new_indices = [
            i for i, s in enumerate(returned) if slide_key(s) not in committed_keys
        ]
        assert len(new_indices) == 1, (
            f"{len(new_indices)} returned slide(s) differ from every committed slide "
            "(comparing every field but position); exactly one, the new slide, should.  "
            "More than one means a committed slide was rewritten to fit the new one.  "
            f"Differing indices in position order: {new_indices}"
        )
        (new_index,) = new_indices
        others = [slide_key(s) for i, s in enumerate(returned) if i != new_index]
        assert others == committed_keys, (
            "the slides other than the new one are not the committed slides, unchanged "
            "and in their committed order (comparing every field but position).  An add "
            "must copy every committed slide as it is; only the positions after the new "
            "slide move up by one."
        )
        assert new_index == closing_index, (
            f"the new slide is at index {new_index} of the returned deck (position "
            f"order); the product rule puts it at index {closing_index}, straight before "
            "the closing slide, when the user gives no place and the new slide is not "
            f"itself a closing slide.  Index {committed} means it was appended after "
            "the close."
        )
        assert out.target_positions == [returned[new_index].position], (
            f"target_positions={out.target_positions!r}; on an add that changes nothing "
            "else they must be exactly the new slide's position in the returned "
            f"deck_spec, [{returned[new_index].position}].  Any committed slide's "
            "position here would rebuild that slide."
        )

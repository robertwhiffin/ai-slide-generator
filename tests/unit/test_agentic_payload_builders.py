"""The layer-3 architect payload builder resolves slide references as production does (#313).

``tests/agentic/payloads.py`` exists so a layer-3 test asks the architect the
question production asks.  Since #313 ``architect_node`` sends two derived keys,
``slide_numbering`` and ``slide_references``, computed by
``src.domain.slide_numbering.architect_slide_payload`` from the conversation,
the message and the deck.  A builder that left them empty, or computed them from
its own defaults rather than from the caller's overrides, would hand the model a
deck whose "slide 2" resolves to nothing, or to a slide of a different deck.

These run in the unit suite: the builder is pure, no model is called.
"""

from __future__ import annotations

import pytest

from tests.agentic.payloads import (
    ARCHITECT_PAYLOAD_KEYS,
    architect_payload,
    deck_spec_dict,
    slide_spec,
)


def _deck(positions=(0, 1, 2)):
    return deck_spec_dict(
        [
            slide_spec(p, purpose=f"purpose {p}", content_brief=f"brief {p}")
            for p in positions
        ],
        title="t",
    )


def test_every_production_key_is_present():
    """Absent keys are as significant as present ones: all eleven, always."""
    assert set(architect_payload("Make slide 2 shorter")) == set(ARCHITECT_PAYLOAD_KEYS)


def test_a_reference_in_the_message_resolves_against_the_overridden_deck():
    payload = architect_payload("Make slide 2 shorter", current_deck_spec=_deck())

    assert payload["slide_numbering"] == [
        {"slide_number": 1, "position": 0},
        {"slide_number": 2, "position": 1},
        {"slide_number": 3, "position": 2},
    ]
    assert payload["slide_references"] == [
        {
            "text": "slide 2",
            "slide_numbers": [2],
            "positions": [1],
            "out_of_range": [],
        }
    ]


def test_the_deck_is_numbered_by_its_slides_positions_not_their_count():
    """A gapped spec (0, 2, 5): "slide 3" is position 5."""
    payload = architect_payload("Make slide 3 shorter", current_deck_spec=_deck((0, 2, 5)))

    assert payload["slide_numbering"] == [
        {"slide_number": 1, "position": 0},
        {"slide_number": 2, "position": 2},
        {"slide_number": 3, "position": 5},
    ]
    assert [r["positions"] for r in payload["slide_references"]] == [[5]]


def test_with_no_deck_both_keys_are_empty_lists():
    payload = architect_payload("Make slide 2 shorter")

    assert payload["slide_numbering"] == []
    assert payload["slide_references"] == []


def test_the_latest_user_turn_of_an_overridden_conversation_is_resolved():
    """Computed from the POST-override conversation: its latest user turn names
    slide 3 (position 2), not the earlier turn's slide 2 and not ``message``."""
    payload = architect_payload(
        "Q3 revenue was 10",
        conversation=[
            {"role": "user", "content": "Make slide 2 shorter"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Now tighten slide 3"},
        ],
        current_deck_spec=_deck(),
    )

    assert payload["slide_references"] == [
        {
            "text": "slide 3",
            "slide_numbers": [3],
            "positions": [2],
            "out_of_range": [],
        }
    ]


def test_an_explicit_slide_references_override_wins():
    payload = architect_payload(
        "Make slide 2 shorter", current_deck_spec=_deck(), slide_references=[]
    )

    assert payload["slide_references"] == []
    # Only the overridden key is replaced; the other is still computed.
    assert payload["slide_numbering"] == [
        {"slide_number": 1, "position": 0},
        {"slide_number": 2, "position": 1},
        {"slide_number": 3, "position": 2},
    ]


def test_an_explicit_slide_numbering_override_wins():
    numbering = [{"slide_number": 1, "position": 7}]

    payload = architect_payload(
        "Make slide 2 shorter", current_deck_spec=_deck(), slide_numbering=numbering
    )

    assert payload["slide_numbering"] == numbering


def test_an_unknown_key_still_raises():
    with pytest.raises(KeyError, match="slide_refs"):
        architect_payload("Make slide 2 shorter", slide_refs=[])

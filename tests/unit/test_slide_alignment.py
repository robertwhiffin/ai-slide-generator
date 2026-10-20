"""Contract for ``src.domain.slide_alignment`` (issue #314, plan D1, corrections C1).

An edit whose revised ``deck_spec`` has more slides than the persisted one is an
insertion. ``align_slides(old, new)`` sorts both lists by position and pairs
every persisted slide with one returned slide, in order. The remaining
``len(new) - len(old)`` returned slides are inserted. The pairing minimises,
lexicographically, (slides whose purpose or brief changed, slides with any
field but ``position`` changed). It never guesses:

- more than one optimal pairing -> ``ambiguous``;
- a revised pair whose new slide equals a DIFFERENT old slide, or an inserted
  slide equal to an old slide whose own pair is revised -> ``moves_slides``
  (an edit never moves a slide's spec; C1 widens the plan's rule);
- fewer returned slides than persisted ones -> ``removes_slides``.

Numberings (D1, finding 1). Every accepted row asserts both:
- ``inserted`` / ``revised``: the returned spec's own ``SlideSpec.position``;
- ``inserted_indices`` / ``revised_indices``: indices in position order;
- ``old_to_new_index``: persisted ``SlideSpec.position`` -> returned index;
- ``new_positions``: returned index -> returned ``SlideSpec.position``.

Deck notation used by the tables:
- a deck is a space-separated list of slide tokens, e.g. ``"A B C~brief X D"``;
- every name (``A``, ``S9``, ``X`` ...) has its own distinct purpose,
  content_brief, assumes, hands_off and data_references. ``X``, ``Y`` and ``Z``
  play the new slides;
- ``B~brief`` is slide B with only its content_brief rewritten. The other
  suffixes are ``~purpose``, ``~assumes``, ``~hands_off``,
  ``~data_references``, ``~slide_type`` and ``~template_section_index``;
- positions are ``0..n-1`` unless the row gives them (gapped decks).
"""

from __future__ import annotations

import copy
import dataclasses
import json

import pytest

from src.domain.deck_spec import SlideSpec
from src.domain.slide_alignment import (
    AlignmentRefused,
    SlideAlignment,
    align_slides,
    slide_key,
)

REFUSAL_CODES = {"removes_slides", "ambiguous", "moves_slides"}

# Every SlideSpec field the alignment compares (everything but ``position``).
COMPARED_FIELDS = [
    "purpose",
    "content_brief",
    "assumes",
    "hands_off",
    "data_references",
    "slide_type",
    "template_section_index",
]

_SUFFIX_FIELD = {
    "brief": "content_brief",
    "purpose": "purpose",
    "assumes": "assumes",
    "hands_off": "hands_off",
    "data_references": "data_references",
    "slide_type": "slide_type",
    "template_section_index": "template_section_index",
}


# ---------------------------------------------------------------------------
# Deck builders
# ---------------------------------------------------------------------------


def _base_fields(name: str) -> dict:
    """Distinct values for every compared field of the slide called ``name``."""
    return {
        "purpose": f"{name} purpose: make the {name} point",
        "content_brief": f"{name} brief: the evidence for {name}",
        "assumes": f"{name} assumes: the audience saw the slide before {name}",
        "hands_off": f"{name} hands off: the question {name} leaves open",
        "data_references": [f"{name.lower()}_metrics"],
        "slide_type": None,
        "template_section_index": None,
    }


def _changed(field: str, value):
    if field == "data_references":
        return [*value, "extra_metrics"]
    if field == "slide_type":
        return "chart"
    if field == "template_section_index":
        return 4
    return f"{value} (rewritten)"


def _slide(token: str, position: int) -> SlideSpec:
    name, _, suffixes = token.partition("~")
    fields = _base_fields(name)
    for suffix in filter(None, suffixes.split("+")):
        field = _SUFFIX_FIELD[suffix]
        fields[field] = _changed(field, fields[field])
    return SlideSpec(position=position, **fields)


def _deck(tokens: str, positions: list[int] | None = None) -> list[SlideSpec]:
    names = tokens.split()
    if positions is None:
        positions = list(range(len(names)))
    assert len(positions) == len(names), "row typo: one position per slide"
    return [_slide(token, position) for token, position in zip(names, positions)]


def _seq(start: int, stop: int) -> str:
    return " ".join(f"S{i}" for i in range(start, stop))


def _observed(alignment: SlideAlignment) -> dict:
    return {
        "new_positions": alignment.new_positions,
        "old_to_new_index": dict(alignment.old_to_new_index),
        "inserted_indices": alignment.inserted_indices,
        "revised_indices": alignment.revised_indices,
        "inserted": alignment.inserted,
        "revised": alignment.revised,
    }


def _expect(
    *,
    new_positions,
    old_to_new_index,
    inserted_indices=(),
    revised_indices=(),
    inserted=None,
    revised=None,
) -> dict:
    """Expected result. ``inserted``/``revised`` default to the indices: on a
    deck numbered ``0..n-1`` the two numberings coincide. Gapped rows give
    both explicitly."""
    return {
        "new_positions": tuple(new_positions),
        "old_to_new_index": dict(old_to_new_index),
        "inserted_indices": tuple(inserted_indices),
        "revised_indices": tuple(revised_indices),
        "inserted": tuple(inserted_indices if inserted is None else inserted),
        "revised": tuple(revised_indices if revised is None else revised),
    }


def _identity(n: int) -> dict:
    return {i: i for i in range(n)}


# ---------------------------------------------------------------------------
# Accepted alignments
# ---------------------------------------------------------------------------

# (old tokens, old positions, new tokens, new positions, expected)
ACCEPTED = [
    # --- Equal length: the positional pairing (today's `changed`). ---------
    pytest.param(
        "A B C", None, "A B C", None,
        _expect(new_positions=(0, 1, 2), old_to_new_index=_identity(3)),
        id="equal-nothing-changed",
    ),
    pytest.param(
        "A B C", None, "A B~brief C", None,
        _expect(new_positions=(0, 1, 2), old_to_new_index=_identity(3), revised_indices=(1,)),
        id="equal-one-brief-changed",
    ),
    pytest.param(
        "A B C", [0, 2, 5], "A B C~brief", [0, 2, 5],
        _expect(
            new_positions=(0, 2, 5),
            old_to_new_index={0: 0, 2: 1, 5: 2},
            revised_indices=(2,),
            revised=(5,),
        ),
        id="equal-gapped-revise-position-5",
    ),
    pytest.param(
        "A B C", [0, 2, 5], "A B~brief C", [0, 2, 5],
        _expect(
            new_positions=(0, 2, 5),
            old_to_new_index={0: 0, 2: 1, 5: 2},
            revised_indices=(1,),
            revised=(2,),
        ),
        id="equal-gapped-revise-position-2",
    ),
    # --- Inserts. -----------------------------------------------------------
    pytest.param(
        "A B C", None, "X A B C", None,
        _expect(
            new_positions=(0, 1, 2, 3),
            old_to_new_index={0: 1, 1: 2, 2: 3},
            inserted_indices=(0,),
        ),
        id="insert-at-0",
    ),
    pytest.param(
        "A B C D", None, "A B X C D", None,
        _expect(
            new_positions=(0, 1, 2, 3, 4),
            old_to_new_index={0: 0, 1: 1, 2: 3, 3: 4},
            inserted_indices=(2,),
        ),
        id="insert-mid-deck",
    ),
    pytest.param(
        "A B C", None, "A B C X", None,
        _expect(
            new_positions=(0, 1, 2, 3),
            old_to_new_index=_identity(3),
            inserted_indices=(3,),
        ),
        id="insert-after-the-last-slide",
    ),
    pytest.param(
        "A B C", None, "A X Y B C", None,
        _expect(
            new_positions=(0, 1, 2, 3, 4),
            old_to_new_index={0: 0, 1: 3, 2: 4},
            inserted_indices=(1, 2),
        ),
        id="two-inserts-adjacent",
    ),
    pytest.param(
        "A B C", None, "A X B Y C", None,
        _expect(
            new_positions=(0, 1, 2, 3, 4),
            old_to_new_index={0: 0, 1: 2, 2: 4},
            inserted_indices=(1, 3),
        ),
        id="two-inserts-apart",
    ),
    pytest.param(
        "A B C", None, "X A Y B C Z", None,
        _expect(
            new_positions=(0, 1, 2, 3, 4, 5),
            old_to_new_index={0: 1, 1: 3, 2: 4},
            inserted_indices=(0, 2, 5),
        ),
        id="three-inserts",
    ),
    pytest.param(
        "A B C", [0, 2, 5], "A X B C", None,
        _expect(
            new_positions=(0, 1, 2, 3),
            old_to_new_index={0: 0, 2: 2, 5: 3},
            inserted_indices=(1,),
        ),
        id="insert-into-gapped-deck-restamped",
    ),
    pytest.param(
        "A B C", [0, 2, 5], "A B X C", [0, 2, 3, 5],
        _expect(
            new_positions=(0, 2, 3, 5),
            old_to_new_index={0: 0, 2: 1, 5: 3},
            inserted_indices=(2,),
            inserted=(3,),
        ),
        id="insert-into-gapped-deck-keeping-its-positions",
    ),
    pytest.param(
        # C1: an inserted copy of an UNREVISED slide is not a move.
        "A B C", None, "A B C B", None,
        _expect(
            new_positions=(0, 1, 2, 3),
            old_to_new_index=_identity(3),
            inserted_indices=(3,),
        ),
        id="duplicate-append-is-not-a-move",
    ),
    # --- Insert plus a non-adjacent revision: unique, NEW numbering. ------
    pytest.param(
        _seq(0, 12), None, f"{_seq(0, 3)} X {_seq(3, 9)} S9~brief {_seq(10, 12)}", None,
        _expect(
            new_positions=tuple(range(13)),
            old_to_new_index={**_identity(3), **{i: i + 1 for i in range(3, 12)}},
            inserted_indices=(3,),
            revised_indices=(10,),
        ),
        id="insert-then-revise-old-9-as-new-10",
    ),
    pytest.param(
        _seq(0, 8), None, f"S0 S1~brief {_seq(2, 6)} X S6 S7", None,
        _expect(
            new_positions=tuple(range(9)),
            old_to_new_index={**_identity(6), 6: 7, 7: 8},
            inserted_indices=(6,),
            revised_indices=(1,),
        ),
        id="revise-before-the-insert-point",
    ),
    pytest.param(
        "A B C D", [0, 2, 5, 7], "A B~brief C X D", [0, 2, 5, 6, 7],
        _expect(
            new_positions=(0, 2, 5, 6, 7),
            old_to_new_index={0: 0, 2: 1, 5: 2, 7: 4},
            inserted_indices=(3,),
            revised_indices=(1,),
            inserted=(6,),
            revised=(2,),
        ),
        id="gapped-insert-plus-revision-both-numberings",
    ),
    # --- Insert with the neighbours' hand-offs tweaked: unique at (0, 2). --
    pytest.param(
        "A B C D", None, "A B~hands_off X C~assumes D", None,
        _expect(
            new_positions=(0, 1, 2, 3, 4),
            old_to_new_index={0: 0, 1: 1, 2: 3, 3: 4},
            inserted_indices=(2,),
            revised_indices=(1, 3),
        ),
        id="insert-with-neighbours-hands-off-and-assumes-changed",
    ),
    pytest.param(
        # The new slide shares B's purpose and brief. Pairing B with its
        # unchanged copy costs (0, 0); pairing it with the variant costs
        # (0, 1). Only the full-diff tier tells the two apart.
        "A B C", None, "A B B~hands_off C", None,
        _expect(
            new_positions=(0, 1, 2, 3),
            old_to_new_index={0: 0, 1: 1, 2: 3},
            inserted_indices=(2,),
        ),
        id="full-diff-tier-breaks-an-identity-tie",
    ),
]


@pytest.mark.parametrize("old_tokens, old_positions, new_tokens, new_positions, expected", ACCEPTED)
def test_alignment(old_tokens, old_positions, new_tokens, new_positions, expected):
    old = _deck(old_tokens, old_positions)
    new = _deck(new_tokens, new_positions)

    assert _observed(align_slides(old, new)) == expected


@pytest.mark.parametrize("field", COMPARED_FIELDS)
def test_any_field_but_position_revises_its_slide(field):
    suffix = next(s for s, f in _SUFFIX_FIELD.items() if f == field)
    old = _deck("A B C")
    new = _deck(f"A B~{suffix} C")

    assert _observed(align_slides(old, new)) == _expect(
        new_positions=(0, 1, 2), old_to_new_index=_identity(3), revised_indices=(1,)
    )


def test_an_out_of_order_fresh_position_sorts_to_the_end():
    """The model placed the new slide mid-list but gave it position 10."""
    old = _deck("A B C")
    a, b, c = _deck("A B C")
    new = [a, _slide("X", 10), b, c]

    assert _observed(align_slides(old, new)) == _expect(
        new_positions=(0, 1, 2, 10),
        old_to_new_index=_identity(3),
        inserted_indices=(3,),
        inserted=(10,),
    )


def test_both_lists_are_read_in_position_order_and_left_untouched():
    a, b, c = _deck("A B C", [0, 2, 5])
    old = [c, a, b]
    new_a, x, new_b, new_c = _deck("A X B C~brief")
    new = [new_c, x, new_a, new_b]
    old_before, new_before = copy.deepcopy(old), copy.deepcopy(new)

    result = align_slides(old, new)

    assert _observed(result) == _expect(
        new_positions=(0, 1, 2, 3),
        old_to_new_index={0: 0, 2: 2, 5: 3},
        inserted_indices=(1,),
        revised_indices=(3,),
    )
    assert old == old_before
    assert new == new_before


def test_the_result_is_frozen():
    result = align_slides(_deck("A B"), _deck("A B X"))

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.inserted_indices = (0,)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

# (old tokens, new tokens, code)
REFUSED = [
    # --- Ambiguous: more than one optimal alignment. ------------------------
    pytest.param("A B C D", "A B C~brief X D", "ambiguous", id="insert-after-a-rewritten-brief"),
    pytest.param("A B C D", "A X B~brief C D", "ambiguous", id="insert-before-a-rewritten-brief"),
    pytest.param(
        "A B C D", "A B C~purpose X D", "ambiguous", id="insert-next-to-a-rewritten-purpose"
    ),
    pytest.param("A B C", "A B B C", "ambiguous", id="identical-duplicate-could-be-either-slide"),
    # A reorder plus an insert where all three alignments tie at (2, 2). The
    # tie is refused before any move check, which would run on a guess.
    pytest.param("A B", "B X A", "ambiguous", id="a-tie-is-ambiguous-before-any-move-check"),
    # --- The identity tier ranks before the full diff. -----------------------
    # Identity first, the optimum is (1, 3): A with A~hands_off, B with the
    # copy of A, C with C~hands_off, X inserted. B becomes a copy of A, so it is
    # a move. Ranked by the full diff first, (2, 2) would win and be accepted:
    # A~hands_off inserted, B's and C's slides rewritten into C~hands_off and X.
    pytest.param(
        "A B C",
        "A~hands_off A C~hands_off X",
        "moves_slides",
        id="identity-tier-ranks-before-the-full-diff",
    ),
    # --- Deletion is out of scope. -------------------------------------------
    pytest.param("A B C", "A B", "removes_slides", id="shrink-drops-the-last-slide"),
    pytest.param("A B C D", "A C D", "removes_slides", id="shrink-drops-a-middle-slide"),
    # --- Moves. --------------------------------------------------------------
    pytest.param("A B C", "A C B", "moves_slides", id="equal-length-swap"),
    pytest.param(
        "A B C D E", "A B C X D", "moves_slides", id="insert-at-3-and-drop-the-last-slide"
    ),
    # C1: a reorder plus an insert aligns uniquely as "insert a copy of the
    # moved slide, rewrite the original". Clause (b) refuses it.
    pytest.param("A B C", "B A X C", "moves_slides", id="c1-swap-first-two-then-insert"),
    pytest.param("A B C D", "A C B X D", "moves_slides", id="c1-swap-middle-two-then-insert"),
    pytest.param("A B C D", "X B A C D", "moves_slides", id="c1-insert-at-0-and-swap"),
]


@pytest.mark.parametrize("old_tokens, new_tokens, code", REFUSED)
def test_refusal(old_tokens, new_tokens, code):
    with pytest.raises(AlignmentRefused) as refused:
        align_slides(_deck(old_tokens), _deck(new_tokens))

    assert refused.value.code == code


def test_reorder_plus_insert_is_refused():
    """The plan asserts only that it is refused, not which code."""
    with pytest.raises(AlignmentRefused) as refused:
        align_slides(_deck("A B C"), _deck("C B A X"))

    assert refused.value.code in REFUSAL_CODES


def test_a_refusal_is_a_value_error_carrying_its_code():
    refusal = AlignmentRefused("moves_slides", "slide B moved")

    assert isinstance(refusal, ValueError)
    assert refusal.code == "moves_slides"


# ---------------------------------------------------------------------------
# slide_key
# ---------------------------------------------------------------------------


def test_slide_key_ignores_position():
    assert slide_key(_slide("A", 0)) == slide_key(_slide("A", 7))


@pytest.mark.parametrize("field", ["template_section_index", "slide_type"])
def test_slide_key_treats_an_absent_optional_field_like_none(field):
    fields = {k: v for k, v in _base_fields("A").items() if k != field}
    absent = SlideSpec.model_validate({"position": 0, **fields})
    explicit = SlideSpec.model_validate({"position": 0, **fields, field: None})

    assert slide_key(absent) == slide_key(explicit)


@pytest.mark.parametrize("field", COMPARED_FIELDS)
def test_slide_key_changes_with_every_field_but_position(field):
    suffix = next(s for s, f in _SUFFIX_FIELD.items() if f == field)

    assert slide_key(_slide(f"A~{suffix}", 0)) != slide_key(_slide("A", 0))


def test_slide_key_is_sorted_json_of_the_slide_without_position():
    slide = _slide("A~slide_type+template_section_index", 3)

    decoded = json.loads(slide_key(slide))

    assert decoded == slide.model_dump(exclude={"position"})
    assert list(decoded) == sorted(decoded)

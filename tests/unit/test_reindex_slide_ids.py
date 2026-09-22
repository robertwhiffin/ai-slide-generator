"""`_reindex_slide_ids` — the invariant it owes, asserted directly.

NOTHING TESTED THIS FUNCTION BEFORE, and that is how the defect shipped.
`tests/integration/test_slide_row_identity_and_verdicts.py` already asserted that a
reorder moves each `slide_id` with its slide — but it drives
`SessionManager.save_slide_deck` directly, one layer BENEATH
`chat_service._reindex_slide_ids`, which rewrote every id to `slide_<index>` before
the deck ever reached that layer.  So the F1/F2 guard was real and passing while the
property it guarded was destroyed by the caller above it.

The contract is now **uniqueness, plus never taking an id away from a slide**:

* uniqueness is what the function's original docstring purpose needs (no duplicate
  React keys in the thumbnail panel), and `ThumbnailRibbon.tsx` additionally uses
  `slide_id` as the dnd-kit sortable item id, where a collision breaks sorting;
* durability is what `_attribute_slide_records` pass 1, `SlideViewer.tsx`'s
  verification Map and `AppLayout.tsx`'s cross-version `findIndex` all read.

Sequentiality is NOT part of the contract: nothing in `src/` or `frontend/src` parses
an index out of a slide_id.
"""
from __future__ import annotations

from src.api.services.chat_service import ChatService
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck


def _deck(*slide_ids) -> SlideDeck:
    """A deck whose slides carry the given ids and DISTINCT html.

    Distinct html matters: it lets an assertion say which slide kept which id,
    rather than only that the set of ids is right.
    """
    return SlideDeck(
        slides=[
            Slide(html=f'<div class="slide">body {n}</div>', slide_id=sid)
            for n, sid in enumerate(slide_ids)
        ]
    )


def _ids(deck: SlideDeck):
    return [s.slide_id for s in deck.slides]


def _by_body(deck: SlideDeck):
    """{slide body -> its id}, so durability is asserted per SLIDE."""
    return {s.html: s.slide_id for s in deck.slides}


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def test_existing_unique_ids_are_left_alone():
    """The whole point. An id a slide has is an id it keeps."""
    deck = _deck("alpha", "beta", "gamma")
    before = _by_body(deck)

    ChatService._reindex_slide_ids(deck)

    assert _by_body(deck) == before, (
        "a slide's id was rewritten even though it was already unique"
    )


def test_reordering_the_list_does_not_renumber_anything():
    """The exact operation that used to destroy identity.

    After the reorder, position 0 holds the slide that was at position 2, and it must
    still be carrying its own id — NOT the id of whatever used to sit at position 0.
    """
    deck = _deck("alpha", "beta", "gamma")
    deck.slides = [deck.slides[2], deck.slides[0], deck.slides[1]]

    ChatService._reindex_slide_ids(deck)

    assert _ids(deck) == ["gamma", "alpha", "beta"], (
        f"ids were renumbered to follow position: {_ids(deck)}"
    )


def test_ids_that_merely_look_positional_are_still_left_alone():
    """`SlideDeck.from_html_string` assigns `slide_<idx>` to freshly parsed slides.

    Those are unique, so they satisfy the contract and must not be touched — and once
    they stop being rewritten they bind to their slide and become real identities.
    Rewriting them "because they look positional" would reintroduce the whole defect
    for every monolith-generated deck, which is where they come from.
    """
    deck = _deck("slide_0", "slide_1", "slide_2")
    deck.slides = [deck.slides[1], deck.slides[0], deck.slides[2]]

    ChatService._reindex_slide_ids(deck)

    assert _ids(deck) == ["slide_1", "slide_0", "slide_2"], (
        f"positional-looking ids were renumbered back to their positions: {_ids(deck)}"
    )


# ---------------------------------------------------------------------------
# Uniqueness — the invariant that replaced sequentiality
# ---------------------------------------------------------------------------


def test_a_duplicate_id_is_broken_and_the_first_holder_keeps_it():
    """A collision must be resolved, and resolved in ONE direction.

    `Slide.clone()` copies slide_id, so a clone arrives colliding with its source.
    The earlier slide keeps the id and the later one is given a new identity: two
    slides sharing one id would break the thumbnail panel's keys and dnd-kit's
    sorting, and `_attribute_slide_records` pass 1 SKIPS an ambiguous id, so both
    slides would lose their verdict rather than one.
    """
    deck = _deck("alpha", "alpha", "beta")

    ChatService._reindex_slide_ids(deck)

    ids = _ids(deck)
    assert len(set(ids)) == 3, f"the collision was not resolved: {ids}"
    assert ids[0] == "alpha", f"the FIRST holder should keep the id: {ids}"
    assert ids[1] not in ("alpha", "beta"), (
        f"the colliding slide got an id that is not its own: {ids}"
    )
    assert ids[2] == "beta", f"an uninvolved slide was disturbed: {ids}"


def test_a_missing_id_is_minted():
    """Legacy decks store `slide_id: null` widely, and a fresh Slide() has None."""
    deck = _deck("alpha", None, "beta")

    ChatService._reindex_slide_ids(deck)

    ids = _ids(deck)
    assert all(ids), f"a slide was left with no id: {ids}"
    assert len(set(ids)) == 3, f"minting produced a collision: {ids}"
    assert ids[0] == "alpha" and ids[2] == "beta"


def test_a_blank_id_counts_as_missing():
    """An empty or whitespace-only id is not an identity, whatever the column says."""
    deck = _deck("alpha", "", "   ")

    ChatService._reindex_slide_ids(deck)

    ids = _ids(deck)
    assert all(i and i.strip() for i in ids), f"a blank id survived: {ids}"
    assert len(set(ids)) == 3, f"minting produced a collision: {ids}"


def test_every_slide_of_an_entirely_idless_deck_gets_its_own_id():
    deck = _deck(None, None, None)

    ChatService._reindex_slide_ids(deck)

    ids = _ids(deck)
    assert all(ids)
    assert len(set(ids)) == 3, f"idless slides were given colliding ids: {ids}"


def test_minted_ids_are_not_positional():
    """A minted id must not be `slide_<idx>`.

    Minting positionally would look harmless on a fresh deck and then collide with —
    or silently impersonate — a slide that legitimately carries that id, which is how
    the original defect did its damage.
    """
    deck = _deck(None, None, None)

    ChatService._reindex_slide_ids(deck)

    assert not any(i.startswith("slide_") for i in _ids(deck)), (
        f"minted ids are positional again: {_ids(deck)}"
    )


def test_the_function_is_idempotent():
    """Calling it twice must not change anything the first call settled.

    It runs after every list mutation, so a second pass over a deck it has already
    normalised has to be a no-op — otherwise ids would churn on every save.
    """
    deck = _deck("alpha", "alpha", None)

    ChatService._reindex_slide_ids(deck)
    first = _by_body(deck)
    ChatService._reindex_slide_ids(deck)

    assert _by_body(deck) == first, (
        f"a second pass changed the ids: {first} -> {_by_body(deck)}"
    )


def test_an_empty_deck_does_not_raise():
    deck = SlideDeck(slides=[])
    ChatService._reindex_slide_ids(deck)
    assert deck.slides == []

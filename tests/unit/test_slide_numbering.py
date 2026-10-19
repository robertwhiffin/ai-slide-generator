"""Contract for ``src.domain.slide_numbering`` (issue #313, acceptance A2).

The user's slide numbers ("slide 2", "the second slide", "the last slide",
"slides 2-4") resolve to ``SlideSpec.position`` deterministically, so the
architect copies positions instead of computing them (known failure: "slide 2"
read as 0-indexed, giving position 2 instead of 1).

These tables ARE the reference grammar (plan D1, D3, D4, D5). Issue #314
(insert a slide) builds on it, so every deliberately unresolved form is pinned
here too: extending the grammar must be a deliberate, test-visible change.

Conventions:
- D1: slide N is the N-th DISTINCT position in ascending order, never N - 1.
- Every resolved row asserts the FULL list of
  ``(text, slide_numbers, positions, out_of_range)`` tuples, in order of
  appearance. ``text`` is the exact matched substring (case kept, no leading
  "the"), so a matcher that over- or under-consumes fails.
- The default deck is positions 0-9 (10 slides).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.domain.slide_numbering import (
    MAX_RANGE_SPAN,
    architect_slide_payload,
    edit_ignores_references,
    latest_user_message,
    resolve_slide_references,
    slide_numbering,
)

MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "domain" / "slide_numbering.py"

DECK10 = list(range(10))
DECK25 = list(range(25))
GAPPED = [0, 2, 5]

REFERENCE_KEYS = {"text", "slide_numbers", "positions", "out_of_range"}
NUMBERING_KEYS = {"slide_number", "position"}

CARDINAL_WORDS = [
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty",
]
ORDINAL_WORDS = [
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
    "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth",
]


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_int_list(value) -> None:
    assert type(value) is list, f"expected a plain list, got {type(value).__name__}"
    for item in value:
        assert type(item) is int, f"expected int items, got {type(item).__name__}"


def _assert_reference_shape(ref) -> None:
    assert type(ref) is dict, f"a reference must be a plain dict, got {type(ref).__name__}"
    assert set(ref) == REFERENCE_KEYS
    assert type(ref["text"]) is str
    _assert_int_list(ref["slide_numbers"])
    _assert_int_list(ref["positions"])
    _assert_int_list(ref["out_of_range"])


def _resolved(text, positions) -> list[tuple]:
    """Resolve, check the JSON-ready shape of every entry, return comparable tuples."""
    refs = resolve_slide_references(text, positions)
    assert type(refs) is list
    for ref in refs:
        _assert_reference_shape(ref)
    return [(r["text"], r["slide_numbers"], r["positions"], r["out_of_range"]) for r in refs]


def _params(rows):
    return [pytest.param(*row, id=repr(row[0])) for row in rows]


def _user(content: str) -> dict[str, str]:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict[str, str]:
    return {"role": "assistant", "content": content}


# ---------------------------------------------------------------------------
# The four A2 phrases (named, so a regression names the acceptance criterion)
# ---------------------------------------------------------------------------


def test_a2_slide_2_resolves_to_position_1():
    assert _resolved("slide 2", DECK10) == [("slide 2", [2], [1], [])]


def test_a2_the_second_slide_resolves_to_position_1():
    assert _resolved("the second slide", DECK10) == [("second slide", [2], [1], [])]


@pytest.mark.parametrize("count", [1, 6, 10, 24])
def test_a2_the_last_slide_resolves_to_count_minus_1(count):
    positions = list(range(count))
    assert _resolved("the last slide", positions) == [
        ("last slide", [count], [count - 1], [])
    ]


def test_a2_slides_2_to_4_resolve_to_positions_1_2_3():
    assert _resolved("slides 2-4", DECK10) == [("slides 2-4", [2, 3, 4], [1, 2, 3], [])]


# ---------------------------------------------------------------------------
# Resolved: singles (F1)
# ---------------------------------------------------------------------------

SINGLES = [
    ("slide 2", DECK10, [("slide 2", [2], [1], [])]),
    ("Slide 2", DECK10, [("Slide 2", [2], [1], [])]),  # text keeps its case
    ("slide #2", DECK10, [("slide #2", [2], [1], [])]),
    ("slide number 2", DECK10, [("slide number 2", [2], [1], [])]),
    ("slide two", DECK10, [("slide two", [2], [1], [])]),
    ("slide 10", DECK10, [("slide 10", [10], [9], [])]),
    ("slide twenty", DECK25, [("slide twenty", [20], [19], [])]),
    # Reported, never clamped.
    ("slide 11", DECK10, [("slide 11", [11], [], [11])]),
    ("slide 0", DECK10, [("slide 0", [0], [], [0])]),
    ("slide 100", DECK10, [("slide 100", [100], [], [100])]),  # 3 digits
    # Embedded in a sentence: text is the substring, not the whole message.
    ("Please shorten slide 2 today", DECK10, [("slide 2", [2], [1], [])]),
    ("Change slide 2's title", DECK10, [("slide 2", [2], [1], [])]),
]


@pytest.mark.parametrize("text,positions,expected", _params(SINGLES))
def test_singles(text, positions, expected):
    assert _resolved(text, positions) == expected


# Every cardinal word one..twenty, so prefix collisions (six/sixteen,
# seven/seventeen) cannot hide.
@pytest.mark.parametrize("number,word", list(enumerate(CARDINAL_WORDS, start=1)), ids=CARDINAL_WORDS)
def test_every_cardinal_word(number, word):
    assert _resolved(f"slide {word}", DECK25) == [(f"slide {word}", [number], [number - 1], [])]


# ---------------------------------------------------------------------------
# Resolved: singular lists (F1 takes and/& lists, NOT bare commas, NOT to-ranges)
# ---------------------------------------------------------------------------

SINGULAR_LISTS = [
    ("slide 2 and 3", DECK10, [("slide 2 and 3", [2, 3], [1, 2], [])]),
    ("slide 2 & 3", DECK10, [("slide 2 & 3", [2, 3], [1, 2], [])]),
    ("On slide 2, 3 cards instead of a list", DECK10, [("slide 2", [2], [1], [])]),
    ("move slide 2 to 5", DECK10, [("slide 2", [2], [1], [])]),
    # F1 ITEM may be a digit dash range, inside an and-list too.
    ("slide 2-4 and 6", DECK10, [("slide 2-4 and 6", [2, 3, 4, 6], [1, 2, 3, 5], [])]),
]


@pytest.mark.parametrize("text,positions,expected", _params(SINGULAR_LISTS))
def test_singular_lists(text, positions, expected):
    assert _resolved(text, positions) == expected


# ---------------------------------------------------------------------------
# Resolved: ordinals (F4), including relative ordinals and digit suffixes
# ---------------------------------------------------------------------------

ORDINALS = [
    ("the second slide", DECK10, [("second slide", [2], [1], [])]),
    ("the 2nd slide", DECK10, [("2nd slide", [2], [1], [])]),
    ("the first slide", DECK10, [("first slide", [1], [0], [])]),
    ("the 1st slide", DECK10, [("1st slide", [1], [0], [])]),
    ("the 3rd slide", DECK10, [("3rd slide", [3], [2], [])]),
    ("the 4th slide", DECK10, [("4th slide", [4], [3], [])]),
    # Definite form after an earlier indefinite article is still a reference.
    ("Add a chart to the second slide", DECK10, [("second slide", [2], [1], [])]),
    # last / final = the slide count.
    ("last slide: drop the cards", DECK10, [("last slide", [10], [9], [])]),
    ("the last slide", DECK10, [("last slide", [10], [9], [])]),
    ("the final slide", DECK10, [("final slide", [10], [9], [])]),
    ("The Last Slide needs work", DECK10, [("Last Slide", [10], [9], [])]),
    # count - 1; the longest form wins ("second-to-last" beats "second" and "last").
    ("the penultimate slide", DECK10, [("penultimate slide", [9], [8], [])]),
    ("the second-to-last slide", DECK10, [("second-to-last slide", [9], [8], [])]),
    ("the second to last slide", DECK10, [("second to last slide", [9], [8], [])]),
    ("the second last slide", DECK10, [("second last slide", [9], [8], [])]),
    ("the second-last slide", DECK10, [("second-last slide", [9], [8], [])]),
    # Out of range is reported.
    ("the twelfth slide", DECK10, [("twelfth slide", [12], [], [12])]),
    # Suffix is not checked against the number: 11th-13th and 21st-23rd all accepted.
    ("the 11th slide", DECK25, [("11th slide", [11], [10], [])]),
    ("the 12th slide", DECK25, [("12th slide", [12], [11], [])]),
    ("the 13th slide", DECK25, [("13th slide", [13], [12], [])]),
    ("the 21st slide", DECK25, [("21st slide", [21], [20], [])]),
    ("the 22nd slide", DECK25, [("22nd slide", [22], [21], [])]),
    ("the 23rd slide", DECK25, [("23rd slide", [23], [22], [])]),
    # Count-relative ordinals on tiny decks: still reported, never clamped.
    ("the last slide", [0], [("last slide", [1], [0], [])]),
    ("the penultimate slide", [0], [("penultimate slide", [0], [], [0])]),
]


@pytest.mark.parametrize("text,positions,expected", _params(ORDINALS))
def test_ordinals(text, positions, expected):
    assert _resolved(text, positions) == expected


# Every ordinal word first..twentieth (fourth/fourteenth etc. cannot collide).
@pytest.mark.parametrize("number,word", list(enumerate(ORDINAL_WORDS, start=1)), ids=ORDINAL_WORDS)
def test_every_ordinal_word(number, word):
    assert _resolved(f"the {word} slide", DECK25) == [(f"{word} slide", [number], [number - 1], [])]


# ---------------------------------------------------------------------------
# Resolved: plural ranges and lists (F3)
# ---------------------------------------------------------------------------

_TWO_TO_FOUR = ([2, 3, 4], [1, 2, 3], [])

PLURALS = [
    ("slides 2-4", DECK10, [("slides 2-4", *_TWO_TO_FOUR)]),
    ("slides 2–4", DECK10, [("slides 2–4", *_TWO_TO_FOUR)]),  # en dash
    ("slides 2—4", DECK10, [("slides 2—4", *_TWO_TO_FOUR)]),  # em dash
    ("slides 2 - 4", DECK10, [("slides 2 - 4", *_TWO_TO_FOUR)]),
    ("slides 2 to 4", DECK10, [("slides 2 to 4", *_TWO_TO_FOUR)]),
    ("slides 2 through 4", DECK10, [("slides 2 through 4", *_TWO_TO_FOUR)]),
    ("slides 2 thru 4", DECK10, [("slides 2 thru 4", *_TWO_TO_FOUR)]),
    ("slide 2-4", DECK10, [("slide 2-4", *_TWO_TO_FOUR)]),
    ("slides 4-2", DECK10, [("slides 4-2", *_TWO_TO_FOUR)]),  # either order
    # Dash ranges take digits only; to/through ranges take number words.
    ("slides two to four", DECK10, [("slides two to four", *_TWO_TO_FOUR)]),
    ("slides 2 and 3", DECK10, [("slides 2 and 3", [2, 3], [1, 2], [])]),
    ("slides 2 & 3", DECK10, [("slides 2 & 3", [2, 3], [1, 2], [])]),
    ("slides two and three", DECK10, [("slides two and three", [2, 3], [1, 2], [])]),
    ("slides 2, 3 and 5", DECK10, [("slides 2, 3 and 5", [2, 3, 5], [1, 2, 4], [])]),
    ("slides 2, 3, and 5", DECK10, [("slides 2, 3, and 5", [2, 3, 5], [1, 2, 4], [])]),
    ("slides 2-4 and 6", DECK10, [("slides 2-4 and 6", [2, 3, 4, 6], [1, 2, 3, 5], [])]),
    ("slides 9-12", DECK10, [("slides 9-12", [9, 10, 11, 12], [8, 9], [11, 12])]),
    # slide_numbers sorted and deduplicated; positions follow; out_of_range sorted.
    ("slides 5 and 2", DECK10, [("slides 5 and 2", [2, 5], [1, 4], [])]),
    ("slides 2-4 and 3", DECK10, [("slides 2-4 and 3", [2, 3, 4], [1, 2, 3], [])]),
    ("slides 12, 0 and 3", DECK10, [("slides 12, 0 and 3", [0, 3, 12], [2], [0, 12])]),
    # A separator not followed by an ITEM is not consumed.
    ("On slides 2, the chart is wrong", DECK10, [("slides 2", [2], [1], [])]),
    ("SLIDES 2-4", DECK10, [("SLIDES 2-4", *_TWO_TO_FOUR)]),
    # Exactly MAX_RANGE_SPAN (100) numbers is kept; more is dropped (see NO_REFERENCE).
    (
        "slides 1-100",
        DECK10,
        [("slides 1-100", list(range(1, 101)), list(range(10)), list(range(11, 101)))],
    ),
]


@pytest.mark.parametrize("text,positions,expected", _params(PLURALS))
def test_plural_ranges_and_lists(text, positions, expected):
    assert _resolved(text, positions) == expected


def test_max_range_span_is_100():
    assert MAX_RANGE_SPAN == 100


# ---------------------------------------------------------------------------
# Resolved: several references, separators, the pinned known limit
# ---------------------------------------------------------------------------

SEVERAL = [
    (
        "make slide 3 match slide 2",
        DECK10,
        [("slide 3", [3], [2], []), ("slide 2", [2], [1], [])],
    ),
    (
        "slide 2 and slide 4",
        DECK10,
        [("slide 2", [2], [1], []), ("slide 4", [4], [3], [])],
    ),
    ("slides 2 and the cover", DECK10, [("slides 2", [2], [1], [])]),
    # "or" is not a separator.
    ("slides 2 or 3", DECK10, [("slides 2", [2], [1], [])]),
    (
        "Swap the first slide with slides 3-4",
        DECK10,
        [("first slide", [1], [0], []), ("slides 3-4", [3, 4], [2, 3], [])],
    ),
    (
        "make the last slide match slide 2",
        DECK10,
        [("last slide", [10], [9], []), ("slide 2", [2], [1], [])],
    ),
    # A list item that is the head of a failed dash range is not consumed; the
    # items before it stand (5 is never read as a lone number).
    ("slides 2 and 5-1000", DECK10, [("slides 2", [2], [1], [])]),
    ("slide 2 and 5-1000", DECK10, [("slide 2", [2], [1], [])]),
    # Controls: the dash guard does not eat a trailing dash or a dash then text.
    ("On slide 2 - the chart is wrong", DECK10, [("slide 2", [2], [1], [])]),
    ("slides 5- and 6", DECK10, [("slides 5", [5], [4], [])]),
    # Controls: the count-relative tail exclusion does not eat definite "last".
    ("put it next to the last slide", DECK10, [("last slide", [10], [9], [])]),
    ("Add a chart to the last slide", DECK10, [("last slide", [10], [9], [])]),
    (
        "Move the chart from the second slide to the last slide",
        DECK10,
        [("second slide", [2], [1], []), ("last slide", [10], [9], [])],
    ),
    ("Make one more pass on the final slide", DECK10, [("final slide", [10], [9], [])]),
    # The exclusions look back a bounded window; a window that starts inside a
    # word ("banana") must not read its tail "a" as the article.
    ("banana" + " " * 63 + "final slide", DECK10, [("final slide", [10], [9], [])]),
]


@pytest.mark.parametrize("text,positions,expected", _params(SEVERAL))
def test_several_references_in_order_of_appearance(text, positions, expected):
    assert _resolved(text, positions) == expected


def test_known_limit_bare_comma_plural_resolves_both_numbers():
    """PINNED KNOWN LIMIT (D3): a bare-comma plural reads the count as a slide.

    "On slides 2, 3 bullets each" means slide 2 with 3 bullets, but F3 accepts
    "," as a separator, so it resolves [2, 3]. Changing this is a deliberate
    grammar change.
    """
    assert _resolved("On slides 2, 3 bullets each", DECK10) == [
        ("slides 2, 3", [2, 3], [1, 2], [])
    ]


# The issue #313 train eval messages (plan D6) resolve to their expected targets.
TRAIN_MESSAGES = [
    ("Could you make the second slide less wordy?", DECK10, [("second slide", [2], [1], [])]),
    (
        "Simplify the last slide: drop the stat cards and keep just the verdict and the call to action",
        DECK10,
        [("last slide", [10], [9], [])],
    ),
    (
        "Slides 4-6 are too text-heavy; trim each to three short bullets",
        DECK10,
        [("Slides 4-6", [4, 5, 6], [3, 4, 5], [])],
    ),
    ("Why is the accessibility point on slide 7?", DECK10, [("slide 7", [7], [6], [])]),
]


@pytest.mark.parametrize("text,positions,expected", _params(TRAIN_MESSAGES))
def test_train_eval_messages(text, positions, expected):
    assert _resolved(text, positions) == expected


# ---------------------------------------------------------------------------
# No reference
# ---------------------------------------------------------------------------

NO_REFERENCE = [
    # Indefinite ordinals name a slide that does not exist yet (#314 owns add/insert).
    ("Add a final slide with next steps", DECK10),
    ("add a second slide on pricing", DECK10),
    ("I need a third slide for the roadmap", DECK10),
    ("add another final slide", DECK10),
    ("an extra second slide", DECK10),
    ("one more final slide", DECK10),
    ("a new third slide", DECK10),
    ("an additional 4th slide", DECK10),
    ("ADD A FINAL SLIDE", DECK10),  # the exclusion is case-insensitive too
    ("Add one last slide with next steps", DECK10),
    ("add one final slide", DECK10),
    # Unhyphenated count-relative ordinals: "last slide" is their tail, not slide N.
    ("Simplify the next to last slide", DECK10),
    ("the third to last slide", DECK10),
    ("the second from last slide", DECK10),
    ("the second to the last slide", DECK10),
    ("the 3rd from the last slide", DECK10),
    ("the 2nd to last slide", DECK10),
    ("The Third To Last Slide", DECK10),
    ("the third to final slide", DECK10),
    # Hyphenated number/ordinal words are never misread as their tail or head.
    ("the twenty-first slide", DECK25),
    ("the thirty-second slide", DECK25),
    ("slide twenty-one", DECK25),
    ("the last-but-one slide", DECK10),
    ("slides two-four", DECK10),  # dash ranges take digits only
    # A range spanning more than MAX_RANGE_SPAN numbers drops the WHOLE reference.
    ("slides 1-200", DECK10),
    ("slides 1-101", DECK10),
    ("slides 2 and 5-500", DECK10),
    # A digit then a dash and a digit is only ever a range: when the range fails
    # the item grammar (a 4-digit end), it never degrades to the lone first number.
    ("slides 1-1000", DECK10),
    ("slide 2-1000", DECK10),
    ("slides 2-1000", DECK10),
    ("slide 1-1000", DECK10),
    ("slide 12-1000", DECK10),
    ("slides 1 - 1000", DECK10),
    ("slides 1–1000", DECK10),
    ("slides 999-1001", DECK10),
    ("slides 1-10000", DECK10),
    ("slides 1-1000 and 3", DECK10),
    # Slide counts.
    ("a 10-slide deck", DECK10),
    ("10 slides", DECK10),
    ("Build five slides about X", DECK10),
    # Count-relative plurals and plural ordinals.
    ("the last two slides", DECK10),
    ("the first three slides", DECK10),
    ("the second and third slides", DECK10),
    # Deictic and semantic phrases.
    ("this slide", DECK10),
    ("the next slide", DECK10),
    ("a new slide", DECK10),
    ("the cover", DECK10),
    ("the agenda slide", DECK10),
    # Not the word "slide(s)" at word boundaries.
    ("slideshow", DECK10),
    ("Slidev", DECK10),
    ("play the slideshow 2 times", DECK10),
    ("export it as a Slidev 2 deck", DECK10),
    ("won by a landslide 2 to 1", DECK10),
    ("slides", DECK10),
    ("", DECK10),
    (None, DECK10),
]


@pytest.mark.parametrize("text,positions", _params(NO_REFERENCE))
def test_no_reference(text, positions):
    assert _resolved(text, positions) == []


# ---------------------------------------------------------------------------
# Numbering (D1): slide N is the N-th distinct position, ascending
# ---------------------------------------------------------------------------


def _numbering_pairs(numbering) -> list[tuple[int, int]]:
    assert type(numbering) is list
    for entry in numbering:
        assert type(entry) is dict
        assert set(entry) == NUMBERING_KEYS
        assert type(entry["slide_number"]) is int
        assert type(entry["position"]) is int
    return [(e["slide_number"], e["position"]) for e in numbering]


def test_slide_numbering_is_distinct_positions_ascending():
    assert slide_numbering([5, 0, 2, 2]) == [
        {"slide_number": 1, "position": 0},
        {"slide_number": 2, "position": 2},
        {"slide_number": 3, "position": 5},
    ]
    assert _numbering_pairs(slide_numbering([5, 0, 2, 2])) == [(1, 0), (2, 2), (3, 5)]


def test_slide_numbering_contiguous_deck():
    assert _numbering_pairs(slide_numbering(DECK10)) == [(n + 1, n) for n in range(10)]


def test_slide_numbering_accepts_any_iterable():
    assert _numbering_pairs(slide_numbering(p for p in (3, 1))) == [(1, 1), (2, 3)]


def test_slide_numbering_empty_deck():
    assert slide_numbering([]) == []


GAPPED_ROWS = [
    ("slide 2", GAPPED, [("slide 2", [2], [2], [])]),
    ("slide 3", GAPPED, [("slide 3", [3], [5], [])]),
    ("the last slide", GAPPED, [("last slide", [3], [5], [])]),
    ("slide 4", GAPPED, [("slide 4", [4], [], [4])]),
    ("the penultimate slide", GAPPED, [("penultimate slide", [2], [2], [])]),
    ("slides 1-3", GAPPED, [("slides 1-3", [1, 2, 3], [0, 2, 5], [])]),
    # Unsorted, duplicated positions are numbered as their distinct ascending set.
    ("slide 1", [5, 0, 2, 2], [("slide 1", [1], [0], [])]),
    ("slide 3", [5, 0, 2, 2], [("slide 3", [3], [5], [])]),
]


@pytest.mark.parametrize("text,positions,expected", _params(GAPPED_ROWS))
def test_gapped_and_unordered_decks_map_through_numbering(text, positions, expected):
    assert _resolved(text, positions) == expected


def test_resolve_accepts_any_iterable_of_positions():
    assert _resolved("slide 2", (p for p in (0, 1, 2))) == [("slide 2", [2], [1], [])]


@pytest.mark.parametrize("text", ["slide 2", "the last slide", "slides 2-4"])
def test_empty_deck_resolves_nothing(text):
    assert resolve_slide_references(text, []) == []


# ---------------------------------------------------------------------------
# JSON-ready result shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "slide 2",
        "make slide 3 match slide 2",
        "slides 9-12",
        "the last slide",
        "slides 12, 0 and 3",
    ],
)
def test_references_are_json_ready(text):
    refs = resolve_slide_references(text, DECK10)
    assert refs, "row must resolve for this shape check to mean anything"
    for ref in refs:
        _assert_reference_shape(ref)
    assert json.loads(json.dumps(refs)) == refs


def test_numbering_is_json_ready():
    numbering = slide_numbering([5, 0, 2])
    _numbering_pairs(numbering)
    assert json.loads(json.dumps(numbering)) == numbering


# ---------------------------------------------------------------------------
# latest_user_message (D4)
# ---------------------------------------------------------------------------


def test_latest_user_message_last_user_turn_wins_over_a_later_assistant_turn():
    conversation = [_user("Put our figures on slide 4"), _assistant("Sure, which figures?")]
    assert latest_user_message(conversation, "Q3 revenue was 10") == "Put our figures on slide 4"


def test_latest_user_message_takes_the_last_of_several_user_turns():
    conversation = [_user("first ask"), _assistant("done"), _user("second ask"), _assistant("ok")]
    assert latest_user_message(conversation, "fallback") == "second ask"


@pytest.mark.parametrize(
    "conversation",
    [
        pytest.param([_assistant("hello")], id="no-user-turn"),
        pytest.param([], id="empty"),
        pytest.param(None, id="none"),
    ],
)
def test_latest_user_message_falls_back_to_message(conversation):
    assert latest_user_message(conversation, "Make slide 2 shorter") == "Make slide 2 shorter"


def test_latest_user_message_none_when_nothing_to_fall_back_to():
    assert latest_user_message(None, None) is None
    assert latest_user_message([_assistant("hello")], None) is None


NON_STRING_CONTENT = [
    pytest.param(None, id="none"),
    pytest.param([{"type": "text", "text": "Make slide 2 shorter"}], id="content-blocks"),
    pytest.param(["Make slide 2 shorter"], id="list-of-str"),
    pytest.param({"text": "Make slide 2 shorter"}, id="dict"),
    pytest.param(42, id="int"),
]


@pytest.mark.parametrize("content", NON_STRING_CONTENT)
def test_latest_user_message_non_string_content_falls_back_never_to_an_older_turn(content):
    conversation = [
        _user("Put our figures on slide 4"),  # older user turn: stale, must not be used
        _assistant("done"),
        {"role": "user", "content": content},
    ]
    assert latest_user_message(conversation, "Make slide 3 shorter") == "Make slide 3 shorter"


@pytest.mark.parametrize("content", NON_STRING_CONTENT)
def test_architect_slide_payload_survives_non_string_content(content):
    payload = architect_slide_payload(
        [{"role": "user", "content": content}], "Make slide 3 shorter", [0, 1, 2]
    )
    assert payload["slide_references"] == [
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []}
    ]
    assert _numbering_pairs(payload["slide_numbering"]) == [(1, 0), (2, 1), (3, 2)]


# ---------------------------------------------------------------------------
# architect_slide_payload: the one helper node, generators and tests call
# ---------------------------------------------------------------------------


def test_architect_slide_payload_resolves_latest_user_turn_not_message():
    payload = architect_slide_payload(
        [_user("Make slide 2 shorter"), _assistant("On it")],
        "Q3 revenue was 10 on slide 3",
        [0, 1, 2],
    )
    assert set(payload) == {"slide_numbering", "slide_references"}
    assert _numbering_pairs(payload["slide_numbering"]) == [(1, 0), (2, 1), (3, 2)]
    assert payload["slide_references"] == [
        {"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []}
    ]
    assert json.loads(json.dumps(payload)) == payload


def test_architect_slide_payload_falls_back_to_message_without_a_user_turn():
    payload = architect_slide_payload(None, "Make slide 3 shorter", [0, 1, 2])
    assert payload["slide_references"] == [
        {"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []}
    ]


def test_architect_slide_payload_describe_only_sends_no_references_but_keeps_numbering():
    conversation = [_user("Make slide 2 shorter")]
    sweeper_text = "Describe the deck as it now stands after the hand edit."
    normal = architect_slide_payload(conversation, sweeper_text, [0, 1, 2])
    describe = architect_slide_payload(conversation, sweeper_text, [0, 1, 2], describe_only=True)
    assert normal["slide_references"], "control: the same inputs resolve when not describe-only"
    assert set(describe) == {"slide_numbering", "slide_references"}
    assert describe["slide_references"] == []
    assert describe["slide_numbering"] == normal["slide_numbering"] == slide_numbering([0, 1, 2])


def test_architect_slide_payload_no_deck_sends_empty_lists():
    assert architect_slide_payload([_user("Make slide 2 shorter")], "Make slide 2 shorter", []) == {
        "slide_numbering": [],
        "slide_references": [],
    }


# ---------------------------------------------------------------------------
# edit_ignores_references (D5, the log-only guard)
# ---------------------------------------------------------------------------

GUARD_ROWS = [
    pytest.param([2], "slide 2", True, id="targets-2-vs-slide-2-pos-1"),
    pytest.param([1], "slide 2", False, id="targets-1-vs-slide-2"),
    pytest.param([1, 7], "slide 2", False, id="any-overlap-is-not-ignoring"),
    pytest.param([2], "make slide 3 match slide 2", False, id="targets-2-vs-two-refs"),
    pytest.param([2], "slide 11", False, id="only-out-of-range-refs"),
    pytest.param([5], "slides 9-12", True, id="in-range-part-of-a-partly-out-of-range-ref"),
    pytest.param([2], "Make it shorter", False, id="no-references"),
]


@pytest.mark.parametrize("targets,text,expected", GUARD_ROWS)
def test_edit_ignores_references(targets, text, expected):
    references = resolve_slide_references(text, DECK10)
    assert edit_ignores_references(targets, references) is expected


def test_edit_ignores_references_with_an_empty_reference_list():
    assert edit_ignores_references([2], []) is False


# ---------------------------------------------------------------------------
# Module hygiene: pure, and documents the grammar #314 builds on
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS = {"__future__", "re", "typing"}


def test_module_imports_only_future_re_and_typing():
    tree = ast.parse(MODULE_PATH.read_text(), filename=str(MODULE_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add(node.module or "")
    assert imported, "expected at least `import re`"
    assert imported <= ALLOWED_IMPORTS, f"disallowed imports: {sorted(imported - ALLOWED_IMPORTS)}"


def test_module_docstring_documents_the_grammar():
    doc = ast.get_docstring(ast.parse(MODULE_PATH.read_text())) or ""
    lowered = doc.lower()
    for term in ("unresolved", "known limit", "indefinite", "describe"):
        assert term in lowered, f"module docstring must cover {term!r} (plan D1/D3/D4)"

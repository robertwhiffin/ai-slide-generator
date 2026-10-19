"""Deterministic slide numbers: resolve what a user typed to ``SlideSpec.position``.

Users say "slide 2", "the second slide", "the last slide" or "slides 2-4"; the
architect needs ``SlideSpec.position`` values.  Left to the model, "slide 2" is
sometimes read as 0-indexed (position 2 instead of 1).  This module does the
mapping in code, so ``architect_node`` can hand the model positions to copy.
It is pure: no I/O, no state, and it imports only ``re`` and ``typing``.

Issue #314 (insert a slide) builds on the rules below; they are pinned by
``tests/unit/test_slide_numbering.py``.  Extending the grammar is a deliberate,
test-visible change.

D1 - slide number versus position
---------------------------------
Slide N is the N-th slide of the current deck in ascending ``position`` order,
which is the number the slide panel shows.  It is NOT ``N - 1``.  Routes keep
positions contiguous, so normally position == N - 1, but a gapped deck (for
example positions 0, 2, 5) numbers its slides 1, 2, 3 and "slide 3" is
position 5.  Callers pass the positions of the deck as the user sees it
(committed rows when there are any, else the persisted spec's positions).
Duplicate and unordered positions are numbered as their distinct ascending set.

D3 - the reference grammar
--------------------------
Matching is case-insensitive, at word boundaries, left to right without
overlap, and the longest form at a start wins.  ``text`` is the exact matched
substring, without a leading "the".  Numbers are 1-3 digits or the cardinal
words one..twenty; ordinals are 1-3 digits plus ``st``/``nd``/``rd``/``th``
(the suffix is not checked against the number) or the words first..twentieth.
Number and ordinal words refuse a hyphen on either side, so "twenty-one",
"twenty-first" and "thirty-second" are never misread as "one", "first" or
"second".

* F1, singular ``slide``: "slide 2", "slide #2", "slide number 2", "slide two",
  "slide 2-4" (a digit dash range, no spaces), "slide 2 and 3", "slide 2 & 3".
  It takes no bare-comma continuation ("On slide 2, 3 cards ..." is slide 2
  only) and no ``to``/``through`` range ("move slide 2 to 5" is slide 2 only).
* F3, plural ``slides``: items separated by ``,``, ``, and``, ``and`` or ``&``.
  An item is a number, a dash range of digits (en and em dashes too, optional
  spaces around the dash), or two numbers joined by ``to``/``through``/``thru``:
  "slides 2-4", "slides 2 to 4", "slides 2, 3 and 5", "slides 2-4 and 6".
* A lone digit item is never the head of a dash range its form could not read
  (F1: a tight dash; F3: a dash with optional spaces): "slides 1-1000" and
  "slide 2-1000" (a 4-digit end) are no reference, never "slides 1" or
  "slide 2".  In a list such an item is simply not consumed: "slides 2 and
  5-1000" is slides 2.
* F4, an ordinal before the singular ``slide``: "the second slide", "the 4th
  slide", "last slide: ...".  ``last`` and ``final`` are the slide count;
  ``penultimate``, ``second-to-last``, ``second to last``, ``second-last`` and
  ``second last`` are the count minus one.
* Indefinite exclusion: an F4 match immediately preceded by ``a``, ``an``,
  ``another``, ``new``, ``extra``, ``additional``, ``one`` or ``one more`` is
  NOT a reference.  "Add a final slide", "Add one last slide", "I need a third
  slide" and "a new second slide" name a slide that does not exist yet.
  Definite or bare forms ("the last slide", "last slide: ...", "Add a chart to
  the second slide") are references.
* Count-relative tail exclusion: ``last``/``final`` immediately preceded by
  ``next to`` or by an ordinal (second.., 2nd..) plus ``to``/``from`` and an
  optional ``the`` is NOT a reference: in "the third to last slide", "the
  second from the last slide" and "the next to last slide" it is the tail of
  a count-relative ordinal, not the last slide.  "put it next to the last
  slide" is still the last slide.
* Ranges are inclusive and may run in either order.  A range spanning more than
  ``MAX_RANGE_SPAN`` numbers drops the whole reference.

Each reference is ``{"text", "slide_numbers", "positions", "out_of_range"}``.
``slide_numbers`` is sorted and deduplicated; ``positions`` maps the in-range
numbers through D1 in the same order; ``out_of_range`` holds the numbers below 1
or above the slide count, sorted.  Numbers are reported, never clamped.  There
are no references when there is no deck.

Deliberately unresolved (each is tested; the model looks these up in
``slide_numbering`` instead):

* count-relative plurals ("the last two slides") and plural ordinals ("the
  second and third slides");
* count-relative ordinals other than the count-minus-one forms above ("the
  third to last slide", "the second from last slide", "the next to last
  slide", "the 2nd-to-last slide");
* deictic and semantic phrases: "this slide", "the next slide", "the cover",
  "the agenda slide", "a new slide";
* slide counts ("a 10-slide deck", "10 slides", "five slides"), "slideshow",
  "Slidev", and "slides" on its own;
* "or" is not a separator ("slides 2 or 3" is slides 2 only);
* a range spanning more than ``MAX_RANGE_SPAN`` numbers.

Known limit, pinned by a test: a bare-comma plural such as "On slides 2, 3
bullets each" resolves to slides 2 and 3, because F3 accepts a bare comma as a
separator and cannot tell a count from a slide.

References are lexical.  They say which existing slide a phrase names, not that
the user wants it changed or what the phrase means for the edit: "after slide
3" resolves "slide 3", and what the anchor means is issue #314's to decide.

D4 - which text is resolved, and when nothing is
------------------------------------------------
``latest_user_message`` picks the text: the content of the latest turn whose
role is ``user``, falling back to the ``message`` argument when there is none
(or when that turn's content is not a string; an older user turn is never
used).  After the analyst returns, ``message`` is the analyst's synthesis, and the
user's "slide 4" must still resolve.  On a describe-only turn the references
are empty, because the latest user turn predates the hand edit that triggered
the describe, so its "slide 2" may now name a different slide; the numbering is
still sent because it describes the current deck.  ``architect_slide_payload``
is the one helper that builds both payload keys.

D5 - the guard
--------------
``edit_ignores_references`` is true when the references resolve at least one
in-range position and the edit's target positions share none with them.  The
caller only logs it.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

MAX_RANGE_SPAN = 100

# ---------------------------------------------------------------------------
# Word tables
# ---------------------------------------------------------------------------

_CARDINALS = {
    word: number
    for number, word in enumerate(
        (
            "one two three four five six seven eight nine ten eleven twelve thirteen "
            "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
        ).split(),
        start=1,
    )
}
_ORDINALS = {
    word: number
    for number, word in enumerate(
        (
            "first second third fourth fifth sixth seventh eighth ninth tenth eleventh "
            "twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth "
            "nineteenth twentieth"
        ).split(),
        start=1,
    )
}

# ---------------------------------------------------------------------------
# Patterns (compiled once; all matching is case-insensitive)
# ---------------------------------------------------------------------------


def _word(alternatives: str) -> str:
    """Wrap number/ordinal words so a hyphen on either side refuses the match.

    The trailing ``\\b`` stops a short word matching the front of a longer one
    ("six" in "sixteen"); the hyphen guards stop "twenty-one" being read as
    "one" and "twenty-first" as "first".
    """
    return rf"(?<![-\w])(?:{alternatives})\b(?!-[a-z])"


_DIGITS = r"(?<!\d)\d{1,3}(?!\d)"
_DASH = r"[-–—]"
_CARDINAL_WORD = _word("|".join(_CARDINALS))
_NUMBER = rf"(?:{_CARDINAL_WORD}|{_DIGITS})"

# Items: a lone number or a range.  Singular ranges are digits joined by a
# tight dash; plural ranges also allow spaces around the dash and to/through.
_TIGHT_RANGE = rf"{_DIGITS}{_DASH}{_DIGITS}"
_LOOSE_RANGE = rf"{_DIGITS}\s*{_DASH}\s*{_DIGITS}"
_WORD_RANGE = rf"{_NUMBER}\s+(?:to|through|thru)\s+{_NUMBER}"
# A lone digit item is never the head of a dash range its form failed to read:
# "slides 1-1000" (a 4-digit end) is no reference, not "slides 1".
_LONE_SINGULAR = rf"(?:{_CARDINAL_WORD}|{_DIGITS}(?!{_DASH}\d))"
_LONE_PLURAL = rf"(?:{_CARDINAL_WORD}|{_DIGITS}(?!\s*{_DASH}\s*\d))"
_SINGULAR_ITEM = rf"(?:{_TIGHT_RANGE}|{_LONE_SINGULAR})"
_PLURAL_ITEM = rf"(?:{_WORD_RANGE}|{_LOOSE_RANGE}|{_LONE_PLURAL})"

_SINGULAR_SEP = r"(?:\s+and\s+|\s*&\s*)"
_PLURAL_SEP = r"(?:\s*,\s*and\s+|\s*,\s*|\s+and\s+|\s*&\s*)"

# F3: "slides 2-4", "slides 2, 3 and 5".  F1: "slide 2", "slide #2", "slide 2 and 3".
_PLURAL_FORM = rf"\bslides\s+(?P<plural_items>{_PLURAL_ITEM}(?:{_PLURAL_SEP}{_PLURAL_ITEM})*)"
_SINGULAR_FORM = (
    r"\bslide(?:\s+number\s+|\s*#\s*|\s+)"
    rf"(?P<singular_items>{_SINGULAR_ITEM}(?:{_SINGULAR_SEP}{_SINGULAR_ITEM})*)"
)

# F4: an ordinal, then the singular "slide".  Relative ordinals come before the
# plain ones so "second-to-last" is never read as "second".
_JOIN = r"(?:-|\s+)"
_ORDINAL_TOKEN = _word(
    rf"(?P<ordinal_relative>penultimate|second(?:{_JOIN}to)?{_JOIN}last)"
    r"|(?P<ordinal_last>last|final)"
    rf"|(?P<ordinal_word>{'|'.join(_ORDINALS)})"
    r"|(?P<ordinal_digits>\d{1,3})(?:st|nd|rd|th)"
)
_ORDINAL_FORM = rf"(?P<ordinal>{_ORDINAL_TOKEN})\s+slide\b"

# One alternation, tried in this order at each start: F3, then F1, then F4.
_REFERENCE_RE = re.compile(f"{_PLURAL_FORM}|{_SINGULAR_FORM}|{_ORDINAL_FORM}", re.IGNORECASE)

# Used to split a matched item list back into items, and an item into numbers.
_ITEM_RE = re.compile(_PLURAL_ITEM, re.IGNORECASE)
_NUMBER_RE = re.compile(_NUMBER, re.IGNORECASE)

# "a final slide" names a slide that does not exist yet (#314 owns add/insert).
_INDEFINITE_BEFORE_RE = re.compile(
    r"\b(?:a|an|another|new|extra|additional|one(?:\s+more)?)\s+\Z", re.IGNORECASE
)

# "the third to last slide", "the second from the last slide", "the next to last
# slide": "last slide" is the tail of a count-relative ordinal there, not the
# last slide, so it is no reference (the hyphenated spellings are refused by
# the word guards already).
_RELATIVE_TAIL_BEFORE_RE = re.compile(
    r"\b(?:next\s+to"
    rf"|(?:{'|'.join(list(_ORDINALS)[1:])}|\d{{1,3}}(?:st|nd|rd|th))\s+(?:to|from)(?:\s+the)?"
    r")\s+\Z",
    re.IGNORECASE,
)

# The exclusions look only this far back from an ordinal, so a long message with
# many ordinals stays linear.  ``\b`` still sees the character before the window.
_LOOKBACK = 64


# ---------------------------------------------------------------------------
# Numbering and resolution
# ---------------------------------------------------------------------------


def slide_numbering(positions: Iterable[int]) -> list[dict[str, int]]:
    """``[{"slide_number": 1, "position": p0}, ...]`` over the DISTINCT positions, ascending."""
    return [
        {"slide_number": number, "position": position}
        for number, position in enumerate(_ordered_positions(positions), start=1)
    ]


def resolve_slide_references(text: str | None, positions: Iterable[int]) -> list[dict]:
    """Each D3 reference in ``text``, in order of appearance.

    Every entry is ``{"text": str, "slide_numbers": [int], "positions": [int],
    "out_of_range": [int]}``.  The result is ``[]`` when ``text`` is empty or
    ``None`` or when ``positions`` is empty.
    """
    ordered = _ordered_positions(positions)
    if not text or not ordered:
        return []
    references = []
    for match in _REFERENCE_RE.finditer(text):
        if _is_indefinite(text, match):
            continue
        if _is_relative_tail(text, match):
            continue
        numbers = _match_numbers(match, len(ordered))
        if numbers is None:
            continue
        references.append(_build_reference(match.group(0), numbers, ordered))
    return references


def latest_user_message(
    conversation: Sequence[Mapping] | None, fallback: str | None
) -> str | None:
    """Content of the last turn whose role is ``"user"``; ``fallback`` when there is none (D4).

    A latest user turn whose content is not a string (``None``, a list of
    content blocks) also gives ``fallback``: never an older user turn, whose
    slide numbers may be stale.
    """
    for turn in reversed(conversation or ()):
        if turn.get("role") == "user":
            content = turn.get("content")
            return content if isinstance(content, str) else fallback
    return fallback


def architect_slide_payload(
    conversation: Sequence[Mapping] | None,
    message: str | None,
    positions: Iterable[int],
    *,
    describe_only: bool = False,
) -> dict[str, list]:
    """The architect payload's ``slide_numbering`` and ``slide_references`` keys.

    The one helper that ``architect_node``, the eval generators and the agentic
    test payloads all call.  References are resolved from the latest user turn
    (falling back to ``message``) and are ``[]`` on a describe-only turn (D4).
    """
    positions = list(positions)
    references = (
        []
        if describe_only
        else resolve_slide_references(latest_user_message(conversation, message), positions)
    )
    return {
        "slide_numbering": slide_numbering(positions),
        "slide_references": references,
    }


def edit_ignores_references(
    target_positions: Iterable[int], references: Sequence[Mapping]
) -> bool:
    """True iff the references resolve at least one in-range position and
    ``target_positions`` shares none of them (D5)."""
    referenced = {position for reference in references for position in reference["positions"]}
    return bool(referenced) and referenced.isdisjoint(target_positions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ordered_positions(positions: Iterable[int]) -> list[int]:
    """The distinct positions, ascending: ``ordered[n - 1]`` is slide ``n``'s position."""
    return sorted({int(position) for position in positions})


def _is_indefinite(text: str, match: re.Match[str]) -> bool:
    """Whether an F4 match sits right after "a", "another", "new", ... (D3 exclusion)."""
    return match.group("ordinal") is not None and _preceded_by(
        _INDEFINITE_BEFORE_RE, text, match.start()
    )


def _is_relative_tail(text: str, match: re.Match[str]) -> bool:
    """Whether a ``last``/``final`` match ends "third to last", "next to last", ..."""
    return match.group("ordinal_last") is not None and _preceded_by(
        _RELATIVE_TAIL_BEFORE_RE, text, match.start()
    )


def _preceded_by(pattern: re.Pattern[str], text: str, start: int) -> bool:
    """Whether *pattern* (anchored by ``\\Z``) matches the text just before *start*."""
    return pattern.search(text, max(0, start - _LOOKBACK), start) is not None


def _match_numbers(match: re.Match[str], slide_count: int) -> list[int] | None:
    """The sorted, distinct slide numbers a match names, or ``None`` to drop it."""
    items = match.group("plural_items") or match.group("singular_items")
    if items is not None:
        return _item_list_numbers(items)
    return [_ordinal_number(match, slide_count)]


def _item_list_numbers(items: str) -> list[int] | None:
    """Expand "2-4 and 6" to [2, 3, 4, 6]; ``None`` if any range spans too many numbers."""
    numbers: set[int] = set()
    for item in _ITEM_RE.finditer(items):
        values = [_cardinal_value(token) for token in _NUMBER_RE.findall(item.group(0))]
        low, high = min(values), max(values)  # one value for a number, two for a range
        if high - low + 1 > MAX_RANGE_SPAN:
            return None
        numbers.update(range(low, high + 1))
    return sorted(numbers)


def _cardinal_value(token: str) -> int:
    return int(token) if token.isdigit() else _CARDINALS[token.lower()]


def _ordinal_number(match: re.Match[str], slide_count: int) -> int:
    if match.group("ordinal_relative"):
        return slide_count - 1
    if match.group("ordinal_last"):
        return slide_count
    if match.group("ordinal_digits"):
        return int(match.group("ordinal_digits"))
    return _ORDINALS[match.group("ordinal_word").lower()]


def _build_reference(text: str, numbers: list[int], ordered: list[int]) -> dict:
    in_range = [number for number in numbers if 1 <= number <= len(ordered)]
    out_of_range = [number for number in numbers if not 1 <= number <= len(ordered)]
    return {
        "text": text,
        "slide_numbers": numbers,
        "positions": [ordered[number - 1] for number in in_range],
        "out_of_range": out_of_range,
    }

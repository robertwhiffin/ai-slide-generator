"""The one shared sanitiser for ``generated_images`` metadata (chat image generation, R2).

Contract: ``docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md``,
"Shared metadata shape" and "Unit G interface":

* ``src/utils/generated_images.py`` holds ``GENERATED_IMAGE_KINDS``,
  ``GENERATED_IMAGE_KEYS`` and ``sanitize_generated_images(value) -> list[dict]``;
* the graph node builds the metadata with it and ``session_manager`` filters what it
  forwards with it, so both sides agree on one shape;
* ``token`` matches ``^[A-Za-z0-9_-]+$``; ``kind`` is one of the four kinds; ``option`` is an
  int of 1 or more; ``for_slide`` is an int of 1 or more, or null; ``slides`` is a list of
  ints of 1 or more;
* unknown keys are dropped; an entry with an invalid ``token``, ``kind`` or ``option`` is
  dropped; junk gives ``[]``; it never raises.

What this file deliberately leaves open: how an entry with a bad ``for_slide``, ``slides`` or
``prompt`` is repaired (the field nulled, emptied or left out). It pins only that the entry
survives and that whatever comes out obeys the shape.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from src.utils.generated_images import (
    GENERATED_IMAGE_KEYS,
    GENERATED_IMAGE_KINDS,
    sanitize_generated_images,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")

VALID: list[dict[str, Any]] = [
    {
        "token": "abc_DEF-1",
        "kind": "illustration",
        "option": 1,
        "prompt": "A calm harbour at dawn",
        "for_slide": 3,
        "slides": [2],
    },
    {
        "token": "tok2",
        "kind": "background",
        "option": 2,
        "prompt": "Soft blue gradient",
        "for_slide": None,
        "slides": [],
    },
    {
        "token": "Tok_3-xyz",
        "kind": "icon",
        "option": 3,
        "prompt": "A shield",
        "for_slide": 12,
        "slides": [1, 4, 12],
    },
    {
        "token": "0",
        "kind": "vector_icon",
        "option": 7,
        "prompt": "",
        "for_slide": 1,
        "slides": [1],
    },
]


def _entry(**overrides: Any) -> dict[str, Any]:
    out = copy.deepcopy(VALID[0])
    out.update(overrides)
    return out


def _without(key: str) -> dict[str, Any]:
    out = copy.deepcopy(VALID[0])
    del out[key]
    return out


def _assert_shape(entries: Any) -> None:
    """Every entry obeys the shared shape, whatever the input was."""
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, dict)
        assert set(entry) <= set(GENERATED_IMAGE_KEYS), entry
        assert isinstance(entry["token"], str) and TOKEN_RE.fullmatch(entry["token"]), entry
        assert entry["kind"] in GENERATED_IMAGE_KINDS, entry
        assert type(entry["option"]) is int and entry["option"] >= 1, entry
        if "for_slide" in entry:
            value = entry["for_slide"]
            assert value is None or (type(value) is int and value >= 1), entry
        if "slides" in entry:
            assert isinstance(entry["slides"], list), entry
            assert all(type(n) is int and n >= 1 for n in entry["slides"]), entry
        if "prompt" in entry:
            assert isinstance(entry["prompt"], str), entry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_the_kinds_and_keys_are_the_shared_shape():
    assert GENERATED_IMAGE_KINDS == ("illustration", "background", "icon", "vector_icon")
    assert GENERATED_IMAGE_KEYS == ("token", "kind", "option", "prompt", "for_slide", "slides")


# ---------------------------------------------------------------------------
# Valid input round-trips
# ---------------------------------------------------------------------------


def test_a_valid_list_round_trips_exactly():
    value = copy.deepcopy(VALID)

    assert sanitize_generated_images(value) == VALID


def test_each_valid_entry_round_trips_on_its_own():
    for entry in VALID:
        assert sanitize_generated_images([copy.deepcopy(entry)]) == [entry]


def test_the_input_is_not_modified():
    value = copy.deepcopy(VALID) + [{"token": "bad token", "kind": "icon", "option": 1}]
    before = copy.deepcopy(value)

    sanitize_generated_images(value)

    assert value == before


def test_an_empty_list_is_empty():
    assert sanitize_generated_images([]) == []


# ---------------------------------------------------------------------------
# Unknown keys are dropped
# ---------------------------------------------------------------------------


def test_unknown_keys_are_dropped_and_the_entry_kept():
    entry = _entry(
        tool_input={"query": "secret"},
        sign_in_url="https://evil.example",
        html="<script>alert(1)</script>",
        Token="shadow",
    )

    assert sanitize_generated_images([entry]) == [VALID[0]]


# ---------------------------------------------------------------------------
# Entries with a bad token, kind or option are dropped
# ---------------------------------------------------------------------------

BAD_TOKENS = [
    "",
    "abc def",
    "abc/def",
    "../etc",
    "{{image:abc}}",
    "abc\n",
    "\nabc",
    "tök",
    "abc.def",
    "a+b=",
    123,
    None,
    ["abc"],
    {"t": "abc"},
]

BAD_KINDS = [
    "photo",
    "Illustration",
    "ICON",
    "icon_png",
    "icon_svg",
    "vector icon",
    "",
    None,
    1,
    ["icon"],
]

BAD_OPTIONS = [0, -1, "1", 1.0, 2.5, True, False, None, [1], {"n": 1}]


@pytest.mark.parametrize("token", BAD_TOKENS, ids=[repr(t) for t in BAD_TOKENS])
def test_an_entry_with_a_bad_token_is_dropped(token):
    value = [copy.deepcopy(VALID[1]), _entry(token=token), copy.deepcopy(VALID[2])]

    assert sanitize_generated_images(value) == [VALID[1], VALID[2]]


@pytest.mark.parametrize("kind", BAD_KINDS, ids=[repr(k) for k in BAD_KINDS])
def test_an_entry_with_a_bad_kind_is_dropped(kind):
    value = [copy.deepcopy(VALID[1]), _entry(kind=kind), copy.deepcopy(VALID[2])]

    assert sanitize_generated_images(value) == [VALID[1], VALID[2]]


@pytest.mark.parametrize("option", BAD_OPTIONS, ids=[repr(o) for o in BAD_OPTIONS])
def test_an_entry_with_a_bad_option_is_dropped(option):
    value = [copy.deepcopy(VALID[1]), _entry(option=option), copy.deepcopy(VALID[2])]

    assert sanitize_generated_images(value) == [VALID[1], VALID[2]]


@pytest.mark.parametrize("key", ["token", "kind", "option"])
def test_an_entry_missing_a_required_key_is_dropped(key):
    value = [_without(key), copy.deepcopy(VALID[1])]

    assert sanitize_generated_images(value) == [VALID[1]]


# ---------------------------------------------------------------------------
# Bad optional fields never let a bad value through (the entry survives)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"for_slide": 0},
        {"for_slide": -2},
        {"for_slide": "3"},
        {"for_slide": 2.0},
        {"for_slide": True},
        {"for_slide": [3]},
        {"slides": "2"},
        {"slides": [0, -1, "2", 2.0, True, None, 3]},
        {"slides": {"2": True}},
        {"slides": None},
        {"prompt": 123},
        {"prompt": None},
        {"prompt": ["a", "b"]},
    ],
    ids=[
        "for_slide-0",
        "for_slide-negative",
        "for_slide-string",
        "for_slide-float",
        "for_slide-bool",
        "for_slide-list",
        "slides-string",
        "slides-mixed-junk",
        "slides-dict",
        "slides-none",
        "prompt-int",
        "prompt-none",
        "prompt-list",
    ],
)
def test_a_bad_optional_field_is_repaired_and_the_entry_kept(overrides):
    out = sanitize_generated_images([_entry(**overrides)])

    _assert_shape(out)
    assert len(out) == 1, "only a bad token, kind or option drops an entry"
    assert (out[0]["token"], out[0]["kind"], out[0]["option"]) == ("abc_DEF-1", "illustration", 1)


def test_valid_slide_numbers_survive_beside_bad_ones():
    out = sanitize_generated_images([_entry(slides=[0, 2, "3", 5, True])])

    _assert_shape(out)
    assert set(out[0].get("slides", [])) <= {2, 5}


# ---------------------------------------------------------------------------
# Junk gives [] and nothing ever raises
# ---------------------------------------------------------------------------

JUNK = [
    None,
    "",
    "generated_images",
    '[{"token": "abc", "kind": "icon", "option": 1}]',
    b"bytes",
    0,
    3.5,
    True,
    {},
    copy.deepcopy(VALID[0]),
    {"generated_images": copy.deepcopy(VALID)},
    [None, 1, "x", [], {}, (), b"x", 2.5],
    [[copy.deepcopy(VALID[0])]],
    [{"token": "a b", "kind": "icon", "option": 1}, {"kind": "icon", "option": 1}],
    [{1: "abc", 2: "icon"}],
    object(),
]


@pytest.mark.parametrize("value", JUNK, ids=[f"junk-{i}" for i in range(len(JUNK))])
def test_junk_gives_an_empty_list(value):
    assert sanitize_generated_images(value) == []


class _ExplodingDict(dict):
    """A dict whose every read raises."""

    def __getitem__(self, key: Any) -> Any:
        raise RuntimeError("boom")

    def get(self, key: Any, default: Any = None) -> Any:
        raise RuntimeError("boom")

    def items(self) -> Any:
        raise RuntimeError("boom")

    def keys(self) -> Any:
        raise RuntimeError("boom")

    def __iter__(self) -> Any:
        raise RuntimeError("boom")

    def __contains__(self, key: Any) -> bool:
        raise RuntimeError("boom")


class _ExplodingList(list):
    def __iter__(self) -> Any:
        raise RuntimeError("boom")

    def __len__(self) -> int:
        raise RuntimeError("boom")

    def __getitem__(self, index: Any) -> Any:
        raise RuntimeError("boom")


class _Unprintable:
    def __str__(self) -> str:
        raise RuntimeError("boom")

    def __repr__(self) -> str:
        raise RuntimeError("boom")

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("boom")

    __hash__ = object.__hash__


@pytest.mark.parametrize(
    "value",
    [
        _ExplodingList([copy.deepcopy(VALID[0])]),
        [_ExplodingDict(copy.deepcopy(VALID[0])), copy.deepcopy(VALID[1])],
        [_entry(token=_Unprintable())],
        [_entry(kind=_Unprintable())],
        [_entry(option=_Unprintable())],
        [_entry(for_slide=_Unprintable(), slides=[_Unprintable()], prompt=_Unprintable())],
        [_entry(slides=_ExplodingList([1]))],
    ],
    ids=[
        "exploding-list",
        "exploding-entry",
        "unprintable-token",
        "unprintable-kind",
        "unprintable-option",
        "unprintable-optionals",
        "exploding-slides",
    ],
)
def test_it_never_raises_and_still_obeys_the_shape(value):
    out = sanitize_generated_images(value)

    _assert_shape(out)


def test_a_long_list_of_mixed_entries_keeps_only_the_valid_ones_in_order():
    value: list[Any] = []
    for i, entry in enumerate(VALID):
        value.append(copy.deepcopy(entry))
        value.append({"token": f"bad token {i}", "kind": "icon", "option": 1})
        value.append("junk")

    assert sanitize_generated_images(value) == VALID

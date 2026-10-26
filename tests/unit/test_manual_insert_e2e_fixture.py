"""The mocked server in manual-insert-slide.spec.ts is the real server (#314 Task 9).

``frontend/tests/e2e/manual-insert-slide.spec.ts`` mocks ``POST /api/slides``: it
answers a blank insert with ``blank_html_by_position[position]`` from
``frontend/tests/fixtures/manual-insert-decks.json``, splices ``blank_spec_entry`` into
the deck spec, and answers a refused insert with ``busy_detail``.  Its AC2 check (the
blank's root paints the same ground as its neighbours) is only as good as those
strings.  This module keeps them honest: each one must equal what the production code
produces, computed here by the production function, never copied by hand.

Sabotage it guards: make ``blank_slide_shell`` return ``BLANK_SLIDE_HTML`` (or drop
``style`` / the ``<section>`` from the shell), or edit a blank in the JSON, and
``test_each_blank_is_the_server_shell`` goes red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.core.database  # noqa: F401  (import order: database before other src.* modules)
from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL
from src.domain.deck_spec_slides import (
    BLANK_DECK_SPEC_ENTRY,
    BLANK_SLIDE_HTML,
    blank_slide_shell,
    is_blank_slide_html,
)
from src.domain.slide import has_slide_wrapper

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "frontend" / "tests" / "fixtures" / "manual-insert-decks.json"
SPEC = REPO_ROOT / "frontend" / "tests" / "e2e" / "manual-insert-slide.spec.ts"

DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
DECKS = DATA["decks"]

#: The two deck shapes AC2 names, and the shell each must get (PLAN-CORRECTIONS,
#: Task 9 pre-brief).  Pinned here as well as computed, so a shell change that the
#: fixture silently followed (regenerated JSON) is still a visible diff.
EXPECTED_SHELL = {
    "W": '<section data-label="Ground"><div class="slide"></div></section>',
    "I": '<div class="slide" style="background: rgb(11, 31, 58); color: #fff"></div>',
}

CASES = [
    (name, position)
    for name, deck in sorted(DECKS.items())
    for position in range(len(deck["slides"]) + 1)
]


def test_the_fixture_holds_the_two_ac2_deck_shapes():
    assert sorted(DECKS) == sorted(EXPECTED_SHELL)


@pytest.mark.parametrize("name", sorted(DECKS))
def test_every_landing_position_has_a_blank(name):
    """The mock answers ANY position 0..n, so a product that sends the wrong one is
    caught by the spec's body assertion, not by a missing fixture entry."""
    deck = DECKS[name]
    assert len(deck["blank_html_by_position"]) == len(deck["slides"]) + 1


@pytest.mark.parametrize(("name", "position"), CASES)
def test_each_blank_is_the_server_shell(name, position):
    deck = DECKS[name]
    assert deck["blank_html_by_position"][position] == blank_slide_shell(
        deck["slides"], position
    )


@pytest.mark.parametrize(("name", "position"), CASES)
def test_each_blank_is_the_deck_frame_not_the_bare_fallback(name, position):
    """If the shell fell back to the bare div, the spec's root-background check would
    compare a transparent root with its neighbours' ground: the AC2 assertion would go
    red for the right reason, but only here does the cause have a name."""
    blank = DECKS[name]["blank_html_by_position"][position]
    assert blank == EXPECTED_SHELL[name]
    assert blank != BLANK_SLIDE_HTML
    assert is_blank_slide_html(blank)
    assert has_slide_wrapper(blank)


@pytest.mark.parametrize("name", sorted(DECKS))
def test_the_content_slides_are_not_blank(name):
    """The neighbours the spec compares against carry content (their data-marker),
    so 'the thumbnail shows no marker' really tells the blank from them."""
    deck = DECKS[name]
    for marker, html in zip(deck["markers"], deck["slides"]):
        assert f'data-marker="{marker}"' in html
        assert not is_blank_slide_html(html)


def test_busy_detail_is_the_server_sentence():
    assert DATA["busy_detail"] == CONVERSATION_BUSY_DETAIL


def test_blank_spec_entry_is_the_server_entry():
    assert DATA["blank_spec_entry"] == BLANK_DECK_SPEC_ENTRY


def test_the_spec_reads_this_fixture():
    """The cross-check is worthless if the spec stops reading the JSON (and starts
    carrying its own copies)."""
    source = SPEC.read_text(encoding="utf-8")
    assert "manual-insert-decks.json" in source
    for key in ("blank_html_by_position", "busy_detail", "blank_spec_entry"):
        assert key in source, key

"""Task 1 (speaker notes): ``speaker_notes`` on the ``Slide`` domain object and the deck wire dict.

D1: ``Slide.speaker_notes`` is ``Optional[str]`` (``None`` = parsed with no aside). On the wire it is always a
string: ``to_dict`` emits ``slide.speaker_notes or ""`` on every slide, and ``from_dict`` reads
``slide_data.get("speaker_notes") or ""``. Notes never appear in any rendered HTML.
"""
from __future__ import annotations

import pytest

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck


def _deck(*notes):
    """A deck with one slide per entry in ``notes``, each slide's HTML distinct."""
    slides = [
        Slide(
            html=f"<div class='slide'><h1>Slide {i}</h1></div>",
            slide_id=f"s{i}",
            scripts=f"console.log({i});",
            speaker_notes=n,
        )
        for i, n in enumerate(notes)
    ]
    return SlideDeck(title="Deck", css=".slide{color:red}", slides=slides)


# Sabotage target: `Slide.__init__` default `speaker_notes: Optional[str] = None` (e.g. default `""`).
def test_a_new_slide_has_no_notes():
    assert Slide(html="<div class='slide'>x</div>").speaker_notes is None


# Sabotage target: the `speaker_notes` parameter must be LAST in `Slide.__init__`, after `modified_at`
# (inserting it earlier silently shifts every positional caller's arguments).
def test_speaker_notes_is_the_last_positional_parameter():
    s = Slide("<div class='slide'>x</div>", "id1", "js()", "alice", "t1", "bob", "t2", "Say this.")
    assert (s.slide_id, s.scripts, s.created_by, s.created_at, s.modified_by, s.modified_at) == (
        "id1", "js()", "alice", "t1", "bob", "t2",
    )
    assert s.speaker_notes == "Say this."


# Sabotage target: `Slide.clone` passing `speaker_notes=self.speaker_notes` (drop the kwarg, or coerce
# `None` to `""`, which would erase the D1 "no aside, keep notes" tri-state).
@pytest.mark.parametrize("notes", ["Pause here.", "", None])
def test_clone_copies_the_notes(notes):
    original = Slide(html="<div class='slide'>x</div>", slide_id="s0", speaker_notes=notes)
    copy_ = original.clone()
    assert copy_ is not original
    assert copy_.speaker_notes == notes
    assert type(copy_.speaker_notes) is type(notes)


# Sabotage target: `SlideDeck.to_dict` per-slide `'speaker_notes': slide.speaker_notes or ''` placed right after
# `'scripts'` (emitting only when truthy, emitting raw `None`, or omitting it must turn this red).
def test_to_dict_emits_notes_on_every_slide():
    d = _deck("Say A.", None, "").to_dict()
    assert [s["speaker_notes"] for s in d["slides"]] == ["Say A.", "", ""]
    for s in d["slides"]:
        keys = list(s)
        assert keys.index("speaker_notes") == keys.index("scripts") + 1
        # The notes do not leak into the slide's HTML on the wire.
        assert "Say A." not in s["html"]


# Sabotage target: `SlideDeck.from_dict` reading `speaker_notes=slide_data.get("speaker_notes") or ""`
# (ignoring the key must turn this red).
def test_from_dict_round_trips_the_notes():
    deck = _deck("Say A.", None, "Line one.\n\nLine two.")
    restored = SlideDeck.from_dict(deck.to_dict())
    # D1: `None` crosses the wire as "" (the wire is always a string).
    assert [s.speaker_notes for s in restored.slides] == ["Say A.", "", "Line one.\n\nLine two."]
    assert restored.knit() == deck.knit()


# Sabotage target: the `or ""` in `from_dict`'s `slide_data.get("speaker_notes") or ""` (a pre-notes blob has no
# key, and an explicit null must also read as "").
@pytest.mark.parametrize(
    "slide_data",
    [
        {"html": "<div class='slide'>old</div>", "slide_id": "s0", "scripts": ""},
        {"html": "<div class='slide'>old</div>", "slide_id": "s0", "scripts": "", "speaker_notes": None},
    ],
    ids=["key-absent", "key-null"],
)
def test_a_blob_written_before_notes_reads_empty_notes(slide_data):
    restored = SlideDeck.from_dict({"title": "Old", "css": "", "slides": [slide_data]})
    assert restored.slides[0].speaker_notes == ""
    assert restored.to_dict()["slides"][0]["speaker_notes"] == ""


# Sabotage target: `Slide.to_html` returning `self.html` only (appending the notes, e.g. as an <aside>, must turn
# this red via `knit()`/`render_slide()`; `to_html_document()` reads `slide.html` and pins the stored HTML stays
# notes-free).
def test_notes_never_reach_the_rendered_html():
    marker = "SECRET-NOTE-ZQX"
    deck = _deck(marker, f"{marker}-2")
    assert deck.slides[0].speaker_notes == marker  # the notes are really set
    rendered = {
        "knit": deck.knit(),
        "render_slide_0": deck.render_slide(0),
        "render_slide_1": deck.render_slide(1),
        "to_html_document": deck.to_html_document(),
        "slide_0_to_html": deck.slides[0].to_html(),
    }
    leaked = [name for name, html in rendered.items() if marker in html]
    assert leaked == []


# --- speaker_notes_source (interface change from the orchestrating agent, overrides the plan) ---------------------
# `Slide.speaker_notes_source: Optional[str] = None`, LAST parameter after `speaker_notes`; "model", "user" or None.


def _sourced_deck(*pairs):
    """A deck with one slide per (notes, source) pair."""
    slides = [
        Slide(
            html=f"<div class='slide'><h1>Slide {i}</h1></div>",
            slide_id=f"s{i}",
            speaker_notes=notes,
            speaker_notes_source=source,
        )
        for i, (notes, source) in enumerate(pairs)
    ]
    return SlideDeck(title="Deck", slides=slides)


# Sabotage target: `speaker_notes_source` must be the LAST `Slide.__init__` parameter (after `speaker_notes`), with
# default `None`.
def test_speaker_notes_source_is_the_last_positional_parameter():
    s = Slide("<div class='slide'>x</div>", "id1", "", None, None, None, None, "Say this.", "user")
    assert (s.speaker_notes, s.speaker_notes_source) == ("Say this.", "user")
    assert Slide(html="<div class='slide'>x</div>").speaker_notes_source is None


# Sabotage target: `Slide.clone` passing `speaker_notes_source=self.speaker_notes_source` (drop the kwarg).
@pytest.mark.parametrize("source", ["model", "user", None])
def test_clone_copies_the_notes_source(source):
    original = Slide(html="<div class='slide'>x</div>", speaker_notes="Pause here.", speaker_notes_source=source)
    assert original.clone().speaker_notes_source == source


# Sabotage target: `SlideDeck.to_dict` per-slide
# `'speaker_notes_source': slide.speaker_notes_source if slide.speaker_notes else None`, right after `speaker_notes`
# (emitting the raw source, emitting only when set, or omitting the key must turn this red).
def test_to_dict_emits_the_notes_source_on_every_slide():
    d = _sourced_deck(
        ("Say A.", "model"),
        ("Say B.", "user"),
        ("Say C.", None),
        ("", "user"),  # source set, notes empty -> None on the wire
        (None, "model"),  # source set, no notes -> None on the wire
    ).to_dict()
    assert [s["speaker_notes_source"] for s in d["slides"]] == ["model", "user", None, None, None]
    for s in d["slides"]:
        keys = list(s)
        assert keys.index("speaker_notes_source") == keys.index("speaker_notes") + 1


# Sabotage target: `SlideDeck.from_dict` reading `slide_data.get("speaker_notes_source")` (ignoring the key must turn
# this red).
def test_from_dict_round_trips_the_notes_source():
    deck = _sourced_deck(("Say A.", "user"), ("Say B.", "model"), ("Say C.", None))
    restored = SlideDeck.from_dict(deck.to_dict())
    assert [s.speaker_notes_source for s in restored.slides] == ["user", "model", None]
    assert [s.speaker_notes for s in restored.slides] == ["Say A.", "Say B.", "Say C."]


# Sabotage target: `from_dict`'s whitelist (only "model"/"user" kept) and its "notes empty -> None" rule; a
# pass-through `slide_data.get("speaker_notes_source")` must turn the unknown and empty-notes cases red.
@pytest.mark.parametrize(
    "extra",
    [
        {},  # pre-source blob: key absent
        {"speaker_notes_source": None},
        {"speaker_notes_source": "agent"},  # unknown value
        {"speaker_notes_source": "USER"},  # not an exact match
        {"speaker_notes_source": ""},
    ],
    ids=["key-absent", "key-null", "unknown", "wrong-case", "empty-string"],
)
def test_from_dict_reads_an_unknown_or_missing_source_as_none(extra):
    slide_data = {"html": "<div class='slide'>x</div>", "slide_id": "s0", "speaker_notes": "Say A.", **extra}
    restored = SlideDeck.from_dict({"slides": [slide_data]})
    assert restored.slides[0].speaker_notes == "Say A."
    assert restored.slides[0].speaker_notes_source is None


# Sabotage target: `from_dict` dropping the source when the notes are empty (a valid "user" source on a slide with
# no notes must read None, matching `to_dict`).
@pytest.mark.parametrize("notes_extra", [{}, {"speaker_notes": ""}, {"speaker_notes": None}], ids=["absent", "empty", "null"])
def test_from_dict_drops_the_source_when_notes_are_empty(notes_extra):
    slide_data = {"html": "<div class='slide'>x</div>", "slide_id": "s0", "speaker_notes_source": "user", **notes_extra}
    restored = SlideDeck.from_dict({"slides": [slide_data]})
    assert restored.slides[0].speaker_notes == ""
    assert restored.slides[0].speaker_notes_source is None

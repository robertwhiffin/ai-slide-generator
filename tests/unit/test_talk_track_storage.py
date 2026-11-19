"""Talk track storage and extraction (presenter plan, Task 1).

A slide carries two presenter fields, each with its own author:

- ``speaker_notes`` / ``speaker_notes_source`` (already on this branch);
- ``talk_track`` / ``talk_track_source`` (new), each source in ``{"model", "user", None}``.

Covers:
- ``extract_presenter_text`` and ``pop_presenter_asides`` move the presenter
  asides out of slide HTML.  An aside is marked by ``data-presenter="talk-track"``
  or ``data-presenter="speaker-notes"`` (the builder's form), or by the class
  ``speaker-notes`` (design-system READMEs) or ``talk-track`` (symmetry).  An
  unknown ``data-presenter`` value is left alone.  ``extract_speaker_notes`` keeps
  its two-tuple but never leaks a talk-track aside.
- ``SlideDeck.from_html_string`` gives each slide its own talk track; ``to_dict``,
  ``from_dict`` and ``Slide.clone`` carry both fields.
- The migration adds ``talk_track`` (TEXT) and ``talk_track_source`` (VARCHAR(16))
  idempotently.
- A row stored before the migration reads ``talk_track == ""`` and source ``None``
  on every read path (Review Focus 2).
- ``SlideWriter.write_slide`` applies the speaker-notes rules to the talk track:
  ``None`` preserves, ``""`` clears, a model write never replaces user text, and
  each field is protected on its own.
- Full-identity writes (``save_slide_deck``), save points and the shift primitive
  (``_lay_out_slide_rows`` via ``_snapshot_row``) carry the talk track.

Fixtures: ``deck_with_three_rows`` (``tests/unit/conftest.py``); the file-engine
migration fixture and helpers follow ``tests/unit/test_speaker_notes_persistence.py``;
the SlideWriter fixtures follow ``tests/unit/test_slide_writer.py``.

New html_utils symbols are read off the module inside each test, so before the
implementation each test is red on its own missing name or field rather than the
whole module failing to import.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import String, Text, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — registers every model on Base.metadata
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core import database as core_database
from src.core.database import Base, _run_migrations
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.utils import html_utils
from src.utils.html_utils import extract_speaker_notes, find_slide_roots
from tests.unit.conftest import _make_fake_db

# The builder's output shape: asides marked by an attribute, not a class.
SLIDE = (
    '<div class="slide"><h1>Q3</h1>'
    '<aside data-presenter="talk-track" hidden><p>Revenue grew 12%.</p><p>Which region led?</p></aside>'
    '<aside data-presenter="speaker-notes" hidden><p>Source: sales.q3</p></aside></div>'
)
SLIDE_STRIPPED = '<div class="slide"><h1>Q3</h1></div>'
TALK = "Revenue grew 12%.\n\nWhich region led?"
NOTES = "Source: sales.q3"


# ===========================================================================
# Extraction (html_utils)
# ===========================================================================


def test_presenter_constants():
    # Sabotage target: a renamed token or attribute silently stops every extraction.
    assert html_utils.PRESENTER_ATTR == "data-presenter"
    assert html_utils.TALK_TRACK_CLASS == "talk-track"
    assert html_utils.SPEAKER_NOTES_CLASS == "speaker-notes"


def test_extract_presenter_text_moves_both_asides():
    # The data-presenter form extracts both fields.
    html, notes, talk = html_utils.extract_presenter_text(SLIDE)
    assert "aside" not in html and "Revenue" not in html and "data-presenter" not in html
    assert html == SLIDE_STRIPPED
    assert notes == NOTES
    assert talk == TALK


def test_class_form_asides_extract_both_fields():
    # Back-compat: class="speaker-notes" (design-system READMEs) and class="talk-track".
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><h1>Q3</h1>'
        '<aside class="talk-track" hidden><p>Revenue grew 12%.</p><p>Which region led?</p></aside>'
        '<aside class="speaker-notes" hidden><p>Source: sales.q3</p></aside></div>'
    )
    assert (html, notes, talk) == (SLIDE_STRIPPED, NOTES, TALK)


def test_class_speaker_notes_still_extracts_into_speaker_notes():
    # Sabotage target: matching only data-presenter and dropping the class form.
    raw = '<div class="slide"><p>x</p><aside class="speaker-notes"><p>From the README.</p></aside></div>'
    assert html_utils.extract_presenter_text(raw) == (
        '<div class="slide"><p>x</p></div>',
        "From the README.",
        None,
    )
    assert extract_speaker_notes(raw) == ('<div class="slide"><p>x</p></div>', "From the README.")


def test_data_presenter_speaker_notes_reaches_extract_speaker_notes():
    # Sabotage target: extract_speaker_notes keeping its old class-only early return.
    raw = '<div class="slide"><p>x</p><aside data-presenter="speaker-notes" hidden><p>Check Q2.</p></aside></div>'
    assert extract_speaker_notes(raw) == ('<div class="slide"><p>x</p></div>', "Check Q2.")


def test_mixed_data_presenter_talk_track_and_class_speaker_notes():
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><h1>Q3</h1>'
        '<aside data-presenter="talk-track" hidden><p>Revenue grew 12%.</p><p>Which region led?</p></aside>'
        '<aside class="speaker-notes"><p>Source: sales.q3</p></aside></div>'
    )
    assert (html, notes, talk) == (SLIDE_STRIPPED, NOTES, TALK)


def test_unknown_data_presenter_value_is_left_untouched():
    # Sabotage target: owning any aside that carries data-presenter, whatever its value.
    raw = '<div class="slide"><p>x</p><aside data-presenter="other" hidden><p>Keep me.</p></aside></div>'
    out = html_utils.extract_presenter_text(raw)
    assert out == (raw, None, None)
    assert out[0] is raw
    assert extract_speaker_notes(raw) == (raw, None)

    # Beside a real presenter aside, the unknown one stays in the HTML unchanged.
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><p>x</p><aside data-presenter="other" hidden><p>Keep me.</p></aside>'
        '<aside data-presenter="talk-track" hidden><p>Say it.</p></aside></div>'
    )
    assert html == '<div class="slide"><p>x</p><aside data-presenter="other" hidden=""><p>Keep me.</p></aside></div>'
    assert (notes, talk) == (None, "Say it.")


def test_data_presenter_value_must_match_exactly():
    for not_owned in (
        '<div class="slide"><p>x</p><aside data-presenter="talk-track-x">S</aside></div>',
        '<div class="slide"><p>x</p><aside data-presenter="my-speaker-notes">S</aside></div>',
    ):
        out = html_utils.extract_presenter_text(not_owned)
        assert out == (not_owned, None, None)
        assert out[0] is not_owned


def test_absent_asides_return_none_and_unchanged_html():
    raw = '<div class="slide"><h1>x</h1></div>'
    out = html_utils.extract_presenter_text(raw)
    assert out == (raw, None, None)
    # Never reserialised when there is nothing to move.
    assert out[0] is raw


def test_empty_talk_track_is_empty_string():
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><aside data-presenter="talk-track" hidden></aside></div>'
    )
    assert (notes, talk) == (None, "")
    assert html == '<div class="slide"></div>'


def test_talk_track_only_slide_reads_none_notes():
    # Sabotage target: a single shared text list (notes and talk track mixed up).
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><p>x</p><aside data-presenter="talk-track" hidden><p>Say it.</p></aside></div>'
    )
    assert html == '<div class="slide"><p>x</p></div>'
    assert notes is None
    assert talk == "Say it."


def test_notes_only_slide_reads_none_talk_track():
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><p>x</p><aside data-presenter="speaker-notes" hidden><p>Check Q2.</p></aside></div>'
    )
    assert html == '<div class="slide"><p>x</p></div>'
    assert (notes, talk) == ("Check Q2.", None)


def test_two_talk_track_asides_join_in_order_skipping_empty():
    html, notes, talk = html_utils.extract_presenter_text(
        '<div class="slide"><aside data-presenter="talk-track">First</aside><p>x</p>'
        '<aside class="talk-track"></aside>'
        '<aside data-presenter="talk-track"><p>Second</p></aside></div>'
    )
    assert html == '<div class="slide"><p>x</p></div>'
    assert (notes, talk) == (None, "First\n\nSecond")


def test_extract_speaker_notes_strips_stray_talk_track():
    html, notes = extract_speaker_notes(SLIDE)
    assert "talk-track" not in html and notes == NOTES
    assert html == SLIDE_STRIPPED


def test_extract_speaker_notes_strips_a_talk_track_with_no_notes_aside():
    # Sabotage target: extract_speaker_notes keeping its old early return on
    # `SPEAKER_NOTES_CLASS not in html`, which leaks a lone talk-track aside.
    raw = '<div class="slide"><p>x</p><aside data-presenter="talk-track" hidden><p>Say it.</p></aside></div>'
    html, notes = extract_speaker_notes(raw)
    assert html == '<div class="slide"><p>x</p></div>'
    assert notes is None


@pytest.mark.parametrize(
    "raw",
    [
        '<aside class="talk-track"><p>x</p></aside><div class="slide"></div>',
        '<aside data-presenter="talk-track" hidden><p>x</p></aside><div class="slide"></div>',
    ],
)
def test_unowned_aside_is_left_in_place(raw):
    out = html_utils.extract_presenter_text(raw)
    assert out[2] is None
    assert out == (raw, None, None)
    assert out[0] is raw


def test_talk_track_class_token_must_match_exactly():
    owned = "<div class='slide'><p>x</p><aside class='talk-track muted'>S</aside></div>"
    assert html_utils.extract_presenter_text(owned) == ('<div class="slide"><p>x</p></div>', None, "S")
    for not_owned in (
        "<div class='slide'><p>x</p><aside class='talk-track-x'>S</aside></div>",
        "<div class='slide'><p>x</p><aside class='my-talk-track'>S</aside></div>",
    ):
        out = html_utils.extract_presenter_text(not_owned)
        assert out == (not_owned, None, None)
        assert out[0] is not_owned


@pytest.mark.parametrize(
    "markers",
    [
        'data-presenter="talk-track" class="speaker-notes"',
        'data-presenter="speaker-notes" class="talk-track"',
        'class="speaker-notes talk-track"',
    ],
    ids=["attr-talk-class-notes", "attr-notes-class-talk", "both-classes"],
)
def test_an_aside_with_both_markers_goes_to_speaker_notes_only(markers):
    # Sabotage target: pop_presenter_asides dropping the dual-marker filter, so one
    # aside's text lands in BOTH fields (and the talk track repeats the notes).
    raw = f'<div class="slide"><p>x</p><aside {markers} hidden><p>Both.</p></aside></div>'
    assert html_utils.extract_presenter_text(raw) == ('<div class="slide"><p>x</p></div>', "Both.", None)

    soup = BeautifulSoup(raw, "html.parser")
    popped = html_utils.pop_presenter_asides(soup)
    assert [t for _, t in popped["speaker_notes"]] == ["Both."]
    assert popped["talk_track"] == []
    assert soup.find("aside") is None


def test_pop_presenter_asides_keys_each_field_to_its_own_root():
    html = (
        '<div class="slide"><p>a</p><aside data-presenter="talk-track" hidden>Talk A</aside></div>'
        '<div class="slide"><p>b</p><aside class="speaker-notes">Notes B</aside>'
        '<aside data-presenter="talk-track" hidden>Talk B</aside></div>'
    )
    soup = BeautifulSoup(html, "html.parser")
    popped = html_utils.pop_presenter_asides(soup)
    assert set(popped) == {"speaker_notes", "talk_track"}
    assert [t for _, t in popped["talk_track"]] == ["Talk A", "Talk B"]
    assert [t for _, t in popped["speaker_notes"]] == ["Notes B"]
    assert soup.find("aside") is None

    roots = find_slide_roots(soup)
    assert [html_utils.text_for_root(r, popped["talk_track"]) for r in roots] == ["Talk A", "Talk B"]
    assert [html_utils.text_for_root(r, popped["speaker_notes"]) for r in roots] == [None, "Notes B"]


def test_notes_for_root_is_an_alias_of_text_for_root():
    assert html_utils.notes_for_root is html_utils.text_for_root


# ===========================================================================
# Domain (Slide, SlideDeck)
# ===========================================================================


def test_parse_assigns_each_slide_its_own_talk_track():
    deck = SlideDeck.from_html_string(
        "<html><body>" + SLIDE + SLIDE.replace("12%", "9%") + "</body></html>"
    )
    assert [s.talk_track.split(".")[0] for s in deck.slides] == ["Revenue grew 12%", "Revenue grew 9%"]
    assert [s.talk_track for s in deck.slides] == [TALK, TALK.replace("12%", "9%")]
    assert all(s.talk_track_source == "model" for s in deck.slides)
    assert [s.speaker_notes for s in deck.slides] == [NOTES, NOTES]
    assert all(s.speaker_notes_source == "model" for s in deck.slides)
    for s in deck.slides:
        assert "aside" not in s.html and "Revenue" not in s.html


def test_parse_without_or_with_empty_talk_track():
    deck = SlideDeck.from_html_string(
        "<html><body>"
        '<div class="slide"><h1>A</h1></div>'
        '<div class="slide"><h1>B</h1><aside data-presenter="talk-track" hidden></aside></div>'
        "</body></html>"
    )
    assert [(s.talk_track, s.talk_track_source) for s in deck.slides] == [(None, None), ("", None)]
    assert all("aside" not in s.html for s in deck.slides)


@pytest.mark.parametrize(
    "notes_attr",
    ['data-presenter="speaker-notes" hidden', 'class="speaker-notes"'],
    ids=["data-presenter", "class-notes-with-data-presenter-talk"],
)
def test_parse_promotes_a_wrapper_holding_the_slide_and_both_asides(notes_attr):
    # Plan review B1.  Sabotage target: per-marker ownership whose "only other element
    # child is the .slide" rule counts the other presenter aside, so neither aside is
    # owned, both stay in the wrapper, and find_slide_roots never promotes it.
    deck = SlideDeck.from_html_string(
        "<html><body>"
        '<section class="dark"><div class="slide"><p>x</p></div>'
        '<aside data-presenter="talk-track" hidden><p>Say it.</p></aside>'
        f"<aside {notes_attr}><p>Check Q2.</p></aside></section>"
        "</body></html>"
    )
    (slide,) = deck.slides
    assert slide.html.startswith('<section class="dark">')
    assert slide.html == '<section class="dark"><div class="slide"><p>x</p></div></section>'
    assert (slide.talk_track, slide.talk_track_source) == ("Say it.", "model")
    assert (slide.speaker_notes, slide.speaker_notes_source) == ("Check Q2.", "model")


def test_a_new_slide_has_no_talk_track():
    s = Slide(html="<div class='slide'>x</div>")
    assert s.talk_track is None and s.talk_track_source is None


def test_existing_positional_parameters_keep_their_place():
    # Sabotage target: inserting talk_track before speaker_notes / speaker_notes_source.
    s = Slide("<div class='slide'>x</div>", "id1", "", None, None, None, None, "Say this.", "user")
    assert (s.speaker_notes, s.speaker_notes_source) == ("Say this.", "user")
    assert (s.talk_track, s.talk_track_source) == (None, None)


@pytest.mark.parametrize(
    "talk,source", [("Beat one.", "model"), ("Mine.", "user"), ("", None), (None, None)]
)
def test_clone_copies_the_talk_track(talk, source):
    original = Slide(
        html="<div class='slide'>x</div>", slide_id="s0", talk_track=talk, talk_track_source=source
    )
    copy_ = original.clone()
    assert copy_ is not original
    assert (copy_.talk_track, copy_.talk_track_source) == (talk, source)
    assert type(copy_.talk_track) is type(talk)


def test_to_dict_from_dict_round_trip():
    deck = SlideDeck.from_html_string("<html><body>" + SLIDE + "</body></html>")
    d = deck.to_dict()["slides"][0]
    assert d["talk_track"].startswith("Revenue") and d["talk_track_source"] == "model"
    assert d["talk_track"] == TALK
    assert d["speaker_notes"] == NOTES
    again = SlideDeck.from_dict(deck.to_dict()).slides[0]
    assert again.talk_track == deck.slides[0].talk_track
    assert again.talk_track_source == "model"


def test_to_dict_emits_talk_track_as_a_string_on_every_slide():
    slides = [
        Slide(html="<div class='slide'>0</div>", slide_id="s0", talk_track="Say A.", talk_track_source="user"),
        Slide(html="<div class='slide'>1</div>", slide_id="s1", talk_track=None, talk_track_source="model"),
        Slide(html="<div class='slide'>2</div>", slide_id="s2", talk_track="", talk_track_source="user"),
    ]
    d = SlideDeck(title="Deck", slides=slides).to_dict()
    assert [(s["talk_track"], s["talk_track_source"]) for s in d["slides"]] == [
        ("Say A.", "user"),
        ("", None),
        ("", None),
    ]
    # The talk track never reaches rendered HTML.
    assert "Say A." not in SlideDeck(title="Deck", slides=slides).to_html_document()


def test_from_dict_round_trips_a_user_talk_track():
    deck = SlideDeck.from_dict(
        {
            "slides": [
                {
                    "html": "<div class='slide'>x</div>",
                    "talk_track": "Mine.",
                    "talk_track_source": "user",
                    "speaker_notes": "Model notes.",
                    "speaker_notes_source": "model",
                }
            ]
        }
    )
    s = deck.slides[0]
    assert (s.talk_track, s.talk_track_source) == ("Mine.", "user")
    assert (s.speaker_notes, s.speaker_notes_source) == ("Model notes.", "model")


def test_from_dict_without_key_reads_empty():
    deck = SlideDeck.from_dict({"slides": [{"html": '<div class="slide"></div>'}]})
    assert deck.slides[0].talk_track == "" and deck.slides[0].talk_track_source is None


@pytest.mark.parametrize(
    "extra",
    [
        {"talk_track": "Say A.", "talk_track_source": "agent"},
        {"talk_track": "Say A.", "talk_track_source": "USER"},
        {"talk_track": "Say A."},
        {"talk_track": "", "talk_track_source": "user"},
        {"talk_track": None, "talk_track_source": "model"},
    ],
    ids=["unknown", "wrong-case", "source-absent", "empty-text", "null-text"],
)
def test_from_dict_whitelists_the_talk_track_source(extra):
    deck = SlideDeck.from_dict({"slides": [{"html": "<div class='slide'>x</div>", **extra}]})
    s = deck.slides[0]
    assert s.talk_track == (extra.get("talk_track") or "")
    assert s.talk_track_source is None


# ===========================================================================
# Migration
# ===========================================================================

_TALK_COLUMNS = ("talk_track", "talk_track_source")
_NOTES_COLUMNS = ("speaker_notes", "speaker_notes_source")
_QUAL = lambda t: f'"{t}"'  # noqa: E731 — the lambda _run_migrations builds with no schema


def _column_map(engine) -> dict:
    with engine.connect() as conn:
        return {c["name"]: c for c in inspect(conn).get_columns("session_slides")}


def _column_names(engine) -> list:
    with engine.connect() as conn:
        return [c["name"] for c in inspect(conn).get_columns("session_slides")]


def _drop_columns_if_present(engine, columns) -> None:
    """Return session_slides to a shape without *columns*; prove they are gone."""
    present = set(_column_names(engine))
    with engine.begin() as conn:
        for col_name in columns:
            if col_name in present:
                conn.execute(text(f"ALTER TABLE session_slides DROP COLUMN {col_name}"))
    remaining = _column_names(engine)
    for col_name in columns:
        assert col_name not in remaining, f"DROP COLUMN did not remove {col_name}"


def _assert_text_and_source_columns(engine, text_col: str, source_col: str) -> None:
    names = _column_names(engine)
    col_map = _column_map(engine)
    for col_name in (text_col, source_col):
        assert names.count(col_name) == 1, (
            f"{col_name} appears {names.count(col_name)} times in session_slides: {names}"
        )
        assert col_map[col_name]["nullable"] is True, f"{col_name} is not nullable"
    assert isinstance(col_map[text_col]["type"], Text), (
        f"{text_col} is {col_map[text_col]['type']!r}, expected TEXT"
    )
    source_type = col_map[source_col]["type"]
    assert isinstance(source_type, String) and not isinstance(source_type, Text), (
        f"{source_col} is {source_type!r}, expected VARCHAR(16)"
    )
    assert source_type.length == 16, f"{source_col} is {source_type!r}, expected VARCHAR(16)"


def _migrate_alone(engine) -> None:
    with engine.begin() as conn:
        core_database._migrate_session_slide_speaker_notes(conn, inspect(conn), None, _QUAL, True)


@pytest.fixture
def migrated_engine(tmp_path):
    """A fresh SQLite file built in production order: create_all, then _run_migrations."""
    engine = create_engine(f"sqlite:///{tmp_path}/talk.db")
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    yield engine
    engine.dispose()


def _seed_pre_migration_row(engine) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        owner = UserSession(session_id="pre-talk-session", created_by="owner@example.com")
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(session_id=owner.id, title="Pre-talk deck", html_content="", slide_count=1)
        )
        db.commit()
        owner_pk = owner.id
    finally:
        db.close()
    # Raw INSERT naming only pre-existing columns, so the seed does not depend on the ORM
    # knowing the new columns.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO session_slides (id, session_id, position, html, slide_id, scripts) "
                "VALUES ('pre-talk-row', :o, 0, '<div class=''slide''>Before</div>', 'pre-talk-slide', '')"
            ),
            {"o": owner_pk},
        )


def test_migration_adds_talk_track_columns_idempotently(migrated_engine):
    # Sabotage target: drop ("talk_track", ...) / ("talk_track_source", ...) from the migration tuple,
    # or the "col_name not in cols" guard (a second ADD COLUMN raises).
    _seed_pre_migration_row(migrated_engine)
    _drop_columns_if_present(migrated_engine, _TALK_COLUMNS)

    _migrate_alone(migrated_engine)  # adds both
    _migrate_alone(migrated_engine)  # must see them and add nothing

    _assert_text_and_source_columns(migrated_engine, "talk_track", "talk_track_source")
    _assert_text_and_source_columns(migrated_engine, "speaker_notes", "speaker_notes_source")
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, slide_id, html, talk_track, talk_track_source FROM session_slides")
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("pre-talk-row", "pre-talk-slide", "<div class='slide'>Before</div>", None, None)
    ]


def test_migration_adds_all_four_presenter_columns_to_a_main_era_table(migrated_engine):
    # A table from before either presenter field: one helper adds all four, twice is a no-op.
    _drop_columns_if_present(migrated_engine, _TALK_COLUMNS + _NOTES_COLUMNS)

    _migrate_alone(migrated_engine)
    _migrate_alone(migrated_engine)

    _assert_text_and_source_columns(migrated_engine, "talk_track", "talk_track_source")
    _assert_text_and_source_columns(migrated_engine, "speaker_notes", "speaker_notes_source")


def test_run_migrations_adds_the_talk_track_columns(migrated_engine):
    _drop_columns_if_present(migrated_engine, _TALK_COLUMNS)

    _run_migrations(migrated_engine)
    _run_migrations(migrated_engine)

    _assert_text_and_source_columns(migrated_engine, "talk_track", "talk_track_source")


def test_orm_model_declares_the_talk_track_columns():
    # A fresh install gets the columns from create_all, not the migration.
    cols = SessionSlide.__table__.columns
    assert isinstance(cols["talk_track"].type, Text) and cols["talk_track"].nullable
    source_type = cols["talk_track_source"].type
    assert isinstance(source_type, String) and not isinstance(source_type, Text)
    assert source_type.length == 16 and cols["talk_track_source"].nullable


# ===========================================================================
# Read paths (Review Focus 2) and full-identity writes (deck_with_three_rows)
# ===========================================================================


def _row_talk(fx) -> list:
    """``[(slide_id, talk_track, talk_track_source)]`` per row, raw column values."""
    return [(r.slide_id, r.talk_track, r.talk_track_source) for r in fx.rows()]


def _read_talk(deck: dict) -> list:
    return [(s["talk_track"], s["talk_track_source"]) for s in deck["slides"]]


def _read_both(deck: dict) -> list:
    return [
        (s["talk_track"], s["talk_track_source"], s["speaker_notes"], s["speaker_notes_source"])
        for s in deck["slides"]
    ]


def _writer_get(fx, position: int) -> dict:
    """The ``_row_to_dict`` read path, through ``SlideWriter.get_slide``."""
    with patch("src.api.services.slide_repository.get_db_session", _make_fake_db(fx._factory)):
        return SlideWriter(SessionManager()).get_slide(fx.session_id, position)


def _save(fx, deck: dict) -> None:
    with fx._patched():
        SessionManager().save_slide_deck(
            fx.session_id,
            deck.get("title"),
            html_content="",
            deck_dict=deck,
            slide_count=len(deck["slides"]),
        )


def _with_talk(deck: dict, talk: list) -> dict:
    for slide, (t, s) in zip(deck["slides"], talk):
        slide["talk_track"] = t
        slide["talk_track_source"] = s
    return deck


def _set_raw(fx, position: int, **cols) -> None:
    assignments = ", ".join(f"{k} = :{k}" for k in cols)
    with fx._engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE session_slides SET {assignments} "
                "WHERE session_id = :o AND position = :p"
            ),
            {**cols, "o": fx._owner_pk(fx.session_id), "p": position},
        )


def test_pre_migration_row_reads_empty_talk_track(deck_with_three_rows):
    # Review Focus 2.  Sabotage targets: the `talk_track` line in get_slide_deck's row path or in
    # _row_to_dict emitting the raw column (None) instead of "", or passing a source through.
    fx = deck_with_three_rows
    _drop_columns_if_present(fx._engine, _TALK_COLUMNS)
    # Notes stored before the migration keep reading exactly as before.
    _set_raw(fx, 1, speaker_notes="Old notes.", speaker_notes_source="user")
    _run_migrations(fx._engine)
    assert [(t, s) for _, t, s in _row_talk(fx)] == [(None, None)] * 3

    assert _read_both(fx.get_slide_deck()) == [
        ("", None, "", None),
        ("", None, "Old notes.", "user"),
        ("", None, "", None),
    ]
    for position in range(3):
        got = _writer_get(fx, position)
        assert got["talk_track"] == "" and got["talk_track_source"] is None
    assert _writer_get(fx, 1)["speaker_notes"] == "Old notes."


def test_row_read_paths_drop_a_stray_or_unknown_talk_track_source(deck_with_three_rows):
    fx = deck_with_three_rows
    _set_raw(fx, 0, talk_track=None, talk_track_source="model")  # source without text
    _set_raw(fx, 1, talk_track="Say it.", talk_track_source="agent")  # unknown source
    _set_raw(fx, 2, talk_track="Mine.", talk_track_source="user")

    assert _read_talk(fx.get_slide_deck()) == [("", None), ("Say it.", None), ("Mine.", "user")]
    assert [
        (g["talk_track"], g["talk_track_source"]) for g in (_writer_get(fx, i) for i in range(3))
    ] == [("", None), ("Say it.", None), ("Mine.", "user")]


def test_blob_read_path_without_talk_track_reads_empty(deck_with_three_rows):
    # Sabotage target: the "F5 key parity" block in get_slide_deck's deck_json path lacking talk_track.
    fx = deck_with_three_rows
    owner_pk = fx._owner_pk(fx.session_id)
    db = fx._factory()
    try:
        db.query(SessionSlide).filter(SessionSlide.session_id == owner_pk).delete()
        deck = db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == owner_pk).one()
        blob = json.loads(deck.deck_json)
        blob["slides"][0]["talk_track"] = "Blob beat."
        blob["slides"][0]["talk_track_source"] = "user"
        blob["slides"][1]["talk_track"] = None
        blob["slides"][1]["talk_track_source"] = "model"  # stray source beside no text
        assert "talk_track" not in blob["slides"][2]  # a blob written before the field
        deck.deck_json = json.dumps(blob)
        db.commit()
    finally:
        db.close()
    assert fx.rows() == []

    assert _read_talk(fx.get_slide_deck()) == [("Blob beat.", "user"), ("", None), ("", None)]


def test_save_slide_deck_writes_the_talk_track_and_rows_read_it_back(deck_with_three_rows):
    # Sabotage target: drop talk_track(_source) from _upsert_slide_row's full-UPDATE branch.
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    _save(fx, _with_talk(fx.get_slide_deck(), [(None, None), ("Beat.", "model"), ("Mine.", "user")]))

    assert _row_talk(fx) == [(ids[0], None, None), (ids[1], "Beat.", "model"), (ids[2], "Mine.", "user")]
    assert _read_talk(fx.get_slide_deck()) == [("", None), ("Beat.", "model"), ("Mine.", "user")]

    # A full rewrite with "" clears the text and its source.
    _save(fx, _with_talk(fx.get_slide_deck(), [("", None), ("", "model"), ("", "user")]))
    assert _row_talk(fx) == [(i, None, None) for i in ids]


def test_a_reorder_moves_the_talk_track_with_its_slide(deck_with_three_rows):
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    _save(fx, _with_talk(fx.get_slide_deck(), [("Open with the question.", "user"), ("", None), ("", None)]))

    deck = fx.get_slide_deck()
    deck["slides"].reverse()
    _save(fx, deck)

    assert _row_talk(fx) == [
        (ids[2], None, None),
        (ids[1], None, None),
        (ids[0], "Open with the question.", "user"),
    ]


def test_the_shift_primitive_carries_the_talk_track(deck_with_three_rows):
    # Sabotage target: _snapshot_row dropping talk_track(_source), which strands the
    # talk track at the old position on every graph layout and manual insert.
    from src.api.services import session_manager as sm_module

    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    _save(
        fx,
        _with_talk(
            fx.get_slide_deck(), [("Beat zero.", "user"), ("Beat one.", "model"), ("", None)]
        ),
    )
    owner_pk = fx._owner_pk(fx.session_id)
    db = fx._factory()
    try:
        old_rows = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_pk)
            .order_by(SessionSlide.position)
            .all()
        )
        sm_module._lay_out_slide_rows(db, owner_pk, old_rows, [2, 0, 1], {})
        db.commit()
    finally:
        db.close()

    assert _row_talk(fx) == [
        (ids[2], None, None),
        (ids[0], "Beat zero.", "user"),
        (ids[1], "Beat one.", "model"),
    ]


def test_a_save_point_carries_the_talk_track_and_restore_brings_it_back(deck_with_three_rows):
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    saved = [("Welcome everyone.", "user"), ("", None), ("Close on the ask.", "model")]
    _save(fx, _with_talk(fx.get_slide_deck(), saved))
    version_number = fx.create_version()["version_number"]

    _save(fx, _with_talk(fx.get_slide_deck(), [("", None), ("", None), ("", None)]))
    assert _row_talk(fx) == [(i, None, None) for i in ids]

    with fx._patched():
        SessionManager().restore_version(fx.session_id, version_number)

    assert _row_talk(fx) == [
        (ids[0], "Welcome everyone.", "user"),
        (ids[1], None, None),
        (ids[2], "Close on the ask.", "model"),
    ]
    assert _read_talk(fx.get_slide_deck()) == saved


# ===========================================================================
# Partial-mode writes: SlideWriter.write_slide
# ===========================================================================


@pytest.fixture()
def factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


_SID = "talk-root-001"


@pytest.fixture()
def session_id(factory):
    db = factory()
    db.add(UserSession(session_id=_SID, created_by="owner@test.com"))
    db.commit()
    db.close()
    return _SID


def _columns(factory) -> list:
    """``[(talk_track, talk_track_source, speaker_notes, speaker_notes_source)]`` per row, raw."""
    db = factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == _SID).one()
        rows = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        )
        return [
            (r.talk_track, r.talk_track_source, r.speaker_notes, r.speaker_notes_source) for r in rows
        ]
    finally:
        db.close()


def _view(slide: dict) -> tuple:
    return (
        slide["html"],
        slide["talk_track"],
        slide["talk_track_source"],
        slide["speaker_notes"],
        slide["speaker_notes_source"],
    )


def _write(factory, session_id, html, **kw) -> dict:
    with patch("src.api.services.slide_repository.get_db_session", _make_fake_db(factory)):
        writer = SlideWriter(SessionManager())
        writer.write_slide(session_id=session_id, position=0, html=html, **kw)
        return writer.get_slide(session_id=session_id, position=0)


def test_write_slide_stores_a_model_talk_track(factory, session_id):
    # Sabotage target: write_slide never putting talk_track into slide_dict (or the INSERT dropping it).
    got = _write(factory, session_id, "<p>A</p>", talk_track="Say this.")
    assert _columns(factory) == [("Say this.", "model", None, None)]
    assert _view(got) == ("<p>A</p>", "Say this.", "model", "", None)


def test_upsert_user_talk_track_survives_model_write(factory, session_id):
    # Sabotage target: drop the per-field user-wins check for talk_track in _upsert_slide_row.
    _write(factory, session_id, "<p>v1</p>", talk_track="mine", talk_track_source="user")
    assert _columns(factory) == [("mine", "user", None, None)]

    got = _write(factory, session_id, "<p>v2</p>", talk_track="model text", talk_track_source="model")

    assert _columns(factory) == [("mine", "user", None, None)]
    # The model write itself landed: only the talk track was protected.
    assert _view(got) == ("<p>v2</p>", "mine", "user", "", None)

    # An empty model talk track never clears user text either.
    _write(factory, session_id, "<p>v3</p>", talk_track="")
    assert _columns(factory) == [("mine", "user", None, None)]


def test_a_model_talk_track_replaces_a_model_talk_track(factory, session_id):
    # Sabotage target: a guard that protects ANY existing talk track instead of only source "user".
    _write(factory, session_id, "<p>v1</p>", talk_track="Old.")
    got = _write(factory, session_id, "<p>v2</p>", talk_track="New.")
    assert _columns(factory) == [("New.", "model", None, None)]
    assert _view(got) == ("<p>v2</p>", "New.", "model", "", None)


def test_upsert_none_preserves_and_empty_clears_talk_track(factory, session_id):
    # Sabotage targets: an unconditional `existing.talk_track = text or None` (None must preserve),
    # and "" treated like None (it must clear text AND source).
    _write(factory, session_id, "<p>v1</p>", talk_track="Keep me.")

    got = _write(factory, session_id, "<p>v2</p>")
    assert _columns(factory) == [("Keep me.", "model", None, None)]
    assert _view(got) == ("<p>v2</p>", "Keep me.", "model", "", None)

    got = _write(factory, session_id, "<p>v3</p>", talk_track="")
    assert _columns(factory) == [(None, None, None, None)]
    assert _view(got) == ("<p>v3</p>", "", None, "", None)

    # A user save of "" clears user text and its source.
    _write(factory, session_id, "<p>v4</p>", talk_track="Typed.", talk_track_source="user")
    got = _write(factory, session_id, "<p>v5</p>", talk_track="", talk_track_source="user")
    assert _columns(factory) == [(None, None, None, None)]
    assert _view(got) == ("<p>v5</p>", "", None, "", None)


def test_user_notes_do_not_freeze_model_talk_track(factory, session_id):
    # Sabotage target: one shared user-wins check (notes source "user" blocking the talk track).
    _write(
        factory,
        session_id,
        "<p>v1</p>",
        speaker_notes="Typed notes.",
        speaker_notes_source="user",
        talk_track="Old beat.",
        talk_track_source="model",
    )
    assert _columns(factory) == [("Old beat.", "model", "Typed notes.", "user")]

    got = _write(
        factory, session_id, "<p>v2</p>", speaker_notes="Model notes.", talk_track="New beat."
    )

    assert _columns(factory) == [("New beat.", "model", "Typed notes.", "user")]
    assert _view(got) == ("<p>v2</p>", "New beat.", "model", "Typed notes.", "user")


def test_user_talk_track_does_not_freeze_model_notes(factory, session_id):
    # The mirror case: a user talk track never blocks a model refresh of the notes.
    _write(
        factory,
        session_id,
        "<p>v1</p>",
        speaker_notes="Old notes.",
        speaker_notes_source="model",
        talk_track="My beat.",
        talk_track_source="user",
    )

    got = _write(
        factory, session_id, "<p>v2</p>", speaker_notes="New notes.", talk_track="Model beat."
    )

    assert _columns(factory) == [("My beat.", "user", "New notes.", "model")]
    assert _view(got) == ("<p>v2</p>", "My beat.", "user", "New notes.", "model")


def test_a_talk_track_only_write_leaves_the_notes(factory, session_id):
    # Review Focus 5 at the storage layer: a write that names only the talk track keeps the notes.
    _write(factory, session_id, "<p>v1</p>", speaker_notes="Fresh notes.")
    got = _write(factory, session_id, "<p>v2</p>", talk_track="Beat.", talk_track_source="user")
    assert _columns(factory) == [("Beat.", "user", "Fresh notes.", "model")]
    assert _view(got) == ("<p>v2</p>", "Beat.", "user", "Fresh notes.", "model")


# A plain Agent-mode deck (no design system) paints its ground with the deck
# style's ground piece, so the builder's root is ``div.dk-slide`` with no
# ``slide`` token (src/core/skills/builder.py, NO BOUND SECTION / DECK STYLE).
# Found live (plan Task 8): every slide of three such decks kept both asides in
# its HTML and stored an empty talk track and notes.
_DK_FRAGMENT = (
    '<div class="dk-slide dk-slide--dark" style="padding:56px 88px"><h1>T</h1>'
    '<aside data-presenter="talk-track" hidden><p>Say one.</p><p>Say two.</p></aside>'
    '<aside data-presenter="speaker-notes" hidden><p>Source: none.</p></aside></div>'
)


def test_a_fragment_whose_sole_root_has_no_slide_class_owns_its_asides():
    out = html_utils.extract_presenter_text(_DK_FRAGMENT)
    assert out == (
        '<div class="dk-slide dk-slide--dark" style="padding:56px 88px"><h1>T</h1></div>',
        "Source: none.",
        "Say one.\n\nSay two.",
    )
    assert extract_speaker_notes(_DK_FRAGMENT)[1] == "Source: none."


@pytest.mark.parametrize(
    "raw",
    [
        # Two top-level elements and no .slide: no single slide root to own it.
        '<div class="a"><aside data-presenter="talk-track" hidden>x</aside></div><div class="b"></div>',
        # An aside beside the sole root, not inside it.
        '<div class="dk-slide"><h1>T</h1></div><aside data-presenter="talk-track" hidden>x</aside>',
        # The sole top-level element is the aside itself: no slide holds it, so
        # it must not own itself and empty the fragment.
        '<aside data-presenter="talk-track" hidden><p>x</p></aside>',
        '\n  <aside data-presenter="speaker-notes" hidden>n</aside>\n',
    ],
)
def test_a_fragment_without_a_single_root_holding_the_aside_leaves_it(raw):
    out = html_utils.extract_presenter_text(raw)
    assert out == (raw, None, None)
    assert out[0] is raw

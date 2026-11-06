"""Speaker notes persist on the per-slide row (speaker-notes plan, Task 2; D2, D9, D10).

Covers:
- ``_migrate_session_slide_speaker_notes`` adds ``speaker_notes`` (TEXT) and
  ``speaker_notes_source`` (VARCHAR(16)), both nullable, to a ``session_slides``
  table that predates them, keeps existing rows (NULL in both), is wired into
  ``_run_migrations`` and is idempotent.  Pattern:
  ``tests/unit/test_chat_request_progress.py`` (drop the columns, then run the
  helper; never trust ``create_all``).
- The full-identity writer (``save_slide_deck``) stores both fields from the deck
  dict, clears them on ``""``, moves them with their slide on a reorder, and save
  points and restore carry them.
- Both ``get_slide_deck`` read paths (rows, and the ``deck_json`` blob of a deck
  with no rows) emit ``speaker_notes`` as a string on every slide, and
  ``speaker_notes_source`` as ``None`` whenever the notes are empty.
- A duplicate carries notes that went through ``save_slide_deck`` (D9: the live
  blob and a save point's blob).

Partial-mode (``SlideWriter.write_slide``) tests live in ``test_slide_writer.py``.
"""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import String, Text, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — registers every model on Base.metadata
from src.api.services.session_manager import SessionManager
from src.core import database as core_database
from src.core.database import Base, _run_migrations
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)

_NOTES_COLUMNS = ("speaker_notes", "speaker_notes_source")
_QUAL = lambda t: f'"{t}"'  # noqa: E731 — the lambda _run_migrations builds with no schema


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------


def _column_map(engine) -> dict:
    """Reflect session_slides' columns through a fresh connection (no cached reflection)."""
    with engine.connect() as conn:
        return {c["name"]: c for c in inspect(conn).get_columns("session_slides")}


def _column_names(engine) -> list:
    """Every session_slides column name, duplicates included."""
    with engine.connect() as conn:
        return [c["name"] for c in inspect(conn).get_columns("session_slides")]


def _drop_notes_columns(engine) -> None:
    """Return session_slides to its pre-notes shape, and prove both columns are gone."""
    with engine.begin() as conn:
        for col_name in _NOTES_COLUMNS:
            conn.execute(text(f"ALTER TABLE session_slides DROP COLUMN {col_name}"))
    remaining = _column_map(engine)
    for col_name in _NOTES_COLUMNS:
        assert col_name not in remaining, f"DROP COLUMN did not remove {col_name}"


def _assert_notes_columns(engine) -> None:
    """Both columns exist exactly once, are nullable, and carry the right types."""
    names = _column_names(engine)
    col_map = _column_map(engine)
    for col_name in _NOTES_COLUMNS:
        assert names.count(col_name) == 1, (
            f"{col_name} appears {names.count(col_name)} times in session_slides: {names}"
        )
        assert col_map[col_name]["nullable"] is True, f"{col_name} is not nullable"
    assert isinstance(col_map["speaker_notes"]["type"], Text), (
        f"speaker_notes is {col_map['speaker_notes']['type']!r}, expected TEXT"
    )
    source_type = col_map["speaker_notes_source"]["type"]
    assert isinstance(source_type, String) and not isinstance(source_type, Text), (
        f"speaker_notes_source is {source_type!r}, expected VARCHAR(16)"
    )
    assert source_type.length == 16, (
        f"speaker_notes_source is {source_type!r}, expected VARCHAR(16)"
    )


def _migrate_alone(engine) -> None:
    """Run the helper in isolation, as _run_migrations calls it, with a fresh inspector."""
    with engine.begin() as conn:
        core_database._migrate_session_slide_speaker_notes(
            conn, inspect(conn), None, _QUAL, True
        )


@pytest.fixture
def migrated_engine(tmp_path):
    """A fresh SQLite file built in production order: create_all, then _run_migrations."""
    engine = create_engine(f"sqlite:///{tmp_path}/notes.db")
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_a_pre_existing_session_slides_table_gains_speaker_notes(migrated_engine):
    # Sabotage target: make _migrate_session_slide_speaker_notes return early.
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    db = factory()
    try:
        owner = UserSession(session_id="pre-notes-session", created_by="owner@example.com")
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id, title="Pre-notes deck", html_content="", slide_count=1
            )
        )
        db.add(
            SessionSlide(
                session_id=owner.id,
                position=0,
                id="pre-notes-row",
                html="<div class='slide'>Before notes</div>",
                slide_id="pre-notes-slide",
                scripts="",
            )
        )
        db.commit()
    finally:
        db.close()

    _drop_notes_columns(migrated_engine)
    _migrate_alone(migrated_engine)

    _assert_notes_columns(migrated_engine)
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, slide_id, html, speaker_notes, speaker_notes_source "
                "FROM session_slides"
            )
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("pre-notes-row", "pre-notes-slide", "<div class='slide'>Before notes</div>", None, None)
    ]


def test_run_migrations_wires_the_speaker_notes_helper(migrated_engine):
    # Sabotage target: comment out the _migrate_session_slide_speaker_notes call in _run_migrations.
    _drop_notes_columns(migrated_engine)

    _run_migrations(migrated_engine)

    _assert_notes_columns(migrated_engine)


def test_the_speaker_notes_migration_is_idempotent(migrated_engine):
    # Sabotage target: drop the "col_name not in cols" check (a second ADD COLUMN raises).
    _drop_notes_columns(migrated_engine)

    _migrate_alone(migrated_engine)  # adds both
    _migrate_alone(migrated_engine)  # must see them and add nothing
    _run_migrations(migrated_engine)
    _run_migrations(migrated_engine)

    _assert_notes_columns(migrated_engine)


# ---------------------------------------------------------------------------
# Full-identity writes and the row read path (deck_with_three_rows)
# ---------------------------------------------------------------------------


def _row_notes(fixture) -> list:
    """``[(slide_id, speaker_notes, speaker_notes_source)]`` per row, raw column values."""
    return [(r.slide_id, r.speaker_notes, r.speaker_notes_source) for r in fixture.rows()]


def _read_notes(deck: dict) -> list:
    """``[(speaker_notes, speaker_notes_source)]`` per slide of a read deck dict."""
    return [(s["speaker_notes"], s["speaker_notes_source"]) for s in deck["slides"]]


def _save(fixture, deck: dict, session_id=None) -> None:
    with fixture._patched():
        SessionManager().save_slide_deck(
            session_id or fixture.session_id,
            deck.get("title"),
            html_content="",
            deck_dict=deck,
            slide_count=len(deck["slides"]),
        )


def _with_notes(deck: dict, notes: list) -> dict:
    """Set ``(speaker_notes, speaker_notes_source)`` on each slide of *deck*, in place."""
    for slide, (n, s) in zip(deck["slides"], notes):
        slide["speaker_notes"] = n
        slide["speaker_notes_source"] = s
    return deck


def test_save_slide_deck_writes_notes_and_the_row_read_returns_them(deck_with_three_rows):
    # Sabotage target: drop speaker_notes(_source) from _upsert_slide_row's full-UPDATE branch.
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    deck = fx.get_slide_deck()
    deck["slides"][1]["speaker_notes"] = "Pause here."
    deck["slides"][1]["speaker_notes_source"] = "model"

    _save(fx, deck)

    assert _row_notes(fx) == [
        (ids[0], None, None),
        (ids[1], "Pause here.", "model"),
        (ids[2], None, None),
    ]
    assert _read_notes(fx.get_slide_deck()) == [
        ("", None),
        ("Pause here.", "model"),
        ("", None),
    ]


def test_a_full_rewrite_with_empty_notes_clears_the_row(deck_with_three_rows):
    # Sabotage target: full-UPDATE branch writing notes only when non-empty (or keeping the source when notes are "").
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    _save(fx, _with_notes(fx.get_slide_deck(), [(None, None), ("Pause here.", "user"), (None, None)]))
    assert _row_notes(fx)[1] == (ids[1], "Pause here.", "user")

    # The source key is still "user" in the dict, but empty notes leave nothing to attribute.
    _save(fx, _with_notes(fx.get_slide_deck(), [("", None), ("", "user"), ("", None)]))

    assert _row_notes(fx) == [(ids[0], None, None), (ids[1], None, None), (ids[2], None, None)]
    assert _read_notes(fx.get_slide_deck()) == [("", None), ("", None), ("", None)]


def test_a_reorder_moves_the_notes_with_the_slide(deck_with_three_rows):
    # Sabotage target: write speaker_notes(_source) only on INSERT (the UPDATE leaves them with the position).
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    _save(fx, _with_notes(fx.get_slide_deck(), [("Open with the question.", "user"), ("", None), ("", None)]))

    deck = fx.get_slide_deck()
    deck["slides"].reverse()
    _save(fx, deck)

    assert _row_notes(fx) == [
        (ids[2], None, None),
        (ids[1], None, None),
        (ids[0], "Open with the question.", "user"),
    ]
    assert _read_notes(fx.get_slide_deck()) == [
        ("", None),
        ("", None),
        ("Open with the question.", "user"),
    ]


def _version_slides(fixture, version_number: int) -> list:
    db = fixture._factory()
    try:
        version = (
            db.query(SlideDeckVersion)
            .filter(
                SlideDeckVersion.session_id == fixture._owner_pk(fixture.session_id),
                SlideDeckVersion.version_number == version_number,
            )
            .one()
        )
        return json.loads(version.deck_json)["slides"]
    finally:
        db.close()


def test_a_save_point_carries_the_notes_and_restore_brings_them_back(deck_with_three_rows):
    # Sabotage target: drop speaker_notes from the row read path (the save point is built from get_slide_deck).
    fx = deck_with_three_rows
    ids = [r.slide_id for r in fx.rows()]
    saved = [("Welcome everyone.", "user"), ("", None), ("Close on the ask.", "model")]
    _save(fx, _with_notes(fx.get_slide_deck(), saved))

    version_number = fx.create_version()["version_number"]
    assert [
        (s["speaker_notes"], s["speaker_notes_source"]) for s in _version_slides(fx, version_number)
    ] == saved

    _save(fx, _with_notes(fx.get_slide_deck(), [("", None), ("", None), ("", None)]))
    assert _row_notes(fx) == [(i, None, None) for i in ids]

    with fx._patched():
        SessionManager().restore_version(fx.session_id, version_number)

    assert _row_notes(fx) == [
        (ids[0], "Welcome everyone.", "user"),
        (ids[1], None, None),
        (ids[2], "Close on the ask.", "model"),
    ]
    assert _read_notes(fx.get_slide_deck()) == saved


# ---------------------------------------------------------------------------
# Blob read path (a deck with no session_slides rows)
# ---------------------------------------------------------------------------


def test_a_deck_with_no_rows_reads_speaker_notes_from_the_blob(deck_with_three_rows):
    # Sabotage target: remove the speaker_notes default line from get_slide_deck's blob path.
    fx = deck_with_three_rows
    owner_pk = fx._owner_pk(fx.session_id)
    db = fx._factory()
    try:
        db.query(SessionSlide).filter(SessionSlide.session_id == owner_pk).delete()
        deck = db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == owner_pk).one()
        blob = json.loads(deck.deck_json)
        blob["slides"][0]["speaker_notes"] = "Blob note."
        blob["slides"][0]["speaker_notes_source"] = "user"
        blob["slides"][1]["speaker_notes"] = None
        # A stray source beside empty notes reads None (D10: no notes, no source).
        blob["slides"][1]["speaker_notes_source"] = "model"
        assert "speaker_notes" not in blob["slides"][2]
        deck.deck_json = json.dumps(blob)
        db.commit()
    finally:
        db.close()
    assert fx.rows() == []

    assert _read_notes(fx.get_slide_deck()) == [("Blob note.", "user"), ("", None), ("", None)]


# ---------------------------------------------------------------------------
# Duplicate (D9): notes travel in the blob save_slide_deck wrote
# ---------------------------------------------------------------------------


def _seed_active_graph_release(fixture) -> None:
    """The fixture deck is a graph deck, so its duplicate locks the active Graph Release.

    Same seed as ``test_conftest_fixtures.py::test_duplicate_returns_new_session_id``.
    """
    now = datetime.now(timezone.utc)
    db = fixture._factory()
    try:
        db.add(
            GraphRelease(
                version_number=1,
                release_note="speaker-notes duplicate test release",
                published_by="fixture@example.com",
                published_at=now,
                effective_from=now,
            )
        )
        db.commit()
    finally:
        db.close()


def _read_as(fixture, session_id: str) -> dict:
    with fixture._patched():
        return SessionManager().get_slide_deck(session_id)


def test_a_duplicate_carries_notes_saved_through_save_slide_deck(deck_with_three_rows):
    # Sabotage target: the blob read path blanking stored notes (`slide["speaker_notes"] = ""`); a duplicate has no rows.
    fx = deck_with_three_rows
    deck = fx.get_slide_deck()
    deck["slides"][1]["speaker_notes"] = "Pause here."
    deck["slides"][1]["speaker_notes_source"] = "user"
    _save(fx, deck)
    _seed_active_graph_release(fx)

    copy_id = fx.duplicate()["session_id"]

    assert _read_notes(_read_as(fx, copy_id)) == [("", None), ("Pause here.", "user"), ("", None)]


def test_a_duplicated_save_point_carries_notes(deck_with_three_rows):
    # Sabotage target: drop speaker_notes from the row read path (create_version snapshots get_slide_deck).
    fx = deck_with_three_rows
    _save(fx, _with_notes(fx.get_slide_deck(), [("", None), ("Pause here.", "model"), ("", None)]))
    version_number = fx.create_version()["version_number"]
    # The live deck moves on; the save point keeps the noted version.
    _save(fx, _with_notes(fx.get_slide_deck(), [("", None), ("", None), ("", None)]))

    _seed_active_graph_release(fx)

    copy_id = fx.duplicate(version_number=version_number)["session_id"]

    assert _read_notes(_read_as(fx, copy_id)) == [("", None), ("Pause here.", "model"), ("", None)]

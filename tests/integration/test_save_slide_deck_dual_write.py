"""Integration tests for save_slide_deck dual-write (Task 4).

Verifies that save_slide_deck:
  - writes session_slides rows in sync with deck_json
  - lifts deck-level css/external_scripts_json into their columns
  - prunes orphan rows in the same transaction
  - updates existing rows (no duplicates) on re-save
  - preserves existing behaviour (return dict shape, VersionConflictError,
    author-stamping, deck_json is still written)

Pattern: in-memory SQLite via
  patch("src.api.services.session_manager.get_db_session", fake_get_db_session)
— the same approach used in tests/unit/test_usage_event_capture.py:88-111.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services import session_manager as sm_module
from src.api.services.session_manager import SessionManager, VersionConflictError
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    UserSession,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine():
    """Fresh in-memory SQLite engine per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def factory(sqlite_engine):
    """SQLAlchemy session factory bound to the in-memory engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)


@pytest.fixture()
def session_id(factory):
    """Create one UserSession and return its string business key."""
    db = factory()
    user_session = UserSession(
        session_id="test-session-001",
        created_by="test-user@example.com",
    )
    db.add(user_session)
    db.commit()
    db.close()
    return "test-session-001"


def _make_fake_get_db_session(factory):
    """Return a contextmanager that yields a SQLAlchemy session from *factory*."""

    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return fake_get_db_session


def _query_slides(factory, deck_owner_id: int) -> list[SessionSlide]:
    """Return all SessionSlide rows for a deck owner, ordered by position."""
    db = factory()
    rows = (
        db.query(SessionSlide)
        .filter(SessionSlide.session_id == deck_owner_id)
        .order_by(SessionSlide.position)
        .all()
    )
    # Detach from session so we can inspect after close
    result = []
    for r in rows:
        result.append(
            {
                "session_id": r.session_id,
                "position": r.position,
                "html": r.html,
                "scripts": r.scripts,
                "created_by": r.created_by,
                "modified_by": r.modified_by,
                "verification_record": r.verification_record,
            }
        )
    db.close()
    return result


def _query_deck(factory, session_id_int: int) -> dict:
    """Return the SessionSlideDeck row as a dict of relevant fields."""
    db = factory()
    deck = (
        db.query(SessionSlideDeck)
        .filter(SessionSlideDeck.session_id == session_id_int)
        .one_or_none()
    )
    if deck is None:
        db.close()
        return {}
    result = {
        "deck_json": deck.deck_json,
        "css": deck.css,
        "external_scripts_json": deck.external_scripts_json,
        "version": deck.version,
    }
    db.close()
    return result


def _user_session_id_int(factory) -> int:
    """Return the integer PK of the sole UserSession in the DB."""
    db = factory()
    us = db.query(UserSession).one()
    pk = us.id
    db.close()
    return pk


def _make_deck_dict(slides: list, css: str = ".body{}", external_scripts: list | None = None):
    """Build a minimal deck_dict with a slides array."""
    if external_scripts is None:
        external_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
    return {
        "title": "Test Deck",
        "css": css,
        "external_scripts": external_scripts,
        "slides": slides,
    }


def _make_slide(html: str = "<p>slide</p>", scripts: str = "", created_by: str | None = None):
    """Build a minimal slide dict."""
    s = {"html": html, "scripts": scripts}
    if created_by:
        s["created_by"] = created_by
    return s


# ---------------------------------------------------------------------------
# Test: 3 slides → 3 rows at right positions with right html/scripts
# ---------------------------------------------------------------------------


class TestThreeSlidesWritten:
    def test_three_slides_produce_three_rows(self, factory, session_id):
        slides = [
            _make_slide("<p>Slide 0</p>", "js0"),
            _make_slide("<p>Slide 1</p>", "js1"),
            _make_slide("<p>Slide 2</p>", "js2"),
        ]
        deck_dict = _make_deck_dict(slides)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.save_slide_deck(
                session_id=session_id,
                title="Test Deck",
                html_content="<html>combined</html>",
                slide_count=3,
                deck_dict=deck_dict,
                modified_by="test-user@example.com",
            )

        owner_id = _user_session_id_int(factory)
        rows = _query_slides(factory, owner_id)

        assert len(rows) == 3
        assert rows[0]["position"] == 0
        assert rows[0]["html"] == "<p>Slide 0</p>"
        assert rows[0]["scripts"] == "js0"
        assert rows[1]["position"] == 1
        assert rows[1]["html"] == "<p>Slide 1</p>"
        assert rows[2]["position"] == 2
        assert rows[2]["html"] == "<p>Slide 2</p>"

    def test_return_dict_has_correct_shape(self, factory, session_id):
        """Return value must keep the existing shape (version, slide_count, etc.)."""
        deck_dict = _make_deck_dict([_make_slide()])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.save_slide_deck(
                session_id=session_id,
                title="My Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
            )

        assert "session_id" in result
        assert "title" in result
        assert "slide_count" in result
        assert "updated_at" in result
        assert "version" in result
        assert result["slide_count"] == 1


# ---------------------------------------------------------------------------
# Test: css and external_scripts_json land in their columns (PRD §3 guard)
# ---------------------------------------------------------------------------


class TestDeckLevelPresentationColumns:
    def test_css_and_external_scripts_json_are_written(self, factory, session_id):
        """PRD §3 guard: css and external_scripts_json must be set on the deck row."""
        css_val = "body { background: red; }"
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js", "https://example.com/lib.js"]
        deck_dict = _make_deck_dict([_make_slide()], css=css_val, external_scripts=ext_scripts)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
            )

        owner_id = _user_session_id_int(factory)
        deck_row = _query_deck(factory, owner_id)

        assert deck_row["css"] == css_val, (
            f"Expected css={css_val!r}, got {deck_row['css']!r}"
        )
        assert deck_row["external_scripts_json"] == json.dumps(ext_scripts), (
            f"Expected external_scripts_json={json.dumps(ext_scripts)!r}, "
            f"got {deck_row['external_scripts_json']!r}"
        )

    def test_css_is_empty_string_when_deck_dict_has_no_css(self, factory, session_id):
        """deck.css should be '' (not None) when deck_dict has no css key."""
        deck_dict = {"title": "Deck", "slides": [_make_slide()]}

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
            )

        owner_id = _user_session_id_int(factory)
        deck_row = _query_deck(factory, owner_id)
        assert deck_row["css"] == ""
        assert deck_row["external_scripts_json"] == "[]"


# ---------------------------------------------------------------------------
# Test: orphan pruning in the same transaction
# ---------------------------------------------------------------------------


class TestOrphanPruning:
    def test_re_saving_shorter_deck_prunes_orphan_rows(self, factory, session_id):
        """3-slide deck → re-save with 1 slide → orphan rows at pos 1 and 2 are gone."""
        slides_3 = [
            _make_slide("<p>S0</p>"),
            _make_slide("<p>S1</p>"),
            _make_slide("<p>S2</p>"),
        ]
        deck_3 = _make_deck_dict(slides_3)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=3,
                deck_dict=deck_3,
            )

        owner_id = _user_session_id_int(factory)
        rows_after_3 = _query_slides(factory, owner_id)
        assert len(rows_after_3) == 3

        # Re-save with only 1 slide
        deck_1 = _make_deck_dict([_make_slide("<p>S0 updated</p>")])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_1,
            )

        rows_after_1 = _query_slides(factory, owner_id)
        assert len(rows_after_1) == 1, (
            f"Expected 1 row after prune, got {len(rows_after_1)}: {rows_after_1}"
        )
        assert rows_after_1[0]["position"] == 0
        assert rows_after_1[0]["html"] == "<p>S0 updated</p>"


# ---------------------------------------------------------------------------
# Test: re-saving updates existing rows (no duplicates)
# ---------------------------------------------------------------------------


class TestRowUpsert:
    def test_re_saving_same_deck_updates_not_duplicates(self, factory, session_id):
        """Saving twice must update existing rows, not insert new duplicates."""
        slides = [_make_slide("<p>Original</p>"), _make_slide("<p>Other</p>")]
        deck_dict = _make_deck_dict(slides)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=2,
                deck_dict=deck_dict,
            )

        owner_id = _user_session_id_int(factory)
        rows_first = _query_slides(factory, owner_id)
        assert len(rows_first) == 2

        # Re-save with updated HTML on slide 0
        slides_updated = [_make_slide("<p>Updated</p>"), _make_slide("<p>Other</p>")]
        deck_updated = _make_deck_dict(slides_updated)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=2,
                deck_dict=deck_updated,
            )

        rows_second = _query_slides(factory, owner_id)
        assert len(rows_second) == 2, (
            f"Expected 2 rows (no duplicates), got {len(rows_second)}"
        )
        assert rows_second[0]["html"] == "<p>Updated</p>"
        assert rows_second[1]["html"] == "<p>Other</p>"


# ---------------------------------------------------------------------------
# Test: deck_json is still written (dual-write, not cutover)
# ---------------------------------------------------------------------------


class TestDeckJsonStillWritten:
    def test_deck_json_column_is_still_populated(self, factory, session_id):
        """deck_json must be written alongside the session_slides rows."""
        slides = [_make_slide("<p>Slide 0</p>")]
        deck_dict = _make_deck_dict(slides)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
            )

        owner_id = _user_session_id_int(factory)
        deck_row = _query_deck(factory, owner_id)

        assert deck_row["deck_json"] is not None
        parsed = json.loads(deck_row["deck_json"])
        assert "slides" in parsed
        assert len(parsed["slides"]) == 1


# ---------------------------------------------------------------------------
# Test: version conflict raises VersionConflictError
# ---------------------------------------------------------------------------


class TestOptimisticLocking:
    def test_version_conflict_raises_error(self, factory, session_id):
        """expected_version mismatch must raise VersionConflictError."""
        deck_dict = _make_deck_dict([_make_slide()])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            # First save creates version=1
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_dict,
            )

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            with pytest.raises(VersionConflictError) as exc_info:
                mgr.save_slide_deck(
                    session_id=session_id,
                    title="Deck",
                    html_content="",
                    slide_count=1,
                    deck_dict=deck_dict,
                    expected_version=0,  # stale — current is 1
                )

        err = exc_info.value
        assert err.current_version == 1
        assert err.expected_version == 0


# ---------------------------------------------------------------------------
# Test: author-stamping still applied
# ---------------------------------------------------------------------------


class TestAuthorStamping:
    def test_slides_without_created_by_are_stamped(self, factory, session_id):
        """Slides lacking created_by must be stamped when modified_by is passed."""
        slides = [
            {"html": "<p>No author</p>", "scripts": ""},  # no created_by
        ]
        deck_dict = _make_deck_dict(slides)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="stamper@example.com",
            )

        owner_id = _user_session_id_int(factory)
        rows = _query_slides(factory, owner_id)
        assert len(rows) == 1
        assert rows[0]["created_by"] == "stamper@example.com"
        assert rows[0]["modified_by"] == "stamper@example.com"

    def test_slides_with_created_by_are_not_overwritten(self, factory, session_id):
        """Slides that already have created_by must not be overwritten."""
        slides = [
            {
                "html": "<p>Has author</p>",
                "scripts": "",
                "created_by": "original@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "original@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            }
        ]
        deck_dict = _make_deck_dict(slides)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="other@example.com",
            )

        owner_id = _user_session_id_int(factory)
        rows = _query_slides(factory, owner_id)
        assert len(rows) == 1
        assert rows[0]["created_by"] == "original@example.com"


# ---------------------------------------------------------------------------
# Test: verification_record is NOT touched by save_slide_deck (Task 7 owns it)
# ---------------------------------------------------------------------------


class TestVerificationRecordUntouched:
    def test_verification_record_stays_none_on_new_row(self, factory, session_id):
        """New rows must have verification_record=None; Task 7 sets it."""
        deck_dict = _make_deck_dict([_make_slide()])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_dict,
            )

        owner_id = _user_session_id_int(factory)
        rows = _query_slides(factory, owner_id)
        assert len(rows) == 1
        assert rows[0]["verification_record"] is None


# ---------------------------------------------------------------------------
# Test: no deck_dict → no session_slides rows, no crash
# ---------------------------------------------------------------------------


class TestNoDeckDict:
    def test_save_without_deck_dict_does_not_write_rows(self, factory, session_id):
        """Passing deck_dict=None must not write any session_slides rows."""
        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=0,
                deck_dict=None,
            )

        owner_id = _user_session_id_int(factory)
        rows = _query_slides(factory, owner_id)
        assert rows == []
        assert "version" in result  # return dict still present

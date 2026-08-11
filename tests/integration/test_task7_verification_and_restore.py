"""Integration tests for Task 7: per-row verification write and restore re-materialisation.

Tests cover:
  Part A: write_slide_verification merge semantics
  Part C: create_version snapshots deck_spec_json; restore_version re-materialises
          session_slides rows, restores css/external_scripts, prunes phantom rows,
          and copies deck_spec_json back to the deck.

Pattern: in-memory SQLite via
  patch("src.api.services.session_manager.get_db_session", fake_get_db_session)
— same approach used in test_save_slide_deck_dual_write.py / test_get_slide_deck_row_read.py.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)
from src.utils.slide_hash import compute_slide_hash


# ---------------------------------------------------------------------------
# Fixtures (mirror prior task pattern exactly)
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


def _user_session_id_int(factory) -> int:
    db = factory()
    us = db.query(UserSession).one()
    pk = us.id
    db.close()
    return pk


def _query_slides(factory, deck_owner_id: int) -> list[dict]:
    db = factory()
    rows = (
        db.query(SessionSlide)
        .filter(SessionSlide.session_id == deck_owner_id)
        .order_by(SessionSlide.position)
        .all()
    )
    result = []
    for r in rows:
        result.append({
            "session_id": r.session_id,
            "position": r.position,
            "html": r.html,
            "scripts": r.scripts,
            "verification_record": r.verification_record,
        })
    db.close()
    return result


def _make_deck_dict(
    slides: list,
    css: str = "body{background:white}",
    external_scripts: list | None = None,
    title: str = "Test Deck",
    deck_spec: str | None = None,
) -> dict:
    if external_scripts is None:
        external_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
    return {
        "title": title,
        "css": css,
        "external_scripts": external_scripts,
        "slides": slides,
    }


def _make_slide(html: str = "<p>slide</p>", scripts: str = "") -> dict:
    return {
        "html": html,
        "scripts": scripts,
        "created_by": "author@example.com",
        "created_at": "2024-01-01T00:00:00Z",
        "modified_by": "author@example.com",
        "modified_at": "2024-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Part A: write_slide_verification merge semantics
# ---------------------------------------------------------------------------


class TestWriteSlideVerification:
    """Part A — write_slide_verification writes and merges per-row records."""

    def test_first_write_creates_entry(self, factory, session_id):
        """Writing a verdict for hash_a stores {hash_a: verdict} in the row."""
        fake_db = _make_fake_get_db_session(factory)
        owner_id = _user_session_id_int(factory)

        deck_dict = _make_deck_dict([_make_slide("<p>Slide zero</p>")])

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )

        slide_html = "<p>Slide zero</p>"
        content_hash = compute_slide_hash(slide_html)
        verdict = {"score": 95, "rating": "excellent"}

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.write_slide_verification(
                session_id=session_id,
                position=0,
                verification_record={content_hash: verdict},
            )

        rows = _query_slides(factory, owner_id)
        assert len(rows) == 1
        assert rows[0]["verification_record"] is not None
        stored = json.loads(rows[0]["verification_record"])
        assert content_hash in stored
        assert stored[content_hash]["score"] == 95

    def test_second_write_merges_not_overwrites(self, factory, session_id):
        """After editing HTML (new hash_b), hash_a verdict must survive.

        This is the key invariant: if the user reverts their edit, the
        original verdict is still present and get_slide_deck returns it.
        The test fails against an assignment implementation (not merge).
        """
        fake_db = _make_fake_get_db_session(factory)
        owner_id = _user_session_id_int(factory)

        html_a = "<p>Original content</p>"
        html_b = "<p>Edited content — different hash</p>"
        hash_a = compute_slide_hash(html_a)
        hash_b = compute_slide_hash(html_b)
        assert hash_a != hash_b, "test setup: html_a and html_b must produce different hashes"

        verdict_a = {"score": 80, "rating": "good"}
        verdict_b = {"score": 95, "rating": "excellent"}

        # Save an initial deck with html_a
        deck_dict = _make_deck_dict([_make_slide(html_a)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )

        # Write verdict for hash_a
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.write_slide_verification(
                session_id=session_id,
                position=0,
                verification_record={hash_a: verdict_a},
            )

        # Simulate edit: save deck with html_b
        deck_dict_b = _make_deck_dict([_make_slide(html_b)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict_b,
                modified_by="author@example.com",
            )

        # Write verdict for hash_b
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.write_slide_verification(
                session_id=session_id,
                position=0,
                verification_record={hash_b: verdict_b},
            )

        # Both hash_a AND hash_b must be present in the row record.
        rows = _query_slides(factory, owner_id)
        assert len(rows) == 1
        stored = json.loads(rows[0]["verification_record"])

        assert hash_a in stored, (
            f"hash_a verdict was lost after hash_b write — assign bug. "
            f"stored keys: {list(stored.keys())}"
        )
        assert hash_b in stored, "hash_b verdict not written"
        assert stored[hash_a]["score"] == 80
        assert stored[hash_b]["score"] == 95

    def test_row_path_reads_back_correct_verdict(self, factory, session_id):
        """get_slide_deck (row path) returns the verdict for the current content hash."""
        fake_db = _make_fake_get_db_session(factory)

        slide_html = "<p>Current slide content</p>"
        content_hash = compute_slide_hash(slide_html)
        verdict = {"score": 90, "rating": "great"}

        deck_dict = _make_deck_dict([_make_slide(slide_html)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )
            mgr.write_slide_verification(
                session_id=session_id,
                position=0,
                verification_record={content_hash: verdict},
            )

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        slides = result.get("slides", [])
        assert len(slides) == 1
        assert slides[0]["verification"] is not None
        assert slides[0]["verification"]["score"] == 90
        assert slides[0]["verification"]["rating"] == "great"

    def test_noop_for_missing_row(self, factory, session_id):
        """write_slide_verification on a nonexistent position logs a warning and returns."""
        # No deck/rows saved — position 99 doesn't exist.
        # Should not raise.
        fake_db = _make_fake_get_db_session(factory)

        # Need a deck to exist so _get_session_or_raise works
        deck_dict = _make_deck_dict([_make_slide("<p>slide</p>")])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )
            # Position 99 does not exist
            mgr.write_slide_verification(
                session_id=session_id,
                position=99,
                verification_record={"hash": {"score": 0}},
            )
        # No exception raised — test passes


# ---------------------------------------------------------------------------
# Part C: create_version snapshots deck_spec_json; restore_version re-materialises rows
# ---------------------------------------------------------------------------


class TestRestoreVersionRowRematerialisation:
    """Part C — restore_version re-materialises session_slides rows.

    Task 5's read path prefers session_slides rows whenever ANY rows exist.
    Without row re-materialisation, restore writes only deck_json which nothing reads —
    the deck does not change from the user's perspective.
    """

    def _save_deck_with_spec(
        self,
        factory,
        session_id: str,
        slides: list,
        css: str,
        external_scripts: list,
        deck_spec_json: str | None,
        title: str = "Test Deck",
    ) -> None:
        """Save a deck and optionally set deck_spec_json on the deck row directly."""
        fake_db = _make_fake_get_db_session(factory)
        deck_dict = {
            "title": title,
            "css": css,
            "external_scripts": external_scripts,
            "slides": slides,
        }
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title=title,
                html_content="<html></html>",
                slide_count=len(slides),
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )

        if deck_spec_json is not None:
            # Directly set deck_spec_json on the deck row (mimics Task 9 foreman write)
            db = factory()
            owner = db.query(UserSession).filter_by(session_id=session_id).one()
            deck = db.query(SessionSlideDeck).filter_by(session_id=owner.id).one()
            deck.deck_spec_json = deck_spec_json
            db.commit()
            db.close()

    def test_restore_returns_original_slides_not_edited_ones(self, factory, session_id):
        """After save → edit → restore, get_slide_deck returns the SAVED slides.

        This is the core C7 correctness guarantee.  Without row re-materialisation
        the row path continues to serve the post-edit rows even after restore.
        """
        fake_db = _make_fake_get_db_session(factory)

        # 1. Save version 1 (3 slides)
        slides_v1 = [
            _make_slide("<p>Original slide 0</p>"),
            _make_slide("<p>Original slide 1</p>"),
            _make_slide("<p>Original slide 2</p>"),
        ]
        self._save_deck_with_spec(
            factory, session_id, slides_v1, css="body{color:red}", external_scripts=[], deck_spec_json=None
        )

        # Create a save point
        owner_id = _user_session_id_int(factory)
        deck_dict_v1 = _make_deck_dict(slides_v1, css="body{color:red}", external_scripts=[])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            version_info = mgr.create_version(
                session_id=session_id,
                description="Initial save",
                deck_dict=deck_dict_v1,
            )
        version_number = version_info["version_number"]

        # 2. Edit: save a different deck (2 slides, different HTML, different css)
        slides_edited = [
            _make_slide("<p>Edited slide 0</p>"),
            _make_slide("<p>Edited slide 1</p>"),
        ]
        self._save_deck_with_spec(
            factory, session_id, slides_edited, css="body{color:blue}", external_scripts=["https://example.com/chart.js"], deck_spec_json=None
        )

        # 3. Restore to version 1
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            with patch("src.api.services.session_manager.SessionManager.require_editing_lock"):
                mgr = SessionManager()
                mgr.restore_version(session_id, version_number)

        # 4. Read via get_slide_deck (row path) — must see restored slides
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        slides = result.get("slides", [])
        assert len(slides) == 3, (
            f"Expected 3 restored slides, got {len(slides)}. "
            f"Restore failed to re-materialise rows."
        )
        htmls = [s["html"] for s in slides]
        assert "<p>Original slide 0</p>" in htmls[0], (
            f"Expected original HTML at position 0, got {htmls[0]!r}"
        )
        assert "<p>Original slide 2</p>" in htmls[2], (
            f"Expected original HTML at position 2, got {htmls[2]!r}"
        )

    def test_restore_prunes_phantom_rows_when_shorter_deck(self, factory, session_id):
        """Restoring a shorter deck must prune rows beyond the restored slide count.

        Without pruning, the row path serves phantom slides — extra slides that
        were added after the save point become visible again after restore.
        """
        fake_db = _make_fake_get_db_session(factory)

        # 1. Save a 2-slide deck and create a save point
        slides_v1 = [
            _make_slide("<p>Short deck slide 0</p>"),
            _make_slide("<p>Short deck slide 1</p>"),
        ]
        self._save_deck_with_spec(
            factory, session_id, slides_v1, css="", external_scripts=[], deck_spec_json=None
        )
        deck_dict_v1 = _make_deck_dict(slides_v1, css="", external_scripts=[])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            version_info = mgr.create_version(
                session_id=session_id,
                description="2-slide save",
                deck_dict=deck_dict_v1,
            )
        version_number = version_info["version_number"]

        # 2. Edit: save a 4-slide deck
        slides_v2 = [
            _make_slide("<p>Expanded slide 0</p>"),
            _make_slide("<p>Expanded slide 1</p>"),
            _make_slide("<p>Expanded slide 2</p>"),
            _make_slide("<p>Expanded slide 3</p>"),
        ]
        self._save_deck_with_spec(
            factory, session_id, slides_v2, css="", external_scripts=[], deck_spec_json=None
        )

        # Verify 4 rows exist before restore
        owner_id = _user_session_id_int(factory)
        rows_before = _query_slides(factory, owner_id)
        assert len(rows_before) == 4

        # 3. Restore to the 2-slide save point
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            with patch("src.api.services.session_manager.SessionManager.require_editing_lock"):
                mgr = SessionManager()
                mgr.restore_version(session_id, version_number)

        # 4. Only 2 rows must remain
        rows_after = _query_slides(factory, owner_id)
        assert len(rows_after) == 2, (
            f"Expected 2 rows after restore of 2-slide deck, got {len(rows_after)}. "
            f"Phantom rows were not pruned."
        )

        # And get_slide_deck must show 2 slides
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)
        assert len(result["slides"]) == 2

    def test_restore_brings_back_css_and_external_scripts(self, factory, session_id):
        """css and external_scripts_json are restored along with the slides.

        The row-read path reconstructs the deck dict from deck-level columns;
        without restoring css/external_scripts_json, every export after restore
        loses the stylesheet and Chart.js CDN.
        """
        fake_db = _make_fake_get_db_session(factory)

        css_v1 = "body { background: red; font-size: 18px; }"
        ext_v1 = ["https://cdn.jsdelivr.net/npm/chart.js", "https://v1-lib.example.com"]

        slides_v1 = [_make_slide("<p>V1 slide</p>")]
        self._save_deck_with_spec(
            factory, session_id, slides_v1, css=css_v1, external_scripts=ext_v1, deck_spec_json=None
        )
        deck_dict_v1 = _make_deck_dict(slides_v1, css=css_v1, external_scripts=ext_v1)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            version_info = mgr.create_version(
                session_id=session_id,
                description="V1 save",
                deck_dict=deck_dict_v1,
            )
        version_number = version_info["version_number"]

        # Edit: different css and external_scripts
        css_v2 = "body { background: blue; }"
        ext_v2 = ["https://cdn.jsdelivr.net/npm/chart.js@4"]
        slides_v2 = [_make_slide("<p>V2 slide</p>")]
        self._save_deck_with_spec(
            factory, session_id, slides_v2, css=css_v2, external_scripts=ext_v2, deck_spec_json=None
        )

        # Restore to v1
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            with patch("src.api.services.session_manager.SessionManager.require_editing_lock"):
                mgr = SessionManager()
                mgr.restore_version(session_id, version_number)

        # get_slide_deck must return v1's css and external_scripts
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result["css"] == css_v1, (
            f"Expected css={css_v1!r}, got {result['css']!r}"
        )
        assert result["external_scripts"] == ext_v1, (
            f"Expected external_scripts={ext_v1!r}, got {result['external_scripts']!r}"
        )

    def test_restore_copies_deck_spec_json_back(self, factory, session_id):
        """deck_spec_json from the save point is copied back to the deck row (C9).

        Without this, a restored deck would be described by the post-edit spec,
        and PR3's §4.4 trigger would re-apply the edited spec to the restored
        slides, silently undoing the restore.
        """
        fake_db = _make_fake_get_db_session(factory)

        spec_v1 = json.dumps({"schema_version": "1.0", "theme": "dark"})

        slides_v1 = [_make_slide("<p>Spec V1 slide</p>")]
        self._save_deck_with_spec(
            factory, session_id, slides_v1, css="", external_scripts=[], deck_spec_json=spec_v1
        )
        deck_dict_v1 = _make_deck_dict(slides_v1)

        # Create version — must snapshot deck_spec_json
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            version_info = mgr.create_version(
                session_id=session_id,
                description="Spec save",
                deck_dict=deck_dict_v1,
            )
        version_number = version_info["version_number"]

        # Verify deck_spec_json was snapshotted in the version row
        db = factory()
        owner = db.query(UserSession).filter_by(session_id=session_id).one()
        version_row = db.query(SlideDeckVersion).filter_by(
            session_id=owner.id, version_number=version_number
        ).one()
        assert version_row.deck_spec_json == spec_v1, (
            f"create_version did not snapshot deck_spec_json. "
            f"Got: {version_row.deck_spec_json!r}"
        )
        db.close()

        # Edit: change deck_spec_json to a different spec
        spec_v2 = json.dumps({"schema_version": "2.0", "theme": "light"})
        slides_v2 = [_make_slide("<p>Spec V2 slide</p>")]
        self._save_deck_with_spec(
            factory, session_id, slides_v2, css="", external_scripts=[], deck_spec_json=spec_v2
        )

        # Restore to v1
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            with patch("src.api.services.session_manager.SessionManager.require_editing_lock"):
                mgr = SessionManager()
                mgr.restore_version(session_id, version_number)

        # deck_spec_json must be restored to spec_v1
        db = factory()
        owner = db.query(UserSession).filter_by(session_id=session_id).one()
        deck_row = db.query(SessionSlideDeck).filter_by(session_id=owner.id).one()
        assert deck_row.deck_spec_json == spec_v1, (
            f"restore_version did not copy deck_spec_json back. "
            f"Expected {spec_v1!r}, got {deck_row.deck_spec_json!r}"
        )
        db.close()

    def test_restore_migrates_verification_onto_rows(self, factory, session_id):
        """Restored verification_map_json is migrated to per-row verification_record.

        After restore, the row for a slide with a known content hash must have
        that hash's verdict in its verification_record.
        """
        fake_db = _make_fake_get_db_session(factory)

        slide_html = "<p>Verified slide</p>"
        content_hash = compute_slide_hash(slide_html)
        verdict = {"score": 85, "rating": "good", "explanation": "Accurate"}

        slides_v1 = [_make_slide(slide_html)]
        deck_dict_v1 = _make_deck_dict(slides_v1)
        verification_map = {content_hash: verdict}

        self._save_deck_with_spec(
            factory, session_id, slides_v1, css="", external_scripts=[], deck_spec_json=None
        )

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            version_info = mgr.create_version(
                session_id=session_id,
                description="With verification",
                deck_dict=deck_dict_v1,
                verification_map=verification_map,
            )
        version_number = version_info["version_number"]

        # Edit: different content
        slides_v2 = [_make_slide("<p>Unverified slide</p>")]
        self._save_deck_with_spec(
            factory, session_id, slides_v2, css="", external_scripts=[], deck_spec_json=None
        )

        # Restore to v1
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            with patch("src.api.services.session_manager.SessionManager.require_editing_lock"):
                mgr = SessionManager()
                mgr.restore_version(session_id, version_number)

        # get_slide_deck must return the verdict for the restored slide
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        slides = result.get("slides", [])
        assert len(slides) == 1
        assert slides[0]["verification"] is not None, (
            "Restored verification was not migrated onto the row"
        )
        assert slides[0]["verification"]["score"] == 85


# ---------------------------------------------------------------------------
# get_verification_map — aggregate from per-row records
# ---------------------------------------------------------------------------


class TestGetVerificationMapAggregation:
    """get_verification_map must aggregate from session_slides rows.

    Before this fix, the method read the legacy blob which nothing writes any
    more (save_verification was deleted).  It now walks the rows and merges all
    {content_hash: verdict} entries.
    """

    def test_aggregates_verdicts_from_multiple_rows(self, factory, session_id):
        """A deck with verdicts on 2+ different slides returns all of them."""
        fake_db = _make_fake_get_db_session(factory)

        html_0 = "<p>Slide zero</p>"
        html_1 = "<p>Slide one</p>"
        hash_0 = compute_slide_hash(html_0)
        hash_1 = compute_slide_hash(html_1)
        verdict_0 = {"score": 80, "rating": "good"}
        verdict_1 = {"score": 95, "rating": "excellent"}

        deck_dict = _make_deck_dict([_make_slide(html_0), _make_slide(html_1)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=2,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )
            mgr.write_slide_verification(session_id, 0, {hash_0: verdict_0})
            mgr.write_slide_verification(session_id, 1, {hash_1: verdict_1})

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_verification_map(session_id)

        assert hash_0 in result, f"hash_0 missing from aggregated map. keys: {list(result)}"
        assert hash_1 in result, f"hash_1 missing from aggregated map. keys: {list(result)}"
        assert result[hash_0]["score"] == 80
        assert result[hash_1]["score"] == 95

    def test_aggregates_multiple_hashes_from_single_row(self, factory, session_id):
        """A row with two hashes (from edit/revert cycle) contributes both to the map."""
        fake_db = _make_fake_get_db_session(factory)

        html_a = "<p>Original</p>"
        html_b = "<p>Edited content different hash</p>"
        hash_a = compute_slide_hash(html_a)
        hash_b = compute_slide_hash(html_b)
        assert hash_a != hash_b

        # Write two verdicts to the same row (position 0)
        deck_dict = _make_deck_dict([_make_slide(html_a)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )
            mgr.write_slide_verification(session_id, 0, {hash_a: {"score": 80}})

        # Edit: save html_b
        deck_dict_b = _make_deck_dict([_make_slide(html_b)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict_b,
                modified_by="author@example.com",
            )
            mgr.write_slide_verification(session_id, 0, {hash_b: {"score": 95}})

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_verification_map(session_id)

        assert hash_a in result, "hash_a lost from aggregation"
        assert hash_b in result, "hash_b missing from aggregation"
        assert result[hash_a]["score"] == 80
        assert result[hash_b]["score"] == 95

    def test_legacy_fallback_when_no_rows(self, factory, session_id):
        """When no session_slides rows exist, falls back to the blob."""
        # Seed a deck row with verification_map blob but NO session_slides rows.
        db = factory()
        owner = db.query(UserSession).filter_by(session_id=session_id).one()
        blob_map = {"legacy_hash": {"score": 70, "rating": "ok"}}
        deck = SessionSlideDeck(
            session_id=owner.id,
            title="Legacy deck",
            html_content="",
            slide_count=1,
            deck_json="{}",
            version=1,
            verification_map=json.dumps(blob_map),
        )
        db.add(deck)
        db.commit()
        db.close()

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_verification_map(session_id)

        assert "legacy_hash" in result, f"Legacy fallback did not return blob content. keys: {list(result)}"
        assert result["legacy_hash"]["score"] == 70

    def test_end_to_end_verdict_survives_into_save_point(self, factory, session_id):
        """Write a verdict → create a save point → SlideDeckVersion.verification_map_json contains it.

        This is the chat_service.py:2150 path: get_verification_map feeds create_version.
        Before this fix, get_verification_map returned {} (empty blob) so all verdicts
        were silently dropped from every save point.
        """
        fake_db = _make_fake_get_db_session(factory)

        slide_html = "<p>Chart shows Q4 revenue $5M</p>"
        content_hash = compute_slide_hash(slide_html)
        verdict = {"score": 92, "rating": "excellent", "explanation": "Accurate"}

        # Save deck
        deck_dict = _make_deck_dict([_make_slide(slide_html)])
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict,
                modified_by="author@example.com",
            )

        # Write verdict
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.write_slide_verification(session_id, 0, {content_hash: verdict})

        # Create a save point — must snapshot the verdict
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            verification_map = mgr.get_verification_map(session_id)
            version_info = mgr.create_version(
                session_id=session_id,
                description="After verification",
                deck_dict=deck_dict,
                verification_map=verification_map,
            )

        # Inspect the saved SlideDeckVersion row directly
        db = factory()
        owner = db.query(UserSession).filter_by(session_id=session_id).one()
        version_row = db.query(SlideDeckVersion).filter_by(
            session_id=owner.id,
            version_number=version_info["version_number"],
        ).one()
        saved_map_raw = version_row.verification_map_json
        db.close()

        assert saved_map_raw is not None, (
            "SlideDeckVersion.verification_map_json is None — verdicts were not snapshotted"
        )
        saved_map = json.loads(saved_map_raw)
        assert content_hash in saved_map, (
            f"content_hash not in saved verification_map_json. "
            f"keys present: {list(saved_map.keys())}"
        )
        assert saved_map[content_hash]["score"] == 92

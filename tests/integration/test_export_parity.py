"""PRD §3 no-regression gate — export parity tests (Task 8).

Verifies that deck-level fields (css, external_scripts, scripts) and per-slide
html survive the legacy → backfill → row-read pipeline without loss, and that
the HTML produced by build_slide_html is byte-identical between the legacy path
and the row path for the same logical deck.

Anchored on:
  - build_slide_html (src/api/routes/export.py:40) — the single funnel for all
    export chains; reads exactly slide["html"], slide_deck["external_scripts"],
    slide_deck["css"], slide_deck["scripts"].
  - backfill_session (scripts/backfill_session_slides.py) — "run the backfill"
    for existing deck_json-only rows.
  - get_slide_deck (src.api.services.session_manager.SessionManager) — the read
    path after backfill.

Pattern: in-memory SQLite, _make_fake_get_db_session patch — same as
tests/integration/test_get_slide_deck_row_read.py (Task 5).

Google Slides check: HtmlToGoogleSlidesConverter requires real Google API
credentials and a live WorkspaceClient SDK token.  There is no subset of its
init/convert surface that can be driven hermetically without network access.
Accordingly the Google Slides parity check is explicitly skipped rather than
stubbed with a vacuous assertion.
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
from scripts.backfill_session_slides import backfill_session
from src.api.routes.export import build_slide_html
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    UserSession,
)


# ---------------------------------------------------------------------------
# Fixtures (mirror test_get_slide_deck_row_read.py exactly)
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
        session_id="export-parity-session-001",
        created_by="test-user@example.com",
    )
    db.add(user_session)
    db.commit()
    db.close()
    return "export-parity-session-001"


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


def _user_session_id_int(factory) -> int:
    """Return the integer PK of the first UserSession in the DB."""
    db = factory()
    us = db.query(UserSession).first()
    pk = us.id
    db.close()
    return pk


def _seed_legacy_deck(
    factory,
    session_id_int: int,
    deck_dict: dict,
):
    """Insert a SessionSlideDeck with deck_json but WITHOUT session_slides rows.

    Simulates the pre-backfill state: deck_json is populated, per-column fields
    (css, external_scripts_json) are NULL (as they would be for legacy rows that
    predate the schema migration).
    """
    db = factory()
    deck = SessionSlideDeck(
        session_id=session_id_int,
        title=deck_dict.get("title", "Test Deck"),
        html_content="<html>combined</html>",
        scripts_content=deck_dict.get("scripts", ""),
        slide_count=len(deck_dict.get("slides", [])),
        deck_json=json.dumps(deck_dict),
        version=1,
        # css and external_scripts_json intentionally NULL — pre-backfill state
        css=None,
        external_scripts_json=None,
    )
    db.add(deck)
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Test 1: deck-level fields survive legacy → backfill → row-read
# ---------------------------------------------------------------------------


class TestRowPathPreservesDeckLevelFields:
    """PRD §3 guard: css, external_scripts, scripts, and per-slide html must not
    be silently dropped when transitioning from legacy deck_json to row path.

    Failure mode this guards: if backfill_session does NOT write deck.css /
    deck.external_scripts_json, get_slide_deck returns css="" and
    external_scripts=[] — every export loses the stylesheet and Chart.js CDN.
    """

    def test_row_path_preserves_deck_level_fields(self, factory, session_id):
        """Seed legacy, backfill, then assert css/external_scripts/scripts/html survived."""
        css_val = "body { font-family: sans-serif; background: #1e1e1e; }"
        ext_scripts = [
            "https://cdn.jsdelivr.net/npm/chart.js",
            "https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels",
        ]
        scripts_val = "(function() { Chart.defaults.font.size = 14; })();"
        slides = [
            {
                "html": "<div class='slide'>Slide One</div>",
                "scripts": "console.log('s1');",
                "slide_id": "s1",
                "created_by": "author@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "author@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            },
            {
                "html": "<div class='slide'>Slide Two</div>",
                "scripts": "",
                "slide_id": "s2",
                "created_by": "author@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "author@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            },
        ]
        deck_dict = {
            "title": "Parity Deck",
            "css": css_val,
            "external_scripts": ext_scripts,
            "scripts": scripts_val,
            "slides": slides,
        }

        owner_id = _user_session_id_int(factory)
        _seed_legacy_deck(factory, owner_id, deck_dict)

        # Run backfill (live — not dry_run) using a raw DB session.
        db = factory()
        backfill_session(db, owner_id, dry_run=False)
        db.close()

        # Read back via the row path.
        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None, "get_slide_deck returned None after backfill"

        # --- Deck-level assertions ---
        assert result["css"] == css_val, (
            f"css lost after backfill. Expected:\n{css_val!r}\nGot:\n{result['css']!r}"
        )
        assert result["external_scripts"] == ext_scripts, (
            f"external_scripts lost after backfill.\n"
            f"Expected: {ext_scripts!r}\nGot: {result['external_scripts']!r}"
        )
        assert result["scripts"] == scripts_val, (
            f"scripts lost after backfill. Expected:\n{scripts_val!r}\nGot:\n{result['scripts']!r}"
        )

        # --- Per-slide assertions ---
        assert len(result["slides"]) == 2, (
            f"Expected 2 slides after backfill, got {len(result['slides'])}"
        )
        assert result["slides"][0]["html"] == slides[0]["html"], (
            f"Slide 0 html lost. Got: {result['slides'][0]['html']!r}"
        )
        assert result["slides"][1]["html"] == slides[1]["html"], (
            f"Slide 1 html lost. Got: {result['slides'][1]['html']!r}"
        )
        assert result["slides"][0]["scripts"] == slides[0]["scripts"], (
            f"Slide 0 scripts lost. Got: {result['slides'][0]['scripts']!r}"
        )


# ---------------------------------------------------------------------------
# Test 2: build_slide_html parity — legacy path vs row path must be identical
# ---------------------------------------------------------------------------


class TestBuildSlideHtmlParity:
    """For the same logical deck, build_slide_html must produce byte-identical
    output whether the deck dict comes from the legacy path (deck_json) or the
    row path (after backfill + get_slide_deck).

    This is the core PRD §3 regression gate: if css or external_scripts are
    dropped on the row path, the export HTML would diverge (missing <style>
    block or missing CDN <script> tags), which silently breaks every chart slide.
    """

    def test_build_slide_html_parity_legacy_vs_row(self, factory, session_id):
        """HTML produced by build_slide_html must be identical per-slide between
        the legacy deck_json path and the row path after backfill."""
        css_val = ".card { padding: 1rem; border-radius: 8px; }"
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
        scripts_val = "(function() { Chart.defaults.font.size = 12; })();"
        slides = [
            {
                "html": "<div><h1>Title Slide</h1><canvas id='chart0'></canvas></div>",
                "scripts": "console.log('chart-init');",
                "slide_id": "slide-a",
                "created_by": "author@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "author@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            },
            {
                "html": "<div><p>Content slide with no chart</p></div>",
                "scripts": "",
                "slide_id": "slide-b",
                "created_by": "author@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "author@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            },
        ]
        deck_dict = {
            "title": "Parity HTML Deck",
            "css": css_val,
            "external_scripts": ext_scripts,
            "scripts": scripts_val,
            "slides": slides,
        }

        owner_id = _user_session_id_int(factory)
        _seed_legacy_deck(factory, owner_id, deck_dict)

        # --- Build HTML via legacy path (deck_json directly) ---
        legacy_htmls = [
            build_slide_html(slide, deck_dict) for slide in slides
        ]

        # --- Run backfill ---
        db = factory()
        backfill_session(db, owner_id, dry_run=False)
        db.close()

        # --- Read back via row path ---
        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            row_deck = mgr.get_slide_deck(session_id)

        assert row_deck is not None

        # --- Build HTML via row path ---
        row_htmls = [
            build_slide_html(slide, row_deck) for slide in row_deck["slides"]
        ]

        # --- Per-slide comparison ---
        assert len(row_htmls) == len(legacy_htmls), (
            f"Slide count mismatch: row={len(row_htmls)} legacy={len(legacy_htmls)}"
        )
        for i, (row_html, legacy_html) in enumerate(zip(row_htmls, legacy_htmls)):
            assert row_html == legacy_html, (
                f"Slide {i} HTML diverges between legacy path and row path.\n"
                f"First difference at char "
                f"{next((j for j,(a,b) in enumerate(zip(row_html,legacy_html)) if a!=b), len(row_html))!r}.\n"
                f"Row path length: {len(row_html)}, legacy path length: {len(legacy_html)}.\n"
                f"Row   starts: {row_html[:200]!r}\n"
                f"Legacy starts: {legacy_html[:200]!r}"
            )


# ---------------------------------------------------------------------------
# Test 3: orphan rows are pruned when the deck shrinks
# ---------------------------------------------------------------------------


class TestOrphanRowsPruned:
    """When a deck is re-saved with fewer slides, orphan session_slides rows at
    higher positions must be pruned so get_slide_deck returns exactly the current
    slide count.

    Without pruning, get_slide_deck (which prefers rows over deck_json when ANY
    rows exist) returns the phantom extra slide — silently corrupting every export.
    """

    def test_orphan_rows_pruned_when_deck_shrinks(self, factory, session_id):
        """Seed 2 slides via save_slide_deck, then re-save with 1 slide.
        get_slide_deck must return exactly 1 slide (no phantom row at position 1).
        """
        css_val = ".slide { color: #fff; }"
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
        slides_2 = [
            {
                "html": "<div>Slide One</div>",
                "scripts": "",
                "slide_id": "slide-1",
                "created_by": "author@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "author@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            },
            {
                "html": "<div>Slide Two</div>",
                "scripts": "",
                "slide_id": "slide-2",
                "created_by": "author@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "author@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            },
        ]
        deck_dict_2 = {
            "title": "Shrink Deck",
            "css": css_val,
            "external_scripts": ext_scripts,
            "scripts": "",
            "slides": slides_2,
        }

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Shrink Deck",
                html_content="<html></html>",
                slide_count=2,
                deck_dict=deck_dict_2,
                modified_by="test-user@example.com",
            )

        # Confirm 2 slides are readable.
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            result_2 = mgr.get_slide_deck(session_id)
        assert result_2 is not None
        assert len(result_2["slides"]) == 2, (
            f"Expected 2 slides initially, got {len(result_2['slides'])}"
        )

        # Re-save with only 1 slide.
        slides_1 = [slides_2[0]]
        deck_dict_1 = dict(deck_dict_2, slides=slides_1)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr.save_slide_deck(
                session_id=session_id,
                title="Shrink Deck",
                html_content="<html></html>",
                slide_count=1,
                deck_dict=deck_dict_1,
                modified_by="test-user@example.com",
            )

        # Must return exactly 1 slide — no phantom row at position 1.
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            result_1 = mgr.get_slide_deck(session_id)

        assert result_1 is not None
        assert len(result_1["slides"]) == 1, (
            f"Orphan rows not pruned: expected 1 slide after shrink, "
            f"got {len(result_1['slides'])}. "
            f"Slides: {[s['html'] for s in result_1['slides']]!r}"
        )
        assert result_1["slides"][0]["html"] == "<div>Slide One</div>", (
            f"Wrong slide survived: {result_1['slides'][0]['html']!r}"
        )


# ---------------------------------------------------------------------------
# Google Slides parity — explicitly skipped (requires network + credentials)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "HtmlToGoogleSlidesConverter requires real Google API credentials "
        "and a live Databricks WorkspaceClient SDK token.  There is no "
        "hermetic subset of the converter that can be driven without network "
        "access.  A vacuous stub would assert nothing; an honest omission is "
        "better.  This check should be added as a contract/integration test "
        "once a credential-free shim exists for the Google Slides API client."
    )
)
def test_google_slides_parity_skipped():
    """Placeholder: Google Slides parity cannot be tested hermetically."""
    pass

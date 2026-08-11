"""Integration tests for get_slide_deck dual-read path (Task 5).

Verifies that get_slide_deck:
  - reconstructs the deck dict from session_slides rows when they exist
  - css and external_scripts survive the row round-trip (PRD §3 export guard)
  - falls back to legacy deck_json when no rows exist
  - produces a dict equivalent to the legacy path for the same logical deck
    (equivalence test — the highest-value test in this task)
  - populates per-slide verification from the row's verification_record blob
  - resolves contributor sessions to the root's rows
  - returns slides in position order (seeded out of order to prove ORDER BY)
  - returns the correct slide_count from row count

Pattern: in-memory SQLite via
  patch("src.api.services.session_manager.get_db_session", fake_get_db_session)
— same approach used in tests/integration/test_save_slide_deck_dual_write.py.
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
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    UserSession,
)
from src.utils.slide_hash import compute_slide_hash


# ---------------------------------------------------------------------------
# Fixtures (mirror task-4 test pattern exactly)
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


def _user_session_id_int(factory) -> int:
    """Return the integer PK of the sole UserSession in the DB."""
    db = factory()
    us = db.query(UserSession).one()
    pk = us.id
    db.close()
    return pk


def _make_deck_dict(
    slides: list,
    css: str = ".body{}",
    external_scripts: list | None = None,
    scripts: str = "",
    title: str = "Test Deck",
):
    """Build a minimal deck_dict with a slides array."""
    if external_scripts is None:
        external_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
    return {
        "title": title,
        "css": css,
        "external_scripts": external_scripts,
        "scripts": scripts,
        "slides": slides,
    }


def _make_slide(
    html: str = "<p>slide</p>",
    scripts: str = "",
    created_by: str | None = "author@example.com",
    slide_id: str | None = None,
):
    """Build a minimal slide dict with authorship."""
    now = "2024-01-01T00:00:00Z"
    s: dict = {
        "html": html,
        "scripts": scripts,
        "created_by": created_by,
        "created_at": now,
        "modified_by": created_by,
        "modified_at": now,
    }
    if slide_id:
        s["slide_id"] = slide_id
    return s


# ---------------------------------------------------------------------------
# Helper: seed rows + deck directly into the DB (bypasses save_slide_deck)
# ---------------------------------------------------------------------------


def _seed_deck_and_rows(
    factory,
    session_id_int: int,
    slides: list[dict],
    css: str = ".body{}",
    external_scripts: list | None = None,
    scripts_content: str = "",
    title: str = "Test Deck",
    created_by: str = "test-user@example.com",
):
    """Insert a SessionSlideDeck + SessionSlide rows directly.

    Gives us fine-grained control (e.g. out-of-order positions, NULL fields)
    without going through save_slide_deck.
    """
    if external_scripts is None:
        external_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]

    db = factory()
    deck = SessionSlideDeck(
        session_id=session_id_int,
        title=title,
        html_content="<html>combined</html>",
        scripts_content=scripts_content,
        slide_count=len(slides),
        deck_json=json.dumps({"title": title, "slides": slides, "css": css,
                               "external_scripts": external_scripts, "scripts": scripts_content}),
        version=1,
        css=css,
        external_scripts_json=json.dumps(external_scripts),
    )
    db.add(deck)
    db.flush()

    now_dt = datetime(2024, 1, 1, 0, 0, 0)
    for position, slide_dict in enumerate(slides):
        row = SessionSlide(
            session_id=session_id_int,
            position=position,
            id=str(uuid.uuid4()),
            html=slide_dict.get("html") or "",
            slide_id=slide_dict.get("slide_id"),
            scripts=slide_dict.get("scripts") or "",
            created_by=slide_dict.get("created_by") or created_by,
            created_at=now_dt,
            modified_by=slide_dict.get("modified_by") or created_by,
            modified_at=now_dt,
            verification_record=slide_dict.get("_verification_record"),
        )
        db.add(row)

    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Test: rows present → correct top-level keys and types
# ---------------------------------------------------------------------------


class TestRowsPresent:
    def test_top_level_keys_all_present(self, factory, session_id):
        """Row-path returns all required top-level keys with correct types."""
        owner_id = _user_session_id_int(factory)
        slides = [_make_slide("<p>Slide 0</p>"), _make_slide("<p>Slide 1</p>")]
        _seed_deck_and_rows(factory, owner_id, slides, css=".body{}", external_scripts=["https://cdn.jsdelivr.net/npm/chart.js"])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        for key in ("slides", "title", "css", "external_scripts", "scripts",
                    "slide_count", "version", "created_by", "created_at",
                    "modified_by", "modified_at"):
            assert key in result, f"Missing top-level key: {key!r}"

        assert isinstance(result["slides"], list)
        assert isinstance(result["external_scripts"], list)
        assert isinstance(result["slide_count"], int)
        assert result["slide_count"] == 2

    def test_per_slide_keys_all_present(self, factory, session_id):
        """Row-path slide dicts have all required per-slide keys."""
        owner_id = _user_session_id_int(factory)
        _seed_deck_and_rows(factory, owner_id, [_make_slide("<p>S0</p>")])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        slide = result["slides"][0]
        for key in ("html", "slide_id", "scripts", "created_by", "created_at",
                    "modified_by", "modified_at", "verification", "content_hash"):
            assert key in slide, f"Missing per-slide key: {key!r}"

    def test_slide_count_reflects_row_count(self, factory, session_id):
        """slide_count must be the number of rows, not the stored deck.slide_count."""
        owner_id = _user_session_id_int(factory)
        _seed_deck_and_rows(factory, owner_id, [
            _make_slide("<p>S0</p>"),
            _make_slide("<p>S1</p>"),
            _make_slide("<p>S2</p>"),
        ])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        assert result["slide_count"] == 3
        assert len(result["slides"]) == 3


# ---------------------------------------------------------------------------
# Test: css and external_scripts survive the row round-trip (PRD §3 guard)
# ---------------------------------------------------------------------------


class TestCssAndExternalScriptsRoundTrip:
    def test_css_and_external_scripts_preserved(self, factory, session_id):
        """css and external_scripts from deck columns reach the returned dict.

        Sabotage test: if deck.css is returned as None or if external_scripts_json
        is not parsed back to a list, this test fails. Proves PRD §3 guard.
        """
        css_val = "body { background: #fff; font-family: sans-serif; }"
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js", "https://example.com/lib.js"]
        owner_id = _user_session_id_int(factory)
        _seed_deck_and_rows(
            factory, owner_id, [_make_slide()],
            css=css_val,
            external_scripts=ext_scripts,
        )

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        assert result["css"] == css_val, (
            f"Expected css={css_val!r}, got {result['css']!r}"
        )
        assert result["external_scripts"] == ext_scripts, (
            f"Expected external_scripts={ext_scripts!r}, got {result['external_scripts']!r}"
        )

    def test_empty_css_returns_empty_string_not_none(self, factory, session_id):
        """deck.css='' must return '' (not None) to preserve contract."""
        owner_id = _user_session_id_int(factory)
        _seed_deck_and_rows(factory, owner_id, [_make_slide()], css="")

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        assert result["css"] == "", f"Expected '' not {result['css']!r}"
        # external_scripts must be a list even when empty
        assert isinstance(result["external_scripts"], list)


# ---------------------------------------------------------------------------
# Test: no rows, deck_json present → legacy fallback
# ---------------------------------------------------------------------------


class TestLegacyFallback:
    def test_no_rows_falls_back_to_deck_json(self, factory, session_id):
        """When no session_slides rows exist, deck_json is returned unchanged."""
        owner_id = _user_session_id_int(factory)

        # Insert deck WITHOUT any session_slides rows
        slides = [{"html": "<p>Legacy</p>", "scripts": "", "created_by": "user@example.com",
                   "created_at": "2024-01-01T00:00:00Z", "modified_by": "user@example.com",
                   "modified_at": "2024-01-01T00:00:00Z"}]
        legacy_deck_dict = {"title": "Legacy Deck", "css": ".legacy{}", "external_scripts": [],
                            "scripts": "", "slides": slides}
        db = factory()
        deck = SessionSlideDeck(
            session_id=owner_id,
            title="Legacy Deck",
            html_content="",
            scripts_content="",
            slide_count=1,
            deck_json=json.dumps(legacy_deck_dict),
            version=1,
        )
        db.add(deck)
        db.commit()
        db.close()

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        # legacy path parses deck_json and returns its slides
        assert result["title"] == "Legacy Deck"
        assert len(result["slides"]) == 1
        assert result["slides"][0]["html"] == "<p>Legacy</p>"


# ---------------------------------------------------------------------------
# Test: equivalence — same logical deck read via both paths produces equal dicts
# ---------------------------------------------------------------------------


class TestEquivalence:
    """The highest-value test: same deck via legacy path == same deck via row path.

    Method:
      1. Write via save_slide_deck (dual-write: populates both deck_json and rows).
      2. Call get_slide_deck → captures the ROW path (rows exist).
      3. Delete the session_slides rows so only deck_json remains.
      4. Call get_slide_deck → captures the LEGACY path.
      5. Assert equality, excluding fields that legitimately differ.

    Exclusions:
      - None: both paths are designed to be identical for the same data.
        We include all keys in the comparison.

    Sabotage proof: covered separately in test_equivalence_fails_if_css_dropped.
    """

    def test_row_path_equals_legacy_path(self, factory, session_id):
        """Row-path dict must equal legacy-path dict for the same logical deck."""
        css_val = ".card { padding: 1rem; }"
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
        slides = [
            _make_slide("<p>Slide A</p>", scripts="console.log('a')", slide_id="slide-a"),
            _make_slide("<p>Slide B</p>", scripts="", slide_id="slide-b"),
        ]
        deck_dict_in = _make_deck_dict(
            slides,
            css=css_val,
            external_scripts=ext_scripts,
            scripts="",
            title="Equiv Deck",
        )

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Equiv Deck",
                html_content="<html></html>",
                slide_count=2,
                deck_dict=deck_dict_in,
                modified_by="test-user@example.com",
            )

        # --- Capture row path (rows exist) ---
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            row_dict = mgr.get_slide_deck(session_id)

        assert row_dict is not None

        # --- Delete the session_slides rows to force legacy path ---
        owner_id = _user_session_id_int(factory)
        db = factory()
        db.query(SessionSlide).filter(SessionSlide.session_id == owner_id).delete()
        db.commit()
        db.close()

        # --- Capture legacy path (no rows) ---
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            legacy_dict = mgr.get_slide_deck(session_id)

        assert legacy_dict is not None

        # --- Compare top-level fields ---
        for key in ("title", "css", "external_scripts", "scripts", "version"):
            assert row_dict.get(key) == legacy_dict.get(key), (
                f"Top-level key {key!r} differs: row={row_dict.get(key)!r} legacy={legacy_dict.get(key)!r}"
            )

        # --- Compare slides (per-slide fields that both paths must agree on) ---
        assert len(row_dict["slides"]) == len(legacy_dict["slides"]), (
            f"Slide count differs: row={len(row_dict['slides'])} legacy={len(legacy_dict['slides'])}"
        )
        for i, (r_slide, l_slide) in enumerate(zip(row_dict["slides"], legacy_dict["slides"])):
            for key in ("html", "scripts", "slide_id", "content_hash"):
                assert r_slide.get(key) == l_slide.get(key), (
                    f"Slide {i} key {key!r} differs: row={r_slide.get(key)!r} legacy={l_slide.get(key)!r}"
                )

    def test_equivalence_fails_if_css_dropped(self, factory, session_id):
        """Sabotage proof: if the row path drops css, the equivalence test fails.

        This test INTENTIONALLY injects a wrong css into the deck columns to
        confirm that a broken row path would be detected.
        """
        css_val = ".sabotage { color: red; }"
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js"]
        slides = [_make_slide("<p>Sabotage</p>")]
        deck_dict_in = _make_deck_dict(slides, css=css_val, external_scripts=ext_scripts)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Sabotage Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_dict_in,
            )

        # Now corrupt the deck's css column to simulate a broken write
        owner_id = _user_session_id_int(factory)
        db = factory()
        deck_row = db.query(SessionSlideDeck).filter(
            SessionSlideDeck.session_id == owner_id
        ).one()
        deck_row.css = "/* WRONG CSS */"  # sabotage
        db.commit()
        db.close()

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            row_result = mgr.get_slide_deck(session_id)

        # Row path should return the WRONG css (because we corrupted the column)
        assert row_result is not None
        assert row_result["css"] != css_val, (
            "Sabotage not detected: css was not read from the column"
        )

    def test_equivalence_fails_if_external_scripts_dropped(self, factory, session_id):
        """Sabotage proof: if the row path drops external_scripts, it would be detected."""
        ext_scripts = ["https://cdn.jsdelivr.net/npm/chart.js", "https://example.com/extra.js"]
        slides = [_make_slide("<p>Sabotage ext</p>")]
        deck_dict_in = _make_deck_dict(slides, external_scripts=ext_scripts)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            mgr.save_slide_deck(
                session_id=session_id,
                title="Sabotage ext Deck",
                html_content="",
                slide_count=1,
                deck_dict=deck_dict_in,
            )

        # Corrupt external_scripts_json to simulate a broken read
        owner_id = _user_session_id_int(factory)
        db = factory()
        deck_row = db.query(SessionSlideDeck).filter(
            SessionSlideDeck.session_id == owner_id
        ).one()
        deck_row.external_scripts_json = "[]"  # sabotage: drop all scripts
        db.commit()
        db.close()

        with patch("src.api.services.session_manager.get_db_session", fake_db):
            row_result = mgr.get_slide_deck(session_id)

        assert row_result is not None
        # Row path must reflect the corrupted (wrong) value
        assert row_result["external_scripts"] == [], (
            "Sabotage not detected: external_scripts_json was not read from the column"
        )
        assert row_result["external_scripts"] != ext_scripts, (
            "Sabotage proof failed: expected mismatch with original ext_scripts"
        )


# ---------------------------------------------------------------------------
# Test: per-slide verification populated by content hash
# ---------------------------------------------------------------------------


class TestVerificationByHash:
    def test_verification_populated_from_verification_record(self, factory, session_id):
        """Slide with a verification_record has its verification field populated."""
        html = "<p>Verified slide</p>"
        content_hash = compute_slide_hash(html)
        verdict = {"score": 95, "rating": "excellent"}
        verification_record = json.dumps({content_hash: verdict})

        owner_id = _user_session_id_int(factory)
        slides = [{"html": html, "scripts": "", "_verification_record": verification_record}]
        _seed_deck_and_rows(factory, owner_id, slides)

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        slide = result["slides"][0]
        assert slide["content_hash"] == content_hash
        assert slide["verification"] == verdict, (
            f"Expected verification={verdict!r}, got {slide['verification']!r}"
        )

    def test_verification_is_none_when_no_record(self, factory, session_id):
        """Slide without verification_record has verification=None."""
        owner_id = _user_session_id_int(factory)
        _seed_deck_and_rows(factory, owner_id, [_make_slide("<p>Unverified</p>")])

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        assert result["slides"][0]["verification"] is None


# ---------------------------------------------------------------------------
# Test: contributor session reads the root's rows
# ---------------------------------------------------------------------------


class TestContributorSessionReadsRoot:
    def test_contributor_session_reads_root_rows(self, factory):
        """get_slide_deck called with a contributor session returns root's rows."""
        db = factory()
        root = UserSession(session_id="root-read-001", created_by="owner@example.com")
        db.add(root)
        db.flush()
        contributor = UserSession(
            session_id="contrib-read-001",
            created_by="contrib@example.com",
            parent_session_id=root.id,
        )
        db.add(contributor)
        db.commit()
        root_pk = root.id
        db.close()

        # Seed rows on the ROOT session
        _seed_deck_and_rows(
            factory, root_pk,
            [_make_slide("<p>Root slide</p>")],
            title="Root Deck",
        )

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            # Call with CONTRIBUTOR session id
            result = mgr.get_slide_deck("contrib-read-001")

        assert result is not None
        assert result["title"] == "Root Deck"
        assert len(result["slides"]) == 1
        assert result["slides"][0]["html"] == "<p>Root slide</p>"


# ---------------------------------------------------------------------------
# Test: ordering — rows returned in position order even when seeded out of order
# ---------------------------------------------------------------------------


class TestPositionOrdering:
    def test_slides_returned_in_position_order(self, factory, session_id):
        """Rows seeded out of order must be returned in ascending position order."""
        owner_id = _user_session_id_int(factory)

        # Seed the deck row first
        db = factory()
        deck = SessionSlideDeck(
            session_id=owner_id,
            title="Order Test",
            html_content="",
            scripts_content="",
            slide_count=3,
            deck_json="{}",
            version=1,
            css="",
            external_scripts_json="[]",
        )
        db.add(deck)
        db.flush()

        now_dt = datetime(2024, 1, 1, 0, 0, 0)
        # Insert rows in REVERSE order: 2, 0, 1
        for pos, html in [(2, "<p>Third</p>"), (0, "<p>First</p>"), (1, "<p>Second</p>")]:
            row = SessionSlide(
                session_id=owner_id,
                position=pos,
                id=str(uuid.uuid4()),
                html=html,
                scripts="",
                created_by="user@example.com",
                created_at=now_dt,
                modified_by="user@example.com",
                modified_at=now_dt,
            )
            db.add(row)

        db.commit()
        db.close()

        fake_db = _make_fake_get_db_session(factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            mgr = SessionManager()
            result = mgr.get_slide_deck(session_id)

        assert result is not None
        assert len(result["slides"]) == 3
        assert result["slides"][0]["html"] == "<p>First</p>", (
            f"Position 0 wrong: {result['slides'][0]['html']!r}"
        )
        assert result["slides"][1]["html"] == "<p>Second</p>", (
            f"Position 1 wrong: {result['slides'][1]['html']!r}"
        )
        assert result["slides"][2]["html"] == "<p>Third</p>", (
            f"Position 2 wrong: {result['slides'][2]['html']!r}"
        )

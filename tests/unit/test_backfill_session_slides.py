"""Unit/integration tests for scripts/backfill_session_slides.py.

Uses in-memory SQLite (StaticPool) with Base.metadata.create_all so every ORM
table is present, but hand-rolled ALTER migrations do NOT run — that's Task 2's
concern.  All columns tested here are defined via the ORM in Task 1.

Pattern sourced from tests/integration/test_savepoint_e2e.py:42-79.
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.utils.slide_hash import compute_slide_hash

from scripts.backfill_session_slides import backfill_session, parse_args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def _make_db(engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def _add_session(db, session_id_str="sess-001"):
    """Create and persist a UserSession; return its integer PK."""
    us = UserSession(session_id=session_id_str)
    db.add(us)
    db.flush()
    return us.id


def _add_deck(db, user_session_pk: int, deck_dict: dict, verification_map: dict | None = None):
    """Create and persist a SessionSlideDeck with deck_json."""
    deck = SessionSlideDeck(
        session_id=user_session_pk,
        deck_json=json.dumps(deck_dict),
        verification_map=json.dumps(verification_map) if verification_map else None,
        slide_count=len(deck_dict.get("slides", [])),
    )
    db.add(deck)
    db.flush()
    return deck


SLIDE_1_HTML = "<div>Slide One</div>"
SLIDE_2_HTML = "<div>Slide Two</div>"
SLIDE_3_HTML = "<div>Slide Three</div>"

SAMPLE_DECK = {
    "slides": [
        {"html": SLIDE_1_HTML, "slide_id": "sid-1", "scripts": ""},
        {"html": SLIDE_2_HTML, "slide_id": "sid-2", "scripts": "alert(1)"},
    ],
    "css": ".custom { color: red; }",
    "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
    "scripts": "",
}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_defaults_to_dry_run(self):
        """No args → dry_run=True."""
        args = parse_args([])
        assert args.dry_run is True

    def test_session_id_defaults_to_none(self):
        """No --session-id → None."""
        args = parse_args([])
        assert args.session_id is None

    def test_yes_disables_dry_run(self):
        """--yes → dry_run=False."""
        args = parse_args(["--yes"])
        assert args.dry_run is False

    def test_session_id_string(self):
        """--session-id accepts a string value."""
        args = parse_args(["--session-id", "abc-xyz-123"])
        assert args.session_id == "abc-xyz-123"

    def test_session_id_with_yes(self):
        """Both flags together."""
        args = parse_args(["--yes", "--session-id", "my-session"])
        assert args.dry_run is False
        assert args.session_id == "my-session"


# ---------------------------------------------------------------------------
# Core backfill — real DB, real rows
# ---------------------------------------------------------------------------

class TestBackfillSession:
    """Tests that exercise backfill_session() against an in-memory SQLite DB."""

    def setup_method(self):
        self.engine = _make_engine()
        self.db = _make_db(self.engine)

    def teardown_method(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    # ------------------------------------------------------------------
    # Basic row production
    # ------------------------------------------------------------------

    def test_inserts_correct_number_of_rows(self):
        """A 2-slide deck produces 2 session_slides rows."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["slides_inserted"] == 2
        assert result["slides_skipped"] == 0
        rows = self.db.query(SessionSlide).filter(SessionSlide.session_id == pk).all()
        assert len(rows) == 2

    def test_row_positions_are_zero_indexed(self):
        """Positions are 0 and 1 for a 2-slide deck."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        positions = {
            r.position
            for r in self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .all()
        }
        assert positions == {0, 1}

    def test_row_html_is_correct(self):
        """Each row carries the right html from the slide dict."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        rows = {
            r.position: r
            for r in self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .all()
        }
        assert rows[0].html == SLIDE_1_HTML
        assert rows[1].html == SLIDE_2_HTML

    def test_row_scripts_is_correct(self):
        """scripts field is mapped from the slide dict."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        rows = {
            r.position: r
            for r in self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .all()
        }
        assert rows[0].scripts == ""
        assert rows[1].scripts == "alert(1)"

    def test_row_id_is_unique_uuid(self):
        """Row id is a fresh UUID (not reused from slide_id) to prevent unique violations."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        rows = (
            self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .all()
        )
        ids = [r.id for r in rows]
        # No duplicates
        assert len(set(ids)) == len(ids)
        # Not the original slide_ids
        assert "sid-1" not in ids
        assert "sid-2" not in ids

    def test_slide_id_preserved_in_slide_id_column(self):
        """Original slide_id from deck_json is kept in the slide_id column."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        rows = {
            r.position: r
            for r in self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .all()
        }
        assert rows[0].slide_id == "sid-1"
        assert rows[1].slide_id == "sid-2"

    # ------------------------------------------------------------------
    # CSS / external_scripts lift (THE CRITICAL NO-REGRESSION GATE)
    # ------------------------------------------------------------------

    def test_css_lifted_into_deck_column(self):
        """deck.css is populated from deck_dict['css'] when it was None."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["css_backfilled"] == 1
        deck = (
            self.db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == pk)
            .one()
        )
        assert deck.css == ".custom { color: red; }"

    def test_external_scripts_lifted_into_deck_column(self):
        """deck.external_scripts_json is populated from deck_dict['external_scripts']."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["external_scripts_backfilled"] == 1
        deck = (
            self.db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == pk)
            .one()
        )
        ext = json.loads(deck.external_scripts_json)
        assert "https://cdn.jsdelivr.net/npm/chart.js" in ext

    def test_css_not_overwritten_if_already_set(self):
        """css_backfilled=0 when deck.css already has a value."""
        pk = _add_session(self.db)
        deck = _add_deck(self.db, pk, SAMPLE_DECK)
        deck.css = "pre-existing"
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["css_backfilled"] == 0
        deck_after = (
            self.db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == pk)
            .one()
        )
        assert deck_after.css == "pre-existing"

    # ------------------------------------------------------------------
    # Verification migration
    # ------------------------------------------------------------------

    def test_verification_record_written_for_matching_hash(self):
        """A slide whose content_hash is in verification_map gets verification_record."""
        html = SLIDE_1_HTML
        content_hash = compute_slide_hash(html)
        findings = {"score": 92, "rating": "good"}
        vmap = {content_hash: findings}

        deck_dict = {
            "slides": [{"html": html, "slide_id": "s1"}],
            "css": "",
            "external_scripts": [],
        }

        pk = _add_session(self.db)
        _add_deck(self.db, pk, deck_dict, verification_map=vmap)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["verification_migrated"] == 1
        row = (
            self.db.query(SessionSlide)
            .filter(
                SessionSlide.session_id == pk,
                SessionSlide.position == 0,
            )
            .one()
        )
        rec = json.loads(row.verification_record)
        assert content_hash in rec
        assert rec[content_hash] == findings

    def test_verification_record_none_when_no_match(self):
        """A slide with no matching hash in verification_map has None verification_record."""
        deck_dict = {
            "slides": [{"html": SLIDE_1_HTML}],
            "css": "",
            "external_scripts": [],
        }

        pk = _add_session(self.db)
        _add_deck(self.db, pk, deck_dict, verification_map={"otherhash": {}})
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        row = (
            self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk, SessionSlide.position == 0)
            .one()
        )
        assert row.verification_record is None

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def test_idempotent_second_run_skips_all(self):
        """Running backfill twice inserts 0 rows on the second run."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        result2 = backfill_session(self.db, pk, dry_run=False)

        assert result2["slides_inserted"] == 0
        assert result2["slides_skipped"] == 2

    def test_idempotent_no_duplicate_rows(self):
        """Exactly 2 rows exist after running twice."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)
        backfill_session(self.db, pk, dry_run=False)

        count = (
            self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .count()
        )
        assert count == 2

    # ------------------------------------------------------------------
    # Orphan pruning
    # ------------------------------------------------------------------

    def test_orphan_rows_pruned_when_deck_shrinks(self):
        """Rows at positions >= new slide count are deleted after backfill."""
        # First, insert a 3-slide deck and backfill it.
        big_deck = {
            "slides": [
                {"html": SLIDE_1_HTML},
                {"html": SLIDE_2_HTML},
                {"html": SLIDE_3_HTML},
            ],
            "css": "",
            "external_scripts": [],
        }
        pk = _add_session(self.db)
        deck = _add_deck(self.db, pk, big_deck)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=False)

        # Simulate deck shrinking to 1 slide.
        small_deck = {
            "slides": [{"html": SLIDE_1_HTML}],
            "css": "",
            "external_scripts": [],
        }
        deck.deck_json = json.dumps(small_deck)
        deck.slide_count = 1
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["orphans_pruned"] == 2
        remaining = (
            self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .all()
        )
        assert len(remaining) == 1
        assert remaining[0].position == 0

    # ------------------------------------------------------------------
    # Dry-run — THE OTHER CRITICAL GATE: must mutate NOTHING
    # ------------------------------------------------------------------

    def test_dry_run_inserts_no_rows(self):
        """Dry-run must not insert any session_slides rows."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=True)

        assert result["slides_inserted"] == 2  # counted, not applied
        count = (
            self.db.query(SessionSlide)
            .filter(SessionSlide.session_id == pk)
            .count()
        )
        assert count == 0  # nothing written

    def test_dry_run_does_not_set_css_column(self):
        """Dry-run must not set deck.css."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=True)

        deck = (
            self.db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == pk)
            .one()
        )
        assert deck.css is None  # unchanged

    def test_dry_run_does_not_set_external_scripts_column(self):
        """Dry-run must not set deck.external_scripts_json."""
        pk = _add_session(self.db)
        _add_deck(self.db, pk, SAMPLE_DECK)
        self.db.commit()

        backfill_session(self.db, pk, dry_run=True)

        deck = (
            self.db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == pk)
            .one()
        )
        assert deck.external_scripts_json is None  # unchanged

    def test_dry_run_reports_correct_counts(self):
        """Dry-run result counts reflect what WOULD happen."""
        html = SLIDE_1_HTML
        content_hash = compute_slide_hash(html)
        vmap = {content_hash: {"score": 80}}
        deck_dict = {
            "slides": [
                {"html": html},
                {"html": SLIDE_2_HTML},
            ],
            "css": ".x {}",
            "external_scripts": ["https://example.com/chart.js"],
        }
        pk = _add_session(self.db)
        _add_deck(self.db, pk, deck_dict, verification_map=vmap)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=True)

        assert result["slides_inserted"] == 2
        assert result["slides_skipped"] == 0
        assert result["verification_migrated"] == 1
        assert result["css_backfilled"] == 1
        assert result["external_scripts_backfilled"] == 1

    # ------------------------------------------------------------------
    # No deck / empty deck_json
    # ------------------------------------------------------------------

    def test_returns_zeros_when_no_deck(self):
        """Session with no slide deck returns all-zero counts."""
        pk = _add_session(self.db)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["slides_inserted"] == 0
        assert result["slides_skipped"] == 0
        assert result["verification_migrated"] == 0

    def test_returns_zeros_when_deck_json_empty(self):
        """Session with empty deck_json returns all-zero counts."""
        pk = _add_session(self.db)
        deck = SessionSlideDeck(
            session_id=pk,
            deck_json=None,
            slide_count=0,
        )
        self.db.add(deck)
        self.db.commit()

        result = backfill_session(self.db, pk, dry_run=False)

        assert result["slides_inserted"] == 0


# ---------------------------------------------------------------------------
# Cross-session uniqueness: same slide_id in two sessions must not conflict
# ---------------------------------------------------------------------------

class TestCrossSessionUniqueness:
    """Regression for the unique-constraint bug: two sessions with the same slide_id."""

    def setup_method(self):
        self.engine = _make_engine()
        self.db = _make_db(self.engine)

    def teardown_method(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_duplicate_slide_id_across_sessions_does_not_raise(self):
        """Two sessions with the same slide_id must both backfill successfully."""
        shared_slide_id = "common-slide-id"
        deck_dict = {
            "slides": [{"html": SLIDE_1_HTML, "slide_id": shared_slide_id}],
            "css": "",
            "external_scripts": [],
        }

        pk1 = _add_session(self.db, "sess-A")
        pk2 = _add_session(self.db, "sess-B")
        _add_deck(self.db, pk1, deck_dict)
        _add_deck(self.db, pk2, deck_dict)
        self.db.commit()

        # Both must succeed without IntegrityError.
        r1 = backfill_session(self.db, pk1, dry_run=False)
        r2 = backfill_session(self.db, pk2, dry_run=False)

        assert r1["slides_inserted"] == 1
        assert r2["slides_inserted"] == 1

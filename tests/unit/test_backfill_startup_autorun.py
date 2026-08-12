"""Startup auto-backfill: historical decks migrate without an operator step.

The row-per-slide migration originally left the data backfill as a manual
``python -m scripts.backfill_session_slides`` step.  That was inconsistent with
this repo — ``migrate_profiles()`` already runs automatically in the FastAPI
lifespan — and it left every deployment in a split state until someone
remembered to run it: reads still worked (``get_slide_deck`` falls back to
``deck_json``), but a deck *edited* before the backfill acquired rows without its
verdicts, and the idempotency guard then skipped it permanently.

``backfill_unmigrated_decks`` closes that window by running on boot, guarded by a
per-deck NOT EXISTS anti-join so it is a no-op scan once every deck has rows.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.backfill_session_slides_startup import backfill_unmigrated_decks
from src.core.database import Base
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.utils.slide_hash import compute_slide_hash


DECK_CSS = ".slide { color: rebeccapurple; }"
CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js"


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def _deck_json(slides):
    return json.dumps(
        {
            "title": "Legacy deck",
            "css": DECK_CSS,
            "external_scripts": [CHART_CDN],
            "scripts": "console.log('deck');",
            "slides": [
                {"html": html, "slide_id": sid, "scripts": ""} for html, sid in slides
            ],
        }
    )


def _seed_legacy_deck(factory, session_key, slides, verification_map=None):
    """Create a session + deck the OLD way: deck_json blob only, no rows."""
    db = factory()
    try:
        us = UserSession(session_id=session_key, created_by="legacy@example.com")
        db.add(us)
        db.flush()
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Legacy deck",
            deck_json=_deck_json(slides),
            verification_map=json.dumps(verification_map) if verification_map else None,
            slide_count=len(slides),
        )
        db.add(deck)
        db.commit()
        return us.id
    finally:
        db.close()


def _rows(factory, owner_pk):
    db = factory()
    try:
        return (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_pk)
            .order_by(SessionSlide.position)
            .all()
        )
    finally:
        db.close()


class TestStartupAutoBackfill:
    def setup_method(self):
        self.engine = _make_engine()
        self.factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def teardown_method(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_migrates_a_legacy_deck_with_no_rows(self):
        """THE POINT OF THE TASK: an upgrade migrates history by itself."""
        pk = _seed_legacy_deck(
            self.factory, "sess-legacy", [("<p>One</p>", "id-1"), ("<p>Two</p>", "id-2")]
        )

        assert _rows(self.factory, pk) == [], "precondition: deck starts with no rows"

        migrated = backfill_unmigrated_decks(self.factory)

        assert migrated == 1, f"expected 1 deck migrated, got {migrated}"
        rows = _rows(self.factory, pk)
        assert [r.position for r in rows] == [0, 1]
        assert [r.html for r in rows] == ["<p>One</p>", "<p>Two</p>"]
        assert [r.slide_id for r in rows] == ["id-1", "id-2"]

    def test_lifts_css_and_external_scripts_into_columns(self):
        """The row read path reads these from COLUMNS, not deck_json.

        Without the lift every migrated deck silently loses its stylesheet and
        the Chart.js CDN on first read — the PRD §3 no-regression gate failing
        invisibly.
        """
        pk = _seed_legacy_deck(self.factory, "sess-css", [("<p>One</p>", "id-1")])

        backfill_unmigrated_decks(self.factory)

        db = self.factory()
        try:
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == pk)
                .one()
            )
            assert deck.css == DECK_CSS, f"css not lifted; got {deck.css!r}"
            assert json.loads(deck.external_scripts_json or "[]") == [CHART_CDN], (
                "external_scripts not lifted — Chart.js CDN would be dropped "
                "from every export"
            )
        finally:
            db.close()

    def test_migrates_verdicts_from_the_blob_onto_rows(self):
        """Verdicts users already earned must survive the migration."""
        html = "<p>Judged</p>"
        vmap = {compute_slide_hash(html): {"score": 91, "rating": "good"}}
        pk = _seed_legacy_deck(
            self.factory, "sess-verdict", [(html, "id-1")], verification_map=vmap
        )

        backfill_unmigrated_decks(self.factory)

        row = _rows(self.factory, pk)[0]
        assert row.verification_record, "verdict was not migrated onto the row"
        record = json.loads(row.verification_record)
        assert record[compute_slide_hash(html)]["score"] == 91

    def test_is_a_noop_once_every_deck_has_rows(self):
        """The anti-join guard: a second boot does no work.

        This is what makes running on every startup acceptable — the steady-state
        cost is one cheap scan, not a re-migration.
        """
        _seed_legacy_deck(self.factory, "sess-idem", [("<p>One</p>", "id-1")])

        first = backfill_unmigrated_decks(self.factory)
        second = backfill_unmigrated_decks(self.factory)

        assert first == 1
        assert second == 0, "second run should find nothing to migrate"

    def test_leaves_already_migrated_decks_untouched(self):
        """A deck that already has rows must not be rewritten."""
        pk = _seed_legacy_deck(self.factory, "sess-mixed", [("<p>One</p>", "id-1")])
        backfill_unmigrated_decks(self.factory)
        before = _rows(self.factory, pk)[0]
        before_id, before_html = before.id, before.html

        backfill_unmigrated_decks(self.factory)

        after = _rows(self.factory, pk)[0]
        assert after.id == before_id, "row identity changed on a no-op run"
        assert after.html == before_html

    def test_skips_decks_with_null_deck_json(self):
        """A deck row with no blob has nothing to migrate and must not crash."""
        db = self.factory()
        try:
            us = UserSession(session_id="sess-null", created_by="x@example.com")
            db.add(us)
            db.flush()
            db.add(SessionSlideDeck(session_id=us.id, title="Empty", deck_json=None))
            db.commit()
        finally:
            db.close()

        assert backfill_unmigrated_decks(self.factory) == 0

    def test_one_bad_deck_does_not_block_the_others(self):
        """Startup must not be aborted by a single unparseable deck_json."""
        good_pk = _seed_legacy_deck(
            self.factory, "sess-good", [("<p>Good</p>", "id-good")]
        )

        db = self.factory()
        try:
            us = UserSession(session_id="sess-bad", created_by="x@example.com")
            db.add(us)
            db.flush()
            db.add(
                SessionSlideDeck(
                    session_id=us.id, title="Corrupt", deck_json="{not valid json"
                )
            )
            db.commit()
        finally:
            db.close()

        # Must not raise: a corrupt deck stays on deck_json and is still readable
        # through the fallback path.
        migrated = backfill_unmigrated_decks(self.factory)

        assert migrated >= 1, "the good deck should still have been migrated"
        assert len(_rows(self.factory, good_pk)) == 1

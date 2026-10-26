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
import contextlib
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core import backfill_session_slides_startup
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


@contextlib.contextmanager
def _capture(engine, event_name):
    """Record every ``event_name`` engine event fired inside the block.

    ``before_cursor_execute`` fires once per statement sent to the driver (an
    executemany counts once), so on PostgreSQL its count is the round-trip count.
    """
    seen = []

    def _record(*args):
        seen.append(args[2] if event_name == "before_cursor_execute" else event_name)

    event.listen(engine, event_name, _record)
    try:
        yield seen
    finally:
        event.remove(engine, event_name, _record)


def _statements_to_backfill(slides_per_deck, decks=3):
    """Statements the startup pass issues to migrate ``decks`` legacy decks."""
    engine = _make_engine()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        for d in range(decks):
            _seed_legacy_deck(
                factory,
                f"sess-shape-{d}",
                [(f"<p>{d}-{s}</p>", f"id-{d}-{s}") for s in range(slides_per_deck)],
            )
        with _capture(engine, "before_cursor_execute") as statements:
            assert backfill_unmigrated_decks(factory) == decks
        return statements
    finally:
        engine.dispose()

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


class TestStartupBackfillCost:
    """The startup pass is bounded by round trips, not by data volume.

    Measured on a prod fork (2026-10-21): 5,183 decks / ~57k slides took ~7.5 min
    at ~3 round trips per slide plus ~5 per deck — two existence SELECTs that the
    NOT EXISTS guard had already answered, the INSERT, a full-row deck load, an
    orphan-prune SELECT and a COMMIT per deck.  These tests pin the shape that
    replaced it.
    """

    def setup_method(self):
        self.engine = _make_engine()
        self.factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def teardown_method(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_statement_count_does_not_grow_with_slide_count(self):
        """No per-slide round trip: a 20-slide deck costs what a 2-slide deck does."""
        few = _statements_to_backfill(slides_per_deck=2)
        many = _statements_to_backfill(slides_per_deck=20)

        assert len(many) == len(few), (
            f"{len(few)} statements for 2 slides/deck but {len(many)} for 20 — "
            "the startup pass is issuing per-slide statements again"
        )

    def test_does_not_load_the_full_knitted_html(self):
        """html_content (~180 MB across prod) is never read by the backfill."""
        _seed_legacy_deck(self.factory, "sess-cols", [("<p>One</p>", "id-1")])

        with _capture(self.engine, "before_cursor_execute") as statements:
            backfill_unmigrated_decks(self.factory)

        readers = [s for s in statements if "html_content" in s]
        assert readers == [], f"backfill read html_content: {readers}"

    def test_commits_once_per_batch_and_migrates_across_batch_boundaries(
        self, monkeypatch
    ):
        monkeypatch.setattr(backfill_session_slides_startup, "_STARTUP_BATCH_DECKS", 2)
        pks = [
            _seed_legacy_deck(self.factory, f"sess-batch-{i}", [(f"<p>{i}</p>", f"id-{i}")])
            for i in range(5)
        ]

        with _capture(self.engine, "commit") as commits:
            migrated = backfill_unmigrated_decks(self.factory)

        assert migrated == 5
        assert all(len(_rows(self.factory, pk)) == 1 for pk in pks)
        assert len(commits) == 3, f"expected 3 commits for 5 decks in batches of 2, got {len(commits)}"

    def test_a_deck_that_fails_midway_leaves_no_partial_rows(self):
        """Batching must not cost per-deck isolation.

        The bad deck's first slide is valid and its second is not, so the failure
        happens after a row was already added.  That row must be discarded — a
        deck with SOME rows is invisible to the NOT EXISTS guard and would never be
        retried — while the good decks either side of it in the same batch commit.
        """
        before_pk = _seed_legacy_deck(self.factory, "sess-before", [("<p>A</p>", "id-a")])
        db = self.factory()
        try:
            us = UserSession(session_id="sess-midway", created_by="x@example.com")
            db.add(us)
            db.flush()
            bad_pk = us.id
            db.add(
                SessionSlideDeck(
                    session_id=bad_pk,
                    title="Half bad",
                    deck_json=json.dumps(
                        {"css": DECK_CSS, "slides": [{"html": "<p>ok</p>"}, "not-a-slide"]}
                    ),
                )
            )
            db.commit()
        finally:
            db.close()
        after_pk = _seed_legacy_deck(self.factory, "sess-after", [("<p>C</p>", "id-c")])

        migrated = backfill_unmigrated_decks(self.factory)

        assert migrated == 2
        assert len(_rows(self.factory, before_pk)) == 1
        assert len(_rows(self.factory, after_pk)) == 1
        assert _rows(self.factory, bad_pk) == [], "the failed deck kept a partial row"
        db = self.factory()
        try:
            bad_deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == bad_pk)
                .one()
            )
            assert bad_deck.css is None, "the failed deck's css lift was not rolled back"
        finally:
            db.close()

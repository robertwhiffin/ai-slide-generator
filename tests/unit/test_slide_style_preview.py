"""Unit tests for the slide-style visual preview feature.

Covers the correctness properties the design depends on:
- fingerprint invalidation (style edits AND generation-version bumps),
- deduplicated enqueue (exactly one generation for concurrent readers),
- revision-guarded write-back (a stale generation cannot clobber a fresh edit),
- hostile-output validation (+ last-known-good preserved on failure),
- migration idempotency,
- regenerate endpoint admin gating and read-visibility 404 parity.

Generation is fully mocked — no real LLM call.
"""

import contextlib
from unittest.mock import MagicMock, patch

import pytest

# Import core.database BEFORE models to avoid the package's import-order cycle.
import src.core.database as core_db
from src.core.database import Base
import src.database.models  # noqa: F401 — registers all tables on Base
from src.database.models.slide_style_library import SlideStyleLibrary
from src.services import slide_style_preview_fixture as fixture
from src.services import slide_style_preview_storage as storage

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Real in-memory DB fixtures (the queue logic is inherently DB-level)
# ---------------------------------------------------------------------------
@pytest.fixture
def db_factory(tmp_path):
    """A file-backed SQLite engine (so multiple sessions share state)."""
    engine = create_engine(f"sqlite:///{tmp_path}/preview.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def patched_db(db_factory, monkeypatch):
    """Point the queue's get_db_session at the test engine (commit-on-exit)."""

    @contextlib.contextmanager
    def _get_db_session():
        s = db_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(
        "src.api.services.slide_style_preview_queue.get_db_session",
        _get_db_session,
    )
    return db_factory


def _make_style(db_factory, **kwargs) -> int:
    s = db_factory()
    style = SlideStyleLibrary(
        name=kwargs.get("name", "Bold"),
        style_content=kwargs.get("style_content", "Big bold headings, navy palette."),
        image_guidelines=kwargs.get("image_guidelines"),
        is_active=True,
        style_revision=0,
        preview_status="missing",
    )
    s.add(style)
    s.commit()
    style_id = style.id
    s.close()
    return style_id


def _deck(slides=3, css=".slide{color:navy}"):
    return {
        "slides": [{"html": f"<div class='slide'>Slide {i}</div>"} for i in range(slides)],
        "css": css,
    }


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------
class TestFingerprint:
    def test_changes_with_style_content(self):
        a = fixture.compute_fingerprint("style A", None)
        b = fixture.compute_fingerprint("style B", None)
        assert a != b

    def test_changes_with_image_guidelines(self):
        a = fixture.compute_fingerprint("s", None)
        b = fixture.compute_fingerprint("s", "prefer photos")
        assert a != b

    def test_changes_when_generation_version_bumps(self, monkeypatch):
        before = fixture.compute_fingerprint("s", None)
        monkeypatch.setattr(fixture, "PREVIEW_GENERATION_VERSION", "999")
        after = fixture.compute_fingerprint("s", None)
        assert before != after

    def test_stable_for_same_inputs(self):
        assert fixture.compute_fingerprint("s", "g") == fixture.compute_fingerprint("s", "g")

    def test_changes_when_preview_max_tokens_changes(self, monkeypatch):
        before = fixture.compute_fingerprint("s", None)
        monkeypatch.setattr(fixture, "PREVIEW_MAX_TOKENS", fixture.PREVIEW_MAX_TOKENS + 1)
        after = fixture.compute_fingerprint("s", None)
        assert before != after


# ---------------------------------------------------------------------------
# Dedup enqueue
# ---------------------------------------------------------------------------
class TestEnqueueDedup:
    def test_second_enqueue_is_suppressed(self, patched_db, db_factory):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        assert q.try_enqueue(style_id) is True   # wins transition -> queued
        assert q.try_enqueue(style_id) is False  # already queued -> dedup

    def test_ready_and_current_is_not_requeued(self, patched_db, db_factory):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        style.preview_status = "ready"
        style.preview_fingerprint = fixture.compute_fingerprint(
            style.style_content, style.image_guidelines
        )
        s.commit()
        s.close()
        assert q.try_enqueue(style_id) is False

    def test_missing_style_returns_false(self, patched_db):
        from src.api.services import slide_style_preview_queue as q

        assert q.try_enqueue(999999) is False


# ---------------------------------------------------------------------------
# Startup warming (backfill)
# ---------------------------------------------------------------------------
class TestWarmBackfill:
    def test_warms_active_styles_and_skips_ready_and_inactive(self, patched_db, db_factory):
        from src.api.services import slide_style_preview_queue as q

        # Two active styles to warm; one already ready+current (skipped); one inactive.
        warm_a = _make_style(db_factory, name="A")
        warm_b = _make_style(db_factory, name="B")
        ready_id = _make_style(db_factory, name="Ready")
        inactive_id = _make_style(db_factory, name="Inactive")

        s = db_factory()
        ready = s.get(SlideStyleLibrary, ready_id)
        ready.preview_status = "ready"
        ready.preview_fingerprint = fixture.compute_fingerprint(
            ready.style_content, ready.image_guidelines
        )
        s.get(SlideStyleLibrary, inactive_id).is_active = False
        s.commit()
        s.close()

        enqueued = q.warm_missing_previews()
        assert enqueued == 2  # only the two missing active styles

        s = db_factory()
        assert s.get(SlideStyleLibrary, warm_a).preview_status == "queued"
        assert s.get(SlideStyleLibrary, warm_b).preview_status == "queued"
        assert s.get(SlideStyleLibrary, ready_id).preview_status == "ready"  # untouched
        # Inactive style never enqueued.
        assert s.get(SlideStyleLibrary, inactive_id).preview_status == "missing"
        s.close()

    def test_warm_respects_limit(self, patched_db, db_factory):
        from src.api.services import slide_style_preview_queue as q

        ids = [_make_style(db_factory, name=f"S{i}") for i in range(5)]
        assert q.warm_missing_previews(limit=3) == 3
        s = db_factory()
        queued = [i for i in ids if s.get(SlideStyleLibrary, i).preview_status == "queued"]
        s.close()
        assert len(queued) == 3


# ---------------------------------------------------------------------------
# Generation + validation + persistence
# ---------------------------------------------------------------------------
class TestGeneration:
    def test_generates_validates_and_caches(self, patched_db, db_factory, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)
        monkeypatch.setattr(q, "_generate_deck", lambda sid: _deck(slides=3))
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "ready"
        assert style.preview_payload_id is not None
        payload = storage.load_payload(s, style.preview_payload_id)
        assert payload is not None
        assert len(payload["slides"]) == 3
        s.close()

    def test_null_revision_row_is_promoted(self, patched_db, db_factory, monkeypatch):
        """Regression: rows inherited via a Lakebase branch have style_revision=NULL.

        The write-back guard snapshots revision 0 (``NULL or 0``); a plain
        ``style_revision == 0`` filter never matches NULL in SQL, so EVERY
        generation was discarded on a fork and no preview reached 'ready'. The
        NULL-safe guard must promote these rows.
        """
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        # Force the inherited-fork condition: style_revision IS NULL.
        s = db_factory()
        s.get(SlideStyleLibrary, style_id).style_revision = None
        s.commit()
        s.close()

        q.try_enqueue(style_id)
        monkeypatch.setattr(q, "_generate_deck", lambda sid: _deck(slides=2))
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "ready"          # promoted, not discarded
        assert style.preview_payload_id is not None
        s.close()

    @pytest.mark.parametrize(
        "bad_deck,code",
        [
            (_deck(slides=1), "bad_slide_count"),          # too few
            (_deck(slides=9), "bad_slide_count"),          # too many
            ({"slides": [{"html": ""}, {"html": ""}], "css": ""}, "bad_slide_count"),
            (
                {"slides": [{"html": "<img src='http://evil/x.png'>"}] * 2, "css": ""},
                "external_asset",
            ),
        ],
    )
    def test_validation_rejects_bad_output(self, bad_deck, code):
        from src.api.services import slide_style_preview_queue as q

        with pytest.raises(ValueError) as exc:
            q._sanitize_and_validate(bad_deck)
        assert str(exc.value) == code

    def test_scripts_are_stripped(self):
        from src.api.services import slide_style_preview_queue as q

        deck = {
            "slides": [
                {"html": "<div class='slide'>a<script>alert(1)</script></div>"},
                {"html": "<div class='slide'>b</div>"},
            ],
            "css": ".x{}",
        }
        slides, css, manifest = q._sanitize_and_validate(deck)
        assert all("<script" not in s for s in slides)

    def test_failure_preserves_last_known_good(self, patched_db, db_factory, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        # First, a successful generation establishes last-known-good.
        q.try_enqueue(style_id)
        monkeypatch.setattr(q, "_generate_deck", lambda sid: _deck(slides=2))
        q.process_preview_job(style_id)
        s = db_factory()
        good_payload_id = s.get(SlideStyleLibrary, style_id).preview_payload_id
        s.close()
        assert good_payload_id is not None

        # Now force a failing regeneration; the good payload must survive.
        s = db_factory()
        s.get(SlideStyleLibrary, style_id).preview_status = "queued"
        s.commit(); s.close()

        def _boom(sid):
            raise RuntimeError("provider down")

        monkeypatch.setattr(q, "_generate_deck", _boom)
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "failed"
        assert style.preview_error_code == "generation_error"
        assert style.preview_payload_id == good_payload_id  # preserved
        s.close()

    def test_revision_race_discards_stale_generation(self, patched_db, db_factory, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)

        # Simulate a concurrent edit: bump style_revision DURING generation so the
        # write-back guard (revision unchanged) fails and the result is discarded.
        def _generate_then_edit(sid):
            s = db_factory()
            style = s.get(SlideStyleLibrary, sid)
            style.style_revision = (style.style_revision or 0) + 1
            s.commit(); s.close()
            return _deck(slides=2)

        monkeypatch.setattr(q, "_generate_deck", _generate_then_edit)
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        # Not promoted to ready; no pointer written.
        assert style.preview_status != "ready"
        assert style.preview_payload_id is None
        s.close()


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------
class TestMigrationIdempotency:
    def _cols_without_preview(self):
        return [{"name": n} for n in ("id", "name", "style_content", "is_active")]

    def test_adds_all_columns_first_run_then_none(self):
        from src.core.database import _migrate_slide_style_preview_columns

        conn = MagicMock()
        insp = MagicMock()
        insp.get_columns.return_value = self._cols_without_preview()
        _qual = lambda t: t

        _migrate_slide_style_preview_columns(conn, insp, None, _qual, is_sqlite=True)
        first = conn.execute.call_count
        # 12 ALTERs (one per new column) + 1 idempotent style_revision backfill UPDATE.
        assert first == 13

        # Second run: all columns present -> no ALTERs, but the idempotent
        # style_revision backfill UPDATE still runs (a no-op WHERE ... IS NULL).
        insp.get_columns.return_value = self._cols_without_preview() + [
            {"name": n}
            for n in (
                "preview_status", "preview_fingerprint", "preview_content_hash",
                "preview_payload_id", "preview_asset_manifest", "preview_total_bytes",
                "preview_error_code", "preview_error_message", "preview_generated_at",
                "preview_attempted_at", "preview_failed_at", "style_revision",
            )
        ]
        _migrate_slide_style_preview_columns(conn, insp, None, _qual, is_sqlite=True)
        # Only the backfill UPDATE (no ALTERs).
        assert conn.execute.call_count - first == 1

    def test_skips_when_table_missing(self):
        from src.core.database import _migrate_slide_style_preview_columns

        conn = MagicMock()
        insp = MagicMock()
        insp.get_columns.side_effect = Exception("no such table")
        _migrate_slide_style_preview_columns(conn, insp, None, lambda t: t, is_sqlite=True)
        conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Endpoints (auth + read visibility)
# ---------------------------------------------------------------------------
class TestPreviewEndpoints:
    def test_regenerate_requires_admin_dependency(self):
        """The regenerate route is server-side admin-gated (not just UI)."""
        from src.api.routes.settings.slide_styles import router, regenerate_slide_style_preview
        from src.api.routes._authz import require_admin

        route = next(
            r for r in router.routes
            if getattr(r, "endpoint", None) is regenerate_slide_style_preview
        )
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert require_admin in dep_calls

    def test_get_preview_route_is_not_admin_gated(self):
        """The read endpoint mirrors GET /{id} visibility — no admin dependency."""
        from src.api.routes.settings.slide_styles import router, get_slide_style_preview
        from src.api.routes._authz import require_admin

        route = next(
            r for r in router.routes
            if getattr(r, "endpoint", None) is get_slide_style_preview
        )
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert require_admin not in dep_calls

    def test_get_preview_404_when_style_missing(self):
        """Read endpoint 404s for an unknown style (visibility parity)."""
        from fastapi import HTTPException
        from src.api.routes.settings.slide_styles import get_slide_style_preview

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc:
            get_slide_style_preview(424242, db=mock_db)
        assert exc.value.status_code == 404

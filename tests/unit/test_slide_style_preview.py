"""Unit tests for the slide-style visual preview feature.

Covers the correctness properties the design depends on:
- fingerprint invalidation (style edits AND generation-version bumps),
- deduplicated enqueue (exactly one generation for concurrent readers),
- revision-guarded write-back (a stale generation cannot clobber a fresh edit),
- hostile-output validation (+ last-known-good preserved on failure),
- migration idempotency,
- regenerate endpoint admin gating and read-visibility 404 parity,
- generation through the active Graph Release's builder role,
- reclaiming jobs abandoned in 'queued'/'generating' by a dead worker.

No real LLM call: generation is mocked at ``_generate_deck``, or at the model
adapter under a real ``AgentRuntime`` reading a real persisted v1 release.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

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


@pytest.fixture
def graph_release(db_factory):
    """Seed the real Graph Version 1 release; return its builder definition."""
    from src.services.graph_configuration import GraphConfiguration

    GraphConfiguration().bootstrap_v1(db_factory)
    with db_factory() as s:
        builder = fixture.current_builder_definition(s)
    assert builder is not None
    return builder


def _current_fingerprint(db_factory, style: SlideStyleLibrary) -> str:
    with db_factory() as s:
        builder = fixture.current_builder_definition(s)
    return fixture.compute_fingerprint(style.style_content, style.image_guidelines, builder)


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
_BUILDER = fixture.BuilderDefinition(graph_release_id=1, content_hash="a" * 64)


class TestFingerprint:
    def test_changes_with_style_content(self):
        a = fixture.compute_fingerprint("style A", None, _BUILDER)
        b = fixture.compute_fingerprint("style B", None, _BUILDER)
        assert a != b

    def test_changes_with_image_guidelines(self):
        a = fixture.compute_fingerprint("s", None, _BUILDER)
        b = fixture.compute_fingerprint("s", "prefer photos", _BUILDER)
        assert a != b

    def test_changes_when_generation_version_bumps(self, monkeypatch):
        before = fixture.compute_fingerprint("s", None, _BUILDER)
        monkeypatch.setattr(fixture, "PREVIEW_GENERATION_VERSION", "999")
        after = fixture.compute_fingerprint("s", None, _BUILDER)
        assert before != after

    def test_stable_for_same_inputs(self):
        assert fixture.compute_fingerprint("s", "g", _BUILDER) == fixture.compute_fingerprint(
            "s", "g", _BUILDER
        )

    def test_changes_when_the_builder_definition_changes(self):
        """A publication that changes the builder's prompt or model regenerates."""
        republished = fixture.BuilderDefinition(graph_release_id=2, content_hash="b" * 64)
        assert fixture.compute_fingerprint("s", None, _BUILDER) != fixture.compute_fingerprint(
            "s", None, republished
        )

    def test_stable_across_a_release_that_keeps_the_builder(self):
        """Republishing other roles leaves the builder's hash, so previews stay warm."""
        same_builder = fixture.BuilderDefinition(graph_release_id=2, content_hash="a" * 64)
        assert fixture.compute_fingerprint("s", None, _BUILDER) == fixture.compute_fingerprint(
            "s", None, same_builder
        )

    def test_no_active_release_never_matches_a_generated_preview(self):
        assert fixture.compute_fingerprint("s", None, None) != fixture.compute_fingerprint(
            "s", None, _BUILDER
        )

    def test_reads_the_active_release_builder(self, db_factory, graph_release):
        """The definition is the persisted builder revision, not a code constant."""
        from src.database.models.graph_configuration import (
            AgentDefinitionRevision,
            GraphReleaseAgent,
        )

        with db_factory() as s:
            revision_hash = (
                s.query(AgentDefinitionRevision.content_hash)
                .join(
                    GraphReleaseAgent,
                    GraphReleaseAgent.agent_definition_revision_id
                    == AgentDefinitionRevision.id,
                )
                .filter(
                    GraphReleaseAgent.graph_release_id == graph_release.graph_release_id,
                    GraphReleaseAgent.agent_key == "builder",
                )
                .scalar()
            )
        assert graph_release.content_hash == revision_hash

    def test_no_active_release_reads_none(self, db_factory):
        with db_factory() as s:
            assert fixture.current_builder_definition(s) is None


# ---------------------------------------------------------------------------
# Dedup enqueue
# ---------------------------------------------------------------------------
class TestEnqueueDedup:
    def test_second_enqueue_is_suppressed(self, patched_db, db_factory):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        assert q.try_enqueue(style_id) is True   # wins transition -> queued
        assert q.try_enqueue(style_id) is False  # already queued -> dedup

    def test_ready_and_current_is_not_requeued(self, patched_db, db_factory, graph_release):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        style.preview_status = "ready"
        style.preview_fingerprint = _current_fingerprint(db_factory, style)
        s.commit()
        s.close()
        assert q.try_enqueue(style_id) is False

    def test_missing_style_returns_false(self, patched_db):
        from src.api.services import slide_style_preview_queue as q

        assert q.try_enqueue(999999) is False


def _set_in_flight(db_factory, style_id: int, status: str, age: timedelta) -> None:
    s = db_factory()
    style = s.get(SlideStyleLibrary, style_id)
    style.preview_status = status
    style.preview_attempted_at = datetime.utcnow() - age
    s.commit()
    s.close()


class TestAbandonedJobs:
    """The dispatch queue is process-local: a worker that restarts mid-job leaves
    its row 'queued'/'generating' with nothing left to run it."""

    @pytest.mark.parametrize("status", ["queued", "generating"])
    def test_abandoned_in_flight_row_is_reclaimed(self, patched_db, db_factory, status):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        _set_in_flight(
            db_factory, style_id, status, q.PREVIEW_STALE_AFTER + timedelta(minutes=1)
        )
        assert q.try_enqueue(style_id) is True
        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "queued"
        assert datetime.utcnow() - style.preview_attempted_at < timedelta(minutes=1)
        s.close()

    @pytest.mark.parametrize("status", ["queued", "generating"])
    def test_live_in_flight_row_is_not_reclaimed(self, patched_db, db_factory, status):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        _set_in_flight(db_factory, style_id, status, timedelta(minutes=1))
        assert q.try_enqueue(style_id) is False
        s = db_factory()
        assert s.get(SlideStyleLibrary, style_id).preview_status == status
        s.close()

    def test_worker_does_not_run_a_row_another_job_is_generating(
        self, patched_db, db_factory, graph_release, monkeypatch
    ):
        """A duplicate dispatch of a live job must not start a second generation."""
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        _set_in_flight(db_factory, style_id, "generating", timedelta(minutes=1))
        calls = []
        monkeypatch.setattr(q, "_generate_deck", lambda *a: calls.append(a) or _deck())
        q.process_preview_job(style_id)
        assert calls == []

    def test_worker_restamps_attempted_at_when_it_starts(
        self, patched_db, db_factory, graph_release, monkeypatch
    ):
        """A job that waited long in a busy worker's queue is live once it starts."""
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        _set_in_flight(db_factory, style_id, "queued", timedelta(minutes=20))
        seen = {}

        def _observe(*_args):
            with db_factory() as s:
                style = s.get(SlideStyleLibrary, style_id)
                seen["abandoned"] = q.is_abandoned(
                    style, datetime.utcnow() + timedelta(minutes=15)
                )
            return _deck()

        monkeypatch.setattr(q, "_generate_deck", _observe)
        q.process_preview_job(style_id)
        assert seen == {"abandoned": False}

    def test_dispatch_from_a_worker_thread_reaches_the_loop(self, monkeypatch):
        """try_enqueue runs on threadpool threads; the queue belongs to the loop.

        Run in asyncio debug mode, which raises on a non-thread-safe call from
        another thread instead of leaving the wakeup to chance.
        """
        from src.api.services import slide_style_preview_queue as q

        async def _main():
            monkeypatch.setattr(q, "preview_queue", asyncio.Queue())
            monkeypatch.setattr(q, "_worker_loop", asyncio.get_running_loop())
            getter = asyncio.create_task(q.preview_queue.get())
            await asyncio.sleep(0)  # the getter is now waiting on the loop
            await asyncio.to_thread(q._dispatch, 7)
            return await asyncio.wait_for(getter, timeout=2)

        assert asyncio.run(_main(), debug=True) == 7

    def test_dispatch_without_a_worker_leaves_the_row_queued(self, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        monkeypatch.setattr(q, "_worker_loop", None)
        q._dispatch(7)  # no raise


# ---------------------------------------------------------------------------
# Startup warming (backfill)
# ---------------------------------------------------------------------------
class TestWarmBackfill:
    def test_warms_active_styles_and_skips_ready_and_inactive(
        self, patched_db, db_factory, graph_release
    ):
        from src.api.services import slide_style_preview_queue as q

        # Two active styles to warm; one already ready+current (skipped); one inactive.
        warm_a = _make_style(db_factory, name="A")
        warm_b = _make_style(db_factory, name="B")
        ready_id = _make_style(db_factory, name="Ready")
        inactive_id = _make_style(db_factory, name="Inactive")

        s = db_factory()
        ready = s.get(SlideStyleLibrary, ready_id)
        ready.preview_status = "ready"
        ready.preview_fingerprint = _current_fingerprint(db_factory, ready)
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
    def test_generates_validates_and_caches(self, patched_db, db_factory, graph_release, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)
        monkeypatch.setattr(q, "_generate_deck", lambda *_: _deck(slides=3))
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "ready"
        assert style.preview_payload_id is not None
        payload = storage.load_payload(s, style.preview_payload_id)
        assert payload is not None
        assert len(payload["slides"]) == 3
        s.close()

    def test_null_revision_row_is_promoted(self, patched_db, db_factory, graph_release, monkeypatch):
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
        monkeypatch.setattr(q, "_generate_deck", lambda *_: _deck(slides=2))
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

    def test_failure_preserves_last_known_good(self, patched_db, db_factory, graph_release, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        # First, a successful generation establishes last-known-good.
        q.try_enqueue(style_id)
        monkeypatch.setattr(q, "_generate_deck", lambda *_: _deck(slides=2))
        q.process_preview_job(style_id)
        s = db_factory()
        good_payload_id = s.get(SlideStyleLibrary, style_id).preview_payload_id
        s.close()
        assert good_payload_id is not None

        # Now force a failing regeneration; the good payload must survive.
        s = db_factory()
        s.get(SlideStyleLibrary, style_id).preview_status = "queued"
        s.commit(); s.close()

        def _boom(*_):
            raise RuntimeError("provider down")

        monkeypatch.setattr(q, "_generate_deck", _boom)
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "failed"
        assert style.preview_error_code == "generation_error"
        assert style.preview_payload_id == good_payload_id  # preserved
        s.close()

    def test_revision_race_discards_stale_generation(self, patched_db, db_factory, graph_release, monkeypatch):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)

        # Simulate a concurrent edit: bump style_revision DURING generation so the
        # write-back guard (revision unchanged) fails and the result is discarded.
        def _generate_then_edit(sid, *_):
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

    def test_no_active_release_fails_without_calling_a_model(
        self, patched_db, db_factory, monkeypatch
    ):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)
        calls = []
        monkeypatch.setattr(q, "_generate_deck", lambda *a: calls.append(a) or _deck())
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "failed"
        assert style.preview_error_code == "no_active_release"
        s.close()
        assert calls == []

    def test_transient_provider_failure_is_retried(
        self, patched_db, db_factory, graph_release, monkeypatch
    ):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)
        calls = []

        def _timeout(*a):
            calls.append(a)
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://x"))

        monkeypatch.setattr(q, "_generate_deck", _timeout)
        q.process_preview_job(style_id)

        assert len(calls) == 1 + q.PREVIEW_MAX_RETRIES
        s = db_factory()
        assert s.get(SlideStyleLibrary, style_id).preview_error_code == "generation_error"
        s.close()

    def test_non_transient_failure_is_not_retried(
        self, patched_db, db_factory, graph_release, monkeypatch
    ):
        """A removed endpoint or invalid release fails the same way every time."""
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)
        calls = []

        def _broken(*a):
            calls.append(a)
            raise RuntimeError("endpoint removed")

        monkeypatch.setattr(q, "_generate_deck", _broken)
        q.process_preview_job(style_id)
        assert len(calls) == 1

    def test_schema_validation_error_is_not_stored_as_a_rejection_code(
        self, patched_db, db_factory, graph_release, monkeypatch
    ):
        """pydantic's ValidationError is a ValueError; its text is no error code
        (and would overflow the VARCHAR(64) column on Postgres)."""
        from src.api.services import slide_style_preview_queue as q

        class _Strict(BaseModel):
            n: int

        def _invalid(*a):
            _Strict(n="not a number")

        style_id = _make_style(db_factory)
        q.try_enqueue(style_id)
        monkeypatch.setattr(q, "_generate_deck", _invalid)
        with pytest.raises(ValidationError):
            _invalid()
        q.process_preview_job(style_id)

        s = db_factory()
        assert s.get(SlideStyleLibrary, style_id).preview_error_code == "generation_error"
        s.close()


# ---------------------------------------------------------------------------
# Generation through the graph builder role (real runtime, fake model)
# ---------------------------------------------------------------------------
class _RecordingAdapter:
    """Stands in for ``DatabricksModelAdapter``: records calls, returns one slide."""

    def __init__(self):
        import threading

        self.calls = []
        self._lock = threading.Lock()

    def invoke(self, *, agent_key, configuration, schema, prompt):
        import re

        position = int(re.search(r'"position": (\d+)', prompt).group(1))
        with self._lock:
            self.calls.append(
                {
                    "agent_key": agent_key,
                    "configuration": configuration,
                    "prompt": prompt,
                    "position": position,
                }
            )
        return schema(
            position=position,
            html=f"<div class='slide'><h1>Slide {position}</h1></div>",
            scripts="",
        )


@pytest.fixture
def builder_runtime(db_factory, graph_release, monkeypatch):
    """A production ``AgentRuntime`` over the seeded release, model faked."""
    import logging

    from src.api.services import slide_style_preview_queue as q
    from src.services.agent_runtime import AgentRuntime
    from src.services.agent_runtime_identity import LoggingAgentInvocationIdentitySink
    from src.services.persisted_graph_release import PersistedGraphReleaseLoader

    adapter = _RecordingAdapter()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=db_factory),
        model_adapter=adapter,
        identity_sink=LoggingAgentInvocationIdentitySink(logger=logging.getLogger(__name__)),
    )
    monkeypatch.setattr(q, "get_agent_runtime", lambda: runtime)
    return adapter


def _release_builder_model(db_factory, graph_release):
    from src.services.persisted_graph_release import PersistedGraphReleaseLoader

    loader = PersistedGraphReleaseLoader(session_factory=db_factory)
    return loader.resolve(graph_release.graph_release_id, "builder").content.model


class TestBuilderGeneration:
    def test_each_canonical_slide_is_built_by_the_release_builder(
        self, db_factory, graph_release, builder_runtime
    ):
        from src.api.services import slide_style_preview_queue as q

        style = "SIGNATURE-STYLE: teal serif headings on warm sand."
        deck = q._generate_deck(1, style, graph_release)

        calls = builder_runtime.calls
        assert len(calls) == len(fixture.PREVIEW_SLIDE_SPECS)
        assert {c["agent_key"] for c in calls} == {"builder"}
        assert sorted(c["position"] for c in calls) == [
            spec.position for spec in fixture.PREVIEW_SLIDE_SPECS
        ]
        assert all(style in c["prompt"] for c in calls)
        assert deck == {
            "slides": [
                {"html": f"<div class='slide'><h1>Slide {spec.position}</h1></div>"}
                for spec in fixture.PREVIEW_SLIDE_SPECS
            ],
            "css": "",
        }

    def test_the_model_is_the_published_builder_model_on_the_gateway(
        self, db_factory, graph_release, builder_runtime
    ):
        """No model is named in preview code: the release's builder decides it,
        under its Unity AI Gateway ``system.ai.*`` name."""
        from src.api.services import slide_style_preview_queue as q

        q._generate_deck(1, "s", graph_release)
        published = _release_builder_model(db_factory, graph_release)
        endpoints = {c["configuration"].endpoint_name for c in builder_runtime.calls}
        assert endpoints == {published.endpoint_name}
        assert published.endpoint_name.startswith("system.ai.")
        assert {c["configuration"].max_tokens for c in builder_runtime.calls} == {
            published.max_tokens
        }

    def test_preview_payload_is_the_graph_builder_payload(self):
        from src.services.graph.nodes import _BUILDER_MODEL_PAYLOAD_KEYS

        for spec in fixture.PREVIEW_SLIDE_SPECS:
            payload = fixture.builder_payload(spec, "s")
            assert set(payload) == _BUILDER_MODEL_PAYLOAD_KEYS
            assert payload["design_system_active"] is False
            assert payload["resolved_style"] == "s"

    def test_metric_slide_supplies_no_figures(self):
        """Figures make the builder draw a Chart.js chart, which the script-less
        preview iframe cannot run."""
        assert fixture.PREVIEW_RESOLVED_DATA.figures == []

    def test_job_caches_builder_slides_under_the_builder_fingerprint(
        self, patched_db, db_factory, graph_release, builder_runtime
    ):
        from src.api.services import slide_style_preview_queue as q

        style_id = _make_style(db_factory)
        assert q.try_enqueue(style_id) is True
        q.process_preview_job(style_id)

        s = db_factory()
        style = s.get(SlideStyleLibrary, style_id)
        assert style.preview_status == "ready"
        assert style.preview_fingerprint == fixture.compute_fingerprint(
            style.style_content, style.image_guidelines, graph_release
        )
        payload = storage.load_payload(s, style.preview_payload_id)
        assert len(payload["slides"]) == len(fixture.PREVIEW_SLIDE_SPECS)
        s.close()
        # Ready and current: nothing more to generate.
        assert q.try_enqueue(style_id) is False


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

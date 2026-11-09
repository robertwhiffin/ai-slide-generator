"""Unit B: image-generation job store and runner (``src/api/services/image_generation_jobs.py``).

Contract: ``docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md``,
section "Unit B interface". Image jobs reuse ``export_jobs`` rows whose
``session_id`` is ``"image-generation:" + owner``; the result is JSON
``{"image_token": ...}`` in ``output_path``.

Harness
-------
* A FILE-backed SQLite database per test (``tmp_path``) with the default pool, so
  every session gets its OWN connection and a probe session sees only COMMITTED
  state: exactly what a poll from another uvicorn worker sees. (An in-memory
  ``StaticPool`` engine shares one connection, so an uncommitted "running" would
  look committed and the mid-generation status test would prove nothing.)
  Consequence for the implementation: commit every status transition in its own
  short session (as ``export_job_queue._update_job_field`` does). Do not hold a
  write transaction open across the generator call or the save.
* ``session_factory`` is a context manager shaped like ``get_db_session`` (commit
  on success, rollback on error, close), bound to that database and passed
  explicitly. Nothing patches ``src.core.database``, so a function that ignores
  its ``session_factory`` writes somewhere else and fails here.
* The generator is a fake with the ``ImageGenerator`` surface (``generate`` /
  ``edit``) that returns a real ``GeneratedImage`` built from real PNG/JPEG/SVG
  bytes, or raises from a nested frame (so a stored traceback would be visible).
  ``save_generated_image`` (Unit A) is REAL, so assertions read real
  ``image_assets`` rows.
* ``_submit`` is patched to CAPTURE work (returning a pending ``Future``). The
  in-flight counter is module state, so the fixture replays everything still
  captured at teardown, bringing the counter back to zero for later tests.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401  (register every table before create_all)
from src.api.services import image_generation_jobs as jobs
from src.api.services.image_generation_jobs import (
    JOB_SESSION_PREFIX,
    JOB_STALE_SECONDS,
    MAX_INFLIGHT,
    MAX_WORKERS,
    EditSpec,
    GenerationSpec,
    create_job,
    get_job,
    run_job,
    submit,
)
from src.core.database import Base
from src.database.models.image import ImageAsset
from src.database.models.session import ExportJob
from src.services.image_generation import (
    PRESETS,
    GeneratedImage,
    ImageGenerationError,
)

OWNER = "alice@test.com"
OTHER = "bob@test.com"
PROMPT = "A calm navy gradient with soft light and room for a title"

#: The four presets the interface names (not derived from PRESETS, so an empty
#: or renamed PRESETS cannot shrink this suite to nothing).
PRESET_IDS = ["background", "illustration", "icon_png", "icon_svg"]

#: Exact user-facing messages from the interface.
MSG_403_PREFIX = "The app identity cannot use the image model (403)."
MSG_429 = "The image model is rate limited (429). Try again shortly."
MSG_UNEXPECTED = "Image generation failed"
MSG_TIMED_OUT = "Image generation timed out"

SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<circle cx="12" cy="12" r="10" fill="#1f77b4"/></svg>'
)


# ---------------------------------------------------------------------------
# Real image bytes
# ---------------------------------------------------------------------------


def _png(color=(0, 128, 255, 255), size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(color=(10, 40, 90), size=(48, 27)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


_BY_FORMAT = {
    "jpeg": (lambda: _jpeg(), "image/jpeg", "jpg"),
    "png": (lambda: _png(), "image/png", "png"),
    "svg": (lambda: SVG_BYTES, "image/svg+xml", "svg"),
}


def _generated(preset_id: str, model: Optional[str] = None) -> GeneratedImage:
    """What a real generator returns for *preset_id*: right format, the model it used."""
    preset = PRESETS[preset_id]
    make, mime, ext = _BY_FORMAT[preset.output_format]
    return GeneratedImage(
        data=make(),
        mime=mime,
        ext=ext,
        model=model or preset.default_model,
        preset_id=preset_id,
        revised_prompt=None,
        latency_s=0.01,
        usage=None,
    )


def _edited(model: str, data: Optional[bytes] = None) -> GeneratedImage:
    return GeneratedImage(
        data=data or _png(color=(200, 30, 30, 255)),
        mime="image/png",
        ext="png",
        model=model,
        preset_id=None,
        revised_prompt=None,
        latency_s=0.01,
        usage=None,
    )


# ---------------------------------------------------------------------------
# Fake generator
# ---------------------------------------------------------------------------


def _raise_from_a_nested_frame(exc: BaseException) -> None:
    def _deep_in_the_client():
        raise exc

    _deep_in_the_client()


class FakeGenerator:
    """The ``ImageGenerator`` surface. Records calls; returns ``result`` or raises ``raises``.

    ``during`` runs inside the call, i.e. while the image is "being generated".
    """

    def __init__(
        self,
        result: Optional[GeneratedImage] = None,
        *,
        raises: Optional[BaseException] = None,
        during: Optional[Callable[[], None]] = None,
    ) -> None:
        self.result = result
        self.raises = raises
        self.during = during
        self.calls: list[tuple[str, dict]] = []

    def _respond(self, kind: str, **kwargs: Any) -> GeneratedImage:
        self.calls.append((kind, kwargs))
        if self.during is not None:
            self.during()
        if self.raises is not None:
            _raise_from_a_nested_frame(self.raises)
        assert self.result is not None, "FakeGenerator needs a result or raises"
        return self.result

    def generate(self, prompt, preset_id, model=None, quality=None):
        return self._respond(
            "generate", prompt=prompt, preset_id=preset_id, model=model, quality=quality
        )

    def edit(self, prompt, source, source_mime, model=None, quality=None):
        return self._respond(
            "edit", prompt=prompt, source=source, source_mime=source_mime,
            model=model, quality=quality,
        )


# ---------------------------------------------------------------------------
# Database fixtures and readers
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'image-jobs.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    """Production session settings (``get_session_local``): no autoflush."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def session_factory(factory):
    """A ``get_db_session``-shaped context manager on the test database."""

    @contextlib.contextmanager
    def _session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _session


_JOB_COLUMNS = (
    "job_id", "session_id", "status", "status_message", "error_message",
    "output_path", "title", "created_at", "completed_at",
)


def _job(factory, job_id: str) -> Optional[dict]:
    """The job row as COMMITTED (fresh connection), or None."""
    db = factory()
    try:
        row = db.query(ExportJob).filter(ExportJob.job_id == job_id).first()
        return None if row is None else {c: getattr(row, c) for c in _JOB_COLUMNS}
    finally:
        db.close()


def _images(factory) -> list[dict]:
    db = factory()
    try:
        return [
            {
                "token": r.token, "tags": list(r.tags or []), "category": r.category,
                "description": r.description, "uploaded_by": r.uploaded_by,
                "is_active": r.is_active, "mime_type": r.mime_type,
                "image_data": r.image_data,
            }
            for r in db.query(ImageAsset).order_by(ImageAsset.id).all()
        ]
    finally:
        db.close()


def _set_job(factory, job_id: str, **fields) -> None:
    db = factory()
    try:
        row = db.query(ExportJob).filter(ExportJob.job_id == job_id).one()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def _seed_export_job(factory, *, job_id: str, session_id: str, **fields) -> None:
    db = factory()
    try:
        db.add(ExportJob(job_id=job_id, session_id=session_id, **fields))
        db.commit()
    finally:
        db.close()


def _token_of(job: dict) -> str:
    return json.loads(job["output_path"])["image_token"]


def _stale(extra_seconds: int = 60) -> datetime:
    # ExportJob.created_at defaults to naive datetime.utcnow(); stay in that frame.
    return datetime.utcnow() - timedelta(seconds=JOB_STALE_SECONDS + extra_seconds)


# ---------------------------------------------------------------------------
# Interface constants
# ---------------------------------------------------------------------------


def test_interface_constants():
    assert JOB_SESSION_PREFIX == "image-generation:"
    # A queued job can wait behind one run on each worker, then run itself; every run is
    # capped by its preset timeout (the stream reader's deadline), plus time to save.
    assert JOB_STALE_SECONDS == 600
    assert JOB_STALE_SECONDS >= 2 * max(p.timeout_s for p in PRESETS.values()) + 60
    assert MAX_WORKERS == 2
    assert MAX_INFLIGHT == 4


# ---------------------------------------------------------------------------
# create_job
# ---------------------------------------------------------------------------


class TestCreateJob:
    def test_writes_a_pending_row_bound_to_the_owner(self, factory, session_factory):
        job_id = create_job(owner=OWNER, title="Calm gradient", session_factory=session_factory)

        row = _job(factory, job_id)
        assert row is not None, "create_job must commit a row through session_factory"
        assert row["session_id"] == "image-generation:" + OWNER
        assert row["status"] == "pending"
        assert row["status_message"] == "Queued"
        assert row["title"] == "Calm gradient"
        assert row["output_path"] is None
        assert row["error_message"] is None
        assert row["completed_at"] is None

    def test_title_is_truncated_to_512_characters(self, factory, session_factory):
        # SQLite does not enforce String(512); Postgres would reject the insert.
        job_id = create_job(owner=OWNER, title="t" * 600, session_factory=session_factory)
        assert _job(factory, job_id)["title"] == "t" * 512

    def test_job_ids_are_unique_and_unguessable(self, session_factory):
        a = create_job(owner=OWNER, title="a", session_factory=session_factory)
        b = create_job(owner=OWNER, title="b", session_factory=session_factory)
        assert a != b
        for job_id in (a, b):
            # export_job_queue.generate_job_id(): secrets.token_urlsafe(24), 32 chars.
            assert len(job_id) >= 32
            assert re.fullmatch(r"[A-Za-z0-9_-]+", job_id)


# ---------------------------------------------------------------------------
# run_job: generation
# ---------------------------------------------------------------------------


class TestRunJobGeneration:
    @pytest.mark.parametrize("preset_id", PRESET_IDS)
    def test_success_saves_an_owned_library_image(self, preset_id, factory, session_factory):
        preset = PRESETS[preset_id]
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        gen = FakeGenerator(_generated(preset_id))

        result = run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id=preset_id),
            generator=gen, session_factory=session_factory,
        )

        assert result is None
        row = _job(factory, job_id)
        assert row["status"] == "completed"
        assert row["status_message"] == "Done"
        assert row["completed_at"] is not None
        assert row["error_message"] is None

        images = _images(factory)
        assert len(images) == 1
        image = images[0]
        assert _token_of(row) == image["token"]
        assert image["is_active"] is True
        assert image["uploaded_by"] == OWNER
        assert image["tags"] == ["ai_generated", preset.default_model, preset_id]
        assert image["category"] == preset.category
        assert image["description"] == PROMPT
        assert image["mime_type"] == _BY_FORMAT[preset.output_format][1]

        assert [kind for kind, _ in gen.calls] == ["generate"]
        call = gen.calls[0][1]
        assert call["prompt"] == PROMPT, "the raw user prompt goes to the generator"
        assert call["preset_id"] == preset_id

    def test_explicit_model_and_quality_reach_the_generator_and_the_tags(
        self, factory, session_factory
    ):
        preset = PRESETS["background"]
        model = preset.models[-1]
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        gen = FakeGenerator(_generated("background", model=model))

        run_job(
            job_id, owner=OWNER,
            spec=GenerationSpec(prompt=PROMPT, preset_id="background", model=model, quality="high"),
            generator=gen, session_factory=session_factory,
        )

        call = gen.calls[0][1]
        assert call["model"] == model
        assert call["quality"] == "high"
        assert _images(factory)[0]["tags"] == ["ai_generated", model, "background"]

    def test_row_reads_running_while_the_image_is_generated(self, factory, session_factory):
        """Another worker polling mid-generation must see a COMMITTED running state."""
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        seen: list[dict] = []
        gen = FakeGenerator(
            _generated("icon_png"), during=lambda: seen.append(_job(factory, job_id))
        )

        run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=gen, session_factory=session_factory,
        )

        assert len(seen) == 1
        assert seen[0]["status"] == "running"
        assert seen[0]["status_message"] == "Generating image..."
        assert _job(factory, job_id)["status"] == "completed"


# ---------------------------------------------------------------------------
# run_job: edit
# ---------------------------------------------------------------------------


def _edit_spec(**overrides) -> EditSpec:
    fields = dict(
        prompt="make the background navy",
        source_bytes=_png(color=(0, 200, 0, 255)),
        source_mime="image/png",
        source_name="team-logo.png",
        source_category="ephemeral",
        model="gpt-image-2.6-flare",
        quality="low",
    )
    fields.update(overrides)
    return EditSpec(**fields)


class TestRunJobEdit:
    def test_edit_saves_a_new_image_from_the_source(self, factory, session_factory):
        spec = _edit_spec()
        job_id = create_job(owner=OWNER, title=spec.prompt, session_factory=session_factory)
        gen = FakeGenerator(_edited(model=spec.model))

        run_job(job_id, owner=OWNER, spec=spec, generator=gen, session_factory=session_factory)

        row = _job(factory, job_id)
        assert row["status"] == "completed"
        assert row["status_message"] == "Done"
        assert row["completed_at"] is not None
        images = _images(factory)
        assert len(images) == 1
        image = images[0]
        assert _token_of(row) == image["token"]
        assert image["uploaded_by"] == OWNER
        assert image["tags"] == ["ai_generated", "ai_edit", spec.model]
        # An ephemeral (chat-pasted) source yields a library image, not another
        # private ephemeral one.
        assert image["category"] == "content"
        assert image["description"].startswith("Edit of team-logo.png: ")
        assert image["description"] == "Edit of team-logo.png: make the background navy"

        assert [kind for kind, _ in gen.calls] == ["edit"]
        call = gen.calls[0][1]
        assert call["prompt"] == spec.prompt
        assert call["source"] == spec.source_bytes
        assert call["source_mime"] == "image/png"
        assert call["model"] == spec.model
        assert call["quality"] == "low"

    @pytest.mark.parametrize("category", ["background", "content", "branding"])
    def test_non_ephemeral_source_category_is_kept(self, category, factory, session_factory):
        spec = _edit_spec(source_category=category)
        job_id = create_job(owner=OWNER, title=spec.prompt, session_factory=session_factory)

        run_job(
            job_id, owner=OWNER, spec=spec,
            generator=FakeGenerator(_edited(model=spec.model)), session_factory=session_factory,
        )

        assert _images(factory)[0]["category"] == category


# ---------------------------------------------------------------------------
# run_job: errors
# ---------------------------------------------------------------------------


def _assert_clean_error(factory, job_id: str) -> str:
    row = _job(factory, job_id)
    assert row["status"] == "error"
    # Never null: pollExportJob shows "Processing slide 0 of 0" for a null message.
    assert row["status_message"] == "Failed"
    message = row["error_message"]
    assert message, "an error job must carry a message"
    assert len(message) <= 300
    assert "Traceback" not in message
    assert 'File "' not in message
    assert _images(factory) == [], "no image row may be created on error"
    return message


class TestRunJobErrors:
    @pytest.mark.parametrize(
        "exc, expected",
        [
            pytest.param(
                ImageGenerationError(
                    "PERMISSION_DENIED on system.ai.gpt-5-4-nano", status_code=403
                ),
                None, id="403",
            ),
            pytest.param(
                ImageGenerationError("Too Many Requests", status_code=429), MSG_429, id="429",
            ),
            pytest.param(
                ImageGenerationError("The model returned no image"),
                "The model returned no image", id="image-error-no-status",
            ),
            pytest.param(
                ImageGenerationError("Upstream returned 502 Bad Gateway", status_code=502),
                "Upstream returned 502 Bad Gateway", id="image-error-other-status",
            ),
            pytest.param(
                ValueError("SVG contains a disallowed <script> element"),
                "SVG contains a disallowed <script> element", id="value-error",
            ),
            pytest.param(
                RuntimeError("pool exhausted at 0x7f3a internal detail"), MSG_UNEXPECTED,
                id="unexpected-runtime-error",
            ),
            pytest.param(KeyError("output"), MSG_UNEXPECTED, id="unexpected-key-error"),
        ],
    )
    def test_generator_failure_maps_to_a_clean_message(
        self, exc, expected, factory, session_factory
    ):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)

        result = run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(raises=exc), session_factory=session_factory,
        )

        assert result is None, "run_job never raises"
        message = _assert_clean_error(factory, job_id)
        if expected is None:  # 403: fixed guidance, wording after the first sentence is free
            assert message.startswith(MSG_403_PREFIX)
        else:
            assert message == expected
        info = get_job(job_id, owner=OWNER, session_factory=session_factory)
        assert info["status"] == "error"
        assert info["error"] == message
        assert info["image_token"] is None

    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(ImageGenerationError("x" * 1000, status_code=500), id="image-error"),
            pytest.param(ValueError("y" * 1000), id="value-error"),
        ],
    )
    def test_long_messages_are_capped_at_300(self, exc, factory, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)

        run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(raises=exc), session_factory=session_factory,
        )

        message = _assert_clean_error(factory, job_id)
        assert message[:200] == str(exc)[:200]

    def test_edit_failure_maps_like_generation(self, factory, session_factory):
        job_id = create_job(owner=OWNER, title="edit", session_factory=session_factory)

        run_job(
            job_id, owner=OWNER, spec=_edit_spec(),
            generator=FakeGenerator(raises=ImageGenerationError("nope", status_code=429)),
            session_factory=session_factory,
        )

        assert _assert_clean_error(factory, job_id) == MSG_429

    def test_a_failed_save_ends_in_error_not_stuck(self, factory, session_factory):
        """Failure AFTER generation (the library rejects the bytes) must still finish the job."""
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        too_big = GeneratedImage(
            data=b"x" * (5 * 1024 * 1024 + 1), mime="image/png", ext="png",
            model=PRESETS["icon_png"].default_model, preset_id="icon_png",
            revised_prompt=None, latency_s=0.01, usage=None,
        )

        result = run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(too_big), session_factory=session_factory,
        )

        assert result is None
        _assert_clean_error(factory, job_id)

    def test_unknown_job_id_does_not_raise(self, session_factory):
        run_job(
            "no-such-job", owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(_generated("icon_png")), session_factory=session_factory,
        )

    def test_database_failure_does_not_raise(self):
        @contextlib.contextmanager
        def broken_session():
            raise RuntimeError("database is unreachable")
            yield  # pragma: no cover

        run_job(
            "any-job", owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(_generated("icon_png")), session_factory=broken_session,
        )


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------


class TestGetJob:
    def test_owner_sees_their_pending_job(self, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)

        info = get_job(job_id, owner=OWNER, session_factory=session_factory)

        assert info is not None
        assert set(info) >= {"job_id", "status", "status_message", "error", "image_token"}
        assert info["job_id"] == job_id
        assert info["status"] == "pending"
        assert info["status_message"] == "Queued"
        assert info["error"] is None
        assert info["image_token"] is None

    def test_owner_sees_the_image_token_once_completed(self, factory, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(_generated("icon_png")), session_factory=session_factory,
        )

        info = get_job(job_id, owner=OWNER, session_factory=session_factory)

        assert info["status"] == "completed"
        assert info["status_message"] == "Done"
        assert info["error"] is None
        assert info["image_token"] == _images(factory)[0]["token"]

    def test_another_owner_gets_none(self, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)

        assert get_job(job_id, owner=OTHER, session_factory=session_factory) is None
        assert get_job(job_id, owner="", session_factory=session_factory) is None

    @pytest.mark.parametrize(
        "job_owner, caller",
        [
            ("alice@test.com.attacker.example", "alice@test.com"),
            ("alice@test.com", "alice"),
        ],
    )
    def test_owner_match_is_exact_not_a_prefix(self, job_owner, caller, session_factory):
        job_id = create_job(owner=job_owner, title=PROMPT, session_factory=session_factory)
        assert get_job(job_id, owner=caller, session_factory=session_factory) is None

    @pytest.mark.parametrize("caller", [OWNER, "deck-123"])
    def test_a_real_export_job_is_invisible(self, caller, factory, session_factory):
        _seed_export_job(
            factory, job_id="pptx-job-1", session_id="deck-123", status="completed",
            output_path="/tmp/deck-123.pptx",
        )
        assert get_job("pptx-job-1", owner=caller, session_factory=session_factory) is None

    def test_a_stale_real_export_job_is_not_touched(self, factory, session_factory):
        _seed_export_job(
            factory, job_id="pptx-job-2", session_id="deck-123", status="running",
            created_at=_stale(),
        )

        assert get_job("pptx-job-2", owner=OWNER, session_factory=session_factory) is None

        row = _job(factory, "pptx-job-2")
        assert row["status"] == "running"
        assert row["error_message"] is None

    def test_unknown_id_gets_none(self, session_factory):
        assert get_job("no-such-job", owner=OWNER, session_factory=session_factory) is None

    @pytest.mark.parametrize("status", ["pending", "running"])
    def test_a_stale_job_times_out_and_is_persisted(self, status, factory, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        _set_job(factory, job_id, status=status, created_at=_stale())

        info = get_job(job_id, owner=OWNER, session_factory=session_factory)

        assert info["status"] == "error"
        assert info["error"] == MSG_TIMED_OUT
        assert info["status_message"] == "Failed"
        row = _job(factory, job_id)
        assert row["status"] == "error", "the timeout must be PERSISTED, not just reported"
        assert row["error_message"] == MSG_TIMED_OUT
        assert row["status_message"] == "Failed"

    def test_a_recent_running_job_is_not_timed_out(self, factory, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        recent = datetime.utcnow() - timedelta(seconds=JOB_STALE_SECONDS - 60)
        _set_job(factory, job_id, status="running", created_at=recent)

        assert get_job(job_id, owner=OWNER, session_factory=session_factory)["status"] == "running"
        assert _job(factory, job_id)["status"] == "running"

    def test_an_old_completed_job_stays_completed(self, factory, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        run_job(
            job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
            generator=FakeGenerator(_generated("icon_png")), session_factory=session_factory,
        )
        _set_job(factory, job_id, created_at=_stale(3600))

        info = get_job(job_id, owner=OWNER, session_factory=session_factory)

        assert info["status"] == "completed"
        assert info["image_token"] == _images(factory)[0]["token"]

    def test_another_owner_cannot_time_out_my_job(self, factory, session_factory):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        _set_job(factory, job_id, status="running", created_at=_stale())

        assert get_job(job_id, owner=OTHER, session_factory=session_factory) is None
        assert _job(factory, job_id)["status"] == "running"


# ---------------------------------------------------------------------------
# submit: the in-flight cap
# ---------------------------------------------------------------------------


class CapturedSubmit:
    """Stands in for ``_submit``: captures work, returns a pending Future, replays on demand."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self.calls: list[tuple[Callable, tuple, dict, Future]] = []
        self._replayed: set[int] = set()

    def __call__(self, fn, /, *args, **kwargs):
        future: Future = Future()
        with self._lock:
            self.calls.append((fn, args, kwargs, future))
        return future

    def replay(self, index: int, generator: FakeGenerator) -> None:
        """Run captured work *index* as the executor would, against the test database."""
        fn, args, kwargs, future = self.calls[index]
        assert index not in self._replayed
        self._replayed.add(index)
        kwargs = {**kwargs, "generator": generator, "session_factory": self._session_factory}
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # the executor swallows into the Future
            future.set_exception(exc)

    def drain(self) -> None:
        for index in range(len(self.calls)):
            if index not in self._replayed:
                self.replay(index, FakeGenerator(_generated("icon_png")))


@pytest.fixture
def captured(monkeypatch, session_factory):
    seam = CapturedSubmit(session_factory)
    monkeypatch.setattr(jobs, "_submit", seam)
    yield seam
    seam.drain()  # return the module's in-flight counter to zero


def _new_job(session_factory, owner: str = OWNER) -> str:
    return create_job(owner=owner, title=PROMPT, session_factory=session_factory)


SPEC = GenerationSpec(prompt=PROMPT, preset_id="icon_png")


class TestSubmit:
    def test_submit_hands_the_job_to_the_executor_seam(self, captured, factory, session_factory):
        job_id = _new_job(session_factory)

        assert submit(job_id, owner=OWNER, spec=SPEC) is True

        assert len(captured.calls) == 1
        assert _job(factory, job_id)["status"] == "pending", "submit only queues the work"
        captured.replay(0, FakeGenerator(_generated("icon_png")))
        row = _job(factory, job_id)
        assert row["status"] == "completed"
        assert row["status_message"] == "Done"
        image = _images(factory)[0]
        assert image["uploaded_by"] == OWNER
        assert image["tags"][-1] == "icon_png"

    def test_the_submit_after_max_inflight_is_refused(self, captured, factory, session_factory):
        accepted = [_new_job(session_factory) for _ in range(MAX_INFLIGHT)]
        for job_id in accepted:
            assert submit(job_id, owner=OWNER, spec=SPEC) is True

        refused = _new_job(session_factory)
        assert submit(refused, owner=OWNER, spec=SPEC) is False

        assert len(captured.calls) == MAX_INFLIGHT, "a refused submit must not reach _submit"
        row = _job(factory, refused)
        assert row["status"] == "pending"
        assert row["status_message"] == "Queued"

    def test_capacity_frees_when_a_job_finishes(self, captured, session_factory):
        for _ in range(MAX_INFLIGHT):
            assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is True
        assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is False

        captured.replay(0, FakeGenerator(_generated("icon_png")))

        assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is True
        assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is False

    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(RuntimeError("boom"), id="unexpected"),
            pytest.param(ImageGenerationError("denied", status_code=403), id="image-error"),
        ],
    )
    def test_capacity_frees_when_the_generator_raises(
        self, exc, captured, factory, session_factory
    ):
        submitted = [_new_job(session_factory) for _ in range(MAX_INFLIGHT)]
        for job_id in submitted:
            assert submit(job_id, owner=OWNER, spec=SPEC) is True

        captured.replay(0, FakeGenerator(raises=exc))

        assert _job(factory, submitted[0])["status"] == "error"
        assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is True

    def test_counter_returns_to_exactly_zero(self, captured, session_factory):
        """A double decrement would let MAX_INFLIGHT + 1 through on the second round."""
        for _ in range(MAX_INFLIGHT):
            assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is True
        captured.drain()

        for _ in range(MAX_INFLIGHT):
            assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is True
        assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is False

    def test_running_an_unsubmitted_job_frees_no_capacity(self, captured, session_factory):
        """``run_job``'s ``finally`` may only release a slot its job HOLDS.

        Direct calls (every run_job test above, a retry, a stray replay) must not
        drive the count below the real in-flight work, or the cap stops capping.
        Track in-flight work per job_id (e.g. a set that ``submit`` adds to and
        ``run_job`` discards from), not as a bare counter.
        """
        for _ in range(MAX_INFLIGHT):
            assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is True
        stray = _new_job(session_factory)

        run_job(
            stray, owner=OWNER, spec=SPEC,
            generator=FakeGenerator(_generated("icon_png")), session_factory=session_factory,
        )

        assert submit(_new_job(session_factory), owner=OWNER, spec=SPEC) is False

    def test_concurrent_submits_respect_the_cap(self, captured, session_factory):
        job_ids = [_new_job(session_factory) for _ in range(MAX_INFLIGHT * 4)]
        barrier = threading.Barrier(len(job_ids))
        results: list[bool] = []
        lock = threading.Lock()

        def _go(job_id):
            barrier.wait(timeout=10)
            ok = submit(job_id, owner=OWNER, spec=SPEC)
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=_go, args=(j,)) for j in job_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(results) == len(job_ids)
        assert results.count(True) == MAX_INFLIGHT
        assert len(captured.calls) == MAX_INFLIGHT


# ---------------------------------------------------------------------------
# _submit: the real executor seam
# ---------------------------------------------------------------------------


class TestExecutorSeam:
    def test_work_runs_on_a_named_background_thread(self):
        caller = threading.current_thread().name

        future = jobs._submit(lambda x: (x, threading.current_thread().name), 7)

        value, worker = future.result(timeout=10)
        assert value == 7
        assert worker != caller
        assert worker.startswith("image-gen")

    def test_at_most_max_workers_run_at_once(self):
        release = threading.Event()
        started: list[int] = []
        lock = threading.Lock()

        def _blocker(i):
            with lock:
                started.append(i)
            release.wait(timeout=10)
            return i

        futures = [jobs._submit(_blocker, i) for i in range(MAX_WORKERS + 1)]
        try:
            deadline = time.monotonic() + 10
            while len(started) < MAX_WORKERS and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(0.2)  # give an over-sized pool the chance to start one more
            assert len(started) == MAX_WORKERS
        finally:
            release.set()
        assert sorted(f.result(timeout=10) for f in futures) == list(range(MAX_WORKERS + 1))


# ---------------------------------------------------------------------------
# Whole-branch review fixes (controller, 2026-11-08)
# ---------------------------------------------------------------------------


def _racing_session_factory(factory, job_id: str, **concurrent: Any):
    """A ``get_db_session``-shaped factory whose session, right after its first SELECT,
    lets ANOTHER session commit ``concurrent`` onto the job row: a worker finishing the job
    between the poll's read and its write."""
    from sqlalchemy import event

    fired = {"done": False}

    @contextlib.contextmanager
    def _session():
        db = factory()

        def _after_first_select(state):
            if fired["done"] or not state.is_select:
                return None
            # Buffer the rows so the SELECT's cursor (and SQLite read lock) is released
            # before the "other worker" commits.
            frozen = state.invoke_statement().freeze()
            fired["done"] = True
            _set_job(factory, job_id, **concurrent)
            return frozen()

        event.listen(db, "do_orm_execute", _after_first_select)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _session, fired


class TestReviewFixes:
    def test_stale_flip_does_not_overwrite_a_job_that_completed_meanwhile(
        self, factory, session_factory
    ):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        _set_job(factory, job_id, status="running", status_message="Generating image...",
                 created_at=_stale())
        done = json.dumps({"image_token": "tok-finished"})
        racing, fired = _racing_session_factory(
            factory, job_id, status="completed", status_message="Done", output_path=done,
            completed_at=datetime.utcnow(),
        )

        info = get_job(job_id, owner=OWNER, session_factory=racing)

        assert fired["done"], "the race was not injected"
        row = _job(factory, job_id)
        assert row["status"] == "completed", "the stale flip overwrote a finished job"
        assert row["output_path"] == done
        assert info["status"] == "completed"
        assert info["image_token"] == "tok-finished"

    def test_run_job_does_not_resurrect_a_job_that_already_timed_out(
        self, factory, session_factory
    ):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        _set_job(factory, job_id, status="error", status_message="Failed",
                 error_message="Image generation timed out", completed_at=datetime.utcnow())
        fake = FakeGenerator(_generated("icon_png"))

        run_job(job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
                generator=fake, session_factory=session_factory)

        assert fake.calls == [], "a timed-out job must not be generated (paid) after all"
        row = _job(factory, job_id)
        assert row["status"] == "error"
        assert row["error_message"] == "Image generation timed out"
        assert _images(factory) == []

    def test_a_job_timed_out_while_generating_is_not_reported_completed_after_all(
        self, factory, session_factory
    ):
        """The stale check flips the job to error while the image is being generated: the
        late "Saving..." / "completed" writes do not overwrite what the user was told."""
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)

        def timed_out_meanwhile() -> None:
            _set_job(factory, job_id, status="error", status_message="Failed",
                     error_message="Image generation timed out", completed_at=datetime.utcnow())

        fake = FakeGenerator(_generated("icon_png"), during=timed_out_meanwhile)

        run_job(job_id, owner=OWNER, spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
                generator=fake, session_factory=session_factory)

        row = _job(factory, job_id)
        assert row["status"] == "error"
        assert row["error_message"] == "Image generation timed out"
        assert row["status_message"] == "Failed"
        # A job past its time limit saves nothing, like a chat straggler.
        assert _images(factory) == []

    def test_failure_log_line_is_capped(self, factory, session_factory, caplog):
        job_id = create_job(owner=OWNER, title=PROMPT, session_factory=session_factory)
        huge = "gateway said: " + "x" * 10_000

        with caplog.at_level("DEBUG", logger=jobs.__name__):
            run_job(job_id, owner=OWNER,
                    spec=GenerationSpec(prompt=PROMPT, preset_id="icon_png"),
                    generator=FakeGenerator(raises=ImageGenerationError(huge, status_code=500)),
                    session_factory=session_factory)

        messages = [r.getMessage() for r in caplog.records if r.name == jobs.__name__]
        assert messages, "the failure was not logged at all"
        assert all(len(m) <= 500 for m in messages), [len(m) for m in messages]

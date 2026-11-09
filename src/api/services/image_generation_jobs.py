"""Job store and runner for AI image generation.

Image jobs reuse ``export_jobs`` rows: ``session_id`` is
``"image-generation:" + owner`` and the result is JSON ``{"image_token": ...}``
in ``output_path``. Every status change is committed in its own short session so
other workers polling see it, and no write transaction is held across the
generator call.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Union

from src.api.services.export_job_queue import generate_job_id
from src.core.database import get_db_session
from src.database.models.session import ExportJob
from src.services.image_generation import (
    PRESETS,
    ImageGenerationError,
    ImageGenerator,
    save_generated_image,
)

logger = logging.getLogger(__name__)

JOB_SESSION_PREFIX = "image-generation:"
JOB_STALE_SECONDS = 300
MAX_WORKERS = 2
MAX_INFLIGHT = 4  # per process; running + queued

MSG_403 = (
    "The app identity cannot use the image model (403). "
    "Grant the app service principal access to the orchestrator model service."
)
MSG_429 = "The image model is rate limited (429). Try again shortly."
MSG_UNEXPECTED = "Image generation failed"
MSG_TIMED_OUT = "Image generation timed out"
MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class GenerationSpec:
    prompt: str
    preset_id: str
    model: Optional[str] = None
    quality: Optional[str] = None


@dataclass(frozen=True)
class EditSpec:
    prompt: str
    source_bytes: bytes
    source_mime: str
    source_name: str
    source_category: str
    model: Optional[str] = None
    quality: Optional[str] = None


_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def _submit(fn, /, *args, **kwargs) -> Future:
    """Run ``fn`` on the lazily created image-generation pool (test seam)."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=MAX_WORKERS, thread_name_prefix="image-gen"
            )
        executor = _executor
    return executor.submit(fn, *args, **kwargs)


def create_job(*, owner: str, title: str, session_factory=get_db_session) -> str:
    job_id = generate_job_id()
    with session_factory() as db:
        db.add(
            ExportJob(
                job_id=job_id,
                session_id=JOB_SESSION_PREFIX + owner,
                status="pending",
                status_message="Queued",
                title=(title or "")[:512],
            )
        )
    return job_id


def submit(job_id: str, *, owner: str, spec: Union[GenerationSpec, EditSpec]) -> bool:
    """Queue the job. False (and nothing queued) when the process is at capacity."""
    with _inflight_lock:
        if len(_inflight) >= MAX_INFLIGHT:
            return False
        _inflight.add(job_id)
    try:
        _submit(run_job, job_id, owner=owner, spec=spec)
    except BaseException:
        with _inflight_lock:
            _inflight.discard(job_id)
        raise
    return True


def _update_job(job_id: str, session_factory, **fields: Any) -> bool:
    """Commit ``fields`` onto the job row in its own session. False if no such row."""
    with session_factory() as db:
        row = db.query(ExportJob).filter(ExportJob.job_id == job_id).first()
        if row is None:
            return False
        for key, value in fields.items():
            setattr(row, key, value)
    return True


def _start_running(job_id: str, session_factory) -> Optional[str]:
    """Move a PENDING job to running. None when started; otherwise the row's status
    ("missing" when there is no row), so a job already timed out by ``get_job`` is never
    generated (and paid for) after all."""
    with session_factory() as db:
        moved = (
            db.query(ExportJob)
            .filter(ExportJob.job_id == job_id, ExportJob.status == "pending")
            .update(
                {"status": "running", "status_message": "Generating image..."},
                synchronize_session=False,
            )
        )
        if moved:
            return None
        row = db.query(ExportJob.status).filter(ExportJob.job_id == job_id).first()
        return "missing" if row is None else row[0]


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, ImageGenerationError):
        if exc.status_code == 403:
            return MSG_403[:MAX_ERROR_CHARS]
        if exc.status_code == 429:
            return MSG_429
        return str(exc)[:MAX_ERROR_CHARS]
    if isinstance(exc, ValueError):
        return str(exc)[:MAX_ERROR_CHARS]
    return MSG_UNEXPECTED


def run_job(
    job_id: str,
    *,
    owner: str,
    spec: Union[GenerationSpec, EditSpec],
    generator: Optional[ImageGenerator] = None,
    session_factory=get_db_session,
) -> None:
    """Generate (or edit) the image and record the outcome. Never raises."""
    try:
        try:
            blocked = _start_running(job_id, session_factory)
            if blocked is not None:
                logger.warning("Image job %s not started (status=%s); skipping", job_id, blocked)
                return
            gen = generator if generator is not None else ImageGenerator()

            if isinstance(spec, EditSpec):
                img = gen.edit(
                    spec.prompt, spec.source_bytes, spec.source_mime,
                    model=spec.model, quality=spec.quality,
                )
                category = spec.source_category
                if category == "ephemeral":
                    category = "content"
                tags = ["ai_generated", "ai_edit", img.model]
                description: Optional[str] = f"Edit of {spec.source_name}: {spec.prompt}"
            else:
                img = gen.generate(
                    spec.prompt, spec.preset_id, model=spec.model, quality=spec.quality
                )
                category = PRESETS[spec.preset_id].category
                tags = ["ai_generated", img.model, spec.preset_id]
                description = None

            _update_job(job_id, session_factory, status="running", status_message="Saving...")
            with session_factory() as db:
                asset = save_generated_image(
                    db, img, owner=owner, prompt=spec.prompt, category=category,
                    tags=tags, description=description,
                )
                token = asset.token
            _update_job(
                job_id, session_factory,
                status="completed", status_message="Done",
                output_path=json.dumps({"image_token": token}),
                completed_at=datetime.utcnow(),
            )
        except Exception as exc:
            if isinstance(exc, (ImageGenerationError, ValueError)):
                # Capped like the stored message: Gateway errors embed whole response bodies.
                logger.warning("Image job %s failed: %s", job_id, str(exc)[:MAX_ERROR_CHARS])
            else:
                logger.error("Image job %s failed", job_id, exc_info=True)
            try:
                _update_job(
                    job_id, session_factory,
                    status="error", status_message="Failed",
                    error_message=_error_message(exc), completed_at=datetime.utcnow(),
                )
            except Exception:
                logger.error("Could not record failure of image job %s", job_id, exc_info=True)
    finally:
        with _inflight_lock:
            _inflight.discard(job_id)


def get_job(job_id: str, *, owner: str, session_factory=get_db_session) -> Optional[dict]:
    """The owner's image job as a dict, or None (unknown, someone else's, or not an image job)."""
    with session_factory() as db:
        row = db.query(ExportJob).filter(ExportJob.job_id == job_id).first()
        if row is None or row.session_id != JOB_SESSION_PREFIX + owner:
            return None
        if row.status in ("pending", "running") and row.created_at is not None and (
            datetime.utcnow() - row.created_at > timedelta(seconds=JOB_STALE_SECONDS)
        ):
            # Conditional: a worker may have finished the job since the read above, and a
            # plain write would overwrite "completed" with a timeout.
            (
                db.query(ExportJob)
                .filter(
                    ExportJob.job_id == job_id,
                    ExportJob.status.in_(("pending", "running")),
                )
                .update(
                    {
                        "status": "error",
                        "status_message": "Failed",
                        "error_message": MSG_TIMED_OUT,
                        "completed_at": datetime.utcnow(),
                    },
                    synchronize_session=False,
                )
            )
            db.refresh(row)
        token = None
        if row.status == "completed" and row.output_path:
            try:
                token = json.loads(row.output_path).get("image_token")
            except (ValueError, AttributeError):
                token = None
        return {
            "job_id": row.job_id,
            "status": row.status,
            "status_message": row.status_message or "",
            "error": row.error_message,
            "image_token": token,
        }

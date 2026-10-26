"""DB-backed, deduplicated background generation of slide-style previews.

Mirrors the ``export_job_queue`` pattern: a process-local ``asyncio.Queue``
dispatches to a background worker that runs the blocking LLM generation in a
thread. Unlike exports there is no separate job table — the ``slide_style_library``
row IS the job record (``preview_status`` + fingerprint + timestamps), which makes
dedup and cache reads a single row read.

Generation calls the active Graph Release's ``builder`` role through
``AgentRuntime`` — the role, prompt, model and Unity AI Gateway transport that
build every slide of a real graph deck — once per canonical slide spec.

Correctness properties:
- Dedup: enqueue performs a CONDITIONAL status transition
  (missing/failed/ready-but-stale -> queued) and only dispatches if it won the
  transition, so N concurrent readers produce exactly one generation.
- Abandoned jobs are reclaimed: the dispatch queue is process-local, so a job
  whose worker restarted mid-flight would sit in 'queued'/'generating' forever.
  An in-flight row older than ``PREVIEW_STALE_AFTER`` is claimable again.
- Revision guard: the worker snapshots ``style_revision`` before generating and
  only writes the result back IF the revision is unchanged, so a slow generation
  cannot clobber a style the admin edited meanwhile.
- Last-known-good: a validation/provider failure sets ``failed`` but never clears
  the previously-ready ``preview_payload_id``.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, or_

from src.core.database import get_db_session
from src.database.models.slide_style_library import SlideStyleLibrary
from src.domain.deck_spec import SlideSpec
from src.services import slide_style_preview_fixture as fixture
from src.services import slide_style_preview_storage as storage
from src.services.agent import UnsafeContentError
from src.services.agent_runtime import (
    AgentAssemblyContext,
    get_agent_runtime,
    is_transient_model_failure,
)
from src.utils.graph_safety import gate_emitted_html
from src.utils.html_utils import strip_inter_tag_escapes

logger = logging.getLogger(__name__)

# Process-local dispatch queue (cross-worker state lives in the DB row).
preview_queue: "asyncio.Queue[int]" = asyncio.Queue()

# The loop the worker drains ``preview_queue`` on, set by ``start_preview_worker``.
# ``try_enqueue`` runs on threadpool threads (sync routes, the startup warm), and
# an ``asyncio.Queue`` may only be touched from its own loop.
_worker_loop: Optional[asyncio.AbstractEventLoop] = None

# Validation / safety caps.
PREVIEW_MAX_BYTES = 3_000_000      # reject runaway payloads
PREVIEW_MAX_ASSETS = 24            # referenced-asset ceiling
PREVIEW_MAX_RETRIES = 2            # transient provider errors

# An in-flight row whose last transition is older than this is presumed
# abandoned (its worker restarted or crashed) and may be claimed again. Generous
# against a live job: one generation is three parallel builder calls, retried at
# most PREVIEW_MAX_RETRIES times.
PREVIEW_STALE_AFTER = timedelta(minutes=30)

# Statuses a preview can be re-queued from.
_REQUEUEABLE = ("missing", "failed", "ready", "stale", None)
_IN_FLIGHT = ("queued", "generating")


class PreviewRejected(ValueError):
    """Generated output failed preview validation; ``str()`` is the error code.

    Its own type so a pydantic ``ValidationError`` (also a ``ValueError``) raised
    inside generation is never mistaken for a rejection and stored as a code.
    """

_IMAGE_TOKEN_RE = re.compile(r"\{\{image:([A-Za-z0-9_\-]+)\}\}")
_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_EXTERNAL_URL_RE = re.compile(r"""(?:src|href)\s*=\s*['"]https?://""", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Enqueue (dedup via conditional transition)
# ---------------------------------------------------------------------------
def is_abandoned(style: SlideStyleLibrary, now: Optional[datetime] = None) -> bool:
    """Whether an in-flight row has outlived ``PREVIEW_STALE_AFTER``."""
    if style.preview_status not in _IN_FLIGHT:
        return False
    attempted = style.preview_attempted_at
    cutoff = (now or datetime.utcnow()) - PREVIEW_STALE_AFTER
    return attempted is None or attempted < cutoff


def claimable_clause(now: datetime):
    """SQL condition: this row may be moved to 'queued' (requeueable or abandoned)."""
    return or_(
        SlideStyleLibrary.preview_status.is_(None),
        SlideStyleLibrary.preview_status.in_([s for s in _REQUEUEABLE if s is not None]),
        and_(
            SlideStyleLibrary.preview_status.in_(_IN_FLIGHT),
            or_(
                SlideStyleLibrary.preview_attempted_at.is_(None),
                SlideStyleLibrary.preview_attempted_at < now - PREVIEW_STALE_AFTER,
            ),
        ),
    )


def try_enqueue(style_id: int) -> bool:
    """Conditionally move a style's preview to 'queued' and dispatch it.

    Returns True if THIS caller won the transition and dispatched a job; False if
    a generation is already queued/generating (dedup) or the style is missing.
    Safe to call from any request handler.
    """
    now = datetime.utcnow()
    with get_db_session() as db:
        style = (
            db.query(SlideStyleLibrary)
            .filter(SlideStyleLibrary.id == style_id)
            .first()
        )
        if style is None:
            return False
        current_fp = fixture.compute_fingerprint(
            style.style_content,
            style.image_guidelines,
            fixture.current_builder_definition(db),
        )

        # Already in-flight? Never double-dispatch a live job.
        if style.preview_status in _IN_FLIGHT and not is_abandoned(style, now):
            logger.debug(
                "slide_style_preview.dedup_suppressed",
                extra={"style_id": style_id, "status": style.preview_status},
            )
            return False
        # Already ready AND current? Nothing to do.
        if style.preview_status == "ready" and style.preview_fingerprint == current_fp:
            return False

        if style.preview_status in _IN_FLIGHT:
            logger.warning(
                "slide_style_preview.reclaiming_abandoned_job",
                extra={
                    "style_id": style_id,
                    "status": style.preview_status,
                    "attempted_at": str(style.preview_attempted_at),
                },
            )

        # Win the transition with a guarded UPDATE (atomic across workers).
        updated = (
            db.query(SlideStyleLibrary)
            .filter(SlideStyleLibrary.id == style_id, claimable_clause(now))
            .update(
                {
                    "preview_status": "queued",
                    "preview_attempted_at": now,
                },
                synchronize_session=False,
            )
        )
        if not updated:
            return False  # lost the race

    _dispatch(style_id)
    logger.info("Enqueued slide-style preview generation", extra={"style_id": style_id})
    return True


def _dispatch(style_id: int) -> None:
    """Hand the job to this process's worker, from whichever thread we are on.

    With no worker running (e.g. a sync test context) the DB row stays 'queued'
    and is reclaimed once it is older than ``PREVIEW_STALE_AFTER``; we don't
    crash the request path.
    """
    loop = _worker_loop
    if loop is None or loop.is_closed():
        logger.debug(
            "No preview worker loop to dispatch to; left queued",
            extra={"style_id": style_id},
        )
        return
    try:
        on_worker_loop = asyncio.get_running_loop() is loop
    except RuntimeError:
        on_worker_loop = False
    if on_worker_loop:
        preview_queue.put_nowait(style_id)
    else:
        loop.call_soon_threadsafe(preview_queue.put_nowait, style_id)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _build_slide(
    style_id: int,
    style_content: str,
    builder: fixture.BuilderDefinition,
    slide_spec: SlideSpec,
) -> str:
    """Build one preview slide with the release's builder, safety-gated.

    The same call ``builder_node`` makes: ``AgentRuntime.run("builder", ...)``
    with the release pin and a design-system-inactive assembly context, then
    ``gate_emitted_html`` with one corrective regeneration, then
    ``strip_inter_tag_escapes``.
    """
    from src.services.graph.nodes import _SAFETY_CORRECTION

    payload = fixture.builder_payload(slide_spec, style_content)
    context = AgentAssemblyContext(design_system_active=False)

    def _run(skill_payload: dict[str, Any]):
        return get_agent_runtime().run(
            fixture.PREVIEW_AGENT_KEY,
            builder.graph_release_id,
            skill_payload,
            context,
        ).output

    out = _run(payload)
    html, _retried = gate_emitted_html(
        out.html,
        lambda: _run({**payload, "corrective_instruction": _SAFETY_CORRECTION}).html,
        f"slide-style-preview:{style_id}",
    )
    return strip_inter_tag_escapes(html)


def _generate_deck(
    style_id: int, style_content: str, builder: fixture.BuilderDefinition
) -> dict[str, Any]:
    """Build every canonical preview slide for one style, in parallel.

    Raises the first slide's failure, so a generation yields the whole preview
    deck or nothing. A slide-style deck has no deck CSS on the graph path (no
    template, no tokens; builders paint inline), so neither does this.
    """
    specs = fixture.PREVIEW_SLIDE_SPECS
    with ThreadPoolExecutor(
        max_workers=len(specs), thread_name_prefix="slide-style-preview"
    ) as pool:
        # contextvars do not cross into pool threads; give each its own copy.
        futures = [
            pool.submit(
                contextvars.copy_context().run,
                _build_slide,
                style_id,
                style_content,
                builder,
                spec,
            )
            for spec in specs
        ]
        slides = [{"html": future.result()} for future in futures]
    return {"slides": slides, "css": ""}


def _sanitize_and_validate(
    deck: dict[str, Any]
) -> tuple[list[str], str, list[dict[str, Any]]]:
    """Treat model output as hostile. Returns (slides_html, css, asset_manifest).

    Slides are kept as a list (the UI pages a mini-deck; concatenating would stack
    the ``position:absolute`` slide roots). Raises PreviewRejected(code) on rejection so
    the caller can record error_code and preserve last-known-good.
    """
    raw_slides = deck.get("slides") or []
    css = _SCRIPT_TAG_RE.sub("", deck.get("css") or "")

    # Strip scripts (preview renders in a script-less sandbox, so any <script> is
    # dead weight and a risk vector). Drop empty fragments.
    slides = [
        _SCRIPT_TAG_RE.sub("", s.get("html") or "").strip()
        for s in raw_slides
    ]
    slides = [s for s in slides if s]

    if not (fixture.PREVIEW_MIN_SLIDES <= len(slides) <= fixture.PREVIEW_MAX_SLIDES):
        raise PreviewRejected("bad_slide_count")

    combined = "\n".join(slides)
    if not combined.strip():
        raise PreviewRejected("empty_html")

    # No external/transient asset references — the iframe CSP forbids them and a
    # third-party URL could rot. Library images use {{image:token}} placeholders.
    if _EXTERNAL_URL_RE.search(combined) or _EXTERNAL_URL_RE.search(css):
        raise PreviewRejected("external_asset")

    total_bytes = len(combined.encode("utf-8")) + len(css.encode("utf-8"))
    if total_bytes > PREVIEW_MAX_BYTES:
        raise PreviewRejected("too_large")

    tokens = set(_IMAGE_TOKEN_RE.findall(combined)) | set(_IMAGE_TOKEN_RE.findall(css))
    if len(tokens) > PREVIEW_MAX_ASSETS:
        raise PreviewRejected("too_many_assets")
    manifest = [{"type": "image", "token": t} for t in sorted(tokens)]

    return slides, css, manifest


def process_preview_job(style_id: int) -> None:
    """Generate, validate, and cache a preview for one style (blocking).

    Idempotent and revision-guarded; safe to run from a worker thread.
    """
    # Snapshot the style + revision + builder definition we are generating
    # against, so the stored fingerprint names exactly what produced the preview.
    with get_db_session() as db:
        style = db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).first()
        if style is None:
            return
        snap_revision = style.style_revision or 0
        style_content = style.style_content
        image_guidelines = style.image_guidelines
        builder = fixture.current_builder_definition(db)
        fingerprint = fixture.compute_fingerprint(style_content, image_guidelines, builder)
        content_hash = fixture.compute_content_hash(style_content, image_guidelines)
        # queued -> generating (guarded; bail if someone superseded us). Only from
        # 'queued': a row already 'generating' belongs to a live job, or to an
        # abandoned one that try_enqueue must re-queue first. The timestamp
        # restarts the abandonment clock now that work has actually begun.
        moved = (
            db.query(SlideStyleLibrary)
            .filter(
                SlideStyleLibrary.id == style_id,
                SlideStyleLibrary.preview_status == "queued",
            )
            .update(
                {"preview_status": "generating", "preview_attempted_at": datetime.utcnow()},
                synchronize_session=False,
            )
        )
        if not moved:
            return

    if builder is None:
        logger.error(
            "slide_style_preview.no_active_graph_release", extra={"style_id": style_id}
        )
        _persist_failure(style_id, "no_active_release")
        return

    started = datetime.utcnow()
    last_err = "unknown"
    for attempt in range(1, PREVIEW_MAX_RETRIES + 2):  # 1 + retries
        try:
            deck = _generate_deck(style_id, style_content, builder)
            slides, css, manifest = _sanitize_and_validate(deck)
            persisted = _persist_success(
                style_id, snap_revision, fingerprint, content_hash, slides, css, manifest,
            )
            latency = (datetime.utcnow() - started).total_seconds()
            logger.info(
                "slide_style_preview.generated" if persisted
                else "slide_style_preview.generated_but_discarded",
                extra={
                    "style_id": style_id,
                    "attempt": attempt,
                    "persisted": persisted,
                    "latency_s": round(latency, 2),
                    "slides": len(slides),
                    "bytes": sum(len(s) for s in slides) + len(css),
                    "assets": len(manifest),
                    "graph_release_id": builder.graph_release_id,
                },
            )
            return
        except PreviewRejected as rejected:  # validation rejection — not retryable
            last_err = str(rejected)
            logger.warning(
                "slide_style_preview.rejected",
                extra={"style_id": style_id, "error_code": last_err, "attempt": attempt},
            )
            break
        except UnsafeContentError:  # still unsafe after the corrective retry
            last_err = "unsafe_output"
            logger.warning(
                "slide_style_preview.rejected",
                extra={"style_id": style_id, "error_code": last_err, "attempt": attempt},
            )
            break
        except Exception as e:  # noqa: BLE001 — provider/runtime error
            last_err = "generation_error"
            transient = is_transient_model_failure(e)
            logger.warning(
                "slide_style_preview.attempt_failed",
                extra={
                    "style_id": style_id,
                    "attempt": attempt,
                    "transient": transient,
                    "error": str(e)[:200],
                },
            )
            # A removed or forbidden endpoint, an invalid release, a schema
            # failure: retrying would only repeat it.
            if not transient:
                break

    _persist_failure(style_id, last_err)


def _persist_success(
    style_id: int,
    snap_revision: int,
    fingerprint: str,
    content_hash: str,
    slides: list[str],
    css: str,
    manifest: list[dict[str, Any]],
) -> bool:
    """Store payload + write pointer back, guarded on style_revision.

    Returns True if the pointer was written (preview promoted to ready), False if
    the write was discarded because the style was edited mid-generation.
    """
    with get_db_session() as db:
        payload_id, total_bytes = storage.store_payload(
            db, style_id, fingerprint, slides, css, manifest
        )
        # Conditional write-back: only if the style wasn't edited mid-generation.
        # NULL-safe: rows inherited via a Lakebase branch have style_revision=NULL
        # (the migration adds the column without a backfill on already-populated
        # forks), and `NULL == 0` is never true in SQL — so a plain equality check
        # would discard EVERY generation on a fork. When we snapshotted revision 0,
        # treat NULL as 0 so those inherited rows can be promoted to ready.
        revision_guard = SlideStyleLibrary.style_revision == snap_revision
        if snap_revision == 0:
            revision_guard = or_(revision_guard, SlideStyleLibrary.style_revision.is_(None))
        updated = (
            db.query(SlideStyleLibrary)
            .filter(
                SlideStyleLibrary.id == style_id,
                revision_guard,
            )
            .update(
                {
                    "preview_status": "ready",
                    "preview_fingerprint": fingerprint,
                    "preview_content_hash": content_hash,
                    "preview_payload_id": payload_id,
                    "preview_asset_manifest": manifest,
                    "preview_total_bytes": total_bytes,
                    "preview_error_code": None,
                    "preview_error_message": None,
                    "preview_generated_at": datetime.utcnow(),
                },
                synchronize_session=False,
            )
        )
        if not updated:
            # Style changed under us: discard. Leave status as-is (a fresh enqueue
            # for the new revision will supersede). Prune the orphaned payload.
            logger.info(
                "slide_style_preview.discarded_stale_generation",
                extra={"style_id": style_id, "snap_revision": snap_revision},
            )
            style = db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).first()
            keep = {style.preview_payload_id} if style and style.preview_payload_id else set()
            storage.prune_payloads(db, style_id, keep_ids=keep)
            return False
        # Success: prune stale payloads, keeping the one we just wrote.
        storage.prune_payloads(db, style_id, keep_ids={payload_id})
        return True


def _persist_failure(style_id: int, error_code: str) -> None:
    """Record failure WITHOUT clearing last-known-good payload."""
    with get_db_session() as db:
        db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).update(
            {
                "preview_status": "failed",
                "preview_error_code": error_code,
                "preview_error_message": f"Preview generation failed ({error_code}).",
                "preview_failed_at": datetime.utcnow(),
            },
            synchronize_session=False,
        )


# ---------------------------------------------------------------------------
# Worker lifecycle (mirrors export_job_queue)
# ---------------------------------------------------------------------------
def _run_preview_job_sync(style_id: int) -> None:
    """Thread entrypoint: run the blocking generation on its own loop."""
    try:
        process_preview_job(style_id)
    except Exception:  # noqa: BLE001 — never let a job kill the worker
        logger.error("slide_style_preview.job_crashed", extra={"style_id": style_id}, exc_info=True)
        try:
            _persist_failure(style_id, "worker_crash")
        except Exception:
            logger.error("slide_style_preview.failure_record_failed", exc_info=True)


async def preview_worker() -> None:
    """Background worker: drain the queue, running each job off the event loop."""
    logger.info("Slide-style preview worker started")
    while True:
        try:
            style_id = await preview_queue.get()
            try:
                await asyncio.to_thread(_run_preview_job_sync, style_id)
            finally:
                preview_queue.task_done()
        except asyncio.CancelledError:
            logger.info("Slide-style preview worker shutting down")
            break
        except Exception as e:  # noqa: BLE001
            logger.error(f"Preview worker loop error: {e}")


async def start_preview_worker() -> "asyncio.Task[None]":
    """Start the background preview worker task on the running loop."""
    global _worker_loop
    _worker_loop = asyncio.get_running_loop()
    return asyncio.create_task(preview_worker())


# ---------------------------------------------------------------------------
# Startup warming (backfill)
# ---------------------------------------------------------------------------
# Cap how many styles we proactively warm per boot so a fresh fork (where every
# style is 'missing') doesn't fan out an unbounded burst of builder generations.
# try_enqueue dedups + skips already-ready styles, so subsequent boots only warm
# the stale/missing ones. Defaults ordered so the default + active styles warm first.
PREVIEW_WARM_LIMIT = 25


def warm_missing_previews(limit: int = PREVIEW_WARM_LIMIT) -> int:
    """Proactively enqueue previews for active styles that aren't ready+current.

    Runs at startup so viewers hit a warm cache instead of a cold generation.
    Best-effort and deduplicated (``try_enqueue`` no-ops ready/in-flight styles).
    Returns the number of styles enqueued.
    """
    enqueued = 0
    try:
        with get_db_session() as db:
            styles = (
                db.query(SlideStyleLibrary)
                .filter(SlideStyleLibrary.is_active.is_(True))
                .order_by(
                    SlideStyleLibrary.is_default.desc(),
                    SlideStyleLibrary.id.asc(),
                )
                .limit(limit)
                .all()
            )
            style_ids = [s.id for s in styles]
    except Exception:  # noqa: BLE001 — warming must never break startup
        logger.warning("slide_style_preview.warm_query_failed", exc_info=True)
        return 0

    for style_id in style_ids:
        try:
            if try_enqueue(style_id):
                enqueued += 1
        except Exception:  # noqa: BLE001
            logger.warning(
                "slide_style_preview.warm_enqueue_failed",
                extra={"style_id": style_id},
                exc_info=True,
            )
    logger.info(
        "slide_style_preview.warm_backfill",
        extra={"candidates": len(style_ids), "enqueued": enqueued},
    )
    return enqueued

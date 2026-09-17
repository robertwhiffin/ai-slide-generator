"""DB-backed, deduplicated background generation of slide-style previews.

Mirrors the ``export_job_queue`` pattern: a process-local ``asyncio.Queue``
dispatches to a background worker that runs the blocking LLM generation in a
thread. Unlike exports there is no separate job table — the ``slide_style_library``
row IS the job record (``preview_status`` + fingerprint + timestamps), which makes
dedup and cache reads a single row read.

Correctness properties:
- Dedup: enqueue performs a CONDITIONAL status transition
  (missing/failed/ready-but-stale -> queued) and only dispatches if it won the
  transition, so N concurrent readers produce exactly one generation.
- Revision guard: the worker snapshots ``style_revision`` before generating and
  only writes the result back IF the revision is unchanged, so a slow generation
  cannot clobber a style the admin edited meanwhile.
- Last-known-good: a validation/provider failure sets ``failed`` but never clears
  the previously-ready ``preview_payload_id``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Optional

from src.core.database import get_db_session
from src.database.models.slide_style_library import SlideStyleLibrary
from src.services import slide_style_preview_fixture as fixture
from src.services import slide_style_preview_storage as storage

logger = logging.getLogger(__name__)

# Process-local dispatch queue (cross-worker state lives in the DB row).
preview_queue: "asyncio.Queue[int]" = asyncio.Queue()

# Validation / safety caps.
PREVIEW_MAX_BYTES = 3_000_000      # reject runaway payloads
PREVIEW_MAX_ASSETS = 24            # referenced-asset ceiling
PREVIEW_MAX_RETRIES = 2            # transient provider errors

# Statuses a preview can be re-queued from.
_REQUEUEABLE = ("missing", "failed", "ready", "stale", None)

_IMAGE_TOKEN_RE = re.compile(r"\{\{image:([A-Za-z0-9_\-]+)\}\}")
_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_EXTERNAL_URL_RE = re.compile(r"""(?:src|href)\s*=\s*['"]https?://""", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Enqueue (dedup via conditional transition)
# ---------------------------------------------------------------------------
def try_enqueue(style_id: int) -> bool:
    """Conditionally move a style's preview to 'queued' and dispatch it.

    Returns True if THIS caller won the transition and dispatched a job; False if
    a generation is already queued/generating (dedup) or the style is missing.
    Safe to call from any request handler.
    """
    with get_db_session() as db:
        style = (
            db.query(SlideStyleLibrary)
            .filter(SlideStyleLibrary.id == style_id)
            .first()
        )
        if style is None:
            return False
        current_fp = fixture.compute_fingerprint(style.style_content, style.image_guidelines)

        # Already in-flight? Never double-dispatch.
        if style.preview_status in ("queued", "generating"):
            logger.debug(
                "slide_style_preview.dedup_suppressed",
                extra={"style_id": style_id, "status": style.preview_status},
            )
            return False
        # Already ready AND current? Nothing to do.
        if style.preview_status == "ready" and style.preview_fingerprint == current_fp:
            return False

        # Win the transition with a guarded UPDATE (atomic across workers).
        updated = (
            db.query(SlideStyleLibrary)
            .filter(
                SlideStyleLibrary.id == style_id,
                SlideStyleLibrary.preview_status.in_(
                    [s for s in _REQUEUEABLE if s is not None]
                )
                | SlideStyleLibrary.preview_status.is_(None),
            )
            .update(
                {
                    "preview_status": "queued",
                    "preview_attempted_at": datetime.utcnow(),
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
    """Put the job on the process-local queue if a loop/worker is available.

    If no running loop (e.g. sync test context), the DB row stays 'queued' and a
    later worker/cron can pick it up; we don't crash the request path.
    """
    try:
        preview_queue.put_nowait(style_id)
    except RuntimeError:
        logger.debug("No running loop to dispatch preview job; left queued", extra={"style_id": style_id})


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _generate_deck(style_id: int) -> dict[str, Any]:
    """Run the real generation pipeline against a fixed brief for one style.

    Creates an ephemeral, non-user-visible session whose agent_config selects the
    target slide style (design system explicitly off), generates the canonical
    preview brief through the same ``send_message`` path real decks use, then
    deletes the session. Returns the parsed slide_deck dict.
    """
    from src.api.services.chat_service import get_chat_service
    from src.api.services.session_manager import get_session_manager

    session_id = f"__preview__{style_id}__{datetime.utcnow().timestamp()}"
    session_manager = get_session_manager()
    session_manager.create_session(
        session_id=session_id,
        created_by="__preview__",
        title="(slide-style preview)",
        agent_config={"slide_style_id": style_id, "design_system_id": None, "tools": []},
    )
    # Cap max_tokens for this generation only (same model, smaller thinking
    # budget). The agent's model factory reads this context-var at creation time;
    # reset in finally so nothing else inherits the cap.
    token = fixture.preview_max_tokens_override.set(fixture.PREVIEW_MAX_TOKENS)
    try:
        chat_service = get_chat_service()
        result = chat_service.send_message(session_id, fixture.PREVIEW_BRIEF)
        deck = result.get("slide_deck") or {}
        deck["_metadata"] = result.get("metadata") or {}
        return deck
    finally:
        fixture.preview_max_tokens_override.reset(token)
        try:
            session_manager.delete_session(session_id)
        except Exception:  # noqa: BLE001 — cleanup best-effort
            logger.warning("Failed to delete ephemeral preview session %s", session_id, exc_info=True)


def _sanitize_and_validate(
    deck: dict[str, Any]
) -> tuple[list[str], str, list[dict[str, Any]]]:
    """Treat model output as hostile. Returns (slides_html, css, asset_manifest).

    Slides are kept as a list (the UI pages a mini-deck; concatenating would stack
    the ``position:absolute`` slide roots). Raises ValueError(code) on rejection so
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
        raise ValueError("bad_slide_count")

    combined = "\n".join(slides)
    if not combined.strip():
        raise ValueError("empty_html")

    # No external/transient asset references — the iframe CSP forbids them and a
    # third-party URL could rot. Library images use {{image:token}} placeholders.
    if _EXTERNAL_URL_RE.search(combined) or _EXTERNAL_URL_RE.search(css):
        raise ValueError("external_asset")

    total_bytes = len(combined.encode("utf-8")) + len(css.encode("utf-8"))
    if total_bytes > PREVIEW_MAX_BYTES:
        raise ValueError("too_large")

    tokens = set(_IMAGE_TOKEN_RE.findall(combined)) | set(_IMAGE_TOKEN_RE.findall(css))
    if len(tokens) > PREVIEW_MAX_ASSETS:
        raise ValueError("too_many_assets")
    manifest = [{"type": "image", "token": t} for t in sorted(tokens)]

    return slides, css, manifest


def process_preview_job(style_id: int) -> None:
    """Generate, validate, and cache a preview for one style (blocking).

    Idempotent and revision-guarded; safe to run from a worker thread.
    """
    # Snapshot the style + revision we are generating against.
    with get_db_session() as db:
        style = db.query(SlideStyleLibrary).filter(SlideStyleLibrary.id == style_id).first()
        if style is None:
            return
        snap_revision = style.style_revision or 0
        style_content = style.style_content
        image_guidelines = style.image_guidelines
        fingerprint = fixture.compute_fingerprint(style_content, image_guidelines)
        content_hash = fixture.compute_content_hash(style_content, image_guidelines)
        # queued -> generating (guarded; bail if someone superseded us).
        moved = (
            db.query(SlideStyleLibrary)
            .filter(
                SlideStyleLibrary.id == style_id,
                SlideStyleLibrary.preview_status.in_(["queued", "generating"]),
            )
            .update({"preview_status": "generating"}, synchronize_session=False)
        )
        if not moved:
            return

    started = datetime.utcnow()
    last_err = "unknown"
    for attempt in range(1, PREVIEW_MAX_RETRIES + 2):  # 1 + retries
        try:
            deck = _generate_deck(style_id)
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
                    "tokens": (deck.get("_metadata") or {}).get("total_tokens"),
                },
            )
            return
        except ValueError as ve:  # validation rejection — not retryable
            last_err = str(ve)
            logger.warning(
                "slide_style_preview.rejected",
                extra={"style_id": style_id, "error_code": last_err, "attempt": attempt},
            )
            break
        except Exception as e:  # noqa: BLE001 — transient provider/runtime error
            last_err = "generation_error"
            logger.warning(
                "slide_style_preview.attempt_failed",
                extra={"style_id": style_id, "attempt": attempt, "error": str(e)[:200]},
            )
            continue

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
    from sqlalchemy import or_

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
    """Start the background preview worker task."""
    return asyncio.create_task(preview_worker())


# ---------------------------------------------------------------------------
# Startup warming (backfill)
# ---------------------------------------------------------------------------
# Cap how many styles we proactively warm per boot so a fresh fork (where every
# style is 'missing') doesn't fan out an unbounded burst of Opus generations.
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

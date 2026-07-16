#!/usr/bin/env python3
"""HTML to Google Slides converter using LLM code-gen approach."""

import ast
import asyncio
import base64
import logging
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from databricks.sdk import WorkspaceClient

from src.services.converter_jail.codeprep import _fix_apostrophe_strings
from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError
from src.services.google_slides_prompts_defaults import (
    DEFAULT_GSLIDES_SYSTEM_PROMPT,
    DEFAULT_GSLIDES_USER_PROMPT,
)

logger = logging.getLogger(__name__)

# Max HTML length passed to the LLM on first generation and on retry (must match).
GSLIDES_HTML_PROMPT_MAX = 25000

# Cap on concurrent LLM code-generation calls during parallel phase.
MAX_CONCURRENT_LLM = 5

# Retry settings for Google Slides API 429 (rate limit) errors.
_RETRY_MAX_ATTEMPTS = 5
_RETRY_BASE_DELAY = 5  # seconds

# SDR-4437 PR-5: safe basename for a tellr-asset:// filename. No path
# separators, no leading dot-dot — a plain asset filename only. Both the
# schema gate (_validate_requests) and the uploader (_upload_and_substitute_assets)
# enforce this before the untrusted filename ever reaches the filesystem.
_SAFE_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _is_rate_limit_error(exc: Exception) -> bool:
    """True if the exception is a 429 rate-limit error from the Google API."""
    msg = str(exc)
    return "429" in msg and ("quota" in msg.lower() or "rate" in msg.lower())


def _retry_api_call(fn, *, label: str = "API call"):
    """Execute *fn()* with exponential backoff on 429 rate-limit errors.

    Non-429 errors are raised immediately.  After ``_RETRY_MAX_ATTEMPTS``
    consecutive 429 failures the last exception is re-raised.
    """
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "%s hit rate limit (attempt %d/%d) — retrying in %ds: %s",
                label, attempt + 1, _RETRY_MAX_ATTEMPTS, delay, exc,
            )
            time.sleep(delay)
    # Final attempt — let any exception propagate.
    return fn()


def _truncate_html_for_prompt(html_str: str) -> str:
    """Truncate slide HTML for LLM prompts with a consistent marker."""
    if len(html_str) <= GSLIDES_HTML_PROMPT_MAX:
        return html_str
    return html_str[:GSLIDES_HTML_PROMPT_MAX] + "\n<!-- truncated -->"


def _looks_like_slides_api_error(error_msg: str) -> bool:
    """True if *error_msg* is from googleapiclient HttpError / Slides API."""
    msg = error_msg.lower()
    if "httperror" in msg or "httpexception" in msg:
        return True
    # e.g. <HttpError 400 when requesting https://slides.googleapis.com/...
    return bool(re.search(r"http(s)?error\s+\d{3}\s+when\s+requesting", msg))


# ---------------------------------------------------------------------------
# Request pre-sanitization helpers
# ---------------------------------------------------------------------------

def _req_cell_key(inner: dict) -> tuple:
    """Return a hashable key for (objectId, [rowIndex, columnIndex])."""
    obj_id = inner.get("objectId", "")
    cell = inner.get("cellLocation")
    if cell:
        return (obj_id, cell.get("rowIndex", 0), cell.get("columnIndex", 0))
    return (obj_id,)


_STYLE_KEYS = {"updateTextStyle", "updateTableCellProperties", "updateParagraphStyle"}


def _filter_requests(requests: list) -> list:
    """Remove empty insertText and any style update for the same (objectId, cell).

    Order-independent: style requests before or after the empty insertText are
    dropped.  Prevents API errors like "The object has no text" on
    ``updateTextStyle`` for empty table cells.
    """
    empty_cells: set = set()
    for req in requests:
        if "insertText" in req and req["insertText"].get("text", "") == "":
            empty_cells.add(_req_cell_key(req["insertText"]))

    filtered: list = []
    for req in requests:
        if "insertText" in req and req["insertText"].get("text", "") == "":
            continue
        if any(k in req for k in _STYLE_KEYS):
            key = next(k for k in req if k in _STYLE_KEYS)
            if _req_cell_key(req[key]) in empty_cells:
                continue

        # Strip bulletPreset from updateParagraphStyle — it only belongs
        # in createParagraphBullets and will cause a 400 error here.
        if "updateParagraphStyle" in req:
            ups = req["updateParagraphStyle"]
            style = ups.get("style", {})
            if "bulletPreset" in style:
                logger.info("Filter: removing bulletPreset from updateParagraphStyle request")
                style.pop("bulletPreset")
                # Also clean the fields mask
                fields = ups.get("fields", "")
                fields = ",".join(
                    f.strip() for f in fields.split(",")
                    if f.strip() != "bulletPreset"
                )
                if fields:
                    ups["fields"] = fields
                else:
                    ups.pop("fields", None)
                # If style is now empty, drop the request entirely
                if not style:
                    continue

        filtered.append(req)

    return filtered


# ---------------------------------------------------------------------------
# Cascading-failure tracker
# ---------------------------------------------------------------------------

class _SkipTracker:
    """Track objectIds whose creation failed so downstream ops can be skipped.

    When a ``createShape`` / ``createTable`` / ``createImage`` request fails,
    all subsequent requests that reference the same ``objectId`` would produce
    noisy "object not found" errors.  This tracker records the failed IDs and
    allows callers to skip those dependent requests silently.
    """

    _CREATE_KEYS = {
        "createShape", "createTable", "createImage",
        "createLine", "createSheetsChart",
    }

    def __init__(self) -> None:
        self._failed_ids: set = set()

    def mark_failed(self, requests: list) -> None:
        """Record objectIds of any create-* requests in *requests* as failed."""
        for req in requests:
            for key in self._CREATE_KEYS:
                if key in req:
                    obj_id = req[key].get("objectId")
                    if obj_id:
                        self._failed_ids.add(obj_id)

    def should_skip(self, req: dict) -> bool:
        """Return True if *req* targets an objectId whose creation failed."""
        for inner in req.values():
            if isinstance(inner, dict):
                if inner.get("objectId") in self._failed_ids:
                    return True
        return False


# ---------------------------------------------------------------------------
# Chunked batchUpdate proxy
# ---------------------------------------------------------------------------

class _ChunkedBatchUpdateRequest:
    """Deferred batchUpdate call that executes in chunks with per-request retry.

    On a chunk failure the wrapper:
    1. Logs the chunk index and error for easy debugging.
    2. Marks any ``create*`` requests in the failed chunk via ``_SkipTracker``.
    3. Retries each request in the chunk individually.
    4. On individual failure → logs + skips; continues to the next request.

    This ensures a single bad request drops only itself, not everything that
    follows in the same batchUpdate call or subsequent calls.
    """

    def __init__(
        self,
        resource,
        presentation_id: str,
        requests: list,
        chunk_size: int,
        slide_num,
        tracker: _SkipTracker,
    ) -> None:
        self._resource = resource
        self._presentation_id = presentation_id
        self._requests = _filter_requests(requests)
        self._chunk_size = chunk_size
        self._slide_num = slide_num
        self._tracker = tracker

    def _do_batch(self, reqs: list):
        label = f"Slide {self._slide_num} batchUpdate ({len(reqs)} reqs)"
        return _retry_api_call(
            lambda: self._resource.batchUpdate(
                presentationId=self._presentation_id,
                body={"requests": reqs},
            ).execute(),
            label=label,
        )

    def execute(self):
        requests = [r for r in self._requests if not self._tracker.should_skip(r)]
        if not requests:
            return None

        total_chunks = max(1, (len(requests) + self._chunk_size - 1) // self._chunk_size)
        last_result = None

        for chunk_idx, i in enumerate(range(0, len(requests), self._chunk_size)):
            chunk = [r for r in requests[i:i + self._chunk_size]
                     if not self._tracker.should_skip(r)]
            if not chunk:
                continue

            chunk_num = chunk_idx + 1
            req_range = f"{i + 1}–{i + len(chunk)}"
            logger.info(
                "Slide %s batchUpdate: chunk %d/%d (requests %s)",
                self._slide_num, chunk_num, total_chunks, req_range,
            )

            try:
                last_result = self._do_batch(chunk)
            except Exception as exc:
                logger.warning(
                    "Slide %s chunk %d/%d failed — retrying individually. Error: %s",
                    self._slide_num, chunk_num, total_chunks, exc,
                )
                self._tracker.mark_failed(chunk)

                for req_idx, req in enumerate(chunk):
                    if self._tracker.should_skip(req):
                        continue
                    req_type = next(iter(req.keys()), "unknown")
                    try:
                        last_result = self._do_batch([req])
                        logger.debug(
                            "Slide %s chunk %d req %d (%s) succeeded individually",
                            self._slide_num, chunk_num, req_idx + 1, req_type,
                        )
                    except Exception as req_exc:
                        logger.warning(
                            "Slide %s chunk %d req %d (%s) failed — skipping: %s",
                            self._slide_num, chunk_num, req_idx + 1, req_type, req_exc,
                        )
                        self._tracker.mark_failed([req])

        return last_result


class _ChunkedPresentations:
    """Proxy for the presentations resource that returns chunked batchUpdate objects."""

    def __init__(self, resource, chunk_size: int, slide_num, tracker: _SkipTracker) -> None:
        self._resource = resource
        self._chunk_size = chunk_size
        self._slide_num = slide_num
        self._tracker = tracker

    def batchUpdate(self, presentationId: str, body: dict):  # noqa: N802
        return _ChunkedBatchUpdateRequest(
            self._resource,
            presentationId,
            body.get("requests", []),
            self._chunk_size,
            self._slide_num,
            self._tracker,
        )

    def __getattr__(self, name):
        return getattr(self._resource, name)


class _ChunkedSlidesService:
    """Transparent proxy over a Google Slides service object.

    Intercepts ``presentations().batchUpdate(...)`` calls and routes them
    through ``_ChunkedBatchUpdateRequest`` so that large request lists are
    executed in small, fault-isolated chunks.
    """

    def __init__(self, service, chunk_size: int = 4, slide_num=None) -> None:
        self._service = service
        self._chunk_size = chunk_size
        self._slide_num = slide_num
        self._tracker = _SkipTracker()

    def presentations(self):
        return _ChunkedPresentations(
            self._service.presentations(),
            self._chunk_size,
            self._slide_num,
            self._tracker,
        )

    def __getattr__(self, name):
        return getattr(self._service, name)


# ---------------------------------------------------------------------------

class GoogleSlidesConversionError(Exception):
    """Raised when Google Slides conversion fails."""


class HtmlToGoogleSlidesConverter:
    """LLM-powered converter: HTML → Google Slides API code → execution."""

    DEFAULT_MODEL = "databricks-claude-sonnet-4-5"

    def __init__(
        self,
        workspace_client: Optional[WorkspaceClient] = None,
        model_endpoint: Optional[str] = None,
        google_auth: Optional[GoogleSlidesAuth] = None,
    ):
        self.model_endpoint = model_endpoint or self.DEFAULT_MODEL

        if workspace_client:
            self.ws_client = workspace_client
        else:
            from src.core.databricks_client import get_databricks_client
            self.ws_client = get_databricks_client()

        self.llm_client = self.ws_client.serving_endpoints.get_open_ai_client()
        self.auth = google_auth or GoogleSlidesAuth()
        self.SYSTEM_PROMPT = DEFAULT_GSLIDES_SYSTEM_PROMPT
        self.USER_PROMPT = DEFAULT_GSLIDES_USER_PROMPT
        logger.info("Google Slides converter initialized", extra={"model": self.model_endpoint})

    # -- Public API --------------------------------------------------------

    async def convert_slide_deck(
        self,
        slides: List[str],
        title: str = "Presentation",
        chart_images_per_slide: Optional[List[Dict[str, str]]] = None,
        progress_callback: Optional[Callable] = None,
        existing_presentation_id: Optional[str] = None,
        on_presentation_created: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, str]:
        """Convert HTML slides to a Google Slides presentation.

        Uses a two-phase approach:
          Phase 1 — Prepare assets + parallel LLM code generation
          Phase 2 — Sequential Google Slides API execution

        Args:
            slides: HTML strings for each slide.
            title: Presentation title.
            chart_images_per_slide: Chart images keyed by canvas ID, per slide.
            progress_callback: Optional ``(current, total, status)`` callback.
            existing_presentation_id: Optional ID of an existing presentation
                to overwrite instead of creating a new one.
            on_presentation_created: Optional callback ``(pres_id, url)``
                fired as soon as the presentation exists in Drive, before
                any slides are processed.
        """
        total = len(slides)
        print(f"[GSLIDES_CONVERTER] Converting {total} slides to Google Slides "
              f"– total HTML size: {sum(len(h) for h in slides)}")

        try:
            slides_service = self.auth.build_slides_service()
            drive_service = self.auth.build_drive_service()
        except GoogleSlidesAuthError as exc:
            raise GoogleSlidesConversionError(f"Auth failed: {exc}") from exc

        if existing_presentation_id:
            logger.info(
                "Ignoring existing presentation %s — creating fresh",
                existing_presentation_id,
            )

        try:
            pres_id = self._create_presentation(slides_service, title)
        except Exception as exc:
            raise GoogleSlidesConversionError(
                f"Failed to create presentation: {exc}"
            ) from exc

        # Fire early URL callback so the user can open the deck immediately
        url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
        if on_presentation_created:
            try:
                on_presentation_created(pres_id, url)
            except Exception:
                logger.warning("on_presentation_created callback failed", exc_info=True)

        # ── Phase 1: Prepare assets + parallel LLM code generation ────────
        if progress_callback:
            try:
                progress_callback(0, total, f"Generating code for {total} slides...")
            except Exception:
                pass

        slide_inputs: List[Tuple[str, List[str], List[str], str]] = []
        for i, html_str in enumerate(slides, 1):
            chart_imgs = None
            if chart_images_per_slide and i - 1 < len(chart_images_per_slide):
                chart_imgs = chart_images_per_slide[i - 1]
            prepared = self._prepare_slide(html_str, chart_imgs, i)
            slide_inputs.append(prepared)

        def _on_codegen_progress(completed: int, codegen_total: int) -> None:
            if progress_callback:
                try:
                    progress_callback(
                        completed, codegen_total,
                        f"Generating code: {completed}/{codegen_total} slides ready…",
                    )
                except Exception:
                    pass

        t0 = time.time()
        codes = await self._generate_all_codes(slide_inputs, on_codegen_progress=_on_codegen_progress)
        logger.info(
            "Parallel codegen complete",
            extra={"total_slides": total, "duration_s": f"{time.time() - t0:.1f}"},
        )

        # ── Phase 2a: create all slide pages (host-side; page_ids known up front)
        page_ids = []
        for i in range(1, total + 1):
            page_id = f"slide_{uuid.uuid4().hex[:12]}"
            try:
                _retry_api_call(
                    lambda _pid=pres_id, _pg=page_id: slides_service.presentations().batchUpdate(
                        presentationId=_pid,
                        body={"requests": [{"createSlide": {
                            "objectId": _pg,
                            "slideLayoutReference": {"predefinedLayout": "BLANK"},
                        }}]},
                    ).execute(),
                    label=f"createSlide {i}/{total}",
                )
                page_ids.append(page_id)
            except Exception:
                logger.error("Failed to create slide %d after retries", i, exc_info=True)
                page_ids.append(None)

        # ── Phase 2b: emit all batchUpdate requests inside the jail (no network)
        import json as _json
        import shutil as _shutil
        from src.services.converter_jail import run_gslides_jail

        job_dir = self._build_gslides_job_dir(codes, slide_inputs, page_ids)
        requests_out = str(Path(job_dir) / "requests.json")
        emitted = []
        try:
            # to_thread: the jail blocks on proc.wait for the whole deck and
            # this coroutine runs on the event loop (same rationale as the
            # PPTX call sites in Task 4).
            result = await asyncio.to_thread(run_gslides_jail, job_dir, requests_out)
            if result.timed_out or result.returncode != 0:
                logger.error("GSlides jail failed rc=%s timeout=%s: %s",
                             result.returncode, result.timed_out, result.stderr_tail)
            else:
                emitted = _json.loads(Path(requests_out).read_text())
        finally:
            _shutil.rmtree(job_dir, ignore_errors=True)
        by_index = {e["index"]: e for e in emitted}

        # ── Phase 2c: execute per slide on the host (validate, upload, chunked)
        for i, (code, (html_str, chart_files, content_files, assets_dir)) in enumerate(
            zip(codes, slide_inputs), 1,
        ):
            page_id = page_ids[i - 1]
            if page_id is None:
                continue
            entry = by_index.get(i - 1)
            requests = entry.get("requests") if entry else None

            if requests is None:
                logger.warning("Slide %d: no emitted requests, adding fallback", i)
                self._add_fallback(slides_service, pres_id, page_id, i)
            else:
                err = self._execute_slide_requests(
                    requests, slides_service, drive_service, pres_id, page_id,
                    assets_dir, i,
                )
                if err is not None:
                    fixed = await self._retry_with_error(
                        code, err, html_str, chart_files, content_files,
                    )
                    retry_err = "no-retry-code"
                    if fixed:
                        retry_requests = self._emit_single_slide(fixed, html_str, assets_dir, page_id)
                        if retry_requests is not None:
                            retry_err = self._execute_slide_requests(
                                retry_requests, slides_service, drive_service,
                                pres_id, page_id, assets_dir, i,
                            )
                    if retry_err is not None:
                        logger.warning("Slide %d: all attempts failed, fallback", i)
                        self._add_fallback(slides_service, pres_id, page_id, i)

            if progress_callback:
                try:
                    progress_callback(i, total, f"Building slide {i}/{total}…")
                except Exception:
                    pass

        # Best-effort Drive cleanup of uploaded asset files (generated code never did this).
        for file_id in getattr(self, "_uploaded_file_ids", []):
            try:
                drive_service.files().delete(fileId=file_id).execute()
            except Exception:
                logger.debug("Asset cleanup failed for %s", file_id, exc_info=True)

        print(f"[GSLIDES_CONVERTER] Done: {url}")
        return {"presentation_id": pres_id, "presentation_url": url}

    # -- Presentation reuse ------------------------------------------------

    def _try_reuse_presentation(
        self, slides_service, presentation_id: str, title: str,
    ) -> Optional[str]:
        """Try to reuse an existing presentation by clearing all its slides.

        Returns the presentation_id on success, or None if the presentation
        is inaccessible (deleted, permission revoked, etc.).
        """
        try:
            pres = slides_service.presentations().get(
                presentationId=presentation_id,
            ).execute()

            existing_slides = pres.get("slides", [])
            print(
                f"[GSLIDES_CONVERTER] Reusing presentation {presentation_id} "
                f"– clearing {len(existing_slides)} existing slides"
            )

            # Delete all existing slides
            if existing_slides:
                delete_requests = [
                    {"deleteObject": {"objectId": s["objectId"]}}
                    for s in existing_slides
                ]
                slides_service.presentations().batchUpdate(
                    presentationId=presentation_id,
                    body={"requests": delete_requests},
                ).execute()

            # Update title if different
            current_title = pres.get("title", "")
            if current_title != title:
                try:
                    drive_service = self.auth.build_drive_service()
                    drive_service.files().update(
                        fileId=presentation_id,
                        body={"name": title},
                    ).execute()
                except Exception:
                    logger.debug("Could not update presentation title", exc_info=True)

            return presentation_id

        except Exception as exc:
            logger.warning(
                "Cannot reuse existing presentation %s: %s — creating new one",
                presentation_id, exc,
            )
            return None

    # -- Presentation creation via native API --------------------------------

    def _create_presentation(
        self, slides_service, title: str,
    ) -> str:
        """Create a new Google Slides presentation with a title/instructions slide.

        Uses the native Slides API (no PPTX upload), so the presentation
        always has Google's standard 10" × 5.625" dimensions — matching the
        LLM prompt exactly.
        """
        pres = _retry_api_call(
            lambda: slides_service.presentations().create(
                body={"title": title},
            ).execute(),
            label="Create presentation",
        )
        pres_id = pres["presentationId"]
        default_slide = pres["slides"][0]
        default_page_id = default_slide["objectId"]

        # Remove default "Click to add title/subtitle" placeholders.
        delete_requests = [
            {"deleteObject": {"objectId": el["objectId"]}}
            for el in default_slide.get("pageElements", [])
        ]
        if delete_requests:
            _retry_api_call(
                lambda: slides_service.presentations().batchUpdate(
                    presentationId=pres_id,
                    body={"requests": delete_requests},
                ).execute(),
                label="Clear default placeholders",
            )

        emu = lambda inches: int(inches * 914400)  # noqa: E731
        def _rgb(hex_str):
            h = hex_str.lstrip("#")
            return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

        black = _rgb("000000")
        white = _rgb("FFFFFF")
        dark_gray = _rgb("333333")

        title_id = f"info_title_{uuid.uuid4().hex[:8]}"
        subtitle_id = f"info_sub_{uuid.uuid4().hex[:8]}"
        body_id = f"info_body_{uuid.uuid4().hex[:8]}"

        requests = [
            {"updatePageProperties": {
                "objectId": default_page_id,
                "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": white}}}},
                "fields": "pageBackgroundFill.solidFill.color",
            }},
            {"createShape": {
                "objectId": title_id, "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": default_page_id,
                    "size": {"width": {"magnitude": emu(8.75), "unit": "EMU"}, "height": {"magnitude": emu(0.5), "unit": "EMU"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": emu(0.6), "translateY": emu(0.44), "unit": "EMU"},
                },
            }},
            {"insertText": {"objectId": title_id, "text": "tellr instructions: Read me & delete me!", "insertionIndex": 0}},
            {"updateTextStyle": {"objectId": title_id, "textRange": {"type": "ALL"},
                "style": {"fontSize": {"magnitude": 31, "unit": "PT"}, "foregroundColor": {"opaqueColor": {"rgbColor": black}}},
                "fields": "fontSize,foregroundColor"}},
            {"createShape": {
                "objectId": subtitle_id, "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": default_page_id,
                    "size": {"width": {"magnitude": emu(8.75), "unit": "EMU"}, "height": {"magnitude": emu(0.5), "unit": "EMU"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": emu(0.6), "translateY": emu(0.96), "unit": "EMU"},
                },
            }},
            {"insertText": {"objectId": subtitle_id, "text": "Questions? Please reach out to your Databricks Account team.", "insertionIndex": 0}},
            {"updateTextStyle": {"objectId": subtitle_id, "textRange": {"type": "ALL"},
                "style": {"fontSize": {"magnitude": 15, "unit": "PT"}, "foregroundColor": {"opaqueColor": {"rgbColor": dark_gray}}},
                "fields": "fontSize,foregroundColor"}},
            {"createShape": {
                "objectId": body_id, "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": default_page_id,
                    "size": {"width": {"magnitude": emu(8.75), "unit": "EMU"}, "height": {"magnitude": emu(3.15), "unit": "EMU"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": emu(0.6), "translateY": emu(1.63), "unit": "EMU"},
                },
            }},
            {"insertText": {"objectId": body_id, "text": (
                "tellr is open source and in early-stage development (equivalent to private preview).\n"
                "We're actively developing new features and welcome feedback.\n"
                "Please wait while your deck is populating below"
            ), "insertionIndex": 0}},
            {"updateTextStyle": {"objectId": body_id, "textRange": {"type": "ALL"},
                "style": {"fontSize": {"magnitude": 13, "unit": "PT"}, "foregroundColor": {"opaqueColor": {"rgbColor": dark_gray}}},
                "fields": "fontSize,foregroundColor"}},
        ]

        _retry_api_call(
            lambda: slides_service.presentations().batchUpdate(
                presentationId=pres_id,
                body={"requests": requests},
            ).execute(),
            label="Build title slide",
        )

        print(f"[GSLIDES_CONVERTER] Created presentation: {pres_id}")
        logger.info("Created presentation via Slides API", extra={"pres_id": pres_id})
        return pres_id

    # -- Per-slide pipeline ------------------------------------------------

    # -- Slide prep / parallel codegen / execution helpers --------------------

    def _prepare_slide(
        self, html_str: str, client_chart_images: Optional[Dict[str, str]], slide_num: int,
    ) -> Tuple[str, List[str], List[str], str]:
        """Save images to disk and clean HTML. Returns (html, chart_files, content_files, assets_dir)."""
        work_dir = Path(tempfile.mkdtemp(prefix=f"gslides_slide_{slide_num}_"))
        assets_dir = work_dir / "assets"
        assets_dir.mkdir()

        chart_images: List[str] = []
        if client_chart_images:
            chart_images = self._save_chart_images(client_chart_images, str(assets_dir))
            if chart_images:
                print(f"[GSLIDES_CONVERTER] Slide {slide_num}: saved {len(chart_images)} chart images")

        html_str, content_images = self._extract_and_save_content_images(html_str, str(assets_dir))
        if content_images:
            print(f"[GSLIDES_CONVERTER] Slide {slide_num}: extracted {len(content_images)} content images: {content_images}")
        print(f"[GSLIDES_CONVERTER] Slide {slide_num}: HTML length after image extraction: {len(html_str)}")

        return html_str, chart_images, content_images, str(assets_dir)

    def _generate_code_sync(self, html_str: str, chart_images: List[str], content_images: Optional[List[str]] = None) -> Optional[str]:
        """Synchronous code generation for use with asyncio.to_thread."""
        content_images = content_images or []
        html_content = _truncate_html_for_prompt(html_str)
        screenshot_note = self._build_chart_note(chart_images)
        if content_images:
            screenshot_note += self._build_content_image_note(content_images)
        prompt = self.USER_PROMPT.format(
            html_content=html_content, screenshot_note=screenshot_note,
        )
        return self._call_llm_sync(self.SYSTEM_PROMPT, prompt)

    async def _generate_all_codes(
        self,
        slide_inputs: List[Tuple[str, List[str], List[str], str]],
        on_codegen_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[Optional[str]]:
        """Generate code for all slides in parallel, capped at MAX_CONCURRENT_LLM.

        Args:
            slide_inputs: List of (html, chart_files, content_files, assets_dir).
            on_codegen_progress: Optional ``(completed, total)`` callback fired
                after each slide's code is generated.
        """
        sem = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        total = len(slide_inputs)
        completed = 0
        lock = asyncio.Lock()

        async def gen_one(html_str: str, chart_images: List[str], content_images: List[str]) -> Optional[str]:
            nonlocal completed
            async with sem:
                code = await asyncio.to_thread(
                    self._generate_code_sync, html_str, chart_images, content_images,
                )
            async with lock:
                completed += 1
                if on_codegen_progress:
                    try:
                        on_codegen_progress(completed, total)
                    except Exception:
                        pass
            return code

        return list(await asyncio.gather(
            *(gen_one(h, c, ci) for h, c, ci, _ad in slide_inputs)
        ))

    # -- LLM calls ---------------------------------------------------------

    async def _generate_code(self, html_str, chart_images, content_images=None):
        """Generate Google Slides API code from HTML."""
        content_images = content_images or []
        html_content = _truncate_html_for_prompt(html_str)
        screenshot_note = self._build_chart_note(chart_images)
        if content_images:
            screenshot_note += self._build_content_image_note(content_images)
        prompt = self.USER_PROMPT.format(
            html_content=html_content, screenshot_note=screenshot_note,
        )
        return await self._call_llm(self.SYSTEM_PROMPT, prompt)

    def _build_chart_note(self, chart_images):
        if not chart_images:
            return "No chart images available in assets_dir. If the HTML has <canvas> or Chart.js, skip the chart — do NOT try to recreate it with matplotlib or any other library."
        files = ", ".join(chart_images)
        return (
            f"CHART IMAGES in assets_dir: {files}\n"
            f"CRITICAL: You MUST use these pre-captured images. Do NOT recreate charts with matplotlib or any library.\n"
            f"For each image filename, append ONE createImage request that references it by\n"
            f"placeholder URL — do NOT upload anything, do NOT touch any Google service:\n"
            f"  {{'createImage': {{'objectId': 'img_' + str(uuid.uuid4())[:8], 'url': 'tellr-asset://' + filename, 'elementProperties': {{'pageObjectId': page_id, 'size': {{...}}, 'transform': {{...}}}}}}}}\n"
            f"The host uploads the file to Drive and substitutes the real URL before execution.\n"
            f"Position: If chart is the main content, use left=0.4\", top=1.1\", width=9.0\", height=4.0\" (fills body zone).\n"
            f"If chart + metrics side-by-side, use left=0.4\", top=1.1\", width=4.5\", height=3.0\"."
        )

    def _build_content_image_note(self, content_images):
        files = ", ".join(content_images)
        return (
            f"\nCONTENT IMAGES (logos/icons) in assets_dir: {files}\n"
            f"These are logos/icons extracted from <img> tags in the HTML.\n"
            f"CRITICAL: You MUST add each content image to the slide via a createImage\n"
            f"request with url = 'tellr-asset://' + filename. NEVER upload; NEVER touch\n"
            f"Drive yourself — the host uploads and substitutes the real URL before execution.\n"
            f"  {{'createImage': {{'objectId': 'img_' + str(uuid.uuid4())[:8], 'url': 'tellr-asset://' + filename, 'elementProperties': {{'pageObjectId': page_id, 'size': {{'width': {{'magnitude': emu(w), 'unit': 'EMU'}}, 'height': {{'magnitude': emu(h), 'unit': 'EMU'}}}}, 'transform': {{'scaleX': 1, 'scaleY': 1, 'translateX': emu(left), 'translateY': emu(top), 'unit': 'EMU'}}}}}}}}\n"
            f"Position the image to match its placement in the HTML layout. "
            f"For logos/icons typically in the header area, use small sizes (e.g. width=0.6\"-1.0\", height=0.3\"-0.5\").\n"
        )

    def _call_llm_sync(self, system_prompt, user_prompt, thinking_budget: int = 10240):
        """Synchronous LLM call — core implementation used by both async and threaded paths."""
        start = time.time()
        try:
            resp = self.llm_client.chat.completions.create(
                model=self.model_endpoint,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=16384,
                timeout=300,
                extra_body={"thinking": {"type": "enabled", "budget_tokens": thinking_budget}},
            )
            duration = time.time() - start
            logger.info("LLM call completed", extra={"duration_s": f"{duration:.1f}"})
            code = self._extract_text(resp.choices[0].message.content)
            return self._strip_fences(code) if code else None
        except Exception:
            duration = time.time() - start
            logger.error("LLM call failed", extra={"duration_s": f"{duration:.1f}"}, exc_info=True)
            return None

    async def _call_llm(self, system_prompt, user_prompt, thinking_budget: int = 10240):
        """Async wrapper — delegates to _call_llm_sync."""
        return self._call_llm_sync(system_prompt, user_prompt, thinking_budget)

    @staticmethod
    def _classify_error(error_msg: str, original_code: str) -> dict:
        """Classify the error and extract structured context for the retry prompt.

        Returns a dict with keys:
          - ``kind``: "syntax_truncated" | "syntax_other" | "api" | "other"
          - ``code_section_label``: human-readable label for the code excerpt
          - ``code_excerpt``: the code lines most relevant to the error
          - ``guidance``: tailored regeneration instruction for the LLM
          - ``concise_retry``: True if the retry LLM call should use a lower
            thinking budget (e.g. truncation — we want a shorter output)
        """
        msg = error_msg.lower()

        line_num = None
        m = re.search(r"line (\d+)", error_msg)
        if m:
            line_num = int(m.group(1))

        code_lines = original_code.splitlines()
        total_lines = len(code_lines)

        # ---- SyntaxError -------------------------------------------------------
        if "syntaxerror" in msg or (line_num and "syntax" in msg):
            is_truncation = any(t in msg for t in (
                "was never closed", "unexpected eof", "unexpected end",
                "eof while scanning",
            )) or (line_num and line_num >= total_lines - 5)

            if is_truncation:
                tail_start = max(0, total_lines - 40)
                code_excerpt = "\n".join(
                    f"{tail_start + i + 1:4d} | {l}"
                    for i, l in enumerate(code_lines[tail_start:])
                )
                return {
                    "kind": "syntax_truncated",
                    "code_section_label": "Tail of truncated code (where generation was cut off):",
                    "code_excerpt": code_excerpt,
                    "guidance": (
                        "Your previous generation was TRUNCATED — the token limit was reached "
                        "before the function was complete (shown by the unclosed bracket/brace "
                        "at the end above). Using the HTML source below as your complete "
                        "reference, write the COMPLETE build_slide_requests function from "
                        "scratch. Keep the implementation concise: combine related requests into "
                        "fewer batchUpdate calls to stay within the token limit."
                    ),
                    "concise_retry": True,
                }
            else:
                if line_num:
                    start = max(0, line_num - 25)
                    end = min(total_lines, line_num + 5)
                    code_excerpt = "\n".join(
                        f"{'>>>' if start + i + 1 == line_num else '   '} "
                        f"{start + i + 1:4d} | {l}"
                        for i, l in enumerate(code_lines[start:end])
                    )
                    label = f"Code around line {line_num} where the SyntaxError occurred ('>>>' marks the failing line):"
                else:
                    code_excerpt = "\n".join(code_lines[:80])
                    label = "Beginning of code with SyntaxError:"
                return {
                    "kind": "syntax_other",
                    "code_section_label": label,
                    "code_excerpt": code_excerpt,
                    "guidance": (
                        "Your generated code had a syntax error (shown above). "
                        "Use the HTML source below as your complete reference and write the "
                        "COMPLETE build_slide_requests function from scratch — do not try "
                        "to patch only the lines shown above; the HTML is the source of truth "
                        "for all slide content and layout."
                    ),
                    "concise_retry": False,
                }

        # ---- Google Slides API error -------------------------------------------
        if _looks_like_slides_api_error(error_msg):
            # Include as much of the original code as fits so the LLM can locate
            # the bad request and understand the surrounding context.
            code_excerpt = original_code[:8000]
            return {
                "kind": "api",
                "code_section_label": "Original generated code (the failing API request is somewhere in here):",
                "code_excerpt": code_excerpt,
                "guidance": (
                    "Fix the Google Slides API error shown above. "
                    "Using the HTML source below as your reference for slide content, "
                    "return the COMPLETE corrected build_slide_requests function."
                ),
                "concise_retry": False,
            }

        # ---- Generic fallback --------------------------------------------------
        return {
            "kind": "other",
            "code_section_label": "Original generated code:",
            "code_excerpt": original_code[:6000],
            "guidance": (
                "Fix the error shown above. Using the HTML source below as your reference, "
                "return the COMPLETE build_slide_requests function."
            ),
            "concise_retry": False,
        }

    async def _retry_with_error(
        self, original_code, error_msg, html_str=None, chart_images=None, content_images=None,
    ):
        """Re-prompt LLM with targeted, error-type-aware context."""
        ctx = self._classify_error(error_msg, original_code)

        # Always include the source HTML — it is the sole authoritative source
        # of slide content.  Without it the LLM has nothing to work from and
        # will hallucinate content.
        html_content = ""
        if html_str:
            truncated = _truncate_html_for_prompt(html_str)
            html_content = f"\n\nHTML source to convert (authoritative — use this for all slide content):\n{truncated}\n"

        chart_note = ""
        if chart_images:
            chart_note = f"\n{self._build_chart_note(chart_images)}\n"
        if content_images:
            chart_note += f"\n{self._build_content_image_note(content_images)}\n"

        fix_prompt = (
            f"Your previously generated code produced this error:\n\n"
            f"```\n{error_msg[:2000]}\n```\n\n"
            f"{ctx['guidance']}\n\n"
            f"{ctx['code_section_label']}\n\n"
            f"```python\n{ctx['code_excerpt']}\n```\n"
            f"{html_content}{chart_note}\n"
            f"Return ONLY the Python code for the complete build_slide_requests function."
        )
        return await self._call_llm(
            self.SYSTEM_PROMPT, fix_prompt,
            # For truncation retries, reduce the thinking budget so the LLM
            # focuses on writing concise, complete code rather than over-thinking.
            thinking_budget=5120 if ctx["concise_retry"] else 10240,
        )

    @staticmethod
    def _extract_text(content):
        """Extract text from LLM response (handles reasoning model blocks)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
        return str(content) if content else ""

    @staticmethod
    def _strip_fences(code):
        """Remove markdown code fences."""
        m = re.search(r"```[Pp]ython\s*\n(.*?)```", code, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*\n(.*?)```", code, re.DOTALL)
        if m:
            return m.group(1).strip()
        lines = code.strip().splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    # -- Code sanitizer ----------------------------------------------------

    @staticmethod
    def _prepare_code(code):
        """Minimal prep: ensure function wrapper and fix smart quotes."""
        # Wrap bare code in function if LLM forgot the function definition
        if "def add_slide_to_presentation" not in code:
            logger.info("Prep: wrapping bare code in add_slide_to_presentation function")
            lines = code.split("\n")
            imports, body, helpers = [], [], []
            in_helper = False

            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")) and not body:
                    imports.append(line)
                elif stripped.startswith(("def emu(", "def hex_to_rgb(")):
                    in_helper = True
                    helpers.append(line)
                elif in_helper:
                    if stripped == "" or (line and line[0] == " "):
                        helpers.append(line)
                        if stripped == "":
                            in_helper = False
                    else:
                        in_helper = False
                        body.append(line)
                else:
                    body.append(line)

            indented = [("    " + l if l.strip() else "") for l in body]
            parts = []
            if imports:
                parts.append("\n".join(imports) + "\n")
            if helpers:
                parts.append("\n".join(helpers) + "\n")
            parts.append(
                "def add_slide_to_presentation(slides_service, drive_service, "
                "presentation_id, page_id, html_str, assets_dir):"
            )
            parts.extend(indented)
            code = "\n".join(parts)

        # Ensure imports
        if "import os" not in code:
            code = "import os\nimport json\nimport uuid\n\n" + code

        # Smart quotes → straight quotes (prevents SyntaxError)
        for smart, straight in {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}.items():
            code = code.replace(smart, straight)

        # Strip 'alpha' from rgbColor dicts — the Slides API rejects it.
        import re as _re
        _alpha_pat = _re.compile(r"""[,\s]*['"]alpha['"]\s*:\s*[\d.]+""")
        if 'alpha' in code:
            new_code = _alpha_pat.sub('', code)
            if new_code != code:
                logger.info("Prep: stripped 'alpha' entries from rgbColor dicts")
                code = new_code

        # Fix missing 'shapeProperties' wrapper in updateShapeProperties.
        # LLM consistently puts shapeBackgroundFill/outline directly inside
        # updateShapeProperties — the API requires them inside 'shapeProperties'.
        if ('updateShapeProperties' in code and 'shapeBackgroundFill' in code
                and 'shapeProperties' not in code):
            logger.info("Prep: injecting shapeProperties wrapper")
            lines = code.split('\n')
            out = []
            i = 0
            while i < len(lines):
                s = lines[i].strip()
                # Look for the shapeBackgroundFill line inside an updateShapeProperties block
                if ('shapeBackgroundFill' in s and s.startswith("'shapeBackgroundFill")
                        and i > 0 and 'objectId' in lines[i - 1]):
                    indent = len(lines[i]) - len(lines[i].lstrip())
                    out.append(' ' * indent + "'shapeProperties': {")
                    # Collect lines until we hit 'fields'
                    while i < len(lines):
                        fs = lines[i].strip()
                        if fs.startswith("'fields'") or fs.startswith('"fields"'):
                            out.append(' ' * indent + '},')
                            out.append(lines[i])
                            break
                        out.append(lines[i])
                        i += 1
                else:
                    out.append(lines[i])
                i += 1
            code = '\n'.join(out)

        # Fix 'paragraphStyle' → 'style' inside updateParagraphStyle blocks.
        # LLM often uses {'updateParagraphStyle': {..., 'paragraphStyle': {...}}}
        # but the API requires {'updateParagraphStyle': {..., 'style': {...}}}.
        if 'updateParagraphStyle' in code:
            if "'paragraphStyle'" in code:
                logger.info("Prep: fixing 'paragraphStyle' → 'style' in updateParagraphStyle")
                code = code.replace("'paragraphStyle'", "'style'")
            if '"paragraphStyle"' in code:
                logger.info("Prep: fixing \"paragraphStyle\" → \"style\" in updateParagraphStyle")
                code = code.replace('"paragraphStyle"', '"style"')

        # Same fix for updateTextStyle — LLM sometimes uses 'textStyle' instead of 'style'.
        if 'updateTextStyle' in code:
            if "'textStyle'" in code:
                logger.info("Prep: fixing 'textStyle' → 'style' in updateTextStyle")
                code = code.replace("'textStyle'", "'style'")
            if '"textStyle"' in code:
                logger.info("Prep: fixing \"textStyle\" → \"style\" in updateTextStyle")
                code = code.replace('"textStyle"', '"style"')

        # Re-quote single-quoted literals that contain contractions (Don't, it's, etc.)
        code = _fix_apostrophe_strings(code)

        try:
            ast.parse(code)
        except SyntaxError as prep_exc:
            logger.debug(
                "Prepared GSlides code still not parseable: %s (line %s)",
                prep_exc.msg,
                prep_exc.lineno,
            )

        return code

    # -- Host-side batchUpdate executor (SDR-4437 PR-5) --------------------

    # Positive allowlist of batchUpdate request-type keys the host will execute.
    # Derived from _SkipTracker._CREATE_KEYS (createShape, createTable,
    # createImage, createLine, createSheetsChart) so the two sets cannot drift.
    _ALLOWED_REQUEST_KEYS = frozenset(_SkipTracker._CREATE_KEYS) | frozenset({
        "createSlide", "insertText", "deleteObject",
        "updateTextStyle", "updateParagraphStyle", "updateShapeProperties",
        "updatePageProperties", "updateTableCellProperties",
        "createParagraphBullets", "insertTableRows", "insertTableColumns",
        "updatePageElementTransform", "updateImageProperties",
    })

    def _validate_requests(self, requests):
        """Schema-gate emitted requests. Raises GoogleSlidesConversionError on
        any unknown top-level key or an image url that is not a
        ``tellr-asset://<safe-basename>`` placeholder.

        SDR-4437 PR-5 hardening: the ONLY accepted createImage url shape is the
        placeholder scheme with a safe basename (``^[A-Za-z0-9_.-]+$``, no path
        separators). Raw ``https://`` urls are rejected — every legitimate image
        now flows through host-side upload of a ``tellr-asset://`` placeholder,
        so accepting attacker-controlled ``https://`` would be a Google-side
        SSRF (Google fetches the url server-side). Rejecting non-basename
        filenames here is the first of two path-traversal guards; the second is
        the resolved-path containment check in
        ``_upload_and_substitute_assets``."""
        if not isinstance(requests, list):
            raise GoogleSlidesConversionError("requests must be a list")
        from src.services.converter_jail import protocol
        for req in requests:
            if not isinstance(req, dict) or len(req) != 1:
                raise GoogleSlidesConversionError(f"malformed request: {req!r}")
            (key, val), = req.items()
            if key not in self._ALLOWED_REQUEST_KEYS:
                raise GoogleSlidesConversionError(f"disallowed request type: {key}")
            if key == "createImage":
                url = (val or {}).get("url", "")
                if not url.startswith(protocol.ASSET_SCHEME):
                    raise GoogleSlidesConversionError(f"disallowed image url: {url!r}")
                filename = url[len(protocol.ASSET_SCHEME):]
                if not _SAFE_ASSET_NAME_RE.match(filename):
                    raise GoogleSlidesConversionError(
                        f"unsafe asset filename: {filename!r}"
                    )
        return requests

    def _upload_and_substitute_assets(self, requests, drive_service, assets_dir):
        """Upload each tellr-asset:// referenced file to Drive and substitute
        the real URL. Records uploaded file IDs on self._uploaded_file_ids.

        SDR-4437 PR-5 hardening: the filename comes from untrusted LLM-emitted
        request data, so before opening the file we confine the resolved path
        to ``assets_dir``. This blocks absolute-path (``tellr-asset:///proc/self/environ``
        — ``Path(base) / "/abs"`` discards ``base``) and traversal
        (``tellr-asset://../../etc/passwd``) reads that would otherwise be
        uploaded to Drive and made world-readable by the trusted host."""
        from googleapiclient.http import MediaFileUpload
        from src.services.converter_jail import protocol

        if not hasattr(self, "_uploaded_file_ids"):
            self._uploaded_file_ids = []
        base = Path(assets_dir).resolve()
        cache = {}
        for req in requests:
            if "createImage" not in req:
                continue
            url = req["createImage"].get("url", "")
            if not url.startswith(protocol.ASSET_SCHEME):
                continue
            filename = url[len(protocol.ASSET_SCHEME):]
            if filename not in cache:
                if not _SAFE_ASSET_NAME_RE.match(filename):
                    raise GoogleSlidesConversionError(
                        f"unsafe asset filename: {filename!r}"
                    )
                path = (base / filename).resolve()
                if not path.is_relative_to(base):
                    raise GoogleSlidesConversionError(
                        f"asset path escapes assets_dir: {filename!r}"
                    )
                media = MediaFileUpload(str(path), mimetype="image/png")
                created = _retry_api_call(
                    lambda: drive_service.files().create(
                        body={"name": filename, "mimeType": "image/png"},
                        media_body=media, fields="id",
                    ).execute(),
                    label=f"Upload {filename}",
                )
                file_id = created["id"]
                _retry_api_call(
                    lambda: drive_service.permissions().create(
                        fileId=file_id, body={"type": "anyone", "role": "reader"},
                    ).execute(),
                    label=f"Share {filename}",
                )
                self._uploaded_file_ids.append(file_id)
                cache[filename] = f"https://drive.google.com/uc?id={file_id}"
            req["createImage"]["url"] = cache[filename]
        return requests

    def _execute_slide_requests(self, requests, slides_service, drive_service,
                                pres_id, page_id, assets_dir, slide_num):
        """Validate → upload+substitute → execute through _ChunkedSlidesService.
        Returns None on success, error string on failure."""
        try:
            self._validate_requests(requests)
            requests = self._upload_and_substitute_assets(
                requests, drive_service, assets_dir,
            )
            wrapped = _ChunkedSlidesService(
                slides_service, chunk_size=4, slide_num=slide_num,
            )
            wrapped.presentations().batchUpdate(
                presentationId=pres_id, body={"requests": requests},
            ).execute()
            return None
        except Exception as exc:
            logger.warning("Slide %d host execution failed", slide_num, exc_info=True)
            return str(exc)

    def _build_gslides_job_dir(self, codes, slide_inputs, page_ids) -> str:
        """Write the jail job dir: manifest + per-slide code/html/assets, with
        page_id per slide and AST-guarded snippets (rejected → has_code=false →
        host fallback)."""
        import json as _json
        import os as _os
        import shutil as _shutil
        import tempfile as _tempfile
        from src.services.converter_jail import protocol
        from src.services.converter_jail.ast_guard import DisallowedImport, check_imports

        job_dir = _tempfile.mkdtemp(prefix="gslides_jail_job_")
        slides_manifest = []
        for idx, (code, (html_str, _cf, _if, assets_dir)) in enumerate(
            zip(codes, slide_inputs)
        ):
            sdir = Path(job_dir) / f"slide_{idx:03d}"
            sdir.mkdir()
            has_code = bool(code) and page_ids[idx] is not None
            if has_code:
                try:
                    check_imports(code)
                except (DisallowedImport, SyntaxError) as exc:
                    logger.warning("GSlides slide %d snippet rejected pre-jail: %s", idx + 1, exc)
                    has_code = False
            if has_code:
                (sdir / protocol.CODE_NAME).write_text(code, encoding="utf-8")
                (sdir / protocol.HTML_NAME).write_text(html_str, encoding="utf-8")
            dest = sdir / protocol.ASSETS_DIR
            try:
                _os.symlink(assets_dir, dest, target_is_directory=True)
            except OSError:
                _shutil.copytree(assets_dir, dest)
            slides_manifest.append({
                "index": idx, "has_code": has_code,
                "dir": sdir.name, "page_id": page_ids[idx],
            })
        (Path(job_dir) / protocol.MANIFEST_NAME).write_text(
            _json.dumps({"slides": slides_manifest})
        )
        return job_dir

    def _emit_single_slide(self, code, html_str, assets_dir, page_id):
        """Run one snippet through the jail to (re)emit its requests. Returns
        the requests list or None on failure."""
        import json as _json
        import os as _os
        import shutil as _shutil
        import tempfile as _tempfile
        from src.services.converter_jail import protocol, run_gslides_jail

        job_dir = _tempfile.mkdtemp(prefix="gslides_retry_")
        try:
            sdir = Path(job_dir) / "slide_000"
            (sdir / protocol.ASSETS_DIR).mkdir(parents=True)
            # Reuse the already-prepared assets.
            _shutil.rmtree(sdir / protocol.ASSETS_DIR)
            try:
                _os.symlink(assets_dir, sdir / protocol.ASSETS_DIR, target_is_directory=True)
            except OSError:
                _shutil.copytree(assets_dir, sdir / protocol.ASSETS_DIR)
            (sdir / protocol.CODE_NAME).write_text(code, encoding="utf-8")
            (sdir / protocol.HTML_NAME).write_text(html_str, encoding="utf-8")
            (Path(job_dir) / protocol.MANIFEST_NAME).write_text(_json.dumps(
                {"slides": [{"index": 0, "has_code": True,
                             "dir": "slide_000", "page_id": page_id}]}
            ))
            out = str(Path(job_dir) / "requests.json")
            result = run_gslides_jail(job_dir, out)
            if result.timed_out or result.returncode != 0:
                return None
            data = _json.loads(Path(out).read_text())
            return data[0].get("requests")
        finally:
            _shutil.rmtree(job_dir, ignore_errors=True)

    # -- Code execution ----------------------------------------------------

    def _add_fallback(self, slides_service, pres_id, page_id, slide_num):
        """Add a simple placeholder text box when all code-gen attempts fail."""
        eid = f"fallback_{uuid.uuid4().hex[:8]}"
        try:
            slides_service.presentations().batchUpdate(
                presentationId=pres_id,
                body={"requests": [
                    {"createShape": {
                        "objectId": eid, "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": page_id,
                            "size": {"width": {"magnitude": 7315200, "unit": "EMU"},
                                     "height": {"magnitude": 914400, "unit": "EMU"}},
                            "transform": {"scaleX": 1, "scaleY": 1,
                                          "translateX": 914400, "translateY": 2743200, "unit": "EMU"},
                        },
                    }},
                    {"insertText": {"objectId": eid, "text": f"Slide {slide_num}", "insertionIndex": 0}},
                    {"updateTextStyle": {
                        "objectId": eid,
                        "style": {"fontSize": {"magnitude": 32, "unit": "PT"},
                                  "foregroundColor": {"opaqueColor": {"rgbColor": {"red": 0.06, "green": 0.13, "blue": 0.15}}}},
                        "textRange": {"type": "ALL"}, "fields": "fontSize,foregroundColor",
                    }},
                    {"updateParagraphStyle": {
                        "objectId": eid, "style": {"alignment": "CENTER"},
                        "textRange": {"type": "ALL"}, "fields": "alignment",
                    }},
                ]},
            ).execute()
        except Exception:
            logger.error("Fallback content also failed", exc_info=True)

    # -- Content image helpers ---------------------------------------------

    # Regex matching <img> tags whose src is a base64 data URI.
    _BASE64_IMG_RE = re.compile(
        r'(<img\b[^>]*?\bsrc=")data:image/(png|jpeg|jpg|gif|svg\+xml);base64,([A-Za-z0-9+/=\s]+)(")',
        re.IGNORECASE,
    )
    _EXT_MAP = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "gif": ".gif", "svg+xml": ".svg"}

    @staticmethod
    def _svg_to_png(svg_bytes: bytes) -> bytes:
        """Convert SVG bytes to PNG using svgpathtools + Pillow (pure Python).

        Parses SVG ``<path>`` elements, samples bezier curves to polygons,
        and rasterises them onto a Pillow RGBA canvas.

        Args:
            svg_bytes: Raw SVG file content.

        Returns:
            PNG image bytes.
        """
        import io
        import xml.etree.ElementTree as ET

        from PIL import Image, ImageDraw
        from svgpathtools import parse_path

        root = ET.fromstring(svg_bytes)
        w = int(float(root.get("width", "100")))
        h = int(float(root.get("height", "100")))

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        paths = (
            root.findall("{http://www.w3.org/2000/svg}path")
            or root.findall("path")
        )

        for elem in paths:
            d = elem.get("d", "")
            fill = elem.get("fill", "none")
            transform = elem.get("transform", "")

            if fill == "none" or not d:
                continue
            if not (fill.startswith("#") and len(fill) >= 7):
                continue

            r_c = int(fill[1:3], 16)
            g_c = int(fill[3:5], 16)
            b_c = int(fill[5:7], 16)

            tx, ty = 0.0, 0.0
            tm = re.match(r"translate\(([^,]+),([^)]+)\)", transform)
            if tm:
                tx, ty = float(tm.group(1)), float(tm.group(2))

            try:
                path = parse_path(d)
                length = path.length()
                n = max(200, int(length))
                n = min(n, 5000)
                points = []
                for i in range(n):
                    pt = path.point(i / n)
                    points.append((pt.real + tx, pt.imag + ty))
                if len(points) >= 3:
                    draw.polygon(points, fill=(r_c, g_c, b_c, 255))
            except Exception:
                continue

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _extract_and_save_content_images(
        self, html_str: str, assets_dir: str,
    ) -> tuple[str, list[str]]:
        """Extract base64-embedded images from HTML, save as files, replace src.

        This prevents huge base64 blobs from being sent to the LLM and makes
        the images available as files that can be uploaded to Google Drive.

        Returns:
            Tuple of (cleaned_html, list_of_saved_filenames).
        """
        filenames: list[str] = []
        counter = 0

        def _replace(match: re.Match) -> str:
            nonlocal counter
            prefix = match.group(1)
            mime_sub = match.group(2)
            b64_data = match.group(3)
            suffix = match.group(4)

            ext = self._EXT_MAP.get(mime_sub.lower(), ".png")
            filename = f"content_image_{counter}{ext}"
            counter += 1

            try:
                image_bytes = base64.b64decode(b64_data)

                # Google Slides createImage needs a raster format; SVG won't work.
                if ext == ".svg":
                    image_bytes = self._svg_to_png(image_bytes)
                    filename = filename.rsplit(".", 1)[0] + ".png"

                filepath = Path(assets_dir) / filename
                filepath.write_bytes(image_bytes)
                filenames.append(filename)
                logger.info("Extracted content image", extra={"filename": filename, "size": len(image_bytes)})
            except Exception as e:
                logger.warning("Failed to extract content image", exc_info=True, extra={"error": str(e)})
                return match.group(0)

            return f"{prefix}{filename}{suffix}"

        cleaned = self._BASE64_IMG_RE.sub(_replace, html_str)
        return cleaned, filenames

    # -- Chart image helpers -----------------------------------------------

    def _save_chart_images(self, chart_images_dict, assets_dir):
        """Save base64 chart images to files. Returns list of filenames."""
        saved = []
        assets = Path(assets_dir)
        for canvas_id, b64_data in chart_images_dict.items():
            try:
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                data = base64.b64decode(b64_data)
                name = f"{canvas_id}.png" if canvas_id.startswith("chart_") else \
                       f"chart_{''.join(c if c.isalnum() or c in '_-' else '_' for c in canvas_id)}.png"
                (assets / name).write_bytes(data)
                saved.append(name)
            except Exception as exc:
                logger.warning("Failed to save chart %s: %s", canvas_id, exc)
        return saved

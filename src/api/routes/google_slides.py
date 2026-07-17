"""Google Slides export endpoints.

Provides user-scoped OAuth2 authorization flow and presentation creation
using the V3 LLM code-gen approach.

Credentials come from the global ``GoogleGlobalCredentials`` table;
user tokens are stored per-user in the ``google_oauth_tokens`` table.
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.api.services.chat_service import get_chat_service
from src.api.routes._authz import (
    _check_deck_permission_for_session,
    _require_export_job_access,
)
from src.api.routes.export import ExportJobResponse
from src.core.database import get_db
from src.database.models.oauth_state import OAuthState
from src.database.models.profile_contributor import PermissionLevel
from src.services.drive_uploader import replace_presentation, upload_pptx_as_slides
from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError
from src.services.pptx_from_records import EmitError, build_pptx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export/google-slides", tags=["google-slides"])

# MEDIUM-3 (SDR-4437): OAuth state nonces are single-use and short-lived.
_OAUTH_STATE_TTL_SECONDS = 600


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _get_user_identity() -> str:
    """Return the current user's identity string.

    In production (Databricks Apps) this is the authenticated user's email.
    In local dev it falls back to ``"local_dev"``.

    HIGH-6 (SDR-4437): no except-Exception fallback in production — a
    missing/failed OBO client must fail closed (UserClientRequiredError,
    mapped to 401 in main.py), never store Google OAuth tokens under a
    fallback identity.
    """
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "local_dev"
    from src.core.databricks_client import UserClientRequiredError, get_user_client

    user_name = get_user_client().current_user.me().user_name
    if not user_name:
        raise UserClientRequiredError("OBO client resolved no user_name")
    return user_name


def _get_auth(db: Session) -> GoogleSlidesAuth:
    """Build a DB-backed ``GoogleSlidesAuth`` for the current user."""
    user_identity = _get_user_identity()
    return GoogleSlidesAuth.from_global(user_identity, db)


# -------------------------------------------------------------------------
# Request / Response schemas
# -------------------------------------------------------------------------


class ChartImage(BaseModel):
    """Chart image data from client-side capture."""
    canvas_id: str
    base64_data: str


class ExportGoogleSlidesRequest(BaseModel):
    """Request to export slides to Google Slides."""
    session_id: str
    chart_images: Optional[list[list[ChartImage]]] = None


class AuthStatusResponse(BaseModel):
    authorized: bool


class AuthUrlResponse(BaseModel):
    url: str




# -------------------------------------------------------------------------
# OAuth2 auth endpoints
# -------------------------------------------------------------------------


def _public_base_url(request: Request) -> str:
    """Public origin of the app, reconstructed from x-forwarded-* headers.

    Behind a reverse proxy (Databricks Apps), ``request.base_url`` returns
    the internal address; the proxy's X-Forwarded-Host/Proto give the public
    one. Also used as the explicit postMessage targetOrigin in the OAuth
    popup pages (SDR-4437 MEDIUM-3).

    For localhost, Google only allows ``http``.
    """
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")

    if forwarded_host:
        scheme = forwarded_proto or "https"
        return f"{scheme}://{forwarded_host.split(',')[0].strip()}"

    base = str(request.base_url).rstrip("/")
    # Force http for localhost (Google rejects https://localhost)
    if "://localhost" in base or "://127.0.0.1" in base:
        base = base.replace("https://", "http://")
    return base


def _build_redirect_uri(request: Request) -> str:
    """Build the OAuth callback redirect URI (exact-match, no query params).

    Google requires redirect URIs to match *exactly* what's registered in
    GCP, with no query parameters.
    """
    return f"{_public_base_url(request)}/api/export/google-slides/auth/callback"


def _create_oauth_state(
    db: Session, nonce: str, user_identity: str, code_verifier: str
) -> None:
    """Store a single-use state nonce bound to the authenticated user.

    The caller generates the nonce first: it must be handed to
    ``get_auth_url(state=nonce)``, which is also the call that returns the
    PKCE verifier — so this helper cannot mint the nonce itself (the row's
    PK must equal the ``state`` sent to Google). Expired rows are swept
    opportunistically on every insert.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=_OAUTH_STATE_TTL_SECONDS)
    db.query(OAuthState).filter(OAuthState.created_at < cutoff).delete()
    db.add(
        OAuthState(
            nonce=nonce, user_identity=user_identity, code_verifier=code_verifier
        )
    )
    db.commit()


def _consume_oauth_state(db: Session, nonce: str):
    """Atomically consume a state nonce (single-use, race-safe).

    ``DELETE ... WHERE nonce = :n RETURNING ...`` — under two concurrent
    callbacks exactly one wins; the loser sees no row. Returns the Row
    (user_identity, code_verifier, created_at) or None.
    """
    if not nonce:
        return None
    row = db.execute(
        delete(OAuthState)
        .where(OAuthState.nonce == nonce)
        .returning(
            OAuthState.user_identity,
            OAuthState.code_verifier,
            OAuthState.created_at,
        )
    ).first()
    db.commit()
    return row


def _callback_page(
    app_origin: str, *, success: bool, heading: str, body_text: str, close_ms: int
) -> HTMLResponse:
    payload = json.dumps({"type": "google-slides-auth", "success": success})
    origin_js = json.dumps(app_origin)
    return HTMLResponse(
        content=f"""
        <html><body>
            <h2>{heading}</h2>
            <p>{body_text}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({payload}, {origin_js});
                }}
                setTimeout(() => window.close(), {close_ms});
            </script>
        </body></html>
        """,
        status_code=200,
    )


def _oauth_success_html(app_origin: str) -> HTMLResponse:
    return _callback_page(
        app_origin,
        success=True,
        heading="Authorization Successful",
        body_text="You can close this window.",
        close_ms=1500,
    )


def _oauth_failure_html(app_origin: str) -> HTMLResponse:
    # MEDIUM-2: generic text only — the reason is logged server-side.
    return _callback_page(
        app_origin,
        success=False,
        heading="Authorization Failed",
        body_text=(
            "Authorization failed. Close this window and try connecting "
            "your Google account again."
        ),
        close_ms=3000,
    )


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status(db: Session = Depends(get_db)):
    """Check whether the current user has a valid Google OAuth token."""
    try:
        auth = _get_auth(db)
        return AuthStatusResponse(authorized=auth.is_authorized())
    except (GoogleSlidesAuthError, Exception) as exc:
        # No credentials, bad encryption key, or any other issue → not authorized
        logger.debug("auth_status check failed: %s", exc)
        return AuthStatusResponse(authorized=False)


@router.get("/auth/url", response_model=AuthUrlResponse)
async def auth_url(
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate the Google OAuth consent URL.

    The frontend should open this URL in a popup window.  The OAuth ``state``
    parameter carries ONLY a server-issued single-use nonce (SDR-4437
    MEDIUM-3) — the PKCE verifier and the user binding live in the
    ``oauth_states`` row, never in anything client-visible. The redirect URI
    itself stays clean (no query params) to satisfy Google's exact-match
    requirement.

    Invariant: the nonce passed as ``state`` to ``get_auth_url`` must equal
    the ``oauth_states`` row's PK — ``_create_oauth_state`` takes the nonce
    as an argument for exactly this reason.
    """
    try:
        user_identity = _get_user_identity()
        auth = GoogleSlidesAuth.from_global(user_identity, db)
        redirect_uri = _build_redirect_uri(request)

        # MEDIUM-3 (SDR-4437): state carries ONLY a server-issued single-use
        # nonce; the PKCE verifier and the user binding live in the
        # oauth_states row, never in anything client-visible. Nonce first,
        # then get_auth_url (which returns the verifier), then the row.
        nonce = secrets.token_urlsafe(32)  # 256-bit
        url, code_verifier = auth.get_auth_url(redirect_uri=redirect_uri, state=nonce)
        _create_oauth_state(db, nonce, user_identity, code_verifier)

        return AuthUrlResponse(url=url)
    except GoogleSlidesAuthError as exc:
        logger.warning("auth_url rejected: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Google authorization is missing, expired, or not configured. Connect your Google account and try again.",
        ) from exc
    except Exception as exc:
        logger.error("Failed to generate auth URL: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate authorization URL. Credentials may be corrupt — try re-uploading.",
        ) from exc


@router.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(
    request: Request,
    code: str = Query("", description="Authorization code (absent when the user denies consent)"),
    state: str = Query("", description="Server-issued single-use state nonce"),
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback from Google.

    MEDIUM-3 (SDR-4437): ``state`` is a single-use server-issued nonce
    (``oauth_states`` row) binding this callback to a consent flow that the
    authenticated request user started. Login-CSRF — an attacker completing
    their own consent and feeding the victim their code — fails the
    nonce/user checks. Token persistence keys off the authenticated request
    identity, never off anything client-supplied. All failures return the
    same generic popup page (HTTP 200 + postMessage, the popup contract);
    the specific reason is logged server-side only (MEDIUM-2).
    """
    app_origin = _public_base_url(request)

    try:
        user_identity = _get_user_identity()
    except Exception:
        # PR-2's fail-closed _get_user_identity() raises in production on OBO
        # failure — keep the popup contract: generic page, reason in the log
        # (an unhandled raise here would surface as a 500 JSON body instead).
        logger.error("OAuth callback failed to resolve user identity", exc_info=True)
        return _oauth_failure_html(app_origin)

    if not code:
        # Consent denied / error redirect: Google calls back with ?error=...
        # and NO code. `code` is optional (default "") precisely so this path
        # returns the popup-contract page instead of FastAPI's 422 JSON
        # validation error. Retire the nonce — the flow is over either way.
        _consume_oauth_state(db, state)
        logger.warning(
            "OAuth callback rejected: no authorization code "
            "(consent denied or error redirect)"
        )
        return _oauth_failure_html(app_origin)

    row = _consume_oauth_state(db, state)
    if row is None:
        logger.warning("OAuth callback rejected: unknown or already-used state nonce")
        return _oauth_failure_html(app_origin)
    if row.user_identity != user_identity:
        logger.warning("OAuth callback rejected: state nonce belongs to another user")
        return _oauth_failure_html(app_origin)
    if datetime.utcnow() - row.created_at > timedelta(
        seconds=_OAUTH_STATE_TTL_SECONDS
    ):
        logger.warning("OAuth callback rejected: state nonce expired")
        return _oauth_failure_html(app_origin)

    try:
        auth = GoogleSlidesAuth.from_global(user_identity, db)
        redirect_uri = _build_redirect_uri(request)
        auth.authorize(
            code=code, redirect_uri=redirect_uri, code_verifier=row.code_verifier
        )
        logger.info(
            "Google Slides OAuth callback successful", extra={"user": user_identity}
        )
    except Exception:
        # MEDIUM-2 (SDR-4437): never reflect the exception into the page.
        logger.error("OAuth callback failed", exc_info=True)
        return _oauth_failure_html(app_origin)

    return _oauth_success_html(app_origin)


# -------------------------------------------------------------------------
# Export endpoint
# -------------------------------------------------------------------------


def _build_slide_html(slide: dict, slide_deck: dict) -> str:
    """Build complete HTML for a slide."""
    from src.api.routes.export import build_slide_html
    return build_slide_html(slide, slide_deck)


@router.post("", response_model=ExportJobResponse)
async def start_google_slides_export(
    request_body: ExportGoogleSlidesRequest,
    db: Session = Depends(get_db),
):
    """Start an async Google Slides export job.

    Returns immediately with a job_id.  The frontend polls
    ``GET .../poll/{job_id}`` for progress until completion.

    Flow:
    1. Validate auth, fetch slides, build HTML (fast).
    2. Enqueue background job for the slow LLM conversion.
    3. Return job_id so the frontend can poll.
    """
    # SDR-4437 HIGH-1: caller must hold CAN_VIEW on the deck being exported.
    _check_deck_permission_for_session(request_body.session_id, PermissionLevel.CAN_VIEW)

    from src.api.services.export_job_queue import (
        enqueue_export_job,
        generate_job_id,
    )

    try:
        auth = _get_auth(db)
    except GoogleSlidesAuthError as exc:
        logger.warning("start_google_slides_export rejected: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Google authorization is missing, expired, or not configured. Connect your Google account and try again.",
        ) from exc

    if not auth.is_authorized():
        raise HTTPException(
            status_code=401,
            detail="Not authorized with Google. Complete the OAuth flow first.",
        )

    # Fetch slide deck
    try:
        chat_service = get_chat_service()
        slide_deck = chat_service.get_slides(request_body.session_id)
    except Exception as exc:
        logger.error("Failed to fetch slides", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch slides") from exc

    if not slide_deck or not slide_deck.get("slides"):
        raise HTTPException(status_code=404, detail="No slides available")

    # Substitute {{image:ID}} placeholders with base64 data URIs
    from src.utils.image_utils import substitute_deck_dict_images
    from src.core.database import get_db_session
    with get_db_session() as db:
        substitute_deck_dict_images(slide_deck, db)

    slides_data = slide_deck.get("slides", [])
    total = len(slides_data)
    title = slide_deck.get("title", "Presentation")

    # Build complete HTML for each slide (fast — no LLM calls)
    slides_html: list[str] = []
    for slide in slides_data:
        slides_html.append(_build_slide_html(slide, slide_deck))

    # Prepare chart images
    chart_images_per_slide: Optional[list[dict[str, str]]] = None
    if request_body.chart_images:
        chart_images_per_slide = [
            {img.canvas_id: img.base64_data for img in slide_charts}
            for slide_charts in request_body.chart_images
        ]

    # Check for existing presentation on this session (re-export overwrites)
    from src.api.services.session_manager import get_session_manager
    session_manager = get_session_manager()
    existing_info = session_manager.get_google_slides_info(request_body.session_id)
    existing_presentation_id = existing_info["presentation_id"] if existing_info else None

    # Enqueue background job
    job_id = generate_job_id()
    payload = {
        "session_id": request_body.session_id,
        "user_identity": _get_user_identity(),
        "slides_html": slides_html,
        "title": title,
        "total_slides": total,
        "chart_images_per_slide": chart_images_per_slide,
        "job_type": "google_slides",
        "existing_presentation_id": existing_presentation_id,
    }
    await enqueue_export_job(job_id, payload)

    logger.info(
        "Google Slides export job enqueued",
        extra={"job_id": job_id, "session_id": request_body.session_id, "total_slides": total},
    )

    return ExportJobResponse(
        job_id=job_id,
        status="pending",
        total_slides=total,
    )


@router.get("/poll/{job_id}", response_model=ExportJobResponse)
async def poll_google_slides_export(job_id: str):
    """Poll for Google Slides export status and progress.

    When ``status`` is ``completed``, the response includes
    ``presentation_id`` and ``presentation_url``.
    """
    # SDR-4437: job-ID IDOR — possession of a job_id must not grant access.
    _require_export_job_access(job_id)

    from src.api.services.export_job_queue import build_export_job_response

    try:
        return ExportJobResponse(**build_export_job_response(job_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Export job not found")


# -------------------------------------------------------------------------
# Records-based export — PPTX → Drive auto-convert to Slides
# -------------------------------------------------------------------------


class GoogleSlidesFromRecordsRequest(BaseModel):
    """Records-based Google Slides export request.

    Mirrors the editable-PPTX ``/from-records`` route shape so the
    frontend can reuse ``extractSlideRecordsForExport``.
    """
    session_id: str
    title: str
    slides: list[dict[str, Any]]
    font_mode: str = "google_slides"


class GoogleSlidesExportResponse(BaseModel):
    presentation_id: str
    presentation_url: str


@router.post("/from-records", response_model=GoogleSlidesExportResponse)
async def export_google_slides_from_records(
    request: GoogleSlidesFromRecordsRequest,
    db: Session = Depends(get_db),
):
    """Build a PPTX from DOM-walker records and upload to Drive.

    Drive's ``files.create`` with ``mimeType=application/vnd.google-apps.
    presentation`` triggers automatic conversion to a native Google
    Slides deck — no per-element Slides API calls needed.

    Re-exports on the same session overwrite the previous presentation.
    """
    # SDR-4437 HIGH-1: caller must hold CAN_VIEW on the deck being exported.
    _check_deck_permission_for_session(request.session_id, PermissionLevel.CAN_VIEW)

    try:
        auth = _get_auth(db)
    except GoogleSlidesAuthError as exc:
        logger.warning("export_google_slides_from_records rejected: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Google authorization is missing, expired, or not configured. Connect your Google account and try again.",
        ) from exc

    if not auth.is_authorized():
        raise HTTPException(
            status_code=401,
            detail="Not authorized with Google. Complete the OAuth flow first.",
        )

    try:
        pptx_bytes = build_pptx(
            title=request.title,
            slides=request.slides,
            font_mode=request.font_mode,
        )
    except EmitError as exc:
        logger.error("PPTX build failed for Google Slides export", exc_info=True)
        raise HTTPException(status_code=500, detail="PPTX build failed") from exc

    from src.api.services.session_manager import get_session_manager
    session_manager = get_session_manager()
    existing_info = session_manager.get_google_slides_info(request.session_id)
    existing_id = existing_info["presentation_id"] if existing_info else None

    try:
        if existing_id:
            presentation_id, url = replace_presentation(
                auth, existing_id, pptx_bytes, request.title,
            )
        else:
            presentation_id, url = upload_pptx_as_slides(
                auth, pptx_bytes, request.title,
            )
    except Exception as exc:
        logger.error("Drive upload failed", exc_info=True)
        raise HTTPException(status_code=502, detail="Drive upload failed") from exc

    session_manager.set_google_slides_info(
        session_id=request.session_id,
        presentation_id=presentation_id,
        presentation_url=url,
    )

    logger.info(
        "Google Slides export complete",
        extra={
            "session_id": request.session_id,
            "presentation_id": presentation_id,
            "replaced": bool(existing_id),
        },
    )

    return GoogleSlidesExportResponse(
        presentation_id=presentation_id,
        presentation_url=url,
    )


# -------------------------------------------------------------------------
# Huashu-based export — server-side Chromium → PPTX → Drive auto-convert
# -------------------------------------------------------------------------


class GoogleSlidesFromHuashuRequest(BaseModel):
    """Huashu-based Google Slides export request.

    No client-side records needed — the backend fetches the deck from
    session storage and builds complete HTML server-side.
    """
    session_id: str


@router.post("/from-huashu", response_model=GoogleSlidesExportResponse)
async def export_google_slides_from_huashu(
    request: GoogleSlidesFromHuashuRequest,
    db: Session = Depends(get_db),
):
    """Build a PPTX via the huashu (Playwright + Chromium) pipeline and
    upload to Drive.

    Trade-offs vs. ``/from-records``:
      * Higher fidelity — server-side Chromium re-renders the actual deck
        HTML and walks the rendered DOM, getting exact positions/fonts/
        colors instead of relying on the client-side walker's records.
      * Slower — ~20-30s for a 10-slide deck because Chromium spawns per
        slide. Acceptable for a one-shot Drive upload.
      * ``bypass_validation=True`` is set so every slide makes it into the
        output PPTX even if it violates huashu's design rules. Without
        this, failing slides would be silently dropped from the deck on
        Drive (e.g. slide 7 missing, numbering shifted) — terrible UX.

    Re-exports on the same session overwrite the previous presentation
    (same as ``/from-records``).
    """
    # SDR-4437 HIGH-1: caller must hold CAN_VIEW on the deck being exported.
    _check_deck_permission_for_session(request.session_id, PermissionLevel.CAN_VIEW)

    from src.services.pptx_from_html_huashu import (
        HuashuExportError,
        build_pptx_huashu,
    )

    try:
        auth = _get_auth(db)
    except GoogleSlidesAuthError as exc:
        logger.warning("export_google_slides_from_huashu rejected: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Google authorization is missing, expired, or not configured. Connect your Google account and try again.",
        ) from exc

    if not auth.is_authorized():
        raise HTTPException(
            status_code=401,
            detail="Not authorized with Google. Complete the OAuth flow first.",
        )

    chat_service = get_chat_service()
    slide_deck = chat_service.get_slides(request.session_id)
    if not slide_deck or not slide_deck.get("slides"):
        raise HTTPException(status_code=404, detail="No slides available")

    # Substitute {{image:ID}} placeholders with base64 data URIs (same as the
    # legacy /export route). Use a fresh session because the request's `db`
    # is held by the route's transaction context.
    from src.core.database import get_db_session
    from src.utils.image_utils import substitute_deck_dict_images
    with get_db_session() as imdb:
        substitute_deck_dict_images(slide_deck, imdb)

    title = slide_deck.get("title") or "Presentation"
    slides_data = slide_deck.get("slides") or []

    slides_html = [
        {
            "html": _build_slide_html(slide, slide_deck),
            "notes": slide.get("notes") or "",
        }
        for slide in slides_data
    ]

    try:
        pptx_bytes, failures = build_pptx_huashu(
            title=title,
            slides_html=slides_html,
            bypass_validation=True,
        )
    except HuashuExportError as exc:
        logger.error("Huashu pipeline error for Google Slides export", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Huashu pipeline unavailable",
        ) from exc

    if not pptx_bytes:
        # With bypass_validation=True the only way this happens is if every
        # slide hit a non-validation error (e.g. chromium failed to launch
        # for all of them). Surface the failures so the user can debug.
        logger.error(
            "Huashu produced no output even with bypass; failures=%s", failures
        )
        raise HTTPException(
            status_code=500,
            detail=f"Huashu produced no output. failures={failures}",
        )

    from src.api.services.session_manager import get_session_manager
    session_manager = get_session_manager()
    existing_info = session_manager.get_google_slides_info(request.session_id)
    existing_id = existing_info["presentation_id"] if existing_info else None

    try:
        if existing_id:
            presentation_id, url = replace_presentation(
                auth, existing_id, pptx_bytes, title,
            )
        else:
            presentation_id, url = upload_pptx_as_slides(
                auth, pptx_bytes, title,
            )
    except Exception as exc:
        logger.error("Drive upload failed (huashu path)", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Drive upload failed",
        ) from exc

    session_manager.set_google_slides_info(
        session_id=request.session_id,
        presentation_id=presentation_id,
        presentation_url=url,
    )

    logger.info(
        "Google Slides huashu export complete",
        extra={
            "session_id": request.session_id,
            "presentation_id": presentation_id,
            "replaced": bool(existing_id),
            "huashu_failures": len(failures),
        },
    )

    return GoogleSlidesExportResponse(
        presentation_id=presentation_id,
        presentation_url=url,
    )

"""Google Slides export endpoints.

Provides profile-scoped, user-scoped OAuth2 authorization flow and
presentation creation using the V3 LLM code-gen approach.

Credentials come from the profile's encrypted ``google_credentials_encrypted``
column; user tokens are stored per-user in the ``google_oauth_tokens`` table.
"""

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.services.chat_service import get_chat_service
from src.api.routes.export import ExportJobResponse
from src.core.database import get_db
from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export/google-slides", tags=["google-slides"])


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _get_user_identity() -> str:
    """Return the current user's identity string.

    In production (Databricks Apps) this is the authenticated user's email.
    In local dev it falls back to ``"local_dev"``.
    """
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "local_dev"
    try:
        from src.core.databricks_client import get_user_client
        client = get_user_client()
        return client.current_user.me().user_name or "local_dev"
    except Exception:
        return "local_dev"


def _get_auth(profile_id: int, db: Session) -> GoogleSlidesAuth:
    """Build a DB-backed ``GoogleSlidesAuth`` for the current user + profile."""
    user_identity = _get_user_identity()
    return GoogleSlidesAuth.from_profile(profile_id, user_identity, db)


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
    profile_id: int
    chart_images: Optional[list[list[ChartImage]]] = None


class AuthStatusResponse(BaseModel):
    authorized: bool


class AuthUrlResponse(BaseModel):
    url: str




# -------------------------------------------------------------------------
# OAuth2 auth endpoints
# -------------------------------------------------------------------------


def _build_redirect_uri(request: Request) -> str:
    """Build the OAuth callback redirect URI from the current request.

    Google requires redirect URIs to match *exactly* what's registered in GCP,
    with no query parameters.

    Behind a reverse proxy (e.g. Databricks Apps), ``request.base_url``
    returns the internal address (``http://localhost:8000``).  We use the
    ``X-Forwarded-Host`` / ``X-Forwarded-Proto`` headers set by the proxy
    to reconstruct the public URL instead.

    For localhost, Google only allows ``http``.
    """
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")

    if forwarded_host:
        scheme = forwarded_proto or "https"
        base = f"{scheme}://{forwarded_host.split(',')[0].strip()}"
    else:
        base = str(request.base_url).rstrip("/")
        # Force http for localhost (Google rejects https://localhost)
        if "://localhost" in base or "://127.0.0.1" in base:
            base = base.replace("https://", "http://")

    return f"{base}/api/export/google-slides/auth/callback"


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status(
    profile_id: int = Query(..., description="Profile ID to check"),
    db: Session = Depends(get_db),
):
    """Check whether the current user has a valid Google OAuth token for a profile."""
    try:
        auth = _get_auth(profile_id, db)
        return AuthStatusResponse(authorized=auth.is_authorized())
    except (GoogleSlidesAuthError, Exception) as exc:
        # No credentials, bad encryption key, or any other issue → not authorized
        logger.debug("auth_status check failed for profile %s: %s", profile_id, exc)
        return AuthStatusResponse(authorized=False)


@router.get("/auth/url", response_model=AuthUrlResponse)
async def auth_url(
    request: Request,
    profile_id: int = Query(..., description="Profile ID whose credentials to use"),
    db: Session = Depends(get_db),
):
    """Generate the Google OAuth consent URL for a profile.

    The frontend should open this URL in a popup window.  Context (profile_id,
    user) is passed via the OAuth ``state`` parameter so the callback can route
    the token to the right profile — the redirect URI itself stays clean
    (no query params) to satisfy Google's exact-match requirement.
    """
    try:
        auth = _get_auth(profile_id, db)
        redirect_uri = _build_redirect_uri(request)
        state = json.dumps({"profile_id": profile_id, "user": _get_user_identity()})
        url = auth.get_auth_url(redirect_uri=redirect_uri, state=state)

        return AuthUrlResponse(url=url)
    except GoogleSlidesAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to generate auth URL for profile %s: %s", profile_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate authorization URL. Credentials may be corrupt — try re-uploading.",
        ) from exc


@router.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(
    request: Request,
    code: str,
    state: str = Query("", description="OAuth state carrying profile context"),
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback from Google.

    ``profile_id`` is extracted from the ``state`` parameter that was set
    during the consent URL generation.  The redirect URI used here must
    match exactly what was registered in GCP (no query params).

    Exchanges the authorization code for tokens, encrypts them, and stores
    them in the ``google_oauth_tokens`` table.  Returns a small HTML page
    that notifies the opener window and closes itself.
    """
    try:
        state_data = json.loads(state) if state else {}
        profile_id = int(state_data.get("profile_id", 0))
        if not profile_id:
            raise ValueError("Missing profile_id in OAuth state")

        auth = _get_auth(profile_id, db)
        redirect_uri = _build_redirect_uri(request)
        auth.authorize(code=code, redirect_uri=redirect_uri)
        logger.info(
            "Google Slides OAuth callback successful",
            extra={"profile_id": profile_id, "user": _get_user_identity()},
        )
    except (GoogleSlidesAuthError, ValueError, json.JSONDecodeError) as exc:
        logger.error("OAuth callback failed", exc_info=True)
        return HTMLResponse(
            content=f"""
            <html><body>
                <h2>Authorization Failed</h2>
                <p>{exc}</p>
                <script>
                    if (window.opener) {{
                        window.opener.postMessage({{ type: 'google-slides-auth', success: false }}, '*');
                    }}
                    setTimeout(() => window.close(), 3000);
                </script>
            </body></html>
            """,
            status_code=200,
        )

    return HTMLResponse(
        content="""
        <html><body>
            <h2>Authorization Successful</h2>
            <p>You can close this window.</p>
            <script>
                if (window.opener) {
                    window.opener.postMessage({ type: 'google-slides-auth', success: true }, '*');
                }
                setTimeout(() => window.close(), 1500);
            </script>
        </body></html>
        """,
        status_code=200,
    )


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
    from src.api.services.export_job_queue import (
        enqueue_export_job,
        generate_job_id,
    )

    try:
        auth = _get_auth(request_body.profile_id, db)
    except GoogleSlidesAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        raise HTTPException(status_code=500, detail=f"Failed to fetch slides: {exc}") from exc

    if not slide_deck or not slide_deck.get("slides"):
        raise HTTPException(status_code=404, detail="No slides available")

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

    # Enqueue background job
    job_id = generate_job_id()
    payload = {
        "session_id": request_body.session_id,
        "profile_id": request_body.profile_id,
        "user_identity": _get_user_identity(),
        "slides_html": slides_html,
        "title": title,
        "total_slides": total,
        "chart_images_per_slide": chart_images_per_slide,
        "job_type": "google_slides",
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
    from src.api.services.export_job_queue import build_export_job_response

    try:
        return ExportJobResponse(**build_export_job_response(job_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Export job not found")

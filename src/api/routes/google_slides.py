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
from src.core.database import get_db
from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError
from src.services.html_to_google_slides import (
    HtmlToGoogleSlidesConverter,
    GoogleSlidesConversionError,
)

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


class ExportGoogleSlidesResponse(BaseModel):
    presentation_id: str
    presentation_url: str


# -------------------------------------------------------------------------
# OAuth2 auth endpoints
# -------------------------------------------------------------------------


def _build_redirect_uri(request: Request) -> str:
    """Build the OAuth callback redirect URI from the current request."""
    base = str(request.base_url).rstrip("/")
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

    The frontend should open this URL in a popup window.  ``profile_id`` is
    encoded into the ``state`` parameter so the callback can look up the right
    profile.
    """
    try:
        auth = _get_auth(profile_id, db)
        redirect_uri = _build_redirect_uri(request)
        url = auth.get_auth_url(redirect_uri=redirect_uri)

        # Append state so callback knows which profile / user to store the token for
        state_payload = json.dumps({"profile_id": profile_id, "user": _get_user_identity()})
        # google_auth_oauthlib encodes state automatically; we re-build
        # with from_client_config so the state is already baked in. Instead,
        # we persist it server-side in a lightweight dict keyed by profile+user.
        # For simplicity, pass profile_id as a query param on the redirect URI.
        # Re-generate auth URL with profile_id baked into redirect URI.
        redirect_uri_with_state = f"{_build_redirect_uri(request)}?profile_id={profile_id}"
        url = auth.get_auth_url(redirect_uri=redirect_uri_with_state)

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
    profile_id: int = Query(..., description="Profile that owns the credentials"),
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback from Google.

    Exchanges the authorization code for tokens, encrypts them, and stores
    them in the ``google_oauth_tokens`` table.  Returns a small HTML page
    that notifies the opener window and closes itself.
    """
    try:
        auth = _get_auth(profile_id, db)
        redirect_uri = f"{_build_redirect_uri(request)}?profile_id={profile_id}"
        auth.authorize(code=code, redirect_uri=redirect_uri)
        logger.info(
            "Google Slides OAuth callback successful",
            extra={"profile_id": profile_id, "user": _get_user_identity()},
        )
    except GoogleSlidesAuthError as exc:
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


@router.post("", response_model=ExportGoogleSlidesResponse)
async def export_to_google_slides(
    request_body: ExportGoogleSlidesRequest,
    db: Session = Depends(get_db),
):
    """Export the current slide deck to a new Google Slides presentation.

    Flow:
    1. Build a DB-backed auth instance for the current user + profile.
    2. Verify authorization.
    3. Fetch slide deck from session.
    4. Build complete HTML per slide.
    5. Run the V3 LLM code-gen converter.
    6. Return the presentation URL.
    """
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

    logger.info(
        "Starting Google Slides export",
        extra={"session_id": request_body.session_id, "total_slides": total},
    )

    # Build complete HTML for each slide
    slides_html: list[str] = []
    for i, slide in enumerate(slides_data):
        html = _build_slide_html(slide, slide_deck)
        slides_html.append(html)

    # Prepare chart images
    chart_images_per_slide: Optional[list[dict[str, str]]] = None
    if request_body.chart_images:
        chart_images_per_slide = [
            {img.canvas_id: img.base64_data for img in slide_charts}
            for slide_charts in request_body.chart_images
        ]

    # Convert
    try:
        converter = HtmlToGoogleSlidesConverter(google_auth=auth)
        result = await converter.convert_slide_deck(
            slides=slides_html,
            title=title,
            chart_images_per_slide=chart_images_per_slide,
        )
    except (GoogleSlidesConversionError, GoogleSlidesAuthError) as exc:
        logger.error("Google Slides conversion failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected error during Google Slides export", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Export failed: {exc}"
        ) from exc

    return ExportGoogleSlidesResponse(
        presentation_id=result["presentation_id"],
        presentation_url=result["presentation_url"],
    )

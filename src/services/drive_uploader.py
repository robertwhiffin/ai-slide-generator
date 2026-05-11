"""Upload PPTX files to Google Drive with auto-conversion to Google Slides."""

import io
import logging
import sys
from typing import Tuple

from googleapiclient.http import MediaIoBaseUpload

from src.services.google_slides_auth import GoogleSlidesAuth

logger = logging.getLogger(__name__)


def _debug(msg: str) -> None:
    """Write a debug line directly to stderr so it surfaces in container logs
    regardless of Python's logging configuration."""
    print(f"[drive_uploader] {msg}", file=sys.stderr, flush=True)

# MIME types
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
GSLIDES_MIME = "application/vnd.google-apps.presentation"


def upload_pptx_as_slides(
    auth: GoogleSlidesAuth,
    pptx_bytes: bytes,
    title: str,
) -> Tuple[str, str]:
    """Upload a PPTX file to Google Drive, auto-converting to Google Slides.

    Args:
        auth: Authenticated GoogleSlidesAuth instance.
        pptx_bytes: Raw PPTX file bytes.
        title: Presentation title (used as the Drive file name).

    Returns:
        Tuple of (presentation_id, web_view_url).
    """
    drive_service = auth.build_drive_service()

    file_metadata = {
        "name": title,
        "mimeType": GSLIDES_MIME,  # triggers auto-conversion from PPTX
    }

    media = MediaIoBaseUpload(
        io.BytesIO(pptx_bytes),
        mimetype=PPTX_MIME,
        resumable=True,
    )

    _debug(f"Starting upload: title={title!r}")
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,webViewLink",
    ).execute()

    presentation_id = file["id"]
    web_view_url = file.get("webViewLink", f"https://docs.google.com/presentation/d/{presentation_id}/edit")
    _debug(f"Created presentation: id={presentation_id}")

    # File is created with the requesting user's OAuth credentials, so it
    # lives in their Drive with full owner access. They open it in a new
    # browser tab using their existing Google session — no additional
    # sharing needed. Previously we granted "anyone-with-link writer" so
    # an embedded iframe could render without cookies, but the actual UI
    # uses window.open(url, '_blank') and the broad share was getting
    # flagged by DoControl as an open-access violation. Users who want
    # to share with others can do so via Google Drive's normal sharing UI.

    _debug(f"Upload complete: url={web_view_url}")
    return presentation_id, web_view_url


def replace_presentation(
    auth: GoogleSlidesAuth,
    old_presentation_id: str,
    pptx_bytes: bytes,
    title: str,
) -> Tuple[str, str]:
    """Replace an existing Google Slides presentation by deleting and re-uploading.

    Args:
        auth: Authenticated GoogleSlidesAuth instance.
        old_presentation_id: ID of the existing presentation to delete.
        pptx_bytes: New PPTX file bytes.
        title: Presentation title.

    Returns:
        Tuple of (new_presentation_id, new_web_view_url).
    """
    drive_service = auth.build_drive_service()

    # Delete old presentation (best-effort)
    try:
        drive_service.files().delete(fileId=old_presentation_id).execute()
        logger.info(f"Deleted old presentation: {old_presentation_id}")
    except Exception as e:
        logger.warning(f"Could not delete old presentation {old_presentation_id}: {e}")

    # Upload new one
    return upload_pptx_as_slides(auth, pptx_bytes, title)

"""PPTX-first Google Slides export pipeline.

Generates a PPTX via the existing HtmlToPptxConverterV3 converter, then
uploads it to Google Drive with automatic conversion to Google Slides format.
This eliminates the fragile LLM-to-Google-Slides-API code-generation path.
"""

import logging
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from googleapiclient.http import MediaFileUpload

from src.services.google_slides_auth import GoogleSlidesAuth
from src.services.html_to_pptx_deterministic import DeterministicPptxConverter

logger = logging.getLogger(__name__)

# Retry configuration for Drive API uploads
_MAX_UPLOAD_RETRIES = 3
_UPLOAD_BACKOFF_BASE = 2  # seconds


class PptxToGoogleSlidesError(Exception):
    """Raised when the PPTX-to-Google-Slides upload/conversion fails."""


class PptxToGoogleSlidesUploader:
    """Upload a PPTX file to Google Drive and convert to native Google Slides."""

    def __init__(self, google_auth: GoogleSlidesAuth):
        self.auth = google_auth

    def upload_and_convert(
        self,
        pptx_path: str,
        title: str = "Presentation",
        existing_presentation_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Upload PPTX to Google Drive, converting to Google Slides format.

        Args:
            pptx_path: Path to the .pptx file on disk.
            title: Title for the Google Slides presentation.
            existing_presentation_id: If provided, delete the old presentation
                before uploading the new one.

        Returns:
            Dict with ``presentation_id`` and ``presentation_url``.
        """
        drive_service = self.auth.build_drive_service()

        # Delete previous presentation if re-exporting
        if existing_presentation_id:
            try:
                drive_service.files().delete(fileId=existing_presentation_id).execute()
                logger.info("Deleted previous presentation %s", existing_presentation_id)
            except Exception:
                logger.warning(
                    "Could not delete previous presentation %s — it may have been removed already",
                    existing_presentation_id,
                    exc_info=True,
                )

        # Upload with automatic conversion to Google Slides
        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.presentation",
        }

        file_size = Path(pptx_path).stat().st_size
        resumable = file_size > 5 * 1024 * 1024  # resumable for files > 5 MB

        media = MediaFileUpload(
            pptx_path,
            mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            resumable=resumable,
        )

        last_exc = None
        for attempt in range(1, _MAX_UPLOAD_RETRIES + 1):
            try:
                uploaded = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields="id",
                ).execute()

                pres_id = uploaded["id"]
                url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
                logger.info("Uploaded PPTX as Google Slides: %s", url)
                return {"presentation_id": pres_id, "presentation_url": url}

            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_UPLOAD_RETRIES:
                    wait = _UPLOAD_BACKOFF_BASE ** attempt
                    logger.warning(
                        "Upload attempt %d failed, retrying in %ds: %s",
                        attempt, wait, exc,
                    )
                    time.sleep(wait)

        raise PptxToGoogleSlidesError(
            f"Failed to upload PPTX after {_MAX_UPLOAD_RETRIES} attempts: {last_exc}"
        ) from last_exc


async def convert_html_to_google_slides(
    slides_html: List[str],
    title: str,
    google_auth: GoogleSlidesAuth,
    chart_images_per_slide: Optional[List[Dict[str, str]]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    existing_presentation_id: Optional[str] = None,
) -> Dict[str, str]:
    """End-to-end pipeline: HTML slides -> PPTX -> Google Slides.

    Args:
        slides_html: List of HTML strings, one per slide.
        title: Presentation title.
        google_auth: Authenticated GoogleSlidesAuth instance.
        chart_images_per_slide: Chart images per slide (passed to PPTX converter).
        progress_callback: ``(current, total, status)`` callback.
        existing_presentation_id: Re-export over an existing presentation.

    Returns:
        Dict with ``presentation_id`` and ``presentation_url``.
    """
    total = len(slides_html)
    print(f"[GSLIDES_PPTX_PIPELINE] Converting {total} slides via PPTX-first pipeline")

    # Step 1: Generate PPTX using the existing proven converter
    tmp_pptx = tempfile.NamedTemporaryFile(
        delete=False, suffix=".pptx", prefix="gslides_upload_",
    )
    tmp_path = tmp_pptx.name
    tmp_pptx.close()

    try:
        converter = DeterministicPptxConverter()
        await converter.convert_slide_deck(
            slides=slides_html,
            output_path=tmp_path,
            chart_images_per_slide=chart_images_per_slide,
        )

        if progress_callback:
            try:
                progress_callback(total, total, "Uploading to Google Slides...")
            except Exception:
                pass

        # Step 2: Upload PPTX to Google Drive with auto-conversion
        print(f"[GSLIDES_PPTX_PIPELINE] PPTX generated, uploading to Google Drive...")
        uploader = PptxToGoogleSlidesUploader(google_auth)
        result = uploader.upload_and_convert(
            pptx_path=tmp_path,
            title=title,
            existing_presentation_id=existing_presentation_id,
        )

        print(f"[GSLIDES_PPTX_PIPELINE] Done: {result['presentation_url']}")
        return result

    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

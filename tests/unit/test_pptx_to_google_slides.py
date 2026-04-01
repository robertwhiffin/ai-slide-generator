"""Tests for the PPTX-first Google Slides export pipeline.

Tests the new pptx_to_google_slides module:
- PptxToGoogleSlidesUploader: uploads PPTX to Drive with auto-conversion
- convert_html_to_google_slides: end-to-end orchestrator
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.services.pptx_to_google_slides import (
    PptxToGoogleSlidesUploader,
    PptxToGoogleSlidesError,
    convert_html_to_google_slides,
)


# ---------------------------------------------------------------------------
# PptxToGoogleSlidesUploader
# ---------------------------------------------------------------------------

class TestPptxToGoogleSlidesUploader:
    """Test the uploader that sends PPTX to Google Drive."""

    def _make_uploader(self, mock_drive_service=None):
        mock_auth = MagicMock()
        mock_auth.build_drive_service.return_value = mock_drive_service or MagicMock()
        return PptxToGoogleSlidesUploader(mock_auth), mock_auth

    def test_upload_and_convert_success(self, tmp_path):
        """Successful upload returns presentation_id and URL."""
        # Create a dummy PPTX file
        pptx_file = tmp_path / "test.pptx"
        pptx_file.write_bytes(b"fake pptx content")

        mock_drive = MagicMock()
        mock_drive.files().create().execute.return_value = {"id": "abc123"}

        uploader, _ = self._make_uploader(mock_drive)
        result = uploader.upload_and_convert(str(pptx_file), title="Test Deck")

        assert result["presentation_id"] == "abc123"
        assert result["presentation_url"] == "https://docs.google.com/presentation/d/abc123/edit"

    def test_upload_and_convert_sets_correct_mime_types(self, tmp_path):
        """Upload should set Google Slides mimeType for auto-conversion."""
        pptx_file = tmp_path / "test.pptx"
        pptx_file.write_bytes(b"fake pptx content")

        mock_drive = MagicMock()
        mock_drive.files().create().execute.return_value = {"id": "xyz"}

        uploader, _ = self._make_uploader(mock_drive)
        uploader.upload_and_convert(str(pptx_file), title="My Deck")

        # Verify create was called with the right metadata
        create_call = mock_drive.files().create
        call_kwargs = create_call.call_args
        body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert body["mimeType"] == "application/vnd.google-apps.presentation"
        assert body["name"] == "My Deck"

    def test_upload_retries_on_failure(self, tmp_path):
        """Upload retries up to 3 times on transient errors."""
        pptx_file = tmp_path / "test.pptx"
        pptx_file.write_bytes(b"fake pptx content")

        mock_drive = MagicMock()
        # Fail twice, succeed on third
        mock_drive.files().create().execute.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            {"id": "retry_ok"},
        ]

        uploader, _ = self._make_uploader(mock_drive)
        result = uploader.upload_and_convert(str(pptx_file))

        assert result["presentation_id"] == "retry_ok"

    def test_upload_raises_after_max_retries(self, tmp_path):
        """Raises PptxToGoogleSlidesError after 3 failed attempts."""
        pptx_file = tmp_path / "test.pptx"
        pptx_file.write_bytes(b"fake pptx content")

        mock_drive = MagicMock()
        mock_drive.files().create().execute.side_effect = Exception("always fails")

        uploader, _ = self._make_uploader(mock_drive)

        with pytest.raises(PptxToGoogleSlidesError, match="Failed to upload PPTX after 3 attempts"):
            uploader.upload_and_convert(str(pptx_file))

    def test_deletes_existing_presentation_on_reexport(self, tmp_path):
        """When existing_presentation_id is provided, delete old one first."""
        pptx_file = tmp_path / "test.pptx"
        pptx_file.write_bytes(b"fake pptx content")

        mock_drive = MagicMock()
        mock_drive.files().create().execute.return_value = {"id": "new_id"}

        uploader, _ = self._make_uploader(mock_drive)
        result = uploader.upload_and_convert(
            str(pptx_file), existing_presentation_id="old_id"
        )

        # Verify delete was called on the old presentation
        mock_drive.files().delete.assert_called_once_with(fileId="old_id")
        assert result["presentation_id"] == "new_id"

    def test_delete_failure_doesnt_block_upload(self, tmp_path):
        """If deleting old presentation fails, upload should still proceed."""
        pptx_file = tmp_path / "test.pptx"
        pptx_file.write_bytes(b"fake pptx content")

        mock_drive = MagicMock()
        mock_drive.files().delete().execute.side_effect = Exception("not found")
        mock_drive.files().create().execute.return_value = {"id": "new_id"}

        uploader, _ = self._make_uploader(mock_drive)
        result = uploader.upload_and_convert(
            str(pptx_file), existing_presentation_id="deleted_id"
        )

        assert result["presentation_id"] == "new_id"


# ---------------------------------------------------------------------------
# convert_html_to_google_slides (orchestrator)
# ---------------------------------------------------------------------------

class TestConvertHtmlToGoogleSlides:
    """Test the end-to-end PPTX-first pipeline."""

    def test_orchestrator_calls_pptx_converter_then_uploads(self):
        """The orchestrator should generate PPTX then upload to Drive."""
        mock_auth = MagicMock()
        mock_drive = MagicMock()
        mock_auth.build_drive_service.return_value = mock_drive
        mock_drive.files().create().execute.return_value = {"id": "gslides_123"}

        slides_html = ["<div>Slide 1</div>", "<div>Slide 2</div>"]

        with patch("src.services.pptx_to_google_slides.HtmlToPptxConverterV3") as MockConverter:
            mock_instance = MockConverter.return_value
            # Make convert_slide_deck a coroutine that creates a fake PPTX
            async def fake_convert(slides, output_path, **kwargs):
                Path(output_path).write_bytes(b"fake pptx")
                return output_path
            mock_instance.convert_slide_deck = fake_convert

            result = asyncio.run(convert_html_to_google_slides(
                slides_html=slides_html,
                title="Test Presentation",
                google_auth=mock_auth,
            ))

        assert result["presentation_id"] == "gslides_123"
        assert "docs.google.com/presentation" in result["presentation_url"]

    def test_orchestrator_cleans_up_temp_file(self):
        """Temp PPTX file should be deleted after upload."""
        mock_auth = MagicMock()
        mock_drive = MagicMock()
        mock_auth.build_drive_service.return_value = mock_drive
        mock_drive.files().create().execute.return_value = {"id": "cleanup_test"}

        created_paths = []

        with patch("src.services.pptx_to_google_slides.HtmlToPptxConverterV3") as MockConverter:
            mock_instance = MockConverter.return_value
            async def fake_convert(slides, output_path, **kwargs):
                Path(output_path).write_bytes(b"fake pptx")
                created_paths.append(output_path)
                return output_path
            mock_instance.convert_slide_deck = fake_convert

            asyncio.run(convert_html_to_google_slides(
                slides_html=["<div>Test</div>"],
                title="Cleanup Test",
                google_auth=mock_auth,
            ))

        # Temp file should be cleaned up
        assert len(created_paths) == 1
        assert not Path(created_paths[0]).exists()

    def test_orchestrator_passes_chart_images(self):
        """Chart images should be forwarded to the PPTX converter."""
        mock_auth = MagicMock()
        mock_drive = MagicMock()
        mock_auth.build_drive_service.return_value = mock_drive
        mock_drive.files().create().execute.return_value = {"id": "charts_test"}

        chart_images = [{"canvas1": "data:image/png;base64,abc123"}]
        captured_kwargs = {}

        with patch("src.services.pptx_to_google_slides.HtmlToPptxConverterV3") as MockConverter:
            mock_instance = MockConverter.return_value
            async def fake_convert(slides, output_path, **kwargs):
                captured_kwargs.update(kwargs)
                Path(output_path).write_bytes(b"fake pptx")
                return output_path
            mock_instance.convert_slide_deck = fake_convert

            asyncio.run(convert_html_to_google_slides(
                slides_html=["<div>Chart slide</div>"],
                title="Charts Test",
                google_auth=mock_auth,
                chart_images_per_slide=chart_images,
            ))

        assert captured_kwargs.get("chart_images_per_slide") == chart_images

    def test_orchestrator_calls_progress_callback(self):
        """Progress callback should be called during the pipeline."""
        mock_auth = MagicMock()
        mock_drive = MagicMock()
        mock_auth.build_drive_service.return_value = mock_drive
        mock_drive.files().create().execute.return_value = {"id": "progress_test"}

        progress_calls = []

        with patch("src.services.pptx_to_google_slides.HtmlToPptxConverterV3") as MockConverter:
            mock_instance = MockConverter.return_value
            async def fake_convert(slides, output_path, **kwargs):
                Path(output_path).write_bytes(b"fake pptx")
                return output_path
            mock_instance.convert_slide_deck = fake_convert

            asyncio.run(convert_html_to_google_slides(
                slides_html=["<div>S1</div>", "<div>S2</div>"],
                title="Progress Test",
                google_auth=mock_auth,
                progress_callback=lambda c, t, s: progress_calls.append((c, t, s)),
            ))

        assert len(progress_calls) >= 1
        # Last call should indicate upload phase
        assert "Upload" in progress_calls[-1][2]

    def test_orchestrator_handles_upload_failure(self):
        """If upload fails, PptxToGoogleSlidesError should propagate."""
        mock_auth = MagicMock()
        mock_drive = MagicMock()
        mock_auth.build_drive_service.return_value = mock_drive
        mock_drive.files().create().execute.side_effect = Exception("Drive API down")

        with patch("src.services.pptx_to_google_slides.HtmlToPptxConverterV3") as MockConverter:
            mock_instance = MockConverter.return_value
            async def fake_convert(slides, output_path, **kwargs):
                Path(output_path).write_bytes(b"fake pptx")
                return output_path
            mock_instance.convert_slide_deck = fake_convert

            with pytest.raises(PptxToGoogleSlidesError):
                asyncio.run(convert_html_to_google_slides(
                    slides_html=["<div>Fail</div>"],
                    title="Fail Test",
                    google_auth=mock_auth,
                ))

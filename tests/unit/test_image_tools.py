"""Unit tests for the search_images agent tool."""
import json

import pytest
from unittest.mock import patch, MagicMock

from src.services.image_tools import search_images


class TestSearchImagesTool:
    """Tests for the agent's search_images tool function."""

    def _make_mock_image(self, id=1, filename="logo.png", description="Company logo",
                         tags=None, category="branding", mime_type="image/png"):
        mock = MagicMock()
        mock.id = id
        mock.original_filename = filename
        mock.description = description
        mock.tags = tags or ["branding"]
        mock.category = category
        mock.mime_type = mime_type
        return mock

    def test_returns_json_string(self):
        mock_image = self._make_mock_image()

        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = [mock_image]

            result = search_images(category="branding")

        parsed = json.loads(result)
        assert len(parsed["images"]) == 1
        assert parsed["images"][0]["id"] == 1
        assert parsed["images"][0]["filename"] == "logo.png"

    def test_returns_usage_hint_with_placeholder(self):
        mock_image = self._make_mock_image(id=42, description="Logo")

        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = [mock_image]

            result = search_images()

        parsed = json.loads(result)
        assert "{{image:42}}" in parsed["images"][0]["usage"]

    def test_does_not_include_base64(self):
        mock_image = self._make_mock_image(description="", tags=[])

        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = [mock_image]

            result = search_images()

        # CRITICAL: base64 data must NEVER appear in tool results
        parsed = json.loads(result)
        for img in parsed["images"]:
            assert "base64_data" not in img
            assert "cached_base64" not in img
            assert "image_data" not in img

    def test_returns_empty_message_when_no_results(self):
        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = []

            result = search_images(query="nonexistent")

        parsed = json.loads(result)
        assert parsed["images"] == []
        assert "No images found" in parsed["message"]

    def test_passes_filters_to_service(self):
        with patch("src.services.image_tools.get_db_session") as mock_ctx, \
             patch("src.services.image_tools.image_service") as mock_svc:
            mock_db = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_svc.search_images.return_value = []

            search_images(query="logo", category="branding", tags=["logo"])

        mock_svc.search_images.assert_called_once_with(
            db=mock_db,
            query="logo",
            category="branding",
            tags=["logo"],
        )

"""Tests for PPTX export base64 image extraction.

Regression tests ensuring base64 data URIs are extracted from HTML
before being sent to the LLM, preventing truncation of image data
and ensuring the LLM receives clean HTML with file references.
"""

import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.html_to_pptx import HtmlToPptxConverterV3


# A minimal valid PNG (1x1 transparent pixel)
TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYPgPAAEDAQAIicLsAAAAASUVORK5CYII="
)
TINY_PNG_B64 = base64.b64encode(TINY_PNG_BYTES).decode("ascii")


def _make_converter():
    """Create a converter with mocked external dependencies."""
    converter = HtmlToPptxConverterV3.__new__(HtmlToPptxConverterV3)
    converter.llm_client = MagicMock()
    converter.model_endpoint = "test-model"
    converter.SYSTEM_PROMPT = "system"
    converter.USER_PROMPT_TEMPLATE = "{html_content}\n{screenshot_note}"
    converter.MULTI_SLIDE_SYSTEM_PROMPT = "multi system"
    converter.MULTI_SLIDE_USER_PROMPT = "{html_content}\n{screenshot_note}"
    return converter


class TestExtractAndSaveContentImages:
    """Unit tests for _extract_and_save_content_images()."""

    def test_extracts_png_image(self, tmp_path):
        """A base64 PNG <img> is extracted, saved to disk, and replaced with filename."""
        converter = _make_converter()
        html = f'<div><img src="data:image/png;base64,{TINY_PNG_B64}" alt="logo" /></div>'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert len(filenames) == 1
        assert filenames[0].startswith("content_image_")
        assert filenames[0].endswith(".png")
        assert "data:image" not in cleaned
        assert filenames[0] in cleaned
        # File actually written to disk
        assert (tmp_path / filenames[0]).exists()
        assert (tmp_path / filenames[0]).read_bytes() == TINY_PNG_BYTES

    def test_extracts_jpeg_image(self, tmp_path):
        """A base64 JPEG <img> is extracted with .jpg extension."""
        converter = _make_converter()
        html = f'<img src="data:image/jpeg;base64,{TINY_PNG_B64}" />'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert len(filenames) == 1
        assert filenames[0].endswith(".jpg")
        assert (tmp_path / filenames[0]).exists()

    def test_extracts_multiple_images(self, tmp_path):
        """Multiple base64 images are each extracted with unique filenames."""
        converter = _make_converter()
        html = (
            f'<img src="data:image/png;base64,{TINY_PNG_B64}" />'
            f'<img src="data:image/png;base64,{TINY_PNG_B64}" />'
        )

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert len(filenames) == 2
        assert filenames[0] != filenames[1]
        assert "data:image" not in cleaned

    def test_no_images_returns_unchanged_html(self, tmp_path):
        """HTML without base64 images passes through unchanged."""
        converter = _make_converter()
        html = "<div><h1>No images here</h1></div>"

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert cleaned == html
        assert filenames == []

    def test_preserves_non_base64_img_tags(self, tmp_path):
        """Regular <img> tags with URL src are left untouched."""
        converter = _make_converter()
        html = '<img src="content_image_0.png" /><img src="https://example.com/logo.png" />'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert cleaned == html
        assert filenames == []


class TestLLMPromptHasNoBase64:
    """The HTML sent to the LLM must not contain data:image base64 URIs."""

    @pytest.mark.asyncio
    async def test_single_slide_prompt_contains_no_base64(self, tmp_path):
        """Single-slide path: LLM prompt must not contain base64 data URIs."""
        converter = _make_converter()

        # Build HTML with embedded base64 image
        html = (
            f'<div class="slide"><h1>Title</h1>'
            f'<img src="data:image/png;base64,{TINY_PNG_B64}" alt="logo" />'
            f'</div>'
        )

        # Capture what the LLM receives
        captured_prompts = []

        async def fake_call_llm(system_prompt, user_prompt):
            captured_prompts.append(user_prompt)
            return "def convert_to_pptx(html_str, output_path, assets_dir): pass"

        converter._call_llm = fake_call_llm

        await converter._generate_converter_code.__wrapped__(
            converter, html, chart_images=[]
        ) if hasattr(converter._generate_converter_code, '__wrapped__') else None

        # Call the method the way convert_html_to_pptx would after extraction
        cleaned_html, content_images = converter._extract_and_save_content_images(
            html, str(tmp_path)
        )
        chart_images = list(content_images)
        code = await converter._generate_converter_code(cleaned_html, chart_images=chart_images)

        assert len(captured_prompts) >= 1
        last_prompt = captured_prompts[-1]
        assert "data:image" not in last_prompt
        assert "content_image_" in last_prompt

    @pytest.mark.asyncio
    async def test_multi_slide_prompt_contains_no_base64(self, tmp_path):
        """Multi-slide path: LLM prompt must not contain base64 data URIs."""
        converter = _make_converter()

        html = (
            f'<div class="slide"><h1>Title</h1>'
            f'<img src="data:image/png;base64,{TINY_PNG_B64}" alt="chart" />'
            f'</div>'
        )

        captured_prompts = []

        async def fake_call_llm(system_prompt, user_prompt):
            captured_prompts.append(user_prompt)
            return "def add_slide_to_presentation(prs, html_str, assets_dir): pass"

        converter._call_llm = fake_call_llm

        cleaned_html, content_images = converter._extract_and_save_content_images(
            html, str(tmp_path)
        )
        chart_images = list(content_images)
        await converter._generate_slide_adder_code(cleaned_html, chart_images=chart_images)

        assert len(captured_prompts) == 1
        assert "data:image" not in captured_prompts[0]
        assert "content_image_" in captured_prompts[0]

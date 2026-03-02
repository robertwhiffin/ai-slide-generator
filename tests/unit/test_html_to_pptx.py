"""Tests for PPTX export base64 image extraction and SVG-to-PNG conversion.

Regression tests ensuring base64 data URIs are extracted from HTML
before being sent to the LLM, preventing truncation of image data
and ensuring the LLM receives clean HTML with file references.

Also tests `_svg_to_png()` which converts SVG images to PNG using
svgpathtools + Pillow (pure Python) for PPTX compatibility.
"""

import base64
import io
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


# -----------------------------------------------------------------------
# SVG-to-PNG conversion
# -----------------------------------------------------------------------

# Minimal SVG with a single filled path (a 50x50 red square)
SIMPLE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<path d="M 10 10 L 60 10 L 60 60 L 10 60 Z" fill="#FF0000"/>'
    b'</svg>'
)

# SVG with a translate transform on the path
SVG_WITH_TRANSFORM = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
    b'<path d="M 0 0 L 50 0 L 50 50 L 0 50 Z" fill="#00FF00" transform="translate(10,20)"/>'
    b'</svg>'
)

# SVG with no filled paths (fill="none")
SVG_NO_FILL = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<path d="M 10 10 L 60 10 L 60 60 L 10 60 Z" fill="none"/>'
    b'</svg>'
)

# SVG with multiple paths of different colors
SVG_MULTI_PATH = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<path d="M 0 0 L 50 0 L 50 50 L 0 50 Z" fill="#FF0000"/>'
    b'<path d="M 50 50 L 100 50 L 100 100 L 50 100 Z" fill="#0000FF"/>'
    b'</svg>'
)


class TestSvgToPng:
    """Unit tests for _svg_to_png() pure-Python SVG-to-PNG conversion."""

    def test_returns_valid_png_bytes(self):
        """Output is valid PNG with correct header bytes."""
        png_bytes = HtmlToPptxConverterV3._svg_to_png(SIMPLE_SVG)
        assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n'

    def test_output_dimensions_match_svg(self):
        """PNG dimensions match the SVG width/height attributes."""
        from PIL import Image

        png_bytes = HtmlToPptxConverterV3._svg_to_png(SIMPLE_SVG)
        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (100, 100)

    def test_filled_path_produces_non_transparent_pixels(self):
        """A filled path produces visible (non-transparent) pixels in the output."""
        from PIL import Image

        png_bytes = HtmlToPptxConverterV3._svg_to_png(SIMPLE_SVG)
        img = Image.open(io.BytesIO(png_bytes))
        pixels = list(img.getdata())
        non_transparent = [p for p in pixels if p[3] > 0]
        assert len(non_transparent) > 0, "Expected non-transparent pixels from filled path"

    def test_red_fill_produces_red_pixels(self):
        """A #FF0000 filled path produces red pixels."""
        from PIL import Image

        png_bytes = HtmlToPptxConverterV3._svg_to_png(SIMPLE_SVG)
        img = Image.open(io.BytesIO(png_bytes))
        pixels = list(img.getdata())
        red_pixels = [p for p in pixels if p[0] == 255 and p[1] == 0 and p[2] == 0 and p[3] > 0]
        assert len(red_pixels) > 0, "Expected red pixels from #FF0000 fill"

    def test_no_fill_produces_transparent_image(self):
        """SVG with fill='none' produces an all-transparent PNG."""
        from PIL import Image

        png_bytes = HtmlToPptxConverterV3._svg_to_png(SVG_NO_FILL)
        img = Image.open(io.BytesIO(png_bytes))
        pixels = list(img.getdata())
        non_transparent = [p for p in pixels if p[3] > 0]
        assert len(non_transparent) == 0, "Expected fully transparent image for fill='none'"

    def test_translate_transform_applied(self):
        """A translate transform shifts the path position."""
        from PIL import Image

        png_bytes = HtmlToPptxConverterV3._svg_to_png(SVG_WITH_TRANSFORM)
        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (200, 200)
        # Pixel at (10, 20) should be within the translated green square
        pixel = img.getpixel((25, 35))  # Center of translated 50x50 square at (10,20)
        assert pixel[1] == 255 and pixel[3] > 0, "Expected green pixel in translated region"

    def test_multiple_paths_both_rendered(self):
        """Multiple paths with different fills both produce colored pixels."""
        from PIL import Image

        png_bytes = HtmlToPptxConverterV3._svg_to_png(SVG_MULTI_PATH)
        img = Image.open(io.BytesIO(png_bytes))
        pixels = list(img.getdata())
        red_pixels = [p for p in pixels if p[0] == 255 and p[1] == 0 and p[2] == 0 and p[3] > 0]
        blue_pixels = [p for p in pixels if p[0] == 0 and p[1] == 0 and p[2] == 255 and p[3] > 0]
        assert len(red_pixels) > 0, "Expected red pixels from first path"
        assert len(blue_pixels) > 0, "Expected blue pixels from second path"

    def test_large_dimensions_from_svg_attributes(self):
        """SVG with custom width/height produces matching PNG dimensions."""
        from PIL import Image

        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="300"><path d="M 0 0 L 100 0 L 100 100 L 0 100 Z" fill="#333333"/></svg>'
        png_bytes = HtmlToPptxConverterV3._svg_to_png(svg)
        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (500, 300)


class TestSvgContentImageExtraction:
    """Integration test: SVG base64 images are extracted, converted to PNG, and saved."""

    def test_svg_base64_extracted_and_converted_to_png(self, tmp_path):
        """An SVG data URI is extracted, converted to PNG, and saved as .png file."""
        converter = _make_converter()
        svg_b64 = base64.b64encode(SIMPLE_SVG).decode("ascii")
        html = f'<img src="data:image/svg+xml;base64,{svg_b64}" alt="icon" />'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert len(filenames) == 1
        assert filenames[0].endswith(".png")
        assert "data:image" not in cleaned
        # Verify the saved file is valid PNG (not raw SVG bytes)
        saved_bytes = (tmp_path / filenames[0]).read_bytes()
        assert saved_bytes[:8] == b'\x89PNG\r\n\x1a\n', "SVG should be converted to PNG"

"""Tests for HtmlToGoogleSlidesConverter and HtmlToPptxConverterV3 static/utility methods.

Covers the newly added helper functions in both converters:
- _extract_text / _extract_text_content (reasoning-model response parsing)
- _strip_fences / _strip_markdown_fences (code fence removal)
- _build_chart_note (chart image prompt builder)
- _prepare_code (code sanitiser / wrapper)
- _save_chart_images (base64 decoding)
- _svg_to_png (SVG-to-PNG conversion via svgpathtools + Pillow)
- _extract_and_save_content_images (base64 image extraction with SVG conversion)
"""

import base64
import io
import os
from pathlib import Path

import pytest

from src.services.html_to_google_slides import HtmlToGoogleSlidesConverter
from src.services.html_to_pptx import HtmlToPptxConverterV3


# -----------------------------------------------------------------------
# _extract_text / _extract_text_content
# -----------------------------------------------------------------------

class TestExtractText:
    """Both converters have near-identical extract helpers; test them together."""

    CASES = [
        # plain string
        ("hello world", "hello world"),
        # reasoning-model block list
        (
            [
                {"type": "reasoning", "text": "thinking..."},
                {"type": "text", "text": "final answer"},
            ],
            "final answer",
        ),
        # empty list — no text block found → fallback to str()
        ([], ""),
        # None
        (None, ""),
    ]

    @pytest.mark.parametrize("content,expected", CASES)
    def test_google_slides_extract_text(self, content, expected):
        assert HtmlToGoogleSlidesConverter._extract_text(content) == expected

    @pytest.mark.parametrize("content,expected", CASES)
    def test_pptx_extract_text_content(self, content, expected):
        assert HtmlToPptxConverterV3._extract_text_content(content) == expected


# -----------------------------------------------------------------------
# _strip_fences / _strip_markdown_fences
# -----------------------------------------------------------------------

class TestStripFences:
    """Markdown code fence removal."""

    CASES = [
        # ```python ... ```
        ("```python\nprint('hi')\n```", "print('hi')"),
        # ```Python (capital)
        ("```Python\nprint('hi')\n```", "print('hi')"),
        # bare ``` ... ```
        ("```\ncode here\n```", "code here"),
        # no fences → unchanged
        ("plain code", "plain code"),
        # leading/trailing whitespace inside fences
        ("```python\n  indented\n```", "indented"),
    ]

    @pytest.mark.parametrize("code,expected", CASES)
    def test_google_slides_strip_fences(self, code, expected):
        assert HtmlToGoogleSlidesConverter._strip_fences(code) == expected

    @pytest.mark.parametrize("code,expected", CASES)
    def test_pptx_strip_markdown_fences(self, code, expected):
        assert HtmlToPptxConverterV3._strip_markdown_fences(code) == expected


# -----------------------------------------------------------------------
# _build_chart_note
# -----------------------------------------------------------------------

class TestBuildChartNote:

    def test_no_chart_images(self):
        """Empty list produces a 'no chart images' note."""
        note = HtmlToGoogleSlidesConverter._build_chart_note(None, [])
        assert "No chart images" in note

    def test_with_chart_images(self):
        """File names are listed in the note."""
        note = HtmlToGoogleSlidesConverter._build_chart_note(None, ["chart_0.png", "chart_trend.png"])
        assert "chart_0.png" in note
        assert "chart_trend.png" in note
        assert "MUST use" in note


# -----------------------------------------------------------------------
# _prepare_code
# -----------------------------------------------------------------------

class TestPrepareCode:
    """Code sanitiser for generated Google Slides Python code."""

    def test_wraps_bare_code(self):
        """Bare code without function def gets wrapped."""
        code = "requests = []\nslides_service.presentations().batchUpdate(...)"
        result = HtmlToGoogleSlidesConverter._prepare_code(code)
        assert "def add_slide_to_presentation" in result
        assert "import os" in result

    def test_preserves_existing_function(self):
        """Code that already has the function is preserved."""
        code = (
            "import os\n"
            "def add_slide_to_presentation(slides_service, drive_service, "
            "presentation_id, page_id, html_str, assets_dir):\n"
            "    pass\n"
        )
        result = HtmlToGoogleSlidesConverter._prepare_code(code)
        assert "def add_slide_to_presentation" in result
        assert result.count("def add_slide_to_presentation") == 1

    def test_replaces_smart_quotes(self):
        """Smart/curly quotes are replaced with straight quotes."""
        code = (
            "def add_slide_to_presentation(a,b,c,d,e,f):\n"
            "    x = \u2018hello\u2019\n"
            '    y = \u201cfoo\u201d\n'
        )
        result = HtmlToGoogleSlidesConverter._prepare_code(code)
        assert "\u2018" not in result
        assert "\u2019" not in result
        assert "\u201c" not in result
        assert "\u201d" not in result


# -----------------------------------------------------------------------
# _save_chart_images
# -----------------------------------------------------------------------

class TestSaveChartImages:

    def test_saves_base64_images(self, tmp_path):
        """Base64-encoded PNGs are decoded and saved to assets_dir."""
        # Minimal 1×1 red PNG
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        b64 = base64.b64encode(png_bytes).decode()
        chart_dict = {"chart_0": f"data:image/png;base64,{b64}"}

        converter = HtmlToGoogleSlidesConverter.__new__(HtmlToGoogleSlidesConverter)
        saved = converter._save_chart_images(chart_dict, str(tmp_path))

        assert len(saved) == 1
        assert (tmp_path / saved[0]).exists()
        assert (tmp_path / saved[0]).stat().st_size > 0

    def test_invalid_base64_skipped(self, tmp_path):
        """Invalid base64 data does not crash; the file is skipped."""
        converter = HtmlToGoogleSlidesConverter.__new__(HtmlToGoogleSlidesConverter)
        saved = converter._save_chart_images({"bad": "not-valid-base64!!!"}, str(tmp_path))
        assert saved == []


# -----------------------------------------------------------------------
# _svg_to_png (Google Slides converter)
# -----------------------------------------------------------------------

# Minimal SVG with a single filled path
SIMPLE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<path d="M 10 10 L 60 10 L 60 60 L 10 60 Z" fill="#FF0000"/>'
    b'</svg>'
)

# A minimal valid PNG (1x1 transparent pixel)
TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYPgPAAEDAQAIicLsAAAAASUVORK5CYII="
)
TINY_PNG_B64 = base64.b64encode(TINY_PNG_BYTES).decode("ascii")


class TestGSlidesSvgToPng:
    """Unit tests for Google Slides converter _svg_to_png()."""

    def test_returns_valid_png(self):
        """Output is valid PNG bytes."""
        png_bytes = HtmlToGoogleSlidesConverter._svg_to_png(SIMPLE_SVG)
        assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n'

    def test_output_dimensions_match_svg(self):
        """PNG dimensions match SVG width/height attributes."""
        from PIL import Image

        png_bytes = HtmlToGoogleSlidesConverter._svg_to_png(SIMPLE_SVG)
        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (100, 100)

    def test_filled_path_has_visible_pixels(self):
        """Filled path produces non-transparent pixels."""
        from PIL import Image

        png_bytes = HtmlToGoogleSlidesConverter._svg_to_png(SIMPLE_SVG)
        img = Image.open(io.BytesIO(png_bytes))
        pixels = list(img.getdata())
        non_transparent = [p for p in pixels if p[3] > 0]
        assert len(non_transparent) > 0

    def test_no_fill_produces_transparent(self):
        """SVG with fill='none' produces a fully transparent PNG."""
        from PIL import Image

        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            b'<path d="M 0 0 L 50 0 L 50 50 L 0 50 Z" fill="none"/>'
            b'</svg>'
        )
        png_bytes = HtmlToGoogleSlidesConverter._svg_to_png(svg)
        img = Image.open(io.BytesIO(png_bytes))
        pixels = list(img.getdata())
        assert all(p[3] == 0 for p in pixels)


# -----------------------------------------------------------------------
# _extract_and_save_content_images (Google Slides converter)
# -----------------------------------------------------------------------

def _make_gslides_converter():
    """Create a Google Slides converter with mocked dependencies."""
    converter = HtmlToGoogleSlidesConverter.__new__(HtmlToGoogleSlidesConverter)
    return converter


class TestGSlidesExtractContentImages:
    """Tests for Google Slides converter content image extraction."""

    def test_extracts_png_image(self, tmp_path):
        """A base64 PNG is extracted, saved, and replaced with filename."""
        converter = _make_gslides_converter()
        html = f'<img src="data:image/png;base64,{TINY_PNG_B64}" alt="logo" />'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert len(filenames) == 1
        assert filenames[0].endswith(".png")
        assert "data:image" not in cleaned
        assert (tmp_path / filenames[0]).exists()

    def test_extracts_svg_and_converts_to_png(self, tmp_path):
        """An SVG data URI is extracted, converted to PNG, and saved."""
        converter = _make_gslides_converter()
        svg_b64 = base64.b64encode(SIMPLE_SVG).decode("ascii")
        html = f'<img src="data:image/svg+xml;base64,{svg_b64}" />'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert len(filenames) == 1
        assert filenames[0].endswith(".png")
        saved_bytes = (tmp_path / filenames[0]).read_bytes()
        assert saved_bytes[:8] == b'\x89PNG\r\n\x1a\n', "SVG should be converted to PNG"

    def test_no_images_returns_unchanged(self, tmp_path):
        """HTML without base64 images passes through unchanged."""
        converter = _make_gslides_converter()
        html = "<div>No images</div>"

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert cleaned == html
        assert filenames == []

    def test_preserves_non_base64_img_tags(self, tmp_path):
        """Non-base64 img tags are not modified."""
        converter = _make_gslides_converter()
        html = '<img src="chart_0.png" />'

        cleaned, filenames = converter._extract_and_save_content_images(html, str(tmp_path))

        assert cleaned == html
        assert filenames == []

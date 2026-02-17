"""Tests for HtmlToGoogleSlidesConverter and HtmlToPptxConverterV3 static/utility methods.

Covers the newly added helper functions in both converters:
- _extract_text / _extract_text_content (reasoning-model response parsing)
- _strip_fences / _strip_markdown_fences (code fence removal)
- _build_chart_note (chart image prompt builder)
- _prepare_code (code sanitiser / wrapper)
- _save_chart_images (base64 decoding)
"""

import base64
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

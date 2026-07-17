# tests/unit/test_codeprep.py
"""Tests for the dependency-light code-prep module (SDR-4437 PR-5, Task 1B).

codeprep is imported by the in-jail runners; it must be stdlib-only so the
sandboxed child never imports the Databricks SDK / Google / pptx graphs.
"""

import ast
import subprocess
import sys
import textwrap

from src.services.converter_jail.codeprep import (
    _fix_apostrophe_strings,
    prepare_requests_code,
    sanitize_code,
)


class TestSanitizeCode:
    def test_fixes_smart_quotes(self):
        code = "x = ‘hello’\ny = “world”\n"
        fixed = sanitize_code(code)
        assert fixed == "x = 'hello'\ny = \"world\"\n"
        ast.parse(fixed)

    def test_fixes_apostrophe_in_single_quoted_literal(self):
        code = "title = 'Anthony's workflow'\n"
        fixed = sanitize_code(code)
        ast.parse(fixed)  # must be parseable after the fix

    def test_replaces_dashes(self):
        assert sanitize_code("a = 1 — 2 – 3") == "a = 1 - 2 - 3"


class TestFixApostropheStrings:
    def test_round_trips_contraction_literal(self):
        code = "msg = 'We don't do that'\n"
        fixed = _fix_apostrophe_strings(code)
        ast.parse(fixed)
        assert '"We don\'t do that"' in fixed

    def test_valid_code_unchanged(self):
        code = "x = 'fine'\n"
        assert _fix_apostrophe_strings(code) == code


class TestPrepareRequestsCode:
    def test_wraps_bare_code_into_build_slide_requests(self):
        code = "requests = []\nrequests.append({'createShape': {}})\n"
        prepared = prepare_requests_code(code)
        assert "def build_slide_requests(html_str, assets_dir, page_id):" in prepared
        assert "return requests" in prepared
        ast.parse(prepared)

    def test_rewrites_paragraph_style_key(self):
        code = (
            "def build_slide_requests(html_str, assets_dir, page_id):\n"
            "    return [{'updateParagraphStyle': {'paragraphStyle': {}}}]\n"
        )
        prepared = prepare_requests_code(code)
        assert "'paragraphStyle'" not in prepared
        assert "'style'" in prepared

    def test_existing_function_not_rewrapped(self):
        code = (
            "def build_slide_requests(html_str, assets_dir, page_id):\n"
            "    return []\n"
        )
        prepared = prepare_requests_code(code)
        assert prepared.count("def build_slide_requests") == 1


class TestImportLight:
    def test_codeprep_pulls_no_heavy_modules(self):
        """Importing codeprep the way the jail child does (as a sibling
        top-level module — NOT via the src.services package, whose __init__
        eagerly imports the SDK/agent graph) must not load the Databricks SDK,
        Google client libs, bs4, or pptx."""
        jail_dir = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "src" / "services" / "converter_jail"
        )
        probe = textwrap.dedent(
            """
            import sys
            sys.path.insert(0, {jail_dir!r})
            import codeprep  # noqa: F401
            import protocol  # noqa: F401
            heavy = [m for m in sys.modules
                     if m.split(".")[0] in {{"databricks", "google",
                                             "googleapiclient", "bs4", "pptx",
                                             "src"}}]
            print(",".join(sorted(heavy)))
            """
        ).format(jail_dir=str(jail_dir))
        out = subprocess.run(
            [sys.executable, "-I", "-c", probe],
            capture_output=True, text=True, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "", f"heavy modules loaded: {out.stdout}"

# tests/unit/test_converter_jail.py
"""Unit tests for the converter subprocess jail (SDR-4437 PR-5)."""

import pytest

from src.services.converter_jail import protocol
from src.services.converter_jail import ast_guard
from src.services.converter_jail.ast_guard import DisallowedImport


class TestProgressProtocol:
    def test_round_trip(self):
        line = protocol.encode_progress(3, 7, "Building slide 3/7")
        assert line.startswith(protocol.PROGRESS_PREFIX)
        assert line.endswith("\n")
        assert protocol.decode_progress(line) == (3, 7, "Building slide 3/7")

    def test_non_progress_line_returns_none(self):
        assert protocol.decode_progress("some generated print output\n") is None
        assert protocol.decode_progress("") is None


class TestAstGuard:
    def test_allows_whitelisted_imports(self):
        code = (
            "import os\n"
            "from pptx.util import Inches\n"
            "from PIL import Image\n"
            "import lxml.etree\n"
        )
        ast_guard.check_imports(code)  # must not raise

    def test_allows_common_harmless_stdlib(self):
        # Guard-failure downgrades a slide to a blank placeholder (Tasks 4/6),
        # so benign stdlib the LLM emits unprompted must be allowed.
        code = (
            "import sys\n"
            "import time\n"
            "from typing import List\n"
            "from functools import lru_cache\n"
            "import random\n"
        )
        ast_guard.check_imports(code)  # must not raise

    def test_rejects_socket(self):
        with pytest.raises(DisallowedImport):
            ast_guard.check_imports("import socket\n")

    def test_rejects_subprocess_from_import(self):
        with pytest.raises(DisallowedImport):
            ast_guard.check_imports("from subprocess import run\n")

    def test_rejects_dotted_disallowed_root(self):
        with pytest.raises(DisallowedImport):
            ast_guard.check_imports("import requests.sessions\n")

    def test_syntax_error_propagates(self):
        with pytest.raises(SyntaxError):
            ast_guard.check_imports("def broken(:\n")

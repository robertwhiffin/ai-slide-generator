# tests/unit/test_converter_jail.py
"""Unit tests for the converter subprocess jail (SDR-4437 PR-5)."""

import sys
import textwrap
from pathlib import Path

import pytest

from src.services.converter_jail import protocol
from src.services.converter_jail import ast_guard
from src.services.converter_jail.ast_guard import DisallowedImport
from src.services.converter_jail import jail


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


class TestScrubbedEnv:
    def test_only_whitelist_survives(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_TOKEN", "secret-token")
        monkeypatch.setenv("DATABRICKS_HOST", "https://example")
        monkeypatch.setenv("PGPASSWORD", "lakebase-pw")
        monkeypatch.setenv("TELLR_FERNET_KEY", "fernet-secret")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        env = jail.build_scrubbed_env()
        assert env.get("PATH") == "/usr/bin:/bin"
        assert "DATABRICKS_TOKEN" not in env
        assert "DATABRICKS_HOST" not in env
        assert "PGPASSWORD" not in env
        assert "TELLR_FERNET_KEY" not in env
        # HOME/TMPDIR point at a fresh dir, not the real home
        assert env["HOME"] == env["TMPDIR"]
        assert Path(env["HOME"]).is_dir()

    def test_env_has_no_databricks_keys_at_all(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "x")
        monkeypatch.setenv("DATABRICKS_CLIENT_ID", "y")
        env = jail.build_scrubbed_env()
        assert not any(k.startswith("DATABRICKS_") for k in env)


class TestNetnsProbe:
    def test_probe_never_raises(self):
        # Must return a bool on any platform; on macOS this is False.
        assert isinstance(jail.netns_available(), bool)


class TestWallClockTimeout:
    def test_runaway_child_is_killed(self, tmp_path):
        # A minimal runner file that sleeps forever; the jail must kill it.
        runner = tmp_path / "sleeper.py"
        runner.write_text(textwrap.dedent("""
            import time
            time.sleep(3600)
        """))
        result = jail._spawn(
            runner_file=str(runner),
            argv=[],
            timeout_s=1.0,
            progress_cb=None,
        )
        assert result.timed_out is True


class TestRlimitsEnforced:
    @pytest.mark.skipif(
        sys.platform == "darwin",
        reason="RLIMIT_AS not enforced on macOS; verified on Linux Apps runtime",
    )
    def test_address_space_limit_kills_allocator(self, tmp_path):
        # Child tries to allocate far beyond RLIMIT_AS -> MemoryError / kill.
        runner = tmp_path / "hog.py"
        runner.write_text(textwrap.dedent("""
            x = bytearray(4 * 1024 * 1024 * 1024)  # 4 GiB > cap
        """))
        result = jail._spawn(
            runner_file=str(runner),
            argv=[],
            timeout_s=30.0,
            progress_cb=None,
            limits=jail.ResourceLimits(address_space_bytes=512 * 1024 * 1024),
        )
        assert result.timed_out is False
        assert result.returncode != 0


class TestEscapeAttempt:
    def test_generated_style_env_read_sees_no_secrets(self, tmp_path, monkeypatch):
        # Simulate hostile code trying to read a credential from the env.
        monkeypatch.setenv("DATABRICKS_TOKEN", "THE-SECRET")
        out = tmp_path / "leak.txt"
        runner = tmp_path / "exfil.py"
        runner.write_text(textwrap.dedent(f"""
            import os
            open({str(out)!r}, "w").write(os.environ.get("DATABRICKS_TOKEN", "ABSENT"))
        """))
        result = jail._spawn(
            runner_file=str(runner), argv=[], timeout_s=30.0, progress_cb=None,
        )
        assert result.returncode == 0
        assert out.read_text() == "ABSENT"


class TestNoInProcessExecAnywhere:
    """SDR-4437 HIGH-5 gate: neither export service execs generated code in-process."""

    def test_no_exec_module_in_either_service(self):
        import inspect
        from src.services import html_to_pptx, html_to_google_slides
        for mod in (html_to_pptx, html_to_google_slides):
            src = inspect.getsource(mod)
            assert "exec_module" not in src, f"{mod.__name__} still execs in-process"

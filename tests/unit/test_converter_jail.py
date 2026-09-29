# tests/unit/test_converter_jail.py
"""Unit tests for the converter subprocess jail (SDR-4437 PR-5)."""

import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.services.converter_jail import ast_guard, jail, protocol
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


class TestNetworkIsolationFallback:
    def test_strip_sensitive_env_removes_credential_patterns(self):
        env = {
            "DATABRICKS_TOKEN": "databricks-token",
            "DATABRICKS_HOST": "https://databricks.example",
            "GITHUB_TOKEN": "github-token",
            "CLIENT_SECRET": "client-secret",
            "FERNET_KEY": "fernet-key",
            "DB_PASSWORD": "database-password",
            "GOOGLE_CREDENTIALS": "google-credentials",
            "OPENAI_API_KEY": "openai-key",
            "LEGACY_APIKEY": "legacy-api-key",
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
        }
        scrubbed = jail.strip_sensitive_env(env)
        assert scrubbed == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}

    def test_spawn_strips_credentials_when_netns_is_unavailable(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(jail, "_netns_cache", False)
        child_home = tmp_path / "child-home"
        child_home.mkdir()

        def _unsafe_env():
            return {
                "DATABRICKS_TOKEN": "databricks-token",
                "DATABRICKS_HOST": "https://databricks.example",
                "GITHUB_TOKEN": "github-token",
                "CLIENT_SECRET": "client-secret",
                "FERNET_KEY": "fernet-key",
                "DB_PASSWORD": "database-password",
                "OPENAI_API_KEY": "openai-key",
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "HOME": str(child_home),
                "TMPDIR": str(child_home),
                "PYTHONHASHSEED": "0",
            }

        monkeypatch.setattr(jail, "build_scrubbed_env", _unsafe_env)
        env_keys_path = tmp_path / "child-env.txt"
        runner = tmp_path / "env_dump.py"
        runner.write_text(
            "import os, sys\n"
            "open(sys.argv[2], 'w').write('\\n'.join(sorted(os.environ)))\n"
        )

        result = jail._spawn(
            runner_file=str(runner),
            argv=[str(env_keys_path)],
            timeout_s=30.0,
            progress_cb=None,
        )

        assert result.returncode == 0
        child_keys = set(env_keys_path.read_text().splitlines())
        assert "DATABRICKS_TOKEN" not in child_keys
        assert "DATABRICKS_HOST" not in child_keys
        assert "GITHUB_TOKEN" not in child_keys
        assert "CLIENT_SECRET" not in child_keys
        assert "FERNET_KEY" not in child_keys
        assert "DB_PASSWORD" not in child_keys
        assert "OPENAI_API_KEY" not in child_keys
        assert {"PATH", "HOME", "TMPDIR"} <= child_keys

    def test_netns_failure_logs_explicit_fallback_warning(self, caplog, monkeypatch):
        monkeypatch.setattr(jail, "_netns_cache", None)
        monkeypatch.setattr(jail.shutil, "which", lambda _: "/usr/bin/unshare")
        monkeypatch.setattr(
            jail.subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
        )

        with caplog.at_level(logging.WARNING, logger=jail.logger.name):
            assert jail.netns_available() is False

        assert "Network isolation failed" in caplog.text
        assert "credential-free child environment" in caplog.text
        assert "egress remains possible" in caplog.text


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


class TestJailHomeCleanup:
    """SDR-4437 PR-5 MEDIUM: the per-launch HOME/TMPDIR temp dir must be
    removed on every exit path (no per-deck disk leak / DoS)."""

    def test_home_dir_removed_after_success(self, tmp_path, monkeypatch):
        captured = {}
        real_build = jail.build_scrubbed_env

        def _spy():
            env = real_build()
            captured["home"] = env["HOME"]
            return env

        monkeypatch.setattr(jail, "build_scrubbed_env", _spy)

        runner = tmp_path / "noop.py"
        runner.write_text("pass\n")
        result = jail._spawn(
            runner_file=str(runner), argv=[], timeout_s=30.0, progress_cb=None,
        )
        assert result.timed_out is False
        assert not Path(captured["home"]).exists()  # cleaned up

    def test_home_dir_removed_after_timeout(self, tmp_path, monkeypatch):
        captured = {}
        real_build = jail.build_scrubbed_env

        def _spy():
            env = real_build()
            captured["home"] = env["HOME"]
            return env

        monkeypatch.setattr(jail, "build_scrubbed_env", _spy)

        runner = tmp_path / "sleeper.py"
        runner.write_text(textwrap.dedent("""
            import time
            time.sleep(3600)
        """))
        result = jail._spawn(
            runner_file=str(runner), argv=[], timeout_s=1.0, progress_cb=None,
        )
        assert result.timed_out is True
        assert not Path(captured["home"]).exists()  # cleaned up even on kill


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

        from src.services import html_to_google_slides, html_to_pptx
        for mod in (html_to_pptx, html_to_google_slides):
            src = inspect.getsource(mod)
            assert "exec_module" not in src, f"{mod.__name__} still execs in-process"

"""Tests for scripts/verify_app_wheel.py, the publish guard for the app wheel's export sidecar.

publish.yml and publish-dev.yml run it on the built databricks-tellr-app wheel.
The export loads its sidecar's source files only when it runs, so a file the
wheel lacks passes every other check and fails every export on the deployed
app. The guard walks the export's module graph inside the wheel.

Interface under test:

    SIDECAR_SOURCES: tuple[str, ...]   # the files the export is known to load
    sidecar_graph(read) -> (loaded, missing)
    check_wheel(wheel, *, min_wheel_mb=MIN_WHEEL_MB) -> list[str]   # [] means OK
    main(argv=None) -> int   # prints each problem to stderr; 1 if any, else 0

The wheels here are built from the real sidecar directory's files, with
stand-in tarballs, so the graph they hold is the one the export loads.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.verify_app_wheel import (
    BOOTSTRAP_FILES,
    SIDECAR_DIR_IN_WHEEL,
    SIDECAR_SOURCES,
    check_wheel,
    main,
    sidecar_graph,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_app_wheel.py"
SIDECAR_DIR = REPO_ROOT / "services" / "pptx-emit-huashu"


def _read_sidecar(name: str) -> str | None:
    path = SIDECAR_DIR / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _wheel(
    tmp_path: Path,
    *,
    leave_out: tuple[str, ...] = (),
    replace: dict[str, str] | None = None,
) -> Path:
    """An app wheel holding the sidecar the export loads, from the real source files.

    The tarballs are stand-ins: the size floor is checked on its own.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "databricks_tellr_app-0.0.0-py3-none-any.whl"
    sources = {name: _read_sidecar(name) for name in SIDECAR_SOURCES}
    sources.update(replace or {})
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("databricks_tellr_app/__init__.py", "")
        for name in BOOTSTRAP_FILES:
            if name not in leave_out:
                archive.writestr(f"{SIDECAR_DIR_IN_WHEEL}/{name}", b"stand-in")
        for name, source in sources.items():
            if name not in leave_out:
                archive.writestr(f"{SIDECAR_DIR_IN_WHEEL}/{name}", source)
    return wheel


def test_the_known_sources_are_the_graph_the_sidecar_loads_today() -> None:
    """SIDECAR_SOURCES is what the graph reaches in services/pptx-emit-huashu/, nothing missing."""
    loaded, missing = sidecar_graph(_read_sidecar)
    assert missing == []
    assert loaded == sorted(SIDECAR_SOURCES)


def test_the_graph_reaches_the_files_the_page_and_node_sides_compose() -> None:
    """The files the export composes into its page sources, or reads in Node, are in the graph."""
    loaded, _ = sidecar_graph(_read_sidecar)
    for name in (
        "pseudo.mjs",
        "gradient.mjs",
        "log_line.cjs",
        "model_check.cjs",
        "text_check.cjs",
        "snapshot_table.mjs",
        "emit_table.cjs",
        "capture.cjs",
    ):
        assert name in loaded, name


def test_a_wheel_with_the_whole_sidecar_passes(tmp_path: Path) -> None:
    assert check_wheel(_wheel(tmp_path), min_wheel_mb=0) == []


@pytest.mark.parametrize("name", ["capture.cjs", "snapshot_table.mjs", "log_line.cjs"])
def test_a_wheel_without_a_source_the_export_loads_fails_naming_it(
    tmp_path: Path, name: str
) -> None:
    problems = check_wheel(_wheel(tmp_path, leave_out=(name,)), min_wheel_mb=0)
    assert problems, f"a wheel without {name} passed"
    assert any(name in problem for problem in problems), problems


def test_a_file_the_graph_reaches_beyond_the_known_sources_is_checked_too(
    tmp_path: Path,
) -> None:
    """A module the export gains, not yet in SIDECAR_SOURCES, still has to be in the wheel."""
    render_slide = _read_sidecar("render_slide.cjs")
    assert render_slide is not None
    wheel = _wheel(
        tmp_path,
        replace={
            "render_slide.cjs": "const { added } = require('./added_module.cjs');\n" + render_slide
        },
    )
    problems = check_wheel(wheel, min_wheel_mb=0)
    assert problems == [
        "the wheel lacks the sidecar source added_module.cjs (loaded by render_slide.cjs)"
    ]


@pytest.mark.parametrize("name", BOOTSTRAP_FILES)
def test_a_wheel_without_a_bootstrap_file_fails(tmp_path: Path, name: str) -> None:
    problems = check_wheel(_wheel(tmp_path, leave_out=(name,)), min_wheel_mb=0)
    assert problems == [f"the wheel lacks the sidecar's {name}"]


def test_a_wheel_under_the_size_floor_fails(tmp_path: Path) -> None:
    problems = check_wheel(_wheel(tmp_path))
    assert len(problems) == 1 and "under the 25 MB floor" in problems[0], problems


def test_a_source_the_graph_no_longer_reaches_is_named(tmp_path: Path) -> None:
    """A file still listed but no longer loaded says so, rather than passing in silence."""
    emit_model = _read_sidecar("emit_model.cjs")
    assert emit_model is not None
    unlinked = emit_model.replace("require('./emit_table.cjs')", "({ emitTable: null })")
    assert unlinked != emit_model, "fixture drift: emit_model.cjs no longer requires emit_table.cjs"
    problems = check_wheel(_wheel(tmp_path, replace={"emit_model.cjs": unlinked}), min_wheel_mb=0)
    assert len(problems) == 1 and "no longer reaches emit_table.cjs" in problems[0], problems


def test_main_exits_one_and_prints_each_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wheel = _wheel(tmp_path, leave_out=("capture.cjs",))
    assert main([str(wheel.parent), "--min-wheel-mb", "0"]) == 1
    assert "capture.cjs" in capsys.readouterr().err


def test_main_exits_zero_on_a_whole_wheel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wheel = _wheel(tmp_path)
    assert main([str(wheel.parent), "--min-wheel-mb", "0"]) == 0
    assert "Verify gate passed" in capsys.readouterr().out


def test_main_wants_exactly_one_wheel(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert main([str(tmp_path / "empty")]) == 1


def test_the_workflows_run_it_on_the_app_wheel() -> None:
    """publish.yml and publish-dev.yml both run the guard on the built app wheel."""
    for workflow in ("publish.yml", "publish-dev.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "scripts/verify_app_wheel.py packages/databricks-tellr-app/dist" in text, workflow


def test_it_runs_as_a_script_on_the_standard_library_alone(tmp_path: Path) -> None:
    """As the build job runs it: python -I, no project on the path."""
    wheel = _wheel(tmp_path)
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(wheel.parent), "--min-wheel-mb", "0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

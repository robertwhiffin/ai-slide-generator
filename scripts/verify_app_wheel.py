"""Publish guard for the databricks-tellr-app wheel's PPTX export sidecar.

publish.yml and publish-dev.yml run this once the app wheel is built, before
anything is uploaded:

    python scripts/verify_app_wheel.py packages/databricks-tellr-app/dist

It refuses the build unless the one wheel in that directory is at least
``MIN_WHEEL_MB`` (below it the bootstrap tarballs are truncated) and holds,
under ``databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/``:

* the bootstrap tarballs (node_modules, the system libraries and the font
  bundle), and ``setup.sh``, which extracts them at boot;
* every sidecar source file the export loads. That is ``emit_deck.mjs``, which
  ``src/services/pptx_from_html_huashu.py`` runs, and each file it requires or
  imports, transitively, read from the wheel's own copies. The export loads them
  only when it runs, so a missing one passes the build and fails every export on
  the deployed app;
* each of ``SIDECAR_SOURCES``, the files the export is known to load, so a read
  of the graph that found nothing cannot pass.

Standard library only: the build job installs nothing but ``build``.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

SIDECAR_DIR_IN_WHEEL = "databricks_tellr_app/_assets/sidecars/pptx-emit-huashu"

# What the deployed app's boot runs before any export: setup.sh, and the tarballs it extracts.
# fonts-liberation.tar.gz is the font bundle the sidecar's Chromium lays text out in.
BOOTSTRAP_FILES = (
    "node_modules.tar.gz",
    "sys-libs-bullseye.tar.gz",
    "fonts-liberation.tar.gz",
    "setup.sh",
)

# Where the export's module graph starts: the script the wrapper runs.
GRAPH_ROOT = "emit_deck.mjs"

# Every file the export loads, as the graph reads the sidecar directory today.
# tests/unit/test_verify_app_wheel_huashu.py keeps this list equal to that reading.
SIDECAR_SOURCES = (
    "capture.cjs",
    "coverage_font.mjs",
    "dom_access.mjs",
    "emit_deck.mjs",
    "emit_dotted.cjs",
    "emit_model.cjs",
    "emit_rewrite.cjs",
    "emit_table.cjs",
    "emit_text.cjs",
    "emit_typography.cjs",
    "gradient.mjs",
    "log_line.cjs",
    "model_check.cjs",
    "preprocess.mjs",
    "pseudo.mjs",
    "render_slide.cjs",
    "request_guard.cjs",
    "snapshot.mjs",
    "snapshot_borders.mjs",
    "snapshot_table.mjs",
    "snapshot_text.mjs",
    "snapshot_text_ellipsis.mjs",
    "snapshot_text_markers.mjs",
    "snapshot_text_metrics.mjs",
    "snapshot_text_turned.mjs",
    "text_check.cjs",
    "units.cjs",
)

MIN_WHEEL_MB = 25

# A relative module specifier, written each way the sidecar loads a file:
# require('./x'), import('./x'), import ... from './x' and import './x'. A package
# (playwright, pptxgenjs, node:fs) is named without a leading dot, so it is no
# sidecar file.
_RELATIVE_SPECIFIER = re.compile(
    r"""(?:\brequire\s*\(\s*|\bimport\s*\(\s*|\bfrom\s+|\bimport\s+)(['"])(\.\.?/[^'"]+)\1"""
)


def relative_specifiers(source: str) -> list[str]:
    """Every relative module specifier ``source`` names, in order."""
    return [match.group(2) for match in _RELATIVE_SPECIFIER.finditer(source)]


def sidecar_graph(read: Callable[[str], str | None]) -> tuple[list[str], list[str]]:
    """The export's module graph over one sidecar directory, from ``GRAPH_ROOT``.

    ``read(name)`` is the text of the sidecar file ``name``, a path relative to
    the sidecar directory, or None when there is none. Returns ``(loaded,
    missing)``, both sorted: every file the graph reaches that is there, and
    every file it names that is not, each as ``"<file> (loaded by <file>)"``.
    """
    loaded: set[str] = set()
    missing: set[str] = set()
    pending = [(GRAPH_ROOT, "pptx_from_html_huashu.py")]
    while pending:
        name, loaded_by = pending.pop()
        if name in loaded:
            continue
        source = read(name)
        if source is None:
            missing.add(f"{name} (loaded by {loaded_by})")
            continue
        loaded.add(name)
        directory = posixpath.dirname(name)
        for specifier in relative_specifiers(source):
            pending.append((posixpath.normpath(posixpath.join(directory, specifier)), name))
    return sorted(loaded), sorted(missing)


def check_wheel(wheel: Path, *, min_wheel_mb: float = MIN_WHEEL_MB) -> list[str]:
    """What the wheel lacks, one message each: [] when it holds all the export needs."""
    problems: list[str] = []
    size_mb = wheel.stat().st_size / (1024 * 1024)
    if size_mb < min_wheel_mb:
        problems.append(f"the wheel is {size_mb:.1f} MB, under the {min_wheel_mb} MB floor")
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())

        def read(name: str) -> str | None:
            member = f"{SIDECAR_DIR_IN_WHEEL}/{name}"
            if member not in members:
                return None
            return archive.read(member).decode("utf-8", errors="replace")

        for name in BOOTSTRAP_FILES:
            if f"{SIDECAR_DIR_IN_WHEEL}/{name}" not in members:
                problems.append(f"the wheel lacks the sidecar's {name}")
        loaded, missing = sidecar_graph(read)
    problems.extend(f"the wheel lacks the sidecar source {entry}" for entry in missing)
    for name in SIDECAR_SOURCES:
        if name in loaded or any(entry.startswith(f"{name} ") for entry in missing):
            continue
        if f"{SIDECAR_DIR_IN_WHEEL}/{name}" not in members:
            problems.append(f"the wheel lacks the sidecar source {name}")
        elif not missing:
            # With a file missing, what it would have loaded is unread, not retired.
            problems.append(
                f"the export's module graph no longer reaches {name}: if it was retired, "
                "take it out of SIDECAR_SOURCES"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "dist_dir", type=Path, help="the directory python -m build wrote the app wheel to"
    )
    parser.add_argument("--min-wheel-mb", type=float, default=MIN_WHEEL_MB)
    args = parser.parse_args(argv)
    wheels = sorted(args.dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        print(
            f"ERROR: expected exactly one wheel in {args.dist_dir}, found: {wheels}",
            file=sys.stderr,
        )
        return 1
    wheel = wheels[0]
    print(f"Wheel: {wheel} ({wheel.stat().st_size / (1024 * 1024):.1f} MB)")
    problems = check_wheel(wheel, min_wheel_mb=args.min_wheel_mb)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"Verify gate passed: the {len(SIDECAR_SOURCES)} sidecar sources the export loads "
        "and the bootstrap files are in the wheel."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

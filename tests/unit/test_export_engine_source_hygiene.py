"""The export engine's sources say what the code does, in characters a reader can see.

* No source holds a raw invisible character (a format character, a combining
  mark, a control character but the tab): a regular expression or a string that
  needs one writes its escape (``\\u200D``), so a review sees what it matches.
* No source cites the plan the engine was built from (a task, a phase, a fix
  round): a measurement is cited by its ``scripts/export_fidelity/CALIBRATION.md``
  ID, which outlives the plan.

The sources are the sidecar's own modules, the fidelity harness's and the font
bundle's scripts, the Python that drives them, and the export's tests.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_GLOBS = (
    "services/pptx-emit-huashu/*.mjs",
    "services/pptx-emit-huashu/*.cjs",
    "services/pptx-emit-huashu/*.sh",
    "scripts/export_fidelity/*.py",
    "scripts/export_fidelity/*.cjs",
    "scripts/export_fidelity/*.mjs",
    "scripts/sidecar_fonts/*",
    "src/services/pptx_from_html_huashu.py",
    "src/api/routes/export.py",
    "src/api/routes/google_slides.py",
    "src/utils/html_safety.py",
    "tests/fixtures/export_snapshot_support.py",
    "tests/fixtures/export_snapshot/*.cjs",
    "tests/unit/test_export*.py",
    "tests/unit/test_huashu*.py",
    "tests/unit/test_pptx_from_html_huashu*.py",
)
# The Unicode categories of characters that draw nothing, or draw on the one before.
INVISIBLE_CATEGORIES = {"Cf", "Mn", "Me", "Cc", "Zl", "Zp"}
VISIBLE_CONTROLS = {"\t"}
# How a comment cites the plan rather than a measurement.
PLAN_REFERENCE = re.compile(r"\bTask \d+|\bfix round\b|\bPhase [A-C]\b|\b[Ff]inal fix\b")


def _sources() -> list[Path]:
    paths = {
        path
        for pattern in SOURCE_GLOBS
        for path in REPO_ROOT.glob(pattern)
        if path.is_file() and path.suffix in {".mjs", ".cjs", ".py", ".sh", ".in"}
    }
    return sorted(paths)


SOURCES = _sources()


def test_the_sources_are_found() -> None:
    names = {path.name for path in SOURCES}
    assert {"snapshot_text_metrics.mjs", "run.py", "fonts.conf.in", "text_check.cjs"} <= names


@pytest.mark.parametrize("path", SOURCES, ids=[str(path.relative_to(REPO_ROOT)) for path in SOURCES])
def test_no_source_holds_a_raw_invisible_character(path: Path) -> None:
    found = [
        f"line {number}: U+{ord(character):04X}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for character in line
        if unicodedata.category(character) in INVISIBLE_CATEGORIES and character not in VISIBLE_CONTROLS
    ]
    assert not found, f"{path.name} holds raw invisible characters, write their escapes: {found}"


@pytest.mark.parametrize("path", SOURCES, ids=[str(path.relative_to(REPO_ROOT)) for path in SOURCES])
def test_no_source_cites_the_plan(path: Path) -> None:
    found = [
        f"line {number}: {line.strip()[:100]}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if PLAN_REFERENCE.search(line)
    ]
    assert not found, f"{path.name} cites the plan; cite a CALIBRATION.md ID instead: {found}"

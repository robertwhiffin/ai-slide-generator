"""Tests for scripts/check_release_notes.py, the publish guard for What's new notes.

publish.yml runs the script on every release tag, so a release can't reach PyPI without a
valid ``frontend/src/whatsNew/releases/<version>.json``. The rules must match the
frontend's ``parseReleaseNotes`` (frontend/src/whatsNew/releaseNotes.ts). Otherwise a file
the guard accepts could still break the popup.

Interface under test:

    DEFAULT_NOTES_DIR: Path   # <repo root>/frontend/src/whatsNew/releases
    check_release_notes(version, notes_dir=DEFAULT_NOTES_DIR) -> list[str]   # [] means OK
    main(argv=None) -> int    # prints each problem to stderr; 1 if any, else 0

``check_release_notes`` is tested through its ``notes_dir`` parameter. ``main`` takes no
directory argument, so its tests move the default with the ``default_dir_is`` fixture.
That fixture patches the module's ``DEFAULT_NOTES_DIR`` and the matching default argument
of ``check_release_notes``, so it works whether ``main`` reads the global at call time or
relies on the default bound when the function was defined.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.check_release_notes as crn
from scripts.check_release_notes import check_release_notes, main

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_release_notes.py"

VERSION = "0.5.7"

VALID_NOTES = {
    "version": VERSION,
    "date": "2026-11-14",
    "items": [
        {"title": "Images in chat", "body": "Ask for an image of a monkey at a keyboard."},
        {"title": "Stop a generation", "body": "Press Esc to stop the deck mid-build."},
    ],
}


def notes(**overrides) -> dict:
    """A deep copy of VALID_NOTES with top-level keys replaced."""
    out = copy.deepcopy(VALID_NOTES)
    out.update(overrides)
    return out


def notes_without(key: str) -> dict:
    out = copy.deepcopy(VALID_NOTES)
    del out[key]
    return out


def one_item(**item) -> dict:
    """VALID_NOTES with a single item made of exactly the given fields."""
    return notes(items=[item])


def write_notes(notes_dir: Path, content, version: str = VERSION) -> Path:
    """Write ``<version>.json``. ``content`` is raw text (str) or a JSON value."""
    path = notes_dir / f"{version}.json"
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return path


def assert_one_problem(problems, fragment: str | None = None) -> None:
    assert isinstance(problems, list), problems
    assert all(isinstance(p, str) for p in problems), problems
    assert len(problems) == 1, problems
    if fragment is not None:
        assert fragment in problems[0], problems


# ---------------------------------------------------------------------------
# check_release_notes: valid files
# ---------------------------------------------------------------------------


def test_valid_file_has_no_problems(tmp_path):
    write_notes(tmp_path, VALID_NOTES)

    assert check_release_notes(VERSION, notes_dir=tmp_path) == []


def test_empty_items_is_valid(tmp_path):
    """``items: []`` means the release has nothing user-facing. It is still a valid file."""
    write_notes(tmp_path, notes(items=[]))

    assert check_release_notes(VERSION, notes_dir=tmp_path) == []


def test_leap_day_is_a_real_date(tmp_path):
    """The real-date check must not reject a 29 February that exists."""
    write_notes(tmp_path, notes(date="2028-02-29"))

    assert check_release_notes(VERSION, notes_dir=tmp_path) == []


def test_reads_the_file_for_the_requested_version(tmp_path):
    """A valid file for a different version does not count as notes for this one."""
    write_notes(tmp_path, notes(version="0.5.6"), version="0.5.6")

    assert_one_problem(check_release_notes(VERSION, notes_dir=tmp_path), "0.5.7.json")


# ---------------------------------------------------------------------------
# check_release_notes: the brief's Step 1 cases (one problem each, with a named fragment)
# ---------------------------------------------------------------------------


def test_missing_file_is_one_problem_naming_the_file(tmp_path):
    assert_one_problem(check_release_notes(VERSION, notes_dir=tmp_path), "0.5.7.json")


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        pytest.param('{"version": "0.5.7", "date": "2026-11-14",', "JSON", id="invalid-json"),
        pytest.param(notes(version="0.5.8"), "0.5.8", id="version-mismatch"),
        pytest.param(notes(date="2026-02-30"), "date", id="impossible-date"),
        pytest.param(one_item(title="Images in chat"), "body", id="item-without-body"),
        pytest.param(
            one_item(title="Images in chat.", body="Ask for an image."),
            "period",
            id="title-trailing-period",
        ),
    ],
)
def test_single_defect_is_one_problem_with_fragment(tmp_path, content, fragment):
    write_notes(tmp_path, content)

    assert_one_problem(check_release_notes(VERSION, notes_dir=tmp_path), fragment)


# ---------------------------------------------------------------------------
# check_release_notes: the rest of the rules, aligned with parseReleaseNotes
#
# The brief names no message fragment for these, so they assert only that the one defect
# gives exactly one problem. Several are cases where an obvious Python approach diverges
# from the TypeScript:
#   * Python 3.11's date.fromisoformat accepts "20261114" and "2026-W46-5". The TS needs
#     YYYY-MM-DD exactly, so the format check has to come before the calendar check.
#   * strptime("%Y-%m-%d") accepts "2026-11-1". The TS needs two-digit month and day.
#   * The TS trims title and body. A whitespace-only body is empty, and "Title. " still
#     ends with a period.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("[]", id="top-level-array"),
        pytest.param('"0.5.7"', id="top-level-string"),
        pytest.param(notes_without("version"), id="version-missing"),
        pytest.param(notes_without("date"), id="date-missing"),
        pytest.param(notes(date=20261114), id="date-not-a-string"),
        pytest.param(notes(date="20261114"), id="date-basic-iso-format"),
        pytest.param(notes(date="2026-W46-5"), id="date-iso-week-format"),
        pytest.param(notes(date="2026-11-1"), id="date-unpadded-day"),
        pytest.param(notes(date="2026-13-01"), id="date-month-13"),
        pytest.param(notes(date="2027-02-29"), id="date-not-a-leap-year"),
        pytest.param(notes_without("items"), id="items-missing"),
        pytest.param(notes(items={"title": "Images in chat", "body": "x"}), id="items-not-a-list"),
        pytest.param(notes(items=["Images in chat"]), id="item-not-an-object"),
        pytest.param(one_item(body="Ask for an image."), id="item-without-title"),
        pytest.param(one_item(title="", body="Ask for an image."), id="title-empty"),
        pytest.param(one_item(title="   ", body="Ask for an image."), id="title-whitespace-only"),
        pytest.param(one_item(title=7, body="Ask for an image."), id="title-not-a-string"),
        pytest.param(one_item(title="Images in chat", body=""), id="body-empty"),
        pytest.param(one_item(title="Images in chat", body="   "), id="body-whitespace-only"),
        pytest.param(one_item(title="Images in chat", body=["x"]), id="body-not-a-string"),
        pytest.param(
            one_item(title="Images in chat. ", body="Ask for an image."),
            id="title-period-before-trailing-space",
        ),
    ],
)
def test_other_single_defects_are_one_problem(tmp_path, content):
    write_notes(tmp_path, content)

    assert_one_problem(check_release_notes(VERSION, notes_dir=tmp_path))


def test_defect_in_a_later_item_is_caught(tmp_path):
    """Every item is checked, not just the first."""
    bad = notes()
    bad["items"].append({"title": "Third item.", "body": "Its title ends with a period."})
    write_notes(tmp_path, bad)

    assert_one_problem(check_release_notes(VERSION, notes_dir=tmp_path), "period")


# ---------------------------------------------------------------------------
# DEFAULT_NOTES_DIR and main
# ---------------------------------------------------------------------------


def test_default_notes_dir_is_the_repo_releases_dir():
    """It is absolute, so the guard does not depend on the directory it runs from."""
    default = Path(crn.DEFAULT_NOTES_DIR)

    assert default.is_absolute()
    assert default.resolve() == (REPO_ROOT / "frontend" / "src" / "whatsNew" / "releases").resolve()


@pytest.fixture
def default_dir_is(tmp_path, monkeypatch):
    """Make tmp_path the notes directory ``main`` uses.

    Patches the module attribute (read at call time) and any default argument of
    check_release_notes equal to the original DEFAULT_NOTES_DIR (bound at def time). With
    both patched, the test does not depend on which of the two ``main`` relies on.
    """
    original = crn.DEFAULT_NOTES_DIR
    monkeypatch.setattr(crn, "DEFAULT_NOTES_DIR", tmp_path)

    fn = crn.check_release_notes
    if fn.__defaults__:
        monkeypatch.setattr(
            fn, "__defaults__", tuple(tmp_path if d == original else d for d in fn.__defaults__)
        )
    if fn.__kwdefaults__:
        monkeypatch.setattr(
            fn,
            "__kwdefaults__",
            {k: (tmp_path if v == original else v) for k, v in fn.__kwdefaults__.items()},
        )
    return tmp_path


def test_main_returns_1_and_reports_a_missing_file_on_stderr(default_dir_is, capsys):
    assert main([VERSION]) == 1

    captured = capsys.readouterr()
    assert "0.5.7.json" in captured.err


def test_main_returns_0_for_a_valid_file_and_prints_no_problems(default_dir_is, capsys):
    """Also shows that ``main`` reads the patched directory. The real releases directory
    has no 0.5.7.json until the 0.5.7 bump PR adds one. After that, the missing-file test
    above is the one that fails if ``main`` ignores the patch."""
    write_notes(default_dir_is, VALID_NOTES)

    assert main([VERSION]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_returns_1_and_reports_an_invalid_file_on_stderr(default_dir_is, capsys):
    """``main`` reports content problems as well as a missing file."""
    write_notes(default_dir_is, notes(date="2026-02-30"))

    assert main([VERSION]) == 1

    captured = capsys.readouterr()
    assert "date" in captured.err


def test_script_runs_on_bare_stdlib_python_and_fails_for_an_unknown_version(tmp_path):
    """publish.yml runs ``python3 scripts/check_release_notes.py <version>`` on a runner
    with no project dependencies. ``-S`` drops site-packages, so a third-party import
    fails here. ``-I`` keeps the script directory and the cwd off sys.path. Running from
    tmp_path shows the default directory doesn't depend on the cwd. 0.0.0 never has notes.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "0.0.0"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "0.0.0.json" in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# JavaScript trim parity and the whole-directory check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "accepted"),
    [
        # JS trim() strips U+FEFF, Python str.strip() does not: the frontend would reject it.
        pytest.param("﻿", False, id="bom-only-title-rejected"),
        # JS trim() does not strip U+0085 (NEL), Python str.strip() does: the frontend accepts it.
        pytest.param("\x85", True, id="nel-only-title-accepted"),
    ],
)
def test_title_whitespace_matches_javascript_trim(tmp_path, title, accepted):
    write_notes(tmp_path, one_item(title=title, body="Ask for an image."))

    problems = check_release_notes(VERSION, notes_dir=tmp_path)

    if accepted:
        assert problems == []
    else:
        assert_one_problem(problems, "title")


def test_a_malformed_other_file_is_one_problem_naming_it(tmp_path):
    """releases.ts throws at import on any bad file, so the guard checks them all."""
    write_notes(tmp_path, VALID_NOTES)
    write_notes(tmp_path, notes(version="0.5.6", date="2026-02-30"), version="0.5.6")

    problems = check_release_notes(VERSION, notes_dir=tmp_path)

    assert_one_problem(problems, "0.5.6.json")
    assert "date" in problems[0]


def test_other_files_are_checked_against_their_own_stem(tmp_path):
    write_notes(tmp_path, VALID_NOTES)
    write_notes(tmp_path, notes(version="0.5.6"), version="0.5.6")  # valid: no problem
    write_notes(tmp_path, notes(version="0.5.5"), version="0.5.4")  # stem 0.5.4, says 0.5.5

    assert_one_problem(check_release_notes(VERSION, notes_dir=tmp_path), "0.5.4.json")

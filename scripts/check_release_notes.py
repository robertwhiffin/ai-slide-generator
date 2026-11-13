"""Publish guard for "What's new in Tellr" release notes.

publish.yml runs this on every release tag, before anything is built or uploaded:

    python3 scripts/check_release_notes.py <version>

It refuses the tag unless frontend/src/whatsNew/releases/<version>.json exists and passes
the checks in parseReleaseNotes (frontend/src/whatsNew/releaseNotes.ts). The rules are
copied by hand, so keep the two in step. Standard library only: the validate job runs on
a bare runner with no project dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

DEFAULT_NOTES_DIR: Path = (
    Path(__file__).resolve().parents[1] / "frontend" / "src" / "whatsNew" / "releases"
)

# Same shapes as the TypeScript regexes. [0-9] rather than \d, because Python's \d also
# matches other Unicode digits. fullmatch rather than ^...$, because $ also matches before
# a trailing newline.
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")

# What String.prototype.trim() strips in JavaScript. Python's str.strip() is different
# (it strips \x1c-\x1f and \x85, and not U+FEFF), so the set is spelled out here.
_JS_WHITESPACE = (
    "\t\n\v\f\r   "
    "           "
    "    　﻿"
)


def _js_trim(text: str) -> str:
    return text.strip(_JS_WHITESPACE)


def _is_real_date(text: str) -> bool:
    """A strict YYYY-MM-DD string that names a real calendar day."""
    m = _DATE_RE.fullmatch(text)
    if not m:
        return False
    year, month, day = (int(g) for g in m.groups())
    # The TypeScript check round-trips through new Date(Date.UTC(y, m - 1, d)). JavaScript
    # maps years 0-99 to 1900-1999, so every year below 100 fails that round trip. Match it.
    if year < 100:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _reject_constant(token: str):
    # json.loads accepts NaN and Infinity by default. JSON.parse in the frontend does not.
    raise ValueError(f"{token} is not valid JSON")


def check_release_notes(version: str, notes_dir: Path = DEFAULT_NOTES_DIR) -> list[str]:
    """Problems with the notes files, one string each. An empty list means OK.

    <version>.json must exist and be valid. Every other *.json in the directory is checked
    too, against its own file name: releases.ts throws at import on ANY malformed file, which
    would white-screen the app.
    """
    name = f"{version}.json"
    path = notes_dir / name
    if not path.is_file():
        return [f"{name} is missing from {notes_dir}"]
    problems = _check_file(path, version)
    for other in sorted(notes_dir.glob("*.json")):
        if other.name != name:
            problems.extend(_check_file(other, other.stem))
    return problems


def _check_file(path: Path, expected_version: str) -> list[str]:
    """Problems with one notes file, each prefixed with the file name."""
    name = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{name}: cannot read the file ({exc})"]
    try:
        raw = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        return [f"{name}: not valid JSON ({exc})"]

    if not isinstance(raw, dict):
        return [f"{name}: expected a JSON object"]

    problems: list[str] = []

    def problem(why: str) -> None:
        problems.append(f"{name}: {why}")

    got_version = raw.get("version")
    if not isinstance(got_version, str) or not _VERSION_RE.fullmatch(got_version):
        problem(f"version must look like X.Y.Z, got {json.dumps(got_version)}")
    elif got_version != expected_version:
        problem(
            f"version {json.dumps(got_version)} does not match the file name, "
            f"which is {expected_version}"
        )

    raw_date = raw.get("date")
    if not isinstance(raw_date, str) or not _is_real_date(raw_date):
        problem(f"date must be a real YYYY-MM-DD date, got {json.dumps(raw_date)}")

    items = raw.get("items")
    if not isinstance(items, list):
        problem("items must be an array")
        return problems

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            problem(f"item {i} must be an object")
            continue
        title = item.get("title")
        if not isinstance(title, str) or _js_trim(title) == "":
            problem(f"item {i} needs a non-empty title")
        elif _js_trim(title).endswith("."):
            problem(f"item {i} title must not end with a period")
        body = item.get("body")
        if not isinstance(body, str) or _js_trim(body) == "":
            problem(f"item {i} needs a non-empty body")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the What's new notes file for a release exists and is valid."
    )
    parser.add_argument("version", help="release version without the leading v, e.g. 0.5.7")
    args = parser.parse_args(argv)

    problems = check_release_notes(args.version, DEFAULT_NOTES_DIR)
    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        return 1
    print(f"What's new notes OK for {args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

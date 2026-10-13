"""Conformance test: Python Finding schema vs TypeScript SlideFinding interface.

Guards against the Python/TS drift that already happened once — the backend
produced {category, severity, description, auto_fixable} while the frontend
declared {id, slideIndex, category, message, seen}.  There is no runtime bridge
between the two declarations, which is exactly why they drifted.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
FINDING_TS = REPO_ROOT / "frontend" / "src" / "types" / "finding.ts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_ts() -> str:
    return FINDING_TS.read_text()


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _extract_interface_fields(ts_src: str, interface_name: str) -> list[str]:
    """Return field names from a TS interface, handling nested {} in type annotations."""
    m = re.search(rf"export interface {interface_name}\s*\{{", ts_src)
    assert m, f"export interface {interface_name} not found in finding.ts"
    start = m.end()
    depth = 1
    i = start
    while i < len(ts_src) and depth > 0:
        if ts_src[i] == "{":
            depth += 1
        elif ts_src[i] == "}":
            depth -= 1
        i += 1
    body = ts_src[start : i - 1]
    fields = []
    for line in body.splitlines():
        stripped = line.strip()
        if ":" not in stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        field_part = stripped.split(":")[0].strip()
        field_name = field_part.rstrip("?").strip()
        if field_name:
            fields.append(field_name)
    return fields


def _extract_type_union(ts_src: str, type_name: str) -> set[str]:
    """Return the union members of 'export type X = ...' declaration."""
    m = re.search(rf"export type {type_name}\s*=\s*([^;]+);", ts_src)
    assert m, f"export type {type_name} not found in finding.ts"
    return {v.strip().strip("'\"") for v in m.group(1).split("|")}


def _extract_deck_level_criteria(ts_src: str) -> set[str]:
    """Return the criterion names listed in the DECK_LEVEL_CRITERIA constant.

    Parses the ``new Set([...])`` literal.  Asserts the construct is present and
    non-empty, so a renamed or deleted constant fails here rather than silently
    yielding an empty set that some other assertion then compares against.
    """
    m = re.search(
        r"export const DECK_LEVEL_CRITERIA[^=]*=\s*new Set\(\s*\[(.*?)\]",
        ts_src,
        re.DOTALL,
    )
    assert m, (
        "export const DECK_LEVEL_CRITERIA = new Set([...]) not found in finding.ts. "
        "If it was renamed or removed, update this test and its consumer "
        "(SlideViewer.tsx's grain-routing filter) together."
    )
    names = set()
    for raw in m.group(1).split(","):
        entry = raw.strip()
        if not entry or entry.startswith("//"):
            continue
        names.add(entry.strip("'\""))
    assert names, "DECK_LEVEL_CRITERIA parsed as empty; the literal has no entries"
    return names


def _extract_category_label_keys(ts_src: str) -> set[str]:
    """Return the keys defined in the CATEGORY_LABEL constant."""
    m = re.search(
        r"export const CATEGORY_LABEL[^=]*=\s*\{([^}]+)\}", ts_src, re.DOTALL
    )
    assert m, "export const CATEGORY_LABEL not found in finding.ts"
    keys = set()
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if ":" not in stripped or stripped.startswith("//"):
            continue
        key = stripped.split(":")[0].strip().strip("'\"")
        if key:
            keys.add(key)
    return keys


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFindingConformance:

    def test_every_backend_field_has_camelcase_mirror(self) -> None:
        """Every Python Finding field must have a camelCase counterpart in SlideFinding.

        Fails when a new field is added to the Python model but the TS mirror is
        not updated.  This is the primary drift guard.
        """
        from src.domain.finding import Finding

        ts_src = _read_ts()
        ts_fields = set(_extract_interface_fields(ts_src, "SlideFinding"))
        py_fields = set(Finding.model_fields.keys())
        camel_fields = {_snake_to_camel(f) for f in py_fields}
        missing = camel_fields - ts_fields
        assert not missing, (
            f"Backend Finding fields missing camelCase mirror in SlideFinding: {sorted(missing)}. "
            f"TS fields present: {sorted(ts_fields)}"
        )

    def test_no_extra_ts_fields_beyond_backend(self) -> None:
        """SlideFinding must not declare fields the backend Finding lacks.

        Fails when TS grows a field that has no Python counterpart, meaning the
        frontend would receive an undefined value at that key from any backend
        serialisation.
        """
        from src.domain.finding import Finding

        ts_src = _read_ts()
        ts_fields = set(_extract_interface_fields(ts_src, "SlideFinding"))
        py_fields = set(Finding.model_fields.keys())
        camel_fields = {_snake_to_camel(f) for f in py_fields}
        extra = ts_fields - camel_fields
        assert not extra, (
            f"SlideFinding declares fields not present in Finding: {sorted(extra)}."
        )

    def test_finding_category_union_has_exactly_three_members(self) -> None:
        """FindingCategory union must equal exactly {content, design, narrative}.

        Fails when a category is added to or removed from one side only.
        Do NOT loop over CRITERIA here — pydantic guarantees each criterion's
        category is valid at construction; the drift this test guards is
        Python-vs-TypeScript, not CRITERIA-vs-FindingCategory.
        """
        ts_src = _read_ts()
        union = _extract_type_union(ts_src, "FindingCategory")
        assert union == {"content", "design", "narrative"}, (
            f"FindingCategory union is {union!r}; expected exactly content|design|narrative"
        )

    def test_finding_status_union_is_exactly_open_or_fixed(self) -> None:
        """FindingStatus union must be exactly open | fixed.

        Fails when the Python FindingStatus Literal or the TS union drifts.
        """
        ts_src = _read_ts()
        union = _extract_type_union(ts_src, "FindingStatus")
        assert union == {"open", "fixed"}, (
            f"FindingStatus union is {union!r}; expected exactly open|fixed"
        )

    def test_category_label_keys_exhaustive_over_union(self) -> None:
        """CATEGORY_LABEL keys must exactly cover the FindingCategory union.

        This is the test that matters (brief §B1.2): a fourth category added to
        the Python CRITERIA registry changes FindingCategory, and a CATEGORY_LABEL
        that is missing the new key silently displays a blank badge label in the
        drawer.  The Record<FindingCategory, string> annotation catches it at
        compile time, and this test catches it before the TypeScript compiler is
        even invoked.
        """
        ts_src = _read_ts()
        union = _extract_type_union(ts_src, "FindingCategory")
        label_keys = _extract_category_label_keys(ts_src)
        assert label_keys == union, (
            f"CATEGORY_LABEL keys {sorted(label_keys)!r} != FindingCategory union "
            f"{sorted(union)!r}. "
            f"Missing from CATEGORY_LABEL: {sorted(union - label_keys)}. "
            f"Extra in CATEGORY_LABEL: {sorted(label_keys - union)}."
        )

    def test_deck_level_criteria_mirror_equals_the_registrys_deck_level_set(self) -> None:
        """DECK_LEVEL_CRITERIA must be exactly the level="deck" names in CRITERIA.

        Review finding I2.  `frontend/src/types/finding.ts` hand-copies the
        server's deck-level criterion names and its own comment says only "keep in
        sync" — a comment, not a test.  There is no runtime bridge between the
        registry and that Set, the same absence that let Finding and SlideFinding
        drift once already, which is why this file exists.

        The consequence of drift is concrete, not stylistic: SlideViewer.tsx's
        grain-routing filter reads this Set to keep deck-level findings OUT of the
        per-slide drawer.  A fourth `level="deck"` criterion added server-side and
        not mirrored here renders in the slide drawer, defeating that filter.  The
        only existing guard is indirect — test_finding_schema.py pins the registry
        to exactly nine named criteria, so adding one forces an edit THERE — and it
        points nowhere at the frontend.

        Fails in both directions: a registry criterion promoted to deck level and
        not mirrored, and a mirror entry that no longer names a deck-level
        criterion (including a typo).
        """
        from src.domain.finding import CRITERIA

        mirrored = _extract_deck_level_criteria(_read_ts())
        registry_deck_level = {
            name for name, crit in CRITERIA.items() if crit.level == "deck"
        }
        assert mirrored == registry_deck_level, (
            f"DECK_LEVEL_CRITERIA in finding.ts is {sorted(mirrored)!r} but the "
            f"level=\"deck\" criteria in src/domain/finding.py CRITERIA are "
            f"{sorted(registry_deck_level)!r}. "
            f"Missing from the TypeScript mirror (these would render in the slide "
            f"drawer): {sorted(registry_deck_level - mirrored)}. "
            f"In the mirror but not deck-level in the registry (these would be "
            f"filtered out of the drawer wrongly): {sorted(mirrored - registry_deck_level)}."
        )

    def test_model_dump_maps_to_exact_camelcase_dict(self) -> None:
        """A real Finding.model_dump() maps to the exact camelCase dict the frontend reads.

        Fails when field names, types, or the camelCase conversion logic drifts
        between Python and TypeScript.
        """
        from src.domain.finding import Finding, make_finding_id

        finding = Finding(
            id=make_finding_id("overflow", "abc123", 0),
            slide_index=0,
            category="design",
            criterion="overflow",
            message="Content overflows the slide frame.",
            objective=True,
            status="open",
            seen=False,
        )
        dumped = finding.model_dump()
        camel_dumped = {_snake_to_camel(k): v for k, v in dumped.items()}
        expected = {
            "id": finding.id,
            "slideIndex": 0,
            "category": "design",
            "criterion": "overflow",
            "message": "Content overflows the slide frame.",
            "objective": True,
            "status": "open",
            "seen": False,
        }
        assert camel_dumped == expected, (
            f"model_dump() camelCase:\n  {camel_dumped}\n"
            f"Expected:\n  {expected}\n"
            f"Diff keys: {set(camel_dumped) ^ set(expected)}"
        )


# ---------------------------------------------------------------------------
# B3.2 — the deck read path's `findings` key, conformed to the same declaration
# ---------------------------------------------------------------------------
#
# `get_slide_deck` emits a deck-level `findings` list that the frontend reads as
# `SlideDeck.findings?: SlideFinding[]`.  There is no runtime bridge between the
# emitted dicts and that TypeScript declaration either — the same absence that
# let Finding and SlideFinding drift once already — so the entries the READ PATH
# actually produces are conformed here, not just Finding.model_dump().
#
# The distinction matters: model_dump() is snake_case.  Something in the read
# path has to convert it, and a test against model_dump() alone would stay green
# while the read path shipped `slide_index` to a frontend reading `slideIndex`.


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class TestReadPathFindingsConformance:
    """The read path's findings entries vs the declared SlideFinding interface."""

    def test_read_path_entry_keys_are_exactly_the_declared_slidefinding_fields(
        self, deck_with_spec
    ) -> None:
        """Every emitted key is declared, and every declared field is emitted.

        Fails if the read path drops a field the frontend declares (the consumer
        reads undefined) or emits one it does not (dead data, and a sign the two
        declarations have drifted again).
        """
        from tests.unit.test_deck_read_path_keys import _write_findings

        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 0, rows[0].html, count=2)
        findings = deck_with_spec.get_slide_deck()["findings"]
        assert findings, "read path produced no findings — the fixture write did not land"

        ts_fields = set(_extract_interface_fields(_read_ts(), "SlideFinding"))
        for entry in findings:
            assert set(entry) == ts_fields, (
                f"read-path findings entry keys {sorted(entry)} != declared "
                f"SlideFinding fields {sorted(ts_fields)}. "
                f"Missing from the entry: {sorted(ts_fields - set(entry))}. "
                f"Not declared in TS: {sorted(set(entry) - ts_fields)}."
            )

    def test_read_path_emits_camelcase_slide_index_not_snake_case(
        self, deck_with_spec
    ) -> None:
        """`slideIndex`, explicitly — the one renamed field, and the drift that bites.

        Finding.slide_index is snake_case in Python and slideIndex in TS.  A read
        path that forwarded model_dump() verbatim would pass every other test in
        this file and still give the drawer `undefined` for the field it filters on.
        """
        from tests.unit.test_deck_read_path_keys import _write_findings

        rows = deck_with_spec.rows()
        _write_findings(deck_with_spec, deck_with_spec.session_id, 1, rows[1].html, count=1)
        entry = deck_with_spec.get_slide_deck()["findings"][0]

        assert "slideIndex" in entry, f"no slideIndex in {entry!r}"
        assert "slide_index" not in entry, (
            f"read path emitted snake_case slide_index alongside/instead of "
            f"slideIndex: {entry!r}"
        )
        assert entry["slideIndex"] == 1

    def test_read_path_entry_round_trips_back_into_a_domain_finding(
        self, deck_with_spec
    ) -> None:
        """camelCase entry -> snake_case -> Finding == the Finding that was stored.

        This is the field-for-field mapping assertion: names AND values survive
        the projection in both directions, so no field is silently renamed,
        dropped, or coerced on the way out.
        """
        from src.domain.finding import Finding

        from tests.unit.test_deck_read_path_keys import _findings_for, _write_findings

        rows = deck_with_spec.rows()
        html = rows[2].html
        _write_findings(deck_with_spec, deck_with_spec.session_id, 2, html, count=2)
        expected = _findings_for(html, 2, 2)

        entries = deck_with_spec.get_slide_deck()["findings"]
        assert len(entries) == len(expected)

        rebuilt = [
            Finding(**{_camel_to_snake(k): v for k, v in entry.items()})
            for entry in entries
        ]
        assert rebuilt == expected, (
            f"read-path findings do not round-trip.\n  from read path: {rebuilt}\n"
            f"  as stored:      {expected}"
        )

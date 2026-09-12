"""Smoke tests: for each skill in OUTPUT_SCHEMAS, assert the canned payload

1. exists on disk,
2. parses against its schema,
3. the schema can emit JSON Schema (it is shipped to the model as a
   structured-output contract, so a schema that cannot serialise is useless),
4. round-trips (model_dump → model_validate → model_dump produces an equal result).

Design notes
------------
- **Driven from OUTPUT_SCHEMAS, never from a hardcoded list of names.**
  A rename in the registry surfaces as a missing-payload failure, not silence.
  A hardcoded list would silently stop covering a renamed key.

- **Two keys share a schema class** (``build_reviewer`` and ``fix_reviewer`` both
  map to ``SlideReviewOutput``).  They get *separate* payload files with distinct
  content so that an optional-field type regression on one does not hide behind
  the other.

- **Discovery guards**: every assertion that counts or globs must include an
  explicit count check.  A test that passes when pointed at an empty directory
  is the worst outcome — this file guards against both a missing directory and
  a real-but-empty one.

- **No postgres marker needed**: the tested schemas are pure Pydantic with no
  database imports (src/domain/skill_io.py, finding.py, deck_spec.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.skill_io import OUTPUT_SCHEMAS

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skill_payloads"

_EXPECTED_KEY_COUNT = 7


# ---------------------------------------------------------------------------
# Registry-level guard
# ---------------------------------------------------------------------------


def test_output_schemas_has_exactly_seven_keys() -> None:
    """Fail loudly if the registry grows or shrinks without updating the payloads."""
    assert len(OUTPUT_SCHEMAS) == _EXPECTED_KEY_COUNT, (
        f"OUTPUT_SCHEMAS must have exactly {_EXPECTED_KEY_COUNT} keys; "
        f"got {len(OUTPUT_SCHEMAS)}: {sorted(OUTPUT_SCHEMAS)}"
    )


# ---------------------------------------------------------------------------
# Coverage guards — the fixture directory must exist and be fully populated
# ---------------------------------------------------------------------------


def test_fixture_directory_exists() -> None:
    """Guard: the fixture directory itself must exist."""
    assert FIXTURES_DIR.is_dir(), (
        f"Fixture directory missing: {FIXTURES_DIR}\n"
        "Create tests/fixtures/skill_payloads/ and add one JSON per OUTPUT_SCHEMAS key."
    )


def test_fixture_directory_payload_count() -> None:
    """Guard against vacuous discovery: the glob must find exactly one file per key.

    Passes neither on a missing directory nor on a real-but-empty one.
    """
    assert FIXTURES_DIR.is_dir(), (
        f"Fixture directory missing: {FIXTURES_DIR}"
    )
    found = sorted(FIXTURES_DIR.glob("*.json"))
    assert len(found) == _EXPECTED_KEY_COUNT, (
        f"Expected {_EXPECTED_KEY_COUNT} payload files (one per OUTPUT_SCHEMAS key); "
        f"found {len(found)}: {[p.name for p in found]}\n"
        f"OUTPUT_SCHEMAS keys: {sorted(OUTPUT_SCHEMAS)}"
    )


# ---------------------------------------------------------------------------
# Per-skill smoke tests — parametrised from OUTPUT_SCHEMAS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_name,schema_cls", list(OUTPUT_SCHEMAS.items()))
def test_payload_file_exists(skill_name: str, schema_cls: type) -> None:
    """Each key in OUTPUT_SCHEMAS must have a corresponding payload file."""
    payload_path = FIXTURES_DIR / f"{skill_name}.json"
    assert payload_path.exists(), (
        f"Missing payload file for skill '{skill_name}': {payload_path}"
    )


@pytest.mark.parametrize("skill_name,schema_cls", list(OUTPUT_SCHEMAS.items()))
def test_payload_parses(skill_name: str, schema_cls: type) -> None:
    """The canned payload must parse without error against its schema."""
    payload_path = FIXTURES_DIR / f"{skill_name}.json"
    data = json.loads(payload_path.read_text())
    instance = schema_cls.model_validate(data)
    assert instance is not None


@pytest.mark.parametrize("skill_name,schema_cls", list(OUTPUT_SCHEMAS.items()))
def test_schema_emits_json_schema(skill_name: str, schema_cls: type) -> None:
    """The schema must serialise to JSON Schema.

    This is not cosmetic: the schema dict is shipped to the model as a
    structured-output contract.  A schema class that cannot emit JSON Schema
    would break every model invocation for that skill.
    """
    schema = schema_cls.model_json_schema()
    assert isinstance(schema, dict), (
        f"model_json_schema() for {schema_cls.__name__} returned {type(schema).__name__}, "
        "expected dict"
    )
    assert schema, (
        f"model_json_schema() for {schema_cls.__name__} returned an empty dict"
    )


@pytest.mark.parametrize("skill_name,schema_cls", list(OUTPUT_SCHEMAS.items()))
def test_payload_round_trips(skill_name: str, schema_cls: type) -> None:
    """model_dump → model_validate must yield an identical model_dump.

    A round-trip failure means the schema has a field whose type cannot
    survive a serialise/deserialise cycle, which would corrupt the graph
    state store on any checkpoint read.
    """
    payload_path = FIXTURES_DIR / f"{skill_name}.json"
    data = json.loads(payload_path.read_text())
    first = schema_cls.model_validate(data)
    second = schema_cls.model_validate(first.model_dump())
    assert first.model_dump() == second.model_dump(), (
        f"Round-trip mismatch for skill '{skill_name}' ({schema_cls.__name__}):\n"
        f"  first  = {first.model_dump()}\n"
        f"  second = {second.model_dump()}"
    )

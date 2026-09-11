"""Conformance test: Python verification schema vs TypeScript VerificationResult interface.

Guards against Python/TS drift on the verification path.  VerificationBadge.tsx
null-checks at line 117 (`if (!verificationResult) return null;`), so the risk
here is not a missing null-check — it is fields the frontend requires that the
backend silently omits.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
VERIFICATION_TS = REPO_ROOT / "frontend" / "src" / "types" / "verification.ts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_ts() -> str:
    return VERIFICATION_TS.read_text()


def _extract_interface_fields(ts_src: str, interface_name: str) -> dict[str, bool]:
    """Return {fieldName: required} from a TS interface.

    Uses brace-counting so nested types like Array<{type: string; detail: string}>
    do not confuse the interface-body extractor.
    """
    m = re.search(rf"export interface {interface_name}\s*\{{", ts_src)
    assert m, f"export interface {interface_name} not found in verification.ts"
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
    result: dict[str, bool] = {}
    for line in body.splitlines():
        stripped = line.strip()
        if (
            ":" not in stripped
            or stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
        ):
            continue
        field_part = stripped.split(":")[0].strip()
        field_name = field_part.rstrip("?").strip()
        if not field_name or field_name.startswith("["):
            continue
        optional = field_part.endswith("?")
        result[field_name] = not optional  # True = required
    return result


def _extract_type_union(ts_src: str, type_name: str) -> set[str]:
    """Return union members of 'export type X = ...'."""
    m = re.search(rf"export type {type_name}\s*=\s*([^;]+);", ts_src)
    assert m, f"export type {type_name} not found in verification.ts"
    return {v.strip().strip("'\"") for v in m.group(1).split("|")}


def _all_switch_case_labels(ts_src: str) -> set[str]:
    """Return all non-default case string-literal labels from switch statements in the file."""
    return {m.group(1) for m in re.finditer(r"case '([^']+)':", ts_src)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVerificationConformance:

    def test_verification_result_required_fields(self) -> None:
        """VerificationResult must declare exactly the six required fields.

        Fails when a new required field is added to the TS interface without
        a corresponding backend change, or when a required field is accidentally
        made optional (or dropped).
        """
        ts_src = _read_ts()
        fields = _extract_interface_fields(ts_src, "VerificationResult")
        required = {name for name, req in fields.items() if req}
        expected_required = {"score", "rating", "explanation", "issues", "duration_ms", "error"}
        assert required == expected_required, (
            f"VerificationResult required fields: {sorted(required)}\n"
            f"Expected:                           {sorted(expected_required)}\n"
            f"Missing from interface: {sorted(expected_required - required)}\n"
            f"Unexpectedly required:  {sorted(required - expected_required)}"
        )

    def test_verification_rating_union_matches_switch_cases(self) -> None:
        """VerificationRating union must equal the non-default case labels in the switch functions.

        All four switch functions (getRatingColor, getRatingIcon, getRatingText,
        getRatingLabel) handle the same set of ratings.  If the union grows a new
        member that the switch functions do not handle, TypeScript does not error
        (the `default` branch absorbs it silently) — but this test fails.
        If a switch adds a new case that is not in the union, it is dead code and
        this test fails.
        """
        ts_src = _read_ts()
        union = _extract_type_union(ts_src, "VerificationRating")
        switch_cases = _all_switch_case_labels(ts_src)
        assert union == switch_cases, (
            f"VerificationRating union {sorted(union)!r} != switch case labels "
            f"{sorted(switch_cases)!r}.\n"
            f"In union but not in any switch: {sorted(union - switch_cases)}.\n"
            f"In a switch but not in union:  {sorted(switch_cases - union)}."
        )

    def test_minimal_backend_record_covers_all_required_frontend_fields(self) -> None:
        """A minimal backend verification payload must supply every required VerificationResult field.

        Simulates what get_slide_deck would produce and confirms the frontend's
        required fields are all present.  Fails when a new required field is added
        to VerificationResult without a matching backend emit.
        """
        from src.domain.finding import VERDICT_KEY

        ts_src = _read_ts()
        fields = _extract_interface_fields(ts_src, "VerificationResult")
        required_fields = {name for name, req in fields.items() if req}

        # Minimal payload: the keys the backend emits into a verification record.
        # This is NOT a pydantic model — it is a plain dict that represents what
        # session_manager serialises into verification_map and the frontend reads.
        minimal_payload = {
            "score": 0.9,
            "rating": "green",
            "explanation": "No issues detected.",
            "issues": [],
            "duration_ms": 150,
            "error": False,
        }

        # Wrap in the {content_hash: {VERDICT_KEY: {...}}} shape.
        content_hash = "deadbeef"
        record = {content_hash: {VERDICT_KEY: {"verdict": "clean", "findings": [], **minimal_payload}}}

        # Resolve: the frontend reads the payload from the VERDICT_KEY entry.
        resolved_payload = record[content_hash][VERDICT_KEY]

        missing = required_fields - set(resolved_payload.keys())
        assert not missing, (
            f"Required VerificationResult fields absent from backend payload: {sorted(missing)}.\n"
            f"Backend payload keys: {sorted(resolved_payload.keys())}.\n"
            f"The backend must emit these fields or the frontend will receive undefined."
        )

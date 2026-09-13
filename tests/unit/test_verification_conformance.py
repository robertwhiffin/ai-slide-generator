"""Conformance test: Python verification schema vs TypeScript VerificationResult interface.

Guards against Python/TS drift on the verification path.  VerificationBadge.tsx
null-checks at line 117 (`if (!verificationResult) return null;`), so the risk
here is not a missing null-check — it is fields the frontend requires that the
backend silently omits.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.api.services.session_manager import (
    _merge_verdict_slots,
    _merge_verification_record,
)
from src.api.services.slide_repository import is_placeholder_record
from src.domain.finding import (
    VERDICT_KEY,
    Finding,
    build_verification_record,
    findings_from_record,
    make_finding_id,
)

REPO_ROOT = Path(__file__).parents[2]
VERIFICATION_TS = REPO_ROOT / "frontend" / "src" / "types" / "verification.ts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _judge_payload() -> dict:
    """The flat LLM-judge verdict — every field VerificationResult requires.

    Not a pydantic model: a plain dict, exactly as the judge path serialises it
    into the per-hash slot of a verification record.
    """
    return {
        "score": 0.9,
        "rating": "green",
        "explanation": "No issues detected.",
        "issues": [],
        "duration_ms": 150,
        "error": False,
    }


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

        RESOLVED WHERE THE READ PATH RESOLVES — ``record[content_hash]``, which is
        what ``get_slide_deck`` assigns to ``slide["verification"]`` (the row branch
        does ``verification_data.get(content_hash)``; the blob branch does
        ``verification_map.get(content_hash)``).  An earlier version of this test
        resolved at ``record[content_hash][VERDICT_KEY]`` — one level BELOW the read
        path — and therefore passed while the record the frontend actually received
        supplied none of the required fields.
        """
        ts_src = _read_ts()
        fields = _extract_interface_fields(ts_src, "VerificationResult")
        required_fields = {name for name, req in fields.items() if req}

        content_hash = "deadbeef"
        record = _merge_verdict_slots(
            {content_hash: _judge_payload()},
            build_verification_record(
                content_hash=content_hash,
                findings=[],
                verdict="clean",
            ),
        )

        # Resolve exactly as the read path does.
        resolved_payload = record[content_hash]

        missing = required_fields - set(resolved_payload.keys())
        assert not missing, (
            f"Required VerificationResult fields absent from backend payload: {sorted(missing)}.\n"
            f"Backend payload keys: {sorted(resolved_payload.keys())}.\n"
            f"The backend must emit these fields or the frontend will receive undefined."
        )


# ---------------------------------------------------------------------------
# The per-hash slot is SHARED — judge payload and review payload must coexist
# ---------------------------------------------------------------------------

class TestSharedPerHashVerdictSlot:
    """``record[content_hash]`` is written by TWO producers and must keep both.

    * the LLM judge writes the flat payload ``frontend/src/types/verification.ts``
      requires (score/rating/explanation/issues/duration_ms/error);
    * the graph reviewer writes ``build_verification_record``'s
      ``{VERDICT_KEY: {verdict, findings}}``.

    Both land in the SAME slot, because the read path assigns the whole per-hash
    dict to ``slide["verification"]``.  A hash-level ``dict.update`` therefore let
    whichever producer wrote second delete the other's payload outright: a review
    write left the slot with keys ``['tellr_review']`` (``rating`` gone), and a
    judge write after a review left it with no ``tellr_review`` and no findings.

    These tests drive the PRODUCTION merge (``_merge_verdict_slots``, which backs
    both ``_merge_verification_record`` and ``write_slide_verification``) in BOTH
    orderings, and assert after each write that BOTH producers' payloads survive.
    Sabotaging that helper back to ``merged.update(incoming)`` turns both red.
    """

    CONTENT_HASH = "cafebabe"

    def _review_record(self) -> dict:
        return build_verification_record(
            content_hash=self.CONTENT_HASH,
            findings=[
                Finding(
                    id=make_finding_id("contrast_failure", self.CONTENT_HASH, 0),
                    slide_index=0,
                    category="design",
                    criterion="contrast_failure",
                    message="Body text fails 4.5:1 against the panel.",
                    objective=True,
                )
            ],
            verdict="surfaced",
        )

    def _assert_both_survive(self, record: dict, ordering: str) -> None:
        # Resolve where the read path resolves: the WHOLE per-hash dict.
        slot = record[self.CONTENT_HASH]

        assert slot.get("rating") == "green", (
            f"{ordering}: the judge's `rating` did not survive. "
            f"Slot keys: {sorted(slot.keys())}"
        )
        assert slot.get("score") == 0.9, (
            f"{ordering}: the judge's `score` did not survive. "
            f"Slot keys: {sorted(slot.keys())}"
        )
        assert VERDICT_KEY in slot, (
            f"{ordering}: `{VERDICT_KEY}` did not survive. "
            f"Slot keys: {sorted(slot.keys())}"
        )
        assert slot[VERDICT_KEY]["verdict"] == "surfaced", (
            f"{ordering}: the review verdict did not survive."
        )
        # Findings survive, and survive the documented reader too.
        assert len(slot[VERDICT_KEY]["findings"]) == 1, (
            f"{ordering}: the review findings did not survive."
        )
        reread = findings_from_record(record, self.CONTENT_HASH)
        assert [f.criterion for f in reread] == ["contrast_failure"], (
            f"{ordering}: findings_from_record could not read the findings back; "
            f"got {reread!r}"
        )

    def test_judge_then_review_keeps_both(self) -> None:
        record = _merge_verdict_slots(
            {self.CONTENT_HASH: _judge_payload()}, self._review_record()
        )
        self._assert_both_survive(record, "judge-then-review")

    def test_review_then_judge_keeps_both(self) -> None:
        record = _merge_verdict_slots(
            self._review_record(), {self.CONTENT_HASH: _judge_payload()}
        )
        self._assert_both_survive(record, "review-then-judge")

    def test_the_json_round_trip_writer_keeps_both_orderings(self) -> None:
        """Same two orderings through ``_merge_verification_record``'s JSON form.

        This is the function the deck-save path calls (and it shares
        ``_merge_verdict_slots`` with ``write_slide_verification``), so the
        guarantee is proved on the serialised shape actually persisted.
        """
        judge = {self.CONTENT_HASH: _judge_payload()}

        forward = _merge_verification_record(
            _merge_verification_record(None, judge), self._review_record()
        )
        self._assert_both_survive(json.loads(forward), "judge-then-review (JSON)")

        backward = _merge_verification_record(
            _merge_verification_record(None, self._review_record()), judge
        )
        self._assert_both_survive(json.loads(backward), "review-then-judge (JSON)")

    def test_a_review_write_does_not_turn_a_slide_into_a_placeholder(self) -> None:
        """The nesting under VERDICT_KEY stays load-bearing after the deeper merge.

        ``is_placeholder_record`` scans every value of the per-hash slot for
        ``error is True``.  The judge's payload carries ``error: False``, and the
        review's payload is nested, so a merged slot must still not read as a
        placeholder — in either order.
        """
        for ordering, record in (
            (
                "judge-then-review",
                _merge_verdict_slots(
                    {self.CONTENT_HASH: _judge_payload()}, self._review_record()
                ),
            ),
            (
                "review-then-judge",
                _merge_verdict_slots(
                    self._review_record(), {self.CONTENT_HASH: _judge_payload()}
                ),
            ),
        ):
            assert is_placeholder_record(record) is False, f"{ordering}: {record!r}"
            assert (
                is_placeholder_record(record[self.CONTENT_HASH]) is False
            ), f"{ordering} (resolved verdict): {record[self.CONTENT_HASH]!r}"

"""Deterministic scorers for the eval harness."""
from __future__ import annotations

from src.core import database  # noqa: F401 - break import cycle before src.* imports
from evals.harness.render import RenderMeasures
from src.domain.finding import CRITERIA


#: Longest error detail quoted in a contract-fail rationale; longer is cut + marked.
CONTRACT_DETAIL_MAX_CHARS = 2000


def contract_score(
    structured: dict | None,
    *,
    status: str | None = None,
    error_detail: str | None = None,
) -> tuple[bool, str]:
    """Pass iff structured is not None (runtime already validated schema).

    A fail rationale names why the run produced no output: the runtime's
    ``status`` as `` (status=<status>)`` and its ``error_detail`` as
    ``: <detail>`` (cut to CONTRACT_DETAIL_MAX_CHARS plus a marker), each only
    when given and non-empty.  The pass rationale ignores both.
    """
    if structured is not None:
        return True, "Contract passed: structured output is present"
    rationale = "Contract failed: structured output is None"
    if status:
        rationale += f" (status={status})"
    if error_detail:
        if len(error_detail) > CONTRACT_DETAIL_MAX_CHARS:
            error_detail = error_detail[:CONTRACT_DETAIL_MAX_CHARS] + " ... [truncated]"
        rationale += f": {error_detail}"
    return False, rationale


def expected_category_score(agent_key: str, structured: dict, expect: dict) -> tuple[bool, str]:
    """Role-dispatched expected category scorer.

    - architect: checks intent match, and for edit mode, target_positions match positions (as sets)
    - data_analyst: checks outcome match
    - build_reviewer/fix_reviewer/deck_reviewer: checks findings against expected criteria/positions,
      guards unknown criteria, and optionally checks verdict for fix_reviewer
    """
    if not isinstance(structured, dict):
        return False, f"Structured output is not a dict: {type(structured).__name__}"

    if agent_key == "architect":
        # Check intent match
        if structured.get("intent") != expect.get("intent"):
            return False, f"Intent mismatch: got {structured.get('intent')!r}, expected {expect.get('intent')!r}"

        # For edit, also check target_positions match positions (as sets)
        if structured.get("intent") == "edit":
            got_positions = set(structured.get("target_positions", []))
            expect_positions = set(expect.get("positions", []))
            if got_positions != expect_positions:
                return False, f"Target positions mismatch: got {got_positions}, expected {expect_positions}"

        return True, "Architect intent and positions match"

    elif agent_key == "data_analyst":
        # Check outcome match
        if structured.get("outcome") != expect.get("outcome"):
            return False, f"Outcome mismatch: got {structured.get('outcome')!r}, expected {expect.get('outcome')!r}"
        return True, "Data analyst outcome matches"

    elif agent_key in ["build_reviewer", "fix_reviewer", "deck_reviewer"]:
        # Check findings
        findings = structured.get("findings") or []

        # First, check for unknown criteria
        for f in findings:
            criterion = f.get("criterion")
            if criterion not in CRITERIA:
                return False, f"Unknown criterion: {criterion!r}"

        # Build set of (criterion, position) tuples from findings
        got = set()
        for f in findings:
            criterion = f.get("criterion")
            position = f.get("slide_index")
            got.add((criterion, position))

        # Build objective_got: set of objective criteria
        objective_got = {c for (c, _) in got if CRITERIA[c].objective}

        # Get expected criteria and positions
        expect_criteria = set(expect.get("criteria", []))
        expect_positions = set(expect.get("positions", []))

        # Build expected set: all combinations of (criterion, position)
        expected = {(c, p) for c in expect_criteria for p in expect_positions}

        # A planted criterion with no positions must still appear somewhere
        if expect_criteria and not expect_positions:
            absent = expect_criteria - {c for (c, _) in got}
            if absent:
                return False, f"Missing expected criteria: {absent}"

        # Check 1: every expected (criterion, position) must be present
        if not expected.issubset(got):
            missing = expected - got
            return False, f"Missing expected findings: {missing}"

        # Check 2: no objective criterion outside expect_criteria should appear
        unplanted_objectives = objective_got - expect_criteria
        if unplanted_objectives:
            return False, f"Unplanted objective criteria found: {unplanted_objectives}"

        # Check 3 (fix_reviewer): verdict check if present in expect
        if agent_key == "fix_reviewer" and "verdict" in expect:
            got_verdict = structured.get("verdict")
            expect_verdict = expect.get("verdict")
            if got_verdict != expect_verdict:
                return False, f"Verdict mismatch: got {got_verdict!r}, expected {expect_verdict!r}"

        return True, "All expected findings match and no unplanted objective criteria"

    else:
        return False, f"Unknown agent: {agent_key!r}"


def render_measures_score(measures: RenderMeasures, html: str) -> tuple[bool, str]:
    """Pass iff all render measures are clean.

    Requires:
    - measures.rendered is True
    - overflow_px == 0
    - min_contrast >= 4.5
    - off_palette == ()
    - console_errors == ()
    - safe_area_px == 0 (no text/media past Tellr's 88px-side / 56px-vertical safe area)
    - no "<style" tag in HTML (case-insensitive)
    """
    reasons = []

    if not measures.rendered:
        reasons.append("Rendering failed")

    if measures.overflow_px != 0:
        reasons.append(f"Overflow: {measures.overflow_px}px")

    if measures.min_contrast < 4.5:
        reasons.append(f"Contrast too low: {measures.min_contrast}")

    if measures.off_palette:
        reasons.append(f"Off-palette colors: {measures.off_palette}")

    if measures.console_errors:
        reasons.append(f"Console errors: {measures.console_errors}")

    if measures.safe_area_px > 0:
        reasons.append(f"Safe area intrusion: {measures.safe_area_px}px past the 88px/56px safe area")

    if "<style" in html.lower():
        reasons.append("Inline style tag found in HTML")

    if reasons:
        return False, "; ".join(reasons)

    return True, "All render measures passed"

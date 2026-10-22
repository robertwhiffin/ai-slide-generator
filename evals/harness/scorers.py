"""Deterministic scorers for the eval harness."""
from __future__ import annotations

from src.core import database  # noqa: F401 - break import cycle before src.* imports
from pydantic import ValidationError

from evals.harness.render import RenderMeasures
from src.domain.deck_spec import DeckSpec
from src.domain.finding import CRITERIA
from src.domain.slide_alignment import AlignmentRefused, align_slides


#: Longest error detail quoted in a contract-fail rationale; longer is cut + marked.
CONTRACT_DETAIL_MAX_CHARS = 2000

#: The deck-level spec fields production re-reviews every slide on (#314, D10).
#: Mirrors ``src.services.graph.nodes._DECK_LEVEL_FIELDS``; a unit test pins the two equal.
#: The design-contract ids are a separate check (``_insert_score``), not part of this tuple.
DECK_LEVEL_FIELDS = ("audience", "purpose", "argument", "call_to_action", "narrative_arc")
_RE_REVIEW = "changed (production re-reviews every slide)"


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


def _validate_deck(value) -> tuple[DeckSpec | None, str]:
    """Validate ``value`` as a ``DeckSpec``; the reason is empty on success."""
    try:
        return DeckSpec.model_validate(value), ""
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "<root>"
        return None, f"{e.error_count()} validation error(s), first at {where}: {first['msg']}"


def _insert_score(
    structured: dict, expect: dict, reference: dict | None, current_deck_spec: dict | None
) -> tuple[bool, str]:
    """Score an architect insert turn with production's own semantics (#314, D10).

    Production ignores the model's ``target_positions`` on an insert and derives
    the turn from ``align_slides(current, output)``, so that is what is checked.
    """
    missing = [
        name for name, value in (("reference", reference), ("current_deck_spec", current_deck_spec))
        if value is None
    ]
    if missing:
        return False, f"Insert: cannot score without {' and '.join(missing)}"

    output, why = _validate_deck(structured.get("deck_spec"))
    if output is None:
        return False, f"Insert: no valid deck_spec in the output ({why})"
    current, why = _validate_deck(current_deck_spec)
    if current is None:
        return False, f"Insert: current_deck_spec is not a valid DeckSpec ({why})"
    ref_deck, why = _validate_deck((reference or {}).get("deck_spec"))
    if ref_deck is None:
        return False, f"Insert: the reference has no valid deck_spec ({why})"

    try:
        alignment = align_slides(current.slides, output.slides)
    except AlignmentRefused as e:
        return False, f"Insert: production would refuse ({e.code}): {e.detail}"

    want_inserted = list(expect["inserted"])
    got_inserted = list(alignment.inserted_indices)
    if got_inserted != want_inserted:
        return False, f"Insert: inserted {got_inserted} != {want_inserted}"
    want_revised = sorted(set(expect.get("positions", [])) - set(want_inserted))
    got_revised = sorted(alignment.revised_indices)
    if got_revised != want_revised:
        return False, f"Insert: revised {got_revised} != {want_revised}"
    # Production builds inserted | revised (D3); a case whose positions omit an
    # inserted slide would otherwise pass while production builds more than it names.
    built = sorted(set(got_inserted) | set(got_revised))
    want_built = sorted(set(expect.get("positions", [])))
    if built != want_built:
        return False, f"Insert: production builds {built} != positions {want_built}"

    for field in DECK_LEVEL_FIELDS:
        if getattr(output, field) != getattr(ref_deck, field):
            return False, f"Insert: deck-level field {field} {_RE_REVIEW}"
    if output.design_contract != ref_deck.design_contract:
        return False, f"Insert: deck-level field design_contract {_RE_REVIEW}"

    rationale = (
        f"Architect intent and insert alignment match "
        f"(inserted {got_inserted}, revised {got_revised})")
    targets = structured.get("target_positions")
    if isinstance(targets, list):
        want_targets = sorted(set(expect.get("positions", [])))
        try:
            got_targets = sorted(set(targets))
        except TypeError:
            got_targets = targets
        if got_targets != want_targets:
            rationale += (
                f"; model target_positions {got_targets} differ from {want_targets} "
                "(production ignores them on an insert)")
    return True, rationale


def expected_category_score(
    agent_key: str,
    structured: dict,
    expect: dict,
    *,
    reference: dict | None = None,
    current_deck_spec: dict | None = None,
) -> tuple[bool, str]:
    """Role-dispatched expected category scorer.

    - architect: checks intent match, and for edit mode, target_positions match positions (as sets).
      An edit case whose ``expect`` has ``"inserted"`` is scored by ``_insert_score`` instead, which
      needs the case's ``reference`` output and the payload's ``current_deck_spec``.
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

        # An insert is scored with production's own alignment, not the model's targets
        if structured.get("intent") == "edit" and "inserted" in expect:
            return _insert_score(structured, expect, reference, current_deck_spec)

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

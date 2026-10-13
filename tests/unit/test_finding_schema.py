"""Tests for src/domain/finding.py — the canonical finding schema (B1.1).

Each test maps to an assertion in the B1.1 brief's test-intent table.
The inline comments name the row in that table so the correspondence is clear.
"""

import pytest
from pydantic import ValidationError

from src.api.services.slide_repository import is_placeholder_record
from src.domain.finding import (
    CRITERIA,
    VERDICT_KEY,
    DeckReviewOutput,
    Finding,
    FindingCriterion,
    SlideReviewOutput,
    build_verification_record,
    findings_from_record,
    make_finding_id,
)
from src.utils.slide_hash import compute_slide_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_overflow_finding(slide_index: int = 0, ordinal: int = 0) -> Finding:
    """Convenience: a valid objective slide finding."""
    h = compute_slide_hash(f"<div class='slide'>slide {slide_index}</div>")
    return Finding(
        id=make_finding_id("overflow", h, ordinal),
        slide_index=slide_index,
        category="design",
        criterion="overflow",
        message=f"overflow finding {ordinal}",
        objective=True,
    )


def _make_arc_gap_finding() -> Finding:
    """Convenience: a valid subjective deck finding."""
    deck_hash = compute_slide_hash("<deck>whole deck</deck>")
    return Finding(
        id=make_finding_id("arc_gap", deck_hash, 0),
        slide_index=-1,
        category="narrative",
        criterion="arc_gap",
        message="arc gap in transition from slide 3 to slide 4",
        objective=False,
    )


# ---------------------------------------------------------------------------
# §A2 registry snapshot
# ---------------------------------------------------------------------------


class TestCriteriaRegistry:
    """Brief row: 'every criterion's category is one of the three'
    and 'slide criteria are objective-heavy; deck criteria are all narrative and subjective'.
    """

    _EXPECTED = {
        # name: (category, level, objective)
        "overflow":              ("design",    "slide", True),
        "contrast_failure":      ("design",    "slide", True),
        "rogue_colour":          ("design",    "slide", True),
        "distorted_image":       ("design",    "slide", True),
        "source_contradiction":  ("content",   "slide", True),
        "brief_not_delivered":   ("content",   "slide", False),
        "arc_gap":               ("narrative", "deck",  False),
        "cross_slide_repetition": ("narrative", "deck", False),
        "missing_conclusion":    ("narrative", "deck",  False),
    }

    def test_registry_has_exactly_the_a2_criteria(self):
        """CRITERIA contains exactly the nine criteria from §A2 — no more, no fewer."""
        assert set(CRITERIA.keys()) == set(self._EXPECTED.keys()), (
            f"Registry keys mismatch.\n"
            f"  Extra:   {set(CRITERIA.keys()) - set(self._EXPECTED.keys())}\n"
            f"  Missing: {set(self._EXPECTED.keys()) - set(CRITERIA.keys())}"
        )

    def test_each_criterion_has_correct_attributes(self):
        """Every criterion's category, level, and objective match §A2 verbatim."""
        for name, (cat, level, obj) in self._EXPECTED.items():
            c = CRITERIA[name]
            assert c.category == cat,   f"{name}: expected category {cat!r}, got {c.category!r}"
            assert c.level == level,    f"{name}: expected level {level!r}, got {c.level!r}"
            assert c.objective is obj,  f"{name}: expected objective={obj}, got {c.objective}"

    def test_deck_criteria_are_all_narrative_and_subjective(self):
        """Brief row: deck criteria are all narrative and subjective (objective=False)."""
        deck_criteria = {n: c for n, c in CRITERIA.items() if c.level == "deck"}
        assert deck_criteria, "Expected at least one deck-level criterion"
        for name, c in deck_criteria.items():
            assert c.category == "narrative", (
                f"Deck criterion {name!r} should be 'narrative', got {c.category!r}"
            )
            assert c.objective is False, (
                f"Deck criterion {name!r} should be subjective (objective=False), got True"
            )

    def test_slide_criteria_are_objective_heavy(self):
        """Brief row: slide criteria are objective-heavy (most are objective=True)."""
        slide_criteria = [c for c in CRITERIA.values() if c.level == "slide"]
        objective_count = sum(1 for c in slide_criteria if c.objective)
        subjective_count = sum(1 for c in slide_criteria if not c.objective)
        assert objective_count > subjective_count, (
            f"Expected more objective slide criteria than subjective, "
            f"got {objective_count} objective, {subjective_count} subjective"
        )


# ---------------------------------------------------------------------------
# ID stability — both halves of §K9
# ---------------------------------------------------------------------------


class TestFindingId:
    """Brief row: 'an id is stable for the same (criterion, hash) and changes when the hash changes'."""

    def test_id_is_stable_for_same_inputs(self):
        h = compute_slide_hash("<div class='slide'>hello world</div>")
        id1 = make_finding_id("overflow", h, 0)
        id2 = make_finding_id("overflow", h, 0)
        assert id1 == id2, "Same inputs must produce the same id (stability)"

    def test_id_changes_when_hash_changes(self):
        h1 = compute_slide_hash("<div class='slide'>content A</div>")
        h2 = compute_slide_hash("<div class='slide'>content B</div>")
        assert h1 != h2, "Precondition: different content must hash differently"
        id1 = make_finding_id("overflow", h1, 0)
        id2 = make_finding_id("overflow", h2, 0)
        assert id1 != id2, "Id must change when the subject hash changes"

    def test_id_changes_when_ordinal_changes(self):
        h = compute_slide_hash("<div class='slide'>same slide</div>")
        id0 = make_finding_id("overflow", h, 0)
        id1 = make_finding_id("overflow", h, 1)
        assert id0 != id1, "Different ordinals must produce different ids"


# ---------------------------------------------------------------------------
# Collision guard — round-trip through build_verification_record
# ---------------------------------------------------------------------------


class TestTwoFindingsSameCriterionRoundTrip:
    """Brief row: 'two findings of the same criterion on one subject get different ids,
    asserted by round-tripping them through build_verification_record'.
    Going through the record is what catches a caller that omitted the ordinal argument.
    """

    def test_two_overflow_findings_survive_round_trip_with_distinct_ids(self):
        h = compute_slide_hash("<div class='slide'>overflowing slide</div>")
        f1 = Finding(
            id=make_finding_id("overflow", h, 0),
            slide_index=2,
            category="design",
            criterion="overflow",
            message="text overflows right margin",
            objective=True,
        )
        f2 = Finding(
            id=make_finding_id("overflow", h, 1),
            slide_index=2,
            category="design",
            criterion="overflow",
            message="image overflows bottom margin",
            objective=True,
        )

        assert f1.id != f2.id, "Different ordinals must produce different ids"

        record = build_verification_record(content_hash=h, findings=[f1, f2], verdict="surfaced")
        recovered = findings_from_record(record, h)

        assert len(recovered) == 2, (
            f"Both findings must survive the round-trip, got {len(recovered)}"
        )
        recovered_ids = {f.id for f in recovered}
        assert f1.id in recovered_ids, f"f1.id {f1.id!r} missing from recovered ids"
        assert f2.id in recovered_ids, f"f2.id {f2.id!r} missing from recovered ids"


# ---------------------------------------------------------------------------
# Registry validation on Finding construction
# ---------------------------------------------------------------------------


class TestFindingRegistryValidation:
    """Brief row: 'a Finding with an unknown criterion is rejected;
    one whose category contradicts the registry is rejected'.
    """

    def test_unknown_criterion_is_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            Finding(
                id="x:hash:0",
                slide_index=0,
                category="design",
                criterion="nonexistent_criterion",
                message="something",
                objective=True,
            )
        assert "Unknown criterion" in str(exc_info.value), (
            f"Expected 'Unknown criterion' in error, got: {exc_info.value}"
        )

    def test_category_contradicting_registry_is_rejected(self):
        # "overflow" is registered as "design"; passing "content" must be rejected.
        with pytest.raises(ValidationError) as exc_info:
            Finding(
                id="x:hash:0",
                slide_index=0,
                category="content",       # wrong — registry says "design"
                criterion="overflow",
                message="overflow text",
                objective=True,
            )
        assert "overflow" in str(exc_info.value), (
            f"Expected criterion name in error message, got: {exc_info.value}"
        )

    def test_valid_finding_constructs_without_error(self):
        """Baseline: a fully correct finding must not raise."""
        h = compute_slide_hash("<div class='slide'>valid</div>")
        f = Finding(
            id=make_finding_id("overflow", h, 0),
            slide_index=0,
            category="design",
            criterion="overflow",
            message="text overflows",
            objective=True,
        )
        assert f.criterion == "overflow"
        assert f.category == "design"


# ---------------------------------------------------------------------------
# objective and status are independent
# ---------------------------------------------------------------------------


class TestObjectiveAndStatusAreIndependent:
    """Brief row: 'objective and status are independent'.
    The superseded plan's auto_fixable conflated predicate and state, making §F2
    unimplementable.
    """

    def test_objective_true_status_fixed(self):
        """An automated fixer may mark an objective finding fixed."""
        f = _make_overflow_finding()
        f2 = f.model_copy(update={"status": "fixed"})
        assert f2.objective is True
        assert f2.status == "fixed"

    def test_objective_false_status_open(self):
        """A subjective finding starts open; human decides."""
        f = _make_arc_gap_finding()
        assert f.objective is False
        assert f.status == "open"

    def test_objective_false_status_fixed(self):
        """A subjective finding can be marked fixed (e.g. human reviewer acted)."""
        f = _make_arc_gap_finding()
        f2 = f.model_copy(update={"status": "fixed"})
        assert f2.objective is False
        assert f2.status == "fixed"

    def test_objective_true_status_open(self):
        """Default state is open regardless of objective flag."""
        f = _make_overflow_finding()
        assert f.objective is True
        assert f.status == "open"


# ---------------------------------------------------------------------------
# Constraint 2 — is_placeholder_record is False for all SlideVerdict values
# ---------------------------------------------------------------------------


class TestIsPlaceholderRecordFalseForAllVerdicts:
    """Brief row: 'is_placeholder_record(build_verification_record(...)) is False
    for every SlideVerdict value'.

    'placeholder' was removed from SlideVerdict, so no reachable verdict can
    produce a placeholder record.  Placeholders come only from commit_placeholder
    (ws4c/d), which writes error:True.  That path is asserted separately below.
    """

    @pytest.mark.parametrize("verdict", ["clean", "fixed", "surfaced"])
    def test_not_a_placeholder_for_verdict(self, verdict):
        h = compute_slide_hash(f"<div class='slide'>content for {verdict}</div>")
        record = build_verification_record(
            content_hash=h,
            findings=[],
            verdict=verdict,
        )
        assert is_placeholder_record(record) is False, (
            f"build_verification_record with verdict={verdict!r} must not read "
            f"as a placeholder.  Record: {record}"
        )

    def test_not_a_placeholder_with_findings(self):
        """Constraint holds when the record contains actual findings."""
        h = compute_slide_hash("<div class='slide'>slide with findings</div>")
        f = Finding(
            id=make_finding_id("overflow", h, 0),
            slide_index=1,
            category="design",
            criterion="overflow",
            message="text overflows",
            objective=True,
        )
        record = build_verification_record(content_hash=h, findings=[f], verdict="surfaced")
        assert is_placeholder_record(record) is False, (
            f"Record with real findings must not read as a placeholder.  Record: {record}"
        )


# ---------------------------------------------------------------------------
# Constraint 3 — record's only top-level key is the content hash
# ---------------------------------------------------------------------------


class TestRecordTopLevelKey:
    """Brief row: 'the record's only top-level key is the content hash'.

    get_verification_map merges per-row records into one flat {content_hash: verdict}
    dict; anything keyed otherwise is silently lost.
    """

    def test_record_has_exactly_one_top_level_key(self):
        h = compute_slide_hash("<div class='slide'>key check</div>")
        record = build_verification_record(content_hash=h, findings=[], verdict="clean")
        assert list(record.keys()) == [h], (
            f"Expected only the content_hash as top-level key, got: {list(record.keys())}"
        )

    def test_top_level_key_is_the_supplied_hash(self):
        h = "deadbeef12345678"   # arbitrary but plausible hash string
        record = build_verification_record(content_hash=h, findings=[], verdict="clean")
        assert h in record, f"Content hash {h!r} must be a key in the record"
        assert len(record) == 1, f"Record must have exactly 1 key, got {len(record)}"


# ---------------------------------------------------------------------------
# Round-trip: findings survive serialisation and reconstruction
# ---------------------------------------------------------------------------


class TestFindingsRoundTrip:
    """Brief row: 'findings round-trip through the record'."""

    def test_finding_round_trips_through_record(self):
        h = compute_slide_hash("<div class='slide'>round trip content</div>")
        original = Finding(
            id=make_finding_id("contrast_failure", h, 0),
            slide_index=3,
            category="design",
            criterion="contrast_failure",
            message="white text on pale background",
            objective=True,
            status="open",
            seen=False,
        )
        record = build_verification_record(content_hash=h, findings=[original], verdict="surfaced")
        recovered = findings_from_record(record, h)

        assert len(recovered) == 1, f"Expected 1 finding after round-trip, got {len(recovered)}"
        r = recovered[0]
        assert r.id == original.id
        assert r.slide_index == original.slide_index
        assert r.category == original.category
        assert r.criterion == original.criterion
        assert r.message == original.message
        assert r.objective == original.objective
        assert r.status == original.status
        assert r.seen == original.seen

    def test_missing_hash_returns_empty_list(self):
        record = build_verification_record(content_hash="abc", findings=[], verdict="clean")
        assert findings_from_record(record, "different_hash") == []

    def test_empty_findings_round_trip(self):
        h = compute_slide_hash("<div class='slide'>empty</div>")
        record = build_verification_record(content_hash=h, findings=[], verdict="clean")
        assert findings_from_record(record, h) == []

    def test_deck_finding_round_trips(self):
        """Deck-level findings (slide_index=-1) must survive round-trip."""
        deck_hash = compute_slide_hash("<deck>full deck content</deck>")
        f = Finding(
            id=make_finding_id("arc_gap", deck_hash, 0),
            slide_index=-1,
            category="narrative",
            criterion="arc_gap",
            message="jump from slide 3 to slide 5 unexplained",
            objective=False,
        )
        record = build_verification_record(content_hash=deck_hash, findings=[f], verdict="surfaced")
        recovered = findings_from_record(record, deck_hash)
        assert len(recovered) == 1
        assert recovered[0].slide_index == -1
        assert recovered[0].criterion == "arc_gap"


# ---------------------------------------------------------------------------
# PR1 backward compatibility — placeholder shape still reads as a placeholder
# ---------------------------------------------------------------------------


class TestPlaceholderShapeBackwardCompatibility:
    """Brief row: 'PR1's placeholder shape still reads as a placeholder'.
    The other direction — don't break what works.
    """

    def test_hash_keyed_placeholder_is_detected(self):
        """The canonical PR1/ws4c placeholder shape: {content_hash: {error: True, message: ...}}."""
        placeholder_record = {
            "somehash1234abcd": {"error": True, "message": "slide generation failed"}
        }
        assert is_placeholder_record(placeholder_record) is True, (
            "The hash-keyed placeholder shape must still be detected as a placeholder"
        )

    def test_top_level_error_placeholder_is_detected(self):
        """Single resolved verdict (get_slide_deck's slide['verification']) shape."""
        single_verdict = {"error": True, "message": "placeholder"}
        assert is_placeholder_record(single_verdict) is True

    def test_none_is_not_a_placeholder(self):
        assert is_placeholder_record(None) is False

    def test_empty_dict_is_not_a_placeholder(self):
        assert is_placeholder_record({}) is False


# ---------------------------------------------------------------------------
# SlideReviewOutput and DeckReviewOutput split properties
# ---------------------------------------------------------------------------


class TestReviewOutputSplits:
    """Verify the objective/subjective split properties on SlideReviewOutput."""

    def test_objective_findings_split(self):
        h = compute_slide_hash("<div class='slide'>split test</div>")
        f_obj = Finding(
            id=make_finding_id("overflow", h, 0),
            slide_index=0, category="design", criterion="overflow",
            message="overflow", objective=True,
        )
        f_subj = Finding(
            id=make_finding_id("brief_not_delivered", h, 0),
            slide_index=0, category="content", criterion="brief_not_delivered",
            message="brief not delivered", objective=False,
        )
        out = SlideReviewOutput(slide_index=0, verdict="surfaced", findings=[f_obj, f_subj])
        assert out.objective_findings == [f_obj]
        assert out.subjective_findings == [f_subj]

    def test_deck_review_output_constructs(self):
        f = _make_arc_gap_finding()
        out = DeckReviewOutput(findings=[f])
        assert len(out.findings) == 1
        assert out.findings[0].criterion == "arc_gap"

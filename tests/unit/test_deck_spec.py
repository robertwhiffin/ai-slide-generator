"""Tests for src/domain/deck_spec.py.

Covers:
- Five validator rejections (mutual exclusion, template dependency, empty title,
  whitespace title, duplicate positions)
- slide_at by position including a gap in the sequence
- JSON round-trip lossless
- from_json tolerates None, empty string, malformed JSON and a partial object
- review-criteria fields absent on DeckSpec
"""

import json

import pytest
from pydantic import ValidationError

from src.domain.deck_spec import (
    DesignContractRef,
    DeckSpec,
    ResolvedData,
    ResolvedFigure,
    SlideSpec,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _minimal_contract(**overrides) -> dict:
    base = {"design_system_id": None, "template_id": None, "slide_style_id": None}
    base.update(overrides)
    return base


def _minimal_resolved_data() -> dict:
    return {"synthesis": "Solid data.", "figures": [], "gaps": []}


def _minimal_slide(position: int = 0) -> dict:
    return {
        "position": position,
        "purpose": "Introduce the topic",
        "content_brief": "Cover the key metrics.",
        "assumes": "Audience knows Python.",
        "hands_off": "Next slide assumes this section was completed.",
        "data_references": [],
        "template_section_index": None,
    }


def _valid_deck(**overrides) -> dict:
    base = {
        "title": "Q3 Business Review",
        "audience": "C-suite executives",
        "purpose": "Communicate quarterly progress",
        "argument": "We are on track for the year",
        "call_to_action": "Approve the budget increase",
        "narrative_arc": ["Context", "Evidence", "Ask"],
        "design_contract": _minimal_contract(),
        "resolved_data": _minimal_resolved_data(),
        "slides": [_minimal_slide(0), _minimal_slide(1)],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# DesignContractRef — mutual exclusion (L1)
# ---------------------------------------------------------------------------

class TestDesignContractRefMutualExclusion:
    """design_system_id and slide_style_id are mutually exclusive."""

    def test_both_set_raises_validation_error(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            DesignContractRef(design_system_id=1, slide_style_id=2)

    def test_only_design_system_id_accepted(self):
        ref = DesignContractRef(design_system_id=1)
        assert ref.design_system_id == 1
        assert ref.slide_style_id is None

    def test_only_slide_style_id_accepted(self):
        ref = DesignContractRef(slide_style_id=3)
        assert ref.slide_style_id == 3
        assert ref.design_system_id is None

    def test_neither_set_accepted(self):
        ref = DesignContractRef()
        assert ref.design_system_id is None
        assert ref.slide_style_id is None


# ---------------------------------------------------------------------------
# DesignContractRef — template_id requires design_system_id (L3)
# ---------------------------------------------------------------------------

class TestDesignContractRefTemplateRequiresDesignSystem:
    """template_id without design_system_id is invalid."""

    def test_template_without_design_system_raises(self):
        with pytest.raises(ValidationError, match="template_id requires design_system_id"):
            DesignContractRef(template_id=5)

    def test_template_with_design_system_accepted(self):
        ref = DesignContractRef(design_system_id=1, template_id=5)
        assert ref.template_id == 5
        assert ref.design_system_id == 1

    def test_template_none_without_design_system_accepted(self):
        ref = DesignContractRef()
        assert ref.template_id is None


# ---------------------------------------------------------------------------
# DeckSpec — title must be non-empty (H1)
# ---------------------------------------------------------------------------

class TestDeckSpecTitleValidation:
    """title rejects empty and whitespace-only strings."""

    def test_empty_string_title_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            DeckSpec(**_valid_deck(title=""))

    def test_spaces_only_title_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            DeckSpec(**_valid_deck(title="   "))

    def test_tab_and_newline_title_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            DeckSpec(**_valid_deck(title="\t\n"))

    def test_valid_title_accepted(self):
        deck = DeckSpec(**_valid_deck(title="Q3 Review"))
        assert deck.title == "Q3 Review"


# ---------------------------------------------------------------------------
# DeckSpec — slide positions must be unique
# ---------------------------------------------------------------------------

class TestDeckSpecSlidePositionsUnique:
    """Duplicate positions within the slides list are rejected."""

    def test_duplicate_positions_raise_validation_error(self):
        slides = [_minimal_slide(0), _minimal_slide(0)]
        with pytest.raises(ValidationError, match="unique"):
            DeckSpec(**_valid_deck(slides=slides))

    def test_unique_positions_accepted(self):
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        assert len(deck.slides) == 3


# ---------------------------------------------------------------------------
# DeckSpec.slide_at — by position, not by list index
# ---------------------------------------------------------------------------

class TestDeckSpecSlideAt:
    """slide_at must look up by the position field, never by list index.

    The key test is a sequence WITH A GAP (positions 0, 1, 3): an index-based
    implementation would return slides[3] (IndexError / None) when asked for
    position 3, or slides[2] (position 1) if it wraps — both wrong.
    """

    def test_finds_existing_position(self):
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        result = deck.slide_at(1)
        assert result is not None
        assert result.position == 1

    def test_finds_position_past_the_gap(self):
        """Position 3 is the 3rd slide (index 2), not the 4th (index 3).

        An index-based implementation for slide_at(3) would do slides[3]
        which either raises IndexError (no 4th slide) or returns the wrong
        slide.
        """
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        result = deck.slide_at(3)
        assert result is not None, (
            "slide_at(3) returned None — likely an index-based implementation "
            "(slides[3] raises IndexError; slides[2].position==1, not 3)"
        )
        assert result.position == 3

    def test_gap_position_returns_none(self):
        """Position 2 does not exist in the sequence 0, 1, 3."""
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        assert deck.slide_at(2) is None

    def test_returns_none_for_completely_absent_position(self):
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        assert deck.slide_at(99) is None

    def test_slide_at_position_zero(self):
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        result = deck.slide_at(0)
        assert result is not None
        assert result.position == 0


# ---------------------------------------------------------------------------
# DeckSpec — JSON round-trip
# ---------------------------------------------------------------------------

class TestDeckSpecJsonRoundTrip:
    """to_json / from_json must be lossless."""

    def test_to_json_returns_a_string(self):
        deck = DeckSpec(**_valid_deck())
        result = deck.to_json()
        assert isinstance(result, str)

    def test_round_trip_is_lossless(self):
        deck = DeckSpec(**_valid_deck())
        restored = DeckSpec.from_json(deck.to_json())
        assert restored is not None
        assert restored == deck

    def test_round_trip_preserves_gap_sequence(self):
        slides = [_minimal_slide(0), _minimal_slide(1), _minimal_slide(3)]
        deck = DeckSpec(**_valid_deck(slides=slides))
        restored = DeckSpec.from_json(deck.to_json())
        assert restored is not None
        assert restored.slide_at(3) is not None
        assert restored.slide_at(3).position == 3
        assert restored.slide_at(2) is None

    def test_to_json_output_is_valid_json(self):
        deck = DeckSpec(**_valid_deck())
        parsed = json.loads(deck.to_json())
        assert parsed["title"] == deck.title


# ---------------------------------------------------------------------------
# DeckSpec.from_json — never raises
# ---------------------------------------------------------------------------

class TestDeckSpecFromJsonNeverRaises:
    """from_json returns None rather than raising for every bad input."""

    def test_none_returns_none(self):
        assert DeckSpec.from_json(None) is None

    def test_empty_string_returns_none(self):
        assert DeckSpec.from_json("") is None

    def test_malformed_json_returns_none(self):
        assert DeckSpec.from_json("{not valid json at all") is None

    def test_partial_object_missing_required_fields_returns_none(self):
        partial = json.dumps({"title": "Incomplete deck"})
        assert DeckSpec.from_json(partial) is None

    def test_wrong_type_for_required_field_returns_none(self):
        bad = {**_valid_deck(), "title": None}
        assert DeckSpec.from_json(json.dumps(bad)) is None

    def test_valid_json_parses_to_deck_spec(self):
        deck = DeckSpec(**_valid_deck())
        result = DeckSpec.from_json(deck.to_json())
        assert result is not None
        assert result.title == deck.title


# ---------------------------------------------------------------------------
# Review criteria are NOT spec fields
# ---------------------------------------------------------------------------

class TestReviewCriteriaAbsent:
    """Assert the absence of review-criteria fields on DeckSpec.

    If a later contributor helpfully adds one of these names, these tests fail.
    The field names to check: review_criteria, criteria, rubric, quality_bar.
    """

    def test_review_criteria_field_absent(self):
        assert "review_criteria" not in DeckSpec.model_fields, (
            "review_criteria must not be a field on DeckSpec"
        )

    def test_criteria_field_absent(self):
        assert "criteria" not in DeckSpec.model_fields, (
            "criteria must not be a field on DeckSpec"
        )

    def test_rubric_field_absent(self):
        assert "rubric" not in DeckSpec.model_fields, (
            "rubric must not be a field on DeckSpec"
        )

    def test_quality_bar_field_absent(self):
        assert "quality_bar" not in DeckSpec.model_fields, (
            "quality_bar must not be a field on DeckSpec"
        )

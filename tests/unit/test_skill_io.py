"""Tests for src/domain/skill_io.py — the five remaining skill output schemas (B1.5).

Each test maps to a row in B1.5's load-bearing-validators table or a test-intent
bullet in the brief.  Inline comments name the relevant row/bullet.

SABOTAGE VERIFICATION is performed in a separate manual pass (see report-B1.5.md).
Each validator that must survive sabotage is called out with a ``# SABOTAGE TARGET``
comment so the sabotage table can reference exact lines.
"""

from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import BaseModel, ValidationError

from src.domain.deck_spec import DeckSpec, DesignContractRef, ResolvedData, SlideSpec
from src.domain.finding import DeckReviewOutput, SlideReviewOutput
from src.domain.skill_io import (
    AnalystOutput,
    ArchitectOutput,
    BuilderOutput,
    DataRequest,
    FixerOutput,
    OUTPUT_SCHEMAS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_design_contract() -> DesignContractRef:
    return DesignContractRef(slide_style_id=1)


def _minimal_resolved_data() -> ResolvedData:
    from src.domain.deck_spec import ResolvedData, ResolvedFigure
    return ResolvedData(synthesis="ok", figures=[], gaps=[])


def _minimal_slide_spec(position: int = 1) -> SlideSpec:
    return SlideSpec(
        position=position,
        purpose="intro",
        content_brief="brief",
        assumes="nothing",
        hands_off="nothing",
        data_references=[],
    )


def _minimal_deck_spec() -> DeckSpec:
    return DeckSpec(
        title="Test Deck",
        audience="devs",
        purpose="test",
        argument="arg",
        call_to_action="cta",
        narrative_arc=["intro", "body", "close"],
        design_contract=_minimal_design_contract(),
        resolved_data=_minimal_resolved_data(),
        slides=[_minimal_slide_spec(1)],
    )


def _minimal_data_request() -> DataRequest:
    return DataRequest(metric="revenue")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestOutputSchemaRegistry:
    """All seven skill names are present, each mapping to a BaseModel subclass."""

    EXPECTED_KEYS = {
        "architect",
        "data_analyst",
        "builder",
        "fixer",
        "build_reviewer",
        "fix_reviewer",
        "deck_reviewer",
    }

    def test_registry_has_exactly_seven_entries(self):
        assert len(OUTPUT_SCHEMAS) == 7

    def test_all_expected_keys_present(self):
        assert set(OUTPUT_SCHEMAS.keys()) == self.EXPECTED_KEYS

    def test_every_value_is_basemodel_subclass(self):
        for name, cls in OUTPUT_SCHEMAS.items():
            assert issubclass(cls, BaseModel), (
                f"OUTPUT_SCHEMAS[{name!r}] = {cls!r} is not a BaseModel subclass"
            )

    def test_reviewer_classes_match_imports(self):
        """build_reviewer and fix_reviewer share SlideReviewOutput; deck_reviewer has DeckReviewOutput."""
        assert OUTPUT_SCHEMAS["build_reviewer"] is SlideReviewOutput
        assert OUTPUT_SCHEMAS["fix_reviewer"] is SlideReviewOutput
        assert OUTPUT_SCHEMAS["deck_reviewer"] is DeckReviewOutput


# ---------------------------------------------------------------------------
# ArchitectOutput — intent/payload consistency
# ---------------------------------------------------------------------------


class TestArchitectIntentPayload:
    """Each intent's payload is what the router acts on — §4.6/§M1."""

    # SABOTAGE TARGET: _intent_payload_consistency validator in skill_io.py

    def test_discuss_needs_no_payload(self):
        """PRD §4.1: a substantive shaping conversation with zero slides."""
        out = ArchitectOutput(intent="discuss", message="hello")
        assert out.intent == "discuss"
        assert out.deck_spec is None
        assert out.data_request is None
        assert out.target_positions == []
        assert out.proposed_design_contract is None

    def test_build_requires_deck_spec(self):
        with pytest.raises(ValidationError) as exc_info:
            ArchitectOutput(intent="build", message="build it")
        assert "intent='build' requires deck_spec" in str(exc_info.value)

    def test_build_succeeds_with_deck_spec(self):
        out = ArchitectOutput(
            intent="build",
            message="build it",
            deck_spec=_minimal_deck_spec(),
        )
        assert out.intent == "build"
        assert out.deck_spec is not None

    def test_ask_data_requires_data_request(self):
        with pytest.raises(ValidationError) as exc_info:
            ArchitectOutput(intent="ask_data", message="get me data")
        assert "intent='ask_data' requires data_request" in str(exc_info.value)

    def test_ask_data_succeeds_with_data_request(self):
        out = ArchitectOutput(
            intent="ask_data",
            message="get revenue",
            data_request=_minimal_data_request(),
        )
        assert out.intent == "ask_data"
        assert out.data_request.metric == "revenue"

    def test_edit_requires_target_positions(self):
        with pytest.raises(ValidationError) as exc_info:
            ArchitectOutput(intent="edit", message="fix slide 3")
        assert "intent='edit' requires" in str(exc_info.value)

    def test_edit_with_empty_list_rejected(self):
        """Explicitly passing an empty list still triggers the guard."""
        with pytest.raises(ValidationError) as exc_info:
            ArchitectOutput(intent="edit", message="fix", target_positions=[])
        assert "intent='edit' requires" in str(exc_info.value)

    def test_edit_succeeds_with_target_positions(self):
        out = ArchitectOutput(
            intent="edit",
            message="fix slide 3",
            target_positions=[3],
        )
        assert out.intent == "edit"
        assert out.target_positions == [3]

    def test_confirm_design_contract_requires_proposed(self):
        with pytest.raises(ValidationError) as exc_info:
            ArchitectOutput(intent="confirm_design_contract", message="use this brand")
        assert "intent='confirm_design_contract' requires proposed_design_contract" in str(
            exc_info.value
        )

    def test_confirm_design_contract_not_in_deck_spec(self):
        """§M1: hold in proposed_design_contract, never deck_spec (no restyle before user answers)."""
        out = ArchitectOutput(
            intent="confirm_design_contract",
            message="use this brand",
            proposed_design_contract=_minimal_design_contract(),
        )
        assert out.intent == "confirm_design_contract"
        assert out.proposed_design_contract is not None
        assert out.deck_spec is None  # deliberately absent

    def test_confirm_design_contract_with_deck_spec_also_set_is_accepted(self):
        """No validator forbids deck_spec being set alongside proposed_design_contract.
        The requirement is only that proposed_design_contract must be present."""
        out = ArchitectOutput(
            intent="confirm_design_contract",
            message="brand change",
            proposed_design_contract=_minimal_design_contract(),
            deck_spec=_minimal_deck_spec(),
        )
        assert out.intent == "confirm_design_contract"


# ---------------------------------------------------------------------------
# AnalystOutput — outcome semantics
# ---------------------------------------------------------------------------


class TestAnalystOutcome:
    """§5.2.2 — three outcomes; success requires both synthesis and sources."""

    # SABOTAGE TARGET: _success_requires_synthesis_and_sources validator

    def test_success_requires_synthesis(self):
        with pytest.raises(ValidationError) as exc_info:
            AnalystOutput(outcome="success", sources=["s1"])
        assert "outcome='success' requires synthesis" in str(exc_info.value)

    def test_success_requires_sources(self):
        with pytest.raises(ValidationError) as exc_info:
            AnalystOutput(outcome="success", synthesis="here is what I found")
        assert "outcome='success' requires sources" in str(exc_info.value)

    def test_success_requires_both(self):
        with pytest.raises(ValidationError) as exc_info:
            AnalystOutput(outcome="success")
        error_str = str(exc_info.value)
        # At least one of the two guard messages appears
        assert (
            "outcome='success' requires synthesis" in error_str
            or "outcome='success' requires sources" in error_str
        )

    def test_success_with_both_fields_accepted(self):
        out = AnalystOutput(
            outcome="success",
            synthesis="Revenue grew 12% YoY.",
            sources=["salesforce", "databricks"],
        )
        assert out.outcome == "success"
        assert out.synthesis
        assert len(out.sources) == 2

    def test_missing_data_needs_no_synthesis_or_sources(self):
        out = AnalystOutput(outcome="missing_data")
        assert out.outcome == "missing_data"
        assert out.synthesis is None
        assert out.sources is None

    def test_no_tool_needs_no_synthesis_or_sources(self):
        out = AnalystOutput(outcome="no_tool")
        assert out.outcome == "no_tool"

    def test_outcome_is_closed_union(self):
        """Invalid outcome values are rejected (§5.2.2's three outcomes are the contract)."""
        with pytest.raises(ValidationError):
            AnalystOutput(outcome="error")

    def test_outcome_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            AnalystOutput(outcome="")

    def test_outcome_rejects_none(self):
        with pytest.raises(ValidationError):
            AnalystOutput(outcome=None)


# ---------------------------------------------------------------------------
# BuilderOutput — <style> element rejection + scripts type
# ---------------------------------------------------------------------------


class TestBuilderOutput:
    """§5.2.3 — no <style> element; scripts is str not Optional[str]."""

    # SABOTAGE TARGET: _no_style_element validator and scripts field annotation

    def test_valid_html_accepted(self):
        out = BuilderOutput(
            position=1,
            html='<div class="slide"><p>Hello</p></div>',
            scripts="",
        )
        assert out.position == 1

    def test_style_tag_rejected_lowercase(self):
        """Most common case: <style> element in output."""
        with pytest.raises(ValidationError) as exc_info:
            BuilderOutput(
                position=1,
                html='<div class="slide"><style>.foo{color:red}</style></div>',
                scripts="",
            )
        assert "must not contain a <style> element" in str(exc_info.value)

    def test_style_tag_rejected_uppercase(self):
        """The check must catch <STYLE> not just <style>."""
        with pytest.raises(ValidationError) as exc_info:
            BuilderOutput(
                position=1,
                html='<div class="slide"><STYLE>.foo{color:red}</STYLE></div>',
                scripts="",
            )
        assert "must not contain a <style> element" in str(exc_info.value)

    def test_style_tag_rejected_with_leading_whitespace(self):
        """< style > with whitespace around the tag name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            BuilderOutput(
                position=1,
                html='<div class="slide">< style >.foo{color:red}</ style ></div>',
                scripts="",
            )
        assert "must not contain a <style> element" in str(exc_info.value)

    def test_style_tag_rejected_with_attribute(self):
        """<style type="text/css"> is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            BuilderOutput(
                position=1,
                html='<div class="slide"><style type="text/css">.x{}</style></div>',
                scripts="",
            )
        assert "must not contain a <style> element" in str(exc_info.value)

    def test_style_attribute_is_not_rejected(self):
        """A style= attribute (inline styling) is NOT the same as a <style> element."""
        out = BuilderOutput(
            position=1,
            html='<div class="slide"><p style="color:red">Hi</p></div>',
            scripts="",
        )
        assert out.html is not None

    def test_scripts_annotation_is_exactly_str(self):
        """Round-3 finding 26: scripts must be str, not Optional[str].

        This test would fail if someone changed the field to Optional[str]
        because the annotation would then be Optional[str] (i.e. str | None),
        not str.
        """
        # SABOTAGE TARGET: this exact assertion
        hints = get_type_hints(BuilderOutput)
        assert hints["scripts"] is str, (
            f"scripts annotation is {hints['scripts']!r}; expected str. "
            "Do not change this to Optional[str] — ws4d must match."
        )

    def test_scripts_default_is_empty_string(self):
        out = BuilderOutput(position=1, html="<div>hi</div>")
        assert out.scripts == ""

    def test_scripts_accepts_non_empty_string(self):
        out = BuilderOutput(
            position=1,
            html="<div>hi</div>",
            scripts="console.log('chart ready');",
        )
        assert out.scripts == "console.log('chart ready');"


# ---------------------------------------------------------------------------
# FixerOutput — inherits BuilderOutput validators
# ---------------------------------------------------------------------------


class TestFixerOutput:
    """FixerOutput extends BuilderOutput — validators are inherited."""

    def test_valid_fixer_output(self):
        out = FixerOutput(
            position=2,
            html='<div class="slide fixed"><p>Fixed</p></div>',
            scripts="",
            changed=True,
            change_summary="Removed overflow text",
        )
        assert out.changed is True
        assert out.change_summary == "Removed overflow text"

    def test_fixer_inherits_no_style_rule(self):
        """The <style> guard is inherited and still fires on FixerOutput."""
        with pytest.raises(ValidationError) as exc_info:
            FixerOutput(
                position=2,
                html='<div class="slide"><style>.x{}</style></div>',
                scripts="",
                changed=True,
            )
        assert "must not contain a <style> element" in str(exc_info.value)

    def test_fixer_scripts_annotation_is_str(self):
        """scripts annotation on FixerOutput (via inheritance) is exactly str."""
        hints = get_type_hints(FixerOutput)
        assert hints["scripts"] is str

    def test_fixer_unchanged(self):
        out = FixerOutput(
            position=1,
            html="<div>ok</div>",
            scripts="",
            changed=False,
        )
        assert out.changed is False
        assert out.change_summary == ""

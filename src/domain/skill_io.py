"""Output schemas and registry for the seven LangGraph skill nodes.

This module is pure Pydantic — no database imports.  It lives in src/domain/
and must stay that way.

Contract ownership
------------------
These five schemas (plus the two imported from finding.py) are the contracts
the LangGraph graph binds to in four places at once: reducers key off them,
the router reads their fields, the frontend types mirror them, and conformance
tests parse them.  Four later PRs (ws4c-e) read OUTPUT_SCHEMAS and are
forbidden from editing this file.

``scripts`` is ``str`` everywhere — this is the single place that type is
settled.  ws4d declares a ``scripts`` field on ``StreamEvent``; it must match.
An earlier draft had ``str`` in one place and ``Optional[str]`` in the other
and papered over it with a test that could never fail.  (Round-3 finding 26.)
"""

from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional, Type

from pydantic import BaseModel, field_validator, model_validator

from src.domain.deck_spec import DeckSpec, DesignContractRef
from src.domain.finding import DeckReviewOutput, SlideReviewOutput

# ---------------------------------------------------------------------------
# Primitive unions — CLOSED
# ---------------------------------------------------------------------------

ArchitectIntent = Literal[
    "discuss",
    "ask_data",
    "build",
    "edit",
    "confirm_design_contract",
]

# ---------------------------------------------------------------------------
# DataRequest
# ---------------------------------------------------------------------------


class DataRequest(BaseModel):
    """What the analyst skill must fetch for the architect.

    All fields except ``metric`` are optional so a partial request can be
    expressed (the analyst treats absent fields as unconstrained).
    """

    metric: str
    time_bound: Optional[str] = None
    grouping: Optional[str] = None
    units: Optional[str] = None
    tool_preferences: List[str] = []


# ---------------------------------------------------------------------------
# ArchitectOutput
# ---------------------------------------------------------------------------


class ArchitectOutput(BaseModel):
    """Output of the architect skill node.

    Invariants (§4.6/§M1)
    ----------------------
    - ``intent='build'``                     → ``deck_spec`` must be present
    - ``intent='ask_data'``                  → ``data_request`` must be present
    - ``intent='edit'``                      → ``target_positions`` must be non-empty
    - ``intent='confirm_design_contract'``   → ``proposed_design_contract`` must be present
    - ``intent='discuss'``                   → no payload required

    ``confirm_design_contract`` holds its proposal in ``proposed_design_contract``
    — never in ``deck_spec`` — so no downstream node restyles before the user
    answers (§4.6/§M1).
    """

    intent: ArchitectIntent
    message: str
    deck_spec: Optional[DeckSpec] = None
    data_request: Optional[DataRequest] = None
    target_positions: List[int] = []
    proposed_design_contract: Optional[DesignContractRef] = None

    @model_validator(mode="after")
    def _intent_payload_consistency(self) -> "ArchitectOutput":
        if self.intent == "build" and self.deck_spec is None:
            raise ValueError(
                "intent='build' requires deck_spec; "
                "the router acts on this field to fan out the builder nodes"
            )
        if self.intent == "ask_data" and self.data_request is None:
            raise ValueError(
                "intent='ask_data' requires data_request; "
                "the analyst node reads this to know what to fetch"
            )
        if self.intent == "edit" and not self.target_positions:
            raise ValueError(
                "intent='edit' requires a non-empty target_positions list; "
                "the router fans out one builder per position"
            )
        if (
            self.intent == "confirm_design_contract"
            and self.proposed_design_contract is None
        ):
            raise ValueError(
                "intent='confirm_design_contract' requires proposed_design_contract; "
                "hold the proposal here, never in deck_spec, until the user answers (§M1)"
            )
        return self


# ---------------------------------------------------------------------------
# AnalystOutput
# ---------------------------------------------------------------------------


class AnalystOutput(BaseModel):
    """Output of the data analyst skill node.

    Outcome semantics (§5.2.2)
    --------------------------
    - ``success``       → both ``synthesis`` and ``sources`` are required
    - ``missing_data``  → the analyst could not find the requested metrics
    - ``no_tool``       → no tool was available for this kind of data request
    """

    outcome: Literal["success", "missing_data", "no_tool"]
    synthesis: Optional[str] = None
    sources: Optional[List[str]] = None
    gap: Optional[str] = None
    tried_tools: List[str] = []
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _success_requires_synthesis_and_sources(self) -> "AnalystOutput":
        if self.outcome == "success":
            if not self.synthesis:
                raise ValueError(
                    "outcome='success' requires synthesis; "
                    "'single source → pass through, do not re-summarise' "
                    "and 'synthesis only engages with 2+ sources' are "
                    "uncheckable without it"
                )
            if not self.sources:
                raise ValueError(
                    "outcome='success' requires sources; "
                    "synthesis quality cannot be verified without the source list"
                )
        return self


# ---------------------------------------------------------------------------
# Style-tag detection — BuilderOutput
# ---------------------------------------------------------------------------

# Matches the opening of any <style> element, case-insensitively, including
# forms with whitespace between '<' and 'style':
#
#   <style>            (standard)
#   <STYLE>            (upper-case)
#   < style >          (whitespace around tag name, per brief requirement)
#   <style type="..."> (attribute variant)
#   <style/>           (self-closed)
#
# The character class [\s>/] after 'style' prevents false positives on other
# elements whose names begin with 'style' (none exist in HTML5, but we guard
# it anyway).
#
# Decision on attribute-value `<style>`:  we deliberately DO fire on a pattern
# such as `<div title="<style>foo</style>">`.  A builder constructing
# well-formed slide HTML has no legitimate reason to embed the text `<style>`
# inside an attribute value.  Rejecting it is the safer default, and it
# matches the intent of the spec (deck-level CSS has a single writer).
_STYLE_TAG_RE = re.compile(r"<\s*style[\s>/]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# BuilderOutput
# ---------------------------------------------------------------------------


class BuilderOutput(BaseModel):
    """Output of the builder (and, by inheritance, the fixer) skill node.

    ``html`` must contain no ``<style>`` element (§5.2.3): deck-level CSS has
    a single writer; n builders each emitting ``<style>`` would collide on
    shared deck state.

    ``scripts`` is ``str`` — not ``Optional[str]``, not a dict.  Matches
    ``src/domain/slide.py``'s JavaScript-source-text field.  This is the one
    place the type is decided; ws4d must match it.
    """

    position: int
    html: str
    scripts: str = ""

    @field_validator("html")
    @classmethod
    def _no_style_element(cls, v: str) -> str:
        """Reject HTML that contains a <style> element (§5.2.3)."""
        if _STYLE_TAG_RE.search(v):
            raise ValueError(
                "BuilderOutput.html must not contain a <style> element; "
                "deck-level CSS has a single writer and concurrent <style> "
                "blocks from multiple builder nodes would collide on shared deck state"
            )
        return v


# ---------------------------------------------------------------------------
# FixerOutput
# ---------------------------------------------------------------------------


class FixerOutput(BuilderOutput):
    """Output of the fixer skill node.

    Inherits ``position``, ``html``, and ``scripts`` from ``BuilderOutput``,
    including the no-``<style>`` rule.
    """

    changed: bool
    change_summary: str = ""


# ---------------------------------------------------------------------------
# Output schema registry
# ---------------------------------------------------------------------------

#: Maps every skill name to its output schema class.
#:
#: The seven names follow lower_snake_case matching the roles in the PRD:
#:
#:   architect          — ArchitectOutput
#:   data_analyst       — AnalystOutput
#:   builder            — BuilderOutput
#:   fixer              — FixerOutput
#:   build_reviewer     — SlideReviewOutput  (slide-level post-build review)
#:   fix_reviewer       — SlideReviewOutput  (slide-level post-fix review)
#:   deck_reviewer      — DeckReviewOutput   (deck-level narrative review)
#:
#: ``build_reviewer`` and ``fix_reviewer`` share ``SlideReviewOutput``; they
#: are distinct graph nodes with distinct names but identical output shapes.
#: ``deck_reviewer`` uses ``DeckReviewOutput`` (deck-level findings only).
OUTPUT_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "architect": ArchitectOutput,
    "data_analyst": AnalystOutput,
    "builder": BuilderOutput,
    "fixer": FixerOutput,
    "build_reviewer": SlideReviewOutput,
    "fix_reviewer": SlideReviewOutput,
    "deck_reviewer": DeckReviewOutput,
}

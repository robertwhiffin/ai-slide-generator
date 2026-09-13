"""Deck specification models.

These are the artefacts the architect agent commits and that every downstream
node reads back.  They are pure Pydantic — no database imports.

Invariants enforced here
------------------------
H1  title is non-empty after stripping whitespace.
L1  design_system_id and slide_style_id are mutually exclusive (both set is
    rejected).
L3  template_id requires design_system_id — a template belongs to exactly one
    design system; a reference without its owning design system is invalid.
M3  template_section_index is typed int | None; brand bytes never pass through
    the model.
    DesignContractRef stores a reference only — never compiled content.
"""

import logging
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)


class DesignContractRef(BaseModel):
    """Which brand to use, never the compiled content.

    Stores only identifiers so a snapshot in the spec cannot go stale against
    COMPILER_VERSION.  Compiled content is resolved on demand from these ids.

    Invariants
    ----------
    L1  design_system_id and slide_style_id are mutually exclusive.
    L3  template_id requires design_system_id.
    """

    design_system_id: Optional[int] = None
    template_id: Optional[int] = None
    slide_style_id: Optional[int] = None

    @model_validator(mode="after")
    def _check_mutual_exclusion_and_template_dependency(
        self,
    ) -> "DesignContractRef":
        if self.design_system_id is not None and self.slide_style_id is not None:
            raise ValueError(
                "design_system_id and slide_style_id are mutually exclusive; "
                "set at most one"
            )
        if self.template_id is not None and self.design_system_id is None:
            raise ValueError(
                "template_id requires design_system_id; "
                "a template belongs to exactly one design system"
            )
        return self


class ResolvedFigure(BaseModel):
    key: str
    value: str
    source: str


class ResolvedData(BaseModel):
    synthesis: str
    figures: list[ResolvedFigure]
    gaps: list[str]


class SlideSpec(BaseModel):
    """Specification for a single slide.

    ``position`` is the canonical identity of the slide within the deck.  It is
    an explicit int so the position is stable after deletes and partial rebuilds
    (where list index and position would otherwise diverge).

    ``template_section_index`` is an index into the template's section list,
    never markup (M3).
    """

    position: int
    purpose: str
    content_brief: str
    assumes: str
    hands_off: str
    data_references: list[str]
    template_section_index: Optional[int] = None


class DeckSpec(BaseModel):
    """Top-level deck specification committed by the architect agent.

    Every downstream node reads this back verbatim.  Four later PRs bind to
    this model and are forbidden from editing it, so the validators must be
    correct now.

    Review criteria are NOT a spec field (§4.2): if the architect authored
    the standard it is judged against, review independence would be nominal.
    """

    title: str
    audience: str
    purpose: str
    argument: str
    call_to_action: str
    narrative_arc: list[str]
    design_contract: DesignContractRef
    resolved_data: ResolvedData
    slides: list[SlideSpec]

    @field_validator("title")
    @classmethod
    def _title_must_be_non_empty(cls, v: str) -> str:
        """H1 — title is required and non-empty (reject whitespace-only)."""
        if not v or not v.strip():
            raise ValueError(
                "title must be non-empty and not whitespace-only"
            )
        return v

    @model_validator(mode="after")
    def _slide_positions_must_be_unique(self) -> "DeckSpec":
        positions = [s.position for s in self.slides]
        if len(positions) != len(set(positions)):
            raise ValueError("slide positions must be unique within a DeckSpec")
        return self

    def slide_at(self, position: int) -> Optional[SlideSpec]:
        """Return the SlideSpec whose ``position`` field matches, or None.

        Looks up by the ``position`` field, NEVER by list index.  The two
        diverge after a delete or a partial multi-target rebuild, at which
        point indexing by list position would silently brief a builder for
        the wrong slide.
        """
        for slide in self.slides:
            if slide.position == position:
                return slide
        return None

    def to_json(self) -> str:
        """Serialise this spec to a JSON string."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: Optional[str]) -> Optional["DeckSpec"]:
        """Deserialise a spec from JSON, returning None rather than raising.

        A deck may legitimately have no spec (pre-cutover decks, MCP-built
        decks), and a hand-edited column may not parse.  The architect
        back-fills an absent spec — it cannot do that if the read raised.

        Tolerates: None, empty string, malformed JSON, partial objects (any
        validation failure).  Never raises.
        """
        if not raw:
            return None
        try:
            return cls.model_validate_json(raw)
        except Exception:
            logger.debug(
                "DeckSpec.from_json: could not parse spec (first 120 chars): %r",
                raw[:120],
            )
            return None

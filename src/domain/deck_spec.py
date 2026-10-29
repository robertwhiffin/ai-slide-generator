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

The deck style (``DeckStyle``) and a slide's ``look`` are type-checked only.
Their content rules (class prefix, size, count, allowed CSS) belong to the
deck-style sanitiser, never to a validator here: a schema rejection would fail
the whole architect turn.
"""

import logging
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)


def look_or_none(v: Optional[str]) -> Optional[str]:
    """A slide's ``look``, stripped; blank (or ``None``) becomes ``None``.

    Shared by ``SlideSpec`` and ``SlideContent`` so a slide built from new
    content stores exactly the look a spec would.
    """
    if v is None:
        return None
    return v.strip() or None


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

    ``look`` says in plain language what the slide looks like: the layout of
    its body and which deck-style (or template) pieces it uses.  Stripped; a
    blank look is ``None``.
    """

    position: int
    purpose: str
    content_brief: str
    assumes: str
    hands_off: str
    data_references: list[str]
    slide_type: Optional[str] = None
    template_section_index: Optional[int] = None
    look: Optional[str] = None

    @field_validator("slide_type")
    @classmethod
    def _slide_type_stripped_and_non_blank(cls, v: Optional[str]) -> Optional[str]:
        """Strip ``slide_type``; reject whitespace-only. ``None`` stays ``None``.

        Free text from the design system's slide-type vocabulary, so it is
        deliberately not a Literal. Pairing with ``template_section_index`` is
        validated where the template inventory is available, not here.
        """
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("slide_type must not be whitespace-only")
        return stripped

    @field_validator("look")
    @classmethod
    def _look_stripped_blank_is_none(cls, v: Optional[str]) -> Optional[str]:
        return look_or_none(v)


class DeckStyleComponent(BaseModel):
    """One reusable piece of the deck style.

    ``class_names`` are the classes from ``DeckStyle.css`` that make it,
    ``use`` says when a slide should use it, and ``example_html`` is a minimal
    snippet showing those classes in use.
    """

    name: str
    class_names: list[str]
    use: str
    example_html: str


class DeckStyle(BaseModel):
    """The deck's own house style: ``css`` plus the catalogue of components it defines.

    It adds to the brand (design system or slide style); it never replaces it.
    """

    css: str
    components: list[DeckStyleComponent]


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
    deck_style: Optional[DeckStyle] = None

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

"""Code-owned compatibility definitions for the LangGraph agent runtime.

This module is the single source of truth for seven legacy ``Skill`` records
(name, version, instructions, output schema, tool grants). ``AgentRuntime``
temporarily adapts them into code-owned Agent Definitions until Graph Releases
become authoritative.
C9 split the seven prose bodies into per-skill sub-modules (Ruling C-22); this
module keeps the registry machinery and imports each body.

Contract ownership
------------------
``Skill`` is defined exactly once, here.  An earlier draft split the definition
across two tasks with incompatible types — a ``BaseModel`` with ``prompt_body``
in one place and a frozen dataclass with ``instructions``/``version``/``tool_grants``
in another.  **The frozen dataclass wins**: spec §5.1 requires both the version
and the tool grants.

Tool grants
-----------
``data_analyst`` is the ONLY skill with non-empty ``tool_grants`` (§16, Ruling
C-11).  Spec §5.2.2's rationale: the analyst is the OBO boundary where
user-scoped data access is concentrated; the architect's work (conversation,
arc, section assignment) reaches no tool.  The other six declare ``[]``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.domain.skill_io import OUTPUT_SCHEMAS


# ---------------------------------------------------------------------------
# Skill dataclass — FROZEN, one definition in one place
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    """A versioned skill definition.

    Attributes:
        name: The skill name, matching an :data:`~src.domain.skill_io.OUTPUT_SCHEMAS`
            key exactly.
        version: Monotonically-incremented integer — increment when
            ``instructions`` change so callers can detect staleness.
        instructions: The system-prompt body for this skill.  C9 replaces these
            placeholder strings with the authored prose; the graph runs on
            placeholders until then.
        output_schema: The pydantic class the model must produce.
        tool_grants: Tool names this skill is allowed to invoke.  Only
            ``data_analyst`` carries a non-empty list; all others declare ``[]``
            (§5.2.2 / Ruling C-11).
    """

    name: str
    version: int
    instructions: str
    output_schema: type[BaseModel]
    tool_grants: list[str]


# ---------------------------------------------------------------------------
# Internal registry — populated at import time, queried via load_skill
# ---------------------------------------------------------------------------

_SKILLS: dict[str, Skill] = {}


def _register(
    name: str,
    *,
    version: int,
    instructions: str,
    tool_grants: list[str],
) -> None:
    """Register a skill, binding it to its :data:`OUTPUT_SCHEMAS` entry."""
    _SKILLS[name] = Skill(
        name=name,
        version=version,
        instructions=instructions,
        output_schema=OUTPUT_SCHEMAS[name],
        tool_grants=list(tool_grants),
    )


# ---------------------------------------------------------------------------
# Skill bodies — imported from per-skill sub-modules (Ruling C-22, C9).
#
# Rules (§15, §16, Ruling C-10, C-11):
#   1. All seven are registered here so C4 can invoke them.
#   2. Each body is non-empty — an empty prompt produces garbage that still
#      parses, which would let tests pass vacuously.
#   3. No body may contain the safe-area literals 88px, 72px, 56px or 1280x720
#      — those numbers are owned by _SLIDE_FRAME_CONSTRAINTS and must come
#      from exactly one source so they can never drift.
#   4. data_analyst is the ONLY skill with non-empty tool_grants.
# ---------------------------------------------------------------------------

from .architect import INSTRUCTIONS as _architect_instructions
from .architect import TOOL_GRANTS as _architect_grants
from .data_analyst import INSTRUCTIONS as _data_analyst_instructions
from .data_analyst import TOOL_GRANTS as _data_analyst_grants
from .builder import INSTRUCTIONS as _builder_instructions
from .builder import TOOL_GRANTS as _builder_grants
from .fixer import INSTRUCTIONS as _fixer_instructions
from .fixer import TOOL_GRANTS as _fixer_grants
from .build_reviewer import INSTRUCTIONS as _build_reviewer_instructions
from .build_reviewer import TOOL_GRANTS as _build_reviewer_grants
from .fix_reviewer import INSTRUCTIONS as _fix_reviewer_instructions
from .fix_reviewer import TOOL_GRANTS as _fix_reviewer_grants
from .deck_reviewer import INSTRUCTIONS as _deck_reviewer_instructions
from .deck_reviewer import TOOL_GRANTS as _deck_reviewer_grants

_register("architect", version=2, instructions=_architect_instructions, tool_grants=_architect_grants)
_register("data_analyst", version=2, instructions=_data_analyst_instructions, tool_grants=_data_analyst_grants)
_register("builder", version=2, instructions=_builder_instructions, tool_grants=_builder_grants)
_register("fixer", version=2, instructions=_fixer_instructions, tool_grants=_fixer_grants)
_register("build_reviewer", version=2, instructions=_build_reviewer_instructions, tool_grants=_build_reviewer_grants)
_register("fix_reviewer", version=2, instructions=_fix_reviewer_instructions, tool_grants=_fix_reviewer_grants)
_register("deck_reviewer", version=2, instructions=_deck_reviewer_instructions, tool_grants=_deck_reviewer_grants)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_skill(name: str) -> Skill:
    """Return the :class:`Skill` registered under *name*.

    Raises:
        KeyError: if *name* is not a registered skill.
    """
    try:
        return _SKILLS[name]
    except KeyError:
        raise KeyError(
            f"Unknown skill {name!r}. Registered skills: {sorted(_SKILLS)}"
        ) from None


def list_skills() -> list[str]:
    """Return the names of all registered skills in registration order."""
    return list(_SKILLS)

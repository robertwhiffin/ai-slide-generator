"""Skill registry and invocation entry-point for the LangGraph graph.

This module is the single source of truth for the seven skill definitions
(name, version, instructions, output schema, tool grants).  Every graph node
calls :func:`call_skill`; the skill prose bodies are placeholders replaced by
C9.

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

import json
from dataclasses import dataclass
from typing import Any

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
# Skill registrations — PLACEHOLDER BODIES.  C9 replaces the prose.
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

_register(
    "architect",
    version=1,
    instructions=(
        "Architect: analyse the user request and produce a structured deck "
        "specification with slide sections, section types, and a narrative arc. "
        "Return an ArchitectOutput that captures the intent and, for 'build' "
        "intent, a complete DeckSpec."
    ),
    tool_grants=[],
)

_register(
    "data_analyst",
    version=1,
    instructions=(
        "Data analyst: query the available tools for the metrics described in "
        "the data_request payload, synthesise the results, and return an "
        "AnalystOutput with outcome, synthesis, and sources."
    ),
    tool_grants=["genie", "vector_index"],
)

_register(
    "builder",
    version=1,
    instructions=(
        "Builder: generate a single, well-structured slide in HTML for the "
        "given section brief. Return valid HTML only; do NOT emit a <style> "
        "element — deck-level CSS has a single writer."
    ),
    tool_grants=[],
)

_register(
    "fixer",
    version=1,
    instructions=(
        "Fixer: apply the reported objective finding to the slide HTML. "
        "Return the corrected HTML, a change_summary, and a changed flag. "
        "Do NOT emit a <style> element."
    ),
    tool_grants=[],
)

_register(
    "build_reviewer",
    version=1,
    instructions=(
        "Build reviewer: inspect the built slide against the objective design "
        "criteria (overflow, contrast, colour fidelity, image distortion, "
        "source fidelity). Return a SlideReviewOutput with a findings list."
    ),
    tool_grants=[],
)

_register(
    "fix_reviewer",
    version=1,
    instructions=(
        "Fix reviewer: verify that the fixer addressed the reported finding "
        "and return a new review of the corrected slide as a SlideReviewOutput."
    ),
    tool_grants=[],
)

_register(
    "deck_reviewer",
    version=1,
    instructions=(
        "Deck reviewer: review the complete deck for narrative arc, cross-slide "
        "repetition, and presence of a conclusion. Return a DeckReviewOutput "
        "with a findings list."
    ),
    tool_grants=[],
)


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


def call_skill(
    name: str,
    payload: dict[str, Any],
    design_system_active: bool,
) -> BaseModel:
    """Every node's single entry point for skill invocation.

    Loads the named skill, assembles a full prompt (instructions + style-gated
    conditionals + serialised payload), calls the structured model, and returns
    parsed output.

    Why ``design_system_active: bool``, not a ``ResolvedStyle`` (Ruling C-21):
    ``assemble_skill_prompt`` reads exactly one field of ``ResolvedStyle``.
    Passing the whole NamedTuple would force every call site to construct dummy
    fields it does not have; and a NamedTuple in ``GraphState`` is on a
    deprecation path in langgraph (unregistered-type deserialisation warning,
    will be blocked in a future version).  A plain ``bool`` never crosses a
    checkpoint boundary as an object.  The caller reads
    ``state["design_system_active"]`` — a scalar written once by
    ``architect_node``.

    Args:
        name: A registered skill name; raises :exc:`KeyError` if unknown.
        payload: Task-specific inputs for this invocation — the builder's section
            brief, the reviewer's HTML, the fixer's finding, etc.
        design_system_active: ``True`` when a design system resolved to compiled
            content for this request.  Read from
            :attr:`~src.services.graph.state.GraphState.design_system_active`
            (written once by ``architect_node``).

    Returns:
        An instance of the skill's declared ``output_schema``.

    Raises:
        KeyError: if *name* is not a registered skill.
    """
    from src.services.agent_resolution import assemble_skill_prompt, get_structured_model

    skill = load_skill(name)
    prompt = assemble_skill_prompt(skill, payload, design_system_active)
    model = get_structured_model(skill.output_schema)
    return model.invoke(prompt)

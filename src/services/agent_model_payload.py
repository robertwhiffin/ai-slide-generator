"""The model-facing payload of each role, for #267 test runs (Correction 37).

Production hands each role's model content only: no session, user, turn or
release identifier (#258, the user's decision for every role).  The builder
filters its branch payload through ``_BUILDER_MODEL_PAYLOAD_KEYS`` in
``src/services/graph/nodes.py``; every other node builds a literal dict for the
model.  A stored Agent Test Case payload (the seeded smoke payloads among them)
may still carry identifier keys, so a test run projects it onto that role's
production keys before the runtime sees it.

Each role's key set is the **union of that role's production calls**, so the
builder's includes the retry's ``corrective_instruction`` and the build
reviewer's includes the deck-level re-review's ``deck_brief``.  The sets are
pinned to the literal per-call sets in ``tests/fixtures/model_payload_keys.py``,
which ``tests/unit/test_graph_nodes.py`` pins production to, and the builder's to
the production allowlist.  ``nodes.py`` does not call this module.

Import-light by design: nothing from ``src`` is imported at module level, so the
test workbench never pulls in the graph module.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

_SLIDE_REVIEW_KEYS = frozenset(
    {
        "position",
        "slide_spec",
        "resolved_style",
        "section_css",
        "resolved_data",
        "html",
        "scripts",
    }
)
_FIXER_KEYS = frozenset(
    {
        "position",
        "finding",
        "html",
        "scripts",
        "slide_spec",
        "resolved_style",
        "section_css",
    }
)

#: Per role, the union of the key sets of every production model call.
MODEL_PAYLOAD_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "architect": frozenset(
            {
                "conversation",
                "message",
                "current_deck_spec",
                "committed_slide_count",
                "previous_deck_review",
                "available_design_contract",
                "template_sections",
                "resolved_style",
                "design_system_library",
            }
        ),
        "data_analyst": frozenset({"data_request", "deck_purpose"}),
        "builder": frozenset(
            {
                "position",
                "slide_spec",
                "assumes",
                "hands_off",
                "resolved_data",
                "section_html",
                "section_css",
                "resolved_style",
                "design_system_active",
                "corrective_instruction",
            }
        ),
        "build_reviewer": _SLIDE_REVIEW_KEYS | {"deck_brief"},
        "fixer": _FIXER_KEYS | {"corrective_instruction", "resolved_data"},
        "fix_reviewer": _FIXER_KEYS
        | {"change_summary", "original_html", "original_scripts"},
        "deck_reviewer": frozenset(
            {"narrative_arc", "call_to_action", "slide_count", "slides"}
        ),
    }
)


def _previous_deck_review(value: Any) -> Any:
    """Production's one nested rule: the stored review loses its ``author``.

    ``architect_node`` sends ``{"digest", "findings"}`` only — the author is the
    reviewing user's identity.  A null review stays null.
    """
    if not isinstance(value, Mapping):
        return value
    return {
        "digest": value.get("digest"),
        "findings": list(value.get("findings") or []),
    }


def model_payload_for(agent_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project ``payload`` onto the role's production model keys, in payload order.

    The result is a detached deep copy, so a later edit of either side cannot
    reach the other.  An unknown or deterministic role raises
    ``UnknownAgentKeyError``.
    """
    keys = MODEL_PAYLOAD_KEYS.get(agent_key)
    if keys is None:
        from src.services.agent_runtime import UnknownAgentKeyError

        raise UnknownAgentKeyError(f"Unknown model-driven agent key {agent_key!r}")
    projected: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in keys:
            continue
        if key == "previous_deck_review":
            value = _previous_deck_review(value)
        projected[key] = copy.deepcopy(value)
    return projected


__all__ = ["MODEL_PAYLOAD_KEYS", "model_payload_for"]

"""Every production model call's payload key set, as literals (#258, #267 C37).

Moved verbatim out of ``tests/unit/test_graph_nodes.py`` so there is one source
of truth for the key sets: ``test_graph_nodes.py`` pins production to these
literals (``TestNoRolesModelPromptCarriesSessionIdentifiers``), and
``test_agent_model_payload.py`` pins ``src/services/agent_model_payload.py``'s
per-role projection to their per-role union.  They are literals, never imports
of a production set, so a widened production payload fails instead of agreeing.
"""

from __future__ import annotations

# The builder's model-facing payload, stated POSITIVELY as the user decided (#258):
# nothing session-, user-, turn- or release-specific reaches the model.  A literal
# here, not an import of the production allowlist, so a widened production set
# fails this test instead of silently agreeing with it.
BUILDER_MODEL_KEYS = frozenset(
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
    }
)
BUILDER_RETRY_MODEL_KEYS = BUILDER_MODEL_KEYS | {"corrective_instruction"}


# Every role's model-facing payload, stated POSITIVELY as the user decided (#258):
# nothing session-, user-, turn- or release-specific reaches ANY role's model.
# Literals, not imports of production key sets, so a widened production payload
# fails here instead of silently agreeing.  One entry per model invocation in the
# order a full turn makes them; the deck-level re-review is the architect's own
# build_reviewer pass, the one call that carries ``deck_brief``.
SLIDE_REVIEW_MODEL_KEYS = frozenset(
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
FIXER_MODEL_KEYS = frozenset(
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
EVERY_MODEL_CALL = (
    ("data_analyst", "data_analyst", frozenset({"data_request", "deck_purpose"})),
    (
        "architect",
        "architect",
        frozenset(
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
    ),
    (
        "deck_level_rereview",
        "build_reviewer",
        SLIDE_REVIEW_MODEL_KEYS | {"deck_brief"},
    ),
    ("builder", "builder", BUILDER_MODEL_KEYS),
    ("builder_retry", "builder", BUILDER_RETRY_MODEL_KEYS),
    ("build_reviewer", "build_reviewer", SLIDE_REVIEW_MODEL_KEYS),
    ("fixer", "fixer", FIXER_MODEL_KEYS),
    ("fixer_retry", "fixer", FIXER_MODEL_KEYS | {"corrective_instruction"}),
    ("fix_reviewer", "fix_reviewer", FIXER_MODEL_KEYS | {"change_summary"}),
    (
        "deck_reviewer",
        "deck_reviewer",
        frozenset({"narrative_arc", "call_to_action", "slide_count", "slides"}),
    ),
)


__all__ = [
    "BUILDER_MODEL_KEYS",
    "BUILDER_RETRY_MODEL_KEYS",
    "EVERY_MODEL_CALL",
    "FIXER_MODEL_KEYS",
    "SLIDE_REVIEW_MODEL_KEYS",
]

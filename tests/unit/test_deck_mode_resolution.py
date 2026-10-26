"""Deck Mode → engine resolution (spec 2026-10-22 §5.1, §5.4).

A deck's stored ``user_sessions.deck_mode`` is ``"agent"``, ``"legacy"`` or NULL (not
chosen yet).  The job payload keeps its internal ``engine_mode`` values, so resolution
maps the stored mode onto them: ``legacy`` → ``"monolith"``; ``agent`` and NULL →
``"graph"`` (the graph is the default).
"""

from src.domain import conversation_engine


def test_engine_mode_for_deck_mode_maps_legacy_to_monolith_else_graph():
    engine_mode_for_deck_mode = conversation_engine.engine_mode_for_deck_mode

    assert engine_mode_for_deck_mode("legacy") == "monolith"
    assert engine_mode_for_deck_mode("agent") == "graph"
    assert engine_mode_for_deck_mode(None) == "graph"


def test_deck_mode_values_are_exactly_agent_and_legacy():
    """The stored values are a fixed vocabulary: every writer validates against
    ``DECK_MODES`` and the migration's fill must equal ``DECK_MODE_LEGACY``."""
    assert conversation_engine.DECK_MODE_AGENT == "agent"
    assert conversation_engine.DECK_MODE_LEGACY == "legacy"
    assert isinstance(conversation_engine.DECK_MODES, frozenset)
    assert conversation_engine.DECK_MODES == frozenset({"agent", "legacy"})

    engine_mode_for_deck_mode = conversation_engine.engine_mode_for_deck_mode
    assert engine_mode_for_deck_mode(conversation_engine.DECK_MODE_LEGACY) == "monolith"
    assert engine_mode_for_deck_mode(conversation_engine.DECK_MODE_AGENT) == "graph"

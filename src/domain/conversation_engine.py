"""Deck Mode: which engine a deck's conversation runs on.

The mode is stored on ``user_sessions.deck_mode`` (set by the deck's first
message, then locked) and mapped to the job payload's ``engine_mode`` by
:func:`engine_mode_for_deck_mode`.  No message text selects an engine.
"""

from __future__ import annotations

#: Deck Mode: the stored ``user_sessions.deck_mode`` values (NULL = not chosen yet).
DECK_MODE_AGENT = "agent"
DECK_MODE_LEGACY = "legacy"
DECK_MODES: frozenset[str] = frozenset({DECK_MODE_AGENT, DECK_MODE_LEGACY})


def engine_mode_for_deck_mode(deck_mode: str | None) -> str:
    """Map a stored Deck Mode to the job payload's ``engine_mode``.

    ``legacy`` -> ``"monolith"``; ``agent`` and NULL -> ``"graph"`` (the default).
    """
    return "monolith" if deck_mode == DECK_MODE_LEGACY else "graph"


#: ``SessionMessage.message_type`` of the one row ``ChatService.clear_context`` and
#: ``delete_message`` keep (a deck's earliest user message).  The deck's Deck Mode
#: is stored on ``user_sessions.deck_mode``, so the row no longer decides any
#: engine; it is kept only so the deck still counts as started and its title is
#: not regenerated.  This type hides it from every transcript read
#: (``SessionManager.get_messages``, save-point capture), and so from the chat
#: panel, the architect's conversation and the monolith's history.
ENGINE_MODE_MARKER_MESSAGE_TYPE = "engine_mode_marker"


def is_transcript_message(message_type: str | None) -> bool:
    """Whether a persisted chat row belongs to the visible conversation."""
    return message_type != ENGINE_MODE_MARKER_MESSAGE_TYPE

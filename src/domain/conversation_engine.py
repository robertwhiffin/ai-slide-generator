"""Shared graph-engine selection semantics.

Every deck runs on the LangGraph engine UNLESS its first user message contains
the case-sensitive opt-out :data:`LEGACY_MODE_PHRASE`, in which case it runs on
the legacy monolith.  (Until 2026-10-12 the rule was inverted: a deck ran on the
graph only if its first user message contained :data:`AGENT_MODE_PHRASE`.)
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


LEGACY_MODE_PHRASE = "USE LEGACY MODE"

# The pre-2026-10-12 opt-IN marker.  It no longer selects anything on its own
# (absence of the opt-out already selects the graph), so a first message
# carrying it still lands on the graph -- harmlessly.  Kept because the startup
# pin backfill (``conversation_pins._backfill_in_transaction``) uses it to
# recognise the historical graph decks it was written to pin.
AGENT_MODE_PHRASE = "USE AGENT MODE"

#: ``SessionMessage.message_type`` of the one row ``ChatService.clear_context`` keeps.
#: The deck's engine is read off its earliest role='user' row (role only), so a
#: clear cannot delete that row; this type hides it from every transcript read
#: (``SessionManager.get_messages``, save-point capture), and so from the chat
#: panel, the architect's conversation and the monolith's history.
ENGINE_MODE_MARKER_MESSAGE_TYPE = "engine_mode_marker"


def selects_legacy_engine(content: str | None) -> bool:
    """Return whether ``content`` contains the case-sensitive legacy opt-out."""
    return bool(content) and LEGACY_MODE_PHRASE in content


def selects_graph_engine(content: str | None) -> bool:
    """Return whether a deck whose first user message is ``content`` runs on the graph.

    True unless ``content`` carries :data:`LEGACY_MODE_PHRASE`.  ``None`` (no
    user message yet) and ``""`` select the graph: the graph is the default.
    The opt-out wins over :data:`AGENT_MODE_PHRASE` when a message has both.
    """
    return not selects_legacy_engine(content)


def with_legacy_marker(content: str) -> str:
    """Return ``content`` carrying :data:`LEGACY_MODE_PHRASE` (idempotent).

    For server-side creators that must stay on the monolith while persisting a
    user-authored first message (MCP ``create_deck``): the engine is derived
    from the persisted transcript, so the transcript has to say so.
    """
    if selects_legacy_engine(content):
        return content
    return f"{LEGACY_MODE_PHRASE}\n\n{content}"


def is_transcript_message(message_type: str | None) -> bool:
    """Whether a persisted chat row belongs to the visible conversation."""
    return message_type != ENGINE_MODE_MARKER_MESSAGE_TYPE

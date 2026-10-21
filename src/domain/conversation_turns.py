"""Conversation turns over persisted chat rows (#317).

A TURN is one user message and everything the app wrote in answer to it: every
later row of the same session up to, not including, the next ``role='user'``
row.  Assistant replies, clarifications, ``info`` notices (the deck reviewer's
advisory, failure notices), ``reasoning``, ``tool_call`` and ``tool_result``
rows belong to the turn they follow, whatever their ``message_type`` and
whether or not they carry a ``request_id`` (the SSE path and the sweeper write
none).  Grouping is by role and order only, so a row type added later joins
its turn with no change here.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from src.domain.conversation_engine import is_transcript_message


def turn_message_ids(rows: Sequence[Any], head_id: int) -> List[int]:
    """Ids of the turn whose user message is ``head_id``, the user message first.

    Args:
        rows: ONE session's rows, each with ``id``, ``role`` and
            ``message_type``, in transcript order (``created_at``, then ``id``).
        head_id: The user message that starts the turn.

    Returns:
        ``[]`` when ``head_id`` is not a visible user message in ``rows``:
        absent, another role, or the hidden engine-mode marker.  A turn is
        addressed only by its user message.
    """
    for index, row in enumerate(rows):
        if row.id == head_id:
            break
    else:
        return []
    if row.role != "user" or not is_transcript_message(row.message_type):
        return []
    ids = [row.id]
    for later in rows[index + 1:]:
        if later.role == "user":
            break
        ids.append(later.id)
    return ids

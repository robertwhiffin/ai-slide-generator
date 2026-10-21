"""`turn_message_ids` (#317 Task 2, plan D2): what one conversation turn is.

A TURN is a user message and every later row of the session up to, not
including, the next ``role='user'`` row.  Grouping is by role and order only:
never by ``request_id`` (the SSE path and the sweeper write none) and never by
``message_type`` (so a row type added later joins its turn with no change).  A
turn is addressed only by its user message, and never through the hidden
engine-mode marker.  These are the pure rules; ``test_delete_message.py``
proves them on real rows.

Rows are ``SimpleNamespace(id, role, message_type)`` -- the three columns
``ChatService.delete_message`` reads -- given in transcript order.  Ids are
deliberately not positions, so an index/id mix-up shows.

Red before Task 2, test by test: ``ModuleNotFoundError: No module named
'src.domain.conversation_turns'``.  The function is imported inside
``_turn_message_ids`` so the file still collects (and so the import block does
not change shape when the module lands).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Sequence

import pytest

from src.domain.conversation_engine import ENGINE_MODE_MARKER_MESSAGE_TYPE


def _turn_message_ids(rows: Sequence[Any], head_id: int) -> List[int]:
    from src.domain.conversation_turns import turn_message_ids

    return turn_message_ids(rows, head_id)


def _row(id_: int, role: str, message_type: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=id_, role=role, message_type=message_type)


# Three turns, shaped the way the live paths write them: the deck reviewer's
# advisory (``info``) after the first reply; reasoning, a tool call, its tool
# result, the reply and an untagged failure notice in the second; a
# clarification in the third.  The three heads carry the three user types.
_TRANSCRIPT = [
    _row(11, "user", "user_input"),
    _row(12, "assistant", "llm_response"),
    _row(13, "assistant", "info"),
    _row(21, "user", "user_query"),
    _row(22, "assistant", "reasoning"),
    _row(23, "assistant", "tool_call"),
    _row(24, "tool", "tool_result"),
    _row(25, "assistant", "llm_response"),
    _row(26, "assistant", "info"),
    _row(31, "user", "chat"),
    _row(32, "assistant", "clarification"),
]


class TestTurnMessageIds:
    def test_a_turn_is_its_user_message_and_every_row_up_to_the_next_user_message(self):
        """The middle turn's tool row (role ``tool``) and its notice (``info``)
        are part of it: a turn that stopped at the first non-assistant row
        would leave the tool result, the reply and the notice behind."""
        assert _turn_message_ids(_TRANSCRIPT, 21) == [21, 22, 23, 24, 25, 26]
        assert _turn_message_ids(_TRANSCRIPT, 11) == [11, 12, 13]

    def test_the_last_turn_runs_to_the_end_of_the_transcript(self):
        assert _turn_message_ids(_TRANSCRIPT, 31) == [31, 32]

    def test_a_user_message_with_no_reply_is_a_turn_of_one(self):
        """A send that failed before any reply was written."""
        rows = [_row(1, "user", "user_input"), _row(2, "user", "user_input")]

        assert _turn_message_ids(rows, 1) == [1]
        assert _turn_message_ids(rows, 2) == [2]

    @pytest.mark.parametrize(
        ("rows", "head_id"),
        [
            (_TRANSCRIPT, 999),
            (_TRANSCRIPT, 12),
            (_TRANSCRIPT, 24),
            (
                [
                    _row(1, "user", ENGINE_MODE_MARKER_MESSAGE_TYPE),
                    _row(2, "user", "user_input"),
                    _row(3, "assistant", "llm_response"),
                ],
                1,
            ),
            ([], 1),
        ],
        ids=[
            "an_absent_id",
            "an_assistant_reply",
            "a_tool_row",
            "the_hidden_engine_mode_marker",
            "an_empty_transcript",
        ],
    )
    def test_an_id_that_is_not_a_visible_user_message_is_no_turn(self, rows, head_id):
        """A turn is never addressed through a reply, and the hidden marker
        (the row a clear or a first-turn delete keeps) is not a message."""
        assert _turn_message_ids(rows, head_id) == []

    def test_the_turn_after_the_hidden_marker_is_an_ordinary_turn(self):
        """After a clear, or after the first turn was deleted, the session's
        earliest row is the hidden marker; the next user message heads a turn."""
        rows = [
            _row(1, "user", ENGINE_MODE_MARKER_MESSAGE_TYPE),
            _row(2, "user", "user_input"),
            _row(3, "assistant", "llm_response"),
        ]

        assert _turn_message_ids(rows, 2) == [2, 3]

    def test_assistant_rows_before_the_first_user_message_belong_to_no_turn(self):
        """Legacy decks can open with assistant rows.  They are not the first
        turn's replies, and no id of theirs addresses a turn."""
        rows = [
            _row(1, "assistant", "llm_response"),
            _row(2, "assistant", "info"),
            _row(3, "user", "user_input"),
            _row(4, "assistant", "llm_response"),
        ]

        assert _turn_message_ids(rows, 3) == [3, 4]
        assert _turn_message_ids(rows, 1) == []
        assert _turn_message_ids(rows, 2) == []

    def test_a_user_message_with_no_type_starts_a_turn(self):
        """``POST /api/sessions/{id}/messages`` and older decks write ``None``."""
        rows = [
            _row(1, "user", None),
            _row(2, "assistant", "llm_response"),
            _row(3, "user", None),
            _row(4, "assistant", "llm_response"),
        ]

        assert _turn_message_ids(rows, 1) == [1, 2]
        assert _turn_message_ids(rows, 3) == [3, 4]

    @pytest.mark.parametrize("next_type", ["user_input", "user_query", "chat", None])
    def test_the_next_user_message_ends_the_turn_whatever_its_type(self, next_type):
        rows = [
            _row(1, "user", "user_input"),
            _row(2, "assistant", "llm_response"),
            _row(3, "user", next_type),
            _row(4, "assistant", "llm_response"),
        ]

        assert _turn_message_ids(rows, 1) == [1, 2]

    def test_a_row_type_added_later_joins_the_turn_it_follows(self):
        """Grouping is by role and order, so a new notice type needs no change."""
        rows = [
            _row(1, "user", "user_input"),
            _row(2, "assistant", "a_type_written_after_317"),
            _row(3, "assistant", None),
            _row(4, "user", "user_input"),
        ]

        assert _turn_message_ids(rows, 1) == [1, 2, 3]

    def test_the_turn_follows_transcript_order_not_id_order(self):
        """SQLite reuses a deleted row's id (plan D13), so a reply can carry a
        LOWER id than the message it answers.  The rows arrive in transcript
        order, and the turn is read off that order, not off an id range."""
        rows = [
            _row(5, "user", "user_input"),
            _row(9, "assistant", "llm_response"),
            _row(7, "user", "user_input"),
            _row(2, "assistant", "llm_response"),
            _row(8, "user", "user_input"),
            _row(3, "assistant", "llm_response"),
        ]

        assert _turn_message_ids(rows, 7) == [7, 2]
        assert _turn_message_ids(rows, 5) == [5, 9]
        assert _turn_message_ids(rows, 8) == [8, 3]

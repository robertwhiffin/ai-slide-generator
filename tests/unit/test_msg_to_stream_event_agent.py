"""The polling projection passes a row's ``metadata["agent"]`` through as the
event's ``agent`` (the data analyst's report renders as its own card), and is
``None`` for a row without it.  Replay exclusion of ``info`` rows is pinned by
test_conversation_turns.py and test_architect_edit_retry.py (``_conversation``).
"""

from src.api.services.session_manager import SessionManager


def _row(metadata):
    return {
        "id": 5,
        "role": "assistant",
        "content": "Trips rose 4%. | zip | n |",
        "message_type": "info",
        "created_at": "2026-10-30T00:00:00",
        "metadata": metadata,
    }


def test_the_agent_in_the_row_metadata_is_the_events_agent():
    event = SessionManager().msg_to_stream_event(_row({"agent": "data_analyst"}))
    assert event["agent"] == "data_analyst"


def test_a_row_without_an_agent_gives_none():
    manager = SessionManager()
    assert manager.msg_to_stream_event(_row({"node": "x"}))["agent"] is None
    assert manager.msg_to_stream_event(_row(None))["agent"] is None

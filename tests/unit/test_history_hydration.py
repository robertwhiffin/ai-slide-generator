from unittest.mock import MagicMock, patch

from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from src.api.services.chat_service import ChatService


def test_hydration_filters_by_message_type():
    msgs = [
        {"role": "user", "content": "make slides", "message_type": "user_query"},
        {"role": "assistant", "content": "thinking...", "message_type": "reasoning"},
        {"role": "assistant", "content": "Calling query_genie_space", "message_type": "tool_call"},
        {"role": "tool", "content": "rows...", "message_type": "tool_result"},
        {"role": "assistant", "content": "rebuilding deck", "message_type": "info"},
        {"role": "assistant", "content": "Add or replace?", "message_type": "clarification"},
        {"role": "user", "content": "replace", "message_type": "user_input"},
        {"role": "assistant", "content": "<div class='slide'>final</div>", "message_type": "llm_response"},
    ]
    sm = MagicMock()
    sm.get_messages.return_value = msgs
    history = ChatMessageHistory()
    with patch("src.api.services.chat_service.get_session_manager", return_value=sm):
        count = ChatService.__new__(ChatService)._hydrate_chat_history("s1", history)

    kinds = [(type(m).__name__, m.content) for m in history.messages]
    # Kept: user_query, clarification, user_input, final llm_response.
    assert ("HumanMessage", "make slides") in kinds
    assert ("AIMessage", "Add or replace?") in kinds
    assert ("HumanMessage", "replace") in kinds
    assert ("AIMessage", "<div class='slide'>final</div>") in kinds
    # Dropped: reasoning, tool_call, tool_result, info.
    assert all(c not in ("thinking...", "Calling query_genie_space", "rows...", "rebuilding deck")
               for _, c in kinds)
    assert count == 4

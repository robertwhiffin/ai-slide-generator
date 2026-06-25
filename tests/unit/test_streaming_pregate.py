import queue
from unittest.mock import MagicMock, patch

from src.services.streaming_callback import StreamingCallbackHandler
from langchain_core.outputs import LLMResult, Generation


def _llm_result(text):
    return LLMResult(generations=[[Generation(text=text)]])


def test_on_llm_end_skips_unsafe_html():
    q = queue.Queue()
    h = StreamingCallbackHandler(event_queue=q, session_id="s1")
    sm = MagicMock()
    h._session_manager = sm
    h.on_llm_end(_llm_result('<script>fetch("https://evil")</script>'))
    sm.add_message.assert_not_called()      # not persisted
    assert q.empty()                         # not emitted


def test_on_llm_end_persists_clean_html():
    q = queue.Queue()
    h = StreamingCallbackHandler(event_queue=q, session_id="s1")
    sm = MagicMock()
    sm.add_message.return_value = {"id": 1}
    h._session_manager = sm
    h.on_llm_end(_llm_result('<div class="slide">ok</div>'))
    sm.add_message.assert_called_once()
    assert not q.empty()

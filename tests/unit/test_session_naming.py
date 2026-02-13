"""Tests for smart session naming via initial prompt analysis.

The core behavior: when a user sends their first message in a session,
the backend generates a descriptive title from the prompt and pushes it
to the frontend via a SESSION_TITLE SSE event. Subsequent messages do
NOT re-trigger title generation.

Run: pytest tests/unit/test_session_naming.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, Mock

from langchain_core.messages import AIMessage

from src.api.services.session_naming import generate_session_title


# ============================================
# Unit tests: generate_session_title utility
# ============================================


class TestGenerateSessionTitle:
    """Unit tests for the generate_session_title function."""

    def test_returns_clean_title_from_llm(self):
        """LLM response is stripped and returned as-is when clean."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="Q3 Revenue Analysis")

        title = generate_session_title("Show me Q3 revenue by region", mock_model)

        assert title == "Q3 Revenue Analysis"
        mock_model.invoke.assert_called_once()

    def test_strips_surrounding_quotes_and_whitespace(self):
        """Quotes and whitespace are stripped from LLM output."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content='  "Sales Dashboard Overview"  \n')

        title = generate_session_title("Create a sales dashboard", mock_model)

        assert title == "Sales Dashboard Overview"

    def test_returns_none_on_empty_response(self):
        """Returns None when LLM returns empty or whitespace-only response."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="   ")

        title = generate_session_title("Create slides about revenue", mock_model)

        assert title is None

    def test_returns_none_on_llm_exception(self):
        """Returns None when LLM call raises an exception."""
        mock_model = MagicMock()
        mock_model.invoke.side_effect = Exception("LLM connection timeout")

        title = generate_session_title("Create slides about revenue", mock_model)

        assert title is None

    def test_truncates_excessively_long_title(self):
        """Titles longer than 100 characters are truncated."""
        mock_model = MagicMock()
        long_title = "A" * 150
        mock_model.invoke.return_value = AIMessage(content=long_title)

        title = generate_session_title("Some prompt", mock_model)

        assert len(title) <= 100


# ============================================
# Integration tests: first-message detection
# in send_message_streaming
# ============================================


class TestSessionNamingInStreaming:
    """Tests that title generation integrates correctly with send_message_streaming.

    These tests exercise the ChatService.send_message_streaming method with
    mocked dependencies to verify the first-message detection logic.
    """

    def _make_chat_service(self):
        """Create a ChatService with a mocked agent."""
        with patch("src.api.services.chat_service.create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_create.return_value = mock_agent

            from src.api.services.chat_service import ChatService

            service = ChatService.__new__(ChatService)
            service.agent = mock_agent
            service._deck_cache = {}
            service._cache_lock = __import__("threading").Lock()
            return service

    def _make_session_manager_mock(self, message_count: int = 0):
        """Create a mock session manager with controlled message_count.

        Args:
            message_count: Number of existing messages in the session.
                0 = first message (should trigger title generation).
                >0 = subsequent message (should NOT trigger).
        """
        mock_sm = MagicMock()
        mock_sm.get_session.return_value = {
            "session_id": "test-session-123",
            "user_id": "user-abc",
            "title": "Session 2026-02-13 14:30",
            "created_at": "2026-02-13T14:30:00",
            "last_activity": "2026-02-13T14:30:00",
            "genie_conversation_id": None,
            "message_count": message_count,
            "has_slide_deck": False,
            "profile_id": None,
            "profile_name": None,
        }
        mock_sm.add_message.return_value = {
            "id": 1,
            "role": "user",
            "content": "test",
            "created_at": "2026-02-13T14:30:00",
        }
        mock_sm.rename_session.return_value = {
            "session_id": "test-session-123",
            "title": "Q3 Revenue Analysis",
            "updated_at": "2026-02-13T14:30:01",
        }
        return mock_sm

    def _collect_events(self, generator):
        """Consume a streaming generator and return all events as a list."""
        events = []
        try:
            for event in generator:
                events.append(event)
        except Exception:
            pass
        return events

    def _setup_agent_to_return_html(self, service):
        """Configure the mock agent to produce a simple slide result via the callback queue."""
        from src.api.schemas.streaming import StreamEvent, StreamEventType

        def fake_generate_streaming(question, session_id, callback_handler, slide_context=None):
            # Simulate the agent emitting an assistant message
            callback_handler.event_queue.put(
                StreamEvent(type=StreamEventType.ASSISTANT, content="Here are your slides.")
            )
            # Return a result dict like the real agent
            return {
                "html": "<div class='slide'>Slide 1</div>",
                "metadata": {},
            }

        service.agent.generate_slides_streaming.side_effect = fake_generate_streaming

    @patch("src.api.services.chat_service.generate_session_title")
    @patch("src.api.services.chat_service.get_session_manager")
    def test_title_generation_fires_on_first_message(
        self, mock_get_sm, mock_gen_title
    ):
        """Title generation is triggered when message_count is 0 (first message).

        This is the critical test. On first message:
        1. generate_session_title is called with the user message
        2. rename_session is called with the generated title
        3. A SESSION_TITLE SSE event is yielded
        """
        mock_sm = self._make_session_manager_mock(message_count=0)
        mock_get_sm.return_value = mock_sm
        mock_gen_title.return_value = "Q3 Revenue Analysis"

        service = self._make_chat_service()
        self._setup_agent_to_return_html(service)

        # Also mock internal methods that aren't relevant to this test
        service._ensure_agent_session = MagicMock(return_value=None)
        service._detect_edit_intent = MagicMock(return_value=False)
        service._detect_generation_intent = MagicMock(return_value=True)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)
        service._get_or_load_deck = MagicMock(return_value=None)
        service._substitute_images_for_response = MagicMock(
            side_effect=lambda d, r=None: (d, r)
        )

        with patch("src.core.settings_db.get_settings") as mock_settings, \
             patch("databricks_langchain.ChatDatabricks") as mock_chat_cls, \
             patch("src.core.databricks_client.get_user_client") as mock_get_client:
            mock_settings.return_value = MagicMock(
                profile_id=None,
                profile_name=None,
                llm=MagicMock(endpoint="test-endpoint"),
            )
            mock_chat_cls.return_value = MagicMock()
            mock_get_client.return_value = MagicMock()

            events = self._collect_events(
                service.send_message_streaming(
                    session_id="test-session-123",
                    message="Show me Q3 revenue by region",
                )
            )

        # generate_session_title was called with the user's message
        mock_gen_title.assert_called_once()
        call_args = mock_gen_title.call_args
        assert call_args[0][0] == "Show me Q3 revenue by region"

        # rename_session was called with the generated title
        mock_sm.rename_session.assert_called_once_with(
            "test-session-123", "Q3 Revenue Analysis"
        )

        # A SESSION_TITLE event was yielded
        from src.api.schemas.streaming import StreamEventType

        title_events = [
            e for e in events if e.type == StreamEventType.SESSION_TITLE
        ]
        assert len(title_events) == 1
        assert title_events[0].session_title == "Q3 Revenue Analysis"

        # COMPLETE event was also yielded (generation not disrupted)
        complete_events = [
            e for e in events if e.type == StreamEventType.COMPLETE
        ]
        assert len(complete_events) == 1

    @patch("src.api.services.chat_service.generate_session_title")
    @patch("src.api.services.chat_service.get_session_manager")
    def test_title_generation_does_not_fire_on_subsequent_messages(
        self, mock_get_sm, mock_gen_title
    ):
        """Title generation is NOT triggered when session already has messages.

        When message_count > 0:
        1. generate_session_title is never called
        2. rename_session is never called
        3. No SESSION_TITLE event appears in the stream
        """
        mock_sm = self._make_session_manager_mock(message_count=3)
        mock_get_sm.return_value = mock_sm
        mock_gen_title.return_value = "Should Not Appear"

        service = self._make_chat_service()
        self._setup_agent_to_return_html(service)

        service._ensure_agent_session = MagicMock(return_value=None)
        service._detect_edit_intent = MagicMock(return_value=False)
        service._detect_generation_intent = MagicMock(return_value=True)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)
        service._get_or_load_deck = MagicMock(return_value=None)
        service._substitute_images_for_response = MagicMock(
            side_effect=lambda d, r=None: (d, r)
        )

        with patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(profile_id=None, profile_name=None)

            events = self._collect_events(
                service.send_message_streaming(
                    session_id="test-session-123",
                    message="Now add a slide about expenses",
                )
            )

        # generate_session_title was NEVER called
        mock_gen_title.assert_not_called()

        # rename_session was NEVER called
        mock_sm.rename_session.assert_not_called()

        # No SESSION_TITLE event in the stream
        from src.api.schemas.streaming import StreamEventType

        title_events = [
            e for e in events if e.type == StreamEventType.SESSION_TITLE
        ]
        assert len(title_events) == 0

    @patch("src.api.services.chat_service.generate_session_title")
    @patch("src.api.services.chat_service.get_session_manager")
    def test_title_generation_failure_is_silent(
        self, mock_get_sm, mock_gen_title
    ):
        """If title generation returns None (failure), the stream completes normally.

        No SESSION_TITLE event, no error event, COMPLETE event still fires.
        """
        mock_sm = self._make_session_manager_mock(message_count=0)
        mock_get_sm.return_value = mock_sm
        mock_gen_title.return_value = None  # Simulates failure

        service = self._make_chat_service()
        self._setup_agent_to_return_html(service)

        service._ensure_agent_session = MagicMock(return_value=None)
        service._detect_edit_intent = MagicMock(return_value=False)
        service._detect_generation_intent = MagicMock(return_value=True)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)
        service._get_or_load_deck = MagicMock(return_value=None)
        service._substitute_images_for_response = MagicMock(
            side_effect=lambda d, r=None: (d, r)
        )

        with patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(profile_id=None, profile_name=None)

            events = self._collect_events(
                service.send_message_streaming(
                    session_id="test-session-123",
                    message="Show me Q3 revenue by region",
                )
            )

        from src.api.schemas.streaming import StreamEventType

        # No SESSION_TITLE event (generation returned None)
        title_events = [
            e for e in events if e.type == StreamEventType.SESSION_TITLE
        ]
        assert len(title_events) == 0

        # rename_session was NOT called (nothing to rename to)
        mock_sm.rename_session.assert_not_called()

        # COMPLETE event still fires (main flow was not disrupted)
        complete_events = [
            e for e in events if e.type == StreamEventType.COMPLETE
        ]
        assert len(complete_events) == 1

        # No error events related to title generation
        error_events = [
            e for e in events if e.type == StreamEventType.ERROR
        ]
        assert len(error_events) == 0

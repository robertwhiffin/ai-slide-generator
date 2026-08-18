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

    def test_rejects_excessively_long_title(self):
        """An output longer than 100 chars is an overrun, not a title —
        rejected so the caller keeps the session's default name (never a
        mid-word truncation of junk)."""
        mock_model = MagicMock()
        long_title = "A" * 150
        mock_model.invoke.return_value = AIMessage(content=long_title)

        title = generate_session_title("Some prompt", mock_model)

        assert title is None

    def test_strips_complete_thinking_block(self):
        """A leading <thinking> block is removed; the title line survives."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content=(
                "<thinking>The user wants a revenue deck, so a good title "
                "would mention revenue.</thinking>\nQ3 Revenue Analysis"
            )
        )

        title = generate_session_title("Show me Q3 revenue", mock_model)

        assert title == "Q3 Revenue Analysis"

    def test_unclosed_thinking_block_rejected_to_fallback(self):
        """max_tokens can cut the model mid-thought: an unclosed <thinking>
        tag means NO title was produced — return None (safe fallback name)."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content="<thinking>The user is asking about Q3 revenue and I sh"
        )

        title = generate_session_title("Show me Q3 revenue", mock_model)

        assert title is None

    def test_takes_first_non_empty_line_only(self):
        """Explanatory prose after the title never leaks into the name."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content="\n\nQ3 Revenue Analysis\n\nThis title captures the request."
        )

        title = generate_session_title("Show me Q3 revenue", mock_model)

        assert title == "Q3 Revenue Analysis"

    def test_strips_markdown_decoration(self):
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="**Q3 Revenue Analysis**")

        title = generate_session_title("Show me Q3 revenue", mock_model)

        assert title == "Q3 Revenue Analysis"

    def test_tag_only_response_rejected(self):
        """A response that is nothing but markup yields None, not '<...>'."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(content="<thinking></thinking>")

        title = generate_session_title("Show me Q3 revenue", mock_model)

        assert title is None


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
        """Create a ChatService without agent (agent is now per-request)."""
        from src.api.services.chat_service import ChatService

        service = ChatService.__new__(ChatService)
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
            "experiment_id": None,
            "agent_config": None,
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

    def _setup_agent_mock(self, service):
        """Configure a mock agent returned by _build_agent_for_session.

        Returns:
            The mock agent so callers can verify calls on it.
        """
        from src.api.schemas.streaming import StreamEvent, StreamEventType

        mock_agent = MagicMock()

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

        mock_agent.generate_slides_streaming.side_effect = fake_generate_streaming
        mock_agent.sessions = {}

        # Mock _build_agent_for_session to return the mock agent
        service._build_agent_for_session = MagicMock(
            return_value=(mock_agent, {"session_id": "test-session-123", "genie_conversation_id": None}, None)
        )
        return mock_agent

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
        self._setup_agent_mock(service)

        # Also mock internal methods that aren't relevant to this test
        service._detect_edit_intent = MagicMock(return_value=False)
        service._detect_generation_intent = MagicMock(return_value=True)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)
        service._get_or_load_deck = MagicMock(return_value=None)
        service._substitute_images_for_response = MagicMock(
            side_effect=lambda d, r=None, *, session_id: (d, r)
        )
        service._persist_genie_conversation_ids = MagicMock()

        with patch("src.core.settings_db.get_settings") as mock_settings, \
             patch("databricks_langchain.ChatDatabricks") as mock_chat_cls, \
             patch("src.core.databricks_client.get_user_client") as mock_get_client:
            mock_settings.return_value = MagicMock(
                profile_id=None,
                profile_name=None,
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
        self._setup_agent_mock(service)

        service._detect_edit_intent = MagicMock(return_value=False)
        service._detect_generation_intent = MagicMock(return_value=True)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)
        service._get_or_load_deck = MagicMock(return_value=None)
        service._substitute_images_for_response = MagicMock(
            side_effect=lambda d, r=None, *, session_id: (d, r)
        )
        service._persist_genie_conversation_ids = MagicMock()

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
        self._setup_agent_mock(service)

        service._detect_edit_intent = MagicMock(return_value=False)
        service._detect_generation_intent = MagicMock(return_value=True)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)
        service._get_or_load_deck = MagicMock(return_value=None)
        service._substitute_images_for_response = MagicMock(
            side_effect=lambda d, r=None, *, session_id: (d, r)
        )
        service._persist_genie_conversation_ids = MagicMock()

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


class TestDegenerateOverrunTitles:
    """Live-reproduced failure shape (diag, 2/2): the naming model emits the
    correct title, then keeps generating — a fused degenerate `Endtml` marker
    plus tag-style reasoning — and max_tokens slices it mid-thought
    (finish_reason == "length"). Both signals must be handled: overruns are
    rejected outright, and the fused marker is stripped when a provider
    reports no finish metadata."""

    def test_finish_reason_length_is_rejected(self):
        """An overrun naming call is junk, never a title — safe fallback."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content=(
                "Acme Robotics Q3 Autonomy RoadmapEndtml\n<thinking>\nThe user "
                "wants me to create a presentation with 3 slides"
            ),
            response_metadata={"finish_reason": "length"},
        )

        title = generate_session_title("Create 3 slides on autonomy", mock_model)

        assert title is None

    def test_anthropic_style_max_tokens_is_rejected(self):
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content="Acme Roadmap<thinking>and now I will",
            response_metadata={"stop_reason": "max_tokens"},
        )

        title = generate_session_title("Create slides", mock_model)

        assert title is None

    def test_fused_endtml_marker_stripped_without_finish_metadata(self):
        """Same content shape but no finish metadata: the fused degenerate
        marker on the title line is stripped, the thinking tail is gone."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content=(
                "Acme Robotics Q3 Autonomy RoadmapEndtml\n<thinking>\nThe user "
                "wants me to create a presentation"
            )
        )

        title = generate_session_title("Create 3 slides on autonomy", mock_model)

        assert title == "Acme Robotics Q3 Autonomy Roadmap"

    def test_legit_title_ending_in_end_survives(self):
        """'End' as a real word (e.g. quarter end) is not the marker."""
        mock_model = MagicMock()
        mock_model.invoke.return_value = AIMessage(
            content="Preparing for Quarter End",
            response_metadata={"finish_reason": "stop"},
        )

        title = generate_session_title("Quarter end prep", mock_model)

        assert title == "Preparing for Quarter End"

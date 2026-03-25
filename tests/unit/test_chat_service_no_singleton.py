"""Tests for ChatService refactor: remove singleton agent, build per-request.

These tests verify:
1. ChatService.__init__ no longer creates a singleton agent
2. reload_agent() method is removed
3. _ensure_agent_session() method is removed
4. send_message() builds agent per-request via build_agent_for_request
5. send_message_streaming() builds agent per-request via build_agent_for_request
6. genie_conversation_id is persisted after request if changed
"""

import threading
from unittest.mock import MagicMock, patch

import pytest


class TestChatServiceInitNoAgent:
    """ChatService.__init__ should not create a singleton agent."""

    def test_init_does_not_call_create_agent(self):
        """ChatService() should not call create_agent or have a singleton agent."""
        from src.api.services.chat_service import ChatService

        service = ChatService()

        # Should NOT have a singleton agent attribute
        assert not hasattr(service, "agent") or service.agent is None

    def test_init_does_not_have_reload_lock(self):
        """ChatService should not have _reload_lock (no agent to reload)."""
        from src.api.services.chat_service import ChatService

        service = ChatService()

        assert not hasattr(service, "_reload_lock")

    def test_init_retains_cache_lock_and_deck_cache(self):
        """ChatService should still have _cache_lock and _deck_cache."""
        from src.api.services.chat_service import ChatService

        service = ChatService()

        assert hasattr(service, "_cache_lock")
        assert hasattr(service, "_deck_cache")
        assert isinstance(service._deck_cache, dict)


class TestReloadAgentRemoved:
    """reload_agent() method should not exist on ChatService."""

    def test_reload_agent_not_present(self):
        """ChatService should not have a reload_agent method."""
        from src.api.services.chat_service import ChatService

        service = ChatService()

        assert not hasattr(service, "reload_agent")


class TestEnsureAgentSessionRemoved:
    """_ensure_agent_session() method should not exist on ChatService."""

    def test_ensure_agent_session_not_present(self):
        """ChatService should not have a _ensure_agent_session method."""
        from src.api.services.chat_service import ChatService

        service = ChatService()

        assert not hasattr(service, "_ensure_agent_session")


class TestSendMessageBuildsAgentPerRequest:
    """send_message() should build agent from session's agent_config."""

    @patch("src.api.services.chat_service.get_session_manager")
    @patch("src.api.services.chat_service.build_agent_for_request")
    @patch("src.api.services.chat_service.resolve_agent_config")
    @patch("src.api.services.chat_service.get_current_username", return_value="test@user.com")
    def test_send_message_calls_build_agent(
        self, mock_username, mock_resolve, mock_build, mock_get_sm
    ):
        """send_message should call build_agent_for_request with session config."""
        from src.api.services.chat_service import ChatService

        # Setup mocks
        mock_sm = MagicMock()
        mock_get_sm.return_value = mock_sm
        mock_sm.get_session.return_value = {
            "session_id": "test-session",
            "genie_conversation_id": "genie-123",
            "experiment_id": "exp-456",
            "agent_config": {"tools": []},
            "message_count": 1,
        }

        mock_agent_config = MagicMock()
        mock_resolve.return_value = mock_agent_config

        mock_agent = MagicMock()
        mock_agent.generate_slides.return_value = {
            "html": "<div>test</div>",
            "replacement_info": None,
            "messages": [{"role": "assistant", "content": "Here are slides"}],
            "metadata": {},
        }
        mock_agent.sessions = {}
        mock_build.return_value = mock_agent

        service = ChatService()

        with patch.object(service, "_get_or_load_deck", return_value=None), \
             patch.object(service, "_ensure_user_experiment", return_value=(None, None)), \
             patch.object(service, "_hydrate_chat_history", return_value=0), \
             patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(profile_id=1, profile_name="test")
            result = service.send_message("test-session", "create slides")

        # Verify build_agent_for_request was called (resolve_agent_config may be
        # called again by _persist_conversation_ids_to_agent_config)
        mock_resolve.assert_any_call({"tools": []})
        mock_build.assert_called_once()

        # Verify the agent_config and session_data were passed
        call_args = mock_build.call_args
        assert call_args[0][0] is mock_agent_config  # first arg: config
        session_data = call_args[0][1]  # second arg: session_data
        assert session_data["session_id"] == "test-session"
        assert session_data["genie_conversation_id"] == "genie-123"


class TestSendMessageStreamingBuildsAgentPerRequest:
    """send_message_streaming() should build agent per-request."""

    @patch("src.api.services.chat_service.get_session_manager")
    @patch("src.api.services.chat_service.build_agent_for_request")
    @patch("src.api.services.chat_service.resolve_agent_config")
    @patch("src.api.services.chat_service.get_current_username", return_value="test@user.com")
    def test_streaming_calls_build_agent(
        self, mock_username, mock_resolve, mock_build, mock_get_sm
    ):
        """send_message_streaming should call build_agent_for_request."""
        from src.api.services.chat_service import ChatService

        mock_sm = MagicMock()
        mock_get_sm.return_value = mock_sm
        mock_sm.get_session.return_value = {
            "session_id": "test-session",
            "genie_conversation_id": None,
            "experiment_id": None,
            "agent_config": None,
            "message_count": 0,
            "profile_id": None,
            "profile_name": None,
        }
        mock_sm.add_message.return_value = {"id": 1}

        mock_agent_config = MagicMock()
        mock_resolve.return_value = mock_agent_config

        mock_agent = MagicMock()
        mock_agent.generate_slides_streaming.return_value = {
            "html": "<div>test</div>",
            "replacement_info": None,
            "messages": [],
            "metadata": {},
        }
        mock_agent.sessions = {}
        mock_build.return_value = mock_agent

        service = ChatService()

        with patch.object(service, "_get_or_load_deck", return_value=None), \
             patch.object(service, "_ensure_user_experiment", return_value=(None, None)), \
             patch.object(service, "_hydrate_chat_history", return_value=0), \
             patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                profile_id=None, profile_name=None,
                llm=MagicMock(endpoint="test-endpoint"),
            )
            # Consume the generator
            events = list(service.send_message_streaming("test-session", "create slides"))

        # Verify build_agent_for_request was called
        mock_build.assert_called_once()


class TestGenieConversationIdPersistence:
    """genie_conversation_id should be persisted if it changed during request."""

    @patch("src.api.services.chat_service.get_session_manager")
    @patch("src.api.services.chat_service.build_agent_for_request")
    @patch("src.api.services.chat_service.resolve_agent_config")
    @patch("src.api.services.chat_service.get_current_username", return_value="test@user.com")
    def test_genie_id_persisted_when_changed(
        self, mock_username, mock_resolve, mock_build, mock_get_sm
    ):
        """If genie_conversation_id changes during request, it should be saved."""
        from src.api.services.chat_service import ChatService

        mock_sm = MagicMock()
        mock_get_sm.return_value = mock_sm
        mock_sm.get_session.return_value = {
            "session_id": "test-session",
            "genie_conversation_id": None,  # starts as None
            "experiment_id": None,
            "agent_config": None,
            "message_count": 1,
            "profile_id": 1,
            "profile_name": "test",
        }

        mock_resolve.return_value = MagicMock()

        # Agent's generate_slides modifies session_data (simulating Genie tool)
        def fake_generate(question, session_id, slide_context=None):
            # The Genie tool closure updates session_data in-place
            call_args = mock_build.call_args
            session_data = call_args[0][1]
            session_data["genie_conversation_id"] = "new-genie-id"
            return {
                "html": "<div>test</div>",
                "replacement_info": None,
                "messages": [{"role": "assistant", "content": "slides"}],
                "metadata": {},
            }

        mock_agent = MagicMock()
        mock_agent.generate_slides.side_effect = fake_generate
        mock_agent.sessions = {}
        mock_build.return_value = mock_agent

        service = ChatService()

        with patch.object(service, "_get_or_load_deck", return_value=None), \
             patch.object(service, "_ensure_user_experiment", return_value=(None, None)), \
             patch.object(service, "_hydrate_chat_history", return_value=0), \
             patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(profile_id=1, profile_name="test")
            service.send_message("test-session", "create slides")

        # Verify genie_conversation_id was persisted
        mock_sm.set_genie_conversation_id.assert_called_once_with(
            "test-session", "new-genie-id"
        )

    @patch("src.api.services.chat_service.get_session_manager")
    @patch("src.api.services.chat_service.build_agent_for_request")
    @patch("src.api.services.chat_service.resolve_agent_config")
    @patch("src.api.services.chat_service.get_current_username", return_value="test@user.com")
    def test_genie_id_not_persisted_when_unchanged(
        self, mock_username, mock_resolve, mock_build, mock_get_sm
    ):
        """If genie_conversation_id didn't change, don't call set_genie_conversation_id."""
        from src.api.services.chat_service import ChatService

        mock_sm = MagicMock()
        mock_get_sm.return_value = mock_sm
        mock_sm.get_session.return_value = {
            "session_id": "test-session",
            "genie_conversation_id": "existing-id",
            "experiment_id": None,
            "agent_config": None,
            "message_count": 1,
            "profile_id": 1,
            "profile_name": "test",
        }

        mock_resolve.return_value = MagicMock()

        mock_agent = MagicMock()
        mock_agent.generate_slides.return_value = {
            "html": "<div>test</div>",
            "replacement_info": None,
            "messages": [{"role": "assistant", "content": "slides"}],
            "metadata": {},
        }
        mock_agent.sessions = {}
        mock_build.return_value = mock_agent

        service = ChatService()

        with patch.object(service, "_get_or_load_deck", return_value=None), \
             patch.object(service, "_ensure_user_experiment", return_value=(None, None)), \
             patch.object(service, "_hydrate_chat_history", return_value=0), \
             patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(profile_id=1, profile_name="test")
            service.send_message("test-session", "create slides")

        # Should NOT call set_genie_conversation_id since it didn't change
        mock_sm.set_genie_conversation_id.assert_not_called()

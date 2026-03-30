"""Tests for per-space Genie conversation_id persistence in agent_config.

Verifies:
1. GenieTool schema accepts optional conversation_id
2. Agent factory seeds session_data from GenieTool.conversation_id
3. Chat service persists updated conversation_ids back to agent_config after execution
"""

from unittest.mock import MagicMock, patch

import pytest


class TestGenieToolConversationIdSchema:
    """GenieTool should accept an optional conversation_id field."""

    def test_genie_tool_without_conversation_id(self):
        from src.api.schemas.agent_config import GenieTool

        tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
        assert tool.conversation_id is None

    def test_genie_tool_with_conversation_id(self):
        from src.api.schemas.agent_config import GenieTool

        tool = GenieTool(
            type="genie", space_id="abc", space_name="Sales",
            conversation_id="conv-123",
        )
        assert tool.conversation_id == "conv-123"

    def test_conversation_id_round_trips_through_dict(self):
        from src.api.schemas.agent_config import AgentConfig, GenieTool

        tool = GenieTool(
            type="genie", space_id="abc", space_name="Sales",
            conversation_id="conv-456",
        )
        config = AgentConfig(tools=[tool])
        d = config.model_dump()
        assert d["tools"][0]["conversation_id"] == "conv-456"

        # Re-parse
        config2 = AgentConfig.model_validate(d)
        assert config2.tools[0].conversation_id == "conv-456"

    def test_conversation_id_none_excluded_when_not_set(self):
        """conversation_id should be None by default, not missing."""
        from src.api.schemas.agent_config import GenieTool

        tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
        d = tool.model_dump()
        assert "conversation_id" in d
        assert d["conversation_id"] is None


class TestAgentFactorySeedsConversationId:
    """Agent factory should seed session_data from GenieTool.conversation_id."""

    @patch("src.services.tools.genie_tool.initialize_genie_conversation")
    @patch("src.services.tools.genie_tool.query_genie_space")
    def test_seeds_session_data_from_config_conversation_id(
        self, mock_query, mock_init
    ):
        from src.api.schemas.agent_config import GenieTool
        from src.services.tools import build_genie_tool

        genie_config = GenieTool(
            type="genie", space_id="space-1", space_name="Sales",
            conversation_id="conv-from-config",
        )
        session_data = {"session_id": "test"}

        build_genie_tool(genie_config, session_data, index=1)

        # Should have seeded the per-space key from the config
        assert session_data["genie_conversation_id:space-1"] == "conv-from-config"

    @patch("src.services.tools.genie_tool.initialize_genie_conversation")
    @patch("src.services.tools.genie_tool.query_genie_space")
    def test_config_conversation_id_takes_precedence_over_legacy(
        self, mock_query, mock_init
    ):
        from src.api.schemas.agent_config import GenieTool
        from src.services.tools import build_genie_tool

        genie_config = GenieTool(
            type="genie", space_id="space-1", space_name="Sales",
            conversation_id="conv-from-config",
        )
        session_data = {
            "session_id": "test",
            "genie_conversation_id": "legacy-conv",
        }

        build_genie_tool(genie_config, session_data, index=1)

        # Config value should win
        assert session_data["genie_conversation_id:space-1"] == "conv-from-config"

    @patch("src.services.tools.genie_tool.initialize_genie_conversation")
    @patch("src.services.tools.genie_tool.query_genie_space")
    def test_falls_back_to_legacy_when_no_config_conversation_id(
        self, mock_query, mock_init
    ):
        from src.api.schemas.agent_config import GenieTool
        from src.services.tools import build_genie_tool

        genie_config = GenieTool(
            type="genie", space_id="space-1", space_name="Sales",
        )
        session_data = {
            "session_id": "test",
            "genie_conversation_id": "legacy-conv",
        }

        build_genie_tool(genie_config, session_data, index=1)

        # Should fall back to legacy
        assert session_data["genie_conversation_id:space-1"] == "legacy-conv"


class TestPersistConversationIdsToAgentConfig:
    """Chat service should persist updated conversation_ids to agent_config."""

    @patch("src.core.database.get_db_session")
    def test_persist_writes_conversation_id_to_agent_config(self, mock_get_db):
        """After execution, conversation_ids should be written to agent_config."""
        from src.api.schemas.agent_config import AgentConfig, GenieTool
        from src.api.services.chat_service import ChatService

        # Setup agent_config with a Genie tool with no conversation_id
        genie_tool = GenieTool(type="genie", space_id="space-1", space_name="Sales")
        agent_config = AgentConfig(tools=[genie_tool])

        # Mock session manager
        session_manager = MagicMock()
        session_manager.get_session.return_value = {
            "session_id": "test-session",
            "agent_config": agent_config.model_dump(),
        }

        # Mock DB session for writing
        mock_db = MagicMock()
        mock_session_row = MagicMock()
        mock_session_row.agent_config = agent_config.model_dump()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_session_row
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        # session_data has a new conversation_id from Genie execution
        session_data = {
            "session_id": "test-session",
            "genie_conversation_id:space-1": "new-conv-123",
        }

        service = ChatService()
        service._persist_conversation_ids_to_agent_config(
            "test-session", session_data, session_manager
        )

        # The DB session row should have been updated with the new conversation_id
        saved_config = mock_session_row.agent_config
        assert saved_config["tools"][0]["conversation_id"] == "new-conv-123"

    @patch("src.core.database.get_db_session")
    def test_no_write_when_conversation_id_unchanged(self, mock_get_db):
        """Should not write to DB if conversation_id hasn't changed."""
        from src.api.schemas.agent_config import AgentConfig, GenieTool
        from src.api.services.chat_service import ChatService

        genie_tool = GenieTool(
            type="genie", space_id="space-1", space_name="Sales",
            conversation_id="existing-conv",
        )
        agent_config = AgentConfig(tools=[genie_tool])

        session_manager = MagicMock()
        session_manager.get_session.return_value = {
            "session_id": "test-session",
            "agent_config": agent_config.model_dump(),
        }

        session_data = {
            "session_id": "test-session",
            "genie_conversation_id:space-1": "existing-conv",  # Same as before
        }

        service = ChatService()
        service._persist_conversation_ids_to_agent_config(
            "test-session", session_data, session_manager
        )

        # DB should NOT have been touched
        mock_get_db.assert_not_called()

    @patch("src.core.database.get_db_session")
    def test_persist_multiple_genie_spaces(self, mock_get_db):
        """Should update conversation_ids for multiple Genie spaces."""
        from src.api.schemas.agent_config import AgentConfig, GenieTool
        from src.api.services.chat_service import ChatService

        tool1 = GenieTool(type="genie", space_id="space-1", space_name="Sales")
        tool2 = GenieTool(type="genie", space_id="space-2", space_name="Marketing")
        agent_config = AgentConfig(tools=[tool1, tool2])

        session_manager = MagicMock()
        session_manager.get_session.return_value = {
            "session_id": "test-session",
            "agent_config": agent_config.model_dump(),
        }

        mock_db = MagicMock()
        mock_session_row = MagicMock()
        mock_session_row.agent_config = agent_config.model_dump()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_session_row
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        session_data = {
            "session_id": "test-session",
            "genie_conversation_id:space-1": "conv-1",
            "genie_conversation_id:space-2": "conv-2",
        }

        service = ChatService()
        service._persist_conversation_ids_to_agent_config(
            "test-session", session_data, session_manager
        )

        saved_config = mock_session_row.agent_config
        assert saved_config["tools"][0]["conversation_id"] == "conv-1"
        assert saved_config["tools"][1]["conversation_id"] == "conv-2"

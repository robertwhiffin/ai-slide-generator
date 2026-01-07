"""
Unit tests for the SlideGeneratorAgent.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.services.agent import (
    AgentError,
    GenieQueryInput,
    LLMInvocationError,
    SlideGeneratorAgent,
    ToolExecutionError,
    create_agent,
)


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = Mock()
    settings.llm.endpoint = "test-endpoint"
    settings.llm.temperature = 0.7
    settings.llm.max_tokens = 4096
    settings.llm.top_p = 0.95
    settings.llm.timeout = 120
    settings.mlflow.tracking_uri = "databricks"
    settings.mlflow.experiment_name = "/test/experiment"
    settings.prompts = {"system_prompt": "You are a test assistant."}
    return settings


@pytest.fixture
def mock_client():
    """Mock Databricks client for testing."""
    client = Mock()
    return client


@pytest.fixture
def mock_mlflow():
    """Mock MLflow for testing."""
    with patch("src.services.agent.mlflow") as mock_mlflow:
        # Mock start_span as a context manager
        span = Mock()
        span.__enter__ = Mock(return_value=span)
        span.__exit__ = Mock(return_value=False)
        span.set_attribute = Mock()
        mock_mlflow.start_span.return_value = span
        mock_mlflow.set_tracking_uri = Mock()
        mock_mlflow.set_experiment = Mock()
        yield mock_mlflow


@pytest.fixture
def mock_langchain_components():
    """Mock LangChain components."""
    with patch("src.services.agent.ChatDatabricks") as mock_chat, patch(
        "langchain_classic.agents.create_tool_calling_agent"
    ) as mock_create_agent, patch("langchain_classic.agents.AgentExecutor") as mock_executor_class:
        # Create a mock executor instance
        mock_executor_instance = Mock()
        mock_executor_class.return_value = mock_executor_instance
        
        yield {
            "chat": mock_chat,
            "create_agent": mock_create_agent,
            "executor": mock_executor_class,
            "executor_instance": mock_executor_instance,
        }


@pytest.fixture
def agent_with_mocks(
    mock_settings, mock_client, mock_mlflow, mock_langchain_components
):
    """Create agent with all dependencies mocked."""
    with patch("src.services.agent.get_settings") as mock_get_settings, \
         patch("src.services.agent.get_databricks_client") as mock_get_client, \
         patch("src.services.agent.initialize_genie_conversation") as mock_init_genie:
        mock_get_settings.return_value = mock_settings
        mock_get_client.return_value = mock_client
        mock_init_genie.return_value = "test-genie-conv-id"

        agent = SlideGeneratorAgent()
        return agent


class TestSlideGeneratorAgent:
    """Test suite for SlideGeneratorAgent."""

    def test_agent_initialization_valid(
        self, mock_settings, mock_client, mock_mlflow, mock_langchain_components
    ):
        """Test successful agent initialization."""
        with patch("src.services.agent.get_settings") as mock_get_settings, \
             patch("src.services.agent.get_databricks_client") as mock_get_client, \
             patch("src.services.agent.initialize_genie_conversation") as mock_init_genie:
            mock_get_settings.return_value = mock_settings
            mock_get_client.return_value = mock_client
            mock_init_genie.return_value = "test-genie-conv-id"

            agent = SlideGeneratorAgent()

            # Verify MLflow setup called
            mock_mlflow.set_tracking_uri.assert_called_once_with("databricks")
            mock_mlflow.set_experiment.assert_called_once()

            # Verify components created
            assert agent.settings == mock_settings
            assert agent.client == mock_client
            # Note: model is now created per-request for user context
            assert agent.prompt is not None
            # Note: tools and agent_executor are now created per-request for thread safety
            assert agent.sessions == {}

    def test_agent_initialization_missing_prompt(
        self, mock_settings, mock_client, mock_mlflow, mock_langchain_components
    ):
        """Test agent initialization fails with missing system prompt."""
        mock_settings.prompts = {}  # Empty prompts

        with patch("src.services.agent.get_settings") as mock_get_settings, \
             patch("src.services.agent.get_databricks_client") as mock_get_client, \
             patch("src.services.agent.initialize_genie_conversation") as mock_init_genie:
            mock_get_settings.return_value = mock_settings
            mock_get_client.return_value = mock_client
            mock_init_genie.return_value = "test-genie-conv-id"

            with pytest.raises(AgentError, match="System prompt not found"):
                SlideGeneratorAgent()

    def test_create_model_valid(self, agent_with_mocks):
        """Test model creation with valid settings."""
        # Model is now created per-request via _create_model()
        with patch("src.services.agent.get_user_client") as mock_user_client:
            mock_user_client.return_value = MagicMock()
            model = agent_with_mocks._create_model()
            assert model is not None

    def test_create_tools_for_session_valid(self, agent_with_mocks):
        """Test tool creation for a specific session."""
        # Mock initialize_genie_conversation for create_session call
        with patch("src.services.agent.initialize_genie_conversation") as mock_init:
            mock_init.return_value = "test-genie-conv-id-session"

            # Create a session first (tools need a session to bind to)
            session_id = agent_with_mocks.create_session()

            # Create tools for the session
            tools = agent_with_mocks._create_tools_for_session(session_id)

            assert len(tools) == 1
            assert tools[0].name == "query_genie_space"
            assert "Genie" in tools[0].description
    
    def test_session_management(self, agent_with_mocks):
        """Test session creation, retrieval, and management."""
        # Mock initialize_genie_conversation for create_session call
        with patch("src.services.agent.initialize_genie_conversation") as mock_init:
            mock_init.return_value = "test-genie-conv-id-session"
            
            # Create session
            session_id = agent_with_mocks.create_session()
            assert session_id is not None
            
            # Verify session data
            session = agent_with_mocks.get_session(session_id)
            assert session["genie_conversation_id"] == "test-genie-conv-id-session"
            assert session["chat_history"] is not None
            assert session["message_count"] == 0
            
            # List sessions
            sessions = agent_with_mocks.list_sessions()
            assert session_id in sessions
            
            # Clear session
            agent_with_mocks.clear_session(session_id)
            sessions_after = agent_with_mocks.list_sessions()
            assert session_id not in sessions_after
            
            # Test error for non-existent session
            with pytest.raises(AgentError, match="Session not found"):
                agent_with_mocks.get_session("non-existent-id")

    def test_genie_query_input_schema_valid(self):
        """Test Genie query input schema validation."""
        # Valid input - conversation_id now managed automatically
        valid_input = GenieQueryInput(query="What were Q4 sales?")
        assert valid_input.query == "What were Q4 sales?"

    def test_format_messages_for_chat_valid(self, agent_with_mocks):
        """Test message formatting with various scenarios."""
        # Mock intermediate steps - conversation_id no longer exposed to LLM
        action1 = Mock()
        action1.tool = "query_genie_space"
        action1.tool_input = {"query": "What were sales?"}

        action2 = Mock()
        action2.tool = "query_genie_space"
        action2.tool_input = {"query": "Show me by region"}

        intermediate_steps = [
            (action1, "Data retrieved successfully:\n\n[{...}]"),
            (action2, "Data retrieved successfully:\n\n[{...}]"),
        ]

        messages = agent_with_mocks._format_messages_for_chat(
            question="Analyze sales data",
            intermediate_steps=intermediate_steps,
            final_output="<html>...</html>",
        )

        # Verify message structure
        assert len(messages) == 6  # user + 2*(assistant + tool) + final assistant
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Analyze sales data"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["tool_call"]["name"] == "query_genie_space"
        assert messages[2]["role"] == "tool"
        assert messages[3]["role"] == "assistant"
        assert messages[4]["role"] == "tool"
        assert messages[5]["role"] == "assistant"
        assert messages[5]["content"] == "<html>...</html>"

        # Verify all messages have timestamps
        for msg in messages:
            assert "timestamp" in msg

    # Note: generate_slides() tests are in integration tests due to
    # complexity of mocking LangChain components. Unit tests focus on
    # individual methods and components.


class TestCreateAgent:
    """Test suite for create_agent factory function."""

    def test_create_agent_valid(
        self, mock_settings, mock_client, mock_mlflow, mock_langchain_components
    ):
        """Test successful agent creation via factory function."""
        with patch("src.services.agent.get_settings") as mock_get_settings, \
             patch("src.services.agent.get_databricks_client") as mock_get_client, \
             patch("src.services.agent.initialize_genie_conversation") as mock_init_genie:
            mock_get_settings.return_value = mock_settings
            mock_get_client.return_value = mock_client
            mock_init_genie.return_value = "test-genie-conv-id"

            agent = create_agent()

            assert isinstance(agent, SlideGeneratorAgent)
            assert agent.settings == mock_settings


class TestExceptionHierarchy:
    """Test exception class hierarchy."""

    def test_exception_inheritance_valid(self):
        """Test exception inheritance."""
        assert issubclass(LLMInvocationError, AgentError)
        assert issubclass(ToolExecutionError, AgentError)
        assert issubclass(AgentError, Exception)


"""
Unit tests for the SlideGeneratorAgent.
"""

from unittest.mock import Mock, patch

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
    with patch("src.services.agent.get_settings") as mock_get_settings, patch(
        "src.services.agent.get_databricks_client"
    ) as mock_get_client:
        mock_get_settings.return_value = mock_settings
        mock_get_client.return_value = mock_client

        agent = SlideGeneratorAgent()
        return agent


class TestSlideGeneratorAgent:
    """Test suite for SlideGeneratorAgent."""

    def test_agent_initialization_valid(
        self, mock_settings, mock_client, mock_mlflow, mock_langchain_components
    ):
        """Test successful agent initialization."""
        with patch("src.services.agent.get_settings") as mock_get_settings, patch(
            "src.services.agent.get_databricks_client"
        ) as mock_get_client:
            mock_get_settings.return_value = mock_settings
            mock_get_client.return_value = mock_client

            agent = SlideGeneratorAgent()

            # Verify MLflow setup called
            mock_mlflow.set_tracking_uri.assert_called_once_with("databricks")
            mock_mlflow.set_experiment.assert_called_once_with("/test/experiment")

            # Verify components created
            assert agent.settings == mock_settings
            assert agent.client == mock_client
            assert agent.model is not None
            assert agent.tools is not None
            assert agent.prompt is not None
            assert agent.agent_executor is not None

    def test_agent_initialization_missing_prompt(
        self, mock_settings, mock_client, mock_mlflow, mock_langchain_components
    ):
        """Test agent initialization fails with missing system prompt."""
        mock_settings.prompts = {}  # Empty prompts

        with patch("src.services.agent.get_settings") as mock_get_settings, patch(
            "src.services.agent.get_databricks_client"
        ) as mock_get_client:
            mock_get_settings.return_value = mock_settings
            mock_get_client.return_value = mock_client

            with pytest.raises(AgentError, match="System prompt not found"):
                SlideGeneratorAgent()

    def test_create_model_valid(self, agent_with_mocks):
        """Test model creation with valid settings."""
        model = agent_with_mocks.model
        assert model is not None

    def test_create_tools_valid(self, agent_with_mocks):
        """Test tool creation."""
        tools = agent_with_mocks.tools

        assert len(tools) == 1
        assert tools[0].name == "query_genie_space"
        assert "Genie" in tools[0].description

    def test_genie_query_input_schema_valid(self):
        """Test Genie query input schema validation."""
        # Valid input
        valid_input = GenieQueryInput(query="What were Q4 sales?")
        assert valid_input.query == "What were Q4 sales?"
        assert valid_input.conversation_id is None

        # Valid input with conversation_id
        valid_input_with_conv = GenieQueryInput(
            query="Follow up question", conversation_id="conv-123"
        )
        assert valid_input_with_conv.query == "Follow up question"
        assert valid_input_with_conv.conversation_id == "conv-123"

    def test_format_messages_for_chat_valid(self, agent_with_mocks):
        """Test message formatting with various scenarios."""
        # Mock intermediate steps
        action1 = Mock()
        action1.tool = "query_genie_space"
        action1.tool_input = {"query": "What were sales?"}

        action2 = Mock()
        action2.tool = "query_genie_space"
        action2.tool_input = {
            "query": "Show me by region",
            "conversation_id": "conv-123",
        }

        intermediate_steps = [
            (action1, "Data: [{...}]\nConversation ID: conv-123"),
            (action2, "Data: [{...}]\nConversation ID: conv-123"),
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

    def test_generate_slides_valid(self, agent_with_mocks, mock_mlflow):
        """Test successful slide generation."""
        # Mock agent executor response
        action = Mock()
        action.tool = "query_genie_space"
        action.tool_input = {"query": "What were Q4 sales?"}

        agent_with_mocks.agent_executor.invoke.return_value = {
            "output": "<html><h1>Sales Report</h1></html>",
            "intermediate_steps": [
                (action, "Data: [{...}]\nConversation ID: conv-123")
            ],
        }

        result = agent_with_mocks.generate_slides(
            question="What were Q4 sales?", max_slides=5
        )

        # Verify result structure
        assert "html" in result
        assert "messages" in result
        assert "metadata" in result
        assert result["html"] == "<html><h1>Sales Report</h1></html>"
        assert len(result["messages"]) == 4  # user + assistant + tool + final assistant
        assert result["metadata"]["tool_calls"] == 1
        assert "latency_seconds" in result["metadata"]

        # Verify agent executor called
        agent_with_mocks.agent_executor.invoke.assert_called_once()

        # Verify MLflow span attributes set
        span = mock_mlflow.start_span.return_value.__enter__.return_value
        span.set_attribute.assert_any_call("question", "What were Q4 sales?")
        span.set_attribute.assert_any_call("max_slides", 5)
        span.set_attribute.assert_any_call("status", "success")

    def test_generate_slides_error_handling(self, agent_with_mocks, mock_mlflow):
        """Test error handling during slide generation."""
        # Test timeout error
        agent_with_mocks.agent_executor.invoke.side_effect = TimeoutError("LLM timeout")
        with pytest.raises(LLMInvocationError, match="LLM request timed out"):
            agent_with_mocks.generate_slides(question="Test question")

        # Test general error
        agent_with_mocks.agent_executor.invoke.side_effect = Exception("General error")
        with pytest.raises(AgentError, match="Slide generation failed"):
            agent_with_mocks.generate_slides(question="Test question")


class TestCreateAgent:
    """Test suite for create_agent factory function."""

    def test_create_agent_valid(
        self, mock_settings, mock_client, mock_mlflow, mock_langchain_components
    ):
        """Test successful agent creation via factory function."""
        with patch("src.services.agent.get_settings") as mock_get_settings, patch(
            "src.services.agent.get_databricks_client"
        ) as mock_get_client:
            mock_get_settings.return_value = mock_settings
            mock_get_client.return_value = mock_client

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


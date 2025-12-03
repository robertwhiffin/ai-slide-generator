"""
Integration tests for SlideGeneratorAgent.

These tests verify that the agent works end-to-end with mocked Databricks responses.
Unlike unit tests, these test the full integration of all components.
"""

import os
from unittest.mock import Mock, patch

import pytest

from src.services.agent import AgentError, SlideGeneratorAgent

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def mock_databricks_responses():
    """Mock Databricks Genie and LLM responses for integration testing."""
    # Mock Genie conversation response
    conversation_response = Mock()
    conversation_response.conversation_id = "conv-integration-123"
    conversation_response.message_id = "msg-integration-456"

    attachment = Mock()
    attachment.attachment_id = "attach-integration-789"
    conversation_response.attachments = [attachment]

    # Mock Genie query result
    attachment_result = Mock()
    attachment_result.as_dict.return_value = {
        "statement_response": {
            "manifest": {
                "schema": {
                    "columns": [
                        {"name": "quarter"},
                        {"name": "region"},
                        {"name": "sales"},
                        {"name": "growth"},
                    ]
                }
            },
            "result": {
                "data_array": [
                    ["Q4 2023", "APAC", 1200000, 15.5],
                    ["Q4 2023", "EMEA", 980000, 12.3],
                    ["Q4 2023", "Americas", 1500000, 18.2],
                ]
            },
        }
    }

    return {
        "conversation_response": conversation_response,
        "attachment_result": attachment_result,
    }


@pytest.fixture
def mock_llm_response():
    """Mock LLM response with tool calls."""
    # Simulate LLM making tool calls and generating HTML
    action1 = Mock()
    action1.tool = "query_genie_space"
    action1.tool_input = {"query": "What were Q4 2023 sales by region?"}

    action2 = Mock()
    action2.tool = "query_genie_space"
    action2.tool_input = {
        "query": "Show me the growth rates",
        "conversation_id": "conv-integration-123",
    }

    html_output = """<!DOCTYPE html>
<html>
<head>
    <title>Q4 2023 Sales Analysis</title>
    <style>
        body { font-family: Arial, sans-serif; }
        .slide { padding: 20px; }
        h1 { color: #333; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; }
    </style>
</head>
<body>
    <div class="slide">
        <h1>Q4 2023 Sales Performance</h1>
        <p>Regional sales analysis and growth trends</p>
    </div>
    <div class="slide">
        <h2>Sales by Region</h2>
        <table>
            <tr><th>Region</th><th>Sales</th><th>Growth</th></tr>
            <tr><td>Americas</td><td>$1,500,000</td><td>18.2%</td></tr>
            <tr><td>APAC</td><td>$1,200,000</td><td>15.5%</td></tr>
            <tr><td>EMEA</td><td>$980,000</td><td>12.3%</td></tr>
        </table>
    </div>
    <div class="slide">
        <h2>Key Insights</h2>
        <ul>
            <li>Americas led with $1.5M in sales (18.2% growth)</li>
            <li>APAC showed strong performance with 15.5% growth</li>
            <li>All regions achieved double-digit growth</li>
        </ul>
    </div>
</body>
</html>"""

    return {
        "output": html_output,
        "intermediate_steps": [
            (action1, "Data: [{...}]\nConversation ID: conv-integration-123"),
            (action2, "Data: [{...}]\nConversation ID: conv-integration-123"),
        ],
    }


@pytest.fixture
def agent_with_mocked_responses(mock_databricks_responses, mock_llm_response):
    """Create agent with mocked Databricks and LLM responses."""
    with patch("src.services.agent.get_databricks_client") as mock_get_client, patch(
        "src.services.agent.ChatDatabricks"
    ) as mock_chat_databricks, patch(
        "langchain_classic.agents.AgentExecutor"
    ) as mock_executor_class, patch(
        "src.services.tools.get_databricks_client"
    ) as mock_tools_client:
        # Mock Databricks client
        mock_client = Mock()
        mock_client.genie.start_conversation_and_wait.return_value = (
            mock_databricks_responses["conversation_response"]
        )
        mock_client.genie.create_message_and_wait.return_value = (
            mock_databricks_responses["conversation_response"]
        )
        mock_client.genie.get_message_attachment_query_result.return_value = (
            mock_databricks_responses["attachment_result"]
        )
        mock_get_client.return_value = mock_client
        mock_tools_client.return_value = mock_client

        # Mock LLM model
        mock_model = Mock()
        mock_chat_databricks.return_value = mock_model

        # Mock agent executor
        mock_executor = Mock()
        mock_executor.invoke.return_value = mock_llm_response
        mock_executor_class.return_value = mock_executor

        agent = SlideGeneratorAgent()
        
        # Pre-create test sessions with mocked Genie conversation ID
        from langchain_community.chat_message_histories import ChatMessageHistory
        for i in range(1, 6):
            session_id = f"test-session-{i}"
            agent.sessions[session_id] = {
                "chat_history": ChatMessageHistory(),
                "genie_conversation_id": "conv-integration-123",
                "created_at": "2024-01-01T00:00:00Z",
                "message_count": 0,
            }
        # Also add special session IDs used in tests
        for special_id in ["test-session-error", "test-session-mlflow"]:
            agent.sessions[special_id] = {
                "chat_history": ChatMessageHistory(),
                "genie_conversation_id": "conv-integration-123",
                "created_at": "2024-01-01T00:00:00Z",
                "message_count": 0,
            }
        
        return agent


@pytest.mark.skip(reason="Requires more sophisticated LangChain mocking - mock model returns Mock objects instead of strings")
class TestAgentEndToEnd:
    """Test complete end-to-end agent workflow."""

    def test_generate_slides_complete_flow(self, agent_with_mocked_responses):
        """Test complete slide generation flow with mocked responses."""
        result = agent_with_mocked_responses.generate_slides(
            question="What were Q4 2023 sales by region?",
            session_id="test-session-1",
            max_slides=5,
        )

        # Verify result structure
        assert "html" in result
        assert "messages" in result
        assert "metadata" in result

        # Verify HTML output
        assert result["html"].startswith("<!DOCTYPE html>")
        assert "Q4 2023 Sales Performance" in result["html"]
        assert "table" in result["html"]

        # Verify messages captured
        messages = result["messages"]
        assert len(messages) > 0
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What were Q4 2023 sales by region?"

        # Verify tool calls captured
        tool_messages = [m for m in messages if m["role"] == "tool"]
        assert len(tool_messages) == 2  # Two tool calls in mock

        # Verify final assistant message with HTML
        assert messages[-1]["role"] == "assistant"
        assert "<!DOCTYPE html>" in messages[-1]["content"]

        # Verify metadata
        assert result["metadata"]["tool_calls"] == 2
        assert "latency_seconds" in result["metadata"]
        assert result["metadata"]["latency_seconds"] > 0

    def test_generate_slides_with_multiple_tool_calls(self, agent_with_mocked_responses):
        """Test slide generation with multiple Genie tool calls."""
        result = agent_with_mocked_responses.generate_slides(
            question="Analyze sales trends and growth rates",
            session_id="test-session-2",
            max_slides=10,
        )

        # Verify multiple tool calls captured in messages
        messages = result["messages"]
        assistant_messages = [m for m in messages if m["role"] == "assistant"]
        tool_messages = [m for m in messages if m["role"] == "tool"]

        # Should have multiple assistant messages (one per tool call + final)
        assert len(assistant_messages) >= 2

        # Should have tool response messages
        assert len(tool_messages) == 2

        # Verify conversation flow maintained
        for i, msg in enumerate(messages):
            assert "timestamp" in msg
            if i > 0:
                # Timestamps should be in order (or same)
                assert msg["timestamp"] >= messages[i - 1]["timestamp"]

    def test_generate_slides_message_structure(self, agent_with_mocked_responses):
        """Test that messages have correct structure and content."""
        result = agent_with_mocked_responses.generate_slides(
            question="Test question",
            session_id="test-session-3",
            max_slides=3,
        )

        messages = result["messages"]

        # Verify user message
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "Test question"
        assert "timestamp" in user_msgs[0]

        # Verify assistant messages with tool calls
        assistant_tool_msgs = [
            m for m in messages if m["role"] == "assistant" and "tool_call" in m
        ]
        for msg in assistant_tool_msgs:
            assert "tool_call" in msg
            assert "name" in msg["tool_call"]
            assert "arguments" in msg["tool_call"]
            assert msg["tool_call"]["name"] == "query_genie_space"

        # Verify tool response messages
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        for msg in tool_msgs:
            assert "content" in msg
            assert "tool_call_id" in msg
            assert "timestamp" in msg

        # Verify final assistant message (HTML output)
        final_msg = messages[-1]
        assert final_msg["role"] == "assistant"
        assert "<!DOCTYPE html>" in final_msg["content"]

    def test_generate_slides_html_quality(self, agent_with_mocked_responses):
        """Test that generated HTML meets quality requirements."""
        result = agent_with_mocked_responses.generate_slides(
            question="Create a sales presentation",
            session_id="test-session-4",
            max_slides=5,
        )

        html = result["html"]

        # Verify HTML structure
        assert html.startswith("<!DOCTYPE html>")
        assert "<html>" in html
        assert "<head>" in html
        assert "<body>" in html
        assert "</html>" in html

        # Verify styling present
        assert "<style>" in html or "style=" in html

        # Verify content present
        assert "<h1>" in html or "<h2>" in html
        assert "<div" in html

    def test_agent_error_propagation(self):
        """Test that errors are properly propagated and logged."""
        with patch("src.services.agent.get_databricks_client") as mock_get_client, patch(
            "src.services.agent.ChatDatabricks"
        ) as mock_chat_databricks, patch(
            "langchain_classic.agents.AgentExecutor"
        ) as mock_executor_class:
            # Mock client
            mock_client = Mock()
            mock_get_client.return_value = mock_client

            # Mock model
            mock_model = Mock()
            mock_chat_databricks.return_value = mock_model

            # Mock executor to raise exception
            mock_executor = Mock()
            mock_executor.invoke.side_effect = Exception("LLM service error")
            mock_executor_class.return_value = mock_executor

            agent = SlideGeneratorAgent()

            # Verify error is caught and re-raised as AgentError
            with pytest.raises(AgentError, match="Slide generation failed"):
                agent.generate_slides(question="Test question", session_id="test-session-error")


@pytest.mark.skip(reason="Requires more sophisticated LangChain mocking - mock model returns Mock objects instead of strings")
class TestAgentWithMLflowTracing:
    """Test MLflow tracing integration."""

    def test_mlflow_span_attributes(self, agent_with_mocked_responses):
        """Test that MLflow spans are created with correct attributes."""
        with patch("src.services.agent.mlflow") as mock_mlflow:
            # Mock start_span as context manager
            span = Mock()
            span.__enter__ = Mock(return_value=span)
            span.__exit__ = Mock(return_value=False)
            span.set_attribute = Mock()
            mock_mlflow.start_span.return_value = span

            result = agent_with_mocked_responses.generate_slides(
                question="Test MLflow tracing",
                session_id="test-session-mlflow",
                max_slides=7,
            )

            # Verify span created
            mock_mlflow.start_span.assert_called_with(name="generate_slides")

            # Verify attributes set
            span.set_attribute.assert_any_call("question", "Test MLflow tracing")
            span.set_attribute.assert_any_call("max_slides", 7)
            span.set_attribute.assert_any_call("status", "success")


class TestAgentConfiguration:
    """Test agent configuration handling."""

    def test_agent_uses_settings(self):
        """Test that agent correctly uses settings from configuration."""
        with patch("src.services.agent.get_settings") as mock_get_settings, patch(
            "src.services.agent.get_databricks_client"
        ) as mock_get_client, patch(
            "src.services.agent.ChatDatabricks"
        ) as mock_chat_databricks:
            # Mock settings
            settings = Mock()
            settings.llm.endpoint = "custom-endpoint"
            settings.llm.temperature = 0.5
            settings.llm.max_tokens = 8192
            settings.llm.top_p = 0.9
            settings.llm.timeout = 180
            settings.mlflow.tracking_uri = "databricks"
            settings.mlflow.experiment_name = "/custom/experiment"
            settings.prompts = {"system_prompt": "Custom prompt"}
            mock_get_settings.return_value = settings

            # Mock client
            mock_client = Mock()
            mock_get_client.return_value = mock_client

            # Mock model creation to capture arguments
            mock_model = Mock()
            mock_chat_databricks.return_value = mock_model

            agent = SlideGeneratorAgent()

            # Verify ChatDatabricks called with correct settings
            mock_chat_databricks.assert_called_once()
            call_kwargs = mock_chat_databricks.call_args[1]
            assert call_kwargs["endpoint"] == "custom-endpoint"
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 8192
            assert call_kwargs["top_p"] == 0.9


if __name__ == "__main__":
    """
    Run agent integration tests directly.

    Usage:
        python tests/integration/test_agent_integration.py
    """
    pytest.main([__file__, "-v", "-s", "-m", "integration"])


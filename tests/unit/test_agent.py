"""
Unit tests for agent module with MLFlow tracing.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.services.agent import SlideGeneratorAgent, SlideGeneratorError


@pytest.fixture
def mock_databricks_client():
    """Mock Databricks client for testing."""
    with patch("src.services.agent.get_databricks_client") as mock_client:
        client = Mock()
        mock_client.return_value = client
        yield client


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch("src.services.agent.get_settings") as mock_settings_fn:
        settings = Mock()
        
        # LLM settings
        settings.llm.endpoint = "test-llm-endpoint"
        settings.llm.temperature = 0.7
        settings.llm.max_tokens = 4096
        
        # Genie settings
        settings.genie.space_id = "test-space"
        
        # Output settings
        settings.output.default_max_slides = 10
        settings.output.min_slides = 3
        settings.output.html_template = "professional"
        settings.output.include_metadata = True
        
        # MLFlow settings
        settings.mlflow.experiment_name = "/test/experiment"
        settings.mlflow.tracing.enabled = True
        settings.mlflow.track_cost = True
        settings.mlflow.cost_per_million_input_tokens = 1.0
        settings.mlflow.cost_per_million_output_tokens = 3.0
        
        # Prompts
        settings.prompts = {
            "intent_analysis": "Analyze: {question} (min:{min_slides}, max:{max_slides})",
            "data_interpretation": "Interpret data: {data} for question: {question}",
            "narrative_construction": "Construct narrative: {insights} for {question}, {target_slides} slides",
            "html_generation": "Generate HTML: {narrative}, style: {template_style}, metadata: {include_metadata}",
        }
        
        # Databricks
        settings.databricks_host = "https://test.databricks.com"
        
        mock_settings_fn.return_value = settings
        yield settings


@pytest.fixture
def mock_mlflow():
    """Mock MLFlow for testing."""
    with patch("src.services.agent.mlflow") as mock_mlflow:
        # Mock tracing
        def trace_decorator(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper
        
        mock_mlflow.trace = trace_decorator
        mock_mlflow.set_experiment = Mock()
        mock_mlflow.start_run = MagicMock()
        mock_mlflow.log_params = Mock()
        mock_mlflow.log_metrics = Mock()
        mock_mlflow.log_dict = Mock()
        mock_mlflow.log_text = Mock()
        mock_mlflow.log_param = Mock()
        mock_mlflow.set_span_attribute = Mock()
        mock_mlflow.tracing.enable = Mock()
        mock_mlflow.utils.time.get_current_time_millis = Mock(return_value=1000000)
        
        # Mock experiment
        experiment = Mock()
        experiment.experiment_id = "exp-123"
        mock_mlflow.get_experiment_by_name = Mock(return_value=experiment)
        
        # Mock run context
        run_info = Mock()
        run_info.run_id = "run-456"
        run_info.experiment_id = "exp-123"
        run_info.start_time = 1000000
        
        run = Mock()
        run.info = run_info
        
        mock_mlflow.start_run.return_value.__enter__ = Mock(return_value=run)
        mock_mlflow.start_run.return_value.__exit__ = Mock(return_value=False)
        
        yield mock_mlflow


@pytest.fixture
def mock_mlflow_client():
    """Mock MLFlow client for testing."""
    with patch("src.services.agent.MlflowClient") as mock_client:
        yield mock_client.return_value


@pytest.fixture
def mock_query_genie():
    """Mock query_genie_space function."""
    with patch("src.services.agent.query_genie_space") as mock_query:
        # Default successful response
        mock_query.return_value = {
            "data": [
                {"region": "APAC", "sales": 1000000},
                {"region": "EMEA", "sales": 800000},
            ],
            "conversation_id": "conv-123",
            "row_count": 2,
            "execution_time_seconds": 2.0,
        }
        yield mock_query


def test_agent_initialization(
    mock_databricks_client, mock_settings, mock_mlflow, mock_mlflow_client
):
    """Test agent initialization."""
    agent = SlideGeneratorAgent()
    
    assert agent.client is not None
    assert agent.settings is not None
    mock_mlflow.set_experiment.assert_called_once_with("/test/experiment")
    mock_mlflow.tracing.enable.assert_called_once()


def test_generate_slides_success(
    mock_databricks_client,
    mock_settings,
    mock_mlflow,
    mock_mlflow_client,
    mock_query_genie,
):
    """Test successful slide generation."""
    agent = SlideGeneratorAgent()
    
    # Mock LLM responses
    def mock_llm_call(messages, span_name, **kwargs):
        if "intent" in span_name:
            return json.dumps({
                "data_requirements": ["sales data"],
                "query_strategy": "query Q4 sales",
                "expected_insights": ["growth trends"],
                "suggested_slide_count": 8,
            })
        elif "interpretation" in span_name:
            return json.dumps({
                "key_findings": ["Finding 1", "Finding 2"],
                "trends": ["Trend 1"],
                "anomalies": [],
                "actionable_insights": ["Action 1"],
                "summary": "Test summary",
            })
        elif "narrative" in span_name:
            return json.dumps({
                "title": "Q4 Sales Analysis",
                "subtitle": "Data-driven insights",
                "slides": [
                    {"type": "title", "title": "Q4 Sales", "content": "Analysis"},
                    {"type": "content", "title": "Findings", "content": "Key insights"},
                ],
            })
        elif "html" in span_name:
            return "<html><body><h1>Q4 Sales</h1></body></html>"
        return "{}"
    
    with patch.object(agent, "_call_llm", side_effect=mock_llm_call):
        result = agent.generate_slides("What were Q4 sales?", max_slides=10)
    
    # Verify result structure
    assert "html" in result
    assert "metadata" in result
    assert result["metadata"]["run_id"] == "run-456"
    assert result["metadata"]["slide_count"] == 2
    assert "trace_url" in result["metadata"]
    
    # Verify MLFlow logging
    assert mock_mlflow.log_params.called
    assert mock_mlflow.log_metrics.called
    assert mock_mlflow.log_dict.called
    assert mock_mlflow.log_text.called


def test_generate_slides_error(
    mock_databricks_client,
    mock_settings,
    mock_mlflow,
    mock_mlflow_client,
    mock_query_genie,
):
    """Test slide generation with error."""
    agent = SlideGeneratorAgent()
    
    # Mock LLM to raise error
    with patch.object(agent, "_call_llm", side_effect=Exception("LLM error")):
        with pytest.raises(SlideGeneratorError) as exc_info:
            agent.generate_slides("Test question")
    
    assert "Failed to generate slides" in str(exc_info.value)
    
    # Verify error was logged
    assert mock_mlflow.log_metrics.called


def test_analyze_intent(
    mock_databricks_client, mock_settings, mock_mlflow, mock_mlflow_client
):
    """Test intent analysis."""
    agent = SlideGeneratorAgent()
    
    # Mock LLM response
    intent_json = json.dumps({
        "data_requirements": ["sales data", "customer data"],
        "query_strategy": "analyze quarterly trends",
        "expected_insights": ["growth", "regional performance"],
        "suggested_slide_count": 8,
    })
    
    with patch.object(agent, "_call_llm", return_value=intent_json):
        intent = agent._analyze_intent("What were Q4 sales?", max_slides=10)
    
    assert "data_requirements" in intent
    assert len(intent["data_requirements"]) == 2
    assert intent["suggested_slide_count"] == 8


def test_analyze_intent_invalid_json(
    mock_databricks_client, mock_settings, mock_mlflow, mock_mlflow_client
):
    """Test intent analysis with invalid JSON response."""
    agent = SlideGeneratorAgent()
    
    # Mock LLM to return invalid JSON
    with patch.object(agent, "_call_llm", return_value="Not valid JSON"):
        intent = agent._analyze_intent("Test question", max_slides=10)
    
    # Should fallback to default structure
    assert "data_requirements" in intent
    assert "query_strategy" in intent


def test_execute_tool_loop(
    mock_databricks_client,
    mock_settings,
    mock_mlflow,
    mock_mlflow_client,
    mock_query_genie,
):
    """Test tool execution loop."""
    agent = SlideGeneratorAgent()
    
    # Mock decision to finish after first query
    with patch.object(
        agent, "_decide_next_action", return_value={"action": "finish"}
    ):
        data_context = agent._execute_tool_loop("What were sales?", None)
    
    # Verify tool was called
    assert mock_query_genie.called
    
    # Verify data context
    assert "data" in data_context
    assert "row_count" in data_context
    assert data_context["row_count"] == 2


def test_call_llm_with_usage(
    mock_databricks_client, mock_settings, mock_mlflow, mock_mlflow_client
):
    """Test LLM call with token usage tracking."""
    agent = SlideGeneratorAgent()
    
    # Mock serving endpoint response
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message.content = "Test response"
    
    # Mock usage
    usage = Mock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    response.usage = usage
    
    mock_databricks_client.serving_endpoints.query.return_value = response
    
    # Call LLM
    content = agent._call_llm(
        messages=[{"role": "user", "content": "Test"}], span_name="test_call"
    )
    
    assert content == "Test response"
    
    # Verify metrics were logged
    assert mock_mlflow.log_metrics.called
    
    # Verify cost calculation
    calls = mock_mlflow.log_metrics.call_args_list
    metrics_logged = {}
    for call in calls:
        metrics_logged.update(call[0][0])
    
    assert "test_call.prompt_tokens" in metrics_logged
    assert "test_call.completion_tokens" in metrics_logged
    assert "test_call.cost_total_usd" in metrics_logged


def test_count_slides(
    mock_databricks_client, mock_settings, mock_mlflow, mock_mlflow_client
):
    """Test slide counting."""
    agent = SlideGeneratorAgent()
    
    narrative = {
        "slides": [
            {"type": "title", "title": "Slide 1"},
            {"type": "content", "title": "Slide 2"},
            {"type": "content", "title": "Slide 3"},
        ]
    }
    
    count = agent._count_slides(narrative)
    assert count == 3


def test_get_trace_url(
    mock_databricks_client, mock_settings, mock_mlflow, mock_mlflow_client
):
    """Test trace URL generation."""
    agent = SlideGeneratorAgent()
    
    url = agent._get_trace_url("run-123")
    
    assert "https://test.databricks.com" in url
    assert "exp-123" in url
    assert "run-123" in url
    assert "traces" in url


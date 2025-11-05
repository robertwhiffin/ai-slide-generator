# Phase 2: MLOps Architecture with MLFlow 3.0

## Overview

This document outlines the architecture and approach for Phase 2 implementation, integrating MLFlow 3.0 best practices for MLOps including tracing, experiment tracking, and deployment of our agent-based slide generator to Databricks Model Serving endpoints.

## Objectives

1. **MLFlow 3.0 Tracing**: Full observability of agent execution with distributed tracing
2. **Experiment Tracking**: Track all runs, parameters, metrics, and artifacts
3. **Model Packaging**: Package agent as deployable MLflow model (pyfunc)
4. **Serving Endpoint Deployment**: Deploy to Databricks Model Serving for production inference
5. **Local-to-Cloud Workflow**: Seamless development locally, deployment to Databricks

## Architecture Components

### 1. Agent Architecture with MLFlow Tracing

```
┌─────────────────────────────────────────────────────────────┐
│                    MLFlow Traced Agent                      │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Agent Orchestrator (SlideGeneratorAgent)           │  │
│  │  - MLFlow Trace: @mlflow.trace() decorators         │  │
│  │  - Span tracking for each step                       │  │
│  │  - Token usage tracking                              │  │
│  └────────┬─────────────────────────────────────┬───────┘  │
│           │                                     │           │
│  ┌────────▼─────────┐              ┌───────────▼────────┐  │
│  │  LLM Client       │              │  Tool Registry      │  │
│  │  - Foundation     │              │  - query_genie      │  │
│  │    Model API      │              │  - Future tools     │  │
│  │  - Traced calls   │              │  - Traced execution │  │
│  └──────────────────┘              └────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
            ┌──────────────────────────┐
            │  MLFlow Tracking Server   │
            │  (Databricks Workspace)   │
            │  - Traces                 │
            │  - Metrics                │
            │  - Parameters             │
            │  - Artifacts              │
            └──────────────────────────┘
```

### 2. MLFlow Model Packaging Strategy

We'll package the agent as a custom MLflow PyFunc model for deployment:

```python
class SlideGeneratorMLflowWrapper(mlflow.pyfunc.PythonModel):
    """
    MLflow wrapper for slide generator agent.
    Packages the agent with all dependencies for serving.
    """
    
    def load_context(self, context):
        """Load model and dependencies on serving endpoint"""
        # Initialize Databricks client
        # Load configuration
        # Initialize agent with tracing disabled (handled by serving)
        
    def predict(self, context, model_input):
        """
        Main inference method called by serving endpoint.
        
        Input: DataFrame with columns: question, max_slides, genie_space_id
        Output: DataFrame with columns: html, metadata
        """
        # Process input
        # Generate slides with agent
        # Return HTML output
```

### 3. MLFlow 3.0 Tracing Implementation

#### Tracing Hierarchy

```
Run: "slide-generation-20250105-123456"
│
├─ Span: "agent_orchestration"
│  ├─ Attributes: question, max_slides, model_endpoint
│  ├─ Span: "intent_analysis"
│  │  └─ LLM Call with token counts
│  ├─ Span: "tool_execution_loop"
│  │  ├─ Span: "tool_call_1_query_genie"
│  │  │  ├─ Input: query, conversation_id
│  │  │  ├─ Output: data_results
│  │  │  └─ Metrics: execution_time, row_count
│  │  ├─ Span: "tool_call_2_query_genie"
│  │  │  └─ ...
│  │  └─ Span: "tool_synthesis"
│  │     └─ LLM Call
│  ├─ Span: "narrative_construction"
│  │  └─ LLM Call
│  └─ Span: "html_generation"
│     └─ LLM Call
│
└─ Metrics: total_tokens, execution_time, slide_count
```

## Implementation Details

### Phase 2.1: MLFlow Tracing Setup

#### Dependencies

```toml
# pyproject.toml additions
[project]
dependencies = [
    "mlflow>=2.10.0",  # MLFlow 3.0 features
    "databricks-sdk>=0.18.0",
    "opentelemetry-api>=1.20.0",  # For advanced tracing
    "opentelemetry-sdk>=1.20.0",
]
```

#### Configuration (`config/mlflow.yaml`)

```yaml
mlflow:
  # Tracking Configuration
  tracking_uri: "databricks"
  experiment_name: "/Users/{username}/ai-slide-generator"
  
  # Tracing Configuration
  tracing:
    enabled: true
    backend: "databricks"  # Uses Databricks native tracing
    sample_rate: 1.0  # Trace 100% of requests in dev, adjust for prod
    capture_input_output: true
    capture_model_config: true
    
  # Model Registry
  registry_uri: "databricks-uc"  # Unity Catalog
  model_name: "main.ml_models.slide_generator"
  
  # Serving Configuration
  serving:
    workload_size: "Small"  # Small, Medium, Large
    scale_to_zero_enabled: true
    min_scale: 0
    max_scale: 5
    
  # Logging Configuration  
  logging:
    log_models: true
    log_input_examples: true
    log_model_signatures: true
    log_system_metrics: true
```

#### Agent Implementation with Tracing

```python
# src/services/agent.py
import mlflow
from mlflow.tracking import MlflowClient
from typing import Dict, Optional
import time

class SlideGeneratorAgent:
    """
    Tool-using agent for slide generation with comprehensive MLFlow tracing.
    """
    
    def __init__(self):
        self.client = get_databricks_client()
        self.mlflow_client = MlflowClient()
        self.settings = get_settings()
        
        # Set MLFlow experiment
        mlflow.set_experiment(self.settings.mlflow.experiment_name)
        
        # Enable autologging for supported frameworks
        mlflow.autolog(
            log_input_examples=True,
            log_model_signatures=True,
            log_models=False,  # We'll log manually
            silent=False
        )
    
    @mlflow.trace(name="generate_slides", span_type="AGENT")
    def generate_slides(
        self,
        question: str,
        max_slides: int = 10,
        genie_space_id: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Main entry point for slide generation with full tracing.
        
        This creates a traced run with all agent steps recorded.
        """
        
        # Start MLFlow run
        with mlflow.start_run(run_name=f"slide-gen-{int(time.time())}") as run:
            
            # Log input parameters
            mlflow.log_params({
                "question": question[:100],  # Truncate for display
                "max_slides": max_slides,
                "genie_space_id": genie_space_id or "default",
                "model_endpoint": self.settings.llm.endpoint,
                "temperature": self.settings.llm.temperature,
            })
            
            try:
                # Step 1: Analyze intent
                intent = self._analyze_intent(question)
                mlflow.log_dict(intent, "intent_analysis.json")
                
                # Step 2: Execute tool loop
                data_context = self._execute_tool_loop(question, genie_space_id)
                mlflow.log_dict(data_context, "data_context.json")
                
                # Step 3: Construct narrative
                narrative = self._construct_narrative(data_context, intent)
                mlflow.log_text(narrative, "narrative.txt")
                
                # Step 4: Generate HTML
                html_output = self._generate_html(narrative, max_slides)
                mlflow.log_text(html_output, "output.html")
                
                # Log success metrics
                mlflow.log_metrics({
                    "success": 1,
                    "slide_count": self._count_slides(html_output),
                    "execution_time_seconds": time.time() - run.info.start_time / 1000,
                })
                
                return {
                    "html": html_output,
                    "metadata": {
                        "run_id": run.info.run_id,
                        "experiment_id": run.info.experiment_id,
                        "trace_url": self._get_trace_url(run.info.run_id)
                    }
                }
                
            except Exception as e:
                # Log failure
                mlflow.log_metrics({"success": 0})
                mlflow.log_param("error", str(e))
                raise
    
    @mlflow.trace(name="analyze_intent", span_type="LLM")
    def _analyze_intent(self, question: str) -> Dict:
        """Analyze user intent with traced LLM call."""
        
        prompt = self.settings.prompts.intent_analysis_prompt.format(
            question=question
        )
        
        response = self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            span_name="intent_analysis_llm_call"
        )
        
        # Parse and return structured intent
        return self._parse_intent(response)
    
    @mlflow.trace(name="execute_tool_loop", span_type="AGENT")
    def _execute_tool_loop(
        self,
        question: str,
        genie_space_id: Optional[str]
    ) -> Dict:
        """
        Execute agent tool loop with tracing for each tool call.
        """
        
        tool_outputs = []
        conversation_state = {
            "question": question,
            "genie_conversation_id": None,
            "iterations": 0,
            "max_iterations": 5
        }
        
        while conversation_state["iterations"] < conversation_state["max_iterations"]:
            
            # Determine next action
            action = self._decide_next_action(
                conversation_state,
                tool_outputs
            )
            
            if action["type"] == "finish":
                break
            
            if action["type"] == "query_genie":
                # Execute Genie tool with tracing
                result = self._execute_genie_tool(
                    query=action["query"],
                    conversation_id=conversation_state["genie_conversation_id"],
                    genie_space_id=genie_space_id,
                    iteration=conversation_state["iterations"]
                )
                tool_outputs.append(result)
                conversation_state["genie_conversation_id"] = result.get("conversation_id")
            
            conversation_state["iterations"] += 1
        
        # Log tool execution summary
        mlflow.log_metrics({
            "tool_calls_count": len(tool_outputs),
            "tool_iterations": conversation_state["iterations"]
        })
        
        return self._synthesize_tool_outputs(tool_outputs)
    
    @mlflow.trace(name="query_genie_tool", span_type="TOOL")
    def _execute_genie_tool(
        self,
        query: str,
        conversation_id: Optional[str],
        genie_space_id: Optional[str],
        iteration: int
    ) -> Dict:
        """Execute Genie tool with comprehensive tracing."""
        
        from src.services.tools import query_genie_space
        
        # Set span attributes
        mlflow.set_span_attribute("tool.name", "query_genie_space")
        mlflow.set_span_attribute("tool.iteration", iteration)
        mlflow.set_span_attribute("tool.query", query[:200])
        
        start_time = time.time()
        
        result = query_genie_space(
            query=query,
            conversation_id=conversation_id,
            genie_space_id=genie_space_id
        )
        
        execution_time = time.time() - start_time
        
        # Log tool-specific metrics
        mlflow.log_metrics({
            f"tool.genie.execution_time.iter_{iteration}": execution_time,
            f"tool.genie.row_count.iter_{iteration}": result.get("row_count", 0)
        })
        
        # Set span output
        mlflow.set_span_attribute("tool.output_rows", result.get("row_count", 0))
        
        return result
    
    @mlflow.trace(name="call_llm", span_type="LLM")
    def _call_llm(
        self,
        messages: list,
        span_name: str = "llm_call",
        **kwargs
    ) -> str:
        """
        Call LLM with automatic tracing of tokens and latency.
        """
        
        start_time = time.time()
        
        # Call Foundation Model API
        response = self.client.serving_endpoints.query(
            name=self.settings.llm.endpoint,
            inputs={
                "messages": messages,
                "temperature": kwargs.get("temperature", self.settings.llm.temperature),
                "max_tokens": kwargs.get("max_tokens", self.settings.llm.max_tokens),
            }
        )
        
        latency = time.time() - start_time
        
        # Extract response and usage
        content = response.choices[0].message.content
        usage = response.usage
        
        # Log LLM metrics
        mlflow.log_metrics({
            f"{span_name}.latency": latency,
            f"{span_name}.prompt_tokens": usage.prompt_tokens,
            f"{span_name}.completion_tokens": usage.completion_tokens,
            f"{span_name}.total_tokens": usage.total_tokens,
        })
        
        # Set span attributes for tracing
        mlflow.set_span_attribute("llm.model", self.settings.llm.endpoint)
        mlflow.set_span_attribute("llm.prompt_tokens", usage.prompt_tokens)
        mlflow.set_span_attribute("llm.completion_tokens", usage.completion_tokens)
        mlflow.set_span_attribute("llm.total_tokens", usage.total_tokens)
        mlflow.set_span_attribute("llm.latency_seconds", latency)
        
        return content
    
    def _get_trace_url(self, run_id: str) -> str:
        """Generate URL to view trace in Databricks."""
        workspace_url = self.settings.databricks_host
        experiment_id = mlflow.get_experiment_by_name(
            self.settings.mlflow.experiment_name
        ).experiment_id
        return f"{workspace_url}/#mlflow/experiments/{experiment_id}/runs/{run_id}/traces"
```

#### Tool Implementation with Tracing

```python
# src/services/tools.py
import mlflow
from typing import Dict, Optional
from databricks.sdk.service.genie import MessageQuery

@mlflow.trace(name="query_genie_space", span_type="TOOL")
def query_genie_space(
    query: str,
    conversation_id: Optional[str] = None,
    genie_space_id: Optional[str] = None
) -> Dict:
    """
    Query Databricks Genie space with tracing.
    
    Returns:
        {
            "data": [...],
            "conversation_id": "...",
            "row_count": N,
            "query_type": "natural_language" | "sql"
        }
    """
    
    client = get_databricks_client()
    settings = get_settings()
    space_id = genie_space_id or settings.genie.default_space_id
    
    # Set span attributes
    mlflow.set_span_attribute("genie.space_id", space_id)
    mlflow.set_span_attribute("genie.query", query[:200])
    mlflow.set_span_attribute("genie.has_conversation_id", conversation_id is not None)
    
    try:
        # Create or continue conversation
        if conversation_id is None:
            # Start new conversation
            conversation = client.genie.start_conversation(space_id=space_id)
            conversation_id = conversation.conversation_id
            mlflow.set_span_attribute("genie.new_conversation", True)
        else:
            mlflow.set_span_attribute("genie.new_conversation", False)
        
        # Execute query
        message = client.genie.execute_message_query(
            space_id=space_id,
            conversation_id=conversation_id,
            content=MessageQuery(query=query)
        )
        
        # Wait for completion (with timeout)
        result = client.genie.wait_for_message_query(
            space_id=space_id,
            conversation_id=conversation_id,
            message_id=message.message_id,
            timeout=settings.genie.timeout
        )
        
        # Extract data
        data = result.attachments[0].query_result.data_array if result.attachments else []
        
        # Log metrics
        row_count = len(data)
        mlflow.log_metrics({
            "genie.result_row_count": row_count,
            "genie.success": 1
        })
        
        mlflow.set_span_attribute("genie.row_count", row_count)
        
        return {
            "data": data,
            "conversation_id": conversation_id,
            "row_count": row_count,
            "query_type": "natural_language",
            "sql": result.attachments[0].query_result.statement_text if result.attachments else None
        }
        
    except Exception as e:
        mlflow.log_metrics({"genie.success": 0})
        mlflow.set_span_attribute("genie.error", str(e))
        raise
```

### Phase 2.2: MLflow Model Packaging

#### Custom PyFunc Wrapper

```python
# src/models/mlflow_wrapper.py
import mlflow
from mlflow.pyfunc import PythonModel
from mlflow.models import infer_signature
import pandas as pd
from typing import Dict, Any
import yaml
import os

class SlideGeneratorMLflowModel(PythonModel):
    """
    MLflow PyFunc wrapper for deploying slide generator to serving endpoints.
    
    This wrapper packages the agent with all dependencies and configuration
    for deployment to Databricks Model Serving.
    """
    
    def __init__(self):
        self.agent = None
        self.config = None
    
    def load_context(self, context):
        """
        Load model and dependencies when serving endpoint starts.
        Called once on endpoint initialization.
        """
        
        # Load configuration from artifacts
        config_path = context.artifacts.get("config")
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        
        # Initialize settings with config
        os.environ["MLFLOW_SERVING_MODE"] = "true"
        
        # Import here to avoid loading during packaging
        from src.config.settings import initialize_settings
        from src.services.agent import SlideGeneratorAgent
        
        # Initialize settings with serving config
        initialize_settings(config_override=self.config)
        
        # Initialize agent (tracing handled by serving infrastructure)
        self.agent = SlideGeneratorAgent()
    
    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        """
        Main prediction method called by serving endpoint.
        
        Input DataFrame columns:
            - question: str
            - max_slides: int (optional, default from config)
            - genie_space_id: str (optional, default from config)
        
        Output DataFrame columns:
            - html: str
            - slide_count: int
            - trace_url: str
            - error: str (if error occurred)
        """
        
        results = []
        
        for idx, row in model_input.iterrows():
            try:
                # Extract inputs
                question = row["question"]
                max_slides = row.get("max_slides", self.config.get("output", {}).get("default_max_slides", 10))
                genie_space_id = row.get("genie_space_id", None)
                
                # Generate slides
                result = self.agent.generate_slides(
                    question=question,
                    max_slides=max_slides,
                    genie_space_id=genie_space_id
                )
                
                # Format output
                results.append({
                    "html": result["html"],
                    "slide_count": result["metadata"].get("slide_count", 0),
                    "trace_url": result["metadata"].get("trace_url", ""),
                    "error": None
                })
                
            except Exception as e:
                results.append({
                    "html": None,
                    "slide_count": 0,
                    "trace_url": "",
                    "error": str(e)
                })
        
        return pd.DataFrame(results)


def log_model_to_mlflow(
    model_name: str,
    experiment_name: str,
    run_name: str = "model_packaging"
) -> str:
    """
    Package and log the slide generator as an MLflow model.
    
    Returns:
        run_id: MLflow run ID where model was logged
    """
    
    mlflow.set_experiment(experiment_name)
    
    with mlflow.start_run(run_name=run_name) as run:
        
        # Create model instance
        model = SlideGeneratorMLflowModel()
        
        # Define input/output signature
        input_schema = {
            "question": "What were our Q4 2023 sales?",
            "max_slides": 10,
            "genie_space_id": None
        }
        
        output_schema = {
            "html": "<html>...</html>",
            "slide_count": 10,
            "trace_url": "https://...",
            "error": None
        }
        
        signature = infer_signature(
            pd.DataFrame([input_schema]),
            pd.DataFrame([output_schema])
        )
        
        # Specify artifacts to include
        artifacts = {
            "config": "config/config.yaml",
            "prompts": "config/prompts.yaml"
        }
        
        # Define pip requirements
        pip_requirements = [
            "databricks-sdk>=0.18.0",
            "mlflow>=2.10.0",
            "pydantic>=2.0.0",
            "pyyaml>=6.0",
            "jinja2>=3.0.0",
        ]
        
        # Log model
        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=model,
            artifacts=artifacts,
            pip_requirements=pip_requirements,
            signature=signature,
            input_example=pd.DataFrame([input_schema]),
            registered_model_name=model_name
        )
        
        # Log metadata
        mlflow.log_params({
            "model_type": "agent_based_slide_generator",
            "agent_framework": "custom_tool_calling",
            "llm_integration": "databricks_foundation_models",
            "tracing_enabled": True
        })
        
        print(f"Model logged to MLflow with run_id: {run.info.run_id}")
        print(f"Registered as: {model_name}")
        
        return run.info.run_id
```

#### Model Registration Script

```python
# scripts/register_model.py
"""
Register slide generator model to Unity Catalog and deploy to serving endpoint.

Usage:
    python scripts/register_model.py --environment dev
    python scripts/register_model.py --environment prod --approve
"""

import argparse
import mlflow
from mlflow.tracking import MlflowClient
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ServedEntityInput
)

def register_and_deploy(
    environment: str = "dev",
    auto_approve: bool = False
):
    """Register model and deploy to serving endpoint."""
    
    client = MlflowClient()
    w = WorkspaceClient()
    
    # Configuration based on environment
    config = {
        "dev": {
            "model_name": "main.ml_models.slide_generator_dev",
            "endpoint_name": "slide-generator-dev",
            "workload_size": "Small",
            "scale_to_zero": True,
        },
        "prod": {
            "model_name": "main.ml_models.slide_generator",
            "endpoint_name": "slide-generator",
            "workload_size": "Medium",
            "scale_to_zero": False,
        }
    }
    
    env_config = config[environment]
    
    # Log and register model
    from src.models.mlflow_wrapper import log_model_to_mlflow
    
    run_id = log_model_to_mlflow(
        model_name=env_config["model_name"],
        experiment_name=f"/Users/{w.current_user.me().user_name}/ai-slide-generator",
        run_name=f"register_{environment}"
    )
    
    # Get latest model version
    latest_version = client.search_model_versions(
        filter_string=f"name='{env_config['model_name']}'",
        order_by=["version_number DESC"],
        max_results=1
    )[0]
    
    print(f"Latest model version: {latest_version.version}")
    
    # Transition to appropriate stage
    if environment == "dev":
        client.transition_model_version_stage(
            name=env_config["model_name"],
            version=latest_version.version,
            stage="Staging"
        )
        deploy = True
    else:
        # Production requires approval
        if auto_approve:
            client.transition_model_version_stage(
                name=env_config["model_name"],
                version=latest_version.version,
                stage="Production"
            )
            deploy = True
        else:
            print(f"Model registered as version {latest_version.version}")
            print("Run with --approve to deploy to production")
            deploy = False
    
    # Deploy to serving endpoint
    if deploy:
        deploy_to_endpoint(
            workspace_client=w,
            model_name=env_config["model_name"],
            model_version=latest_version.version,
            endpoint_name=env_config["endpoint_name"],
            workload_size=env_config["workload_size"],
            scale_to_zero=env_config["scale_to_zero"]
        )
    
    return run_id, latest_version.version


def deploy_to_endpoint(
    workspace_client: WorkspaceClient,
    model_name: str,
    model_version: str,
    endpoint_name: str,
    workload_size: str = "Small",
    scale_to_zero: bool = True
):
    """Deploy model to Databricks Model Serving endpoint."""
    
    print(f"Deploying {model_name} version {model_version} to {endpoint_name}...")
    
    # Check if endpoint exists
    try:
        existing_endpoint = workspace_client.serving_endpoints.get(endpoint_name)
        print(f"Endpoint {endpoint_name} exists, updating...")
        
        # Update endpoint with new model version
        workspace_client.serving_endpoints.update_config(
            name=endpoint_name,
            served_entities=[
                ServedEntityInput(
                    entity_name=model_name,
                    entity_version=model_version,
                    workload_size=workload_size,
                    scale_to_zero_enabled=scale_to_zero
                )
            ]
        )
        
    except Exception:
        print(f"Creating new endpoint {endpoint_name}...")
        
        # Create new endpoint
        workspace_client.serving_endpoints.create(
            name=endpoint_name,
            config=EndpointCoreConfigInput(
                served_entities=[
                    ServedEntityInput(
                        entity_name=model_name,
                        entity_version=model_version,
                        workload_size=workload_size,
                        scale_to_zero_enabled=scale_to_zero
                    )
                ]
            )
        )
    
    # Wait for endpoint to be ready
    workspace_client.serving_endpoints.wait_get_serving_endpoint_not_updating(
        endpoint_name
    )
    
    print(f"✅ Endpoint {endpoint_name} is ready!")
    print(f"🔗 Endpoint URL: {workspace_client.config.host}/serving-endpoints/{endpoint_name}/invocations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=["dev", "prod"], default="dev")
    parser.add_argument("--approve", action="store_true", help="Auto-approve production deployment")
    args = parser.parse_args()
    
    register_and_deploy(args.environment, args.approve)
```

### Phase 2.3: Local Development to Production Workflow

#### Development Workflow

```bash
# 1. Local Development with Tracing
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-token"

# Run locally with tracing to Databricks
python -c "
from src.services.agent import SlideGeneratorAgent
agent = SlideGeneratorAgent()
result = agent.generate_slides('What were Q4 sales?')
print(result['metadata']['trace_url'])
"

# View traces in Databricks MLflow UI

# 2. Test with local API
uvicorn src.main:app --reload

curl -X POST http://localhost:8000/generate-slides \
  -H "Content-Type: application/json" \
  -d '{"question": "What were Q4 sales?", "max_slides": 10}'

# 3. Run tests with tracing
pytest tests/ --capture=no

# 4. Package and register model
python scripts/register_model.py --environment dev

# 5. Test deployed endpoint
python scripts/test_endpoint.py --endpoint slide-generator-dev

# 6. Deploy to production (after validation)
python scripts/register_model.py --environment prod --approve
```

#### Testing Deployed Endpoint

```python
# scripts/test_endpoint.py
"""Test deployed model serving endpoint."""

import requests
import os
import argparse

def test_endpoint(endpoint_name: str):
    """Test serving endpoint with sample queries."""
    
    host = os.environ["DATABRICKS_HOST"]
    token = os.environ["DATABRICKS_TOKEN"]
    
    url = f"{host}/serving-endpoints/{endpoint_name}/invocations"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Test cases
    test_cases = [
        {
            "question": "What were our Q4 2023 sales by region?",
            "max_slides": 10
        },
        {
            "question": "Show me customer churn trends",
            "max_slides": 8
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"Test Case {i}: {test_case['question']}")
        print(f"{'='*60}")
        
        # Format for serving endpoint (dataframe_records format)
        payload = {
            "dataframe_records": [test_case]
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            predictions = result["predictions"]
            
            print(f"✅ Success!")
            print(f"Slide Count: {predictions[0]['slide_count']}")
            print(f"Trace URL: {predictions[0]['trace_url']}")
            print(f"HTML Length: {len(predictions[0]['html'])} chars")
            
            if predictions[0]["error"]:
                print(f"⚠️  Error: {predictions[0]['error']}")
        else:
            print(f"❌ Request failed: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True, help="Endpoint name")
    args = parser.parse_args()
    
    test_endpoint(args.endpoint)
```

## MLFlow 3.0 Best Practices

### 1. Comprehensive Tracing

- **Use @mlflow.trace() decorators** on all key functions
- **Set span attributes** for debugging (model names, token counts, etc.)
- **Log inputs/outputs** at each step for reproducibility
- **Hierarchical spans** for complex workflows (agent → tools → LLM calls)

### 2. Experiment Organization

```python
# Experiment naming convention
/Users/{username}/ai-slide-generator/{environment}

# Run naming convention
f"slide-gen-{environment}-{timestamp}-{short_hash}"

# Tag best practices
mlflow.set_tags({
    "environment": "dev",
    "version": "v1.2.0",
    "model_type": "agent",
    "framework": "custom",
    "deployment_target": "model_serving"
})
```

### 3. Model Signature and Input Examples

Always define explicit signatures for serving:

```python
signature = infer_signature(
    model_input=pd.DataFrame([{
        "question": "Sample question",
        "max_slides": 10,
        "genie_space_id": None
    }]),
    model_output=pd.DataFrame([{
        "html": "<html>...</html>",
        "slide_count": 10,
        "trace_url": "https://...",
        "error": None
    }])
)
```

### 4. Metrics Tracking

Track comprehensive metrics:

```python
# Execution metrics
mlflow.log_metrics({
    "execution_time_seconds": duration,
    "slide_count": count,
    "tool_calls_count": tool_count,
    "total_tokens": tokens,
    "success": 1 or 0
})

# Cost tracking
mlflow.log_metrics({
    "input_tokens_cost": input_cost,
    "output_tokens_cost": output_cost,
    "total_cost_usd": total_cost
})

# Quality metrics (if available)
mlflow.log_metrics({
    "coherence_score": score,
    "data_accuracy": accuracy,
    "user_rating": rating
})
```

### 5. Artifact Management

Log relevant artifacts:

```python
# Log generated output
mlflow.log_text(html_output, "output.html")

# Log intermediate results
mlflow.log_dict(data_context, "data_context.json")
mlflow.log_text(narrative, "narrative.txt")

# Log configuration
mlflow.log_dict(config, "run_config.yaml")
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Developer Workstation                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Local Development                               │   │
│  │  - Edit code                                     │   │
│  │  - Run tests with local tracing                 │   │
│  │  - View traces in Databricks                    │   │
│  └─────────────────┬───────────────────────────────┘   │
└────────────────────┼─────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│           Databricks Workspace (MLFlow)                  │
│  ┌─────────────────────────────────────────────────┐   │
│  │  MLFlow Tracking Server                         │   │
│  │  - Experiments                                   │   │
│  │  - Runs with traces                             │   │
│  │  - Metrics & parameters                         │   │
│  │  - Artifacts (HTML, configs)                    │   │
│  └─────────────────┬───────────────────────────────┘   │
│                    │                                     │
│  ┌─────────────────▼───────────────────────────────┐   │
│  │  Model Registry (Unity Catalog)                 │   │
│  │  - main.ml_models.slide_generator_dev           │   │
│  │  - main.ml_models.slide_generator (prod)        │   │
│  │  - Version history                              │   │
│  └─────────────────┬───────────────────────────────┘   │
│                    │                                     │
│  ┌─────────────────▼───────────────────────────────┐   │
│  │  Model Serving Endpoints                        │   │
│  │  ┌───────────────────────────────────────────┐ │   │
│  │  │  slide-generator-dev (Staging)             │ │   │
│  │  │  - Small workload                          │ │   │
│  │  │  - Scale to zero enabled                   │ │   │
│  │  └───────────────────────────────────────────┘ │   │
│  │  ┌───────────────────────────────────────────┐ │   │
│  │  │  slide-generator (Production)              │ │   │
│  │  │  - Medium workload                         │ │   │
│  │  │  - Auto-scaling 1-5 instances              │ │   │
│  │  │  - Tracing enabled                         │ │   │
│  │  └───────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│               Client Applications                        │
│  - REST API calls to serving endpoint                   │
│  - Receives HTML slides + metadata                      │
│  - Can view traces via returned trace_url               │
└─────────────────────────────────────────────────────────┘
```

## Testing Strategy

### Unit Tests with Tracing

```python
# tests/unit/test_agent_with_tracing.py
import pytest
import mlflow
from unittest.mock import Mock, patch

@pytest.fixture
def mock_mlflow_tracking():
    """Mock MLflow tracking for unit tests."""
    with patch("mlflow.start_run"):
        with patch("mlflow.log_params"):
            with patch("mlflow.log_metrics"):
                yield

def test_agent_generate_slides_traced(mock_mlflow_tracking, mock_databricks_client):
    """Test agent execution with tracing mocked."""
    
    from src.services.agent import SlideGeneratorAgent
    
    agent = SlideGeneratorAgent()
    
    # Mock tool outputs
    with patch.object(agent, "_execute_tool_loop") as mock_tools:
        mock_tools.return_value = {"sales_data": [{"region": "APAC", "amount": 1000000}]}
        
        result = agent.generate_slides(
            question="What were Q4 sales?",
            max_slides=10
        )
        
        assert "html" in result
        assert "metadata" in result
        assert "trace_url" in result["metadata"]
```

### Integration Tests

```python
# tests/integration/test_mlflow_integration.py
import pytest
import mlflow
from databricks.sdk import WorkspaceClient

@pytest.mark.integration
def test_full_workflow_with_real_tracing():
    """Test complete workflow with real MLflow tracing."""
    
    from src.services.agent import SlideGeneratorAgent
    
    # This test requires real Databricks connection
    agent = SlideGeneratorAgent()
    
    result = agent.generate_slides(
        question="What were Q4 sales?",
        max_slides=5
    )
    
    # Verify result
    assert result["html"] is not None
    assert len(result["html"]) > 0
    
    # Verify trace was created
    run_id = result["metadata"]["run_id"]
    client = mlflow.tracking.MlflowClient()
    run = client.get_run(run_id)
    
    assert run.info.status == "FINISHED"
    assert "question" in run.data.params
    assert "execution_time_seconds" in run.data.metrics
```

## Security Considerations

### Secrets Management

```python
# config/settings.py - secure secrets handling
from pydantic_settings import BaseSettings
from pydantic import SecretStr

class Settings(BaseSettings):
    """Settings with secure secret handling."""
    
    # Secrets (never logged)
    databricks_token: SecretStr
    
    # Configuration (can be logged)
    databricks_host: str
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        
    def get_databricks_token(self) -> str:
        """Get token value securely."""
        return self.databricks_token.get_secret_value()

# MLflow logging - exclude secrets
mlflow.log_params({
    "databricks_host": settings.databricks_host,
    # NEVER log: databricks_token
    "model_endpoint": settings.llm.endpoint
})
```

### Endpoint Security

- **Authentication**: Serving endpoints use workspace authentication
- **Authorization**: Unity Catalog permissions control model access
- **Rate Limiting**: Configure endpoint quotas
- **Input Validation**: Validate all inputs in PyFunc predict method

## Monitoring and Observability

### Metrics Dashboard

Key metrics to monitor in Databricks:

1. **Latency Metrics**
   - p50, p95, p99 latency
   - Per-component latency (LLM, Genie, total)
   
2. **Cost Metrics**
   - Total tokens per request
   - Estimated cost per request
   - Daily/weekly cost trends

3. **Quality Metrics**
   - Success rate
   - Error rate by type
   - Slide count distribution

4. **Resource Metrics**
   - Endpoint utilization
   - Scaling events
   - Cold start frequency

### Alerting

Set up alerts for:
- Error rate > 5%
- p95 latency > 60 seconds
- Daily cost exceeds budget
- Endpoint downtime

## Rollback Strategy

```python
# scripts/rollback_model.py
"""Rollback serving endpoint to previous model version."""

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ServedEntityInput

def rollback_endpoint(endpoint_name: str, target_version: str):
    """Rollback endpoint to specific model version."""
    
    w = WorkspaceClient()
    
    # Get current endpoint config
    endpoint = w.serving_endpoints.get(endpoint_name)
    served_entities = endpoint.config.served_entities
    
    # Update to target version
    served_entities[0].entity_version = target_version
    
    # Update endpoint
    w.serving_endpoints.update_config(
        name=endpoint_name,
        served_entities=served_entities
    )
    
    print(f"Rolled back {endpoint_name} to version {target_version}")
```

## Implementation Checklist

### Phase 2.1: Tracing Setup ✓
- [ ] Add MLflow 3.0 dependencies
- [ ] Configure MLflow tracking to Databricks
- [ ] Implement @mlflow.trace() decorators on agent
- [ ] Add span attributes for debugging
- [ ] Implement LLM call tracing with token tracking
- [ ] Implement tool call tracing
- [ ] Test local tracing to Databricks
- [ ] Verify traces in Databricks UI

### Phase 2.2: Model Packaging ✓
- [ ] Create MLflow PyFunc wrapper
- [ ] Define model signature
- [ ] Configure artifacts (config, prompts)
- [ ] Specify pip requirements
- [ ] Implement model logging script
- [ ] Test model loading locally
- [ ] Register model to Unity Catalog

### Phase 2.3: Deployment ✓
- [ ] Create endpoint deployment script
- [ ] Deploy to dev endpoint
- [ ] Test dev endpoint
- [ ] Verify tracing in production
- [ ] Document deployment process
- [ ] Create rollback procedure
- [ ] Deploy to prod endpoint (after validation)

### Phase 2.4: Testing & Documentation ✓
- [ ] Unit tests with tracing mocked
- [ ] Integration tests with real tracing
- [ ] Endpoint testing script
- [ ] Performance benchmarking
- [ ] Documentation updates
- [ ] Create runbook for operations

## Key Differences from Original Plan

### Enhancements

1. **MLflow 3.0 Integration**: Full tracing support vs. basic logging
2. **Model Serving**: Deploy as serving endpoint vs. FastAPI only
3. **Unity Catalog**: Model registry in UC vs. workspace registry
4. **PyFunc Wrapper**: Custom model wrapper for serving
5. **Dual Deployment**: Dev and prod endpoints with different configs

### Maintained

1. **Agent Architecture**: Still tool-using agent with LLM
2. **Genie Integration**: Still primary data source
3. **Configuration**: Still YAML-based config system
4. **Singleton Client**: Still shared Databricks client
5. **Testing Strategy**: Still comprehensive unit/integration tests

## References

### Official Documentation

1. [MLflow 3.0 GenAI Features](https://learn.microsoft.com/en-us/azure/databricks/mlflow3/genai/)
2. [Custom Models for Serving](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/model-serving/custom-models)
3. [AI Agent Demo Notebooks](https://notebooks.databricks.com/demos/ai-agent/index.html)
4. [MLflow Tracing](https://mlflow.org/docs/latest/llms/tracing/index.html)
5. [Unity Catalog Model Registry](https://docs.databricks.com/machine-learning/manage-model-lifecycle/index.html)

### Internal Documentation

- [PROJECT_PLAN.md](../PROJECT_PLAN.md) - Original project plan
- [databricks-ai-specialist.md](../.cursor/agents/databricks-ai-specialist.md) - AI development patterns
- [databricks-ml-engineering-specialist.md](../.cursor/agents/databricks-ml-engineering-specialist.md) - MLOps patterns

## Success Criteria

### Phase 2 Complete When:

- ✅ Agent executes with full MLflow tracing to Databricks
- ✅ All agent steps (LLM calls, tool calls) are traced
- ✅ Model packaged as MLflow PyFunc
- ✅ Model registered in Unity Catalog
- ✅ Deployed to dev serving endpoint
- ✅ Endpoint accepts requests and returns slides
- ✅ Traces viewable in Databricks for served requests
- ✅ Tests pass with tracing enabled
- ✅ Documentation complete
- ✅ Deployment scripts functional

---

**Document Version:** 1.0  
**Author:** AI Slide Generator Team  
**Date:** November 5, 2025  
**Status:** Architecture Design


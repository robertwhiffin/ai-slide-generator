"""
MLflow PyFunc wrapper for deploying the slide generator to Databricks Model Serving.

This module packages the slide generator agent as an MLflow model that can be
deployed to Databricks serving endpoints.
"""

import os
from typing import Any

import mlflow
import pandas as pd
import yaml
from mlflow.models import infer_signature
from mlflow.pyfunc import PythonModel


class SlideGeneratorMLflowModel(PythonModel):
    """
    MLflow PyFunc wrapper for deploying slide generator to serving endpoints.

    This wrapper packages the agent with all dependencies and configuration
    for deployment to Databricks Model Serving.
    """

    def __init__(self):
        """Initialize the model wrapper."""
        self.agent = None
        self.config = None

    def load_context(self, context):
        """
        Load model and dependencies when serving endpoint starts.

        Called once on endpoint initialization.

        Args:
            context: MLflow context containing artifacts
        """
        # Load configuration from artifacts
        config_path = context.artifacts.get("config")
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        # Set environment flag for serving mode
        os.environ["MLFLOW_SERVING_MODE"] = "true"

        # Import agent (done here to avoid loading during packaging)
        from src.services.agent import SlideGeneratorAgent

        # Initialize agent
        # Note: Tracing will be handled by serving infrastructure
        self.agent = SlideGeneratorAgent()

    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        """
        Main prediction method called by serving endpoint.

        Input DataFrame columns:
            - question: str - User's question about data
            - max_slides: int (optional) - Maximum slides to generate
            - genie_space_id: str (optional) - Genie space ID to query

        Output DataFrame columns:
            - html: str - Generated HTML slide deck
            - slide_count: int - Number of slides generated
            - trace_url: str - URL to view trace in Databricks
            - error: str - Error message if generation failed (None if success)

        Args:
            context: MLflow context
            model_input: Input DataFrame with request data

        Returns:
            Output DataFrame with results
        """
        results = []

        for idx, row in model_input.iterrows():
            try:
                # Extract inputs
                question = row["question"]
                max_slides = row.get("max_slides", None)
                genie_space_id = row.get("genie_space_id", None)

                # Generate slides
                result = self.agent.generate_slides(
                    question=question, max_slides=max_slides, genie_space_id=genie_space_id
                )

                # Format output
                results.append(
                    {
                        "html": result["html"],
                        "slide_count": result["metadata"].get("slide_count", 0),
                        "trace_url": result["metadata"].get("trace_url", ""),
                        "execution_time_seconds": result["metadata"].get(
                            "execution_time_seconds", 0.0
                        ),
                        "error": None,
                    }
                )

            except Exception as e:
                results.append(
                    {
                        "html": None,
                        "slide_count": 0,
                        "trace_url": "",
                        "execution_time_seconds": 0.0,
                        "error": str(e),
                    }
                )

        return pd.DataFrame(results)


def log_model_to_mlflow(
    model_name: str,
    experiment_name: str,
    run_name: str = "model_packaging",
) -> str:
    """
    Package and log the slide generator as an MLflow model.

    This function packages the agent with all dependencies and configurations,
    then logs it to MLflow for deployment to serving endpoints.

    Args:
        model_name: Name for model registration in Unity Catalog
        experiment_name: MLflow experiment name
        run_name: Name for this MLflow run

    Returns:
        run_id: MLflow run ID where model was logged

    Example:
        >>> run_id = log_model_to_mlflow(
        ...     model_name="main.ml_models.slide_generator_dev",
        ...     experiment_name="/Users/me/ai-slide-generator"
        ... )
        >>> print(f"Model logged with run_id: {run_id}")
    """
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name=run_name) as run:

        # Create model instance
        model = SlideGeneratorMLflowModel()

        # Define input/output signature
        input_example = pd.DataFrame(
            [
                {
                    "question": "What were our Q4 2023 sales?",
                    "max_slides": 10,
                    "genie_space_id": None,
                }
            ]
        )

        output_example = pd.DataFrame(
            [
                {
                    "html": "<html>...</html>",
                    "slide_count": 10,
                    "trace_url": "https://...",
                    "execution_time_seconds": 25.5,
                    "error": None,
                }
            ]
        )

        signature = infer_signature(input_example, output_example)

        # Specify artifacts to include
        artifacts = {
            "config": "config/config.yaml",
            "prompts": "config/prompts.yaml",
            "mlflow_config": "config/mlflow.yaml",
        }

        # Define pip requirements
        pip_requirements = [
            "databricks-sdk>=0.20.0",
            "mlflow>=2.10.0",
            "pydantic>=2.4.0",
            "pydantic-settings>=2.0.0",
            "pyyaml>=6.0.0",
            "jinja2>=3.1.0",
            "pandas>=2.0.0",
            "opentelemetry-api>=1.20.0",
            "opentelemetry-sdk>=1.20.0",
        ]

        # Log model
        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=model,
            artifacts=artifacts,
            pip_requirements=pip_requirements,
            signature=signature,
            input_example=input_example,
            registered_model_name=model_name,
        )

        # Log metadata
        mlflow.log_params(
            {
                "model_type": "agent_based_slide_generator",
                "agent_framework": "custom_tool_calling",
                "llm_integration": "databricks_foundation_models",
                "tracing_enabled": True,
                "tools": "query_genie_space",
            }
        )

        # Log model info
        mlflow.set_tags(
            {
                "model_name": model_name,
                "deployment_target": "databricks_model_serving",
                "project": "ai-slide-generator",
                "phase": "2",
            }
        )

        print(f"✅ Model logged to MLflow with run_id: {run.info.run_id}")
        print(f"📦 Registered as: {model_name}")
        print(f"🔗 View in MLflow: {mlflow.get_tracking_uri()}")

        return run.info.run_id


def test_model_locally(model_uri: str, test_questions: list[str]) -> None:
    """
    Test the packaged model locally before deployment.

    Args:
        model_uri: MLflow model URI (e.g., "runs:/<run_id>/model")
        test_questions: List of test questions to try

    Example:
        >>> test_model_locally(
        ...     "runs:/abc123/model",
        ...     ["What were Q4 sales?", "Show customer trends"]
        ... )
    """
    print(f"🧪 Testing model: {model_uri}")

    # Load model
    model = mlflow.pyfunc.load_model(model_uri)

    # Test each question
    for i, question in enumerate(test_questions, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}: {question}")
        print('="*60')

        input_df = pd.DataFrame([{"question": question, "max_slides": 5}])

        try:
            result = model.predict(input_df)
            print(f"✅ Success!")
            print(f"  Slides: {result['slide_count'].iloc[0]}")
            print(f"  HTML Length: {len(result['html'].iloc[0])} chars")
            print(f"  Trace: {result['trace_url'].iloc[0]}")

            if result["error"].iloc[0]:
                print(f"  ⚠️  Error: {result['error'].iloc[0]}")

        except Exception as e:
            print(f"❌ Failed: {e}")


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "package":
            # Package model
            run_id = log_model_to_mlflow(
                model_name="main.ml_models.slide_generator_dev",
                experiment_name="/Users/default/ai-slide-generator",
                run_name="local_packaging",
            )
            print(f"Run ID: {run_id}")

        elif command == "test" and len(sys.argv) > 2:
            # Test model
            model_uri = sys.argv[2]
            test_questions = [
                "What were our Q4 2023 sales?",
                "Show me customer churn trends",
            ]
            test_model_locally(model_uri, test_questions)

        else:
            print("Usage:")
            print("  python mlflow_wrapper.py package")
            print("  python mlflow_wrapper.py test <model_uri>")
    else:
        print("Usage:")
        print("  python mlflow_wrapper.py package")
        print("  python mlflow_wrapper.py test <model_uri>")


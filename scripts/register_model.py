#!/usr/bin/env python3
"""
Register slide generator model to Unity Catalog and deploy to serving endpoint.

Usage:
    python scripts/register_model.py --environment dev
    python scripts/register_model.py --environment prod --approve
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
from mlflow.tracking import MlflowClient

from src.models.mlflow_wrapper import log_model_to_mlflow


def register_and_deploy(environment: str = "dev", auto_approve: bool = False) -> tuple[str, str]:
    """
    Register model and optionally deploy to serving endpoint.

    Args:
        environment: Environment to deploy to ('dev' or 'prod')
        auto_approve: Auto-approve production deployment without prompt

    Returns:
        Tuple of (run_id, model_version)
    """
    client = MlflowClient()
    w = WorkspaceClient()

    # Get current user
    username = w.current_user.me().user_name

    # Configuration based on environment
    config = {
        "dev": {
            "model_name": "main.ml_models.slide_generator_dev",
            "endpoint_name": "slide-generator-dev",
            "experiment_name": f"/Users/{username}/ai-slide-generator",
            "workload_size": "Small",
            "scale_to_zero": True,
            "min_scale": 0,
            "max_scale": 3,
        },
        "prod": {
            "model_name": "main.ml_models.slide_generator",
            "endpoint_name": "slide-generator",
            "experiment_name": f"/Users/{username}/ai-slide-generator",
            "workload_size": "Medium",
            "scale_to_zero": False,
            "min_scale": 1,
            "max_scale": 5,
        },
    }

    env_config = config[environment]

    print(f"\n{'='*60}")
    print(f"🚀 Registering Model for {environment.upper()} Environment")
    print(f"{'='*60}\n")
    print(f"Model Name: {env_config['model_name']}")
    print(f"Endpoint: {env_config['endpoint_name']}")
    print(f"Experiment: {env_config['experiment_name']}")
    print()

    # Log and register model
    print("📦 Packaging and logging model...")
    run_id = log_model_to_mlflow(
        model_name=env_config["model_name"],
        experiment_name=env_config["experiment_name"],
        run_name=f"register_{environment}_{mlflow.utils.time.get_current_time_millis()}",
    )

    # Get latest model version
    print("\n🔍 Fetching model version...")
    latest_version = client.search_model_versions(
        filter_string=f"name='{env_config['model_name']}'",
        order_by=["version_number DESC"],
        max_results=1,
    )[0]

    print(f"✅ Model version: {latest_version.version}")

    # Transition to appropriate stage
    deploy = False
    if environment == "dev":
        print("\n📌 Transitioning to Staging...")
        client.transition_model_version_stage(
            name=env_config["model_name"],
            version=latest_version.version,
            stage="Staging",
        )
        deploy = True
    else:
        # Production requires approval
        if auto_approve:
            print("\n📌 Transitioning to Production...")
            client.transition_model_version_stage(
                name=env_config["model_name"],
                version=latest_version.version,
                stage="Production",
            )
            deploy = True
        else:
            print(f"\n⚠️  Model registered as version {latest_version.version}")
            print("❌ Production deployment requires approval.")
            print("   Run with --approve to deploy to production")
            deploy = False

    # Deploy to serving endpoint
    if deploy:
        print(f"\n🚢 Deploying to serving endpoint: {env_config['endpoint_name']}")
        deploy_to_endpoint(
            workspace_client=w,
            model_name=env_config["model_name"],
            model_version=latest_version.version,
            endpoint_name=env_config["endpoint_name"],
            workload_size=env_config["workload_size"],
            scale_to_zero=env_config["scale_to_zero"],
            min_scale=env_config["min_scale"],
            max_scale=env_config["max_scale"],
        )

        print(f"\n{'='*60}")
        print("✅ DEPLOYMENT SUCCESSFUL")
        print(f"{'='*60}")
        print(f"🔗 Endpoint URL:")
        print(f"   {w.config.host}/serving-endpoints/{env_config['endpoint_name']}/invocations")
        print(f"\n📊 View in Databricks:")
        print(f"   {w.config.host}/ml/endpoints/{env_config['endpoint_name']}")
        print()

    return run_id, latest_version.version


def deploy_to_endpoint(
    workspace_client: WorkspaceClient,
    model_name: str,
    model_version: str,
    endpoint_name: str,
    workload_size: str = "Small",
    scale_to_zero: bool = True,
    min_scale: int = 0,
    max_scale: int = 3,
) -> None:
    """
    Deploy model to Databricks Model Serving endpoint.

    Args:
        workspace_client: Databricks WorkspaceClient
        model_name: Unity Catalog model name
        model_version: Model version to deploy
        endpoint_name: Serving endpoint name
        workload_size: Workload size (Small, Medium, Large)
        scale_to_zero: Whether to enable scale-to-zero
        min_scale: Minimum number of instances
        max_scale: Maximum number of instances
    """
    print(f"   Model: {model_name} v{model_version}")
    print(f"   Workload: {workload_size}")
    print(f"   Scale: {min_scale}-{max_scale} instances")
    print(f"   Scale to zero: {scale_to_zero}")

    # Check if endpoint exists
    try:
        existing_endpoint = workspace_client.serving_endpoints.get(endpoint_name)
        print(f"\n   📝 Endpoint exists, updating...")

        # Update endpoint with new model version
        workspace_client.serving_endpoints.update_config(
            name=endpoint_name,
            served_entities=[
                ServedEntityInput(
                    entity_name=model_name,
                    entity_version=model_version,
                    workload_size=workload_size,
                    scale_to_zero_enabled=scale_to_zero,
                )
            ],
        )

    except Exception:
        print(f"\n   ✨ Creating new endpoint...")

        # Create new endpoint
        workspace_client.serving_endpoints.create(
            name=endpoint_name,
            config=EndpointCoreConfigInput(
                served_entities=[
                    ServedEntityInput(
                        entity_name=model_name,
                        entity_version=model_version,
                        workload_size=workload_size,
                        scale_to_zero_enabled=scale_to_zero,
                    )
                ]
            ),
        )

    # Wait for endpoint to be ready
    print("\n   ⏳ Waiting for endpoint to be ready...")
    workspace_client.serving_endpoints.wait_get_serving_endpoint_not_updating(endpoint_name)

    print("   ✅ Endpoint is ready!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Register and deploy slide generator model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy to dev
  python scripts/register_model.py --environment dev
  
  # Deploy to prod with auto-approval
  python scripts/register_model.py --environment prod --approve
        """,
    )

    parser.add_argument(
        "--environment",
        choices=["dev", "prod"],
        default="dev",
        help="Environment to deploy to (default: dev)",
    )

    parser.add_argument(
        "--approve",
        action="store_true",
        help="Auto-approve production deployment (prod only)",
    )

    args = parser.parse_args()

    try:
        run_id, version = register_and_deploy(args.environment, args.approve)
        print(f"📋 Run ID: {run_id}")
        print(f"🏷️  Model Version: {version}")
        sys.exit(0)

    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


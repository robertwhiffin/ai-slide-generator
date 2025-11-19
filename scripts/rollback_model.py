#!/usr/bin/env python3
"""
Rollback serving endpoint to a previous model version.

Usage:
    python scripts/rollback_model.py --endpoint slide-generator-dev --version 2
    python scripts/rollback_model.py --endpoint slide-generator --version 5 --confirm
"""

import argparse
import sys

from databricks.sdk.service.serving import ServedEntityInput

from src.config.client import get_databricks_client


def rollback_endpoint(
    endpoint_name: str, target_version: str, confirm: bool = False
) -> None:
    """
    Rollback endpoint to specific model version.

    Args:
        endpoint_name: Name of the serving endpoint
        target_version: Model version to rollback to
        confirm: If True, skip confirmation prompt
    """
    w = get_databricks_client()

    print(f"\n{'='*60}")
    print(f"🔄 Rollback Endpoint")
    print(f"{'='*60}")
    print(f"Endpoint: {endpoint_name}")
    print(f"Target Version: {target_version}\n")

    try:
        # Get current endpoint config
        endpoint = w.serving_endpoints.get(endpoint_name)

        if not endpoint.config or not endpoint.config.served_entities:
            print("❌ ERROR: Endpoint has no served entities")
            sys.exit(1)

        current_entity = endpoint.config.served_entities[0]
        current_version = current_entity.entity_version
        model_name = current_entity.entity_name

        print(f"Current Configuration:")
        print(f"  Model: {model_name}")
        print(f"  Version: {current_version}")
        print(f"  Workload: {current_entity.workload_size}")
        print()

        if current_version == target_version:
            print(f"⚠️  Endpoint is already at version {target_version}")
            sys.exit(0)

        # Confirm rollback
        if not confirm:
            response = input(
                f"❓ Rollback from v{current_version} to v{target_version}? (yes/no): "
            )
            if response.lower() not in ["yes", "y"]:
                print("❌ Rollback cancelled")
                sys.exit(0)

        # Update to target version
        print(f"\n🔄 Rolling back to version {target_version}...")

        w.serving_endpoints.update_config(
            name=endpoint_name,
            served_entities=[
                ServedEntityInput(
                    entity_name=model_name,
                    entity_version=target_version,
                    workload_size=current_entity.workload_size,
                    scale_to_zero_enabled=current_entity.scale_to_zero_enabled,
                )
            ],
        )

        # Wait for update to complete
        print("⏳ Waiting for endpoint to update...")
        w.serving_endpoints.wait_get_serving_endpoint_not_updating(endpoint_name)

        print(f"\n{'='*60}")
        print("✅ ROLLBACK SUCCESSFUL")
        print(f"{'='*60}")
        print(f"Endpoint: {endpoint_name}")
        print(f"Version: {current_version} → {target_version}")
        print()
        print(f"🔗 View endpoint:")
        print(f"   {w.config.host}/ml/endpoints/{endpoint_name}")
        print()

    except Exception as e:
        print(f"\n❌ ERROR: Failed to rollback endpoint")
        print(f"   {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def list_model_versions(model_name: str) -> None:
    """
    List available model versions.

    Args:
        model_name: Unity Catalog model name
    """
    from mlflow.tracking import MlflowClient

    client = MlflowClient()

    print(f"\n📋 Available versions for {model_name}:")
    print(f"{'='*60}\n")

    versions = client.search_model_versions(
        filter_string=f"name='{model_name}'", order_by=["version_number DESC"]
    )

    if not versions:
        print("   No versions found")
        return

    for version in versions:
        print(f"Version {version.version}:")
        print(f"  Status: {version.status}")
        print(f"  Stage: {version.current_stage}")
        print(f"  Created: {version.creation_timestamp}")
        if version.description:
            print(f"  Description: {version.description}")
        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rollback model serving endpoint to previous version",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available versions
  python scripts/rollback_model.py --list-versions main.ml_models.slide_generator_dev
  
  # Rollback with confirmation prompt
  python scripts/rollback_model.py --endpoint slide-generator-dev --version 2
  
  # Rollback without confirmation
  python scripts/rollback_model.py --endpoint slide-generator --version 5 --confirm
        """,
    )

    parser.add_argument(
        "--endpoint",
        help="Name of the serving endpoint to rollback",
    )

    parser.add_argument(
        "--version",
        help="Model version to rollback to",
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt",
    )

    parser.add_argument(
        "--list-versions",
        help="List available versions for a model",
        metavar="MODEL_NAME",
    )

    args = parser.parse_args()

    try:
        if args.list_versions:
            # List versions
            list_model_versions(args.list_versions)

        elif args.endpoint and args.version:
            # Rollback endpoint
            rollback_endpoint(args.endpoint, args.version, args.confirm)

        else:
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


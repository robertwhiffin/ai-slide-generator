# CI Deploy Integration Test - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a CI workflow that tests the full Databricks App lifecycle (create, update, delete) against a real workspace, gated behind all existing tests passing.

**Architecture:** A new `scripts/deploy_ci.py` script (adapted from `scripts/deploy_local.py`) accepts all config via CLI args and authenticates via `DATABRICKS_HOST`/`DATABRICKS_TOKEN` env vars. Two new jobs are added to `.github/workflows/test.yml`: `deploy-integration` (the test) and `deploy-cleanup` (safety net). Each run uses unique resource names derived from `github.run_id` to prevent collisions across concurrent PR builds.

**Tech Stack:** Python (databricks-sdk), GitHub Actions, uv (package management/builds)

---

## Task 1: Create `scripts/deploy_ci.py`

**Files:**
- Create: `scripts/deploy_ci.py`

This script is adapted from `scripts/deploy_local.py` with these key differences:
- No `deployment.yaml` dependency -- all values come from CLI args
- No `--profile` flag -- uses `WorkspaceClient()` which picks up `DATABRICKS_HOST` + `DATABRICKS_TOKEN` from env
- No interactive prompts or `.venv` checks
- Adds `--verify-deleted` and `--verify-lakebase-deleted` actions
- Delete action also deletes the Lakebase instance (with `purge=True`)

**Step 1: Create the script**

```python
"""CI deployment script for Databricks Apps integration testing.

This script enables create/update/delete lifecycle testing of the AI Slide
Generator on Databricks Apps in CI. Unlike deploy_local.py, this script:
- Takes all config via CLI arguments (no deployment.yaml)
- Authenticates via DATABRICKS_HOST/DATABRICKS_TOKEN env vars (no --profile)
- Includes verification actions to confirm resources are truly deleted
- Deletes Lakebase instances as part of cleanup

Usage:
    python -m scripts.deploy_ci --create --app-name my-app --workspace-path /path --lakebase-name my-lb --schema my-schema
    python -m scripts.deploy_ci --update --app-name my-app --workspace-path /path --lakebase-name my-lb --schema my-schema
    python -m scripts.deploy_ci --delete --app-name my-app --workspace-path /path --lakebase-name my-lb --schema my-schema
    python -m scripts.deploy_ci --verify-deleted --app-name my-app
    python -m scripts.deploy_ci --verify-lakebase-deleted --lakebase-name my-lb
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "databricks-tellr"))

from databricks_tellr.deploy import (
    DeploymentError,
    _get_or_create_lakebase,
    _write_requirements,
    _write_app_yaml,
    _upload_files,
    _create_app,
    _deploy_app,
    _setup_database_schema,
    _reset_schema,
    _get_app_client_id,
)


def _get_client() -> WorkspaceClient:
    """Get WorkspaceClient using env vars (DATABRICKS_HOST, DATABRICKS_TOKEN)."""
    return WorkspaceClient()


def find_app_wheel() -> Path:
    """Find the built databricks-tellr-app wheel.

    Returns:
        Path to the wheel file

    Raises:
        DeploymentError: If wheel not found
    """
    app_dist = PROJECT_ROOT / "packages" / "databricks-tellr-app" / "dist"

    if not app_dist.exists():
        raise DeploymentError(
            f"No dist directory found at {app_dist}. "
            "Build wheels first."
        )

    wheels = list(app_dist.glob("*.whl"))
    if not wheels:
        raise DeploymentError(
            f"No wheel files found in {app_dist}. "
            "Build wheels first."
        )

    return max(wheels, key=lambda p: p.stat().st_mtime)


def upload_wheel(
    ws: WorkspaceClient,
    wheel_path: Path,
    workspace_path: str,
) -> str:
    """Upload wheel to Databricks workspace.

    Args:
        ws: WorkspaceClient
        wheel_path: Local path to the wheel file
        workspace_path: Base workspace path for the app

    Returns:
        Relative path to use in requirements.txt
    """
    from databricks.sdk.service.workspace import ImportFormat

    wheels_dir = f"{workspace_path}/wheels"

    try:
        ws.workspace.mkdirs(wheels_dir)
    except Exception:
        pass

    try:
        objects = ws.workspace.list(wheels_dir)
        for obj in objects:
            if obj.path and obj.path.endswith(".whl"):
                ws.workspace.delete(obj.path)
                print(f"   Removed old wheel: {Path(obj.path).name}")
    except Exception:
        pass

    wheel_dest = f"{wheels_dir}/{wheel_path.name}"
    with open(wheel_path, "rb") as f:
        ws.workspace.upload(
            wheel_dest,
            f,
            format=ImportFormat.AUTO,
            overwrite=True,
        )

    return f"./wheels/{wheel_path.name}"


def create_ci(
    app_name: str,
    workspace_path: str,
    lakebase_name: str,
    schema_name: str,
    lakebase_capacity: str = "CU_1",
    compute_size: str = "MEDIUM",
) -> dict[str, Any]:
    """Create a new Databricks App for CI testing.

    Args:
        app_name: Unique app name (includes run ID suffix)
        workspace_path: Databricks workspace path for app files
        lakebase_name: Lakebase instance name (includes run ID suffix)
        schema_name: Schema name (includes run ID suffix)
        lakebase_capacity: Lakebase compute capacity
        compute_size: App compute size

    Returns:
        Dictionary with deployment info
    """
    ws = _get_client()

    print(f"Creating CI app: {app_name}")
    print(f"   Workspace path: {workspace_path}")
    print(f"   Lakebase: {lakebase_name}")
    print(f"   Schema: {schema_name}")
    print()

    try:
        # Find and upload wheel
        print("Finding built wheel...")
        wheel_path = find_app_wheel()
        print(f"   Found: {wheel_path.name}")

        print("Uploading wheel to workspace...")
        local_wheel_ref = upload_wheel(ws, wheel_path, workspace_path)
        print(f"   Uploaded: {local_wheel_ref}")
        print()

        # Create Lakebase instance
        print("Setting up Lakebase database...")
        lakebase_result = _get_or_create_lakebase(
            ws, lakebase_name, lakebase_capacity
        )
        print(f"   Lakebase: {lakebase_result['name']} ({lakebase_result['status']})")
        print()

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_ci_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(staging_dir, lakebase_name, schema_name)
            print("   Generated app.yaml")

            print(f"Uploading to: {workspace_path}")
            _upload_files(ws, staging_dir, workspace_path)
            print("   Files uploaded")
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
        print()

        # Create app
        print(f"Creating Databricks App: {app_name}")
        app = _create_app(
            ws,
            app_name=app_name,
            description=f"CI Integration Test - {app_name}",
            workspace_path=workspace_path,
            compute_size=compute_size,
            lakebase_name=lakebase_name,
        )
        print("   App registered")
        print()

        # Set up database schema
        print("Setting up database schema...")
        _setup_database_schema(ws, app, lakebase_name, schema_name)
        print(f"   Schema '{schema_name}' configured")
        print()

        # Deploy the app
        print("Deploying app...")
        app = _deploy_app(ws, app_name, workspace_path)
        print("   App deployed")
        if app.url:
            print(f"   URL: {app.url}")
        print()

        print("Create complete!")
        return {
            "url": app.url,
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "schema_name": schema_name,
            "wheel": wheel_path.name,
            "status": "created",
        }

    except Exception as e:
        raise DeploymentError(f"Create failed: {e}") from e


def update_ci(
    app_name: str,
    workspace_path: str,
    lakebase_name: str,
    schema_name: str,
) -> dict[str, Any]:
    """Update an existing CI Databricks App.

    Args:
        app_name: App name to update
        workspace_path: Databricks workspace path for app files
        lakebase_name: Lakebase instance name
        schema_name: Schema name

    Returns:
        Dictionary with deployment info
    """
    ws = _get_client()

    print(f"Updating CI app: {app_name}")
    print()

    try:
        # Find and upload wheel
        print("Finding built wheel...")
        wheel_path = find_app_wheel()
        print(f"   Found: {wheel_path.name}")

        print("Uploading wheel to workspace...")
        local_wheel_ref = upload_wheel(ws, wheel_path, workspace_path)
        print(f"   Uploaded: {local_wheel_ref}")
        print()

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_ci_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(staging_dir, lakebase_name, schema_name)
            print("   Generated app.yaml")

            _upload_files(ws, staging_dir, workspace_path)
            print("   Files updated")
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        # Deploy new version
        print("   Deploying...")
        deployment = AppDeployment(source_code_path=workspace_path)
        result = ws.apps.deploy_and_wait(app_name=app_name, app_deployment=deployment)
        print(f"   Deployment completed: {result.deployment_id}")

        app = ws.apps.get(name=app_name)
        if app.url:
            print(f"   URL: {app.url}")

        return {
            "url": app.url,
            "app_name": app_name,
            "deployment_id": result.deployment_id,
            "wheel": wheel_path.name,
            "status": "updated",
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e


def delete_ci(
    app_name: str,
    lakebase_name: str,
    schema_name: str,
) -> dict[str, Any]:
    """Delete a CI Databricks App, its schema, and its Lakebase instance.

    Args:
        app_name: App name to delete
        lakebase_name: Lakebase instance name to delete
        schema_name: Schema name to drop

    Returns:
        Dictionary with deletion status
    """
    ws = _get_client()

    print(f"Deleting CI app: {app_name}")

    try:
        # Drop the schema
        print("Dropping database schema...")
        try:
            app = ws.apps.get(name=app_name)
            _reset_schema(ws, app, lakebase_name, schema_name, drop_only=True)
            print(f"   Schema '{schema_name}' dropped")
        except Exception as e:
            print(f"   Schema drop skipped: {e}")

        # Delete the app
        print("Deleting app...")
        try:
            ws.apps.delete(name=app_name)
            print("   App deleted")
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "does not exist" in error_str:
                print("   App already deleted")
            else:
                raise

        # Delete the Lakebase instance
        print(f"Deleting Lakebase instance: {lakebase_name}...")
        try:
            ws.database.delete_database_instance(name=lakebase_name, purge=True)
            print("   Lakebase instance deleted")
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "does not exist" in error_str:
                print("   Lakebase instance already deleted")
            else:
                raise

        return {
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "status": "deleted",
        }

    except Exception as e:
        raise DeploymentError(f"Delete failed: {e}") from e


def verify_app_deleted(app_name: str) -> None:
    """Verify that a Databricks App no longer exists.

    Args:
        app_name: App name to verify is deleted

    Raises:
        DeploymentError: If the app still exists
    """
    ws = _get_client()

    print(f"Verifying app deleted: {app_name}")
    try:
        app = ws.apps.get(name=app_name)
        raise DeploymentError(
            f"App '{app_name}' still exists (status: {app.status})"
        )
    except DeploymentError:
        raise
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            print(f"   Confirmed: app '{app_name}' does not exist")
        else:
            raise DeploymentError(f"Verification failed with unexpected error: {e}") from e


def verify_lakebase_deleted(lakebase_name: str) -> None:
    """Verify that a Lakebase instance no longer exists.

    Args:
        lakebase_name: Lakebase instance name to verify is deleted

    Raises:
        DeploymentError: If the instance still exists
    """
    ws = _get_client()

    print(f"Verifying Lakebase deleted: {lakebase_name}")
    try:
        instance = ws.database.get_database_instance(name=lakebase_name)
        raise DeploymentError(
            f"Lakebase '{lakebase_name}' still exists (state: {instance.state})"
        )
    except DeploymentError:
        raise
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            print(f"   Confirmed: Lakebase '{lakebase_name}' does not exist")
        else:
            raise DeploymentError(f"Verification failed with unexpected error: {e}") from e


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CI deployment script for Databricks Apps integration testing"
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--create", action="store_const", const="create", dest="action",
        help="Create new app with Lakebase",
    )
    action_group.add_argument(
        "--update", action="store_const", const="update", dest="action",
        help="Update existing app",
    )
    action_group.add_argument(
        "--delete", action="store_const", const="delete", dest="action",
        help="Delete app, schema, and Lakebase instance",
    )
    action_group.add_argument(
        "--verify-deleted", action="store_const", const="verify_deleted", dest="action",
        help="Verify app is deleted",
    )
    action_group.add_argument(
        "--verify-lakebase-deleted", action="store_const", const="verify_lakebase_deleted", dest="action",
        help="Verify Lakebase instance is deleted",
    )

    parser.add_argument("--app-name", type=str, help="Databricks App name")
    parser.add_argument("--workspace-path", type=str, help="Workspace path for app files")
    parser.add_argument("--lakebase-name", type=str, help="Lakebase instance name")
    parser.add_argument("--schema", type=str, help="Database schema name")
    parser.add_argument("--lakebase-capacity", type=str, default="CU_1", help="Lakebase capacity (default: CU_1)")
    parser.add_argument("--compute-size", type=str, default="MEDIUM", help="App compute size (default: MEDIUM)")

    args = parser.parse_args()

    try:
        if args.action == "create":
            if not all([args.app_name, args.workspace_path, args.lakebase_name, args.schema]):
                parser.error("--create requires --app-name, --workspace-path, --lakebase-name, and --schema")
            result = create_ci(
                app_name=args.app_name,
                workspace_path=args.workspace_path,
                lakebase_name=args.lakebase_name,
                schema_name=args.schema,
                lakebase_capacity=args.lakebase_capacity,
                compute_size=args.compute_size,
            )
        elif args.action == "update":
            if not all([args.app_name, args.workspace_path, args.lakebase_name, args.schema]):
                parser.error("--update requires --app-name, --workspace-path, --lakebase-name, and --schema")
            result = update_ci(
                app_name=args.app_name,
                workspace_path=args.workspace_path,
                lakebase_name=args.lakebase_name,
                schema_name=args.schema,
            )
        elif args.action == "delete":
            if not all([args.app_name, args.lakebase_name, args.schema]):
                parser.error("--delete requires --app-name, --lakebase-name, and --schema")
            result = delete_ci(
                app_name=args.app_name,
                lakebase_name=args.lakebase_name,
                schema_name=args.schema,
            )
        elif args.action == "verify_deleted":
            if not args.app_name:
                parser.error("--verify-deleted requires --app-name")
            verify_app_deleted(args.app_name)
            result = {"app_name": args.app_name, "status": "verified_deleted"}
        elif args.action == "verify_lakebase_deleted":
            if not args.lakebase_name:
                parser.error("--verify-lakebase-deleted requires --lakebase-name")
            verify_lakebase_deleted(args.lakebase_name)
            result = {"lakebase_name": args.lakebase_name, "status": "verified_deleted"}
        else:
            raise ValueError(f"Unknown action: {args.action}")

        print()
        print(f"Result: {result}")

    except DeploymentError as e:
        print(f"CI deployment failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
```

**Step 2: Verify the script parses correctly**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -c "import ast; ast.parse(open('scripts/deploy_ci.py').read()); print('Syntax OK')"`
Expected: `Syntax OK`

**Step 3: Verify help text**

Run: `cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator && python -m scripts.deploy_ci --help`
Expected: Help output showing `--create`, `--update`, `--delete`, `--verify-deleted`, `--verify-lakebase-deleted` actions and all arguments.

---

## Task 2: Add `deploy-integration` job to `.github/workflows/test.yml`

**Files:**
- Modify: `.github/workflows/test.yml` (append after `test-summary` job, ~line 799)

This job depends on all existing test jobs directly (not `test-summary`, to avoid circular dependencies). It only runs if none of the prerequisite jobs failed.

**Step 1: Add the `deploy-integration` job**

Add the following job after the `test-summary` job in `.github/workflows/test.yml`:

```yaml
  # Deploy integration test - full lifecycle against real Databricks workspace
  deploy-integration:
    name: "Deploy Integration Test"
    runs-on: ubuntu-latest
    needs:
      - unit-tests
      - frontend-build
      - wheel-build
      - integration-api-routes
      - integration-config-api
      - integration-export
      - integration-streaming
      - integration-slides
      - integration-genie
      - e2e-tests
    if: |
      always() &&
      !contains(needs.*.result, 'failure')
    environment: ci-build-workspace
    outputs:
      app_name: ${{ steps.names.outputs.app_name }}
      lakebase_name: ${{ steps.names.outputs.lakebase_name }}
      schema_name: ${{ steps.names.outputs.schema_name }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: |
          uv pip install --system -e ".[dev]"
          uv pip install --system build

      - name: Generate unique resource names
        id: names
        run: |
          RUN_ID="${{ github.run_id }}"
          echo "app_name=db-tellr-ci-${RUN_ID}" >> "$GITHUB_OUTPUT"
          echo "lakebase_name=db-tellr-ci-${RUN_ID}" >> "$GITHUB_OUTPUT"
          echo "schema_name=app_data_ci_${RUN_ID}" >> "$GITHUB_OUTPUT"
          echo "workspace_path=/Workspace/Users/robert.whiffin@databricks.com/.apps/ci/tellr-${RUN_ID}" >> "$GITHUB_OUTPUT"

      - name: Build wheels
        run: |
          # Build databricks-tellr wheel
          uv build packages/databricks-tellr --wheel --out-dir packages/databricks-tellr/dist

          # Copy src/ into app package for build (same as build_wheels.sh)
          cp -r src packages/databricks-tellr-app/src

          # Build databricks-tellr-app wheel
          uv build packages/databricks-tellr-app --wheel --out-dir packages/databricks-tellr-app/dist

          # Clean up copied src/
          rm -rf packages/databricks-tellr-app/src

          echo "Built wheels:"
          ls -lh packages/databricks-tellr/dist/*.whl
          ls -lh packages/databricks-tellr-app/dist/*.whl

      - name: "Create: Deploy new app"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --create \
            --app-name "${{ steps.names.outputs.app_name }}" \
            --workspace-path "${{ steps.names.outputs.workspace_path }}" \
            --lakebase-name "${{ steps.names.outputs.lakebase_name }}" \
            --schema "${{ steps.names.outputs.schema_name }}"

      - name: "Verify: App exists after create"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -c "
          from databricks.sdk import WorkspaceClient
          ws = WorkspaceClient()
          app = ws.apps.get(name='${{ steps.names.outputs.app_name }}')
          assert app is not None, 'App not found after create'
          assert app.url, 'App has no URL after create'
          print(f'Verified: app exists with URL {app.url}')
          "

      - name: "Update: Redeploy app"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --update \
            --app-name "${{ steps.names.outputs.app_name }}" \
            --workspace-path "${{ steps.names.outputs.workspace_path }}" \
            --lakebase-name "${{ steps.names.outputs.lakebase_name }}" \
            --schema "${{ steps.names.outputs.schema_name }}"

      - name: "Verify: App updated"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -c "
          from databricks.sdk import WorkspaceClient
          ws = WorkspaceClient()
          app = ws.apps.get(name='${{ steps.names.outputs.app_name }}')
          assert app is not None, 'App not found after update'
          print(f'Verified: app exists after update (URL: {app.url})')
          "

      - name: "Delete: Remove app and Lakebase"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --delete \
            --app-name "${{ steps.names.outputs.app_name }}" \
            --lakebase-name "${{ steps.names.outputs.lakebase_name }}" \
            --schema "${{ steps.names.outputs.schema_name }}"

      - name: "Verify: App deleted"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --verify-deleted \
            --app-name "${{ steps.names.outputs.app_name }}"

      - name: "Verify: Lakebase deleted"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --verify-lakebase-deleted \
            --lakebase-name "${{ steps.names.outputs.lakebase_name }}"
```

**Step 2: Verify the YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('YAML OK')"`
Expected: `YAML OK`

---

## Task 3: Add `deploy-cleanup` job to `.github/workflows/test.yml`

**Files:**
- Modify: `.github/workflows/test.yml` (append after `deploy-integration` job)

This safety-net job runs even if `deploy-integration` fails or is cancelled. It re-attempts deletion of all CI resources and verifies they're gone.

**Step 1: Add the `deploy-cleanup` job**

Add the following job after the `deploy-integration` job:

```yaml
  # Safety net: ensure CI resources are always cleaned up
  deploy-cleanup:
    name: "Deploy Cleanup"
    runs-on: ubuntu-latest
    needs: [deploy-integration]
    if: always() && needs.deploy-integration.result != 'skipped'
    environment: ci-build-workspace
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv pip install --system -e ".[dev]"

      - name: "Cleanup: Delete app (if still exists)"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --delete \
            --app-name "${{ needs.deploy-integration.outputs.app_name }}" \
            --lakebase-name "${{ needs.deploy-integration.outputs.lakebase_name }}" \
            --schema "${{ needs.deploy-integration.outputs.schema_name }}" \
          || echo "Cleanup delete completed (may have already been deleted)"

      - name: "Verify: App is gone"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --verify-deleted \
            --app-name "${{ needs.deploy-integration.outputs.app_name }}"

      - name: "Verify: Lakebase is gone"
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN }}
        run: |
          python -m scripts.deploy_ci --verify-lakebase-deleted \
            --lakebase-name "${{ needs.deploy-integration.outputs.lakebase_name }}"
```

**Step 2: Verify YAML validity**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('YAML OK')"`
Expected: `YAML OK`

---

## Task 4: Update `test-summary` job

**Files:**
- Modify: `.github/workflows/test.yml:750-798` (the `test-summary` job)

Add `deploy-integration` and `deploy-cleanup` to the `needs` list and status checks.

**Step 1: Update the `test-summary` job**

Update the `needs` list to include:
```yaml
    needs:
      - unit-tests
      - frontend-build
      - wheel-build
      - integration-api-routes
      - integration-config-api
      - integration-export
      - integration-streaming
      - integration-slides
      - integration-genie
      - e2e-tests
      - deploy-integration
      - deploy-cleanup
```

Add to the echo block:
```bash
          echo "Deploy Integration: ${{ needs.deploy-integration.result }}"
          echo "Deploy Cleanup: ${{ needs.deploy-cleanup.result }}"
```

Add to the failure check loop:
```bash
                        "${{ needs.deploy-integration.result }}" \
                        "${{ needs.deploy-cleanup.result }}"; do
```

**Step 2: Verify YAML validity**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('YAML OK')"`
Expected: `YAML OK`

---

## Task 5: Verify complete workflow

**Step 1: Validate the full workflow file**

Run:
```bash
python -c "
import yaml
with open('.github/workflows/test.yml') as f:
    workflow = yaml.safe_load(f)
jobs = workflow.get('jobs', {})
print(f'Total jobs: {len(jobs)}')
for name in jobs:
    needs = jobs[name].get('needs', [])
    print(f'  {name}: needs={needs}')
assert 'deploy-integration' in jobs, 'Missing deploy-integration job'
assert 'deploy-cleanup' in jobs, 'Missing deploy-cleanup job'
print('Workflow structure OK')
"
```
Expected: All jobs listed with correct dependencies, no missing jobs.

**Step 2: Verify `deploy_ci.py` imports work**

Run:
```bash
python -c "
import ast
ast.parse(open('scripts/deploy_ci.py').read())
print('deploy_ci.py syntax OK')
"
```
Expected: `deploy_ci.py syntax OK`

"""Local development deployment for Databricks Apps.

This script enables deploying the AI Slide Generator to Databricks Apps
using locally-built wheels instead of PyPI packages.

Usage:
    python -m scripts.deploy_local --create --env development --profile my-profile
    python -m scripts.deploy_local --update --env development --profile my-profile
    python -m scripts.deploy_local --update --env development --profile my-profile --reset-db
    python -m scripts.deploy_local --delete --env development --profile my-profile
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment
from databricks.sdk.service.workspace import ImportFormat

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "databricks-tellr"))

# Module-level config path — monkeypatched by tests that need a custom config.
CONFIG_PATH = PROJECT_ROOT / "config" / "deployment.yaml"

from databricks_tellr import secret_key
from databricks_tellr.identifiers import validate_schema_name
from databricks_tellr.deploy import (
    DeploymentError,
    _branch_exists,
    _delete_branch,
    _get_lakebase_connection,
    _get_workspace_client,
    _get_or_create_lakebase,
    _migrate_encryption_key_to_lakebase,
    _mlflow_flat_from_env_section,
    _mlflow_substitutions_for_app_yaml,
    _probe_autoscaling_available,
    _read_existing_encryption_key,
    _recreate_ephemeral_branch,
    _write_requirements,
    _write_app_yaml,
    _is_valid_version,
    _upload_files,
    _create_app,
    _deploy_app,
    _setup_database_schema,
    _reset_schema,
    _get_app_client_id,
    _ensure_sp_autoscaling_role,
    delete,
)


def _load_branch_source_config(source_env_name: str) -> dict:
    """Return {workspace_path, schema, database_name, app_name} from the source env.

    Reads CONFIG_PATH directly so callers only need the env name.

    Raises:
        DeploymentError: if the config file is missing or the env is absent.
    """
    if not CONFIG_PATH.exists():
        raise DeploymentError(f"Deployment config not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    environments = config.get("environments", {})
    if source_env_name not in environments:
        raise DeploymentError(
            f'branch_from "{source_env_name}" not found in deployment config'
        )
    env_config = environments[source_env_name]
    lb = env_config.get("lakebase", {})
    return {
        "workspace_path": env_config.get("workspace_path"),
        "schema": lb.get("schema"),
        "database_name": lb.get("database_name"),
        # Needed so the fork can read the source app's resources and inherit its
        # secret scope/key. Not derivable from workspace_path — the app name is
        # arbitrary config.
        "app_name": env_config.get("app_name"),
    }


def load_deployment_config(env: str) -> dict[str, Any]:
    """Load deployment configuration for the specified environment.

    Supports `lakebase.branch_from: <env>` — when set, the target env
    inherits `schema` from the source env and the output dict carries
    `branch_from_env` + `branch_from_workspace_path` so callers can run the
    branching flow.
    """
    if not CONFIG_PATH.exists():
        raise DeploymentError(f"Deployment config not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    environments = config.get("environments", {})
    if env not in environments:
        available = ", ".join(environments.keys())
        raise DeploymentError(
            f"Environment '{env}' not found in deployment config. "
            f"Available: {available}"
        )

    env_config = environments[env]
    lakebase_config = env_config.get("lakebase", {})
    ml_flat = _mlflow_flat_from_env_section(env_config)

    branch_from = lakebase_config.get("branch_from")
    schema_name = lakebase_config.get("schema")
    branch_from_workspace_path = None
    branch_from_app_name = None

    if branch_from:
        src = _load_branch_source_config(branch_from)
        if src["database_name"] != lakebase_config.get("database_name"):
            raise DeploymentError(
                f"branching requires same database_name; "
                f'{env}={lakebase_config.get("database_name")}, '
                f'{branch_from}={src["database_name"]}'
            )
        # Inherit schema from source env. If this env also specified a schema
        # and it differs, raise — avoid silent mismatches.
        if schema_name and schema_name != src["schema"]:
            raise DeploymentError(
                f"branching env '{env}' declared schema '{schema_name}' "
                f"which differs from source env '{branch_from}' schema "
                f"'{src['schema']}'. Remove the schema field from '{env}' "
                f"or change it to match."
            )
        schema_name = src["schema"]
        branch_from_workspace_path = src["workspace_path"]
        branch_from_app_name = src.get("app_name")

    return {
        "app_name": env_config.get("app_name"),
        "description": env_config.get("description", "AI Slide Generator"),
        "workspace_path": env_config.get("workspace_path"),
        "compute_size": env_config.get("compute_size", "MEDIUM"),
        "lakebase_name": lakebase_config.get("database_name"),
        "lakebase_capacity": lakebase_config.get("capacity", "CU_1"),
        "schema_name": schema_name,
        "branch_from_env": branch_from,
        "branch_from_workspace_path": branch_from_workspace_path,
        "branch_from_app_name": branch_from_app_name,
        "owner_grant_job_id": lakebase_config.get("owner_grant_job_id"),
        "encryption_secret_scope": env_config.get("encryption_secret_scope"),
        "encryption_secret_key": env_config.get("encryption_secret_key"),
        **ml_flat,
    }


_INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _validate_instance(instance: str) -> None:
    """Validate a deploy instance id. Raises DeploymentError if invalid."""
    if not _INSTANCE_RE.match(instance) or len(instance) > 59:
        raise DeploymentError(
            "--instance must match ^[a-z][a-z0-9-]*$ and be <=59 chars "
            f"(got '{instance}')"
        )


def _resolve_target(
    config: dict[str, Any], env: str, instance: Optional[str]
) -> tuple[str, str, str]:
    """Resolve (app_name, workspace_path, target_branch) for a deploy.

    Without an instance: names come straight from config and the branch is named
    after the env. With an instance: the env must be a branching env; the app
    name and workspace path are suffixed with the instance and the branch is
    ``dev-<instance>``.
    """
    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
    if instance is None:
        return app_name, workspace_path, env
    if not config.get("branch_from_env"):
        raise DeploymentError(
            f"--instance requires a branch_from env; '{env}' is not a "
            "branching env"
        )
    _validate_instance(instance)
    return (
        f"{app_name}-{instance}",
        f"{workspace_path}/{instance}",
        f"dev-{instance}",
    )


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
            "Run scripts/build_wheels.sh first."
        )

    wheels = list(app_dist.glob("*.whl"))
    if not wheels:
        raise DeploymentError(
            f"No wheel files found in {app_dist}. "
            "Run scripts/build_wheels.sh first."
        )

    # Return the most recently modified wheel
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
        Relative path to use in requirements.txt (e.g., "./wheels/package.whl")
    """
    wheels_dir = f"{workspace_path}/wheels"

    # Ensure wheels directory exists
    try:
        ws.workspace.mkdirs(wheels_dir)
    except Exception:
        pass  # May already exist

    # Clean old wheels to ensure only latest version is present
    try:
        objects = ws.workspace.list(wheels_dir)
        for obj in objects:
            if obj.path and obj.path.endswith(".whl"):
                ws.workspace.delete(obj.path)
                print(f"   Removed old wheel: {Path(obj.path).name}")
    except Exception:
        pass  # Directory might not exist yet

    # Upload new wheel
    wheel_dest = f"{wheels_dir}/{wheel_path.name}"
    with open(wheel_path, "rb") as f:
        ws.workspace.upload(
            wheel_dest,
            f,
            format=ImportFormat.AUTO,
            overwrite=True,
        )

    return f"./wheels/{wheel_path.name}"


def _source_secret_config(ws, source_app_name: str) -> tuple[str, str] | None:
    """Return the (scope, key) the source app uses, or None if it is legacy.

    The fork inherits the source's ciphertext through the copy-on-write branch but
    gets no encryption_keys row, because secret mode never writes one. So a fork of
    a secret-mode app MUST point at the same secret, or it boots, finds nothing,
    mints a fresh key, and silently destroys its own inherited test data.

    Fetching the source app is the only source of truth here; the
    --encryption-secret-scope flag applies to non-branching deploys only.
    """
    try:
        app = ws.apps.get(name=source_app_name)
    except Exception as exc:
        print(
            f"ERROR: cannot read the source app '{source_app_name}' to determine "
            f"whether it uses a secret-backed encryption key: {exc}\n"
            f"Refusing to fork: if the source is in secret mode, the fork would "
            f"mint a fresh key over inherited ciphertext."
        )
        raise SystemExit(1) from exc
    for r in (app.resources or []):
        if r.name == secret_key.RESOURCE_KEY and getattr(r, "secret", None):
            return r.secret.scope, r.secret.key
    return None


def _check_branching_preconditions(
    ws: WorkspaceClient, config: dict[str, Any]
) -> None:
    """Run preconditions for branching-mode deploy.

    Raises DeploymentError if any precondition fails, BEFORE any mutating
    ws.postgres call. Post SDR-4437 PR-3 the fork inherits the Fernet key via
    the copy-on-write encryption_keys table, so no key is returned — the
    legacy-key read below is purely a "source env already migrated?" check.
    """
    branch_from_env = config["branch_from_env"]
    branch_from_workspace_path = config["branch_from_workspace_path"]
    project_name = config["lakebase_name"]

    # 1+2 handled by load_deployment_config. By the time we get here,
    # branch_from_env is already resolved and database_name matches.

    # 3 + 4 in one download: the strict reader raises DeploymentError when
    # app.yaml cannot be downloaded/parsed — which here means the source env
    # is not deployed (or unreachable; the chained cause carries the detail).
    # Re-raise with the preflight's actionable message.
    try:
        legacy_key = _read_existing_encryption_key(ws, branch_from_workspace_path)
    except DeploymentError as e:
        raise DeploymentError(
            f"{branch_from_env} not deployed — deploy {branch_from_env} first "
            f"(could not read {branch_from_workspace_path}/app.yaml: {e})"
        ) from e

    # 4: source env must already be migrated off the app.yaml key. The fork
    # template cannot carry a key, and seeding the fork's table here would
    # need a human Postgres login (breaking SP-only dev-loop deploys).
    if legacy_key:
        raise DeploymentError(
            f"{branch_from_env}'s app.yaml still carries a legacy encryption key. "
            f"Update {branch_from_env} with the new deploy tool first (it relocates "
            f"the key into the encryption_keys table), then re-run this deploy."
        )

    # 5: Lakebase is autoscaling
    if not _probe_autoscaling_available(ws):
        raise DeploymentError(
            f"Lakebase branching requires autoscaling; "
            f"{project_name} is not an autoscaling project"
        )
    try:
        ws.postgres.get_project(name=f"projects/{project_name}")
    except Exception as e:
        raise DeploymentError(
            f"Lakebase branching requires autoscaling; "
            f"{project_name} is not an autoscaling project (get_project failed: {e})"
        ) from e

    # 6: source branch exists
    if not _branch_exists(ws, project_name, branch_from_env):
        raise DeploymentError(
            f'source branch "{branch_from_env}" not found in project {project_name}'
        )

    # 7: Secret-mode inheritance: if the source uses a secret-backed key, the
    # fork must point at the same secret. _source_secret_config refuses
    # (SystemExit) when the source app cannot be read — safe-fail over
    # proceeding blindly and minting a fresh key over inherited ciphertext.
    source_app = config.get("branch_from_app_name")
    if source_app:
        config["_inherited_secret"] = _source_secret_config(ws, source_app)


def _trigger_owner_grant_job(ws, job_id, new_sp_id, host, endpoint_name) -> None:
    """Run the serverless grant job (as the granter SP) to add new_sp_id to the
    shared owning role on this branch, and wait for it. Raises on failure so a
    deploy never proceeds with an SP that cannot migrate its fork."""
    print(f"   Granting SP {new_sp_id} into shared owning role via job {job_id}...")
    run = ws.jobs.run_now(
        job_id=job_id,
        python_params=[
            "--new-sp-id", new_sp_id,
            "--host", host,
            "--endpoint-name", endpoint_name,
        ],
    ).result()
    state = run.state.result_state if run.state else None
    if str(state) != "SUCCESS" and getattr(state, "value", None) != "SUCCESS":
        raise DeploymentError(
            f"owner-grant job {job_id} did not succeed (state={state}); "
            f"SP {new_sp_id} cannot migrate its fork"
        )
    print("   SP granted into shared owning role")


def _assert_fork_schema_setup_skippable(
    sp_owner_grant_ran: bool, schema_name: Optional[str]
) -> None:
    """Guard the fork-path skip of `_setup_database_schema`; raise if unsafe.

    Skipping deploy-time schema setup on a fork is only safe when the app SP
    actually owns the inherited schema. That holds only if BOTH:
      * the owner-grant job ran and succeeded — `_trigger_owner_grant_job`
        raises on failure, so a True flag here means the app SP is a member of
        `tellr_app_owners` WITH INHERIT (owner rights on the inherited schema);
      * the fork inherited a schema at all (copy-on-write from `branch_from_env`).

    The `tellr_app_owners` *ownership* of the inherited schema/tables cannot be
    re-checked here without a human Postgres connection — the very thing the
    skip removes — so it is guaranteed by construction: the branching preflight
    (`_check_branching_preconditions`) requires the source env to be deployed,
    and the fork is a copy-on-write branch of it. This guard enforces the parts
    that ARE checkable SP-only, and fails loudly rather than shipping an app
    that would lack schema ownership (or a schema) at runtime.
    """
    if not sp_owner_grant_ran:
        raise DeploymentError(
            "cannot skip deploy-time schema setup on the fork: the app SP was "
            "not granted into tellr_app_owners (missing app SP client id or "
            "owner_grant_job_id). Refusing to deploy an app that would lack "
            "schema ownership at runtime."
        )
    if not schema_name:
        raise DeploymentError(
            "cannot skip deploy-time schema setup on the fork: no schema was "
            "inherited from the source env (empty schema_name) — check the "
            "branch_from env's lakebase.schema."
        )


def create_local(
    env: str,
    profile: str,
    seed_databricks_defaults: bool = True,
    from_pypi: Optional[str] = None,
    instance: Optional[str] = None,
    encryption_secret_scope: Optional[str] = None,
    encryption_secret_key: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new Databricks App using locally-built wheels.

    Args:
        env: Environment name (development, staging, production)
        profile: Databricks CLI profile name
        seed_databricks_defaults: If True, seed Databricks-specific content
        from_pypi: If set (a version string), skip building/uploading a
            local wheel and instead pin ``databricks-tellr-app==<version>``
            from PyPI.
        encryption_secret_scope: Opt into secret-backed Fernet key. CLI arg
            takes precedence over the config value.
        encryption_secret_key: Secret key name (defaults to
            secret_key.DEFAULT_SECRET_KEY when scope is set).

    Returns:
        Dictionary with deployment info
    """
    config = load_deployment_config(env)
    ws = _get_workspace_client(profile=profile)

    app_name, workspace_path, target_branch = _resolve_target(config, env, instance)
    lakebase_name = config["lakebase_name"]
    schema_name = config["schema_name"]
    branch_from_env = config.get("branch_from_env")

    # Secret-mode resolution: CLI arg takes precedence over config.
    scope = encryption_secret_scope or config.get("encryption_secret_scope")
    skey = (
        encryption_secret_key
        or config.get("encryption_secret_key")
        or secret_key.DEFAULT_SECRET_KEY
    )

    print("Deploying AI Slide Generator (local wheels)...")
    print(f"   App name: {app_name}")
    print(f"   Workspace path: {workspace_path}")
    print(f"   Lakebase: {lakebase_name}")
    print(f"   Schema: {schema_name}")
    if branch_from_env:
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{target_branch}')")
    print()

    try:
        # Secret mode preflight (non-branching only; branching path is handled
        # by Task 13's fork secret-inheritance).
        if scope and not branch_from_env:
            secret_key.preflight_scope(ws, scope)
            secret_key.resolve_key_for_create(ws, scope, skey)

        # Resolve the app package source: local wheel (default) or PyPI.
        wheel_path = None
        local_wheel_ref = None
        if from_pypi:
            print(f"Using PyPI version: databricks-tellr-app=={from_pypi}")
            print("   Skipping local wheel build/upload")
            print()
        else:
            # Find and upload wheel
            print("Finding built wheel...")
            wheel_path = find_app_wheel()
            print(f"   Found: {wheel_path.name}")

            print("Uploading wheel to workspace...")
            local_wheel_ref = upload_wheel(ws, wheel_path, workspace_path)
            print(f"   Uploaded: {local_wheel_ref}")
            print()

        # Branching mode: preflight + recreate branch
        if branch_from_env:
            print("Running branching preflight checks...")
            _check_branching_preconditions(ws, config)
            print(f"   Preflight OK (source: {branch_from_env})")

            print(f"Creating ephemeral branch '{target_branch}' off '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, target_branch
            )
            print(
                f"   Branch '{lakebase_result['branch_id']}' ready "
                f"(endpoint: {lakebase_result['host']})"
            )
        else:
            # Standard path: get/create project + read production endpoint
            print("Setting up Lakebase database...")
            lakebase_result = _get_or_create_lakebase(
                ws, lakebase_name, config["lakebase_capacity"]
            )

        lakebase_type = lakebase_result.get("type", "provisioned")
        print(f"   Lakebase: {lakebase_result['name']} ({lakebase_result['status']})")
        print(f"   Type: {lakebase_type}")
        print()

        # Read any inherited secret that _check_branching_preconditions detected.
        # Set by _source_secret_config when the source app carries RESOURCE_KEY;
        # None for legacy sources and for non-branching deploys.
        _inherited_secret = config.get("_inherited_secret")

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_local_staging_"))
        try:
            if from_pypi:
                _write_requirements(staging_dir, from_pypi)
                print(f"   Generated requirements.txt (PyPI: {from_pypi})")
            else:
                _write_requirements(
                    staging_dir, None, local_wheel_path=local_wheel_ref
                )
                print("   Generated requirements.txt (local wheel)")

            mlflow_subs = _mlflow_substitutions_for_app_yaml(
                deployment_flat=config,
                overrides=None,
            )
            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                lakebase_result=lakebase_result,
                mlflow_tracing=mlflow_subs,
                encryption_secret_resource_key=(
                    secret_key.RESOURCE_KEY
                    if (_inherited_secret or (scope and not branch_from_env))
                    else None
                ),
            )
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
            description=config["description"],
            workspace_path=workspace_path,
            compute_size=config["compute_size"],
            lakebase_name=lakebase_name,
            lakebase_type=lakebase_type,
            encryption_secret_scope=(
                _inherited_secret[0] if _inherited_secret
                else (scope if not branch_from_env else None)
            ),
            encryption_secret_key=(
                _inherited_secret[1] if _inherited_secret
                else (skey if not branch_from_env else None)
            ),
        )
        print("   App registered")
        print()

        # Register SP role on the target branch (staging branch or production branch)
        sp_owner_grant_ran = False
        if lakebase_type == "autoscaling":
            client_id = _get_app_client_id(app)
            if client_id:
                print("Configuring SP role on autoscaling project...")
                # For branching envs, use the unique branch_id the helper
                # generated (e.g. "staging-1777000000"). For non-branching,
                # fall back to the production branch.
                sp_branch = (
                    lakebase_result.get("branch_id") if branch_from_env else "production"
                )
                _ensure_sp_autoscaling_role(
                    ws, lakebase_name, client_id, branch_name=sp_branch
                )
                grant_job_id = config.get("owner_grant_job_id")
                if branch_from_env and grant_job_id and client_id:
                    _trigger_owner_grant_job(
                        ws, grant_job_id, client_id,
                        lakebase_result["host"], lakebase_result["endpoint_name"],
                    )
                    # Grant job raises unless it succeeds, so reaching here means
                    # the app SP now owns the inherited schema via tellr_app_owners.
                    sp_owner_grant_ran = True
            else:
                print("   Warning: Could not get SP client ID — role setup skipped")

        # Set up database schema.
        #
        # On the branching/fork path this step is skipped: it is redundant and
        # is the ONLY step that requires the deploying human to hold a Postgres
        # login role on the project, so skipping it keeps dev-loop deploys
        # SP-only.
        #   * The fork inherits the schema and tables copy-on-write from the
        #     source env, owned by the shared `tellr_app_owners` role. The new
        #     app SP was just granted into that role WITH INHERIT (see
        #     `_trigger_owner_grant_job` above), so it already owns the
        #     inherited schema/tables — the GRANTs here would be no-ops.
        #   * The app (re)creates and migrates its own tables at startup AS the
        #     app SP (`init_db()` in the FastAPI lifespan), so table setup does
        #     not need to happen at deploy time.
        # `_setup_database_schema` connects via `_get_lakebase_connection`,
        # which authenticates as `ws.current_user.me()` (the deploying human);
        # a deployer with no login role on the project would fail there with
        # "password authentication failed". The non-fork (local/prod) path
        # still needs it — the schema may not exist yet and the SP's grants
        # come from AppResourceDatabase — so only the fork path is skipped.
        # The skip is gated on the owner-grant having actually run (see
        # `_assert_fork_schema_setup_skippable`): if the SP was never granted
        # into tellr_app_owners we fail loudly rather than ship a broken app.
        if branch_from_env:
            _assert_fork_schema_setup_skippable(sp_owner_grant_ran, schema_name)
            print(
                "Skipping deploy-time schema setup on fork "
                "(SP owns inherited schema; app migrates on startup)"
            )
        else:
            print("Setting up database schema...")
            _setup_database_schema(
                ws, app, lakebase_name, schema_name,
                lakebase_result=lakebase_result,
            )
            print(f"   Schema '{schema_name}' configured")
        print()

        # Deploy the app
        print("Deploying app...")
        app = _deploy_app(ws, app_name, workspace_path)
        print("   App deployed")
        if app.url:
            print(f"   URL: {app.url}")
        print()

        print("Deployment complete!")
        return {
            "url": app.url,
            "app_name": app_name,
            "lakebase_name": lakebase_name,
            "schema_name": schema_name,
            "wheel": wheel_path.name if wheel_path else None,
            "pypi_version": from_pypi,
            "branch": target_branch if branch_from_env else None,
            "status": "created",
        }

    except Exception as e:
        raise DeploymentError(f"Deployment failed: {e}") from e


def update_local(
    env: str,
    profile: str,
    reset_database: bool = False,
    seed_databricks_defaults: bool = True,
    from_pypi: Optional[str] = None,
    instance: Optional[str] = None,
    encryption_secret_scope: Optional[str] = None,
    encryption_secret_key: Optional[str] = None,
) -> dict[str, Any]:
    """Update an existing Databricks App using locally-built wheels.

    When ``from_pypi`` is set (a version string), skip building/uploading a
    local wheel and instead pin ``databricks-tellr-app==<version>`` from PyPI.
    """
    config = load_deployment_config(env)
    ws = _get_workspace_client(profile=profile)

    app_name, workspace_path, target_branch = _resolve_target(config, env, instance)
    lakebase_name = config["lakebase_name"]
    schema_name = config["schema_name"]
    branch_from_env = config.get("branch_from_env")

    # Pre-define scope so the post-deploy health gate can reference it
    # regardless of which path was taken below.
    scope: Optional[str] = None

    if branch_from_env and reset_database:
        print(
            "WARNING: --reset-db is a no-op for branching envs "
            "(each deploy is already a fresh branch). Ignoring."
        )
        reset_database = False

    print(f"Updating AI Slide Generator (local wheels): {app_name}")
    if branch_from_env:
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{target_branch}')")
    print()

    try:
        # Branching mode: preflight + recreate branch
        if branch_from_env:
            print("Running branching preflight checks...")
            _check_branching_preconditions(ws, config)
            print(f"   Preflight OK (source: {branch_from_env})")

            # Verify the app exists BEFORE branch recreation so we don't leave
            # an orphan staging branch when the user runs update before create.
            try:
                app = ws.apps.get(name=app_name)
            except Exception as e:
                raise DeploymentError(
                    f"App '{app_name}' does not exist — "
                    f"run 'deploy_local.sh create --env {env}' first"
                ) from e

            print(f"Recreating ephemeral branch '{target_branch}' from '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, target_branch
            )
            print(
                f"   Branch '{lakebase_result['branch_id']}' ready "
                f"(endpoint: {lakebase_result['host']})"
            )

            # Register SP role on the new staging branch.
            # (`app` was fetched above — reuse it; no need to re-GET.)
            client_id = _get_app_client_id(app)
            sp_owner_grant_ran = False
            if client_id:
                print("Configuring SP role on new branch...")
                _ensure_sp_autoscaling_role(
                    ws, lakebase_name, client_id,
                    branch_name=lakebase_result["branch_id"],
                )
                # update re-forks the branch (fresh prod copy), so the SP's
                # fork-scoped tellr_app_owners membership from the previous
                # deploy is gone — re-grant it on the new branch, same as create.
                grant_job_id = config.get("owner_grant_job_id")
                if branch_from_env and grant_job_id and client_id:
                    _trigger_owner_grant_job(
                        ws, grant_job_id, client_id,
                        lakebase_result["host"], lakebase_result["endpoint_name"],
                    )
                    # Grant job raises unless it succeeds — reaching here means
                    # the app SP owns the inherited schema via tellr_app_owners.
                    sp_owner_grant_ran = True
            else:
                print(
                    "   Warning: Could not get SP client ID — role setup skipped"
                )

            # Schema setup is intentionally NOT run on the branch (see the
            # detailed note in `create_local`): the SP was just granted into
            # `tellr_app_owners` WITH INHERIT above, so it already owns the
            # inherited schema/tables, and the app migrates them at startup AS
            # the SP. Running it here would connect as the deploying human via
            # `_get_lakebase_connection`, breaking SP-only dev-loop deploys.
            # Gated on the grant having run, same as create_local.
            _assert_fork_schema_setup_skippable(sp_owner_grant_ran, schema_name)
            print(
                "Skipping deploy-time schema setup on fork "
                "(SP owns inherited schema; app migrates on startup)"
            )
        else:
            # Standard path (prod/dev): get current Lakebase state
            print("Checking Lakebase database...")
            lakebase_result = _get_or_create_lakebase(
                ws, lakebase_name, config["lakebase_capacity"]
            )

            # Resolve effective scope (CLI arg beats config).
            scope = encryption_secret_scope or config.get("encryption_secret_scope")
            skey = (
                encryption_secret_key
                or config.get("encryption_secret_key")
                or secret_key.DEFAULT_SECRET_KEY
            )
            if scope:
                validate_schema_name(schema_name)  # defense-in-depth: interpolated into SQL below
                secret_key.preflight_scope(ws, scope)
                mig_conn = None
                try:
                    mig_conn, _ = _get_lakebase_connection(
                        ws, lakebase_name, lakebase_result=lakebase_result
                    )
                    with mig_conn.cursor() as cur:
                        secret_key.preflight_lakebase_privileges(cur, schema_name)
                        lakebase_key = secret_key.read_lakebase_key(cur, schema_name)
                finally:
                    if mig_conn is not None:
                        mig_conn.close()
                legacy_key = _read_existing_encryption_key(ws, workspace_path)
                _, wrote = secret_key.resolve_key_for_update(
                    ws, scope, skey, lakebase_key, legacy_key
                )
                if wrote:
                    print("   Key written to the secret and verified")
                secret_key.attach_secret_resource(ws, app_name, scope, skey)
                print("   Secret resource attached")
            else:
                legacy_key = _read_existing_encryption_key(ws, workspace_path)
                if legacy_key:
                    # CRITICAL-3: relocate before the keyless app.yaml overwrites it
                    print("Relocating encryption key into Lakebase (encryption_keys)...")
                    app_for_grant = ws.apps.get(name=app_name)
                    grant_client_id = _get_app_client_id(app_for_grant)
                    mig_conn, _ = _get_lakebase_connection(
                        ws, lakebase_name, lakebase_result=lakebase_result
                    )
                    try:
                        with mig_conn.cursor() as cur:
                            _migrate_encryption_key_to_lakebase(
                                cur, schema_name, grant_client_id, legacy_key
                            )
                    finally:
                        mig_conn.close()
                    print("   Key relocated")

        lakebase_type = lakebase_result.get("type", "provisioned")
        print(f"   Lakebase: {lakebase_result['name']} (type={lakebase_type})")
        print()

        # Reset database if requested (non-branching only; warning already printed)
        if reset_database:
            print("Resetting database schema...")
            app = ws.apps.get(name=app_name)
            _reset_schema(
                ws, app, lakebase_name, schema_name,
                lakebase_result=lakebase_result,
            )
            print(f"   Schema '{schema_name}' reset")
            print()

        # Resolve the app package source: local wheel (default) or PyPI.
        wheel_path = None
        local_wheel_ref = None
        if from_pypi:
            print(f"Using PyPI version: databricks-tellr-app=={from_pypi}")
            print("   Skipping local wheel build/upload")
            print()
        else:
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
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_local_staging_"))
        try:
            if from_pypi:
                _write_requirements(staging_dir, from_pypi)
                print(f"   Generated requirements.txt (PyPI: {from_pypi})")
            else:
                _write_requirements(
                    staging_dir, None, local_wheel_path=local_wheel_ref
                )
                print("   Generated requirements.txt (local wheel)")

            mlflow_subs = _mlflow_substitutions_for_app_yaml(
                deployment_flat=config,
                overrides=None,
            )
            app_already_secret = (
                not branch_from_env
                and secret_key.app_is_secret_mode(ws, app_name)
            )
            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                lakebase_result=lakebase_result,
                mlflow_tracing=mlflow_subs,
                encryption_secret_resource_key=(
                    secret_key.RESOURCE_KEY
                    if (config.get("_inherited_secret")
                        or (scope and not branch_from_env)
                        or app_already_secret)
                    else None
                ),
            )
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

        # Health gate + DELETE: only on the non-branching secret path.
        # A fork has no pre-existing row, and _get_lakebase_connection connects
        # as the deploying human, which breaks SP-only dev-loop deploys.
        if scope and not branch_from_env:
            app = ws.apps.get(name=app_name)
            if not app.url:
                print("   WARNING: no app URL — cannot confirm the key source; "
                      "leaving the Lakebase key row in place")
            elif secret_key.app_reports_secret_source(ws, app.url):
                del_conn = None
                try:
                    del_conn, _ = _get_lakebase_connection(
                        ws, lakebase_name, lakebase_result=lakebase_result
                    )
                    with del_conn.cursor() as cur:
                        if secret_key.read_lakebase_key(cur, schema_name):
                            secret_key.delete_lakebase_key_row(cur, schema_name)
                            print("   Lakebase key row deleted")
                        else:
                            print("   No Lakebase key row to remove")
                except Exception as exc:  # noqa: BLE001 — deploy already succeeded
                    print(f"   WARNING: could not delete the key row: {exc}")
                    print(f'   Run manually: DELETE FROM "{schema_name}".'
                          f"encryption_keys WHERE id = 1;")
                finally:
                    if del_conn is not None:
                        del_conn.close()
            else:
                print("   WARNING: the deployed app does not report the secret "
                      "as its key source. Leaving the Lakebase key row in "
                      "place. Expected if the app version predates secret mode.")

        return {
            "url": app.url,
            "app_name": app_name,
            "deployment_id": result.deployment_id,
            "wheel": wheel_path.name if wheel_path else None,
            "pypi_version": from_pypi,
            "status": "updated",
            "branch": target_branch if branch_from_env else None,
            "database_reset": reset_database,
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e


def delete_local(
    env: str, profile: str, reset_database: bool = False,
    instance: Optional[str] = None,
) -> dict[str, Any]:
    """Delete a Databricks App (and its ephemeral branch, if branching)."""
    config = load_deployment_config(env)
    branch_from_env = config.get("branch_from_env")
    app_name, _workspace_path, target_branch = _resolve_target(config, env, instance)

    if branch_from_env and reset_database:
        print(
            "WARNING: --reset-db is a no-op for branching envs "
            "(the branch itself is about to be deleted). Ignoring."
        )
        reset_database = False

    result = delete(
        app_name=app_name,
        lakebase_name=config["lakebase_name"],
        schema_name=config["schema_name"],
        reset_database=reset_database,
        profile=profile,
    )

    # For branching envs, also delete the ephemeral branch (fixed name, so this
    # is now safe and re-runnable — idempotent on not-found).
    if branch_from_env:
        ws = _get_workspace_client(profile=profile)
        _delete_branch(ws, config["lakebase_name"], target_branch)
        print(f"   Deleted branch '{target_branch}'")

    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the deploy_local CLI argument parser.

    Extracted from main() with no behaviour change so tests (and secret-mode
    plumbing) can construct the parser directly.
    """
    parser = argparse.ArgumentParser(
        description="Deploy AI Slide Generator to Databricks Apps using local wheels"
    )

    # Load available environments from config
    config_path = PROJECT_ROOT / "config" / "deployment.yaml"
    available_envs = []
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            _cfg = yaml.safe_load(f) or {}
        available_envs = list(_cfg.get("environments", {}).keys())

    parser.add_argument(
        "--env",
        type=str,
        required=True,
        choices=available_envs or ["development", "staging", "production"],
        help="Environment to deploy to",
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--create",
        action="store_const",
        const="create",
        dest="action",
        help="Create new app",
    )
    action_group.add_argument(
        "--update",
        action="store_const",
        const="update",
        dest="action",
        help="Update existing app",
    )
    action_group.add_argument(
        "--delete",
        action="store_const",
        const="delete",
        dest="action",
        help="Delete app",
    )

    parser.add_argument(
        "--profile",
        type=str,
        required=True,
        help="Databricks CLI profile name from ~/.databrickscfg",
    )

    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Drop and recreate database schema (WARNING: deletes all data)",
    )

    parser.add_argument(
        "--include-databricks-prompts",
        action="store_true",
        help="Include Databricks-specific content when seeding (for internal use)",
    )

    parser.add_argument(
        "--from-pypi",
        dest="from_pypi",
        type=str,
        default=None,
        metavar="VERSION",
        help=(
            "Deploy by pinning databricks-tellr-app==VERSION from PyPI "
            "instead of building/uploading a local wheel"
        ),
    )
    parser.add_argument(
        "--instance",
        dest="instance",
        type=str,
        default=None,
        metavar="ID",
        help=(
            "Ephemeral instance id for a branching env (e.g. devloop). "
            "Derives app name db-<base>-<id>, branch dev-<id>, and a per-instance "
            "workspace path. Required for concurrent dev-loop deploys."
        ),
    )

    parser.add_argument(
        "--encryption-secret-scope",
        default=None,
        help="Databricks secret scope for the Fernet encryption key. Opts into "
             "the secret-backed key path; omit for the Lakebase-backed default.",
    )
    parser.add_argument(
        "--encryption-secret-key",
        default=None,
        help="Secret key name within the scope (default: tellr-encryption-key).",
    )

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()

    args = parser.parse_args()

    if args.from_pypi and not _is_valid_version(args.from_pypi):
        parser.error(
            f"--from-pypi value '{args.from_pypi}' is not a valid "
            "PEP 440 version"
        )

    # Clear environment variables that would override profile settings
    env_vars_to_clear = [
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
    ]
    for var in env_vars_to_clear:
        if var in os.environ:
            del os.environ[var]

    try:
        if args.action == "create":
            result = create_local(
                env=args.env,
                profile=args.profile,
                seed_databricks_defaults=args.include_databricks_prompts,
                from_pypi=args.from_pypi,
                instance=args.instance,
                encryption_secret_scope=args.encryption_secret_scope,
                encryption_secret_key=args.encryption_secret_key,
            )
        elif args.action == "update":
            result = update_local(
                env=args.env,
                profile=args.profile,
                reset_database=args.reset_db,
                seed_databricks_defaults=args.include_databricks_prompts,
                from_pypi=args.from_pypi,
                instance=args.instance,
                encryption_secret_scope=args.encryption_secret_scope,
                encryption_secret_key=args.encryption_secret_key,
            )
        elif args.action == "delete":
            result = delete_local(
                env=args.env,
                profile=args.profile,
                reset_database=args.reset_db,
                instance=args.instance,
            )
        else:
            raise ValueError(f"Unknown action: {args.action}")

        print()
        print(f"Result: {result}")

    except DeploymentError as e:
        print(f"Deployment failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

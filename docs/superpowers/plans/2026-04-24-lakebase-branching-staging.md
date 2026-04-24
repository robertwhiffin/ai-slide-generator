# Lakebase branching for staging — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `deploy_local.sh {create|update} --env staging` fork an ephemeral Lakebase branch off production on every deploy, deploy the staging app against that branch with prod's schema + encryption key, and delete the branch on `delete --env staging`. Design doc: `docs/superpowers/specs/2026-04-24-lakebase-branching-staging-design.md`.

**Architecture:** Add a new `lakebase.branch_from` field to `config/deployment.yaml`. Extend `scripts/deploy_local.py` config resolution to inherit the source env's schema + workspace_path when `branch_from` is set. Add branch primitives (`_branch_exists`, `_delete_branch`, `_create_branch_from`, `_recreate_ephemeral_branch`) to `packages/databricks-tellr/databricks_tellr/deploy.py`. Parameterize two existing autoscaling helpers (`_ensure_sp_autoscaling_role`, `_get_or_create_lakebase_autoscaling`) with a `branch_name` kwarg defaulting to `"production"` so prod/dev behaviour is unchanged. Thread branching mode through `create_local` / `update_local` / `delete_local` via a preflight gate.

**Tech Stack:** Python 3.11, `databricks-sdk` (`ws.postgres.create_branch`/`delete_branch`/`get_branch`/`list_endpoints`), `pytest`, `unittest.mock`, `pyyaml`.

---

## File Structure

**New files:**
- `tests/unit/test_deploy_local_config_branching.py` — tests for config resolution with `branch_from`.
- `tests/unit/test_deploy_branch_helpers.py` — tests for the 4 new branch helpers in `deploy.py`.
- `tests/unit/test_deploy_local_preflight.py` — tests for the preflight check function.

**Modified files:**
- `config/deployment.yaml` — staging entry gets `branch_from: production`, loses `schema`.
- `scripts/deploy_local.py` — new `_load_branch_source_config`, new `_check_branching_preconditions`, branching mode in `load_deployment_config` / `create_local` / `update_local` / `delete_local`.
- `packages/databricks-tellr/databricks_tellr/deploy.py` — 4 new branch helpers; add `branch_name` kwarg to `_ensure_sp_autoscaling_role` and `_get_or_create_lakebase_autoscaling`.
- `tests/unit/test_deploy_autoscaling.py` — update 1-2 existing tests to cover the new `branch_name` kwarg's default (back-compat).

**SDK confirmed** (verified live): `ws.postgres.{create_branch, delete_branch, get_branch, list_branches, list_endpoints}` all exist. `Branch`, `BranchSpec` dataclasses exist. `BranchSpec.source_branch: str` is the field that points at the parent branch path.

---

## Task 1: Config resolution — `_load_branch_source_config` and `branch_from` in `load_deployment_config`

**Files:**
- Modify: `scripts/deploy_local.py` — function `load_deployment_config`, add helper `_load_branch_source_config`.
- Create: `tests/unit/test_deploy_local_config_branching.py`

**What this task does:** When `lakebase.branch_from: <name>` is set on an env, staging's resolved config inherits `schema` (read from source env's `lakebase.schema`) and gains two new keys: `branch_from_env` (str) and `branch_from_workspace_path` (str). Non-branching envs keep exact current behaviour.

### Steps

- [ ] **Step 1.1: Write the failing tests**

Create `tests/unit/test_deploy_local_config_branching.py`:

```python
"""Tests for branch_from resolution in load_deployment_config."""
from pathlib import Path
import pytest
import yaml

from scripts.deploy_local import load_deployment_config

FIXTURE_YAML = {
    "environments": {
        "production": {
            "app_name": "db-tellr-prod",
            "description": "prod",
            "workspace_path": "/Workspace/Users/x/.apps/prod/tellr",
            "compute_size": "LARGE",
            "lakebase": {
                "database_name": "db-tellr",
                "schema": "app_data_prod",
                "capacity": "CU_1",
            },
        },
        "staging": {
            "app_name": "db-tellr-staging",
            "description": "staging",
            "workspace_path": "/Workspace/Users/x/.apps/staging/tellr",
            "compute_size": "MEDIUM",
            "lakebase": {
                "database_name": "db-tellr",
                "branch_from": "production",
                "capacity": "CU_1",
            },
        },
        "development": {
            "app_name": "db-tellr-dev",
            "description": "dev",
            "workspace_path": "/Workspace/Users/x/.apps/dev/tellr",
            "compute_size": "MEDIUM",
            "lakebase": {
                "database_name": "db-tellr",
                "schema": "tellr_app_data_dev",
                "capacity": "CU_1",
            },
        },
    },
}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Write FIXTURE_YAML to tmp and point load_deployment_config at it."""
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(yaml.safe_dump(FIXTURE_YAML))
    # load_deployment_config resolves PROJECT_ROOT / "config" / "deployment.yaml"
    # Patch PROJECT_ROOT to tmp_path, and put the yaml at tmp_path/config/deployment.yaml
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "deployment.yaml").write_text(yaml.safe_dump(FIXTURE_YAML))
    monkeypatch.setattr("scripts.deploy_local.PROJECT_ROOT", tmp_path)
    return tmp_path


class TestLoadDeploymentConfig:
    def test_non_branching_env_unchanged(self, config_path):
        """production config is unaffected by branch_from logic."""
        cfg = load_deployment_config("production")
        assert cfg["schema_name"] == "app_data_prod"
        assert cfg.get("branch_from_env") is None
        assert cfg.get("branch_from_workspace_path") is None

    def test_dev_env_unchanged(self, config_path):
        cfg = load_deployment_config("development")
        assert cfg["schema_name"] == "tellr_app_data_dev"
        assert cfg.get("branch_from_env") is None

    def test_staging_inherits_prod_schema(self, config_path):
        cfg = load_deployment_config("staging")
        assert cfg["schema_name"] == "app_data_prod"
        assert cfg["branch_from_env"] == "production"
        assert cfg["branch_from_workspace_path"] == "/Workspace/Users/x/.apps/prod/tellr"
        # database_name still staging's own (same value)
        assert cfg["lakebase_name"] == "db-tellr"

    def test_branch_from_unknown_env_errors(self, config_path, tmp_path, monkeypatch):
        bad = dict(FIXTURE_YAML)
        bad["environments"]["staging"]["lakebase"]["branch_from"] = "nonexistent"
        (tmp_path / "config" / "deployment.yaml").write_text(yaml.safe_dump(bad))
        with pytest.raises(Exception, match="branch_from.*nonexistent.*not found"):
            load_deployment_config("staging")

    def test_database_name_mismatch_errors(self, config_path, tmp_path, monkeypatch):
        bad = yaml.safe_load(yaml.safe_dump(FIXTURE_YAML))
        bad["environments"]["staging"]["lakebase"]["database_name"] = "other-db"
        (tmp_path / "config" / "deployment.yaml").write_text(yaml.safe_dump(bad))
        with pytest.raises(Exception, match="same database_name"):
            load_deployment_config("staging")
```

- [ ] **Step 1.2: Run tests to verify they fail**

```
pytest tests/unit/test_deploy_local_config_branching.py -v
```

Expected: ALL tests fail — `KeyError: 'branch_from_env'` or `schema_name` is `None` for staging.

- [ ] **Step 1.3: Implement the resolution logic in `scripts/deploy_local.py`**

Replace the body of `load_deployment_config` (currently lines 50–86) with the logic below. Add the new `_load_branch_source_config` helper immediately above it.

```python
def _load_branch_source_config(
    environments: dict, source_env_name: str
) -> dict:
    """Return {workspace_path, schema, database_name} from the source env.

    Raises:
        DeploymentError: if source env is missing.
    """
    if source_env_name not in environments:
        raise DeploymentError(
            f'branch_from "{source_env_name}" not found in deployment config'
        )
    src = environments[source_env_name]
    src_lb = src.get("lakebase", {})
    return {
        "workspace_path": src.get("workspace_path"),
        "schema": src_lb.get("schema"),
        "database_name": src_lb.get("database_name"),
    }


def load_deployment_config(env: str) -> dict[str, Any]:
    """Load deployment configuration for the specified environment.

    Supports `lakebase.branch_from: <env>` — when set, the target env
    inherits `schema` from the source env and the output dict carries
    `branch_from_env` + `branch_from_workspace_path` so callers can run the
    branching flow.
    """
    config_path = PROJECT_ROOT / "config" / "deployment.yaml"
    if not config_path.exists():
        raise DeploymentError(f"Deployment config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
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

    branch_from = lakebase_config.get("branch_from")
    schema_name = lakebase_config.get("schema")
    branch_from_workspace_path = None

    if branch_from:
        src = _load_branch_source_config(environments, branch_from)
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
    }
```

- [ ] **Step 1.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_local_config_branching.py -v
```

Expected: 5 passed.

- [ ] **Step 1.5: Verify existing tests still pass**

```
pytest tests/unit/test_deploy_autoscaling.py tests/unit/test_database_autoscaling.py -v
```

Expected: all pass (no regressions — non-branching envs return same config shape with two extra keys set to `None`).

- [ ] **Step 1.6: Commit**

```
git add scripts/deploy_local.py tests/unit/test_deploy_local_config_branching.py
git commit -m "feat(deploy): add branch_from config resolution for Lakebase branching"
```

---

## Task 2: `_branch_exists` helper

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` — add new helper.
- Create: `tests/unit/test_deploy_branch_helpers.py`

**What this task does:** Thin wrapper around `ws.postgres.get_branch` that returns `False` on "not found" and surfaces other errors. Used by preflight + `_recreate_ephemeral_branch`.

### Steps

- [ ] **Step 2.1: Write the failing tests**

Create `tests/unit/test_deploy_branch_helpers.py`:

```python
"""Tests for Lakebase branch helpers in databricks_tellr.deploy."""
from unittest.mock import MagicMock, patch
import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import _branch_exists


@pytest.fixture
def mock_ws():
    return MagicMock()


class TestBranchExists:
    def test_returns_true_when_branch_exists(self, mock_ws):
        mock_ws.postgres.get_branch.return_value = MagicMock(name="branch")
        assert _branch_exists(mock_ws, "db-tellr", "production") is True
        mock_ws.postgres.get_branch.assert_called_once_with(
            name="projects/db-tellr/branches/production"
        )

    def test_returns_false_on_not_found(self, mock_ws):
        mock_ws.postgres.get_branch.side_effect = Exception("Resource not found")
        assert _branch_exists(mock_ws, "db-tellr", "staging") is False

    def test_returns_false_on_does_not_exist(self, mock_ws):
        mock_ws.postgres.get_branch.side_effect = Exception("branch does not exist")
        assert _branch_exists(mock_ws, "db-tellr", "staging") is False

    def test_surfaces_other_errors(self, mock_ws):
        mock_ws.postgres.get_branch.side_effect = Exception("permission denied")
        with pytest.raises(Exception, match="permission denied"):
            _branch_exists(mock_ws, "db-tellr", "production")
```

- [ ] **Step 2.2: Run tests to verify they fail**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestBranchExists -v
```

Expected: `ImportError: cannot import name '_branch_exists'`.

- [ ] **Step 2.3: Implement `_branch_exists`**

In `packages/databricks-tellr/databricks_tellr/deploy.py`, add immediately after `_get_or_create_lakebase` (around line 943):

```python
def _branch_exists(
    ws: WorkspaceClient, project_name: str, branch_name: str
) -> bool:
    """Return True if the Lakebase branch exists, False on not-found.

    Any error other than not-found is surfaced.
    """
    try:
        ws.postgres.get_branch(
            name=f"projects/{project_name}/branches/{branch_name}"
        )
        return True
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            return False
        raise
```

- [ ] **Step 2.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestBranchExists -v
```

Expected: 4 passed.

- [ ] **Step 2.5: Commit**

```
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_branch_helpers.py
git commit -m "feat(deploy): add _branch_exists helper for Lakebase branches"
```

---

## Task 3: `_delete_branch` helper

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py`
- Modify: `tests/unit/test_deploy_branch_helpers.py`

**What this task does:** Idempotent branch delete. Waits on the operation. Swallows "not found" so the command is re-runnable.

### Steps

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/unit/test_deploy_branch_helpers.py`:

```python
from databricks_tellr.deploy import _delete_branch


class TestDeleteBranch:
    def test_calls_delete_with_correct_path_and_waits(self, mock_ws):
        operation = MagicMock()
        mock_ws.postgres.delete_branch.return_value = operation

        _delete_branch(mock_ws, "db-tellr", "staging")

        mock_ws.postgres.delete_branch.assert_called_once_with(
            name="projects/db-tellr/branches/staging"
        )
        operation.wait.assert_called_once()

    def test_noop_on_not_found(self, mock_ws):
        mock_ws.postgres.delete_branch.side_effect = Exception("Resource not found")
        # Should not raise
        _delete_branch(mock_ws, "db-tellr", "staging")

    def test_noop_on_does_not_exist(self, mock_ws):
        mock_ws.postgres.delete_branch.side_effect = Exception("branch does not exist")
        _delete_branch(mock_ws, "db-tellr", "staging")

    def test_surfaces_other_errors(self, mock_ws):
        mock_ws.postgres.delete_branch.side_effect = Exception("permission denied")
        with pytest.raises(Exception, match="permission denied"):
            _delete_branch(mock_ws, "db-tellr", "staging")
```

- [ ] **Step 3.2: Run tests to verify they fail**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestDeleteBranch -v
```

Expected: `ImportError: cannot import name '_delete_branch'`.

- [ ] **Step 3.3: Implement `_delete_branch`**

Add to `deploy.py` immediately after `_branch_exists`:

```python
def _delete_branch(
    ws: WorkspaceClient, project_name: str, branch_name: str
) -> None:
    """Delete a Lakebase branch. Idempotent — no-op if the branch is missing.

    Waits on the long-running delete operation. Any error other than
    not-found is surfaced.
    """
    try:
        operation = ws.postgres.delete_branch(
            name=f"projects/{project_name}/branches/{branch_name}"
        )
        operation.wait()
        logger.info(f"Deleted Lakebase branch: {branch_name}")
    except Exception as e:
        error_str = str(e).lower()
        if "not found" in error_str or "does not exist" in error_str:
            logger.info(f"Branch {branch_name} not found (already deleted)")
            return
        raise
```

- [ ] **Step 3.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestDeleteBranch -v
```

Expected: 4 passed.

- [ ] **Step 3.5: Commit**

```
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_branch_helpers.py
git commit -m "feat(deploy): add idempotent _delete_branch helper"
```

---

## Task 4: `_create_branch_from` helper

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py`
- Modify: `tests/unit/test_deploy_branch_helpers.py`

**What this task does:** Creates a new branch as a child of `source_branch`. Waits on the operation. Polls `list_endpoints` on the new branch until an endpoint with a populated host appears (up to ~60s). Returns a `lakebase_result`-shaped dict so downstream helpers route connections to this branch.

### Steps

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/unit/test_deploy_branch_helpers.py`:

```python
from databricks_tellr.deploy import _create_branch_from


class TestCreateBranchFrom:
    def test_creates_branch_with_correct_source(self, mock_ws):
        # Set up mocks for the create_branch call
        create_op = MagicMock()
        mock_ws.postgres.create_branch.return_value = create_op

        # Set up endpoints polling: first call returns empty, then returns one
        endpoint_ready = MagicMock()
        endpoint_ready.name = "projects/db-tellr/branches/staging/endpoints/ep1"
        endpoint_ready.status = MagicMock(
            hosts=MagicMock(host="staging-ep1.example.com")
        )
        # list_endpoints returns an iterator; mock returns ready endpoint
        mock_ws.postgres.list_endpoints.return_value = iter([endpoint_ready])
        mock_ws.postgres.get_endpoint.return_value = endpoint_ready

        result = _create_branch_from(
            mock_ws,
            project_name="db-tellr",
            source_branch="production",
            target_branch="staging",
        )

        # Verify create_branch call shape
        call_kwargs = mock_ws.postgres.create_branch.call_args.kwargs
        assert call_kwargs["parent"] == "projects/db-tellr"
        assert call_kwargs["branch_id"] == "staging"
        branch_arg = call_kwargs["branch"]
        assert branch_arg.spec.source_branch == "projects/db-tellr/branches/production"

        # Verify operation waited
        create_op.wait.assert_called_once()

        # Verify returned lakebase_result shape
        assert result["type"] == "autoscaling"
        assert result["name"] == "db-tellr"
        assert result["host"] == "staging-ep1.example.com"
        assert result["endpoint_name"] == "projects/db-tellr/branches/staging/endpoints/ep1"
        assert result["project_id"] == "db-tellr"
        assert result["instance_name"] is None

    def test_raises_when_no_endpoint_after_timeout(self, mock_ws, monkeypatch):
        """If list_endpoints never returns a ready endpoint, raise DeploymentError."""
        from databricks_tellr.deploy import DeploymentError

        create_op = MagicMock()
        mock_ws.postgres.create_branch.return_value = create_op
        # Always empty
        mock_ws.postgres.list_endpoints.return_value = iter([])

        # Patch sleep so the test doesn't actually wait
        monkeypatch.setattr("databricks_tellr.deploy.time.sleep", lambda *_: None)
        # Shrink the timeout for fast test
        monkeypatch.setattr("databricks_tellr.deploy._BRANCH_ENDPOINT_TIMEOUT_S", 0.1)

        with pytest.raises(DeploymentError, match="no endpoint ready"):
            _create_branch_from(mock_ws, "db-tellr", "production", "staging")
```

- [ ] **Step 4.2: Run tests to verify they fail**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestCreateBranchFrom -v
```

Expected: `ImportError: cannot import name '_create_branch_from'`.

- [ ] **Step 4.3: Implement `_create_branch_from`**

First add `import time` if not already at the top of `deploy.py` (check with `grep -n "^import time" packages/databricks-tellr/databricks_tellr/deploy.py` — add at alphabetical position in the stdlib imports if missing).

Add the module-level constant near the top of the autoscaling section (around line 707, just before `_probe_autoscaling_available`):

```python
# How long to poll for a new branch's endpoint to come up before giving up.
_BRANCH_ENDPOINT_TIMEOUT_S = 120
_BRANCH_ENDPOINT_POLL_INTERVAL_S = 3
```

Add the helper immediately after `_delete_branch`:

```python
def _create_branch_from(
    ws: WorkspaceClient,
    project_name: str,
    source_branch: str,
    target_branch: str,
) -> dict[str, Any]:
    """Create a new Lakebase branch as a child of `source_branch`.

    Waits on the create operation, then polls list_endpoints on the new
    branch until an endpoint with a populated host appears
    (up to _BRANCH_ENDPOINT_TIMEOUT_S). Raises DeploymentError on timeout.

    Returns a lakebase_result-shaped dict pointing at the new branch.
    """
    if not HAS_AUTOSCALING_SDK:
        raise DeploymentError(
            "Autoscaling SDK not available — cannot create Lakebase branch. "
            "Upgrade databricks-sdk."
        )

    source_path = f"projects/{project_name}/branches/{source_branch}"
    target_parent = f"projects/{project_name}"
    target_path = f"projects/{project_name}/branches/{target_branch}"

    logger.info(f"Creating branch {target_branch} from {source_branch}")
    operation = ws.postgres.create_branch(
        parent=target_parent,
        branch=Branch(spec=BranchSpec(source_branch=source_path)),
        branch_id=target_branch,
    )
    operation.wait()
    logger.info(f"Branch {target_branch} created")

    # Poll for endpoint readiness
    deadline = time.time() + _BRANCH_ENDPOINT_TIMEOUT_S
    endpoint = None
    while time.time() < deadline:
        endpoints = list(ws.postgres.list_endpoints(parent=target_path))
        ready = [
            e for e in endpoints
            if getattr(e, "status", None)
            and getattr(e.status, "hosts", None)
            and getattr(e.status.hosts, "host", None)
        ]
        if ready:
            endpoint = ready[0]
            break
        time.sleep(_BRANCH_ENDPOINT_POLL_INTERVAL_S)

    if endpoint is None:
        raise DeploymentError(
            f"Branch {target_branch} created but no endpoint ready within "
            f"{_BRANCH_ENDPOINT_TIMEOUT_S}s"
        )

    return {
        "name": project_name,
        "type": "autoscaling",
        "status": "created",
        "host": endpoint.status.hosts.host,
        "endpoint_name": endpoint.name,
        "project_id": project_name,
        "instance_name": None,
    }
```

Also add `Branch, BranchSpec` to the autoscaling import block at the top of `deploy.py` (currently line 32–37):

```python
# Autoscaling imports (Lakebase next-gen)
try:
    from databricks.sdk.service.postgres import (
        Branch,
        BranchSpec,
        Project,
        ProjectDefaultEndpointSettings,
        ProjectSpec,
    )
    HAS_AUTOSCALING_SDK = True
except ImportError:
    HAS_AUTOSCALING_SDK = False
```

- [ ] **Step 4.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestCreateBranchFrom -v
```

Expected: 2 passed.

- [ ] **Step 4.5: Commit**

```
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_branch_helpers.py
git commit -m "feat(deploy): add _create_branch_from helper with endpoint polling"
```

---

## Task 5: `_recreate_ephemeral_branch` helper

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py`
- Modify: `tests/unit/test_deploy_branch_helpers.py`

**What this task does:** Composition of `_delete_branch` + `_create_branch_from`. Exists as its own function for call-site readability in `create_local`/`update_local`.

### Steps

- [ ] **Step 5.1: Write the failing tests**

Append to `tests/unit/test_deploy_branch_helpers.py`:

```python
from databricks_tellr.deploy import _recreate_ephemeral_branch


class TestRecreateEphemeralBranch:
    def test_deletes_then_creates(self, mock_ws, monkeypatch):
        calls = []

        def fake_delete(ws, project, branch):
            calls.append(("delete", branch))

        def fake_create(ws, project, source, target):
            calls.append(("create", source, target))
            return {"host": "x", "endpoint_name": "e", "type": "autoscaling"}

        monkeypatch.setattr(
            "databricks_tellr.deploy._delete_branch", fake_delete
        )
        monkeypatch.setattr(
            "databricks_tellr.deploy._create_branch_from", fake_create
        )

        result = _recreate_ephemeral_branch(
            mock_ws,
            project_name="db-tellr",
            source_branch="production",
            target_branch="staging",
        )

        assert calls == [
            ("delete", "staging"),
            ("create", "production", "staging"),
        ]
        assert result["host"] == "x"
```

- [ ] **Step 5.2: Run tests to verify they fail**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestRecreateEphemeralBranch -v
```

Expected: `ImportError: cannot import name '_recreate_ephemeral_branch'`.

- [ ] **Step 5.3: Implement `_recreate_ephemeral_branch`**

In `deploy.py`, add immediately after `_create_branch_from`:

```python
def _recreate_ephemeral_branch(
    ws: WorkspaceClient,
    project_name: str,
    source_branch: str,
    target_branch: str,
) -> dict[str, Any]:
    """Delete `target_branch` if it exists, then create it from `source_branch`.

    Returns the lakebase_result dict for the newly-created branch.
    """
    _delete_branch(ws, project_name, target_branch)
    return _create_branch_from(ws, project_name, source_branch, target_branch)
```

- [ ] **Step 5.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_branch_helpers.py::TestRecreateEphemeralBranch -v
```

Expected: 1 passed.

- [ ] **Step 5.5: Run the full branch-helpers test file**

```
pytest tests/unit/test_deploy_branch_helpers.py -v
```

Expected: 11 passed (4 + 4 + 2 + 1).

- [ ] **Step 5.6: Commit**

```
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_branch_helpers.py
git commit -m "feat(deploy): add _recreate_ephemeral_branch composition helper"
```

---

## Task 6: Parameterize `_ensure_sp_autoscaling_role` with `branch_name`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` — function `_ensure_sp_autoscaling_role` (currently at line 777).
- Modify: `tests/unit/test_deploy_autoscaling.py` — add test covering non-default `branch_name`.

**What this task does:** Replace the hardcoded `branches/production` with a `branch_name` kwarg defaulting to `"production"`. All existing callers keep working; staging flow can pass `branch_name="staging"`.

### Steps

- [ ] **Step 6.1: Write the failing test**

Find the existing `TestEnsureSpAutoscalingRole` (or similar) class in `tests/unit/test_deploy_autoscaling.py` and append this test to it. If no such class exists, add it at the bottom of the file:

```python
class TestEnsureSpAutoscalingRoleBranchName:
    """Tests that _ensure_sp_autoscaling_role uses the branch_name kwarg."""

    def test_default_branch_is_production(self, mock_ws):
        # get_role raises not-found so we go down the create path
        mock_ws.postgres.get_role.side_effect = Exception("not found")
        create_op = MagicMock()
        mock_ws.postgres.create_role.return_value = create_op

        _ensure_sp_autoscaling_role(mock_ws, "db-tellr", "client-123")

        # Inspect parent path used for role creation
        assert (
            mock_ws.postgres.create_role.call_args.kwargs["parent"]
            == "projects/db-tellr/branches/production"
        )

    def test_custom_branch_name_threads_through(self, mock_ws):
        mock_ws.postgres.get_role.side_effect = Exception("not found")
        create_op = MagicMock()
        mock_ws.postgres.create_role.return_value = create_op

        _ensure_sp_autoscaling_role(
            mock_ws, "db-tellr", "client-123", branch_name="staging"
        )

        assert (
            mock_ws.postgres.create_role.call_args.kwargs["parent"]
            == "projects/db-tellr/branches/staging"
        )
```

- [ ] **Step 6.2: Run the tests to verify failure**

```
pytest tests/unit/test_deploy_autoscaling.py::TestEnsureSpAutoscalingRoleBranchName -v
```

Expected: `test_custom_branch_name_threads_through` fails because the `branch_name` kwarg doesn't exist yet (TypeError: unexpected keyword argument). `test_default_branch_is_production` may pass today because the hardcoded `"production"` happens to match.

- [ ] **Step 6.3: Modify `_ensure_sp_autoscaling_role` in `deploy.py`**

Change the signature (line 777) from:

```python
def _ensure_sp_autoscaling_role(
    ws: WorkspaceClient, project_name: str, client_id: str
) -> None:
```

to:

```python
def _ensure_sp_autoscaling_role(
    ws: WorkspaceClient,
    project_name: str,
    client_id: str,
    branch_name: str = "production",
) -> None:
```

Replace the hardcoded branch_path (line 803):

```python
branch_path = f"projects/{project_name}/branches/production"
```

with:

```python
branch_path = f"projects/{project_name}/branches/{branch_name}"
```

Update the docstring at the top of the function to mention the new parameter (one line is fine).

- [ ] **Step 6.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_autoscaling.py -v
```

Expected: all existing tests still pass + 2 new tests pass.

- [ ] **Step 6.5: Commit**

```
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_autoscaling.py
git commit -m "refactor(deploy): parameterize _ensure_sp_autoscaling_role with branch_name"
```

---

## Task 7: Parameterize `_get_or_create_lakebase_autoscaling` with `branch_name`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` — function `_get_or_create_lakebase_autoscaling` (currently at line 720).
- Modify: `tests/unit/test_deploy_autoscaling.py` — add test covering non-default `branch_name`.

**What this task does:** Allow the caller to fetch the endpoint info from a non-production branch. Used by the staging flow to grab connection info for the staging branch.

### Steps

- [ ] **Step 7.1: Write the failing test**

Append to `tests/unit/test_deploy_autoscaling.py`:

```python
class TestGetOrCreateLakebaseAutoscalingBranchName:
    def test_default_branch_is_production(self, mock_ws):
        # Mock get_project so we skip the create path
        mock_ws.postgres.get_project.return_value = MagicMock()
        endpoint = MagicMock()
        endpoint.name = "projects/db-tellr/branches/production/endpoints/ep1"
        endpoint.status = MagicMock(hosts=MagicMock(host="prod-host"))
        mock_ws.postgres.list_endpoints.return_value = iter([endpoint])
        mock_ws.postgres.get_endpoint.return_value = endpoint

        _get_or_create_lakebase_autoscaling(mock_ws, "db-tellr", "CU_1")

        mock_ws.postgres.list_endpoints.assert_called_once_with(
            parent="projects/db-tellr/branches/production"
        )

    def test_custom_branch_name(self, mock_ws):
        mock_ws.postgres.get_project.return_value = MagicMock()
        endpoint = MagicMock()
        endpoint.name = "projects/db-tellr/branches/staging/endpoints/ep1"
        endpoint.status = MagicMock(hosts=MagicMock(host="staging-host"))
        mock_ws.postgres.list_endpoints.return_value = iter([endpoint])
        mock_ws.postgres.get_endpoint.return_value = endpoint

        result = _get_or_create_lakebase_autoscaling(
            mock_ws, "db-tellr", "CU_1", branch_name="staging"
        )

        mock_ws.postgres.list_endpoints.assert_called_once_with(
            parent="projects/db-tellr/branches/staging"
        )
        assert result["host"] == "staging-host"
```

- [ ] **Step 7.2: Run tests to verify failure**

```
pytest tests/unit/test_deploy_autoscaling.py::TestGetOrCreateLakebaseAutoscalingBranchName -v
```

Expected: `test_custom_branch_name` fails with TypeError (unexpected kwarg).

- [ ] **Step 7.3: Modify `_get_or_create_lakebase_autoscaling` in `deploy.py`**

Change the signature (line 720) from:

```python
def _get_or_create_lakebase_autoscaling(
    ws: WorkspaceClient, database_name: str, capacity: str
) -> dict[str, Any]:
```

to:

```python
def _get_or_create_lakebase_autoscaling(
    ws: WorkspaceClient,
    database_name: str,
    capacity: str,
    branch_name: str = "production",
) -> dict[str, Any]:
```

Replace the hardcoded endpoint parent (line 755):

```python
endpoints = list(ws.postgres.list_endpoints(
    parent=f"projects/{database_name}/branches/production"
))
```

with:

```python
endpoints = list(ws.postgres.list_endpoints(
    parent=f"projects/{database_name}/branches/{branch_name}"
))
```

Also update the error message at line 758 to include the branch:

```python
raise DeploymentError(
    f"No endpoints found for autoscaling project {database_name} "
    f"on branch {branch_name}"
)
```

- [ ] **Step 7.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_autoscaling.py -v
```

Expected: all pass.

- [ ] **Step 7.5: Commit**

```
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_autoscaling.py
git commit -m "refactor(deploy): parameterize _get_or_create_lakebase_autoscaling with branch_name"
```

---

## Task 8: Preflight `_check_branching_preconditions` in `deploy_local.py`

**Files:**
- Modify: `scripts/deploy_local.py` — new helper `_check_branching_preconditions`.
- Create: `tests/unit/test_deploy_local_preflight.py`

**What this task does:** Runs all 6 preconditions from the spec §Error handling table. Returns the source app's encryption key (so callers don't re-download). Raises `DeploymentError` with actionable messages. Must be invoked before any mutating Lakebase call.

### Steps

- [ ] **Step 8.1: Write the failing tests**

Create `tests/unit/test_deploy_local_preflight.py`:

```python
"""Tests for branching-mode preflight checks."""
from unittest.mock import MagicMock, patch
import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr package not installed")

from databricks_tellr.deploy import DeploymentError


@pytest.fixture
def mock_ws():
    return MagicMock()


@pytest.fixture
def good_config():
    return {
        "lakebase_name": "db-tellr",
        "branch_from_env": "production",
        "branch_from_workspace_path": "/Workspace/Users/x/.apps/prod/tellr",
    }


class TestCheckBranchingPreconditions:
    def test_happy_path_returns_encryption_key(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        # Patch all the Workspace/SDK calls
        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="prod-key-123",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available", return_value=True
        ):
            mock_ws.postgres.get_project.return_value = MagicMock()
            with patch(
                "scripts.deploy_local._branch_exists", return_value=True
            ):
                key = _check_branching_preconditions(mock_ws, good_config)
        assert key == "prod-key-123"

    def test_missing_prod_app_yaml(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value=None,
        ):
            with pytest.raises(
                DeploymentError, match="production not deployed"
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_provisioned_lakebase_errors(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="k",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available",
            return_value=False,
        ):
            with pytest.raises(
                DeploymentError, match="requires autoscaling"
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_project_missing(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="k",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available",
            return_value=True,
        ):
            mock_ws.postgres.get_project.side_effect = Exception("not found")
            with pytest.raises(
                DeploymentError, match="not an autoscaling project"
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_source_branch_missing(self, mock_ws, good_config):
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value="k",
        ), patch(
            "scripts.deploy_local._probe_autoscaling_available",
            return_value=True,
        ), patch(
            "scripts.deploy_local._branch_exists", return_value=False
        ):
            mock_ws.postgres.get_project.return_value = MagicMock()
            with pytest.raises(
                DeploymentError, match='source branch "production" not found'
            ):
                _check_branching_preconditions(mock_ws, good_config)

    def test_preflight_does_not_mutate_on_any_failure(self, mock_ws, good_config):
        """Confirm no mutating ws.postgres call is made when preflight fails."""
        from scripts.deploy_local import _check_branching_preconditions

        with patch(
            "scripts.deploy_local._read_existing_encryption_key",
            return_value=None,
        ):
            with pytest.raises(DeploymentError):
                _check_branching_preconditions(mock_ws, good_config)

        mock_ws.postgres.create_branch.assert_not_called()
        mock_ws.postgres.delete_branch.assert_not_called()
        mock_ws.postgres.create_role.assert_not_called()
```

- [ ] **Step 8.2: Run tests to verify failure**

```
pytest tests/unit/test_deploy_local_preflight.py -v
```

Expected: `ImportError: cannot import name '_check_branching_preconditions'`.

- [ ] **Step 8.3: Implement `_check_branching_preconditions` in `scripts/deploy_local.py`**

First, add these imports at the top of `deploy_local.py` alongside the existing `from databricks_tellr.deploy import ...`:

```python
from databricks_tellr.deploy import (
    DeploymentError,
    _branch_exists,
    _get_workspace_client,
    _get_or_create_lakebase,
    _probe_autoscaling_available,
    _read_existing_encryption_key,
    _recreate_ephemeral_branch,
    _write_requirements,
    _write_app_yaml,
    _upload_files,
    _create_app,
    _deploy_app,
    _setup_database_schema,
    _reset_schema,
    _get_app_client_id,
    _ensure_sp_autoscaling_role,
    delete,
)
```

(Adds: `_branch_exists`, `_probe_autoscaling_available`, `_recreate_ephemeral_branch`.)

Add the new function immediately above `create_local`:

```python
def _check_branching_preconditions(
    ws: WorkspaceClient, config: dict[str, Any]
) -> str:
    """Run preconditions for branching-mode deploy. Return prod's encryption key.

    Raises DeploymentError if any precondition fails, BEFORE any mutating
    ws.postgres call.
    """
    branch_from_env = config["branch_from_env"]
    branch_from_workspace_path = config["branch_from_workspace_path"]
    project_name = config["lakebase_name"]

    # 1+2 handled by load_deployment_config. By the time we get here,
    # branch_from_env is already resolved and database_name matches.

    # 3 + 4: source app.yaml exists and has a key
    encryption_key = _read_existing_encryption_key(ws, branch_from_workspace_path)
    if not encryption_key:
        raise DeploymentError(
            f"{branch_from_env} not deployed — deploy {branch_from_env} first "
            f"(could not read GOOGLE_OAUTH_ENCRYPTION_KEY from "
            f"{branch_from_workspace_path}/app.yaml)"
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

    return encryption_key
```

- [ ] **Step 8.4: Run tests to verify they pass**

```
pytest tests/unit/test_deploy_local_preflight.py -v
```

Expected: 6 passed.

- [ ] **Step 8.5: Commit**

```
git add scripts/deploy_local.py tests/unit/test_deploy_local_preflight.py
git commit -m "feat(deploy): add branching-mode preflight check with all six preconditions"
```

---

## Task 9: Wire branching mode into `create_local`

**Files:**
- Modify: `scripts/deploy_local.py` — function `create_local`.

**What this task does:** When `config["branch_from_env"]` is set, run preflight, recreate the ephemeral branch, and pass the branch-pointing `lakebase_result` through the rest of the flow. Use prod's encryption key (already returned by preflight). When `branch_from_env` is not set, behaviour is unchanged.

Tests: we don't unit-test `create_local` end-to-end (too many moving parts); we verify the piece we changed — the branching switch — via the preflight tests and integration tests documented in Task 14.

### Steps

- [ ] **Step 9.1: Modify `create_local` in `scripts/deploy_local.py`**

Replace the current body of `create_local` (currently lines 163–288) with the branching-aware version below. The diff is additive at the top (preflight + branch creation) and a small change in the lakebase-acquisition path.

```python
def create_local(
    env: str,
    profile: str,
    seed_databricks_defaults: bool = True,
) -> dict[str, Any]:
    """Create a new Databricks App using locally-built wheels."""
    config = load_deployment_config(env)
    ws = _get_workspace_client(profile=profile)

    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
    lakebase_name = config["lakebase_name"]
    schema_name = config["schema_name"]
    branch_from_env = config.get("branch_from_env")

    print("Deploying AI Slide Generator (local wheels)...")
    print(f"   App name: {app_name}")
    print(f"   Workspace path: {workspace_path}")
    print(f"   Lakebase: {lakebase_name}")
    print(f"   Schema: {schema_name}")
    if branch_from_env:
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{env}')")
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

        # Branching mode: preflight + recreate branch
        encryption_key = None
        if branch_from_env:
            print("Running branching preflight checks...")
            encryption_key = _check_branching_preconditions(ws, config)
            print(f"   Preflight OK (source: {branch_from_env})")

            print(f"Recreating ephemeral branch '{env}' from '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, env
            )
            print(
                f"   Branch '{env}' ready "
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

        # Generate and upload deployment files
        print("Preparing deployment files...")
        staging_dir = Path(tempfile.mkdtemp(prefix="tellr_local_staging_"))
        try:
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                encryption_key=encryption_key,  # None → _write_app_yaml generates one
                lakebase_result=lakebase_result,
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
        )
        print("   App registered")
        print()

        # Register SP role on the target branch (staging branch or production branch)
        if lakebase_type == "autoscaling":
            client_id = _get_app_client_id(app)
            if client_id:
                print("Configuring SP role on autoscaling project...")
                sp_branch = env if branch_from_env else "production"
                _ensure_sp_autoscaling_role(
                    ws, lakebase_name, client_id, branch_name=sp_branch
                )
            else:
                print("   Warning: Could not get SP client ID — role setup skipped")

        # Set up database schema
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
            "wheel": wheel_path.name,
            "branch": env if branch_from_env else None,
            "status": "created",
        }

    except Exception as e:
        raise DeploymentError(f"Deployment failed: {e}") from e
```

- [ ] **Step 9.2: Run all unit tests for regressions**

```
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 9.3: Commit**

```
git add scripts/deploy_local.py
git commit -m "feat(deploy): wire branching mode into create_local"
```

---

## Task 10: Wire branching mode into `update_local`

**Files:**
- Modify: `scripts/deploy_local.py` — function `update_local`.

**What this task does:** On every `update --env staging`, preflight + recreate the branch + re-register the SP role on the new branch. For non-branching envs, behaviour is unchanged (continue reading the existing encryption key from the app's own workspace path).

### Steps

- [ ] **Step 10.1: Modify `update_local` in `scripts/deploy_local.py`**

Replace the current `update_local` (currently lines 291–395) with:

```python
def update_local(
    env: str,
    profile: str,
    reset_database: bool = False,
    seed_databricks_defaults: bool = True,
) -> dict[str, Any]:
    """Update an existing Databricks App using locally-built wheels."""
    config = load_deployment_config(env)
    ws = _get_workspace_client(profile=profile)

    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
    lakebase_name = config["lakebase_name"]
    schema_name = config["schema_name"]
    branch_from_env = config.get("branch_from_env")

    if branch_from_env and reset_database:
        print(
            "WARNING: --reset-db is a no-op for branching envs "
            "(each deploy is already a fresh branch). Ignoring."
        )
        reset_database = False

    print(f"Updating AI Slide Generator (local wheels): {app_name}")
    if branch_from_env:
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{env}')")
    print()

    try:
        # Branching mode: preflight + recreate branch
        if branch_from_env:
            print("Running branching preflight checks...")
            encryption_key = _check_branching_preconditions(ws, config)
            print(f"   Preflight OK (source: {branch_from_env})")

            print(f"Recreating ephemeral branch '{env}' from '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, env
            )
            print(
                f"   Branch '{env}' ready "
                f"(endpoint: {lakebase_result['host']})"
            )

            # Register SP role on the new staging branch
            app = ws.apps.get(name=app_name)
            client_id = _get_app_client_id(app)
            if client_id:
                print("Configuring SP role on new branch...")
                _ensure_sp_autoscaling_role(
                    ws, lakebase_name, client_id, branch_name=env
                )

            # Grant schema perms on the new branch
            print("Granting schema permissions on new branch...")
            _setup_database_schema(
                ws, app, lakebase_name, schema_name,
                lakebase_result=lakebase_result,
            )
            print(f"   Schema '{schema_name}' permissions configured")
        else:
            # Standard path (prod/dev): get current Lakebase state
            print("Checking Lakebase database...")
            lakebase_result = _get_or_create_lakebase(
                ws, lakebase_name, config["lakebase_capacity"]
            )
            encryption_key = _read_existing_encryption_key(ws, workspace_path)

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
            _write_requirements(staging_dir, None, local_wheel_path=local_wheel_ref)
            print("   Generated requirements.txt (local wheel)")

            _write_app_yaml(
                staging_dir,
                lakebase_name,
                schema_name,
                seed_databricks_defaults=seed_databricks_defaults,
                encryption_key=encryption_key,
                lakebase_result=lakebase_result,
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

        return {
            "url": app.url,
            "app_name": app_name,
            "deployment_id": result.deployment_id,
            "wheel": wheel_path.name,
            "status": "updated",
            "branch": env if branch_from_env else None,
            "database_reset": reset_database,
        }

    except Exception as e:
        raise DeploymentError(f"Update failed: {e}") from e
```

- [ ] **Step 10.2: Run all unit tests**

```
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 10.3: Commit**

```
git add scripts/deploy_local.py
git commit -m "feat(deploy): wire branching mode into update_local with per-deploy branch reset"
```

---

## Task 11: Wire branching mode into `delete_local`

**Files:**
- Modify: `scripts/deploy_local.py` — function `delete_local`.

**What this task does:** After the existing `delete()` call removes the app, also delete the staging branch. Idempotent. Non-branching envs unchanged.

### Steps

- [ ] **Step 11.1: Modify `delete_local`**

Replace current `delete_local` (lines 398–417) with:

```python
def delete_local(env: str, profile: str, reset_database: bool = False) -> dict[str, Any]:
    """Delete a Databricks App (and its ephemeral branch, if branching)."""
    config = load_deployment_config(env)
    branch_from_env = config.get("branch_from_env")

    result = delete(
        app_name=config["app_name"],
        lakebase_name=config["lakebase_name"],
        schema_name=config["schema_name"],
        reset_database=reset_database,
        profile=profile,
    )

    if branch_from_env:
        ws = _get_workspace_client(profile=profile)
        print(f"Deleting ephemeral branch '{env}'...")
        _delete_branch(ws, config["lakebase_name"], env)
        print(f"   Branch '{env}' deleted")
        result["branch_deleted"] = env

    return result
```

Also add `_delete_branch` to the import list at the top of `scripts/deploy_local.py`:

```python
from databricks_tellr.deploy import (
    ...
    _delete_branch,
    ...
)
```

- [ ] **Step 11.2: Run all unit tests**

```
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 11.3: Commit**

```
git add scripts/deploy_local.py
git commit -m "feat(deploy): delete ephemeral branch on delete_local when branching"
```

---

## Task 12: `--reset-db` no-op warning sanity test

**Files:**
- Modify: `tests/unit/test_deploy_local_config_branching.py` — add a small unit test for the warning behaviour (by checking `update_local` path is reachable, or test the warning message via stdout capture).

**What this task does:** The warning logic already landed in Task 10. This task verifies the observable behaviour with a small test. Skippable if you've manually verified — flagged because silent "ignore a flag" behaviour is the kind of thing that surprises users later.

### Steps

- [ ] **Step 12.1: Write the test**

Append to `tests/unit/test_deploy_local_config_branching.py`:

```python
class TestResetDbNoopWarning:
    def test_reset_db_warning_printed_for_branching_env(
        self, config_path, capsys, monkeypatch
    ):
        """update_local with a branching env + reset_database prints a warning and ignores the flag."""
        from scripts import deploy_local

        # Patch every side-effecting call in update_local down to the warning print
        monkeypatch.setattr(
            deploy_local, "_get_workspace_client", lambda profile=None: MagicMock()
        )
        # Make preflight fail loudly with a recognisable error — we just want to
        # get past the warning print, not execute the rest of the flow.
        def boom(*a, **kw):
            raise deploy_local.DeploymentError("STOP")
        monkeypatch.setattr(deploy_local, "_check_branching_preconditions", boom)

        with pytest.raises(deploy_local.DeploymentError, match="STOP"):
            deploy_local.update_local(
                env="staging", profile="p", reset_database=True
            )

        captured = capsys.readouterr()
        assert "--reset-db is a no-op for branching envs" in captured.out
```

(Add `from unittest.mock import MagicMock` at the top of the file if not already imported.)

- [ ] **Step 12.2: Run the test**

```
pytest tests/unit/test_deploy_local_config_branching.py::TestResetDbNoopWarning -v
```

Expected: passes (warning behaviour is already implemented in Task 10).

- [ ] **Step 12.3: Commit**

```
git add tests/unit/test_deploy_local_config_branching.py
git commit -m "test(deploy): verify --reset-db prints warning for branching envs"
```

---

## Task 13: Update `config/deployment.yaml`

**Files:**
- Modify: `config/deployment.yaml` — staging entry.

**What this task does:** Switches staging to branching mode. No tests (config file).

### Steps

- [ ] **Step 13.1: Edit `config/deployment.yaml`**

Replace the current `staging:` block (lines 5–21) with:

```yaml
  staging:
    app_name: "db-tellr-staging"
    description: "AI Slide Generator - Staging (ephemeral branch of prod)"
    workspace_path: "/Workspace/Users/robert.whiffin@databricks.com/.apps/staging/tellr"
    permissions:
      - user_name: "robert.whiffin@databricks.com"
        permission_level: "CAN_MANAGE"
    compute_size: "MEDIUM"  # Options: MEDIUM, LARGE, LIQUID
    env_vars:
      ENVIRONMENT: "staging"
      LOG_LEVEL: "DEBUG"
      LAKEBASE_INSTANCE: "db-tellr"
      # LAKEBASE_SCHEMA derived from branch_from env — not set here
    lakebase:
      database_name: "db-tellr"
      branch_from: "production"   # ephemeral branch of production on every deploy
      capacity: "CU_1"
      # schema omitted — inherited from production env
```

- [ ] **Step 13.2: Sanity-check load_deployment_config against the real file**

```
python -c "from scripts.deploy_local import load_deployment_config; import json; print(json.dumps(load_deployment_config('staging'), indent=2))"
```

Expected output contains:
```
"schema_name": "app_data_prod",
"branch_from_env": "production",
"branch_from_workspace_path": "/Workspace/Users/robert.whiffin@databricks.com/.apps/prod/tellr"
```

And:
```
python -c "from scripts.deploy_local import load_deployment_config; import json; print(json.dumps(load_deployment_config('development'), indent=2))"
```

Expected: `"schema_name": "tellr_app_data_dev"`, `"branch_from_env": null`.

- [ ] **Step 13.3: Commit**

```
git add config/deployment.yaml
git commit -m "feat(config): switch staging env to Lakebase branch_from production"
```

---

## Task 14: Manual integration test — verify against real workspace

**Files:** none modified. Records evidence in the PR body / commit message.

**What this task does:** Execute the integration checklist from the spec (§Testing → Integration) against the real Databricks workspace. Unit tests don't cover the SDK contract for Lakebase branch creation — only a live deploy does.

### Steps

- [ ] **Step 14.1: Run baseline — dev untouched**

```
./scripts/deploy_local.sh update --env development --profile <profile>
```

Expected: deploys successfully. Confirms non-branching path is unaffected.

- [ ] **Step 14.2: Staging first deploy**

If a staging app already exists with the old schema config, delete it first:

```
./scripts/deploy_local.sh delete --env staging --profile <profile>
```

Then create fresh:

```
./scripts/deploy_local.sh create --env staging --profile <profile>
```

Verify:
- In the Databricks UI → Lakebase → `db-tellr` → branches, you see `staging` as a child of `production`.
- In the Databricks UI → Workspace → `/Workspace/Users/.../.apps/staging/tellr/app.yaml`, `LAKEBASE_SCHEMA=app_data_prod`, `GOOGLE_OAUTH_ENCRYPTION_KEY=` matches prod's value, and `LAKEBASE_PG_HOST` is the staging branch's host (differs from prod's host).
- Log in to the staging app URL. You see your own prod sessions / slide decks.
- If you had a Google OAuth credential configured in prod, it still works in staging (encryption key matches).

- [ ] **Step 14.3: Staging update — confirms branch is recreated**

Record the current `branches/staging` `create_time` via the Lakebase UI, then:

```
./scripts/deploy_local.sh update --env staging --profile <profile>
```

Verify:
- `branches/staging` now has a newer `create_time`.
- Any test data you wrote in Step 14.2 is gone (you see a fresh copy of current prod).

- [ ] **Step 14.4: `--reset-db` warning**

```
./scripts/deploy_local.sh update --env staging --profile <profile> --reset-db
```

Verify: stdout contains `WARNING: --reset-db is a no-op for branching envs`. Deploy still succeeds.

- [ ] **Step 14.5: Staging delete — confirms branch cleanup**

```
./scripts/deploy_local.sh delete --env staging --profile <profile>
```

Verify:
- Staging app is gone.
- `branches/staging` is gone from the Lakebase UI.
- `branches/production` is untouched.

- [ ] **Step 14.6: Precondition failure — prod not deployed**

Temporarily rename the prod app.yaml (via the Databricks UI or API) to simulate "prod not deployed":

```
# (UI: rename /Workspace/.../.apps/prod/tellr/app.yaml to app.yaml.bak)
./scripts/deploy_local.sh update --env staging --profile <profile>
```

Expected: fails at preflight with `production not deployed — deploy production first`. Run `ws.postgres` audit log or observe that no `branches/staging` was created during the failed run.

Restore the renamed file.

- [ ] **Step 14.7: Production untouched sanity check**

Throughout 14.2–14.6, confirm the production app URL keeps returning 200 and continues to serve real users. No unexpected deploys were triggered against `db-tellr-prod`.

- [ ] **Step 14.8: Commit evidence to PR body**

Paste a compact summary of the results from steps 14.1–14.7 into the PR body when opening the branch for review. No code changes.

---

## Post-implementation: open PR

- [ ] **Final step: open PR with evidence**

```
git push -u origin <branch-name>
gh pr create --title "Lakebase branching: staging deploys against ephemeral prod branch" --body "$(cat <<'EOF'
## Summary
- Adds `lakebase.branch_from` field to `config/deployment.yaml`; staging now uses `branch_from: production`.
- On every `deploy_local.sh create|update --env staging`, recreates an ephemeral Lakebase branch `staging` forked from `branches/production`. Staging app reads schema `app_data_prod` with prod's encryption key.
- On `delete --env staging`, also deletes the branch. `--reset-db` on branching envs is a no-op with a warning.
- Prod/dev deploys unchanged.

Design: `docs/superpowers/specs/2026-04-24-lakebase-branching-staging-design.md`
Plan:   `docs/superpowers/plans/2026-04-24-lakebase-branching-staging.md`

## Test plan
- [x] Unit tests: config resolution (5), branch helpers (11), preflight (6), warning (1).
- [x] Regression: `test_deploy_autoscaling.py` passes with the new `branch_name` kwargs.
- [x] Integration checklist §Task 14: steps 14.1–14.7 executed against workspace <profile>. Evidence: <paste per-step notes>.

This pull request and its description were written by Isaac.
EOF
)"
```

---

## Self-review (performed after plan was written)

**Spec coverage:**
- §Configuration → Task 1 (resolution) + Task 13 (yaml change). ✓
- §Deployment flow (create) → Task 9. ✓
- §Deployment flow (update) → Task 10. ✓
- §Deployment flow (delete) → Task 11. ✓
- §Deployment flow (--reset-db warning) → Task 10 (impl) + Task 12 (test). ✓
- §Code changes (modified helpers) → Tasks 6, 7. ✓
- §Code changes (new helpers in deploy.py) → Tasks 2, 3, 4, 5. ✓
- §Code changes (new helper in deploy_local.py: `_load_branch_source_config`) → Task 1. ✓
- §Code changes (modified flow fns) → Tasks 1, 9, 10, 11. ✓
- §Error handling preconditions (6) → Task 8 tests cover all 6. ✓
- §Error handling runtime failures → covered by existing SDK operation.wait() semantics; idempotent delete in Task 3; timeout in Task 4.
- §Testing unit tests → Tasks 1, 2-5, 8, 12. ✓
- §Testing regression → Task 7.5 + runs in Tasks 9.2, 10.2, 11.2. ✓
- §Testing integration → Task 14. ✓

**Type consistency check:**
- `_branch_exists` returns `bool` — consumers (Task 8 preflight) use it as bool. ✓
- `_create_branch_from` returns lakebase_result-shaped dict — consumers (`_recreate_ephemeral_branch`, `create_local`/`update_local`) pass it to `_write_app_yaml`/`_setup_database_schema` which already accept that shape. ✓
- `_recreate_ephemeral_branch` kwargs: `ws, project_name, source_branch, target_branch`. Callers in Tasks 9 & 10 use those exact names. ✓
- `_ensure_sp_autoscaling_role` new kwarg `branch_name` — used in Tasks 9 & 10. ✓
- `_get_or_create_lakebase_autoscaling` new kwarg `branch_name` — unused by this feature (branching flow goes through `_create_branch_from` instead), but added for parity so future work can fetch endpoint info for arbitrary branches without another modification.
- `_check_branching_preconditions` returns `str` (the encryption key). Callers in Tasks 9 & 10 bind its return value as `encryption_key`. ✓

**No placeholders:** scanned — every step has concrete code and commands.

**Scope:** single feature, one PR, ~14 tasks, ~65 steps. Right size.

# Devloop Per-Instance Branching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `--instance <id>` flag to the dev-deploy tooling so each concurrent agentic dev loop gets an isolated app (`db-tellr-dev-<id>`) backed by its own fresh copy-on-write branch of production Lakebase (`dev-<id>`), created via delete-then-recreate on a fixed name.

**Architecture:** Reuse the existing `branch_from` machinery built for the staging design. Two changes: (1) make branch creation use a fixed branch id via delete-then-create instead of timestamp-suffix + TTL-for-freshness (a live probe proved fixed-name reuse is clean); (2) thread an `--instance` identifier through `deploy_local` that derives the app name, workspace path, and target branch name. The app compute is created once and reused; the branch is refreshed every deploy.

**Tech Stack:** Python 3, argparse, bash, pytest, Databricks SDK (`ws.postgres.*`), PyYAML.

## Global Constraints

- Branch ids must be 1–63 chars (Lakebase limit). `--instance` is validated `^[a-z][a-z0-9-]*$` and ≤59 chars so `dev-<id>` ≤63.
- `--instance` is only valid for a branching env (one whose `lakebase.branch_from` is set); otherwise fail fast with `DeploymentError`.
- Backward compatibility: when `--instance` is absent, behavior is unchanged except the branch is now a fixed env-named branch (e.g. `staging`) created via delete+create rather than `staging-<timestamp>`.
- `replace_existing` is NOT used (it preserves data; a live probe confirmed it is not a fresh fork).
- This plan implements the **branch mechanism only**. Migrations that `ALTER` inherited prod tables remain blocked by the separate Lakebase table-ownership workstream (see the spec's dependency section). Do not attempt ownership/group changes here.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- Run tests with the project venv: `source .venv/bin/activate` then `pytest`.

**Spec:** `docs/superpowers/specs/2026-06-29-devloop-instance-branching-design.md`

---

## File Structure

- `packages/databricks-tellr/databricks_tellr/deploy.py` — branch helpers: `_create_branch_from`, `_recreate_ephemeral_branch` (change to fixed-name delete+create).
- `scripts/deploy_local.py` — add `_validate_instance` + `_resolve_target` helpers; thread `instance` through `create_local`/`update_local`/`delete_local`; add `--instance` CLI arg; delete the branch on `delete`.
- `scripts/deploy_local.sh` — parse/forward `--instance`; allow `devloop` env.
- `config/deployment.example.yaml` — add the `devloop` template env (committed example; the real `config/deployment.yaml` is gitignored and updated by hand).
- `.github/workflows/publish-dev.yml` — deploy summary prints the `--env devloop --instance` form.
- `docs/technical/dev-deploy.md`, `.claude/skills/deploy-tellr-dev/SKILL.md` — document the instance loop.
- Tests: `tests/unit/test_deploy_branch_helpers.py` (update), `tests/unit/test_deploy_local_instance.py` (new).

---

### Task 1: Fixed-name branch creation in `_create_branch_from`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:1129-1210`
- Test: `tests/unit/test_deploy_branch_helpers.py:70-140`

**Interfaces:**
- Produces: `_create_branch_from(ws, project_name: str, source_branch: str, branch_id: str) -> dict` — creates `projects/<project>/branches/<branch_id>` forked from `source_branch`, with a 1-day TTL backstop, polls for a ready endpoint, returns a `lakebase_result` dict whose `branch_id` equals the passed `branch_id` verbatim (no timestamp suffix).

- [ ] **Step 1: Update the test to expect a verbatim fixed branch id**

Replace the body of `test_creates_branch_with_correct_source` in `tests/unit/test_deploy_branch_helpers.py` (currently lines ~71-126) with:

```python
    def test_creates_branch_with_correct_source(self, mock_ws):
        branch_id = "dev-agent-7f3a"

        create_op = MagicMock()
        mock_ws.postgres.create_branch.return_value = create_op

        endpoint_ready = MagicMock()
        endpoint_ready.name = (
            f"projects/db-tellr/branches/{branch_id}/endpoints/ep1"
        )
        endpoint_ready.status = MagicMock(
            hosts=MagicMock(host="dev-ep1.example.com")
        )
        mock_ws.postgres.list_endpoints.side_effect = (
            lambda **kw: iter([endpoint_ready])
        )

        result = _create_branch_from(
            mock_ws,
            project_name="db-tellr",
            source_branch="production",
            branch_id=branch_id,
        )

        call_kwargs = mock_ws.postgres.create_branch.call_args.kwargs
        assert call_kwargs["parent"] == "projects/db-tellr"
        # branch_id is used verbatim — no timestamp suffix.
        assert call_kwargs["branch_id"] == branch_id
        branch_arg = call_kwargs["branch"]
        assert branch_arg.spec.source_branch == "projects/db-tellr/branches/production"
        # TTL remains as an orphan backstop (not the freshness mechanism).
        assert branch_arg.spec.ttl is not None
        assert branch_arg.spec.ttl.seconds == 86400
        assert not branch_arg.spec.no_expiry

        create_op.wait.assert_called_once()

        assert result["type"] == "autoscaling"
        assert result["name"] == "db-tellr"
        assert result["host"] == "dev-ep1.example.com"
        assert (
            result["endpoint_name"]
            == f"projects/db-tellr/branches/{branch_id}/endpoints/ep1"
        )
        assert result["project_id"] == "db-tellr"
        assert result["instance_name"] is None
        assert result["branch_id"] == branch_id
```

Also update `test_raises_when_no_endpoint_after_timeout` (last line) to call with a fixed id:

```python
        with pytest.raises(DeploymentError, match="no endpoint ready"):
            _create_branch_from(mock_ws, "db-tellr", "production", "dev-x")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_branch_helpers.py::TestCreateBranchFrom -v`
Expected: FAIL — old code names the param `target_branch_prefix` and appends a timestamp, so `branch_id` kwarg mismatch / `TypeError` on the `branch_id=` keyword.

- [ ] **Step 3: Implement fixed-name creation**

In `packages/databricks-tellr/databricks_tellr/deploy.py`, change the signature and body of `_create_branch_from` (lines ~1129-1175). Replace:

```python
def _create_branch_from(
    ws: WorkspaceClient,
    project_name: str,
    source_branch: str,
    target_branch_prefix: str,
) -> dict[str, Any]:
```

with:

```python
def _create_branch_from(
    ws: WorkspaceClient,
    project_name: str,
    source_branch: str,
    branch_id: str,
) -> dict[str, Any]:
```

Update the docstring's first paragraph to:

```python
    """Create a new Lakebase branch named ``branch_id`` as a child of
    ``source_branch``.

    The branch id is used verbatim (a fixed per-instance name). A 1-day TTL is
    attached purely as an orphan backstop so abandoned instances get
    garbage-collected; freshness comes from delete-then-create (see
    _recreate_ephemeral_branch), not from the TTL.

    Waits on the create operation, then polls list_endpoints on the new branch
    until an endpoint with a populated host appears. Raises DeploymentError on
    timeout. Returns a lakebase_result-shaped dict with an added ``branch_id``.
    """
```

Then delete the line that builds the timestamped id:

```python
    branch_id = f"{target_branch_prefix}-{int(time.time())}"
```

(The rest of the function already references `branch_id` and works unchanged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_branch_helpers.py::TestCreateBranchFrom -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_branch_helpers.py
git commit -m "refactor(deploy): _create_branch_from uses a fixed verbatim branch id

Co-authored-by: Isaac"
```

---

### Task 2: Delete-then-create in `_recreate_ephemeral_branch`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:1213-1227`
- Test: `tests/unit/test_deploy_branch_helpers.py:143-172`

**Interfaces:**
- Consumes: `_delete_branch(ws, project_name, branch_id)`, `_create_branch_from(ws, project_name, source_branch, branch_id)` (Task 1).
- Produces: `_recreate_ephemeral_branch(ws, project_name: str, source_branch: str, branch_id: str) -> dict` — deletes `branch_id` (idempotent) then re-creates it fresh from `source_branch`. Returns the `_create_branch_from` result.

- [ ] **Step 1: Replace the test to assert delete-then-create**

Replace `TestRecreateEphemeralBranch` in `tests/unit/test_deploy_branch_helpers.py` (lines ~146-172) with:

```python
class TestRecreateEphemeralBranch:
    def test_deletes_then_creates_fixed_name(self, mock_ws, monkeypatch):
        """Fresh copy each deploy = delete the fixed branch, then recreate it."""
        calls = []

        def fake_delete(ws, project, branch):
            calls.append(("delete", branch))

        def fake_create(ws, project, source, branch_id):
            calls.append(("create", source, branch_id))
            return {"host": "x", "endpoint_name": "e", "type": "autoscaling",
                    "branch_id": branch_id}

        monkeypatch.setattr("databricks_tellr.deploy._delete_branch", fake_delete)
        monkeypatch.setattr("databricks_tellr.deploy._create_branch_from", fake_create)

        result = _recreate_ephemeral_branch(
            mock_ws,
            project_name="db-tellr",
            source_branch="production",
            branch_id="dev-agent-7f3a",
        )

        assert calls == [
            ("delete", "dev-agent-7f3a"),
            ("create", "production", "dev-agent-7f3a"),
        ]
        assert result["host"] == "x"
        assert result["branch_id"] == "dev-agent-7f3a"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_branch_helpers.py::TestRecreateEphemeralBranch -v`
Expected: FAIL — current code only creates (no delete) and uses `target_branch_prefix`.

- [ ] **Step 3: Implement delete-then-create**

In `deploy.py`, replace the whole `_recreate_ephemeral_branch` function (lines ~1213-1227) with:

```python
def _recreate_ephemeral_branch(
    ws: WorkspaceClient,
    project_name: str,
    source_branch: str,
    branch_id: str,
) -> dict[str, Any]:
    """Refresh an ephemeral Lakebase branch to a fresh copy of source_branch.

    Deletes ``branch_id`` (idempotent — no-op if absent) then recreates it from
    ``source_branch``. Delete-then-create on a fixed name was verified clean
    (~6s, no collision); the older "skip delete and rely on TTL" workaround is
    no longer needed.
    """
    _delete_branch(ws, project_name, branch_id)
    return _create_branch_from(ws, project_name, source_branch, branch_id)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_branch_helpers.py -v`
Expected: PASS (all classes in the file)

- [ ] **Step 5: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/deploy.py tests/unit/test_deploy_branch_helpers.py
git commit -m "refactor(deploy): _recreate_ephemeral_branch does delete-then-create on a fixed name

Co-authored-by: Isaac"
```

---

### Task 3: `--instance` helpers in deploy_local

**Files:**
- Modify: `scripts/deploy_local.py` (imports near line 15-23; add helpers after `load_deployment_config`, ~line 140)
- Test: `tests/unit/test_deploy_local_instance.py` (create)

**Interfaces:**
- Produces:
  - `_validate_instance(instance: str) -> None` — raises `DeploymentError` unless `instance` matches `^[a-z][a-z0-9-]*$` and is ≤59 chars.
  - `_resolve_target(config: dict, env: str, instance: Optional[str]) -> tuple[str, str, str]` — returns `(app_name, workspace_path, target_branch)`. No instance → `(config["app_name"], config["workspace_path"], env)`. With instance → requires `config["branch_from_env"]` set (else `DeploymentError`), validates the slug, returns `(f"{app_name}-{instance}", f"{workspace_path}/{instance}", f"dev-{instance}")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_deploy_local_instance.py`:

```python
"""Tests for --instance resolution + validation in deploy_local."""
import pytest

from databricks_tellr.deploy import DeploymentError
from scripts.deploy_local import _validate_instance, _resolve_target

BRANCHING = {
    "app_name": "db-tellr-dev",
    "workspace_path": "/Workspace/Users/x/.apps/devloop",
    "branch_from_env": "production",
}
NON_BRANCHING = {
    "app_name": "db-tellr-dev",
    "workspace_path": "/Workspace/Users/x/.apps/dev",
    "branch_from_env": None,
}


class TestValidateInstance:
    @pytest.mark.parametrize("good", ["agent-7f3a", "a", "spike01", "x-1-2-3"])
    def test_accepts_valid(self, good):
        _validate_instance(good)  # no raise

    @pytest.mark.parametrize("bad", ["Agent", "1abc", "has_underscore", "has.dot",
                                     "trailing ", "UPPER", "a" * 60])
    def test_rejects_invalid(self, bad):
        with pytest.raises(DeploymentError):
            _validate_instance(bad)


class TestResolveTarget:
    def test_no_instance_uses_env_branch(self):
        app, wp, branch = _resolve_target(BRANCHING, "staging", None)
        assert app == "db-tellr-dev"
        assert wp == "/Workspace/Users/x/.apps/devloop"
        assert branch == "staging"

    def test_instance_suffixes_names_and_dev_branch(self):
        app, wp, branch = _resolve_target(BRANCHING, "devloop", "agent-7f3a")
        assert app == "db-tellr-dev-agent-7f3a"
        assert wp == "/Workspace/Users/x/.apps/devloop/agent-7f3a"
        assert branch == "dev-agent-7f3a"

    def test_instance_on_non_branching_raises(self):
        with pytest.raises(DeploymentError, match="branch_from"):
            _resolve_target(NON_BRANCHING, "development", "agent-7f3a")

    def test_instance_invalid_slug_raises(self):
        with pytest.raises(DeploymentError):
            _resolve_target(BRANCHING, "devloop", "Bad_Id")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_local_instance.py -v`
Expected: FAIL — `ImportError: cannot import name '_validate_instance'`.

- [ ] **Step 3: Add `re` import and the helpers**

In `scripts/deploy_local.py`, add `import re` to the stdlib import block (after `import os`, line ~16).

Then add these two helpers immediately after `load_deployment_config` (after line ~139):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_local_instance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_local.py tests/unit/test_deploy_local_instance.py
git commit -m "feat(deploy): add _validate_instance + _resolve_target helpers

Co-authored-by: Isaac"
```

---

### Task 4: Thread `instance` through create/update/delete

**Files:**
- Modify: `scripts/deploy_local.py` — imports (line ~32-52), `create_local` (~263-442), `update_local` (~445-621), `delete_local` (~624-649)
- Test: `tests/unit/test_deploy_local_instance.py` (add a delete_local test)

**Interfaces:**
- Consumes: `_resolve_target` (Task 3), `_delete_branch`, `_get_workspace_client`, `delete` (already importable from `databricks_tellr.deploy`).
- Produces: `create_local(env, profile, seed_databricks_defaults=True, from_pypi=None, instance=None)`, `update_local(env, profile, reset_database=False, seed_databricks_defaults=True, from_pypi=None, instance=None)`, `delete_local(env, profile, reset_database=False, instance=None)`. On a branching env, `delete_local` now also deletes `branches/<target_branch>`.

- [ ] **Step 1: Add the `_delete_branch` import**

In `scripts/deploy_local.py`, add `_delete_branch,` to the `from databricks_tellr.deploy import (...)` block (alongside `_branch_exists`, near line 34):

```python
    _branch_exists,
    _delete_branch,
```

- [ ] **Step 2: Write the failing delete_local test**

Append to `tests/unit/test_deploy_local_instance.py`:

```python
from unittest.mock import MagicMock, patch


class TestDeleteLocalBranch:
    def test_deletes_app_and_instance_branch(self, monkeypatch):
        import scripts.deploy_local as dl

        cfg = {
            "app_name": "db-tellr-dev",
            "workspace_path": "/Workspace/Users/x/.apps/devloop",
            "lakebase_name": "db-tellr",
            "schema_name": "app_data_prod",
            "branch_from_env": "production",
        }
        monkeypatch.setattr(dl, "load_deployment_config", lambda env: cfg)
        fake_ws = MagicMock()
        monkeypatch.setattr(dl, "_get_workspace_client", lambda profile: fake_ws)
        delete_calls = {}
        monkeypatch.setattr(dl, "delete", lambda **kw: delete_calls.update(kw) or {"status": "deleted"})
        branch_calls = []
        monkeypatch.setattr(dl, "_delete_branch", lambda ws, proj, br: branch_calls.append((proj, br)))

        dl.delete_local(env="devloop", profile="p", instance="agent-7f3a")

        # App deleted under the instance-suffixed name
        assert delete_calls["app_name"] == "db-tellr-dev-agent-7f3a"
        # Branch deleted with the fixed dev-<instance> name
        assert branch_calls == [("db-tellr", "dev-agent-7f3a")]

    def test_non_branching_delete_does_not_touch_branches(self, monkeypatch):
        import scripts.deploy_local as dl

        cfg = {
            "app_name": "db-tellr-dev",
            "workspace_path": "/Workspace/Users/x/.apps/dev",
            "lakebase_name": "db-tellr",
            "schema_name": "tellr_app_data_dev",
            "branch_from_env": None,
        }
        monkeypatch.setattr(dl, "load_deployment_config", lambda env: cfg)
        monkeypatch.setattr(dl, "delete", lambda **kw: {"status": "deleted"})
        branch_calls = []
        monkeypatch.setattr(dl, "_delete_branch", lambda ws, proj, br: branch_calls.append((proj, br)))

        dl.delete_local(env="development", profile="p")
        assert branch_calls == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_local_instance.py::TestDeleteLocalBranch -v`
Expected: FAIL — `delete_local` has no `instance` kwarg and never calls `_delete_branch`.

- [ ] **Step 4: Update `delete_local`**

Replace the whole `delete_local` function (lines ~624-649) with:

```python
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
```

- [ ] **Step 5: Run the delete test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_local_instance.py::TestDeleteLocalBranch -v`
Expected: PASS

- [ ] **Step 6: Update `create_local` for instance + target_branch**

In `create_local`, add `instance: Optional[str] = None,` as the last parameter (after `from_pypi`, line ~267).

Replace these two lines (~285-286):

```python
    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
```

with:

```python
    app_name, workspace_path, target_branch = _resolve_target(config, env, instance)
```

Update the branching print (line ~297) from:

```python
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{env}')")
```

to:

```python
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{target_branch}')")
```

Update the recreate call (lines ~326-329) from:

```python
            print(f"Creating ephemeral branch off '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, env
            )
```

to:

```python
            print(f"Creating ephemeral branch '{target_branch}' off '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, target_branch
            )
```

- [ ] **Step 7: Update `update_local` for instance + target_branch**

In `update_local`, add `instance: Optional[str] = None,` as the last parameter (after `from_pypi`, line ~450).

Replace these two lines (~460-461):

```python
    app_name = config["app_name"]
    workspace_path = config["workspace_path"]
```

with:

```python
    app_name, workspace_path, target_branch = _resolve_target(config, env, instance)
```

Update the branching print (line ~475) from `'{env}'` to `'{target_branch}'`:

```python
        print(f"   Branching from: {branch_from_env} (ephemeral branch '{target_branch}')")
```

Update the recreate call (lines ~495-498) from:

```python
            print(f"Recreating ephemeral branch '{env}' from '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, env
            )
```

to:

```python
            print(f"Recreating ephemeral branch '{target_branch}' from '{branch_from_env}'...")
            lakebase_result = _recreate_ephemeral_branch(
                ws, lakebase_name, branch_from_env, target_branch
            )
```

- [ ] **Step 8: Run the full deploy_local test suite**

Run: `source .venv/bin/activate && pytest tests/unit/test_deploy_local_instance.py tests/unit/test_deploy_local_config_branching.py tests/unit/test_deploy_local_preflight.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add scripts/deploy_local.py tests/unit/test_deploy_local_instance.py
git commit -m "feat(deploy): thread --instance through create/update/delete_local

Co-authored-by: Isaac"
```

---

### Task 5: `--instance` CLI argument in `main()`

**Files:**
- Modify: `scripts/deploy_local.py` — `main()` (arg block ~716-726; dispatch ~748-769)

**Interfaces:**
- Consumes: `create_local`/`update_local`/`delete_local` `instance=` kwarg (Task 4).

- [ ] **Step 1: Add the `--instance` argument**

In `main()`, after the `--from-pypi` argument block (line ~726), add:

```python
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
```

- [ ] **Step 2: Pass `instance` into the dispatch calls**

Update the three calls (lines ~749-769) to pass `instance=args.instance`:

```python
        if args.action == "create":
            result = create_local(
                env=args.env,
                profile=args.profile,
                seed_databricks_defaults=args.include_databricks_prompts,
                from_pypi=args.from_pypi,
                instance=args.instance,
            )
        elif args.action == "update":
            result = update_local(
                env=args.env,
                profile=args.profile,
                reset_database=args.reset_db,
                seed_databricks_defaults=args.include_databricks_prompts,
                from_pypi=args.from_pypi,
                instance=args.instance,
            )
        elif args.action == "delete":
            result = delete_local(
                env=args.env,
                profile=args.profile,
                reset_database=args.reset_db,
                instance=args.instance,
            )
```

- [ ] **Step 3: Verify the CLI parses (smoke test)**

Run: `source .venv/bin/activate && python -m scripts.deploy_local --help`
Expected: help text lists `--instance ID`. Exit code 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy_local.py
git commit -m "feat(deploy): add --instance CLI arg to deploy_local

Co-authored-by: Isaac"
```

---

### Task 6: Forward `--instance` and allow `devloop` in the shell wrapper

**Files:**
- Modify: `scripts/deploy_local.sh` (arg parse ~52-100; env regex ~123; echo block ~141-158; python call ~201-212)

- [ ] **Step 1: Add the INSTANCE variable and parser case**

In `scripts/deploy_local.sh`, add `INSTANCE=""` to the variable block (after `FROM_PYPI=""`, line ~59). Then add a parser case (after the `--from-pypi` case, line ~90):

```bash
        --instance)
            INSTANCE="$2"
            shift 2
            ;;
```

- [ ] **Step 2: Allow the `devloop` (and `devtest`) envs**

Update the env validation regex (line ~123) from:

```bash
if [[ ! "$ENV" =~ ^(development|staging|production|test)$ ]]; then
```

to:

```bash
if [[ ! "$ENV" =~ ^(development|staging|production|test|devtest|devloop)$ ]]; then
```

- [ ] **Step 3: Echo the instance and forward it to Python**

In the echo block (after the `--from-pypi` echo, line ~157), add:

```bash
if [ -n "$INSTANCE" ]; then
    echo "  Instance:    $INSTANCE"
fi
```

Then update the python invocation (lines ~201-212). After the `FROM_PYPI_ARG` block, add:

```bash
INSTANCE_ARG=()
if [ -n "$INSTANCE" ]; then
    INSTANCE_ARG=(--instance "$INSTANCE")
fi
```

and add `"${INSTANCE_ARG[@]}"` to the `python -m scripts.deploy_local` call:

```bash
python -m scripts.deploy_local \
    --$ACTION \
    --env "$ENV" \
    --profile "$PROFILE" \
    $RESET_DB \
    $INCLUDE_DB_PROMPTS \
    "${FROM_PYPI_ARG[@]}" \
    "${INSTANCE_ARG[@]}"
```

- [ ] **Step 4: Smoke-test the usage path**

Run: `bash scripts/deploy_local.sh --help`
Expected: usage prints; exit 1 (its usage() exits 1 by design). Confirm no bash syntax error.

Run: `bash -n scripts/deploy_local.sh`
Expected: no output, exit 0 (syntax OK).

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_local.sh
git commit -m "feat(deploy): forward --instance and allow devloop env in deploy_local.sh

Co-authored-by: Isaac"
```

---

### Task 7: Add the `devloop` template env to the example config

**Files:**
- Modify: `config/deployment.example.yaml`

**Note:** The real `config/deployment.yaml` is gitignored. This task documents the env in the committed example; the operator mirrors it into their real config (see Step 3).

- [ ] **Step 1: Add the `devloop` env**

In `config/deployment.example.yaml`, under `environments:`, add (match the file's existing indentation and surrounding entries):

```yaml
  devloop:
    app_name: "ai-slide-generator-dev"            # base; --instance appended -> ...-<id>
    description: "AI Slide Generator - Dev loop (prod branch)"
    workspace_path: "/Workspace/Users/me@example.com/.apps/devloop"  # base; /<id> appended
    compute_size: "MEDIUM"
    env_vars:
      ENVIRONMENT: "development"
      LOG_LEVEL: "DEBUG"
      LAKEBASE_INSTANCE: "ai-slide-generator-db"
      # LAKEBASE_SCHEMA inherited from branch_from (prod schema) — not set here
    lakebase:
      database_name: "ai-slide-generator-db"      # MUST equal the production env's
      branch_from: "production"                    # fresh ephemeral branch per deploy
      capacity: "CU_1"
      # schema removed — inherited from the production env
```

- [ ] **Step 2: Verify the example parses as YAML**

Run: `source .venv/bin/activate && python -c "import yaml; yaml.safe_load(open('config/deployment.example.yaml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Mirror into the real config (manual, operator action)**

Add the same `devloop` block to the gitignored `config/deployment.yaml`, with the real `database_name: db-tellr`, the real prod `workspace_path` base, and `app_name: db-tellr-dev`. This is a local edit, not committed. (No code depends on it being present until a deploy is run.)

- [ ] **Step 4: Commit**

```bash
git add config/deployment.example.yaml
git commit -m "docs(deploy): add devloop template env to example config

Co-authored-by: Isaac"
```

---

### Task 8: Print the devloop instance loop in the publish-dev summary

**Files:**
- Modify: `.github/workflows/publish-dev.yml` (deploy-summary step, ~line 196-204)

- [ ] **Step 1: Add the devloop example to the summary**

In the "Write deploy summary" step, alongside the existing `deploy_local.sh ... --env devtest ...` echo (line ~204), add a devloop example. Replace the single echo line with:

```yaml
            echo "Static devtest:"
            echo "  ./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi ${RESOLVED_VERSION}"
            echo "Per-instance dev loop (prod branch):"
            echo "  ./scripts/deploy_local.sh create --env devloop --instance <id> --profile tellr-dev --from-pypi ${RESOLVED_VERSION}"
            echo "  ./scripts/deploy_local.sh update --env devloop --instance <id> --profile tellr-dev --from-pypi ${RESOLVED_VERSION}"
```

(Keep the surrounding `echo` lines and the `${RESOLVED_VERSION}` variable usage consistent with what's already in the step.)

- [ ] **Step 2: Verify the workflow YAML parses**

Run: `source .venv/bin/activate && python -c "import yaml; yaml.safe_load(open('.github/workflows/publish-dev.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/publish-dev.yml
git commit -m "ci(devops): print devloop --instance loop in publish-dev summary

Co-authored-by: Isaac"
```

---

### Task 9: Document the instance loop

**Files:**
- Modify: `docs/technical/dev-deploy.md`
- Modify: `.claude/skills/deploy-tellr-dev/SKILL.md`

- [ ] **Step 1: Add a "Per-instance dev loop" section to dev-deploy.md**

Append to `docs/technical/dev-deploy.md`:

```markdown
## Per-instance dev loop (`devloop`) — branch off prod

For agentic dev loops that run multiple deployments at once, use the `devloop`
env with an `--instance <id>`. Each instance gets its own app
(`db-tellr-dev-<id>`) and a fresh copy-on-write branch of production Lakebase
(`branches/dev-<id>`), recreated on every deploy:

```bash
gh workflow run publish-dev.yml          # publish the next .devN
./scripts/deploy_local.sh create --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>    # first deploy
./scripts/deploy_local.sh update --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>    # iterate (reuses app, refreshes branch)
./scripts/deploy_local.sh delete --env devloop --instance agent-7f3a \
    --profile tellr-dev                          # teardown (app + branch)
```

`--instance` must match `^[a-z][a-z0-9-]*$` and be ≤59 chars. Concurrent
instances are fully isolated. The app compute is created once and reused; the
branch is deleted and re-forked from prod on every deploy (fresh prod data each
time — anything written to an instance is wiped on its next deploy).

**Migration limitation:** an instance can create new tables and read/write prod
data, but a build that `ALTER`s an *inherited* prod table fails at startup with
`must be owner of table`. Fixing that needs the Lakebase table-ownership
(shared-owner) workstream — see
`docs/superpowers/specs/2026-06-29-devloop-instance-branching-design.md`.
```

- [ ] **Step 2: Add the instance loop to the deploy-tellr-dev skill**

In `.claude/skills/deploy-tellr-dev/SKILL.md`, add a short subsection mirroring the commands above (create/update/delete with `--env devloop --instance <id>`), and note the migration limitation in one line. Match the file's existing heading style.

- [ ] **Step 3: Commit**

```bash
git add docs/technical/dev-deploy.md .claude/skills/deploy-tellr-dev/SKILL.md
git commit -m "docs(deploy): document the devloop --instance dev loop

Co-authored-by: Isaac"
```

---

### Task 10: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit suite**

Run: `source .venv/bin/activate && pytest tests/unit -q`
Expected: PASS. Pay attention to `test_deploy_branch_helpers.py`, `test_deploy_local_config_branching.py`, `test_deploy_local_preflight.py`, `test_database_autoscaling.py`, `test_deploy_local_instance.py`.

- [ ] **Step 2: If any regression test asserts old branch behavior, fix it**

If `test_database_autoscaling.py` or another test references `target_branch_prefix` or timestamp-suffixed branch ids, update the assertion to the fixed-name behavior (branch id used verbatim; `_recreate_ephemeral_branch` deletes then creates). Re-run until green. Commit any such fix:

```bash
git add tests/unit/<file>.py
git commit -m "test: update branch assertions for fixed-name delete+create

Co-authored-by: Isaac"
```

- [ ] **Step 3: Manual integration checklist (against a real workspace; not automated)**

Perform the spec's integration tests:
1. `create --instance a` and `create --instance b` → two apps + two branches (`dev-a`, `dev-b`), both children of `branches/production`, isolated.
2. write a row in `a`, `update --instance a` with a newer version → row gone (branch re-forked), app URL unchanged (compute reused).
3. confirm prod sessions/decks visible and a prod Google OAuth credential decrypts.
4. `delete --instance a` → app and `branches/dev-a` gone; `branches/production` and `b` untouched.
5. `--instance FOO` (uppercase) → fails fast with the slug message, no `ws.postgres` call.
6. a build that adds a column to an existing table → fails at startup with `must be owner of table` (expected; confirms the ownership dependency is still needed).

---

## Self-Review

- **Spec coverage:** config (Task 7), `--instance` flag + validation (Tasks 3, 5, 6), naming derivation (Tasks 3, 4), branch mechanism delete+create fixed name (Tasks 1, 2), preflight (unchanged — already implemented), create/update/delete flows (Task 4), publish-dev summary (Task 8), docs (Task 9), unit + regression + manual integration tests (Tasks 1-4, 10). The ownership dependency is explicitly out of scope per the spec.
- **Placeholder scan:** none — every code step shows exact code; the only manual step (Task 7 Step 3, real gitignored config) is operator action by necessity, with exact values given.
- **Type consistency:** `_resolve_target` returns `(app_name, workspace_path, target_branch)` and is consumed identically in create/update/delete; `_recreate_ephemeral_branch` / `_create_branch_from` take `branch_id` (renamed from `target_branch_prefix`) consistently across deploy.py and all callers/tests.

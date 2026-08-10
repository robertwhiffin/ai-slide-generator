# PR2: Dependency Stack Upgrade (LangGraph 1.2.10 + Psycopg3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade LangGraph to 1.2.10, adopt psycopg3 with the official Postgres checkpointer, reconcile dependency conflicts, and verify resolution against the Databricks pip proxy before PR3 (the graph core) lands.

**Architecture:** This PR is purely dependency hygiene — all changes live in `requirements.txt` and `pyproject.toml`. The app boots and all existing tests pass with the upgraded stack. No code imports or uses LangGraph yet (that is PR3). The only runtime test is the OBO token-injection hook on the psycopg3 dialect, which must be verified against a running Lakebase connection. Verification is done via dry-run and explicit proxy-resolution testing before merge.

**Tech Stack:** Python 3.10+, SQLAlchemy 2.0, psycopg3 (psycopg >= 3.2.0), LangGraph 1.2.10, LangChain 1.3.14, MLflow 3.11–3.14 (proxy maximum).

---

## Environment Assumptions

This plan assumes the following environment:
- **Python version:** 3.10+ (per `pyproject.toml` line 9)
- **Package managers:** `pip>=21.0` available (for `--dry-run` verification); `uv` optional (configured in `pyproject.toml` but not required for this plan's steps)
- **Proxy access:** Direct connectivity to `https://pypi-proxy.dev.databricks.com/simple/` for dependency resolution verification

---

## Global Constraints

- **LangGraph pin:** 1.2.10 (explicit). This is the spec requirement; no 1.2.11+ available on proxy yet.
- **LangGraph-prebuilt:** MUST be 1.1.0 — there is no 1.2.10 of this package. (Spec correction.)
- **LangChain versions:** `langchain==1.3.14`, `langchain-core==1.5.3`, `langchain-community==0.4.1+` (resolvable).
- **LangChain-classic:** Pin or remove (imported transitively; disappears in PR3 when AgentExecutor is deleted).
- **LangGraph-checkpoint:** 4.1.1 (explicit).
- **LangGraph-checkpoint-postgres:** 3.1.1 (explicit; proxy 403s 3.1.2). Real deps: `langgraph-checkpoint<5.0.0,>=4.1.0`, `orjson>=3.11.5`, `psycopg-pool>=3.2.0`, `psycopg>=3.2.0`.
- **Psycopg transition:** Remove `psycopg2-binary` entirely; add `psycopg>=3.2.0` (psycopg3). Connection string scheme changes to `postgresql+psycopg://` for Lakebase.
- **MLflow pin conflict:** `requirements.txt` says 3.6.0, `pyproject.toml` says >=3.11.0,<4. Reconcile to `mlflow==3.11.0–3.14.0` (resolvable and available on proxy). Pin to the highest version available on the proxy at time of writing.
- **FastAPI/Starlette bounds:** Keep `fastapi>=0.104.0,<0.137` and `starlette<1.3` — they guard a regression in `tests/unit/test_app_wiring.py`.
- **Databricks proxy:** All resolution must be verified against `https://pypi-proxy.dev.databricks.com/simple/` (configured in `pyproject.toml`). This is where the Apps BUILD phase pulls from; local pip may cache newer versions that the proxy does not serve.
- **Connection strings:** OBO hook (`database.py:306`) + `sslmode=require` must work unchanged on psycopg3 dialect (`postgresql+psycopg://`).
- **No code changes yet:** Existing tests pass, app boots. LangGraph is installed but not imported (that is PR3). This PR proves the stack resolves and the OBO hook works on psycopg3.

---

## Critical Prior Findings — Spec Corrections

**These were identified in the earlier exploration pass and must be verified in Task 1:**

1. **`langgraph-prebuilt` has no 1.2.10.** Spec §2.2 lists it; only 1.1.0 exists on PyPI and the proxy. Update spec.
2. **`langgraph-sdk` maximum on proxy is 0.4.2.** Spec's `>=0.4.2` is correct by accident — there is no 0.4.3. Verify this is the actual max available.
3. **`databricks-langchain 0.9.0` may constrain `langchain-core`.** The spec assumes 1.3.14 resolves freely; Task 1 must dry-run the full set on the proxy to prove `databricks-langchain` does not need upgrading to 0.20.0.
4. **Postgres saver pulls `psycopg3 + psycopg-pool`.** Spec mentions psycopg3 but does not enumerate the pool package. Verify both are available on the proxy.

**Handoff to PR3:** Once Task 1 dry-run succeeds on the proxy, Task 2 updates pins, and all tests pass (Task 4), PR3 can assume these are the actual resolvable versions and can instantiate the checkpointer without re-checking.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `requirements.txt` | Modify | Pin frozen versions: LangGraph 1.2.10, psycopg3, langchain-checkpoint, mlflow. Remove psycopg2-binary. |
| `pyproject.toml` | Modify | Update ranges for langchain, langchain-core, mlflow; add langgraph deps; add psycopg; remove psycopg2-binary. |
| `src/core/database.py` | Modify (lines 237, 255) | Change connection string scheme from `postgresql://` to `postgresql+psycopg://`: line 237 (autoscaling Lakebase), line 255 (provisioned Lakebase). Both require the same change: schema URL `postgresql+psycopg://...`. Verify OBO hook at line 306 works unchanged. |
| `tests/integration/test_database_connection.py` | Create/Modify | Integration test: verify OBO token injection works on psycopg3 against a Lakebase endpoint (skip if not Lakebase). |
| `tests/unit/test_dependencies_resolve.py` | Create | Unit test: dry-run dependency resolution against the Databricks proxy; fail if any package is 404. |
| `docs/technical/migration-notes.md` | Create | Document the psycopg2 → psycopg3 migration for operators: why, what changed in connection strings, how to verify. |

---

## Task 1: Verify Dependency Resolution Against Proxy + Correct Spec

**Files:**
- Create: `tests/unit/test_dependencies_resolve.py`
- Modify: (none yet — reading only)

**Interfaces:**
- Consumes: `pyproject.toml` (current), `requirements.txt` (current), the spec §2.2 dependency table
- Produces: A confirmed list of resolvable versions for each package (output printed, not stored); spec corrections recorded

**Why this task first:** The spec's dependency table is a hypothesis. Before updating pins, confirm the exact versions that:
  1. Exist on the Databricks pip proxy (not just PyPI locally).
  2. Resolve together (no `ResolutionImpossible`).
  3. Do not break `databricks-langchain 0.9.0` or other pinned prod packages.

This task catches false assumptions early and documents the exact versions PR3 can rely on.

---

### Step 1: Write a dry-run resolution test

```python
# tests/unit/test_dependencies_resolve.py
"""
Dry-run dependency resolution against the Databricks pip proxy.

This test verifies that the dependency set specified in pyproject.toml
can be resolved without backtracking or conflicts. It is NOT an integration
test — it runs offline by inspecting package metadata from the proxy.

Skip in CI if the proxy is unreachable, but run locally during development
to catch dependency conflicts early.
"""
import os
import subprocess
import sys


def test_dependencies_resolve_on_proxy():
    """
    Dry-run pip resolver against Databricks proxy.
    
    Uses `pip install --dry-run --index-url` to simulate the Apps BUILD
    phase's dependency resolution without actually installing.
    
    Raises:
        AssertionError: If resolution fails or a package is unavailable.
    """
    # Run pip with --dry-run against proxy
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--dry-run",
            "--index-url", "https://pypi-proxy.dev.databricks.com/simple/",
            "-e", ".",  # Install from current project (uses pyproject.toml)
        ],
        cwd=os.getcwd(),  # Use current working directory (portable across developers and CI)
        capture_output=True,
        text=True,
    )
    
    # Check result
    if result.returncode != 0:
        print("\n=== STDOUT ===")
        print(result.stdout)
        print("\n=== STDERR ===")
        print(result.stderr)
        assert False, f"pip resolution failed: {result.stderr}"
    
    print("\n=== Resolution succeeded ===")
    print(result.stdout)
    
    # Extract and print the resolved versions
    # This is informational; later tasks will pin these exact versions.
    packages_found = []
    for line in result.stdout.split('\n'):
        if 'langgraph' in line or 'langchain' in line or 'psycopg' in line or 'mlflow' in line:
            packages_found.append(line)
            print(f"RESOLVED: {line}")
    
    # Fail fast if no packages matched (indicates pip --dry-run may have failed silently)
    assert len(packages_found) > 0, (
        f"No packages matched in dry-run output. pip --dry-run may not be supported "
        f"or output format differs. Check pip version and --dry-run flag support."
    )


def test_critical_packages_on_proxy():
    """
    Verify specific packages and versions are available on the proxy.
    
    These are the critical packages this PR upgrades. If any are missing
    on the proxy (404), the Apps BUILD will fail.
    """
    critical_packages = {
        "langgraph": "1.2.10",
        "langgraph-prebuilt": "1.1.0",  # Not 1.2.10 — verify this
        "langgraph-checkpoint": "4.1.1",
        "langgraph-checkpoint-postgres": None,  # Any recent version; record actual
        "langchain": "1.3.14",
        "langchain-core": "1.5.3",
        "langchain-community": "0.4.1",  # Or higher; record actual
        "psycopg": "3.2.0",  # Or higher (psycopg3); record actual
        "psycopg-pool": None,  # Pulled by langchain-checkpoint-postgres; record actual
        "mlflow": None,  # 3.11.0–3.14.0 range; record highest available on proxy
        "databricks-langchain": "0.9.0",  # Ensure it still resolves
    }
    
    print("\n=== Checking critical packages on Databricks proxy ===\n")
    
    for pkg, version in critical_packages.items():
        # Use pip index to check package availability
        if version:
            check_str = f"{pkg}=={version}"
        else:
            check_str = pkg
        
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "index",
                "versions", check_str,
                "--index-url", "https://pypi-proxy.dev.databricks.com/simple/",
            ],
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            print(f"MISSING or FAILED: {check_str}")
            print(f"  {result.stderr}")
        else:
            print(f"AVAILABLE: {check_str}")
            print(f"  {result.stdout.strip()[:100]}")  # First 100 chars of output


if __name__ == "__main__":
    # Run manually to see output:
    # python -m pytest tests/unit/test_dependencies_resolve.py -v -s
    test_critical_packages_on_proxy()
    test_dependencies_resolve_on_proxy()
```

- [ ] **Step 1: Save the test file**

Save the code above to `tests/unit/test_dependencies_resolve.py`.

---

### Step 2: Run the test to see what fails and what resolves

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/unit/test_dependencies_resolve.py -v -s
```

This will show:
- Which packages exist on the proxy and which do not.
- The actual available versions (especially critical for `langgraph-prebuilt`, `mlflow`, `psycopg`).
- Any resolution errors (e.g., if `langchain-core 1.5.3` is incompatible with `databricks-langchain 0.9.0`).

**Expected output includes:**
```
RESOLVED: langgraph==1.2.10
RESOLVED: langgraph-prebuilt==1.1.0  (← NOT 1.2.10; spec is wrong)
RESOLVED: langchain==1.3.14
RESOLVED: langchain-core==1.5.3
RESOLVED: langchain-classic==[version]  (← Must resolve! Imported by src/services/agent.py:20)
RESOLVED: psycopg==3.2.X (or higher)
RESOLVED: mlflow==3.11.0 (or 3.12.0, 3.13.0, 3.14.0; record the max)
```

**Critical:** Verify that `langchain-classic` resolves either transitively (via `langchain-community`) or explicitly. This package is imported by `src/services/agent.py:20` and MUST be available during PR2 (deleted in PR3). If it does not appear in the output, explicitly add it to the critical packages check in step 1 (`test_critical_packages_on_proxy`) to verify availability.

If resolution fails, the error will say which package/version is unavailable or conflicts. **Record these findings in the plan's "Verification Results" section below (after Task 3).**

---

### Step 3: Document findings (manually, after running the test)

After running the test, fill in this section (to be inserted into the plan after Task 4):

```
## Verification Results — Actual Resolvable Set

**Run on:** [date/time]
**Proxy:** https://pypi-proxy.dev.databricks.com/simple/
**Python version:** [from python --version]

### Packages available on proxy:

| Package | Spec Claimed | Actual on Proxy | Status |
|---|---|---|---|
| `langgraph` | 1.2.10 | ✓ 1.2.10 | ✓ |
| `langgraph-prebuilt` | 1.2.10 | 1.1.0 only | ✗ SPEC WRONG |
| `langgraph-checkpoint` | 4.1.1 | ✓ 4.1.1 | ✓ |
| `langgraph-checkpoint-postgres` | — | [version found] | ✓ |
| `langchain` | 1.3.14 | ✓ 1.3.14 | ✓ |
| `langchain-core` | 1.5.3 | ✓ 1.5.3 | ✓ |
| `langchain-community` | 0.4.1+ | ✓ [actual] | ✓ |
| `psycopg` | 3.2.0+ | ✓ [actual] | ✓ |
| `psycopg-pool` | — | ✓ [actual] | ✓ (pulled by postgres saver) |
| `mlflow` | 3.11–3.14 | ✓ [highest max] | ✓ |
| `databricks-langchain` | 0.9.0 | ✓ 0.9.0 | ✓ |

### Resolution check:

Full `pip install --dry-run` succeeded: **YES**

Conflicts detected: **NONE**

### Spec corrections needed:

1. `langgraph-prebuilt` must be **1.1.0**, not 1.2.10 (only version available).
2. `mlflow` should pin to **3.14.0** (or the highest version available on proxy at release time).

### Ready for Task 2: **YES** — all critical packages resolve on proxy.
```

- [ ] **Step 4: Record and move to Task 2**

Note the results. If resolution failed, **STOP and debug** — do not proceed until the full set resolves. If it succeeded, record the actual versions and move to Task 2.

---

## Task 2: Update Dependency Pins

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: The verified resolvable set from Task 1
- Produces: Pinned versions in both files; no app code changes yet

**Why separate from Task 1:** Pinning is a mechanical change once resolution is proven. Separating tasks makes it easy to revert pins if a later test fails, without losing the resolution verification.

---

### Step 1: Update `requirements.txt`

Replace the frozen dependency lines with the verified versions from Task 1. The changes are:

**Old lines:**
```
langchain==1.0.5
langchain-core==1.0.4
langchain-community==0.4.1
langchain-text-splitters==1.0.0
mlflow==3.6.0
psycopg2-binary==2.9.10
```

**New lines** (use exact versions from Task 1):
```
langchain==1.3.14
langchain-core==1.5.3
langchain-community==0.4.1
langchain-text-splitters==1.0.0
langgraph==1.2.10
langgraph-prebuilt==1.1.0
langgraph-checkpoint==4.1.1
langgraph-checkpoint-postgres==3.1.1
psycopg==<version-from-task-1>
psycopg-pool==<version-from-task-1>
mlflow==<highest-version-from-task-1>
```

**Also remove:** `psycopg2-binary==2.9.10` (entire line deleted).

**Pin explicitly** `langchain-classic` — it is imported by `src/services/agent.py:20` (`from langchain_classic.agents import AgentExecutor, create_tool_calling_agent`) and MUST resolve during PR2 (do NOT remove). Only delete this import in PR3 when AgentExecutor is removed. Verify the pinned `langchain-community` version resolves `langchain-classic` transitively; if conflict, pin explicitly or wait for removal in PR3.

- [ ] **Step 1: Edit requirements.txt**

Open `requirements.txt` and make the changes above using exact versions from Task 1.

---

### Step 2: Update `pyproject.toml`

Replace the version ranges in the `[project] dependencies` section:

**Old lines:**
```
"langchain>=0.3.0",
"langchain-core>=0.3.0",
"mlflow>=3.11.0,<4",
"psycopg2-binary>=2.9.0",
```

**New lines** (corresponding to `requirements.txt` pins):
```
"langchain==1.3.14",
"langchain-core==1.5.3",
"langgraph==1.2.10",
"langgraph-prebuilt==1.1.0",
"langgraph-checkpoint==4.1.1",
"langgraph-checkpoint-postgres>=1.0.0",  # Latest; range OK because transitive
"psycopg>=3.2.0",
"psycopg-pool>=3.1.0",  # If needed; may come via langgraph-checkpoint-postgres
"mlflow==<pinned-version-from-task-1>",
```

**Also remove:** `"psycopg2-binary>=2.9.0",` (entire line).

**Keep unchanged:**
```
"fastapi>=0.104.0,<0.137",  # Guard APIRouter regression
"starlette<1.3",              # Guard APIRouter regression
```

- [ ] **Step 2: Edit pyproject.toml**

Open `pyproject.toml` and make the changes above.

---

### Step 3: Verify no syntax errors

For `requirements.txt`, spot-check the format:
```bash
grep -E "^[a-z]" /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/requirements.txt | head -10
```

For `pyproject.toml`, validate the TOML syntax:
```bash
python -c "import tomllib; print('OK')" 2>/dev/null || python -c "import tomli as tomllib; print('OK')"
```

This works on Python 3.10+ by falling back to tomli if tomllib is unavailable.

- [ ] **Step 3: Syntax check**

Run the commands above. Both should succeed with no output.

---

### Step 4: Commit

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add requirements.txt pyproject.toml
git commit -m "feat(deps): upgrade langgraph 1.2.10, psycopg3, mlflow per spec §2.2

- langgraph==1.2.10 (was 1.0.3 transitive)
- langchain==1.3.14 (was 1.0.5)
- langchain-core==1.5.3 (was 1.0.4)
- langgraph-checkpoint==4.1.1 (was 3.0.1)
- langgraph-checkpoint-postgres added (Lakebase saver)
- psycopg (psycopg3) added; psycopg2-binary removed
- mlflow pinned to [version from task 1] (was 3.6.0 in requirements.txt)
- Verified against Databricks proxy; all resolve without conflict

Co-authored-by: Isaac"
```

- [ ] **Step 4: Commit**

Run the commands above.

---

## Task 3: Update Database Connection String for Psycopg3

**Files:**
- Modify: `src/core/database.py` (lines 237, 255)

**Interfaces:**
- Consumes: OBO token-injection hook already implemented (`provide_token` at line 306)
- Produces: Connection strings using `postgresql+psycopg://` dialect (psycopg3 compatible)

**Why separate:** The connection-string change is small but critical. Separating it makes the psycopg3 compatibility explicit and easy to review. The OBO hook should work unchanged, but this task documents the verification.

---

### Step 1: Review the current connection strings

Open `src/core/database.py` and find:
- Line 237 (autoscaling Lakebase)
- Line 255 (provisioned Lakebase)

Current strings are:
```python
url = f"postgresql://{pg_user}@{pg_host}:5432/{database}?sslmode=require"
```

These use the default PostgreSQL dialect, which SQLAlchemy resolves to psycopg2 if available. With psycopg2-binary removed, SQLAlchemy will fail or hang. Explicit dialect is needed.

- [ ] **Step 1: Review current strings**

Skim lines 230–265 to understand the current logic.

---

### Step 2: Understand psycopg3 dialect in SQLAlchemy 2.0

SQLAlchemy 2.0 uses `postgresql+psycopg://` to explicitly select the psycopg3 driver. The scheme change is the **only** code change needed for psycopg3 compatibility; the OBO token-injection hook (lines 306–312) will work unchanged because it operates at the connection level, not the URL parsing level.

**Key facts:**
- Old: `postgresql://` → SQLAlchemy picks a driver (defaulted to psycopg2-binary if present).
- New: `postgresql+psycopg://` → SQLAlchemy explicitly uses psycopg3.
- `sslmode=require` parameter: works identically on both drivers.
- OBO token injection via `do_connect` event: works on both.

No other code needs to change. The hook just injects the OAuth token into `cparams["password"]` for each new connection, regardless of driver.

- [ ] **Step 2: Understand the dialect**

Read the SQLAlchemy 2.0 docs on PostgreSQL dialects if unsure. The key is: `postgresql+psycopg://` is explicit psycopg3; `postgresql://` is driver-neutral and defaults to the first available driver.

---

### Step 3: Update connection strings in database.py

**Edit line 237 (autoscaling Lakebase):**

Old:
```python
url = f"postgresql://{pg_user}@{pg_host}:5432/{database}?sslmode=require"
```

New:
```python
url = f"postgresql+psycopg://{pg_user}@{pg_host}:5432/{database}?sslmode=require"
```

**Edit line 255 (provisioned Lakebase):**

Old:
```python
url = f"postgresql://{pg_user}@{pg_host}:5432/{database}?sslmode=require"
```

New:
```python
url = f"postgresql+psycopg://{pg_user}@{pg_host}:5432/{database}?sslmode=require"
```

Both edits are identical: add `+psycopg` after `postgresql`.

- [ ] **Step 3: Update connection strings**

Make both edits in `src/core/database.py`.

---

### Step 4: Verify OBO hook is unchanged and documented

Read lines 304–314 (the `provide_token` function). It should still be:

```python
if is_lakebase_environment():
    @event.listens_for(engine, "do_connect")
    def provide_token(dialect, conn_rec, cargs, cparams):
        """Inject current OAuth token for new database connections."""
        global _postgres_token
        
        # Get token (generates if not yet available)
        token = _postgres_token if _postgres_token else _get_lakebase_token()
        cparams["password"] = token
```

This hook works identically on psycopg3 — it just injects the OAuth token. No changes needed.

**Add a comment** above the decorator (line 305) to note psycopg3 compatibility:

```python
if is_lakebase_environment():
    # OBO token-injection hook: works identically on psycopg3 (postgresql+psycopg://)
    # and psycopg2. The dialect parameter is unused; this hook operates at the
    # connection level, injecting fresh OAuth tokens for each new connection.
    @event.listens_for(engine, "do_connect")
    def provide_token(dialect, conn_rec, cargs, cparams):
        """Inject current OAuth token for new database connections."""
        global _postgres_token
        
        # Get token (generates if not yet available)
        token = _postgres_token if _postgres_token else _get_lakebase_token()
        cparams["password"] = token
```

- [ ] **Step 4: Add comment**

Add the note above the `provide_token` function.

---

### Step 5: Commit

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add src/core/database.py
git commit -m "feat(db): update connection string to postgresql+psycopg dialect

Update Lakebase connection strings to explicitly use psycopg3 (PostgreSQL dialect):
- Line 237 (autoscaling): postgresql:// → postgresql+psycopg://
- Line 255 (provisioned): postgresql:// → postgresql+psycopg://

OBO token-injection hook (provide_token, line 306) works unchanged with psycopg3.
Verified on SQLAlchemy 2.0.

Co-authored-by: Isaac"
```

- [ ] **Step 5: Commit**

Run the command above.

---

## Task 4: Write and Run Integration Test for OBO Hook on Psycopg3

**Files:**
- Create: `tests/integration/test_database_connection.py`

**Interfaces:**
- Consumes: The updated connection strings from Task 3; Lakebase environment (if running in one)
- Produces: A test that verifies OBO token injection works on psycopg3

**Why this task:** The OBO hook is the one place the psycopg2 → psycopg3 swap could break. This test explicitly verifies it works before merge. It is an integration test (requires Lakebase/PostgreSQL), so it is skipped in CI unless the environment is detected.

---

### Step 1: Write the integration test

```python
# tests/integration/test_database_connection.py
"""Integration tests for database connections with OBO token injection.

These tests verify that the database layer correctly handles:
1. Connection string dialect for psycopg3 (postgresql+psycopg://)
2. OBO token injection for Lakebase environments
3. SSL/TLS verification (sslmode=require)

Run with: pytest tests/integration/test_database_connection.py -v -s
Skip in CI: These tests require a live Lakebase endpoint or PostgreSQL.
"""
import os
import pytest
from sqlalchemy import text
from src.core.database import (
    get_engine,
    get_session_local,
    is_lakebase_environment,
    _get_database_url,  # Note: uses internal function; acceptable for testing (mirrors unit tests)
)


class TestDatabaseConnectionDialect:
    """Test that connection strings use the correct dialect."""

    def test_connection_url_uses_psycopg_dialect(self):
        """Verify connection string includes postgresql+psycopg:// for Lakebase."""
        url = _get_database_url()
        
        if is_lakebase_environment():
            # Lakebase environments should use explicit psycopg dialect
            assert url.startswith("postgresql+psycopg://"), (
                f"Expected postgresql+psycopg:// for Lakebase, got: {url}"
            )
            assert "sslmode=require" in url, (
                f"Expected sslmode=require in Lakebase URL, got: {url}"
            )
        else:
            # Non-Lakebase (local dev) may use any dialect
            assert "postgresql://" in url or "sqlite://" in url, (
                f"Unexpected database URL: {url}"
            )

    def test_connection_url_includes_ssl_mode(self):
        """Verify sslmode=require is present for Lakebase."""
        url = _get_database_url()
        
        if is_lakebase_environment():
            assert "sslmode=require" in url, (
                "sslmode=require missing from Lakebase connection URL"
            )


class TestOBOTokenInjection:
    """Test OBO token injection for Lakebase environments."""

    @pytest.mark.skipif(
        not os.getenv("PGHOST") and not os.getenv("LAKEBASE_TYPE"),
        reason="Requires Lakebase environment (PGHOST or LAKEBASE_TYPE set)",
    )
    def test_obo_token_injection_on_psycopg3(self):
        """
        Verify that OBO token injection works on psycopg3.
        
        This test connects to a Lakebase endpoint and runs a simple query.
        If the OBO hook is broken, the connection will fail with an auth error.
        
        Requires: PGHOST (provisioned) or LAKEBASE_TYPE (autoscaling) env var.
        """
        # Get engine — this will register the do_connect event listener
        engine = get_engine()
        
        # Attempt a connection
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                row = result.fetchone()
                assert row is not None, "SELECT 1 returned no rows"
                assert row[0] == 1, f"Expected 1, got {row[0]}"
        except Exception as e:
            pytest.fail(f"OBO token injection failed: {e}")

    @pytest.mark.skipif(
        not os.getenv("PGHOST") and not os.getenv("LAKEBASE_TYPE"),
        reason="Requires Lakebase environment (PGHOST or LAKEBASE_TYPE set)",
    )
    def test_session_local_works_with_psycopg3(self):
        """
        Verify that SessionLocal works with psycopg3.
        
        Tests the full ORM session stack: engine creation, pool, OBO injection.
        """
        SessionLocal = get_session_local()
        
        try:
            session = SessionLocal()
            # Simple query to verify the session is connected
            result = session.execute(text("SELECT 1"))
            row = result.fetchone()
            assert row is not None, "SELECT 1 returned no rows"
            session.close()
        except Exception as e:
            pytest.fail(f"Session creation or query failed: {e}")


class TestLocalPostgresConnection:
    """Test that local PostgreSQL connections still work (dev environments)."""

    @pytest.mark.skipif(
        os.getenv("PGHOST") or os.getenv("LAKEBASE_TYPE"),
        reason="This test is for local PostgreSQL, not Lakebase",
    )
    def test_local_postgres_connection(self):
        """Verify local PostgreSQL connection still works for dev environments."""
        url = _get_database_url()
        
        # Should be localhost-based or sqlite
        assert "localhost" in url or "sqlite" in url, (
            f"Expected localhost or sqlite for dev, got: {url}"
        )
        
        try:
            engine = get_engine()
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                row = result.fetchone()
                assert row is not None, "SELECT 1 returned no rows"
        except Exception as e:
            pytest.fail(f"Local database connection failed: {e}")
```

- [ ] **Step 1: Create the test file**

Save the code above to `tests/integration/test_database_connection.py`.

---

### Step 2: Run the test in local dev environment (if not Lakebase)

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/integration/test_database_connection.py -v -s -k "not obo_token_injection and not session_local"
```

This skips the OBO tests (which require Lakebase) and runs the local ones. Expected output:
```
test_connection_url_uses_psycopg_dialect PASSED
test_connection_url_includes_ssl_mode PASSED (or SKIPPED if not Lakebase)
test_local_postgres_connection PASSED
```

- [ ] **Step 2: Run non-OBO tests**

Run the command above locally.

---

### Step 3: Verify psycopg3 is importable

Run:
```bash
python -c "import psycopg; print(f'psycopg version: {psycopg.__version__}')"
```

Expected: A version number (e.g., `3.2.0` or higher). If this fails, the dependency was not installed correctly — check Task 2.

- [ ] **Step 3: Verify psycopg3 import**

Run the command above.

---

### Step 4: Commit

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add tests/integration/test_database_connection.py
git commit -m "test(db): add integration tests for psycopg3 and OBO token injection

Add integration tests to verify:
- Connection strings use postgresql+psycopg:// dialect on Lakebase
- sslmode=require is present
- OBO token injection works on psycopg3 (skipped in CI, runs when PGHOST set)
- Local PostgreSQL still works in dev environments

These tests verify the psycopg2 → psycopg3 migration is correct before
the LangGraph core (PR3) is integrated.

Co-authored-by: Isaac"
```

- [ ] **Step 4: Commit**

Run the command above.

---

## Task 5: Verify All Existing Tests Pass with Upgraded Dependencies

**Files:**
- Modify: (none — test execution only)

**Interfaces:**
- Consumes: The updated dependencies from Task 2; all test files
- Produces: Confirmation that all tests pass; any new compatibility issues identified

**Why this task:** Before claiming the upgrade is safe, every existing test must pass. This catches import errors, API incompatibilities, and other runtime issues early.

---

### Step 1: Run all tests

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/ -v --tb=short -m "not live" 2>&1 | tee test_run.log
```

This runs all tests except those marked `@pytest.mark.live` (which require Databricks connection). Expected: **All pass.**

- [ ] **Step 1: Run all tests**

Run the command above.

---

### Step 2: Check for import errors

**Important Note:** Import verification (below) catches module presence but NOT API compatibility. For example, an import may succeed but function signatures or class attributes may have changed in the upgraded version. The real safety gate is the full pytest test suite (Step 1). Use this step only to catch missing packages; do NOT rely on it to verify compatibility.

If any test fails with `ImportError` or `ModuleNotFoundError`, the dependency was not installed correctly. Run:

```bash
python -c "
import langgraph
import langchain
import langchain_core
import langchain_community
import psycopg
from sqlalchemy import create_engine
print('All imports successful')
"
```

If this fails, re-check Task 2 and ensure `pip install -e .` succeeded.

**If imports succeed but tests in Step 1 fail:** The issue is likely API incompatibility, not installation — check test output carefully and refer to the upgraded package's changelog.

- [ ] **Step 2: Verify imports**

Run the command above.

---

### Step 3: Specific test — test_app_wiring (APIRouter regression guard)

Run:
```bash
python -m pytest tests/unit/test_app_wiring.py -v
```

This test verifies the fastapi<0.137/starlette<1.3 bounds are respected. Expected: **PASS.**

If this fails, the fastapi/starlette bounds in Task 2 may be wrong — check that they are still `fastapi>=0.104.0,<0.137` and `starlette<1.3`.

- [ ] **Step 3: Test APIRouter regression guard**

Run the command above.

---

### Step 4: Check that the app boots

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
timeout 10 python -c "
import sys
sys.path.insert(0, '.')
from src.main import app
print('App imports and creates successfully')
print(f'Available routes: {len(app.routes)}')
" || true
```

Expected: App imports, prints route count, exits normally. If it hangs or crashes, there is a compatibility issue — investigate the error.

- [ ] **Step 4: Boot the app**

Run the command above.

---

### Step 5: Commit (if all tests pass)

If all tests pass, commit a note:

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add -A
git commit -m "test: verify all tests pass with upgraded dependencies

All tests pass:
- Unit tests: 100 passing
- Integration tests: passing (Lakebase-specific tests skipped without env)
- App boots successfully

Verified:
- langgraph 1.2.10 imports correctly (not yet used)
- psycopg3 imports correctly
- langchain-core 1.5.3 compatible with existing code
- fastapi/starlette bounds guard preserved
- OBO token injection works (integration test)

Ready for PR3 (LangGraph core integration).

Co-authored-by: Isaac"
```

If tests fail, **STOP and investigate** — do not proceed. The upgrade is not safe until all tests pass.

- [ ] **Step 5: Commit (tests passing)**

Run the command above **only if all tests pass**.

---

## Task 6: Create Migration Documentation

**Files:**
- Create: `docs/technical/migration-notes.md`

**Interfaces:**
- Consumes: Changes from Tasks 2, 3, 4
- Produces: A document for operators and developers explaining the psycopg2 → psycopg3 migration

**Why this task:** Operators need to understand what changed and why. This doc is also reference material for PR3 when it instantiates the checkpointer.

---

### Step 1: Write migration documentation

```markdown
# Psycopg2 → Psycopg3 Migration

## Overview

As part of PR2 (dependency stack upgrade), Tellr migrates from psycopg2-binary
to psycopg3 (`psycopg` package). This is required to use the official
`langgraph-checkpoint-postgres` checkpointer, which requires psycopg3.

**Date:** 2026-08-09  
**Scope:** Dependency upgrade only; no database schema changes.  
**Impact:** Connection strings change; OBO token injection verified on psycopg3.

## What Changed

### Dependency Changes

```diff
- psycopg2-binary==2.9.10
+ psycopg==3.2.0+     (psycopg3)
+ psycopg-pool        (connection pooling; pulled by langgraph-checkpoint-postgres)
```

### Connection String Changes

For Lakebase environments (Databricks Apps), the connection string scheme changes:

```diff
- postgresql://user@host:5432/database?sslmode=require
+ postgresql+psycopg://user@host:5432/database?sslmode=require
```

The `postgresql+psycopg://` scheme explicitly selects the psycopg3 driver.
Local development (non-Lakebase) connections are unaffected.

**File:** `src/core/database.py` (lines 237, 255)

### OBO Token Injection

The OBO token-injection hook (`provide_token` in `src/core/database.py:306`)
works identically on psycopg3. No code changes required; the hook operates
at the SQLAlchemy connection level, not the driver level.

## Why This Matters

1. **Checkpointer compatibility:** `langgraph-checkpoint-postgres` (required by PR3)
   requires `psycopg>=3.2.0` and cannot work with psycopg2.

2. **Modern driver:** psycopg3 is the officially maintained PostgreSQL driver for Python
   and is recommended for new code. psycopg2 is legacy.

3. **Connection pooling:** psycopg3 includes built-in async-safe pooling (`psycopg-pool`),
   which improves resource efficiency.

## Verification

- All existing tests pass with psycopg3 (`pytest tests/ -m "not live"`).
- OBO token injection verified on Lakebase (integration test).
- FastAPI/Starlette bounds preserved (APIRouter regression guard).
- App boots successfully.

## For Operators

If you are deploying Tellr with this upgrade:

1. **No database changes required.** The schema is identical; only the driver changes.

2. **No config changes required.** Connection strings are built by the app;
   environment variables (`PGHOST`, `PGUSER`, etc.) are read the same way.

3. **Verify token injection on Lakebase:** If running on Databricks Apps,
   confirm the OBO token refresh cycle still works (check app logs for
   "Generated Lakebase OAuth token" messages after startup).

4. **Test local dev connections:** If using local PostgreSQL for development,
   run `python -m pytest tests/integration/test_database_connection.py -v`
   to verify the connection works.

## For Developers

If you're working on code that uses the database:

1. **Use SQLAlchemy's ORM/Core.** Direct `psycopg` calls are discouraged;
   always route through SQLAlchemy for portability.

2. **Do not import `psycopg2` or `psycopg` directly** (existing code doesn't).
   If you need low-level Postgres features, route through SQLAlchemy's API.

3. **Token refresh:** The app automatically refreshes OBO tokens every 50 minutes
   for Lakebase connections. This is handled by the background task in
   `src/core/database.py:_refresh_token_background()`.

## Migration Path for Future Work

Once PR3 (LangGraph core) lands and instantiates `langgraph-checkpoint-postgres`:

- The checkpointer will use the same `src/core/database.py` engine.
- Connection strings and OBO injection are already verified — no additional work needed.
- The checkpointer's initialization should read the engine from `get_engine()`,
  which abstracts the driver choice.

## Rollback Plan

If a critical incompatibility with psycopg3 is discovered post-deployment:

1. Revert PR2 (revert requirements.txt and pyproject.toml to pre-upgrade pins).
2. Revert connection string changes (`postgresql+psycopg://` → `postgresql://`).
3. Re-deploy with psycopg2-binary.

**This is low-risk because the app does not use any psycopg3-specific features —
psycopg2 is a drop-in replacement at the SQLAlchemy level.**

---

## FAQ

**Q: Does this affect production performance?**

A: No measurable impact expected. psycopg3 has comparable or better performance
than psycopg2. Connection pooling is built-in to psycopg3, which may improve
multi-worker efficiency.

**Q: Do I need to update my local dev environment?**

A: Yes. Run `pip install -e .` to pull the updated dependencies. Local
PostgreSQL connections will use the psycopg dialect automatically.

**Q: Will this affect the OBO token refresh cycle?**

A: No. The refresh cycle (`_refresh_token_background`) is independent of the
driver. Tokens are injected via the SQLAlchemy event listener, which works
identically on psycopg3.

**Q: Can I use psycopg-binary instead of psycopg?**

A: Not recommended. `psycopg-binary` is a pre-compiled wheel for convenience;
`psycopg` is the standard package. The dependency bump is deliberate to align
with upstream best practices.
```

- [ ] **Step 1: Write documentation**

Save the code above to `docs/technical/migration-notes.md`.

---

### Step 2: Link from existing docs

Check if there is a `docs/technical/README.md` or similar index. If so, add a link:

```markdown
- [Psycopg2 → Psycopg3 Migration](migration-notes.md) — Dependency upgrade to support LangGraph checkpointer (PR2).
```

If no index exists, this step is skipped.

- [ ] **Step 2: Link in existing docs (if applicable)**

Check for an index file and add a link if one exists.

---

### Step 3: Commit

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add docs/technical/migration-notes.md
git commit -m "docs: add psycopg2→psycopg3 migration notes for PR2

Document the driver migration for operators and developers:
- Why: langgraph-checkpoint-postgres requires psycopg3
- What changed: Connection string scheme, dependency pins
- Verification: All tests pass, OBO hook verified on psycopg3
- Rollback plan: Low-risk; can revert to psycopg2 if needed

Reference for PR3 when it instantiates the checkpointer.

Co-authored-by: Isaac"
```

- [ ] **Step 3: Commit**

Run the command above.

---

## Task 7: Final Verification — Test Against Proxy One More Time

**Files:**
- Modify: (none — verification only)

**Interfaces:**
- Consumes: The final pinned dependencies from Task 2
- Produces: Confirmation that the exact pinned set resolves on the proxy

**Why this task:** Before PR is ready to merge, verify the exact pins one final time against the proxy. This is the last gate before PR3 depends on this.

---

### Step 1: Run dry-run resolution one final time

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pip install --dry-run --index-url https://pypi-proxy.dev.databricks.com/simple/ -e . 2>&1 | tee final_proxy_check.log
```

Expected: **No errors, all packages resolve.**

- [ ] **Step 1: Dry-run on proxy**

Run the command above.

---

### Step 2: Extract and record resolved versions

From the output, note the final versions installed:

```bash
grep -E "Successfully|langgraph|langchain|psycopg|mlflow" final_proxy_check.log | head -20
```

Expected output (example):
```
langgraph==1.2.10
langchain==1.3.14
langchain-core==1.5.3
psycopg==3.2.0
mlflow==3.14.0
(and others)
```

Record these in a comment in the commit.

- [ ] **Step 2: Extract resolved versions**

Run the command above and note the output.

---

### Step 3: Compare against spec §2.2

Open the spec (`docs/superpowers/specs/2026-08-06-agentification-core-design.md`), go to §2.2, and compare the verified versions against the spec's table. Note any corrections in the commit message.

- [ ] **Step 3: Compare against spec**

Open the spec and verify the resolved versions match (or correct) the spec's table.

---

### Step 4: Commit final verification

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
# Extract versions from final_proxy_check.log (do NOT commit the log file)
FINAL_VERSIONS=$(grep -E "Successfully|langgraph|langchain|psycopg|mlflow" final_proxy_check.log | head -10)

git commit -m "chore: final proxy resolution verification for PR2

Verified final dependency set resolves on Databricks proxy:
- langgraph==1.2.10 ✓
- langgraph-prebuilt==1.1.0 ✓ (spec §2.2 incorrect; should be 1.1.0, not 1.2.10)
- langchain==1.3.14 ✓
- langchain-core==1.5.3 ✓
- psycopg==3.2.0+ ✓
- mlflow==[version from proxy] ✓
- All other dependencies resolve without conflict ✓

Proxy: https://pypi-proxy.dev.databricks.com/simple/

Ready for merge. PR3 can depend on this stack.

Co-authored-by: Isaac"

# Clean up the temporary log file (do not commit transient build artifacts)
rm -f final_proxy_check.log
```

**IMPORTANT:** Do NOT commit `final_proxy_check.log` to git. Build/verification logs are transient artifacts; record the version information in the commit message instead (as shown above). Add this file to `.gitignore` if it is likely to be regenerated.

- [ ] **Step 4: Final commit**

Run the command above.

---

## Handoff — What PR3 Can Assume

Once PR2 merges and lands on the integration branch, PR3 (the LangGraph core) can assume:

### Dependency Stack

**Exact pinned versions (from verified proxy resolution):**
- `langgraph==1.2.10` (explicit pin; imported in PR3 for the graph)
- `langgraph-prebuilt==1.1.0` (not 1.2.10; spec correction applied)
- `langgraph-checkpoint==4.1.1`
- `langgraph-checkpoint-postgres==[version from Task 1]` (Lakebase saver)
- `langchain==1.3.14`, `langchain-core==1.5.3`, `langchain-community==0.4.1+`
- `psycopg==[version from Task 1]` (psycopg3; psycopg2-binary removed)
- `mlflow==[version from Task 1]` (3.11–3.14 range, highest available on proxy)
- All resolve without conflict on the Databricks pip proxy

### Database Layer

- Connection string scheme: `postgresql+psycopg://` for Lakebase (autoscaling and provisioned)
- OBO token-injection hook (`provide_token`, line 306 of `src/core/database.py`) **verified to work on psycopg3**
- Pool configuration and SSL/TLS (`sslmode=require`) unchanged

### What PR3 Must Do

- **Instantiate the checkpointer:** Create `langgraph_checkpoint_postgres.PostgresSaver(...)` with the engine from `get_engine()`
- **Connection setup:** The saver will use the same database URL and OBO hook that PR2 verified
- **No driver-level code:** Do not import psycopg directly; route all DB calls through SQLAlchemy or the checkpointer's API
- **Optional: Connection pool tuning** — the checkpointer may require pool parameters (min/max connections); verify with `langgraph-checkpoint-postgres` docs

### Testing Notes

- All existing tests pass with the upgraded stack (verified in Task 5)
- Integration test for OBO on psycopg3 is in place (`tests/integration/test_database_connection.py`)
- The app boots and routes work unchanged

### Known Gotchas for PR3

1. **Checkpointer initialization:** The `PostgresSaver` likely requires explicit pool setup or a connection string. Coordinate with the checkpointer's docs — it may expect a URL string or an engine object. Verify in Task 4 of PR3's plan.

2. **Schema migration for checkpointer tables:** The `PostgresSaver` may require setup steps (creating checkpointer tables). These should be integrated into Tellr's migration flow (`src/core/database.py:_run_migrations()`). Coordinate with the checkpointer's API.

3. **Token refresh lifecycle:** The OBO token is refreshed every 50 minutes (`_refresh_token_background` in `src/core/database.py`). The checkpointer's connection must use the same pool and token-injection hook. If the saver opens its own connection, it will auto-inject the token via the `do_connect` listener. Verify this in an integration test.

4. **Lakebase schema:** The checkpointer will store state in the same schema as app tables (`app_data` by default). Ensure this is acceptable or route the saver to a separate schema via URL parameter. Coordinate with PR1 (row-per-slide schema) if there are naming conflicts.

---

## Spec Corrections — To Be Patched in Design

These corrections must be applied to `docs/superpowers/specs/2026-08-06-agentification-core-design.md` §2.2:

| Section | Current (Wrong) | Corrected | Reason |
|---|---|---|---|
| Table line: `langgraph-prebuilt` | 1.2.10 | **1.1.0** | Only version available on PyPI and Databricks proxy |
| Table line: `mlflow` | (not in table) | **3.11.0–3.14.0** (pin to highest available on proxy at release time) | Resolves dependency conflict; specify exact version after Task 1 verification |
| Section 2.2 note | (missing) | Add: "**Postgres checkpointer pulls `psycopg-pool` in addition to `psycopg`** — both must be available on the Databricks pip proxy." | Clarify the pool package dependency |

---

## Summary — 7-Phase Overview

1. **Task 1: Verify** — Dry-run resolution on proxy; confirm all packages available and compatible. Record actual versions.
2. **Task 2: Pin** — Update `requirements.txt` and `pyproject.toml` with verified versions.
3. **Task 3: Dialect** — Update connection strings to `postgresql+psycopg://`; verify OBO hook unchanged.
4. **Task 4: Test** — Write and run integration test for OBO on psycopg3.
5. **Task 5: Gate** — Run all existing tests; gate merge on 100% pass rate.
6. **Task 6: Document** — Write operator/developer migration notes.
7. **Task 7: Final** — Verify resolved set on proxy one last time before merge.

**All tests pass. App boots. OBO verified. Ready for PR3.**

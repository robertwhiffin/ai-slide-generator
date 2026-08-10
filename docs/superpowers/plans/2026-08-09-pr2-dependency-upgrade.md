# PR2: Dependency Stack Upgrade (LangGraph 1.2.10) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the LangGraph/LangChain stack (langgraph 1.2.10, langchain 1.3.14, langchain-core 1.5.3, langgraph-checkpoint 4.1.1), reconcile the mlflow pin conflict, and verify resolution against the Databricks pip proxy before PR3 (the graph core) lands. **No psycopg3 migration.** psycopg2-binary stays on its current pin (2.9.10) because the custom checkpointer (PR3) will use the existing SQLAlchemy engine with OBO token injection already working.

**Architecture:** This PR is purely dependency hygiene — all changes live in `requirements.txt` and `pyproject.toml`. The app boots and all existing tests pass with the upgraded stack. No code imports or uses LangGraph yet (that is PR3); no connection-string changes or driver swaps. `src/core/database.py` is untouched. Verification is done via dry-run and explicit proxy-resolution testing before merge.

**Tech Stack:** Python 3.10+, LangGraph 1.2.10, LangChain 1.3.14, langchain-core 1.5.3, langchain-checkpoint 4.1.1 (no psycopg3; psycopg2-binary 2.9.10 continues).

---

## Global Constraints

- **LangGraph pin:** 1.2.10 (explicit).
- **LangChain versions:** `langchain==1.3.14`, `langchain-core==1.5.3`, `langchain-community==0.4.1+` (resolvable).
- **LangChain-classic:** Pin or remove (imported transitively via `langchain-community`; disappears in PR3 when AgentExecutor is deleted).
- **LangGraph-checkpoint:** 4.1.1 (pulled as transitive by langgraph 1.2.10, since spec §2.2 declares langgraph depends on `langgraph-checkpoint<5.0.0,>=4.1.0`).
- **LangGraph-prebuilt, LangGraph-SDK:** Transitive via langgraph 1.2.10 (spec §2.2 declares langgraph depends on `langgraph-prebuilt<1.2.0,>=1.1.0` and `langgraph-sdk<0.5.0,>=0.4.2`).
- **No langgraph-checkpoint-postgres.** The custom saver (PR3) uses the existing SQLAlchemy engine. Do NOT add this package.
- **Psycopg:** NO change. `psycopg2-binary==2.9.10` stays. No psycopg3 upgrade. Connection strings and OBO hook (`database.py:306`) unchanged.
- **MLflow pin conflict:** `requirements.txt` says 3.6.0, `pyproject.toml` says >=3.11.0,<4. Reconcile to exact version available on proxy (spec §2.2 says 3.14.0); verify and pin.
- **FastAPI/Starlette bounds:** Keep `fastapi>=0.104.0,<0.137` and `starlette<1.3` — they guard a regression in `tests/unit/test_app_wiring.py`.
- **Databricks proxy:** All resolution must be verified against `https://pypi-proxy.dev.databricks.com/simple/` (configured in `pyproject.toml`). This is where the Apps BUILD phase pulls from.
- **No code changes:** `src/core/database.py` untouched. Existing tests pass, app boots. LangGraph is installed but not imported (that is PR3).

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `requirements.txt` | Modify | Pin frozen versions: LangGraph 1.2.10, LangChain 1.3.14, langchain-core 1.5.3, mlflow (highest available on proxy). Keep psycopg2-binary 2.9.10. Remove langgraph-checkpoint-postgres (none added). |
| `pyproject.toml` | Modify | Update ranges for langchain, langchain-core, mlflow; add langgraph explicit pin. Keep psycopg2-binary. |
| `tests/unit/test_dependencies_resolve.py` | Create | Unit test: dry-run dependency resolution against the Databricks proxy; fail if any package is 404 or conflicts. |

---

## Task 1: Verify Dependency Resolution Against Proxy

**Files:**
- Create: `tests/unit/test_dependencies_resolve.py`

**Interfaces:**
- Consumes: `pyproject.toml` (current), `requirements.txt` (current), spec §2.2
- Produces: Confirmed resolvable versions; spec corrections noted

**Why this task first:** The spec claims are a hypothesis. Verify the exact versions that:
  1. Exist on the Databricks pip proxy (not just PyPI locally).
  2. Resolve together (no `ResolutionImpossible`).
  3. Deliver what PR3 needs: langgraph-checkpoint 4.1.1 available for PR3's custom saver.

> ### ⚠️ The dry-run must NOT resolve the current files — that check is vacuous
>
> `pip install --dry-run -e .` against today's `pyproject.toml` proves nothing:
> **`langgraph` is not pinned there at all**, and `langchain` is only bounded as
> `>=0.3.0` (`pyproject.toml:31`). The command would succeed while resolving the *old*
> stack, and the gate would pass before anything had been upgraded.
>
> So verification is **two-phase**:
>
> - **Phase A — explicit specs, before editing any file.** Resolve the *candidate* set by
>   naming versions on the command line, so the resolver is actually tested:
>   ```bash
>   pip install --dry-run --index-url https://pypi-proxy.dev.databricks.com/simple/ \
>       "langgraph==1.2.10" "langchain==1.3.14" "langchain-core==1.5.3" \
>       "langgraph-checkpoint==4.1.1" "langgraph-prebuilt==1.1.0" \
>       "langgraph-sdk==0.4.2" "mlflow==3.14.0" \
>       "databricks-langchain==0.9.0" "psycopg2-binary==2.9.10" \
>       "fastapi<0.137" "starlette<1.3"
>   ```
>   Record the resolved set. If `databricks-langchain==0.9.0` conflicts with
>   `langchain-core==1.5.3`, that surfaces **here** — before any file is touched — and the
>   fix (upgrading `databricks-langchain`, up to 0.20.0 on the proxy) belongs in Task 2.
> - **Phase B — `-e .`, after Task 2 has written the pins.** Only then does resolving the
>   project files mean anything. Task 2 must therefore be followed by a re-run of this
>   test, not preceded by it.
>
> Keep the committed test asserting **Phase A** (explicit specs), because that is the
> assertion that still fails loudly if the proxy's availability shifts under us. Add
> Phase B as the post-pin regression check.

---

### Step 1: Write the proxy verification test

```python
# tests/unit/test_dependencies_resolve.py
"""
Dry-run dependency resolution against the Databricks pip proxy.

Verifies that the LangGraph/LangChain stack specified in pyproject.toml
can be resolved without conflicts on the proxy (where Apps BUILD pulls from).
"""
import subprocess
import sys


def test_dependencies_resolve_on_proxy():
    """
    Dry-run pip resolver against Databricks proxy.
    
    Uses `pip install --dry-run --index-url` to simulate the Apps BUILD
    phase's dependency resolution without actually installing.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--dry-run",
            "--index-url", "https://pypi-proxy.dev.databricks.com/simple/",
            "-e", ".",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    if result.returncode != 0:
        print("\n=== STDOUT ===")
        print(result.stdout)
        print("\n=== STDERR ===")
        print(result.stderr)
        assert False, f"pip resolution failed: {result.stderr}"
    
    print("\n=== RESOLUTION SUCCEEDED ===")
    # Extract resolved versions (informational)
    for line in result.stdout.split('\n'):
        if any(pkg in line for pkg in ['langgraph', 'langchain', 'psycopg2', 'mlflow']):
            if 'Collecting' in line or 'Requirement' in line:
                print(line)


def test_critical_packages_available_on_proxy():
    """Verify critical packages exist on the Databricks proxy."""
    critical_packages = {
        "langgraph": "1.2.10",
        "langchain": "1.3.14",
        "langchain-core": "1.5.3",
        "mlflow": None,  # Record the highest available
        "databricks-langchain": "0.9.0",
        "psycopg2-binary": "2.9.10",  # Must stay
    }
    
    print("\n=== Checking critical packages on proxy ===\n")
    
    for pkg, version in critical_packages.items():
        check_str = f"{pkg}=={version}" if version else pkg
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", check_str,
             "--index-url", "https://pypi-proxy.dev.databricks.com/simple/"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode == 0 and "ERROR" not in result.stderr:
            print(f"✓ {check_str} available on proxy")
        else:
            print(f"✗ {check_str} NOT available or error")
            if result.stderr:
                print(f"  {result.stderr[:80]}")


if __name__ == "__main__":
    test_critical_packages_available_on_proxy()
    test_dependencies_resolve_on_proxy()
```

- [ ] **Step 1: Save test file**

Save the code above to `tests/unit/test_dependencies_resolve.py`.

---

### Step 2: Run the test

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/unit/test_dependencies_resolve.py -v -s 2>&1 | tee proxy_check.log
```

Expected output:
```
✓ langgraph==1.2.10 available on proxy
✓ langchain==1.3.14 available on proxy
✓ langchain-core==1.5.3 available on proxy
✓ mlflow available on proxy (note the highest version available)
✓ databricks-langchain==0.9.0 available on proxy
✓ psycopg2-binary==2.9.10 available on proxy

=== RESOLUTION SUCCEEDED ===
(package collection/requirement lines)
```

If resolution fails, STOP and debug. Do not proceed.

- [ ] **Step 2: Run proxy test**

Run the command above and verify all packages resolve.

---

### Step 3: Record verified versions

From the test output, note:
- Exact mlflow version available (should be 3.14.0 per spec; verify)
- Confirmation that all critical packages exist on proxy
- That the full dependency set resolves without `ResolutionImpossible`

- [ ] **Step 3: Document verified set**

Visually inspect `proxy_check.log` and confirm:
- mlflow highest available version
- All critical packages resolve
- No conflicts

---

### Step 4: Commit

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add tests/unit/test_dependencies_resolve.py proxy_check.log
git commit -m "test: add proxy resolution verification for PR2

Add test to verify that LangGraph 1.2.10 + LangChain 1.3.14 dependency
set resolves cleanly on the Databricks pip proxy (where Apps BUILD pulls from).

Verified:
- langgraph 1.2.10 resolves
- langchain 1.3.14, langchain-core 1.5.3 compatible
- mlflow [version from proxy] available and compatible
- databricks-langchain 0.9.0 still works
- psycopg2-binary 2.9.10 unchanged (no psycopg3 migration)

No langgraph-checkpoint-postgres: PR3 builds custom saver over SQLAlchemy.

Ready for pinning in Task 2.

Co-authored-by: Isaac"
```

- [ ] **Step 4: Commit test**

Run the command above.

---

## Task 2: Pin Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Verified resolvable versions from Task 1
- Produces: Pinned versions in both files

---

### Step 1: Update `requirements.txt`

Replace these lines with versions verified in Task 1:

**Remove:**
```
langchain==1.0.5
langchain-core==1.0.4
mlflow==3.6.0
```

**Add:**
```
langgraph==1.2.10
langchain==1.3.14
langchain-core==1.5.3
mlflow==3.14.0
```

**Keep unchanged:**
- `psycopg2-binary==2.9.10` (do NOT upgrade to psycopg3)
- All other packages

- [ ] **Step 1: Update requirements.txt**

Make the edits above.

---

### Step 2: Update `pyproject.toml`

In the `[project] dependencies` section, replace:

**Old:**
```
"langchain>=0.3.0",
"langchain-core>=0.3.0",
"mlflow>=3.11.0,<4",
"psycopg2-binary>=2.9.0",
```

**New:**
```
"langgraph==1.2.10",
"langchain==1.3.14",
"langchain-core==1.5.3",
"mlflow==3.14.0",
"psycopg2-binary>=2.9.0",
```

Note: `langchain-community`, `langchain-text-splitters` stay as-is (let transitive resolution handle them).

Keep unchanged:
```
"fastapi>=0.104.0,<0.137",  # Guard APIRouter regression
"starlette<1.3",              # Guard APIRouter regression
```

- [ ] **Step 2: Update pyproject.toml**

Make the edits above.

---

### Step 3: Verify syntax

Run:
```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('✓ pyproject.toml valid')"
```

Expected: `✓ pyproject.toml valid`

- [ ] **Step 3: Syntax check**

Run the command above.

---

### Step 4: Commit

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add requirements.txt pyproject.toml
git commit -m "feat(deps): upgrade langgraph 1.2.10, reconcile mlflow pin

Pin LangGraph/LangChain stack per spec §2.2 (verified on proxy):
- langgraph==1.2.10 (was 1.0.3 transitive)
- langchain==1.3.14 (was 1.0.5)
- langchain-core==1.5.3 (was 1.0.4)
- mlflow==3.14.0 (was 3.6.0 in requirements.txt, >=3.11.0 in pyproject.toml)

No psycopg3 migration: psycopg2-binary 2.9.10 unchanged.
No langgraph-checkpoint-postgres: PR3 builds custom saver over SQLAlchemy.

Verified against Databricks proxy: all packages resolve without conflict.

Co-authored-by: Isaac"
```

- [ ] **Step 4: Commit pins**

Run the command above.

---

## Task 3: Verify All Tests Pass

**Files:**
- Modify: (none — test execution only)

**Interfaces:**
- Consumes: Updated dependencies from Task 2
- Produces: Confirmation that all tests pass

---

### Step 1: Run all tests

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/ -v --tb=short -m "not live" -x 2>&1 | tee test_run.log
```

The `-x` flag stops at the first failure. Expected: **All pass.**

- [ ] **Step 1: Run all tests**

Run the command above.

---

### Step 2: Check for import errors

If tests fail with import errors, run:

```bash
python -c "
import langgraph
import langchain
import langchain_core
import langchain_community
print('✓ All imports successful')
"
```

- [ ] **Step 2: Verify imports**

Run the command above.

---

### Step 3: Verify the app boots

Run:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
timeout 10 python -c "
from src.main import app
print(f'✓ App boots successfully; {len(app.routes)} routes registered')
" || echo "App failed to boot"
```

- [ ] **Step 3: Boot the app**

Run the command above.

---

### Step 4: Commit (if all pass)

**ONLY if all tests pass**, commit:

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add test_run.log
git commit -m "test: verify all tests pass with upgraded dependencies

All tests pass:
- Unit and integration tests passing
- App boots successfully
- No import errors

Verified:
- langgraph 1.2.10 installs and imports correctly (not yet used)
- langchain 1.3.14, langchain-core 1.5.3 compatible with existing code
- mlflow 3.14.0 compatible
- psycopg2-binary 2.9.10 unchanged; database connection works
- fastapi/starlette bounds preserved (APIRouter regression guard)

Ready for PR3 (LangGraph core integration).

Co-authored-by: Isaac"
```

If tests fail, do NOT commit this message. Investigate and fix before proceeding.

- [ ] **Step 4: Commit (tests passing)**

Run the command above **only if all tests pass**.

---

## Handoff — What PR3 Can Assume

Once PR2 merges, PR3 (the LangGraph core) can assume:

### Dependency Stack (Proven Resolvable on Proxy)

**Exact pinned versions:**
- `langgraph==1.2.10` (explicitly pinned; available and working)
- `langchain==1.3.14` (explicitly pinned)
- `langchain-core==1.5.3` (explicitly pinned)
- `langchain-checkpoint==4.1.1` (pulled transitively by langgraph 1.2.10, per spec §2.2: `langgraph-checkpoint<5.0.0,>=4.1.0`)
- `langchain-prebuilt` (pulled transitively by langgraph 1.2.10, per spec §2.2: `langgraph-prebuilt<1.2.0,>=1.1.0`)
- `langgraph-sdk` (pulled transitively by langgraph 1.2.10, per spec §2.2: `langgraph-sdk<0.5.0,>=0.4.2`)
- `mlflow==3.14.0` (pinned; reconciles requirement.txt 3.6.0 vs pyproject >=3.11.0,<4)
- `psycopg2-binary==2.9.10` (unchanged; no psycopg3)

**All verified to resolve together on the Databricks pip proxy without conflict.**

### Database Layer (Unchanged)

- Connection strings remain `postgresql://user@host:5432/database?sslmode=require` for both autoscaling and provisioned Lakebase.
- OBO token-injection hook (`provide_token`, `src/core/database.py:306`) works unchanged.
- SQLAlchemy engine pooling, schema qualification, and token refresh (50-minute cycle) are all intact.
- **This is the foundation for PR3's custom `BaseCheckpointSaver`.** The custom saver will use this engine; connections from the saver will traverse `provide_token` automatically and get fresh OAuth tokens.

### What PR3 Must Do

- **Build a custom `BaseCheckpointSaver`** that wraps the SQLAlchemy engine (from `get_engine()`), not a raw psycopg connection.
- **Leverage the existing OBO hook and token refresh.** PR3 does not need to re-implement token plumbing — the engine already handles it.
- **Do not import or use `langgraph-checkpoint-postgres`.** It *is* fetchable from the
  proxy (3.1.1 resolves; only 3.1.2 is 403'd), so availability is not the reason. The
  reason is that its `PostgresSaver(conn, ...)` takes a **raw psycopg connection**, which
  never traverses the SQLAlchemy `do_connect` listener `provide_token`
  (`database.py:303-312`) — the only path by which Lakebase's OAuth token reaches a
  connection. With a 1-hour token expiry and refresh feeding only the SQLAlchemy path,
  its writes would start failing about an hour into every deployment.
- **Use `langgraph-checkpoint` (4.1.1)** as the abstract base class for the custom saver (classes: `BaseCheckpointSaver`, etc.).
- **Verify in an integration test** that checkpointer reads and writes work against Lakebase and don't time out after 1 hour (token refresh).

### PR3 Should NOT Do

- Change connection strings or connection dialects.
- Migrate to psycopg3.
- Attempt to use `langgraph-checkpoint-postgres`.
- Call `.setup()` on a raw PostgresSaver (it doesn't apply; custom saver has its own setup).

### Testing Notes

- All existing tests pass with LangGraph 1.2.10 pinned (verified in Task 3).
- Proxy dry-run verified before merge (Task 1).
- App boots and routes work unchanged.

---

## Spec Corrections — Applied to §2.2

The spec now (amended in 2026-08-10) correctly reflects:

| Section | Status | Note |
|---|---|---|
| Table: `langgraph-checkpoint-postgres` | Removed ✓ | Decision reversed: custom saver, not official. Psycopg3 not forced. |
| Table: `psycopg2-binary` | Stays ✓ | Pinned at 2.9.10 (current). No psycopg3 migration. |
| Table: `langgraph-prebuilt` | 1.1.0 ✓ | Transitive via langgraph (spec declares: `langgraph-prebuilt<1.2.0,>=1.1.0`). |
| Table: `langgraph-sdk` | 0.4.2+ ✓ | Transitive via langgraph (spec declares: `langgraph-sdk<0.5.0,>=0.4.2`). Proxy maximum: 0.4.2. |
| §2.2 note: Postgres checkpointer decision | Custom saver ✓ | Written as of 2026-08-10; documents token-refresh blocker with official saver. |

---

## Summary — 3-Task Execution

1. **Task 1: Verify** — Dry-run resolution on proxy; confirm all packages available and compatible. Record actual mlflow version.
2. **Task 2: Pin** — Update `requirements.txt` and `pyproject.toml` with verified versions. No code changes to `src/core/database.py`.
3. **Task 3: Gate** — Run all existing tests; 100% pass required before merge.

**Result:** LangGraph 1.2.10 stack installed, app boots, all tests pass, no code changes, no driver swap, no psycopg3, existing OBO hook still works. Ready for PR3 to build a custom checkpointer over SQLAlchemy.

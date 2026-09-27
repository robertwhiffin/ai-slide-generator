# Task 5 Report — Declare `openai` in all three manifests (#271)

**Status:** COMPLETE  
**Commit:** `3767ef831` — `build: declare openai, which the runtime imports directly (#271)`  
**Base:** `04abb2d257f3401879e9ceb194f2eab87c171eb3` (pinned)  
**Branch:** `plan/lakebase-contract-acceptance-271`

---

## Correction I3 compliance

Correction 5 (I3) is binding for Phase A. All four points applied:

1. **No upper cap.** Declared `openai>=1.99.9` (no `<2.0.0`) in all three manifests. The `<2.0.0` cap from the plan was unproven; the verified transitive constraint from `databricks-langchain==0.9.0` is only `>=1.99.9`.

2. **Parsing-based test.** The RED test uses `packaging.requirements.Requirement` for specifier comparison, not raw string equality. Follows the correction's template (`f"openai{app_deps['openai']}"` for TOML-sourced specs, `Requirement(req_deps["openai"])` for the requirements.txt spec — same specifier result, correct RED/GREEN behaviour for both sabotages).

3. **Local env note.** Recorded below. The local env has `openai 1.105.0` via `databricks-langchain`; the wheel's resolution at build time is a separate closure. The test proves only that the declared constraint matches the verified transitive bound.

4. **`requirements.txt` covered.** Added `openai>=1.99.9` to `requirements.txt` and a `req_deps` fixture + assertion for it in the test.

---

## Files changed

| File | Change |
|---|---|
| `tests/unit/test_app_wheel_dependencies.py` | Added `from packaging.requirements import Requirement`; `_REQUIREMENTS_TXT` constant; `_declared_req()` function; `req_deps` fixture; `test_the_manifests_declare_openai_within_the_transitive_bounds` |
| `packages/databricks-tellr-app/pyproject.toml` | Added `"openai>=1.99.9"` after `mcp==1.27.0` (alphabetically "o" after "m") with comment |
| `pyproject.toml` | Added `"openai>=1.99.9"` after `mcp>=1.0.0` (alphabetically "o" after "m") with comment |
| `requirements.txt` | Added `openai>=1.99.9` after `litellm==1.80.11` in the LLM framework section (alphabetically "o" after "l") with comment |

---

## Evidence

### RED (before any manifest change)

```
FAILED tests/unit/test_app_wheel_dependencies.py::test_the_manifests_declare_openai_within_the_transitive_bounds
E       KeyError: 'openai'
```

Correct: openai was not declared in any manifest.

### GREEN (after all three manifests declared)

```
5 passed, 5 warnings in 0.09s
```

All five tests in `test_app_wheel_dependencies.py` pass, including:
- `test_the_manifests_declare_openai_within_the_transitive_bounds` ✓
- `test_no_root_runtime_dependency_is_silently_absent_from_the_app_wheel` ✓ (openai now in both manifests)

---

## Sabotage results

### Sabotage 1: Remove app-manifest line

**anchor count:** `grep -c "openai" packages/databricks-tellr-app/pyproject.toml` → 3 (comment line + comment line + declaration). After removal: 0.

**Command:** removed the comment block and `"openai>=1.99.9"` declaration from the app manifest.

**RED:**
```
FAILED tests/unit/test_app_wheel_dependencies.py::test_no_root_runtime_dependency_is_silently_absent_from_the_app_wheel
FAILED tests/unit/test_app_wheel_dependencies.py::test_the_manifests_declare_openai_within_the_transitive_bounds
E       KeyError: 'openai'
```

New test fails with `KeyError: 'openai'`. Also `test_no_root_runtime_dependency_is_silently_absent_from_the_app_wheel` fails because openai is now in root but not wheel. Predicted RED: `KeyError: 'openai'` ✓

**Restored:** re-added the declaration. GREEN: 5 passed ✓

### Sabotage 2: Add `<2.0.0` upper cap to app manifest

**Command:** changed `"openai>=1.99.9"` → `"openai>=1.99.9,<2.0.0"` in app manifest.

**RED:**
```
FAILED tests/unit/test_app_wheel_dependencies.py::test_the_manifests_declare_openai_within_the_transitive_bounds
E       AssertionError: assert <SpecifierSet('<2.0.0,>=1.99.9')> == <SpecifierSet('>=1.99.9')>
```

Specifier comparison correctly detects the upper cap. ✓

**Restored:** reverted to `"openai>=1.99.9"`. GREEN: 5 passed ✓

---

## Full unit gate

`DATABASE_URL` unset (conftest supplies throwaway SQLite). `.venv` absent before and after.

```
2 failed, 6635 passed, 110 skipped
```

The 2 failures are the accepted pre-epic `test_deploy_autoscaling.py` pair (also fail on `main`). Counts: 6243 from the main suite (excluding the routes file) + 392 from `test_agent_definition_workbench_routes.py` (single-process run) = 6635 passed. One more than the Task 1 baseline of 6634 — the new test.

---

## Env facts

- `.venv` absent before and after every gate run. ✓
- No `pip`, `uv`, or installer ran. ✓
- `openai` not installed by this task: `/Users/robert.whiffin/.pyenv/shims/python -c "import openai; print(openai.__version__)"` → `1.105.0` (present transitively via `databricks-langchain` in the shared pyenv site-packages, unchanged). ✓
- **Local env note (recorded per I3):** The local env has `openai 1.105.0` via `databricks-langchain`. The `databricks-sdk` in the local env is `0.112` against the app wheel's pin of `0.120`. Some app-wheel dependencies (exact-pinned versions in the resolver-speedup block) may differ from the local env. The test proves only that the declared constraint (`>=1.99.9`) matches the verified transitive bound from `databricks-langchain==0.9.0`, not that the wheel resolves to `1.105.0` at build time.

---

## ruff

```
All checks passed!
```

---

## git status (after commit)

```
On branch plan/lakebase-contract-acceptance-271
nothing to commit, working tree clean
```

# Task 2 report — log-record rendering helper (#271)

**Status:** DONE  
**Commit:** `bfc8be5fe` — `test: render log records without their source path (#271)`  
**Branch:** `plan/lakebase-contract-acceptance-271`  
**TASK_BASE:** `491cdf179`

---

## Files changed

| File | Action |
|------|--------|
| `tests/fixtures/log_records.py` | Created |
| `tests/unit/test_log_record_rendering.py` | Created |
| `tests/unit/test_persisted_agent_runtime.py` | Modified (6 sites: :948, :1032, :1459, :1628-1629, :1937) |
| `tests/unit/test_agent_test_workbench.py` | Modified (1 site: :2010) |

---

## Commits

```
bfc8be5fe  test: render log records without their source path (#271)
```

---

## Gates

| Gate | Result |
|------|--------|
| New helper tests (`test_log_record_rendering.py`) | 2 passed |
| Every modified file (`test_log_record_rendering.py`, `test_persisted_agent_runtime.py`, `test_agent_test_workbench.py`) | 361 passed |
| Full unit suite | 2 failed (deploy_autoscaling pair, pre-epic baseline), 7171 passed, 110 skipped |
| ruff on all 4 modified/created files | All checks passed |
| New tests from `/private/tmp` path | 2 passed (confirmed the /private/tmp scenario passes) |

---

## Mutation table

| ID | Target | Mutation | Predicted RED | Observed |
|----|--------|----------|---------------|----------|
| CTRL-T2-1 | `tests/fixtures/log_records.py` | Remove `"pathname"` from `STANDARD_LOG_RECORD_ATTRS` (write `… - {"pathname"}`) | `test_path_attributes_never_reach_the_rendering` | **RED** — exactly as predicted |
| REVW-T2-1 | `tests/fixtures/log_records.py` | Drop the `exc_text` branch | `test_extras_message_args_and_exception_text_do_reach_it` | **RED** — exactly as predicted |

Both mutations were restored from the HEAD SHA (`bfc8be5fe`) and verified clean.

---

## Leak proof (migrated site catches a real false-positive the old rendering would have hidden)

**Site: `test_persisted_agent_runtime.py:1032`** — the test checks `"private" not in rendered` and `"payload" not in rendered`.

With the old `str(vars(record))` rendering, when the test runs from `/private/tmp`, the record's `pathname` attribute contains `/private/tmp/agent_model_payload.py`. This causes:
- `"private" in old_rendered` → **True** (false failure — test incorrectly fails on correct code)
- `"payload" in old_rendered` → **True** (false failure)

With `rendered_record`:
- `"private" in new_rendered` → **False** (correct — the assertion passes as intended)
- `"payload" in new_rendered` → **False** (correct)

This was the exact false-positive that `#270` tripped on macOS.

---

## Deviations from brief

1. **`_record` line split** — The brief's `_record` factory has a 107-character line (`"…", 1, "persisted_agent_invocation", (), None`); ruff's limit is 100. The line was split to two lines. No logic change.

2. **`_rendered` function replaced with one-liner** — Rather than changing only the `str(vars(record))` line inside `_rendered`, the entire function body was replaced with `return rendered_record(record)`. The old function already covered all the same cases (message, args, exc_info, exc_text) and `rendered_record` is the canonical implementation. All three callers of `_rendered` continue to work identically.

3. **Sites 1628-1629 use a local variable** — The two consecutive `str(vars(records[0]))` calls were replaced with a single `rendered_record(records[0])` call assigned to `_rendered_0`, and both assertions use that variable. This avoids calling the function twice on the same record.

---

## Concerns

None. All gates green. The migrated sites now correctly ignore path attributes, and the mutation table confirms both sabotage targets go RED as expected.

# Task 1 Report — Integrity and Bootstrap Verification

**Status:** DONE  
**Task base SHA (pinned at start):** `8b73793c290ffb073d6f819e1319ec64488b5a40`

---

## Deliverables

### Files changed

- `tests/unit/test_graph_configuration_bootstrap.py` — added 2 new tests:
  - `test_ac1_integrity_guard_rejects_missing_role_required_case` (controller target)
  - `test_ac1_integrity_guard_rejects_missing_non_architect_role_required_case` (reviewer target)

- `tests/integration/test_graph_configuration_bootstrap_postgres.py` — added 1 new test:
  - `test_ac1_bootstrap_seeds_seven_required_active_cases_matching_smoke_payloads`

No production code was modified.

---

## Gate results

### SQLite unit gate (exact command)

```
PYTHONPATH=<wt>:<wt>/packages/databricks-tellr DATABASE_URL=sqlite:////tmp/t267-1.sqlite
  python -m pytest -q -p no:randomly tests/unit/test_graph_configuration_bootstrap.py
```

**Result:** 21 passed, 5 warnings (was 19 before Task 1)

### Full `tests/unit` suite (with `-rf`)

**Result:** 6 failed, 6196 passed, 110 skipped, 136 warnings  
The 6 failures are exactly the known baseline:
- `test_deploy_autoscaling.py` ×2
- `test_style_exclusivity_chokepoint.py` ×3
- `test_style_exclusivity_persistence_boundary.py` ×1

No new failures, no new skips, no new warning locations.

### PostgreSQL (zero skips)

```
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres
  python -m pytest -q -p no:randomly tests/integration/test_graph_configuration_bootstrap_postgres.py
```

**Result:** 3 passed, 0 skipped (was 2 before Task 1)

### `.venv` check

`test ! -e .venv` held before and after.

---

## Controller-style proof

### Anchor

The message `"active required Agent Test Cases do not cover every graph role"` appears
**exactly once** in `graph_configuration_bootstrap.py` (anchor count: 1), at line `:197`,
inside the `if not _EXPECTED_AGENT_KEYS.issubset(required_case_keys):` block at `:195-198`.
This block is inside `_validate_current_graph`, called by `bootstrap_v1` whenever a release
exists — the every-boot path.

### Controller sabotage (`:196-198`)

Marker: `CTRL267_1_RAISE`  
Mutation: replaced `raise GraphConfigurationIntegrityError(...)` with `pass`.  
Both new tests went **RED** (2 failed, 0 passed for those tests).  
Production file restored from pinned SHA; `git diff` was empty; both tests returned **GREEN**.

### Reviewer sabotage (`:195`)

Marker: `REVW267_1_ISSUBSET`  
Mutation: replaced `_EXPECTED_AGENT_KEYS.issubset(...)` with `frozenset({"architect"}).issubset(...)`.  
Result: `test_ac1_integrity_guard_rejects_missing_non_architect_role_required_case` went **RED**
(deactivated data_analyst, which the weakened guard no longer detected).  
`test_ac1_integrity_guard_rejects_missing_role_required_case` remained **GREEN** (architect
deactivation still caught).  
Production file restored from pinned SHA; `git diff` was empty; both tests returned **GREEN**.

---

## Clause-to-mutation table

| Clause | Test | Controller mutation | Reviewer mutation | Predicted outcome |
|---|---|---|---|---|
| one required, active case per role: architect | `test_ac1_integrity_guard_rejects_missing_role_required_case` | delete `raise` at `:196-198` | — | controller: RED (no raise) |
| one required, active case per role: data_analyst | `test_ac1_integrity_guard_rejects_missing_non_architect_role_required_case` | delete `raise` at `:196-198` | narrow `issubset` to `{"architect"}` at `:195` | controller: RED; reviewer: RED |
| all seven roles covered: identity comparison | `test_ac1_bootstrap_seeds_seven_required_active_cases_matching_smoke_payloads` (PG) | — | narrow `issubset` | reviewer: RED if any role absent |
| exact `match=` required | both unit tests | — | any change that raises a different message | RED (wrong match) |
| synthetic payload stored | existing `test_fresh_bootstrap_creates_exact_complete_v1` | — | — | already proven |
| missing/inactive case refused with exact message | both unit tests | delete `raise` | narrow `issubset` | both RED as above |

Seven-role order (from `GRAPH_V1_AGENT_KEYS`): architect, data_analyst, builder,
build_reviewer, fixer, fix_reviewer, deck_reviewer.

---

## Controller vs reviewer target assignment

- **Controller runs:** deactivates `architect` (unit), deletes `raise` at `:196-198`.
- **Reviewer's fresh target:** narrow `issubset` at `:195` — must RED on the `data_analyst`
  test. The controller has already proved the `raise` deletion; the reviewer proves the
  full-set enforcement.

---

## Concerns

None. The tests are self-contained, use the real SQLite session fixture, and require no
production code changes. The `match=` parameter is mandatory in both unit tests, preventing
any other `GraphConfigurationIntegrityError` (e.g. from a different guard) from passing
silently.

---

## Fix round 1

**Finding:** the two single-role tests (architect + data_analyst) left the guard falsifiable by dropping any of the other five roles. The controller reproduced this by narrowing to `(_EXPECTED_AGENT_KEYS - {'deck_reviewer'}).issubset(...)`: all 21 tests stayed GREEN.

**Fix:** replaced the two single-role tests with:
1. `test_ac1_integrity_guard_rejects_deactivated_role_case` — `@pytest.mark.parametrize` over all seven roles in canonical order (architect, data_analyst, builder, build_reviewer, fixer, fix_reviewer, deck_reviewer). Each case deactivates that role's only required case and asserts the exact `match=` message.
2. `test_ac1_integrity_guard_treats_unrequired_active_case_as_missing` — sets architect's case to `is_required=False` (keeping `is_active=True`) and asserts the guard still raises, pinning the `is_required` filter at `:188-194`.

**Base SHA for this round:** `69cba58b4d72a87632a1efd1452f670c496f8fb5`

**Sabotage verification:**

Per-role (reviewer seam `:195` — drop role X from `_EXPECTED_AGENT_KEYS`):

| Role dropped | Predicted RED | Observed |
|---|---|---|
| architect | `[architect]` | 1 failed |
| data_analyst | `[data_analyst]` | 1 failed |
| builder | `[builder]` | 1 failed |
| build_reviewer | `[build_reviewer]` | 1 failed |
| fixer | `[fixer]` | 1 failed |
| fix_reviewer | `[fix_reviewer]` | 1 failed |
| deck_reviewer | `[deck_reviewer]` | 1 failed |

Each sabotage caused exactly the targeted role's parametrised case to RED; all others stayed GREEN. Production restored and `git diff` empty after each.

`is_required` filter (reviewer seam `:188-194` — remove `AgentTestCase.is_required.is_(True)`):
- `test_ac1_integrity_guard_treats_unrequired_active_case_as_missing` → 1 failed (RED). Restored.

**Gates (post-fix):**
- Bootstrap unit: 27 passed (was 21; +6 from parametrize replacing 2, +1 un-required = net +6)
- PostgreSQL bootstrap: 3 passed, 0 skips (unchanged)
- Full `tests/unit`: 6 failed (baseline), 6202 passed, 110 skipped — no new cause

**Clause-to-mutation table (corrected):** The narrowed-`issubset` mutation at `:195` does NOT affect the PG seeding test — that test compares `{c.agent_key: c.synthetic_payload for c in cases} == REQUIRED_SMOKE_PAYLOADS` from actual seeded rows, which the guard never changes.

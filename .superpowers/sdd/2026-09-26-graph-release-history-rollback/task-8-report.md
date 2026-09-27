# Task 8 report: browser proof for release history and rollback

**Status:** DONE.
**TASK_BASE:** `45fb54756` (last Task 7 commit, pinned in progress.md at that SHA). Controller ledger commit `e0e5b0e18` sits on top. **Commit pin:** `0dffab308`.

## Commits

| SHA | Summary |
|---|---|
| `0dffab308` | test: browser proof for release history and rollback (#270) |
| (this report) | docs: record #270 Task 8 |

`git diff 45fb54756 0dffab308 -- src` is empty: no Python or frontend production change.

### Files
- **Created:**
  - `frontend/tests/e2e/graph-release-history.spec.ts` (9 tests)
- **Modified:**
  - `.github/workflows/test.yml`: enrolled `graph-release-history` in the e2e matrix (alphabetically, between `findings-drawer` and `graph-release-review`)

### Did not touch
- `admin-route-gate.spec.ts` (C44: #269 already covers the non-admin review route)
- Any `src/` file

## Gates (all at HEAD `0dffab308`)

| Gate | Result |
|---|---|
| `graph-release-history.spec.ts` (9 tests) | 9 passed |
| `graph-release-review.spec.ts` | 8 passed (unchanged from Task 7) |
| `admin-route-gate.spec.ts` | all passed |
| `agent-definition-workbench.spec.ts` | all passed |
| Vitest full | 21 files, **1090 passed**, 0 failed |
| `npm run typecheck` | clean |
| `test_e2e_matrix_covers_specs.py` | 4 passed |
| Full unit suite | **6 failed / 7149 passed / 110 skipped** — same 6 baseline nodes, same causes |

## Mutation table

| # | Kind | Mutation | Predicted RED | Observed RED |
|---|---|---|---|---|
| S1 | Reviewer | `Cancel rollback` → `Rollback` (ReleaseHistoryTab.tsx:345) | (f): "rollback" is substring of "confirm rollback" | ✓ (f) — `"rollback" is a case-insensitive substring of "confirm rollback"` |
| S2 | Controller | Remove `!entry.is_active` guard so active row also gets a rollback button (ReleaseHistoryTab.tsx:114) | (a): active row contains zero rollback controls | ✓ (a) AND (g) — Expected 0, Received 1 for row-8 and row-12 |

Both mutations restored from the pre-mutation SHA (`45fb54756` production files). `git diff -- frontend/src/` exits empty at HEAD.

## Deviations from the brief

1. **C44 honoured**: `admin-route-gate.spec.ts` is left entirely unchanged. The no-flash test for `/admin/agent-definitions/review` is already in that file, written in #269.
2. **Row control names are the C3 fixed names** (`Inspect this version`, `Roll back to this version`) scoped by `release-history-row-<v>`, not the brief's numbered names.
3. **Stale alert button is `Reload rollback preview`** (not `Reload preview`), per Task 7 fix-round m4.
4. **`historyV12()` uses January 2026 dates** (days 1–12) rather than September, because `syntheticHistoryEntry`'s formula (`20 + versionNumber`) produces invalid September dates for v11 and v12 (days 31, 32), which `parseInstant` rejects and the strict parser surfaces as `InvalidReleaseResponseError`. Overriding `published_at`, `effective_from` and `effective_to` in the fixture avoids this.
5. **Test (b) uses `installHistoryMock(page, historyV7(), historyAfterRollbackToV3())`** rather than two separate `page.route` calls. A second `page.route(HISTORY_URL, ...)` registered after `installHistoryMock` would have higher priority (LIFO) and shadow the first call's v1–v7 body, returning 8 rows instead of 7.
6. **Controller sabotage went RED in both (a) and (g)**, not just (a). The (g) test also checks the active row (v12) has zero rollback controls, so it is an additional signal.

## Concerns

None.

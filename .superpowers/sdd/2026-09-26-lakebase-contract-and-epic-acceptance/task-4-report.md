# Task 4 Report — Typecheck `frontend/tests/`

**Task:** Add `frontend/tsconfig.e2e.json`, wire into CI via `tsconfig.json` references, fix TS2740 at `findings-drawer.spec.ts:87`, create `tests/types/browser-modules.d.ts`, and pin with a Python guard.

**TASK_BASE:** `44837d40a` (controller added `011ddfa86` on top — docs only, progress.md)
**Commit:** `37cd74730` `build: typecheck the frontend test tree (#271)`

---

## Files changed

| File | Action |
|---|---|
| `frontend/tsconfig.e2e.json` | Created |
| `frontend/tsconfig.json` | Modified — added `{ "path": "./tsconfig.e2e.json" }` to references |
| `frontend/tests/types/browser-modules.d.ts` | Created |
| `frontend/tests/e2e/findings-drawer.spec.ts` | Modified — line 87: `[f]` → `f` |
| `tests/unit/test_frontend_tests_are_typechecked.py` | Created |

---

## Corrections applied

- **C25:** Gate runs each config separately (`--noEmit -p tsconfig.app.json`, `--noEmit -p tsconfig.node.json`, `--noEmit -p tsconfig.e2e.json`). Never used `tsc -b` from agent.
- **C26:** Kept `"tsBuildInfoFile": "./node_modules/.tmp/tsconfig.e2e.tsbuildinfo"` so CI's `tsc -b` writes build info to the ignored path.
- **C27:** Files block shrunk to `findings-drawer.spec.ts:87` + new `.d.ts`. No edits to `slide-viewer.spec.ts` or `slide-surface-fidelity.spec.ts`. ESLint baseline: 25 errors in 12 files (unchanged).
- **C3 (I1):** Dropped `verbatimModuleSyntax`. Python guard asserts it is absent.

---

## Gates

| Gate | Result |
|---|---|
| `tsc --noEmit -p tsconfig.app.json` | EXIT 0 |
| `tsc --noEmit -p tsconfig.node.json` | EXIT 0 |
| `tsc --noEmit -p tsconfig.e2e.json` | EXIT 0 |
| `tsc -b` (CI form) | EXIT 0 |
| No un-ignored tsbuildinfo in `git status` | PASS (build info at `node_modules/.tmp/tsconfig.e2e.tsbuildinfo`) |
| Python guard (3 tests) | 3/3 PASS |
| Vitest | 21 files / 1099 tests PASS |
| ESLint `tests/` | 25 errors in 12 files (baseline, no regression) |
| Full unit suite | 2 failed (deploy_autoscaling baseline) / 7174 passed / 110 skipped |

---

## Mutation table

| ID | Mutation | Scope | Predicted RED | Actual |
|---|---|---|---|---|
| M-R1 (reviewer) | Delete `{"path": "./tsconfig.e2e.json"}` from `tsconfig.json` references | `frontend/tsconfig.json` | Python guard `test_tsconfig_json_references_tsconfig_e2e` fails; `tsc --noEmit -p tsconfig.e2e.json` stays GREEN | CONFIRMED: 1 FAILED (guard), tsc EXIT 0 |
| M-E1 (typecheck proof) | Re-introduce `[f]` at `findings-drawer.spec.ts:87` | `frontend/tests/e2e/findings-drawer.spec.ts` | `tsc --noEmit -p tsconfig.e2e.json` reports TS2740 | CONFIRMED: TS2740 at line 87, EXIT 2 |
| M-R1 restore | Restore `tsconfig.json` reference | — | GREEN | CONFIRMED: EXIT 0, guard 3/3 PASS |
| M-E1 restore | Restore `= f` at line 87 | — | EXIT 0 | CONFIRMED |

**Note:** The controller sabotage (re-introduce `verbatimModuleSyntax`) was NOT run — that is the controller's sabotage, not the reviewer's.

---

## Deviations

None. All corrections (C25, C26, C27, C3/I1) applied as specified.

---

## Concerns

None. The `declare module '/src/*';` wildcard suppresses all 9 TS2307 errors for browser-side `/src/**` dynamic imports (measured: 10 errors without `.d.ts`, 1 error with it). The single remaining error (TS2740) was fixed at its cause without a cast.

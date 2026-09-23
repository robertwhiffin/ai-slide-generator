# SDD ledger — plan: docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md

Task 0 phase A: started at `0cfc80472d74c83d37b1281c9faad872cdb033bc`; worktree clean, `.venv` absent, shared interpreter only.
Task 0 phase A: reviewed authority includes scoped approval `plan-rereview-500ae52ea.md`; zero Critical/Important findings.
Task 0 phase A: SDK re-probe matched 0.112.0 (`list(self)`, `get(self, name)`, `foundation_model` present); Task 1 paths absent.
Task 0 phase A: baseline 22 passed / 0 skipped with five recorded pre-existing warning causes; no install or environment mutation.

Plan task self-consistency scan:

| Task | Declared output against declared tests/consumers | Finding / required order |
| --- | --- | --- |
| 0-A | Produces pre-integration history, Task-1 base, seam inventory, and cause baseline only | Clean; final implementation base must remain absent. |
| 1 | Produces catalog/policy/fake in two new files; focused tests cover discovery, local policy, remote validation, and typed failures | Clean; only pre-integration implementation task. |
| 2 | Consumes Task 1 plus the future integrated #263 writer and produces ordered local/stale/remote/write validation | Internally coherent, but intentionally unavailable until Task 0-B. |
| 3 | Consumes Task 1 and integrated admin authorization/route seams; creates read-only discovery route | Internally coherent; serialized after Task 2 composition. |
| 4 | Consumes Task 3 and integrated #263 editor state; creates discovery UI without a second writer | Internally coherent; exact owners must be re-probed in Task 0-B. |
| 5 | Consumes Task 1 plus integrated #261/#264/#265 runtime/workbench; creates saved-candidate probe | Internally coherent; blocked until integrated owners exist. |
| 6 | Consumes Tasks 4–5 and the integrated single pending-operation gate; proves browser recovery and whole matrix | Internally coherent; final task only. |

Plan pairwise producer/consumer/shared-seam scan:

| Tasks | Producer -> consumer / shared file | Finding / required order |
| --- | --- | --- |
| 0-A -> 1 | Corrections/history/baseline -> two new catalog files | Sequential; clean. |
| 1 -> 2 | Pure name policy and remote catalog validator -> one #263 save pipeline | Sequential; Task 2 waits for local integration. |
| 1 -> 3 | Catalog port/failure types -> admin GET route/DTO | Sequential; route must not create another catalog. |
| 2 -> 3 | Composed writer/facade -> unchanged #263 PUT plus new read-only GET | Sequential shared route/composition owners. |
| 3 -> 4 | Exact GET contract -> strict client parser and local-search UI | Sequential backend contract before UI. |
| 1/2 -> 5 | Exact endpoint plus integrated saved candidate -> structured-output probe | Sequential; probe accepts no client endpoint override. |
| 4/5 -> 6 | Catalog/editor plus probe -> one browser/state-machine proof | Sequential shared client/editor/E2E owners. |
| 2/3/5 | `graph_configuration*`, admin schema/route tests | Same integrated files; never parallelize within #266. |
| 4/6 | `agentDefinitions.ts`, Definition editor, mocks, component/E2E tests | Same frontend owners; strictly sequential. |

Task 0 phase A: Ruling: Tasks 2–6 remain plan-reviewed but execution-blocked until the mandatory integrated-code Task 0-B scan is appended to `PLAN-CORRECTIONS.md`. Cost if wrong: dispatching them now would build against missing #264/#265 interfaces and invalidate review ranges.
Task 0 phase A: complete (execution artifact only; no implementation commit).
Task 1: implementer DONE at `3b6542cacee893a4a8e6409e6aff0a3b65aa3926`; exactly two authorized files, focused 19 passed / 0 skipped, Ruff and `git diff --check` clean, with the five baseline warning causes unchanged.
Task 1: controller sabotage replaced the executed served-entity foundation-model classification with the endpoint `task` heuristic (`TASK1_CONTROLLER_TASK_HEURISTIC_SABOTAGE`); the exact discovery test failed because only `task-only` was returned, restoration removed the marker, and the same test passed. This target is distinct from the implementer's URL-prefix-policy sabotage and leaves exact detail-name equality to the reviewer. Evidence: `task-1-controller-sabotage.md`.
Task 1: reviewer independently removed exact returned-name equality (`TASK1_REVIEWER_EXACT_NAME_SABOTAGE`); the alias-response test failed, exact restoration removed the marker, and the same test passed. Spec Compliance APPROVED; Task Quality APPROVED; no Critical, Important, Minor, or ⚠️ findings.
Task 1: complete (commits `0cfc804..3b6542c` plus report/review evidence commits, review clean).

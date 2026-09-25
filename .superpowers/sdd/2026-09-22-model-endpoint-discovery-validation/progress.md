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

## REBASED onto c040dbde0
Date: 2026-09-25, run by the Task 0 phase B agent, which dispatched no subagents.
- Pre-flight triple check was clean: `git status --porcelain`, `git diff HEAD` and `git diff --cached` were all empty. HEAD was `ce10838ac9951fb3728029cb42db56dbd0cb8efc`, 184 behind and 15 ahead of `feat/langgraph-core`. `.venv` was absent.
- Tag `backup/266-pre-rebase-ce10838ac` points at `ce10838ac9951fb3728029cb42db56dbd0cb8efc`. It is a tag (`git cat-file -t`), not a branch.
- `git rebase --onto c040dbde0 a94c907d2db75e53743289651443fe9583bfa8f7 plan/model-discovery-266` applied 15 of 15 commits with no conflict. New HEAD is **`c5de240440b161bf31adbd205924f210ee5818d7`** (`TASK1_REBASED_HEAD`).
- Proof:
  - `git merge-base --is-ancestor c040dbde0 HEAD` returned 0.
  - `git rev-list --left-right --count c040dbde0...HEAD` returned `0 15`, so the branch is 0 behind.
  - `git rev-list --merges c040dbde0..HEAD` is empty.
  - `git range-diff a94c907d2..ce10838ac c040dbde0..HEAD` shows 15 of 15 as `=` and **zero `!`**. The full mapping is in PLAN-CORRECTIONS correction 1.
  - `git diff --name-only c040dbde0 HEAD` versus `git diff --name-only a94c907d2 ce10838ac`: `comm -23` and `comm -13` are both empty. There are 17 paths, and all 17 blobs are byte-identical between `ce10838ac` and HEAD.
- Task 1 survives the rebase: `test_model_endpoint_catalog.py` gives 19 passed, the same as its review. With `test_agent_runtime.py` and `test_ci_collects_integration_tests.py` added, the result is 64 passed, 0 failed, 0 skipped. Ruff is clean. Import provenance for `src`, `databricks_tellr` and the catalog module is in this worktree.
- `IMPLEMENTATION_BASE=c040dbde087e1c9ff4bc07656b74b3d09aa06300`. The merged predecessor heads #260 `29e03411`, #261 `e9ab7f93`, #263 `1d706e21`, #265 `7eaf58f0` and #264 `e3aa3650` are all ancestors. See correction 1, which also records that the phase-A #265 and #264 head SHAs are superseded.

## Task 0 phase B: COMPLETE
Date: 2026-09-25. Evidence is in PLAN-CORRECTIONS.md under "Task 0 phase B — integrated-code re-probe", **corrections 1–23**. They are appended to, not replacing, phase A.
- SDK: `databricks-sdk` **0.112.0**, re-probed live. `list(self)`, `get(self, name)` and `get_open_api(name)` are as expected. `query` has no `response_format`. `ServedEntityOutput.foundation_model: Optional[FoundationModel]`. The state enums match. There is no `system_ai` attribute.
- **Blocking defects that Task 2's brief must carry:**
  - **c3:** the catalog maps only `DatabricksError`. SDK transport exhaustion raises builtin `TimeoutError`, measured, so both list and get escape as 500s.
  - **c4:** `get(name)` interpolates the name into the path unescaped. `../../2.0/...` normalises to another workspace API under the service principal, measured with no network. The policy must reject path metacharacters.
  - **c6:** both validator tuples are class-wide, so registering there would run endpoint checks on both upgrades. The upgrade UI then drops inline endpoint issues, making them invisible. Ruling: a save-only composition; the class tuples and #264's guard `:2107` stay untouched.
  - **c7:** a measured 134-test radius for any default remote validator. Ruling: constructor injection with a `None` default, and production wiring in Task 3 with a sabotage-proved wiring test.
- Other corrections: c5 writer (CONFIRMED) · c8 lock held across remote I/O with the SDK's 300 s retry (parked for a **user decision**) · c9 routes, schemas and admin (CONFIRMED) · c10 five-leaf body only for v1/no-overlay roles · c11 runtime binding (CONFIRMED four-argument `run`; `invoke` collapses `PermissionDenied`; one-binding guards force the helper into `agent_runtime.py`) · c12 `probe(configuration)` · c13 probe read must release its FOR SHARE locks before invoking, plus a new PostgreSQL proof · c14 `test_graph_configuration_workbench.py` has never existed, so Task 5 creates it · c15 one reducer, counter and gate (Probe joins as `'probe'`; catalog stays out) · c16 catalog state hoisted to `AgentDefinitionWorkbench.tsx` · c17 the harnesses route by method (a measured list of GET-count and locator sites) · c18 endpoint 422 binding already landed · c19 text-read and strict-JSON joins · c20 CI enrolment unchanged · c21 scans · c22 baselines · c23 pre-briefs.
- Cause baselines at `c5de24044`:
  - Unit: 6 failed, 5900 passed, 110 skipped, run twice. The failures are exactly the controller's set by traceback: autoscaling ×2; `_FakeSession.execute` ×3 at `conversation_pins.py:79`; no active Graph Release ×1 at `:83`.
  - Skips: 105 huashu/node/Chrome, 1 RLIMIT on macOS, 3 RC-guard documented, 1 opentelemetry.
  - Focused #266 matrix: 620 passed, 0 failed, 0 skipped. Two files are absent by design (c14).
  - PostgreSQL, eight files each invoked separately: 2, 7, 7, 1, 2, 15, 10 and 1, totalling 45 passed with 0 skips.
  - Warnings: the same five locations as phase A.
  - Frontend: Vitest 14 files with 333 passed; `tsc -b` exit 0; eslint exit 0; Playwright workbench spec 60 passed. Port 3000 was empty before and after, and nothing was left running.
- The only temporary source mutation was the c7 radius probe `PHASEB_RADIUS_PROBE`. It was restored byte-exact (md5 `77cd8c49…` before and after, marker absent, tree clean, 121 re-passed). No install ran, no `.venv` was created, the dev database was untouched, and no other worktree was written.
- **GO for Task 2**, conditional on the Task 2 brief attaching corrections 1–23 and carrying c3, c4, c6 and c7 as its pre-briefed defects. c8 is a user decision that does not block Task 2.

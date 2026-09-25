# SDD ledger — plan: docs/superpowers/plans/2026-09-23-agent-test-case-runs.md (user's untracked draft in the main worktree)

- **Overrides:** `PLAN-CORRECTIONS.md` in this directory overrides the plan. The user's earlier `2026-09-23-agent-test-case-runs-CORRECTIONS.md` (7 items, against `d72ad974d`) is re-verified and carried forward as Corrections 1–7.
- **Worktree:** `.worktrees/issue-267-plan`. **Branch:** `feat/agent-test-case-runs-267`. **Code base:** `c040dbde0` (local `feat/langgraph-core`, with #259–#265 integrated).

## 2026-09-25 — Task 0 phase A: corrections pre-pass and cause baseline

**Pass:** 28 corrections.
- 18 blocking for their named task (Correction 10 also gates Task 4): 1, 2, 3, 8, 9, 10, 11, 12, 13, 15, 16, 17, 19, 20, 21, 22, 23, 25.
- The rest are advisory.
- Five binding carry-forwards were recorded:
  - Correction 8: no lock across a model call (#269 C13/I11);
  - Correction 9: last-required-case refusal (#269 C1 knock-on);
  - Correction 10: builder payload parity;
  - Correction 11: scope and verdict DDL;
  - Correction 12: `run_candidate` goes through `_run_resolved`, not `run`.

**Baseline by cause at `c040dbde0`:**
- **Unit:** 6 failed, 5881 passed, 110 skipped. The failures are exactly the known set: `test_deploy_autoscaling` ×2, `test_style_exclusivity_chokepoint` ×3 (`_FakeSession` has no `execute`), and `test_style_exclusivity_persistence_boundary` ×1 (no active Graph Release).
- **Focused:** 724 passed, 0 skipped.
- **PostgreSQL** (one file per run, 0 skips): bootstrap 2, constraints 7, workbench 15, overlay 10, runtime failures 7.
- **Frontend:** not run.

**Re-probes of volunteered facts:**
- "The seed is bootstrap-hashed" is **false as worded**. The payload is test-pinned and first-boot-verified, and it is already persisted. Nothing hashes it. The not-editing-the-seed conclusion stands for that reason.
- "#266 owns token-usage capture" (plan :50) is **false**. #266's plan has no usage capture.
- #264's gate SHA `ac69f62b6` is not an ancestor even though #264 is merged. This is the same class of problem as ADVISORY-3.

**Controller rulings:**
- Keep the four execution statuses, with an exact mapping.
- Add `run_kind`, `model_payload` and `assembled_prompt` columns.
- `compared_*` columns are NOT NULL.
- Keep a single router under `/api/admin/agent-definitions`. #268's verdict path follows it.
- Delete Task 7, because #264 and #265 are integrated.
- Case writers take L2 `FOR UPDATE` only (answers #269 Q9 for case writers).
- Keep the `-1` sentinels, defined in `agent_runtime.py`.
- Cost if wrong: see PLAN-CORRECTIONS §9.

**Gates:**
- **Task 1:** conditional GO after #266's reviewed local merge, a rebase, a recorded `IMPLEMENTATION_BASE`, a re-derived cause baseline, and a re-probe of Corrections 3, 12, 15 and 23.
- **Task 4:** NO-GO until `fix/builder-owner-session-id` is merged locally.
- **Task 8:** waits for #266's structured-binding helper.

**Deferred:**
- Product questions P1–P9 (PLAN-CORRECTIONS §10) go to the user.
- Hand to #268's pre-pass: the verdict route path, and a recommendation that readiness filters on `run_kind`.
- Hand to #269's Task 0-B: the fake adapter location, the verdict column list, the transaction-2 lock statement, and the case-writer lock.
- Out of scope, noted for the whole-branch review: the existing `test_postgres_restricts_deletion_of_referenced_release_and_revision` passes through the 23514 immutability trigger, so it does not prove the FK.

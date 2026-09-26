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

## User decisions and controller rulings — 2026-09-25
User decisions: P1 — the published baseline is shown as soon as it exists (newest completed published-baseline run), labelled "not approved" until approved; P2 — a case `name` is its immutable identity; P3 — replacing a case is two actions (add the new case, then retire the old; the last-required-case guard makes the order matter); P6 — session identifiers are stripped from EVERY role's model payload, not only the builder's (delivered as a separate reviewed change on `feat/langgraph-core` before #267 Task 4).
Ruling: P4 — the only approval gate in #267 is the runtime's schema validation; role-specific deterministic checks are deferred. Cost if wrong: approvals accept schema-valid but semantically poor output until checks are added.
Ruling: P5 — admins may run only active case versions. Cost if wrong: historical versions cannot be re-run from the UI.
Ruling: P7 — the synthetic-data rule is a UI warning, not server-enforced. Cost if wrong: a real-customer payload can be saved deliberately.
Ruling: P8 — no rate or cost limiting in #267; recorded as an epic follow-up. Cost if wrong: an admin can run many live model calls.
Ruling: P9 — NULL token usage is acceptable evidence, displayed as "not reported". Cost if wrong: cost reporting has gaps for endpoints that omit usage.
Controller correction: the earlier ledger claim that the builder seed payload is "bootstrap-hashed" was false as worded (correction 10 here): it is test-pinned and first-boot-checked, not hashed.
Status: `fix/builder-owner-session-id` merged locally at `6cbab388a`, so correction 10's Task 4 precondition is met; this branch must rebase onto the post-#266 integration head before Task 1.

## 2026-09-26 — rebase onto #266 and conditional-GO discharge (controller)

**Rebase:**
- The triple check was empty. Backup tag: `backup/267-pre-rebase-e06f78241`.
- Command: `git rebase --onto e91fcd856 c040dbde0`, which took `e06f78241` to `c7cb587c7`.
- `git range-diff`: both commits `=` (`e6bb42ff0`→`ac1168242`, `e06f78241`→`c7cb587c7`).
- The branch is 0 behind, and the name-only diff is the same two ledger files.
- **IMPLEMENTATION_BASE=e91fcd856.**

**Corrections 29–40** (PLAN-CORRECTIONS §12):
- **CONFIRMED:** 29, 30 (C3), 31 (C12; C14 is now integrated at `run` `:604-608`), 34 (C15), 35 (C17 = #264's `validate_output` `:511`, called once at runtime `:710`), 39 (baseline).
- **CORRECTED:**
  - 32: reuse #266's probe read path by extraction, not a parallel copy. Candidate runs carry `lock_version`. Transaction 1 becomes two short reads.
  - 36: model-calling routes are async and use `run_in_threadpool`, with loop-observer tests.
  - 37: an all-role projection in `agent_model_payload.py`. `nodes.py` is untouched. The key sets move to `tests/fixtures`. The seed is unedited.
  - 38: keep `\brun\b` and exempt two names. Naming rules avoid collisions with #266's names. mocks.ts and agentDefinitions.ts text-read rules.
  - 40: the §6 table.
- **NEW DEFECT:** 33. A test run inherited the production adapter's unbounded provider window inside an admin request. The fix is a bounded `get_agent_test_runtime()` through an additive `DatabricksModelAdapter(transport_options=)`. #267 does not borrow the probe's 403/422/503 classification: a provider failure is a persisted `model_error` run.
- **Blocking:** 29–39. 40 is advisory.

**Baseline at `e91fcd856`, by cause:**
- **Full unit** (with `DATABASE_URL=sqlite:////tmp/t267-base.sqlite`): 6 failed, 6175 passed, 110 skipped, 136 warnings. The same six nodes and causes as at `c040dbde0`: `test_deploy_autoscaling` ×2, chokepoint `_FakeSession.execute` ×3, persistence-boundary "no active Graph Release" ×1. The warning count went +1, and none of the warnings is in a #266 or #267 file.
- **Focused:** 865 passed and 0 skipped for the ten files. The five #266-shared files: 167 passed.
- **PostgreSQL:** bootstrap 2, constraints 7, workbench 17 (+2 from #266), overlay 10, runtime failures 7, with zero skips.

**Rulings:**
- 120 s and 0 retries is the test-run transport bound (C33). Cost if wrong: a healthy but slow builder call is persisted as `model_error`, and can be run again.
- Candidate runs are lock-pinned like the probe (C32). Cost if wrong: an admin approves evidence for a candidate that is not on their screen.
- `nodes.py` is not routed through #267's union (C37). Cost if wrong: none to production. Parity is held by the fixture-equality test.

**Gate: Task 1 GO.** The four §11 conditions are discharged, and Task 1's files are byte-unchanged since `c040dbde0`. The Task 4 external gate is also discharged. Task 4's brief must carry 32, 33, 36 and 37.

## Task 0 (DDL) — 2026-09-26
Task 0: implementer DONE_WITH_CONCERNS at `4d685d03d` (TASK_BASE `a14309016`): `c80ab897f` `AgentTestRun` / `GraphReleaseTestRun` (named RESTRICT FKs incl. composite revision FK, 11+2 checks, 2 indexes, exports, C24 evidence-immutability trigger), `17cf746ec` PG NOT NULL proof. Implementer gates: focused 1051; full `tests/unit` (DATABASE_URL sqlite) 6 failed (baseline) / 6194 / 110; PG constraints 59, bootstrap 2, workbench 17, overlay 10, runtime failures 7, zero skips; 48-row mutation sweep all RED. `create_all` + `_run_migrations` twice on SQLite and PG: 41 tables, no index-name collision.
Ruling: concern 1 ACCEPTED — the evidence JSON columns use `JSON(none_as_null=True)` / `JSONB(none_as_null=True)` (a deviation from C19's letter) because plain JSON stores Python `None` as JSON `'null'`, which bypassed `ck_agent_test_run_completed_has_output` and the NOT NULLs through the ORM. Cost if wrong: none observed; the existing tables' JSON columns keep the old behaviour (flagged for the whole-branch review).
Ruling: implementer ran both plan sabotage targets (controller: drop `AND deterministic_checks_passed` → RED 2; reviewer: CASCADE on `fk_agent_test_run_test_case` → RED 4). The reviewer gets a fresh target: widen the C24 trigger's exempt-column array (e.g. add `run_by`) — the immutability test must RED in PostgreSQL.
Task 0: controller sabotage (own seam) — `_EVIDENCE_JSON_DOCUMENT` reverted to plain `JSON()`/`JSONB()` (`CTRL267_0_NONE_AS_NULL`, anchor 1). Scope `tests/unit/test_graph_configuration_models.py`: GREEN 27 → RED 2/27 (`test_semantic_columns_use_json_variants_numeric_decimals_and_database_timestamps`, `test_sqlite_rejects_each_agent_test_run_check_violation[ck_agent_test_run_completed_has_output-9]`). Restored from pinned HEAD, marker 0, clean, GREEN 27.
Carry to #268 and #269 corrections (from the implementer): add `run_kind='candidate'` to #269's approval query (plan :727-735) and #268's readiness query; #269's ORM fallback must supply `run_kind`, `model_payload`, both `compared_*` and `deterministic_check_results`; #269's C14 trigger coexists with `trg_agent_test_run_evidence_immutable` and its idempotence test must expect both; verdict columns are `verdict`, `verdict_reviewer`, `verdict_at`, `verdict_notes`.
Task 0: review `task-0-review.md` (Opus): spec ✅, quality APPROVED — 1 Important (I1: the immutability test rewrites only 17 of 23 non-verdict columns; exempting `id`, `test_case_id`, `agent_key`, `compared_release_id`, `compared_definition_revision_id`, `run_at` left 59/59 GREEN), 4 Minor. Reviewer sabotage: `run_by` exempted RED 1/59; role-compatibility dropped from the composite FK RED 1/27 unit + 1/59 PG. Trigger verified in a throwaway PG14 DB (NaN floats, nested JSONB, non-UTC TimeZone, ORM flush; idempotent across three migrations).
Ruling: M1 (an approved `published_baseline` run is allowed by the DDL) — NO check added: user decision P1 implies baselines can later be approved; #268's readiness and #269's gate filter `run_kind='candidate'` (already carried). Cost if wrong: a query that forgets the filter counts a baseline approval as candidate evidence.
Task 0: minor (deferred): M2 `verdict_reviewer` has no non-blank check and `verdict_notes` can exist without a verdict; M3 nothing ties the run's `test_case_version`/`agent_key` to its case row (Task 4 service test); M4 SQLite FK tests match only "FOREIGN KEY" (PG 23503 tests carry the proof); #268/#269 fixtures must not make a run stale by updating the run row (trigger rejects it).

## Task 1 — 2026-09-26
Task 1: implementer DONE at `69cba58b4` (base `8b73793c2`): AC1 guard tests + PG seeding identity test. Controller finding (Important): narrowing the guard to drop `deck_reviewer` left `tests/unit/test_graph_configuration_bootstrap.py` 21/21 GREEN — only architect and data_analyst were pinned.
Task 1: fix round 1/5 (1 addressed, 0 open — one test parametrised over all seven roles plus an un-required-but-active variant; commit `1e67a90b7`). Implementer sabotage: dropping each role in turn REDs exactly that role's case (7/7); removing the `is_required` filter REDs the un-required variant.
Ruling: no scoped re-review subagent — test-only, one file; controller re-measured with a different role than the implementer's report emphasised: guard ignoring `fixer` (`CTRL267_1_DROP_FIXER`, anchor 1) → RED 1/27 `test_ac1_integrity_guard_rejects_deactivated_role_case[fixer]`, restored from pinned HEAD, clean. Cost if wrong: an unreviewed 1-file test diff reaches the whole-branch review.
Task 1: complete (commits `8b73793c2..1e67a90b7`, review clean after 1 controller-found fix round). Implementer gates: bootstrap unit 27; PG bootstrap 3 zero skips; full `tests/unit` 6 failed (baseline) / 6202 / 110.

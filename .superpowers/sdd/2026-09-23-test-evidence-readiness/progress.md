# SDD ledger — plan: docs/superpowers/plans/2026-09-23-test-evidence-readiness.md (user's untracked draft in the main worktree)

- **Overrides:** `PLAN-CORRECTIONS.md` in this directory overrides the plan. The user's `2026-09-23-agent-test-case-runs-CORRECTIONS.md` has one #268 item, ADVISORY-4 (no publication method). It was re-verified and is superseded by Correction 1.
- **Worktree:** `.worktrees/issue-268-plan`. **Branch:** `feat/test-evidence-readiness-268`. **Code base:** `b0c4d8aeb` (#267's reviewed head).
- **Pending:** a rebase onto the #267 merge into `feat/langgraph-core`, which happens after #267's token-usage fix wave. `IMPLEMENTATION_BASE` is not yet recorded (Correction 2).

## 2026-09-26 — Task 0 phase A: corrections pre-pass and cause baseline

**Pass:** 30 corrections.
- **Blocking (24):** 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27.
- **Advisory:** 2, 14, 21, 28, 29, 30.
- **Binding inputs recorded as corrections:**
  - #269 Q1 scope → C1;
  - #267 verdict columns and checks → C3;
  - the C24 trigger → C8 and C13;
  - `run_kind` → C12 and C19a;
  - the verdict route path (#267 C23) → C15;
  - the strict evidence model and parser → C16;
  - case versioning and the unfiltered lock → C11, C19g (#269 C29);
  - the fake adapter → C8;
  - the history route → C3;
  - `TestRunPanel`, one reducer and one gate → C24;
  - P1 → C9 and C26;
  - #269 C13 (no model call) → C27.

**Baseline by cause at `b0c4d8aeb`:**
- **Full unit:** 6 failed, 6616 passed, 110 skipped, 136 warnings. These are the known six by node and cause: `test_deploy_autoscaling` ×2, the chokepoint `_FakeSession.execute` ×3, and the persistence boundary "no active Graph Release" ×1.
- **Focused (the plan's six unit files):** 795 passed, 0 skipped. Extras (the join, workbench and CI files): 35.
- **PostgreSQL** (one file per run, zero skips): bootstrap 3, constraints 66, workbench 25, overlay 10, runtime failures 7.
- **Frontend:** not run (brief).
- `.venv` was absent before and after.

**Controller-level rulings in this pass** (each has its cost in PLAN-CORRECTIONS §14):
- C1: Task 5 is deleted, and so is Task 6 Step 4.
- C5: `not_completed` applies to both verdicts. This is settled by the issue's AC1; it is not a product question.
- C6: the verdict writer takes L3 only. This answers #269 Q9 for the verdict writer.
- C10: two readiness entry points; `readiness_under_parent_lock` is #269's Q4 binding.
- C11: any eligible approval makes a case ready, and the newest one is reported. This reconciles the plan's :146 and :464 with #269 Q5.
- C18: cleanup takes an L0 share lock on **both** parents. This answers #269 Q2.
- C19d: exclude protected runs, then rank. This gives #269 C19 outcome (a).
- C19e (**new defect, reasoned but not probed**): the cleanup DELETE must recheck eligibility on the target row. Task 4's RED must reproduce it.

**Hand to #269's Task 0-B:**
- the readiness binding name (C10);
- the cleanup signature and lock statement (C18);
- the verdict writer's L3-only lock, and its `IntegrityError` propagation (C6, C7);
- C19 outcome (a);
- that #269 C7's `ALLOWED_ACTION_NAMES` count is stale: after #268 it is 7, so #269 makes it 8 (C23);
- the readiness TS type names (C22).

**Deferred to the user:** product questions Q1, Q2, Q3, Q5, Q6 and Q7 (PLAN-CORRECTIONS §15).

**Gate:**
- **Task 1:** conditional GO once #267 merges. The conditions are the rebase and `IMPLEMENTATION_BASE`, the re-derived baseline, the Correction 3 re-probe (especially the evidence field set after the token wave), and a brief carrying C4–C9 and C27.
- **Task 5:** deleted.
- **Task 6:** can proceed on Q2's default.

## Controller rulings on the pre-pass's product questions — 2026-09-26
The user asked for autonomous progress without interruption; these are reversible defaults, recorded here and reported to the user for override.
Ruling: Q1 — cleanup ships as a service method with NO automatic caller in #268; an admin-triggered route or a schedule is a follow-up decision. Cost if wrong: unpublished runs accumulate until a trigger is chosen.
Ruling: Q2 — a role's badge is worst-first across its required cases (the pre-pass default). Cost if wrong: a label change.
Ruling: Q3 — an admin MAY record a verdict on a stale-candidate or retired-version run (it is truthful evidence); readiness ignores such approvals. Cost if wrong: harmless verdicts on runs that cannot unlock publication.
Ruling: Q5 — show the newest completed baseline, with its own verdict label; an older approved baseline is not preferred over a newer unapproved one. Cost if wrong: display only.
Ruling: Q6 — baseline runs are NOT subject to the 20-run candidate retention (C12/C19: cleanup is candidate-only). Cost if wrong: baseline rows accumulate slowly.
Ruling: Q7 — no verdict withdrawal back to "no verdict" in #268; a verdict can be changed (approve ↔ reject) while unlinked. Cost if wrong: an admin cannot clear a verdict, only flip it.
Pre-pass: 30 corrections (24 blocking). GO for Task 1 once #267 merges, conditional on rebase + baseline + C3 re-probe of the evidence field set after #267's token-usage fix wave.

## REBASED onto a08389ec3 (#267 merged) — 2026-09-26, controller
`git rebase --onto a08389ec3 b0c4d8aeb`: 2 of 2 commits `=`, 0 behind; backup tag `backup/268-pre-rebase-*`. IMPLEMENTATION_BASE = `a08389ec3`.
C3 re-probe after #267's token wave: `src/api/schemas/agent_definitions.py` unchanged between `b0c4d8aeb` and `a08389ec3` (evidence field set unchanged); `agent_test_workbench.py` changed only to persist `input_tokens`/`output_tokens` from the observation.
Baseline at the rebased HEAD (`DATABASE_URL=sqlite:///...`, `-q -p no:randomly -rf`): 6 failed / 6625 passed / 110 skipped — the same six nodes and causes.
Task 1: GO — conditions met (rebase, IMPLEMENTATION_BASE, baseline, C3). Task 1 brief carries C4-C9 and C27.

## Task 1 — 2026-09-26
Task 1: implementer DONE_WITH_CONCERNS at `262b65bf5` (TASK_BASE `f68635ea6`): `1ea3daeb2` `AgentTestWorkbench.record_verdict` (validate → own txn → `FOR UPDATE` run row only → not_completed / checks_failed refusals → identical re-submit writes nothing → one core UPDATE of exactly the four verdict columns with DB-clock `verdict_at`; no IntegrityError caught); `fcca6b4c4` hardens two tests its own sweep showed could not catch their mutation (FOR UPDATE removal; a `self._runtime()` call). Implementer gates: focused 611; full unit 6 (baseline) / 6666 / 110; PG constraints 66, workbench 31 zero skips; 17/17 mutations RED. Both plan sabotage targets already run by the implementer.
Ruling: concern 2 — core UPDATE instead of ORM assignment ACCEPTED (the ORM omits unchanged columns, breaking C6's exact four-column SET proof). Concern 1 — verdict fields reach the evidence response in Task 3 per C16. Concern 4 — a blank reviewer reports the reused `actor` field; Task 3's route mapping must know. Concern 3 — `populate_existing` unpinned: assigned as the reviewer's fresh target.
Task 1: controller sabotage (own seam) — `checks_failed` refusal replaced by `pass` (`CTRL268_1_CHECKS`, anchor 1, `agent_test_workbench.py:1248`). Scope `tests/unit/test_agent_test_workbench.py`: RED 2/185 (`test_an_approval_of_a_completed_run_with_failed_checks_is_checks_failed`, `test_a_rejected_failing_run_cannot_flip_to_approved`). Restored from pinned HEAD, clean.
Task 1: review (Sonnet): spec PASS, quality PASS with 1 Important — I1 `populate_existing=True` on the verdict lock pinned by nothing (removed → 185/185 GREEN; every test used a fresh session). Reviewer's own mutation (notes validated after the lock) RED 5/185. Named risks all clear (trigger coexistence, run-row-only lock, DDL/service eligibility agree, Q3/Q7, no model).
Task 1: fix round 1/5 (1 addressed, 0 open; commits `961d3753f..af0aef92e`, test-only): `test_the_lock_read_refreshes_a_run_already_cached_in_the_session` (holds a strong reference so the weak identity map keeps the stale object). Implementer sabotage: `populate_existing` removed → RED 1/186, restored GREEN 186; full unit 6 (baseline) / 6667 / 110; PG workbench 31 zero skips.
Ruling: no scoped re-review subagent — one test in one file, and the same mutation was independently measured twice (reviewer's fresh test and the implementer's committed one). Cost if wrong: small.
Task 1: minor (deferred to Task 3): verdict fields on the returned evidence (C16); blank-reviewer issue field is `actor`.
Task 1: complete (commits `f68635ea6..af0aef92e`, review clean after 1 fix round).

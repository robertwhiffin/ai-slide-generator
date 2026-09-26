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

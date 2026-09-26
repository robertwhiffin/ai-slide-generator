# SDD ledger — plan: docs/superpowers/plans/2026-09-26-lakebase-contract-and-epic-acceptance.md

This plan was drafted on 2026-09-26 by a planning agent on `plan/lakebase-contract-acceptance-271`, at base `a08389ec3` (Merge #267). It has Tasks 0–14.

- **Not yet plan-reviewed.** It is executable beyond Phase A (Task 0 phase A, Tasks 1 and 5) only after reviewed #268, #269 and #270 are merged locally and Task 0 phase B has run.
- **Phase A** is Task 0 phase A plus Tasks 1 and 5. These touch no file that #268, #269 or #270 own.
- **Phase B** is Tasks 2–4 and 6–14.
- **AC10 ordering:** Task 12 (the deletion) refuses to start until the Tasks 6–11 suites are green at its base SHA.

## Probes recorded while planning (read-only)

- **P1.** A typecheck of `frontend/tests/**` with a throwaway tsconfig (in `/tmp/probe271-ts`, using the main worktree's node_modules through a symlink) gives 12 errors:
  - 9 × TS2307 on `'/src/…'` browser imports;
  - 2 × TS2339 on `ImportMeta.env`;
  - 1 × TS2740 at `findings-drawer.spec.ts:87`.
- **P2.** Six unit failures at `a08389ec3`:
  - The deploy_autoscaling ×2 also fail on `main` `f6b1506c5`, so they are not caused by the epic.
  - The style_exclusivity ×4 pass on `main`, so they are caused by the epic: `create_session` requires an active Graph Release.

## Rulings made in the plan (for plan review)

- **In scope:**
  - the `frontend/tests` typecheck (Task 4);
  - log needles matching `pathname` (Task 2);
  - the dev-DB default in conftest (Task 1);
  - the style_exclusivity ×4 (Task 1);
  - declaring `openai` (Task 5).
- **Out of scope** (for the user to file as GitHub issues):
  - deploy_autoscaling ×2, which fails on `main`;
  - #266 m7, `tools/model_endpoint_tool.py:75`, which is the legacy tool path.
- **Conditional release gate:** #266 m9, pay-per-token `config_update` (Task 13). It needs the user's authorisation to read the dev workspace.

## Open questions

Q1–Q4 are listed at the end of the plan.

## Controller rulings — 2026-09-26
Controller check of the planner's "file changed on disk before commit" note: working tree clean; committed plan is 1005 lines and is the file on disk; no other agent works in this worktree. Nothing to reconcile.
Ruling: OQ1 — the conftest REFUSES to run a unit suite whose `DATABASE_URL` names `ai_slide_generator` (fail fast), and defaults to a throwaway SQLite URL when unset. Cost if wrong: a developer who deliberately points unit tests at the dev DB must override explicitly.
Ruling: OQ2 — deleting the now-unread authored prompt text in `src/core/skills` is OUT of #271's scope (a follow-up); protected constants stay. Cost if wrong: dead text remains for a while.
Ruling: OQ3 — a documented developer command to re-record the Playwright contract is acceptable (no new make target). Cost if wrong: none.
Ruling: OQ4 — the local merge of #271 may proceed with #266 m9 unverified; the epic is NOT reported shippable until the user authorises and the dev-workspace check passes. Surfaced to the user. Cost if wrong: none locally.
Ruling: the planner's follow-up split is accepted — style-exclusivity ×4 in scope (Task 1); deploy-autoscaling ×2 out (pre-epic, needs an issue); #266 m7 out (needs an issue); `openai` declared (Task 5); typecheck gap and log needles in scope.
Next: independent plan review before execution. Phase A (Tasks 0-A, 1, 5) is runnable at `a08389ec3`.

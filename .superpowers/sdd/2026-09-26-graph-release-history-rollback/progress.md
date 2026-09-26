# SDD ledger — plan: docs/superpowers/plans/2026-09-26-graph-release-history-rollback.md

The plan was drafted on 2026-09-26 by a planning agent on `plan/release-history-rollback-270`, at base `a08389ec3` (Merge #267). It has Tasks 0–10.
- **Not yet plan-reviewed.** It is not executable beyond Task 1 until reviewed #268 and #269 are integrated locally and Task 0 phase B runs.
- **Phase A:** Task 1 only, a lock-free history read model in a new module. It touches no #268/#269 file.
- **Phase B:** Tasks 2–9. Rollback is a thin caller of #269's `_commit_locked_publication`.
- **#269 interfaces:** every one (I1–I12 in the plan) is assumed from #269's plan plus its 30 corrections, and is re-probed at Task 0 phase B.

## Planner rulings

**Q7 (deferred from #269): three-way draft rebase.**
- Clean roles (candidate equals the pre-rollback active hash) reset to the restored content.
- Pending edits are kept.
- The parent is rebased once by the core.
- Basis:
  - §5.4 and §11.4 step 10 say "rebased".
  - User story 17 says no silent loss of saved edits.
  - §12's purpose is served: a parent-only rebase would leave v7's content changed-and-approved, ready to re-publish.
- The column-and-hash assignment is extracted from `_write_locked_content` into `_assign_locked_candidate`, so the draft keeps one content writer.
- User confirmation is requested (open question 1).
- Cost if wrong: the `_draft_effect` function, the reset loop, and their tests.

**Rollback refusals.**
- It refuses the active release (`409 rollback_source_active`).
- It refuses a mapping identical to the active one (`409 rollback_matches_active`).
- It refuses a structurally incompatible release (`422 rollback_incompatible`). The check runs the local validator tuples only, with no network call.

**Evidence linked on rollback.** Every candidate run linked to the selected source is linked, of any kind, as `historical_restore` with `source_release_id` set to the selected source. The source release's cases get no L2 lock. Its runs get an L3 `FOR SHARE` lock.

**No model or remote call.** Rollback makes no model, catalog, probe, or remote endpoint call. Tests prove this with must-not-run fakes.

**Frontend.** The frontend is a third tab on #269's page. It uses that page's one reducer, one counter, and one gate. `ALLOWED_ACTION_NAMES` is unchanged.

## Open questions for the controller

These are open questions 1–9 in the plan:
- Q7 confirmation;
- the no-op rollback refusal;
- evidence transitivity when the source was itself a rollback;
- v1's `changed_agents`;
- the forbidden sweep on #269's page, since parametrized names cannot be exempted exactly;
- the stale token (lock_version or active id);
- log content;
- the route module;
- structural-validation scope, where a removed endpoint is not checked.

## Before execution

Run an independent plan review against the issue, the design, #269's plan and corrections, and the code.

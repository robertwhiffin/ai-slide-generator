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

## Controller rulings on the planner's open questions — 2026-09-26
Ruling: OQ1 (Q7) — three-way draft rebase ACCEPTED: per role, a draft equal to the pre-rollback active content resets to the restored content; a pending edit is kept exactly. Reported to the user as a visible behaviour they may override. Cost if wrong: the rollback's draft effect differs from what admins expect.
Ruling: OQ2 — refuse a rollback to the active release, or to a mapping identical to the active one, with 409. Cost if wrong: a no-op rollback is refused rather than silently succeeding.
Ruling: OQ3 — link all of the selected source release's linked runs with `source_release_id` = the selected source (not the release that originally approved each). Cost if wrong: provenance points one hop short.
Ruling: OQ4 — for v1, `changed_agents` lists all seven roles. Cost if wrong: a display difference.
Ruling: OQ5 — exact whole-name exemptions only; controls must use FIXED accessible names (e.g. "Roll back to this version", "Inspect this version") scoped by their row, with the version number in visible text or a description, never a numbered accessible name. Cost if wrong: one Playwright locator style.
Ruling: OQ6 — keep the draft `lock_version` stale check (conservative: an unrelated draft save between preview and confirm forces a re-preview). Cost if wrong: an occasional extra 409 and retry.
Ruling: OQ7 — logs carry only the outcome code and role key names. Consistent with the user's log decision.
Ruling: OQ8 — #270 follows whatever router module #269 lands. Cost if wrong: none.
Ruling: OQ9 — rollback does NOT block on the remote endpoint check (no network call under the publication lock), but the rollback PREVIEW runs #266's bounded remote endpoint validation outside any lock and shows a warning for any restored endpoint that no longer resolves. Cost if wrong: an admin can still restore a removed endpoint after a warning; pinned conversations then fail as §15 describes.
Next: independent plan review, then corrections, before any execution (Task 1 Phase A is runnable at `a08389ec3`; Tasks 2+ wait for #268 and #269).

## Plan review 1 — 2026-09-26

**Verdict:** APPROVE WITH CORRECTIONS.

| Severity | Count |
|---|---|
| Critical | 1 |
| Important | 6 |
| Minor | 16 |
| **Total** | **23** |

**Correction numbers:** 1 (C1), 2 (I1), 3 (I2), 4 (I3), 5 (I4), 6 (I5), 7 (I6), 8 (M1), 9 (M2), 10 (M3), 11 (M4), 12 (M5), 13 (M6), 14 (M7), 15 (M8), 16 (M9), 17 (M10), 18 (M11), 19 (M12), 20 (M13), 21 (M14), 22 (M15), 23 (M16).

**Corrections that block Task 1 (Phase A — must be in Task 1's brief):**
- Correction 11 (M4): `populate_existing=True` in `list_release_history` code template.
- Correction 14 (M7): Task 0 Step 3 baseline loop must include three missing PostgreSQL files and one unit file before the baseline is recorded.

**Corrections that block Phase B (after #268/#269 integration, before named task):**
- Before Task 2: Corrections 1 (C1), 2 (I1), 12 (M5), 20 (M13), 22 (M15).
- Before Task 3a: Corrections 15 (M8), 16 (M9), 18 (M11), 19 (M12), 21 (M14).
- Before Task 4: Correction 6 (I5).
- Before Task 6: Correction 13 (M6).
- Before Task 7: Corrections 3 (I2), 4 (I3), 23 (M16).
- Before Task 8: Correction 7 (I6).
- Before Task 9: Correction 5 (I4).

**Non-blocking (apply in named task):** Corrections 8 (M1), 9 (M2), 10 (M3), 17 (M10).

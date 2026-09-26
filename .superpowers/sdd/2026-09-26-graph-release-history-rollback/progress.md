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

## Task 0 phase A — 2026-09-26

- **TASK1_BASE** = `dbbea85e1` (file `TASK1_BASE`). `a08389ec3` is an ancestor; src/tests/frontend/packages/.github identical to it. Python 3.11.0; no `.venv`.
- **Implementation facts (re-verified at a08389ec3, all match the plan's lines):** `GraphRelease` models:193 with a non-deferrable partial unique one-active index (two active rows are unrepresentable on both backends; zero active is the reachable integrity case); `GraphReleaseTestRun` :493; `AgentTestRun.run_kind` check :453–454; guards database.py:935 (release first-close only :1019–1020, deferred exactly-one :1110); `validate_definition_hash` graph_configuration_content.py:128; `GRAPH_V1_AGENT_KEYS` manifest:66; `_publish_v2` recipe test_conversation_pin_acceptance_postgres.py:125; `postgres_engine` conftest:235. SQLite returns naive datetimes, PostgreSQL aware; the read model returns them as stored.
- **Unit baseline (full tests/unit):** 6 failed / 6625 passed / 110 skipped. The 6 expected nodes; causes: deploy_autoscaling ×2 (`'provisioned' == 'autoscaling'`; provisioned mock not called), style_exclusivity_chokepoint ×3 (`'_FakeSession' object has no attribute 'execute'`), persistence_boundary ×1 (`ConversationGraphReleaseIntegrityError: no active Graph Release`). None touches #270.
- **PostgreSQL baseline (Correction 14's corrected loop, 11 files, one invocation each):** all green, 0 skips (159 tests). Detail in `reports/preflight-phase-a.md`.

## Task 1 — 2026-09-26 — DONE (`d0e4d693a`)

- `src/services/graph_release_history.py` (lock-free; first statement `select(GraphRelease).order_by(version_number.desc()).execution_options(populate_existing=True)` per C11; every later statement filtered to that id set; evidence read filtered to `run_kind='candidate'` plus a filtered/unfiltered link-count comparison; no logging; no model/runtime import). Unit file (17 tests), PostgreSQL file (4 tests, 0 skips), CI enrollment in `test.yml` and a pin test in `test_ci_collects_integration_tests.py`.
- Gates: full unit 6 failed / 6643 passed / 110 skipped, the same 6 nodes and causes as baseline (+18 new passes); 12 PostgreSQL files 163 passed, 0 skips; ruff no new findings vs base.
- 23 clause mutations, each anchor=1, marker grep -c=1, probe-proven executed, RED, restored byte-identical (grep -c 0, `git diff --exit-code`). Controller sabotage (changed vs own mapping) REDs `test_history_lists_every_version_newest_first_with_exact_lineage` (+2 PG tests); reviewer sabotage (`restored_from=ref(previous_release_id)`) REDs the lineage test on SQLite and `test_history_reads_under_guards_and_restored_lineage_is_exact` on PostgreSQL, observing `Ref(v3)`. Report: `task-1-report.md`.
- Deviations from the plan text: see report "Deviations". Phase A ends; Task 2 waits for Task 0 Step 4 (phase B).

## Task 1 — controller record, 2026-09-26
Task 1: implementer DONE at `a2d62e43b` (TASK1_BASE `dbbea85e1`): `d0e4d693a` `src/services/graph_release_history.py` (lock-free; first statement fixes the release set with `populate_existing`; later reads filter to it; candidate-only evidence with a filtered-vs-unfiltered link count so a non-candidate link raises) + 17 unit and 4 PG tests + CI enrolment. Implementer gates: full unit 6 (baseline) / 6643 / 110; 12 PG files 163 passed zero skips; 23 mutations RED incl. both plan targets. The implementer found and fixed a hang (a lock regression deadlocked in-process; the publisher now sets `lock_timeout='5s'`) and dropped the one throwaway DB it leaked (`tellr_int_e17103e7d3d64c34`), attributed by its unique actor; four older `tellr_int_*` DBs are not its and were left.
Ruling: deviations ACCEPTED — the plan's two-active-releases case is unbuildable (partial unique index), replaced by a zero-active case (RED via M05); references outside the first-statement set raise `GraphConfigurationIntegrityError` rather than `KeyError`; datetimes returned as stored (Task 6's wire normalises). Cost if wrong: none observed.
Task 1: controller sabotage (own seam) — drop `AgentTestRun.run_kind == "candidate"` (`CTRL270_1`, anchor 1, `graph_release_history.py:251`). Scope `tests/unit/test_graph_release_history.py`: RED 1/17 `test_linked_non_candidate_run_is_an_integrity_error`. Restored from pinned HEAD, clean.
Task 1: review (Sonnet): spec PASS, quality PASS — 0 Critical, 0 Important, 2 observations (evidence read filtered by `== entry.release_id`, safe under insert-only release-scoped links; two-active deviation covered by zero-active + populate_existing tests). Reviewer sabotage: remove `populate_existing` → RED 1/17 (`test_history_refreshes_a_release_already_loaded_in_the_session`); remove mapping `in_(ids)` filter → PG RED 2/4 (`test_history_is_coherent_when_a_release_commits_between_statements[list|detail]`, KeyError, 2.2 s, no hang). Restored clean; temp worktree removed; no PG databases leaked.
Task 1: complete (commits `dbbea85e1..a2d62e43b`, review clean, no fix round).

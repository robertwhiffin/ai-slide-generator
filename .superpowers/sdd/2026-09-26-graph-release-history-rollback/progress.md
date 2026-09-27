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

## Phase B start — 2026-09-27
#268 merged locally `16aa02b76`; #269 merged locally `c7ea1d943` (whole-branch review MERGE after 2 minor fixes). Rebased onto `c7ea1d943`: append-only conflicts in `.github/workflows/test.yml` (integration-graph list) and `tests/unit/test_ci_collects_integration_tests.py` — resolved keeping both sides; rebased Task 1 = `29df4c318`. Post-rebase: history PG 4/4, unit 17/17, CI collection green.
INTEGRATION_BASE = `c7ea1d943` (the #269 merge). `c7ea1d943..HEAD` code-wise = exactly the rebased Task 1 (`29df4c318`) plus docs.
Carried from #269 (BINDING for Phase B): (1) widen `evidence_kind` to include `historical_restore` AND add `source_release_id` to `ReleaseEvidenceResponse` (dataclass has it; wire drops it) — TS parser + `test_graph_release_client_join.py` change together; (2) restore must lock the source runs `FOR UPDATE ORDER BY id` before `link_release_evidence` (the linker takes no lock); (3) every L0/L1 lock is the first statement of a fresh txn (the L0/L1 statements lack `populate_existing`); (4) any both-parents lock goes through `_lock_current_parents` (AST scanner); (5) C33: re-check in a new statement after any lock wait; (6) publication 200 not 201; routes on the one admin router (C35).

## Task 0 phase B — 2026-09-27
- **Bases:** INTEGRATION_BASE `c7ea1d943` (Merge #269) is an ancestor of HEAD `7465854f4`; code-wise `c7ea1d943..HEAD` = the rebased Task 1 `29df4c318` only (other 7 commits docs). `predecessor-heads.md`: #268 merge `16aa02b76` / reviewed head `dd129b832`; #269 merge `c7ea1d943` / reviewed head `126ea2bb6` (last code `8666939de`); all ancestors of HEAD and `feat/langgraph-core`.
- **Re-probe:** corrections 24–47 appended to `PLAN-CORRECTIONS.md` (+ Task 2–9 self-consistency and producer/consumer tables). Errata: 37 → Correction 8 (handlers in `agent_definitions.py`, C35) and Correction 13's cite; 32 resolves 20(b); 33 resolves 12; 34 completes 2; 39 resolves 23 and confirms 4. #269 carries bound: (1) → 38 (Task 6, atomic Python+TS+join test), (2)+(5) → 28 (L3 `FOR UPDATE ORDER BY id`), (3)+(4) → 29, (6) → 37; m4 → 39.
- **Probe:** `/tmp/t270b/probe_restore.py` — the real core restores v2 as v4 with a `historical_restore` link and `restored_from = v2`, all seven reused, no new revision; parent-only rebase leaves architect `changed is True` (Q7 evidence).
- **Baseline (report `reports/preflight-phase-b.md`):** full unit 6 failed (the baseline six, same causes) / 6975 / 110; all 30 integration-graph files one per invocation, zero skips, all green (`test_shared_deck_mutation_attribution` 60 passed under `timeout 120` — the pre-existing hang did not reproduce; still recorded as pre-existing); Vitest GraphRelease+Workbench 778/778; typecheck clean. No `tellr_int_*` leaked (4 older only).
- **Forbidden actions:** `ALLOWED_ACTION_NAMES` = 8 and stays 8 (C40); no page-level sweep, OQ5 trigger not met.
- **Q7 (OQ1):** flagged for the user (C35); binds Task 3a dispatch.
- **Verdict:** GO for Task 2 once the controller adopts the proposed rulings in 32 (endpoint policy included), 33 and 34. Task 3a additionally waits on the Q7 confirmation/ruling (35).
Ruling (C32): ADOPT — rollback's structural validation = `_save_local_validators()` + post-stale validators, including #266's endpoint-name policy (same as #269 publication, C37). — the policy rejects path-injection-shaped names; any release published after #266 already passed it, and v1 comes from the manifest. — cost if wrong: a rollback to a pre-policy release with a now-invalid endpoint name is refused; the admin must fix it through a draft save + publish.
Ruling (C33, C34): ADOPT as proposed (reuse `_read_history` + extracted `_release_definitions`; preview's remote check runs after the lock-holding txn commits, once per distinct endpoint; plain `def` route).
Ruling (C38): SIGN-OFF — widening `ReleaseEvidenceResponse` (restore kind + `source_release_id` + pairing validator, publish stays approval-only) edits #269's join test, route body test and TS fixtures in ONE Task 6 commit. — a deliberate contract extension, not a loosening. — cost if wrong: small.
Ruling (C40): the forbidden-action count stays 8; no workbench "Release History" exemption.
Ruling (Q7 / C35): PROCEED ON THE DEFAULT three-way rebase (clean role → reset to the restored content; role with a saved unpublished edit → edit kept, still needs its own approval; role identical in both → nothing). Disclosed caveat: a kept edit that already had an approved run stays approved though reviewed against the rolled-back version. Surfaced to the user in the next status message for possible override; the user's standing instruction is to keep working autonomously. — cost if wrong: Task 3a's rebase semantics rework.
Task 0 phase B: complete (`202741fb1`). GO for Task 2.

## Task 2 — 2026-09-27
Task 2: implementer DONE_WITH_CONCERNS at `e4a473489` (TASK_BASE `e4385f487`): `624385f08` `src/services/graph_configuration_rollback.py` (`compare_with_active`, `preview_rollback`, `_load_source` → `_HistoricalSource`, `_structural_issues`, `_draft_effect`, `_historical_evidence`), facade base + 5 exports, `_release_definitions` extracted from `read_release_detail` (C33). Writes nothing; touches no #269 file. Gates: named unit 281; full unit 6 (baseline) / 6996 / 110; history PG 4, publication PG 21 zero skips; ruff clean. 30 mutations: 28 RED (incl. plan reviewer sabotage + C32's endpoint-policy), M23 / M26 survive.
Ruling (M23 — default note built from `release_id` not `version_number` survives because ids == versions in every fixture): NOT equivalent in production — on PostgreSQL a rolled-back publication consumes a `graph_release.id` sequence value, so ids diverge from version numbers. FIX: a fixture where id ≠ version_number (e.g. burn a sequence value / insert out of order) pinning the note and every version→id resolution. To the reviewer + fix round.
Ruling (M26 — same_revision by content vs id): equivalent while #269's (agent_key, content_hash) reuse holds — accepted.
Ruling (concern 2 — remote checks run even when blocked): accepted (issues are computed even when an earlier check blocks); no change.
Concern 3 (`_HistoricalSource` interface) → carried to Task 3a's brief.
Task 2: controller sabotage (plan controller target) — `_structural_issues` returns `()` (`CTRL270_2_STRUCT`, anchor 1): RED 4/21 (`test_incompatible_historical_release_is_reported_per_role` as predicted, + blocked-first, endpoint-policy, local-phase-skips). Restored from pinned HEAD, clean, marker 0.
Task 2: review (Opus): spec PASS, quality PASS WITH FIXES — 0 Critical, 2 Important, 2 Minor. M23 CONFIRMED on real PG: a rolled-back publication consumed id 2 → rows (1,1),(3,2),(4,3); M23 then REDs a probe while all 21 unit tests stay GREEN. I-1: EIGHT id↔version swaps (history `:152, :180, :251`; rollback `:198, :220, :226, :262, :267`) each survive every suite — no fixture has id ≠ version. I-2: the preview's lock mode is untested (S1 `exclusive=True` survived 106). m-1: three-way draft-effect coverage gap (S2 survived 38): pending edit on an identical role, and a draft saved to exactly the restored content, must be `kept`. m-2: `_structural_issues` duplicates #269's `_changed_candidate_issues` loop (C32 allows; drift risk).
Ruling: fix I-1 (SQLite fixture burning ids before v2 + a PG probe-style test; assert note, refs, next_version_number, evidence source_release_id, compare refs, history detail + entries), I-2 (compiled first statement ends `FOR SHARE OF graph_release, graph_draft`), m-1 (two added cases). Park m-2 → follow-up (share one helper taking a contents mapping). CARRY to the #271 epic review: check #269 / #268 for the same id-equals-version assumption.
Task 2: fix round 1/5 dispatched (resume implementer).
Task 2: fix round 1/5 (3 addressed, m-2 parked; `daaf9daf4`, test-only): `offset_release_ids` re-keys v1 to id 11 in every SQLite fixture (FKs off, `foreign_key_check` empty) + literal (id, version) assertions; PG test with a real rolled-back publication → (1,1),(3,2),(4,3); preview first statement compiled for PG ends `FOR SHARE OF graph_release, graph_draft`; two `kept` cases. Gates: 285 named unit; full unit 6 (baseline) / 7000 / 110; history PG 5 zero skips; ruff clean. 12 mutations RED (all 8 swaps, M23, S1, S2, S3).
Controller re-check: `next_version_number = release_row.id + 1` (`CTRL270_2_ID`) → RED 2/25; restored clean.
Ruling: no scoped re-review — test-only, every finding mutated RED, controller swap RED. Cost if wrong: small.
Task 2: complete (commits `e4385f487..daaf9daf4`, review clean after 1 fix round). Tasks 3a+ inherit ids ≠ versions via `build_v2_v3_v4`.

## Task 3a — 2026-09-27
Task 3a: implementer DONE_WITH_CONCERNS at `e6142ab72` (TASK_BASE `6dbd051c7`): `d64ba5ce0` `restore_release` (`graph_configuration_rollback.py:311`), `_validate_rollback_request`, `_verify_rebased_draft`, `_assign_locked_candidate` extraction (`graph_configuration_draft.py:1013`), facade exports, 31 SQLite tests; `5e15d5cf2` one post-condition per draft effect + base-release guard test. Gates: rollback unit 57; named 970; full unit 6 (baseline) / 7031 / 110; PG publication 21, evidence 18, workbench 49, overlay 10, history 5 — zero skips; ruff clean. 34 mutations: 32 RED (incl. plan reviewer sabotage), M27/M28 equivalent (guards kept deliberately).
Ruling: concern 3 (unknown version + stale lock → `GraphVersionNotFound` before conflict, per the plan's check order) ACCEPTED; Task 6 maps it. Concern 4 (`test_dependencies_resolve_on_proxy` does a real network resolve — slow) noted for the baseline.
Task 3a: controller sabotage (plan controller target) — `restored_from_release_id=None` (`CTRL270_3A_RESTORED`, anchor 1, `:383`): rollback + history unit RED 1/74 (`test_restore_v3_while_v7_active_produces_v8_restoring_v3`). Restored clean, marker 0.
Task 3a: review (Opus): spec PASS, quality PASS — 0 Critical, 0 Important, 2 Minor. One publication writer; every refusal before the first write (shape → stale → not found → active → matches_active → incompatible via C32 validators incl. endpoint policy); L0 X → L1 → L3 `FOR UPDATE OF agent_test_run ORDER BY id` + new-statement re-check, pinned on compiled SQL; no remote call under a lock; deadlock-free vs publisher / #268 cleanup / verdict writer / #267 case writers; atomic; Q7 matches exactly; `_verify_rebased_draft` runs; C36 extraction behaviour-identical; ids ≠ versions; C48; no import cycle. Reviewer sabotage: S1 links as `approval` → RED 1/74; S2 extraction skips `top_p` → RED 2/331. Restored GREEN 350; PG publication + workbench 70 zero skips. Temp worktree removed; no DB leaked.
Ruling: m1 (the "only candidate_hash writer" AST test claims more than it checks — misses constructors, setattr, Core `.values`) and m2 (no restore-level endpoint-policy refusal case) → whole-branch fix wave (reword/extend m1; add the m2 case).
Task 3a: complete (commits `6dbd051c7..5e15d5cf2`, review clean, no fix round).

## Task 3b — 2026-09-27
Task 3b: implementer DONE at `b50ed17e8` (TASK_BASE `51a9f6120`; controller ledger `e6864276f` interleaved): `8f9c1eca1` test-only `tests/integration/test_graph_release_rollback_postgres.py` (12: headline v8-restores-v3 with burned ids, 6 C42 injection stages + C15 evidence checks + gapless retry, restore-a-restoration, restore v1, pinned conversations + runtime runs on v7/v3/v8, 2 readiness negative-proof variants) + integration-graph enrolment + CI pin. Gates: new 12, history 5, publication 21, evidence 18 — zero skips; CI collection 20; full unit 6 (baseline) / 7033 / 110; ruff clean. 11 mutations RED twice (resolve-by-id REDs all but restore-v1 — the ids ≠ versions proof). No production defect.
Concern 2 (literal ids assume sequence cache 1 on a fresh DB per test) accepted — holds for `postgres_engine`. Concern 1 (early-COMMIT mutation only REDs `draft_reset`) accepted — #269's suite covers the core's own write steps.
Task 3b: controller sabotage (C16 seam) — `_historical_evidence(source_release_id=release_row.id)` (active release instead of source; `CTRL270_3B_SRC`, anchor 1): RED 11/12 (headline + injection stages + restoration + v1 + readiness variants). Restored clean, marker 0.
Task 3b: review (Sonnet): spec PASS, quality PASS — 0/0/1 Minor (M1: the injection test checks `historical_restore` links globally, not per `graph_release_id` — equivalent; optional tighten → whole-branch wave). Real writers only; ids ≠ versions with exact pairs; 6 stages; arming logic sound (reads matching the `mappings_read_back` matcher precede any write, so arming prevents a false fire, masks no stage); readiness negative proof genuine (C30); bounded waits; CI + pin. Reviewer sabotage `_draft_effect` kept → reset (`:540`) RED 2/12 exactly as predicted; restored GREEN 12. Note: a 5th `tellr_int_*` DB (`tellr_int_f7551cc43d7846bc`) present — not the reviewer's; likely the concurrent Task 4 implementer's live fixture. Controller to re-check after Task 4.
Task 3b: complete (commits `51a9f6120..8f9c1eca1`, review clean, no fix round).

## Task 4 — 2026-09-27
Task 4: implementer DONE at `92d51e509` (TASK_BASE `0230e685c`; ledger `ad8950c9f` interleaved): `9d7a079b9` test-only `tests/integration/test_graph_release_rollback_ordering_postgres.py` (12: rollback vs publish, vs rollback, vs draft save, vs #268 verdict [change_refused, identical_noop], vs #268 cleanup — both orders where the brief says) + integration-graph enrolment + CI pin. Gates: new 12 (~10 s), rollback 12, history 5, publication 21, evidence 18, session ordering 29, workbench 49 — zero skips; CI collection 21; full unit 6 (baseline) / 7034 / 110; ruff clean. 7 mutations RED (M01 = the plan's controller target — SPENT, run by the implementer).
Erratum (C6 prediction for two-rollbacks under L0 shared): the loser's shared L0 is granted and it then blocks on `UPDATE GRAPH_RELEASE SET EFFECTIVE_TO`, so the RED lands at `_race`'s `waiting_on` check (waiter statement must contain the exclusive L0 text), not at `_await_blocked_by`. Still a named RED before deadlock.
DB note: `tellr_int_f7551cc43d7846bc` (created 07:08:04 UTC, only the v1 bootstrap row, no connections) is claimed by neither the 3b reviewer nor the Task 4 implementer; not provably anyone's → NOT dropped; added to the user's leftover-DB list (now 5).
Task 4: controller sabotage (fresh) — rollback L3 `FOR SHARE` instead of `FOR UPDATE` (`CTRL270_4_SHARE`, anchor 1, `:570`): ordering PG RED 2/12 (both verdict cases), unit RED 2/57 (L3 shape + lock-order). Restored clean, marker 0.
Task 4: review (Sonnet): spec PASS, quality PASS — 0/0/1 Minor (M1: `identical_noop` proved as a separate case, not concurrently with a change in the same pause — `_race` takes one waiter; accepted, park). All interleavings exact both orders; C5 PID capture; C6 pause + exclusive assertion; C28 L3 predicate + `pg_locks` AccessExclusiveLock; bounded; C41/C48 verdict cases; helpers imported; ids ≠ versions; CI + pin; the C6 erratum verified correct. Reviewer sabotage (evidence from the active release, `:368` — same seam as Task 3b's C16) RED 6/12 here; restored GREEN 12. Temp worktree removed.
Task 4: complete (commits `ad8950c9f..9d7a079b9`, review clean, no fix round).

## Task 5 — 2026-09-27
Task 5: implementer (Sonnet) STALLED — session ended on an API 401 authentication error mid-mutation-sweep. Salvage (executing-plans-tellr §5): `src/services/graph_configuration_rollback.py` had a LEFT-IN sabotage (`MUT-C5-1`, draft-only lock — the controller's target, which the implementer had begun running against instructions); restored from `367548e97`, `git diff HEAD -- src` empty, marker 0. The uncommitted test work (+460 lines appended to #269's `tests/integration/test_graph_release_session_ordering_postgres.py`, 28 new tests) verified by the controller: file 57 passed zero skips; ruff clean; no stray pytest; DB list unchanged (5). Committed by the controller as `6f5e7a25c` (noted in the message). No task-5-report.md exists; no implementer mutation table.
Task 5: controller sabotage — rollback's L0 replaced by an unlocked release read + draft-only `FOR UPDATE` (`CTRL270_5_L0`, anchor 1, `:336`): RED 14/57 (`test_rollback_first_each_creator_pins_the_restoring_release` ×7 creators, `test_creation_first_rollback_waits_and_creator_keeps_v4` ×7). Restored clean; test file byte-identical to the salvaged copy.
Ruling: the review gets two reviewer sabotages (compensating for the missing implementer sweep) and must check the cleanup half of the brief is present (Task 4 may already cover it).
Task 5: review (Opus): spec PASS, quality PASS — 0/0/4 Minor. Cleanup half covered exactly by Task 4's `test_rollback_and_cleanup_serialize_with_exact_deletions[cleanup|rollback]` (`test_graph_release_rollback_ordering_postgres.py:649`). All 7 creators via real paths (`session_manager.py:759, :897, :1245`); append-only; helpers imported; bounded; PIDs before blocking. Reviewer sabotage (compensating the missing sweep): S1 `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1` RED 28/57 (14 new); S2 creator pins the pre-rollback release RED 28/57 (14 new); S3 duplicate harness path → create_session RED 8/57 (only `[duplicate]`). Brief Step 2 files also run: mixed-creation 14, pin-creation 2, creator-exclusions 4, pin-acceptance 1, CI collection 21. Temp worktree removed; DBs unchanged.
Ruling: Minor 1 (assert literal (id, version) pairs in `_seed_v4` + v5 id 6), Minor 2 (add `race.scans` assertions to the flushed-rollback test), Minor 4 (Task 4 cleanup test asserts R2's full link list) → whole-branch fix wave. Minor 3 (near-duplicate `_RollbackRace` / seed / assert helpers vs #269's) → park, follow-up.
Task 5: complete (commit `6f5e7a25c`, review clean, no fix round).

## Task 6 — 2026-09-27
Task 6: implementer DONE_WITH_CONCERNS at `342af500f` (TASK_BASE `01213fca5`): `0794afa25` five handlers on the one admin router (`agent_definitions.py`, `main.py` unchanged), wire `src/api/schemas/graph_release_history.py`, C38 widening (Python evidence model + pairing validator, TS parser, `mocks.ts`, `releaseClient.test.ts`, #269 join test + exact publish body, route-registry pin) in the same commit, new join `tests/unit/test_graph_release_history_client_join.py`. Gates: routes 69, join 20, named 800; full unit 6 baseline + 1 environment-only (`test_persisted_agent_runtime` "private" check tripped by running from `/tmp` → `/private/tmp`; passes in the real worktree); PG publication 21, evidence 18, rollback 12, history 5, acceptance 3, rollback ordering 12 zero skips; Vitest GraphRelease 152 / Admin 780; typecheck + ruff clean. 35 mutations: 34 RED (M01 plan reviewer, M02 C38 pairing), M10 unobservable range check kept.
Ruling: deviations 1–5 accepted (no `ge=0`, id-offset fixture, ERROR only for integrity, body before range check, two #269 helpers delegate to shared cores with #269 GREEN). Concern 3 (SQLite `Z` vs no-`Z` timestamps across endpoints) → Task 7 compares instants; carried to the whole-branch review. Concern 6 → Task 7 extends the C46 join to its TS parsers.
Task 6: controller sabotage (plan controller target) — rollback handler without `Depends(require_draft_write_principal)`, `actor=""` (`CTRL270_6_AUTH`, anchor 1): RED 19/69 (blank-principal and every path that needs the actor). Restored clean, marker 0.
Task 6: review (Opus): spec PASS, quality APPROVED — 0/0/5 Minor. Auth-first; explicit mapping (404 before 409; integrity → one ERROR record, no exc_info; IntegrityError uncaught; unknown → AssertionError 500); C38 consistent in one commit, publish approval-only, #269 test edits are behaviour changes not loosening; wire strict; one router, registry pin + count updated, `main.py` untouched; the two #269 helpers byte-identical except the intentional C38 field; ids ≠ versions. Timestamp `Z` inconsistency is SQLite-only (PG serialises the aware value identically). Reviewer sabotage: S1 IntegrityError → 409 RED 1/69; S2 detail resolves version as id RED 5/69; S3 C34 in-lock remote check RED 2 in Task 2's service tests (none in routes — acceptable, the rule lives in the service). Temp worktree removed; no DB change.
Ruling: m1 (rollback log record missing on raw IntegrityError / AssertionError / path-int 422) → whole-branch fix wave (log `outcome="error"` + re-raise); m2 (role keys derived by splitting the issue field) → park; m3, m4, m5 accept.
Task 6: complete (commits `01213fca5..0794afa25`, review clean, no fix round).

## Task 7 — 2026-09-27
Task 7: implementer DONE_WITH_CONCERNS at `b091b9fae` (TASK_BASE `4ed72a984`; ledger `3f03752bd` interleaved): `f13b1d82a` typed client + strict parsers + Release History tab on #269's page (one reducer / counter / gate shared by publish and rollback; `FieldDiffView.tsx`, `releaseText.ts` extracted), join extended; `7a2d094ee` m4 guard pinned at the hook (renderHook). No `src/` change. Gates: Vitest 1084 (GraphRelease 348, workbench 628, ALLOWED 8); typecheck/ESLint clean; 6 join files 112; full unit 6 (baseline) / 7148 / 110. 37 mutations: 35 RED (M08 plan reviewer sabotage RED; M32 = the plan's controller trim guard — SPENT), M08b/M09b equivalent. A first m4 component test was vacuous and was replaced (M11/M11b RED).
Ruling (concern 1 — stem names): KEEP the brief's names (`Confirm rollback`, `Cancel rollback`, tab `Release History`); no exemption, count stays 8. — the forbidden-action stems guard the WORKBENCH panel from growing publish/rollback controls (C40: the sweep covers the workbench only); on the Review & Publish page these actions are the page's purpose. Task 8 must NOT add a stem sweep over the review page. — cost if wrong: a future sweep widening flags these names and needs exemptions.
Ruling (concern 2): Task 8 uses the C3 fixed row names (`Inspect this version`, `Roll back to this version`) scoped by `release-history-row-<v>`, overriding its plan text.
Concern 5 (M21 zoneless-timestamp mutation only REDs on a non-UTC host) → Task 8 / whole-branch: pin with an explicit TZ-independent test.
Task 7: controller sabotage (fresh; trim guard spent as M32) — the `kept` draft-effect label shows the `reset` text (`CTRL270_7_LABEL`, anchor 1): GraphRelease Vitest RED 2/348. Restored clean, marker 0.
Task 7: review (Opus): spec PASS, quality APPROVED — 0/0/6 Minor. Parity read from both sides (112 join tests); one in-flight ref across publish/rollback; confirm checks the reducer's current request id (m4 not copied); stale drops in all four slices; extractions identical; text-only; instants; ids ≠ versions (`releaseVersionUrl` refuses non-positive); stem names not swept; 11 new fixtures validated against the real Pydantic models byte-identical. Reviewer sabotage: S1 comparison diff swapped RED 1/1084; S2 unknown evidence_kind accepted RED 1/1084; restored GREEN 1084.
Ruling: fix now (fix round 1) — m2 restore the C4 test's non-vacuity guard + the `history` alternative; m3 `rollbackFailureAction` must not store the source as `active` for `rollback_incompatible`; m4 RENAME the stale-alert button to `Reload rollback preview` (two different actions shared one name; Task 8 queries by name); m5 clear/refetch a shown inspection after a restore or publish succeeds; m6 add a second diff-direction assertion. m1 (report counts) — ledger correction: #270 join 45, #269 join 22. TZ-independent pin for zoneless timestamps (set a non-UTC TZ inside the test) — add in this round too.
Task 7: fix round 1/5 dispatched (resume implementer).
Task 7: fix round 1/5 (all addressed; `45fb54756`, frontend only): m2 non-vacuity restored; m3 `RollbackBlocked.active` nullable, incompatible stores null; m4 stale button renamed `Reload rollback preview` (matches the `rollback` stem like the other page names — unswept, per the ruling; count stays 8); m5 success resets the inspection (drops late answers); m6 second direction assertion; TZ pin (Asia/Kolkata) makes the zoneless-as-local mutation RED on a UTC host (F7u). Gates: Vitest 1090, typecheck/ESLint clean, joins 112 (45 / 22). Mutations F1–F7u RED, control F0u 0 failed.
Ruling: no scoped re-review — frontend-only narrow fixes, each mutated RED including the TZ-independence control. Cost if wrong: small.
Task 7: complete (commits `3f03752bd..45fb54756`, review clean after 1 fix round).

## Task 9 — 2026-09-27
Task 9: implementer (Sonnet) DONE at `9d9e74c23`: `7b2511b58` test-only `tests/integration/test_graph_release_rollback_acceptance_postgres.py` (`test_restore_v3_while_v7_active_over_http`, 12 steps over the one admin router) + integration-graph + CI pin. Gates: new 1, publication 21, history 5, rollback 12, #269 acceptance 3 — zero skips; CI collection 22; full unit 6 (baseline) / 7149 / 110; ruff clean. No defect. Mutations: M01 (reviewer: no `unchanged` branch) RED; M02 = the CONTROLLER target (evidence from the active release) run by the implementer against instructions — SPENT (RED). Only 2 mutations — thin; the review compensates.
Task 9: controller sabotage (fresh, in a temp worktree to avoid the concurrent Task 8 lane) — history listed ascending (`CTRL270_9_ORDER`, `graph_release_history.py:126`): acceptance RED (`[1, 2, 3, …] == [7, 6, 5, …]`). Temp worktree removed; DB count unchanged.

## Task 8 — 2026-09-27
Task 8: implementer (Sonnet) DONE at `34dd5b669`: `0dffab308` `frontend/tests/e2e/graph-release-history.spec.ts` (9 scenarios) + e2e matrix enrolment (`graph-release-history`). Gates: new 9/9; graph-release-review, admin-route-gate, workbench specs green; full Vitest green; typecheck clean; `test_e2e_matrix_covers_specs.py` green. The plan's controller sabotage was run by the implementer (RED in (a) and (g)) — SPENT. Found a Task 7 FIXTURE BUG: `syntheticHistoryEntry` builds day `20 + versionNumber`, so v ≥ 11 yields invalid September dates (31, 32) → NaN → strict parser rejects; worked around locally with January dates → fix the shared fixture in the whole-branch wave.
Task 8: controller sabotage (fresh) — the restored badge names `restored_from.release_id` instead of `version_number` (`CTRL270_8_BADGE`, `ReleaseHistoryTab.tsx:84`): new spec RED 1/9 (`toContainText`). Restored clean, marker 0; port 3000 free.
Task 9: review (Sonnet): spec PASS, quality PASS — 0/0/1 Minor (M01: step 11 checks `changed` only for architect/builder/fixer, not the other four → whole-branch fix wave). All 12 steps exact; C53 override only; ids ≠ versions with exact tuples; CI + pin. Reviewer sabotage: A id burn removed → RED (exact pairs assert); B history drops `restored_from` → RED; restored GREEN 1/1 zero skips. Temp worktree removed; DB count 5.
Task 9: complete (commit `7b2511b58`, review clean, no fix round).
Task 8: review (Sonnet): spec PASS with qualifications, quality APPROVED — 0 Critical, 1 Important, 2 Minor. I-1 `page.waitForTimeout(100)` sleep (`:473`); M-1 two unused imports; M-2 (f) reaches blocked via a blocked preview GET rather than a 422 POST (accepted). All scenarios present with exact counts; C3/C7/C40/C44; `exact: true` on overlapping names; URL-keyed mocks with ids ≠ versions; matrix enrolled; the January-dates override judged sound. Reviewer sabotage: a 409 fires a second rollback POST → RED 1/9 (c-2); restored GREEN 9/9.
Task 8: fix (controller, `5587103b0`): sleep replaced by `expect.poll(() => postCount).toBe(1)`; unused imports removed; spec 9/9, port free. (The poll is no weaker than the original check; a late-POST proof would need a longer negative window — accepted.)
Task 8: complete (commits `5b11f3da7..5587103b0`).
All #270 build tasks complete (0-A, 1, 0-B, 2, 3a, 3b, 4, 5, 6, 7, 8, 9). Next: whole-branch review.

## Whole-branch review — 2026-09-27
Whole-branch review (Opus) at `0a870f29c`: MERGE AFTER FIXES — 0 Critical, 0 Important, 14 Minor + O1. Writer table extended (restore_release: own txn, L0 X → L1 → L3 id-order + new-statement re-check, no L2, no gate, shared core; `_assign_locked_candidate` sole attribute writer; linker relies on rollback's L3). Deadlock-free; no remote call under L0; C34 holds; scanner GREEN. Rollback atomic across 6 stages; no IntegrityError caught. Publication safety re-derived: the gate and readiness never read `graph_release_test_run`, so `historical_restore` links can never satisfy a new publication; Q7 caveat ACCEPTABLE (eligibility is hash + case version, never base-relative — #269 already allows it). ids ≠ versions CLEAN across #268/#269/#270 → the carry to #271 is CLOSED. Parity strict; frontend one reducer/counter/gate; CI complete. Gates: unit 6 (baseline) / 7149 / 110; all 33 integration-graph PG files 549 passed zero skips (attribution file 60 in 17 s, no hang); Vitest 1090; typecheck clean; ESLint 1 error (N2); Playwright 102. Sabotage: S1 gate accepts restore links → PG RED 2/12 (unit 0/143 — N3); S2 rollback bypasses the core with a copy → RED only 1 PG test (N1); S3 rollback success skips the #269 preview refetch → Vitest 1 + Playwright 1 RED.
Ruling: fix now — 3a-m1 (extend the only-writer AST test: keyword `candidate_hash=`, setattr, Core `.values`, with an allowlist; rename), 3a-m2 (restore-level endpoint-policy refusal), 5-M1, 5-M2, 5-M4, 6-m1 (log one ERROR `outcome="error"` + class on raw IntegrityError / AssertionError, re-raise; path-int 422 accepted), the Task 8 fixture (`Date.UTC(2026, 8, 20+v)` in `mocks.ts`; bug starts at v=10; drop the `historyV12` override), 9-M01 (all seven roles), 2-m-2 (de-duplicate `_structural_issues` onto #269's `_changed_candidate_issues` core; re-run #269's suites), N1 (pin that restore writes through `_commit_locked_publication` — a spy), N2 (unused var ESLint error). Park — 5-Minor-3, N3, O1 label copy. Accept — 3b-M1.
Whole-branch fix wave dispatched (one fix dispatch).
Whole-branch fix wave (Opus, `e37f5ff0f..8fd1e046c`, report `e796a0457`): all 11 items addressed (table in `whole-branch-fix-report.md`); parked items untouched. Gates: unit 6 (baseline) / 7159 / 110; PG rollback 12, history 5, publication 21, evidence 18, session ordering 57, rollback ordering 12, rollback acceptance 1, publication acceptance 3 — zero skips, DBs unchanged; Vitest 1099; typecheck + ESLint clean (all 14 branch TS files); Playwright 18; ruff clean. 18 mutations RED (N1 core copy now RED on the spy; M5 link move RED at the full R2 list; M8 RED only under the 7-role assert; old date formula RED Vitest 7 + Playwright 1).
Controller check (in place of a scoped re-review subagent): the shared `_candidate_contents_issues` local phase swapped to `local_candidate_validators` (drops #266's endpoint policy) → RED on BOTH sides: #269 `test_url_shaped_endpoint_written_past_the_save_is_rejected_at_public…` and #270 `test_endpoint_name_policy_makes_a_historical_release_incompatible` + `test_restore_refuses_an_endpoint_url_before_any_write` (3/100). Restored clean.
Ruling: concerns accepted (6-m1 catches every non-HTTPException, one record, no double-log proven; item 1's constructor check matches the name only; item 9 reads all changed roles before validating — no observable change). No further re-review: every item mutated RED and the de-duplication proven from both call sites. Cost if wrong: small.
Whole-branch: complete — MERGE.

# Task 4 report: approval evidence gate, evidence links, linked-verdict freeze, cleanup and verdict races

**Status:** DONE_WITH_CONCERNS (the concerns are minor; see the end).
**TASK_BASE:** `dbc713919`. The controller's ledger commit `3e8083f86` sits between my first and second commits and touches only `progress.md`.

## Commits
| SHA | Summary |
|---|---|
| `a186edfd1` | feat: lock and link approval evidence during publication (#269) |
| `08fcf26c4` | test: align #267/#268/#269-Task-1 pins with the linked-verdict refusal and real evidence linking |
| `c0c8dd789` | test: pin role-first gap order when a later role has no required case (the mutation-sweep pin SHA) |

### Files changed
- **Created:**
  - `src/services/graph_release_evidence.py`
  - `tests/unit/test_graph_release_evidence.py` (30 tests)
  - `tests/integration/test_graph_release_evidence_postgres.py` (18 tests)
- **Modified, source:**
  - `src/services/graph_configuration_publication.py`: `_link_evidence` now delegates to `link_release_evidence`, imported lazily to break an import cycle.
  - `src/core/database.py`: the C14 trigger `trg_agent_test_run_linked_verdict_immutable` and its function `reject_linked_agent_test_run_verdict_change`.
  - `src/services/agent_test_workbench.py`: `IneligibleReason` gains `linked_to_release`; `record_verdict` gets the C48 re-check.
  - `src/api/schemas/agent_definitions.py`: the `reason` literal.
  - `src/api/routes/agent_definitions.py`: `_INELIGIBLE_MESSAGES` and the section comment.
- **Modified, test and CI:**
  - `.github/workflows/test.yml` and `tests/unit/test_ci_collects_integration_tests.py`: enrolment and pin.
  - `tests/integration/test_graph_configuration_constraints_postgres.py`: the C14 idempotence extension.
- **Modified, existing pins (08fcf26c4):**
  - `tests/unit/test_agent_test_workbench.py`: the verdict writer's "no `graph_release` read" check now allows `graph_release_test_run` (word-boundary regex).
  - `tests/unit/test_agent_definition_workbench_routes.py`: the "unknown reason" test used `linked_to_release`, which is now a wire reason, so it uses `withdrawn`.
  - `tests/unit/test_graph_release_publication.py`: the Phase A refusal test became `test_evidence_naming_a_missing_run_is_refused_before_the_draft_rebases`.
- **C48 TS parity edit (minimal, no UI).** `tests/unit/test_draft_readiness_client_join.py` went RED on the Python-only change: 2 failures, the reason set and the served fixture message. I added the literal in these places:
  - `frontend/src/api/agentDefinitions.ts`: `TestRunIneligibilityReason` and `INELIGIBILITY_REASONS`;
  - `frontend/tests/fixtures/mocks.ts`: `syntheticVerdictIneligible`, now a message map with 3 reasons;
  - the join test's docstring text.

  The results after the edit:
  - `tsc -b` is clean.
  - Workbench Vitest: 622/622.
  - `draftEditorState.ts:854` still labels any non-`not_completed` reason "checks did not pass". That UI text is Task 6's to fix.

## Gate design (as built)
Inside `publish_draft`'s transaction, after L0 and L1:
1. **L2.** `SELECT agent_test_case … WHERE agent_key IN changed ORDER BY id FOR SHARE`, unfiltered, with `populate_existing` (C29).
2. **Re-select.** A NEW unlocked statement re-selects the active required cases (`populate_existing`). Any changed key without one becomes `PublicationGap(k, None, "no_required_case")` (C1).
3. **L3.** Only if there are cases: `SELECT agent_test_run.id … FOR UPDATE ORDER BY id`. The statement uses literal columns only: one `(test_case_id, test_case_version, agent_key, candidate_hash)` conjunction per case, plus `run_kind='candidate'`, `verdict='approved'`, `execution_status='completed'` and `deterministic_checks_passed` (C30, C33, C45).
4. **Re-verify.** A NEW statement over the locked ids, joined to each run's case row and the draft agent, using the imported `eligible_approval_clause` from #268, term for term (C45).
5. **Selection.** Newest by `(run_at, id)` per case.
6. **Gaps.** Sorted by role index, then case id. On gaps only, `readiness(session)` is called, before any write (C32). The gate never writes.

`link_release_evidence` works as follows:
- It rejects a duplicate run id.
- It checks existence with a plain, unlocked read, and raises `release evidence names a missing run`. It takes no lock itself: the gate already holds L3. A locking linker would have hidden C47's seam; see M2.
- It inserts, flushes, and reads back the release's `{(run, kind, source)}`. A mismatch raises `release evidence read-back does not match its links`.

`record_verdict` (C48):
- After the L3 lock and the not-found check, a NEW statement runs `EXISTS graph_release_test_run WHERE agent_test_run_id=:id` and raises `IneligibleForApprovalError(run_id, "linked_to_release")`. The route returns 422 `ineligible_for_approval` with the ruled message.
- It is the first eligibility check, so an identical re-submit on a linked run is also refused.

The trigger (C14/C30):
- It is `BEFORE UPDATE OF verdict, verdict_reviewer, verdict_at, verdict_notes`.
- Its `WHEN` compares columns only (four `IS DISTINCT FROM` tests).
- The plpgsql body checks the schema-qualified link table and raises 23514.
- It uses an idempotent `DROP TRIGGER IF EXISTS` and `CREATE OR REPLACE FUNCTION`, and coexists with `trg_agent_test_run_evidence_immutable` (the constraints test expects both).

## Gates
- **Unit, focused.** The brief's files and the C52 files: evidence, publication, `test_agent_test_workbench`, the 4 client-join/endpoint files, `model_endpoint_probe`, ci_collects, the parent-lock scanner, workbench routes, draft, bootstrap. Result: all green (1105 passed after the pin updates, plus the new ordering test).
- **Full unit.** 6 failed, 6854 passed, 110 skipped. These are exactly the baseline six by node, with causes unchanged: the deploy_autoscaling ×2 provisioned/autoscaling asserts, chokepoint ×3 `_FakeSession.execute`, and persistence_boundary with "no active Graph Release". The run went from 00:50 to 00:56 UTC, so the `test_usage_service` midnight flake did not arise.
- **PostgreSQL**, one invocation per file, 0 skips each:

  | File | Passed |
  |---|---|
  | evidence | 18 |
  | publication | 21 |
  | session_ordering | 29 |
  | agent_definition_workbench (#267/#268) | 49 |
  | constraints | 66 |
  | bootstrap | 3 |

- **ruff.** Clean on every new file. Changed files have no new findings: `database.py` has 22 pre-existing, `test_ci_collects` 1 pre-existing, workbench routes 2 pre-existing.
- **Frontend.** `tsc -b` clean. `vitest src/components/Admin/AgentDefinitionWorkbench`: 622 passed.
- **DB hygiene.** At the end, only the 4 older `tellr_int_*` databases remain. A fifth seen mid-run changed identity and vanished, so it belonged to the concurrent reviewer, not me. Nothing leaked.

### RED evidence
- **Step 3.** Both new files failed at collection with `ModuleNotFoundError: src.services.graph_release_evidence`.
- **C48.** The join test went RED (2) on the Python-only change, before the TS edit.
- **Pins.** Three existing pins went RED on the implementation. All three were intended behaviour changes, listed above.
- **Caveat.** Most new behavioural tests went GREEN straight from the import-error RED. Their discriminating power rests on the mutation sweep below, not on a per-test pre-implementation RED.

## Mutation sweep
Every mutation was restored from pin `c0c8dd789` with `git checkout`. After each: `git diff --quiet` gave 0 and the `MUT269_4` marker count was 0.

| # | Mutation | Result and observed cause |
|---|---|---|
| M1 (C29 reviewer) | Filtered `FOR SHARE` lock, gating on the locked set | RED `test_supersede_while_the_gate_waits_is_seen_and_refused`: `PublishedRelease(v2)`, so B v2 was dropped from the gate and published unapproved |
| M2 (C47 reviewer) | Remove `.with_for_update()` from L3 | RED `test_verdict_rejection_first_then_publication` at the query-text assertion. Observed waiter query: `INSERT INTO GRAPH_RELEASE_TEST_RUN (…) VALUES (2, 1, 'APPROVAL', NULL)`, exactly C47's revised prediction (the publisher waits at the FK check, not at L3) |
| M3 (C45 reviewer) | Drop `run_kind` from L3, and inline the shared clause minus `run_kind` in the re-verify | RED unit parity `[run_kind]` only: a `published_baseline` approval was linked while readiness refused it |
| M4 | Skip the re-verify statement (use the locked ids directly) | SURVIVED, equivalent. L3's predicate is literal columns of the locked row, so EvalPlanQual re-checks every term. The draft hash is L1-locked and the case L2-share-locked. Kept as C33/C45's term-parity layer; M27 proves the layers together |
| M5 | Newest selection `>` changed to `<` | RED: unit ×3 (newest, run_at-then-id, tied id) and PG newest test, each linking the older run |
| M8 | Trigger `WHEN` omits `verdict_notes` | RED: PG direct-update test (`DID NOT RAISE`) and the constraints idempotence test |
| M10 | Remove the read-back check | RED `test_link_release_evidence_refuses_a_read_back_that_is_not_exactly_its_links` |
| M11 | Remove the missing-run check | RED: unit missing-run test and the publication unit missing-run test (FK error instead of the named one) |
| M12 | `_link_evidence` links nothing | RED: unit ×4 and PG (`[] != [(2, 2, 'approval', None)]`) |
| M13 | Drop `graph_draft_id == draft_id` from the re-verify | SURVIVED, equivalent: the draft is a singleton |
| M14 | Call readiness on the success path too | RED ×2: parity control and `test_readiness_is_called_only_on_the_not_ready_path` |
| M15 | No gap sort | RED `test_a_later_roles_missing_case_sorts_after_an_earlier_roles_case_gap`, a test added because the first sweep design showed this was unpinned |
| M17 | The C48 link check read BEFORE the L3 lock (old snapshot) | RED `test_publication_first_then_verdict_change`: `IntegrityError` (23514, the trigger) instead of the typed refusal. This proves the new-statement placement |
| M18 | Schema literal without `linked_to_release` | RED: unit 422 test (pydantic literal_error) and the join test |
| M20 | No L2 lock at all | RED: C29 test `publisher was never blocked by case_writer`, bounded at 31 s, no hang; the lock-sequence test has 3 statements where 4 are expected |
| M22 | L3 without `ORDER BY id` | RED `test_gate_lock_statement_sequence` |
| M23 | Hash term dropped from L3 only | SURVIVED, equivalent, as C11 predicts: the shared-clause re-verify catches it |
| M27 | Hash dropped from L3 AND the re-verify skipped (C11's "both") | RED: PG stale-hash test (publishes v2) and unit parity `[candidate_hash]`, `[draft_agent-agent_key]`, plus the C1 ordering test |
| M24 | Remove the evidence file from `test.yml` | RED ×2 in `test_ci_collects_integration_tests.py` |

Controller targets I did **not** run:
- C11/C1: delete the `no_required_case` emission;
- C48: delete the pre-check;
- C14: drop the `IF EXISTS … RAISE` body, which C14 labels as run by the controller.

## Deviations
1. **C45 "Python re-verify on the locked rows".** Implemented as a NEW SQL statement that imports `eligible_approval_clause`, as the brief's "import and reuse it, do not copy it" asks. There is no separate Python attribute re-check. L3 keeps the literal per-case predicate (C45's EvalPlanQual reason).
2. **L3 selects ids only.** The full-entity select exceeded `track_activity_query_size` (1024), which truncated `pg_stat_activity.query` so it could not show `FOR UPDATE`. The re-verify reads every value afresh, and `populate_existing` stays on the statement.
3. **Verdict-writer wait assertion.** #268's L3 statement lists every column and is truncated. `test_publication_first_then_verdict_change` therefore asserts the waiter's `pg_locks` tuple-lock mode is `AccessExclusiveLock` (FOR UPDATE), not the query text. The verdict-first test asserts both the query prefix and the tuple mode (`AccessExclusiveLock`, not the FK check's `AccessShareLock`).
4. **Lock-wait bound.** The new file bounds lock waits with `ALTER DATABASE <throwaway> SET lock_timeout='30s'` plus `engine.dispose()` in `_setup`, instead of a per-thread `SET LOCAL`. This covers every thread, including the #267/#268 writers, which have no override hook.
5. **C13 PID capture.** The run-vs-publication test captures #267 T2's PID through an `_ObservedGraphConfiguration` injected into the executor (`_lock_current_parents` override), counting calls to tell T2 from T1.
6. **C8 part 2.** Implemented as `test_injected_failure_with_evidence_rolls_back_every_row` in the evidence file, over 5 stages (the 4 of Task 1 plus `evidence_linked`) with a real approval. It asserts zero links, unchanged verdicts, v1 still active, and a retry that links the approval. Task 1's parametrization is untouched.
7. **Parity test.** It has 11 parametrizations: a control plus 10. For the `draft_agent.agent_key` join term, which one row cannot vary independently, I used a run carrying another role's current draft hash. `execution_status` and `checks_passed` rows are built with `PRAGMA ignore_check_constraints`, because the DDL refuses an approved incomplete or failing run.
8. **Evidence rows.** All come from #267's real `execute_candidate_run` (fake adapter) and #268's real `record_verdict`, plus INSERT-only copies with explicit `run_at`. There is no ORM fallback shape.

## Interfaces for Tasks 5–9
- `from src.services.graph_release_evidence import ApprovalEvidenceGate, link_release_evidence`.
- `ApprovalEvidenceGate(*, readiness: Callable[[Session], object])`. `.lock_and_verify(session, *, snapshot, changed_agent_keys) -> tuple[EvidenceLink, ...] | PublicationNotReady`. The production readiness is `get_agent_test_workbench().readiness_under_parent_lock` (C39; the Task 5 route binds it). It is called only on the not-ready path; the attribute is `_readiness`, for C21's spy.
- `link_release_evidence(session, *, release_id, evidence) -> None`. The caller must already hold the runs `FOR UPDATE` in id order (#270 `historical_restore` must lock first). It raises `GraphConfigurationIntegrityError` on a duplicate, a missing run or a read-back mismatch.
- Evidence ordering: role index, then case id. Gap ordering: role index, then case id, with `no_required_case` sorting within its role.
- Wire (for Task 6): `IneligibleForApprovalResponse.reason` now includes `linked_to_release`, message "This run is evidence for a published Graph Version; its verdict cannot change." The TS literal is present; the UI label is not.
- The DB trigger `trg_agent_test_run_linked_verdict_immutable` raises 23514 on any change of the four verdict columns of a linked run.

## Concerns
1. **C48 re-submit semantics.** The linked check comes first, so an identical approve re-submit on a published run is refused (422), not a no-op. This follows C48's "first check", but it differs from #268's idempotent re-submit on unlinked runs.
2. **UI text.** `draftEditorState.ts:854` shows "Deterministic checks did not pass…" for `linked_to_release`. Task 6 must add the label.
3. **M4, M13 and M23 are equivalent survivors.** The re-verify statement is proved load-bearing only in combination (M27). That is expected, because the literal L3 predicate is complete. A reviewer may question the redundancy; it is kept for C33/C45.
4. **Mutation coverage over RED coverage.** Most new tests were never RED against real pre-Task-4 code, only against the missing module. Their power rests on the sweep above.

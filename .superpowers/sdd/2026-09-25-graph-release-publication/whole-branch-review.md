# #269 whole-branch review — Graph Release publication

- **Reviewer:** final whole-branch review (Opus), 2026-09-27.
- **Range:** `16aa02b76..HEAD`. HEAD is `d5ca5ffb6` (docs: record #269 Task 8 complete) on `plan/publish-release-269`. 63 commits. The code diff has 49 files, +11,868/−95, excluding `docs/` and `.superpowers/`. Diff: `/tmp/wbr-269.diff`.
- **Read:** `progress.md` (the whole ledger), `PLAN-CORRECTIONS.md` (C1–C55 and the C33 addendum), the task reports, and every changed `src/` and `frontend/src` file. I also read the #267/#268 writers they interact with (`agent_test_workbench.py`, `conversation_pins.py`) and #270's plan, for the consumer contract.

## Verdict: MERGE AFTER FIXES

- **Counts:** Critical 0, Important 0, Minor 7.
- **Fixes before merge:** m1 and m2 only. Both are trivial, and the controller had already ruled them into this fix wave.
  - m1 is test-only.
  - m2 is typing-only.
- Nothing I found touches the safety invariant, the rollback guarantee or the lock order. m3–m7 are park or accept.

---

## 1. Writer-by-writer table

**Key to the columns:**
- **Txn:** who opens and closes the transaction.
- **Locks:** the locks the writer takes, in the order it takes them.
- **C33:** does the writer re-check its protecting predicate in a new statement after any lock wait?
- **Helper:** does it use the shared helper for its lock, eligibility, write or reuse?

| # | Writer (file:line) | Writes | Txn | Locks, in order | Predicates / guards | C33 | Shared helper |
|---|---|---|---|---|---|---|---|
| W1 | `publish_draft` (`graph_configuration_publication.py:276`) → `_commit_locked_publication` (:463) | `graph_release` (close + insert), `graph_release_agent` ×7, `agent_definition_revision` (new only), `graph_release_test_run`, `graph_draft` (rebase + audit) | Own `with session.begin()` (:286). Every outcome returns inside it; every raise rolls back. | L0 release→draft `FOR UPDATE` (`_lock_current_parents(exclusive=True)`, one statement, `OF` order) → L1 all 7 `graph_draft_agent` `FOR UPDATE ORDER BY agent_key` (:343) → gate L2 → L3 (W2). Implicit: FK `KEY SHARE` on its own locked runs, and on new release/revision rows. | Request shape before any lock (:285). Stale lock before nothing-to-publish (:292). Local + post-stale validators and never the remote one (:452-453, C37). Gate. Timestamp strictly after `effective_from` (:484). Unchanged roles reuse (:496-503). `max(version)=active` (:504). Mapping read-back (:533). Link read-back. | Yes. L0 is one statement with a bounded rescan (the handoff). The snapshot and hashes are read after L0+L1 (:287-290). | `_lock_current_parents` ✔, `materialize_or_reuse_revision` ✔ (:489), `_advance_locked_draft` ✔ (:547), `database_transaction_timestamp` / `as_utc_aware` ✔, `link_release_evidence` ✔ |
| W2 | `ApprovalEvidenceGate.lock_and_verify` (`graph_release_evidence.py:160`) | none (reads and locks only) | Inside W1's txn | L2 `agent_test_case` of the changed roles, unfiltered, `ORDER BY id FOR SHARE`, `populate_existing` (:61). Then a NEW statement re-selects the active required cases (:72). L3 candidate runs: a literal-column predicate only, `ORDER BY id FOR UPDATE`, `populate_existing` (:91). Then a NEW statement re-verifies with `eligible_approval_clause` (:124). | `run_kind='candidate'`, case id+version, agent, draft hash, approved, completed, checks passed. Newest `(run_at,id)` per active required case. `no_required_case` / `no_eligible_approval` gaps. Readiness called only on the not-ready path, before any write (:203). | Yes, twice (C29, C33, C45) | `eligible_approval_clause` ✔ (imported, not copied). The L3 literal predicate is a deliberate second spelling, pinned by the C45 parity test over all 9 terms. |
| W3 | `link_release_evidence` (`graph_release_evidence.py:211`) | `graph_release_test_run` | Caller's | None of its own (documented). Its INSERT FK takes `KEY SHARE` on the runs. | No duplicate run. Every named run exists (plain read). Exact read-back. | n/a: relies on the caller's L3 (W1 has it; #270 must add it, see §8) | the one linker ✔ |
| W4 | Draft saves: `save_editable_model_draft` :399, `save_draft_content` :461, `upgrade_draft_protected_assembly` :520, `upgrade_draft_schema_contract` :559 (`graph_configuration_draft.py`) → `_write_locked_content` :1013 | `graph_draft_agent` (one role), `graph_draft` (audit) | Own `session.begin()` | L0 release→draft `FOR UPDATE` → L1 selected role `FOR UPDATE` (`_read_workbench_for_draft_write`, workbench :377). Then #266's remote endpoint check under L0 (:453, :512). | Stale lock, validators, remote endpoint | Yes. The snapshot is read after the locks. | `_lock_current_parents` ✔, `_write_locked_content` ✔ (all 4), `_advance_locked_draft` ✔, `database_transaction_timestamp` ✔ |
| W5 | Bootstrap `bootstrap_v1` (`graph_configuration_bootstrap.py:58`): first boot `_insert_complete_v1`, re-boot `_validate_current_graph` :119 | First boot: v1 `graph_release`, 7 mappings, revisions, `graph_draft`, 7 draft agents, smoke cases. Re-boot: none. | Own `session_factory.begin()` | Advisory `pg_advisory_xact_lock` → re-boot: L0 `FOR SHARE` as the first statement after the count (C2). First boot takes no L0 (no rows exist). | Complete history, mapping, base, and required-case coverage | Yes (C2: one consistent L0 for the whole validation) | `_lock_current_parents` ✔, `materialize_or_reuse_revision` ✔ (:219, the hand copy was removed), `database_transaction_timestamp` ✔ |
| W6 | #267 case writers `create_test_case` :1034, `update_test_case` :1095, `deactivate_test_case` :1182 (`agent_test_workbench.py`) | `agent_test_case` (retire + insert v+1) | Own | L2 every row of one role, unfiltered, `ORDER BY id FOR UPDATE`, `populate_existing` (:212/:227). Then a NEW-statement re-read (:233). No L0. | Last-required-case refusal (C43), `name_immutable`, identical no-op | Yes | shared `_role_lock_statement` ✔ |
| W7 | #267 `_persist_run` T2 (`agent_test_workbench.py:1761`) | `agent_test_run` INSERT | Own, retried once on the handoff diagnosis | `expire_all()`, then L0 `FOR SHARE` (:1782). FK `KEY SHARE` on the case, the (possibly closed) compared release and the revision. The model call happens outside every txn (C13/C50). | Currency of candidate and base | Yes (the lock precedes the currency read) | `_lock_current_parents` ✔ |
| W8 | #268/#269 `record_verdict` (`agent_test_workbench.py:1471`) | `agent_test_run` 4 verdict columns (Core UPDATE) | Own | L3 one run `FOR UPDATE`, `populate_existing` (:531). No L0/L2 (C41). | Not-found → identical no-op → linked re-check in a NEW statement (#269 C48) → `not_completed` / `checks_failed` → UPDATE. PG backstop: `trg_agent_test_run_linked_verdict_immutable` (`database.py:1112-1158`) plus #267's evidence trigger. | Yes (the link re-check is a new statement after L3). Eligibility is on the locked row itself. | own lock statement (single-row). There is no second eligibility copy: verdict eligibility is row-local. |
| W9 | #268 `cleanup_unpublished_test_runs` (`agent_test_workbench.py:1647`), the only `agent_test_run` DELETE (:775). No production caller. | `agent_test_run` DELETE | Own | L0 `FOR SHARE` (:1673) → L3 targets `FOR UPDATE OF agent_test_run ORDER BY id` → DELETE as a NEW statement re-checking `_deletable_candidate` | not linked, not a retained approval, `run_kind='candidate'`, rank > 20 | Yes (C40) | `_lock_current_parents` ✔, `eligible_approval_clause` ✔ (via `_retained_approval`) |
| W10 | Session creation `lock_active_graph_release` (`conversation_pins.py:66`), from `session_manager.py:759/:897/:1245` | `user_sessions` pin (FK `KEY SHARE` on the release) | Caller's | Release-only `FOR UPDATE`, 2 scans | n/a | Handoff rescan | release-only lock, allowed by the AST scanner |
| R1 | `preview_release` (`graph_configuration_publication.py:361`), `read_workbench`, `readiness_under_parent_lock` | none | Own / caller's | L0 `FOR SHARE` only; plain SELECTs; no remote call | — | — | `_lock_current_parents` ✔, `_changed_candidate_issues` ✔ (shared with W1) |

**Diverged-copy hunt:**
- The only writer of `graph_release` / `graph_release_agent` outside bootstrap is W1. Every `candidate_hash` write goes through `_write_locked_content`. Every `lock_version` bump goes through `_advance_locked_draft`. The only revision materialiser is `materialize_or_reuse_revision`. The only transaction-timestamp read is `database_transaction_timestamp`. The only both-parent locker is `_lock_current_parents`: the AST scanner passes, and my sabotage S1 proved it catches an inline rogue locker.
- The only `graph_release_test_run` writer is `link_release_evidence`.
- The only `agent_test_run` DELETE is W9.
- `rg` for `content_hash ==` / `current_timestamp()` / `verdict == "approved"` in `src` returns only:
  - the shared helpers;
  - W2's L3 literal (the deliberate C45 spelling);
  - W8's row-local check.
- **No diverged copy found.**

## 2. Lock-order table and deadlock-freedom ruling

Global order: **[advisory bootstrap lock] → L0 release → L0 draft → L1 draft agents → L2 case rows (`FOR SHARE`, unfiltered, id order) → L3 run rows (`FOR UPDATE`, id order)**.

| Path | Advisory | L0 release | L0 draft | L1 | L2 | L3 | Remote call under a lock? |
|---|---|---|---|---|---|---|---|
| W1 publish | — | UPDATE | UPDATE (same stmt, `OF` order) | UPDATE ×7 by key | SHARE | UPDATE | **No** (C37; `_changed_candidate_issues` runs only the local + post-stale validators) |
| W4 draft saves | — | UPDATE | UPDATE | UPDATE ×1 | — | — | **Yes, #266's remote endpoint check under L0, ≤ ~15 s (C51, pre-existing)** |
| W5 bootstrap re-boot | ✔ | SHARE | SHARE | — | — | — | No |
| W5 first boot | ✔ | (no rows) | — | — | — | — | No |
| W6 case writers | — | — | — | — | UPDATE (one role) | — | No |
| W7 run insert | — | SHARE | SHARE | — | (FK KEY SHARE on case) | — | No (the model call is outside the txn, C50) |
| W8 verdict | — | — | — | — | — | UPDATE ×1 | No |
| W9 cleanup | — | SHARE | SHARE | — | — | UPDATE, id order | No |
| W10 session creation | — | UPDATE (release only) | — | — | — | — | No |
| R1 preview / read / readiness | — | SHARE | SHARE | — | — | — | No |

**Ruling: deadlock-free.** Every path acquires a prefix-consistent subsequence of the global order. No path takes an earlier level after a later one.
- **The release and draft L0 order** is fixed by the `OF` list of the one statement, which is pinned for both modes. Every other both-parent locker is barred by the scanner.
- **The implicit FK locks** are these:
  - #267's run insert takes `KEY SHARE` on the case row and the compared release, but only while already holding L0 `SHARE`. So publication, which needs L0 `UPDATE`, can never hold the release while waiting on it.
  - The case writer never waits on L0.
  - Publication's link INSERT takes `KEY SHARE` on runs it already holds `FOR UPDATE`.
- **Multi-row L2/L3 lockers:**
  - The gate's L2 and W6 both lock in id order. W6 locks one role and the gate locks several roles in one statement, and they cannot cross.
  - The gate's L3 and W9 both lock in id order. They also never overlap in time, because L0 `UPDATE` excludes L0 `SHARE`.
- **Session creation** takes the release only, so it can never hold the draft.
- **#266's remote call** runs under the saves' L0. That is the longest L0 hold in the system, and it is pre-existing and bounded. #269 adds no remote call under L0: I checked publish, preview, the gate and bootstrap.

## 3. Rollback guarantee

**Ruling: no partial state is possible, and no `IntegrityError` is swallowed.**
- **One transaction.** Every write of W1 (the interval close, the new release, 7 mappings, new revisions, evidence links, and the draft rebase plus audit) runs inside the one `with session.begin()` block at `publication.py:286`. Any exception rolls the whole block back.
- **Nothing is caught inside the service** except `DraftContentRejected`, which is converted to a list of issues (:454) and then raised as `PublicationRejected`.
- **The route** (`agent_definitions.py`, publish handler) catches exactly two exceptions:
  - `PublicationRejected` → 403 when the actor field fails, otherwise 422;
  - `GraphConfigurationIntegrityError` → 500.
- **SQLAlchemy `IntegrityError` is not caught anywhere** in the new code (the `except` clauses at diff lines 3627, 3639, 3767, 3809 and 3824 are all listed above), so it propagates as a 500 after the rollback.
- **Refusal outcomes** (`PublicationConflict`, `NothingToPublish`, `PublicationNotReady`) return from inside the block before any write. Nothing is flushed at that point: the gate and readiness only read, and there are no dirty ORM rows.
- **Tests:** C8's stage injection (`test_injected_failure_rolls_back_every_row[stage]`) covers every write seam, including `evidence_linked`, with full-rollback asserts.
- **For #270:** `_commit_locked_publication` keeps the same guarantee as long as #270 calls it inside its own single `session.begin()`.

## 4. Publication safety invariant (re-derived)

**Claim:** no interleaving publishes a changed role whose active required case lacks an eligible approval for the current candidate hash and the case's current version.

Under L0 `FOR UPDATE`, the question is what can still change each input the gate relies on.

1. **The candidate hashes.** Only W4 writes `graph_draft_agent`, and W4 needs L0 `UPDATE` first, so it is excluded for the whole transaction. The snapshot and the gate's `hashes` come from rows read after L0 (and L1). My S3 confirmed this: reading the snapshot before L1 is behaviourally equivalent, and only the statement-sequence pin catches it. L1 is therefore defence in depth, not load-bearing.
2. **The set of active required cases per changed role.** L2 `FOR SHARE` locks every existing row of those roles, unfiltered, so no W6 writer can change any locked row after L2. If W6 was mid-supersede when L2 waited:
   - the retired row is still locked (no filter);
   - the new version is seen by the NEW re-select statement;
   - the new row cannot be changed afterwards, because every W6 writer locks the whole role in id order and blocks on the lower-id row we already hold `FOR SHARE`.

   A role with zero case rows gets no L2 protection. A concurrent create is then invisible and yields `no_required_case`, which is a refusal (the safe direction).
3. **The eligibility of each run.** L3 locks the runs that are approved in the lock statement's snapshot, and EPQ re-checks the literal columns on the newest row version:
   - **approved → rejected while waiting:** the row is dropped (refusal);
   - **rejected/null → approved while L3 runs:** the row is invisible to the snapshot and not locked (refusal);
   - **after L3:** W8 blocks.

   The re-verify is a NEW statement using the shared clause, joined to rows locked at L1/L2. W9 cannot run at all, because it needs L0 `SHARE`. A new run inserted by W7 needs L0 `SHARE` and would be unapproved anyway.
4. **After commit.** The links are FK `RESTRICT`, so they are undeletable. W8 refuses a changed verdict (C48), and the PG trigger backstops direct writes.

**Conclusion:** every input to the decision is either locked or can only move in the refusing direction. The invariant holds. Optional and inactive cases are never linked, and each case links only its newest eligible approval (Q5).

## 5. Contract parity

**Python wire:** `src/api/schemas/graph_releases.py`, plus the #268 `IneligibleForApprovalResponse` reason `linked_to_release`.
**TS parsers:** `frontend/src/api/agentDefinitions.ts:1888+`.
**Joins:** `tests/unit/test_graph_release_client_join.py` and `test_draft_readiness_client_join.py`.

Checked for:
- key lists at every level (`extra="forbid"` ↔ `hasExactKeys`);
- the 12 diff fields in order;
- the gap codes, and the rule that `test_case_id` is null iff `no_required_case` (both sides);
- `next_version_number ≥ 2`;
- the seven mappings in Graph order (a Python validator ↔ TS `isSevenMappings`);
- `evidence_kind: Literal["approval"]` ↔ `'approval'`;
- the note cap of 2000 counted in code points on both sides;
- the three 409 codes and the one 422 code;
- the readiness object parsed only by #268's `parseDraftReadinessResponse`, so there is no second type;
- the `linked_to_release` literal on both sides, with its message.

**Nothing is loosened or aliased.** The TS side is stricter in three harmless places:
- it requires Graph order on `changed`;
- it requires ascending diff-field order;
- it requires non-empty 422 `errors`.

The server always satisfies all three.

## 6. Frontend

- **One reducer, one counter, one gate.** `useReviewAndPublish.ts` has one `useReducer`, one `nextRequestIdRef` and one `publishInFlightRef`. `canPublish` is the one gate: it is used by the button, the hook and the reducer's `publishStarted`, and it never reads readiness (C32).
- **Forbidden actions.** `ALLOWED_ACTION_NAMES` has 8 entries; the new one is exactly `'Review & Publish'`. The whole-name exemption is unchanged. The length is pinned at 8 in both lanes (`AgentDefinitionWorkbench.test.tsx:378`, `agent-definition-workbench.spec.ts:1518`).
- **Text-only rendering.** There is no `dangerouslySetInnerHTML` or `innerHTML`, and every server string is rendered as a text node. 422 messages are client copy, except the service's own `definitions.<role>.*` triples, which are guarded by `Object.hasOwn`.
- **The route** sits inside `RequireAdmin` (`App.tsx:55`).

## 7. CI

- **PostgreSQL files.** The 4 new PG files are in `integration-graph` (`test.yml:465-468`), and each is pinned by `test_ci_collects_integration_tests.py:342-398`.
- **Playwright.** `graph-release-review` is in the e2e matrix (`test.yml:727`, from the controller's `986122f55`). `test_e2e_matrix_covers_specs.py` is GREEN in my full run.
- **Test files.** `admin-route-gate.spec.ts` and `agent-definition-workbench.spec.ts` were already in the matrix. No new unit file needs CI enrolment.

## 8. Parked items: adjudication

| Item | Ruling |
|---|---|
| Task 1 C8 prediction erratum (M04 REDs with `PendingRollbackError`) | **Accept.** It is text-only: the mutant is still RED, and the ledger records the observed cause. |
| Task 2 M-b (the C49 seam table and C51 lock table not written into the plan doc) | **Accept, no plan edit.** `PLAN-CORRECTIONS.md` overrides the plan, and §1–§2 above are now the authoritative writer and lock tables, including #266's remote check under L0. |
| Task 5 m2 (dead `builder_run = None` at `test_graph_release_routes.py:709`; the test lacks `_release_count == 1`) | **Fix now (m1).** |
| Task 5 m3 (`# type: ignore[attr-defined]` on `readiness_result.blocking_agents`, `graph_configuration_publication.py:424`) | **Fix now (m2).** Type `readiness` as a small `Protocol` with `blocking_agents: tuple[str, ...]`, or as `Callable[[Session], DraftReadinessResult]` under `TYPE_CHECKING`, and drop the ignore. |
| Task 7 brittle inline-style splash selector (`admin-route-gate.spec.ts:183`, `div[style*="background: #1a1a2e"]` ↔ `App.tsx:105`) | **Park (m5).** It fails loudly rather than silently: if the splash is restyled, the wait times out RED. A follow-up can add `data-testid="app-setup-splash"` to `App.tsx` and key on it. |
| C14 prediction erratum (the RED is now `test_linked_verdict_trigger_rejects_a_direct_update_after_migration_rerun`) | **Accept.** It is recorded in the ledger, and C48 covers the route path. |
| #270: widen `evidence_kind` for `historical_restore` | **Park to #270 (confirmed in #270's plan, I3).** #270 must widen the Python `ReleaseEvidenceResponse.evidence_kind`, **add `source_release_id` to the wire** (the dataclass has it, the wire drops it), and update the TS `ReleaseEvidence`, `isReleaseEvidence` and the join test together. |
| #270: `link_release_evidence` takes no lock; callers must lock runs first | **Park to #270, binding.** The restore must lock the source release's linked runs `FOR UPDATE ORDER BY id` before linking (C33 addendum). Two things already make this lower-risk: source-linked runs are FK-RESTRICT undeletable and verdict-frozen (C48 plus the trigger). Keep the lock anyway, so two L3 lockers never cross. |
| Task 2 M-c double-publication bound (a 3-way race returns the byte-identical diagnosis as a 500) | **Accept.** It is the same bound as session creation's `MAX_ACTIVE_RELEASE_LOCK_SCANS`, and it needs three concurrent publishers. |
| Task 3 `test_usage_service.py` midnight flake | **Accept as pre-existing** (#269 does not touch it). My full run did not cross midnight. |
| Task 8 m1/m2 | **Accept** (as ruled). |

## 9. Findings

### Minor

- **m1 — fix now.** `tests/unit/test_graph_release_routes.py:709`: drop the dead `builder_run = None` and add `assert _release_count(session_factory) == 1` to `test_a_changed_role_without_a_required_case_is_a_null_case_gap`.
- **m2 — fix now.** `src/services/graph_configuration_publication.py:365,424`: type the readiness callable's result so the `type: ignore[attr-defined]` can go. This is Task 5's m3.
- **m3 — park to #270.** `src/services/graph_configuration_workbench.py:196-213` and `graph_configuration_publication.py:343-351`: the L0 and L1 lock statements carry no `populate_existing`, while the gate's L2/L3 do (C45).
  - It is correct today, because every caller locks first in a fresh transaction (`session.begin()` refuses an already-begun session, and `expire_on_commit` expires prior objects). #267's `_persist_run` even calls `expire_all()`.
  - #270's rollback must keep the lock-first discipline, or add `populate_existing` to both statements. `populate_existing` is an execution option, so it does not change the SQL text the shape pins check.
- **m4 — park.** `frontend/src/components/Admin/GraphRelease/useReviewAndPublish.ts:39-47`: `publish()` checks `canPublish` against the render-closure `state` and then sends the POST, even when the reducer refuses `publishStarted` because the live state has moved (for example, a reload dispatched but not yet rendered).
  - In that case the POST is sent and its outcome is dropped, because the status is not `publishing`.
  - It is very narrow in practice: React flushes discrete events first, and the button is disabled. Server-side it is harmless, because the lock version protects it.
  - Fix later by gating the POST on the reducer accepting the start. Alternatively, keep a `stateRef` and re-check `canPublish(stateRef.current)`.
- **m5 — park.** The splash selector in `admin-route-gate.spec.ts:183` (see §8).
- **m6 — accept.** The AST scanner (`test_graph_parent_lock_is_single_sourced.py`) sees both parents only within one function, so a rogue locker split across two helpers would evade it. My S1 showed the PG harness (`_RaceObservedGraphConfiguration`) still catches a save that bypasses the helper. Record the limit; no change.
- **m7 — accept.** L1 (`_lock_all_draft_agents`) is behaviourally redundant under L0 `FOR UPDATE`: my S3 was caught only by `test_publication_lock_statement_sequence`. Keep it as defence in depth. The statement-shape pin is what keeps it.

### Not a #269 finding (recorded)

`tests/integration/test_shared_deck_mutation_attribution.py`, which is in `integration-graph`, hangs locally in `test_direct_crud_records_exactly_one_named_event_for_each_actor_classification`:
- The main thread sits in `time.sleep` at 0% CPU with no DB activity.
- I reproduced the same hang at base `16aa02b76` in a throwaway worktree (60 s timeout, exit 124). #269 changes no file on that path.
- Its first 22 tests pass. It is an environment issue with the fake `DATABRICKS_HOST` and a SQLite `DATABASE_URL`. CI uses a PG `DATABASE_URL`.
- It is a candidate GitHub issue; GitHub is read-only here.

## 10. Gates (run by me at HEAD `d5ca5ffb6`)

**Full unit suite: 6 failed / 6957 passed / 110 skipped** (371 s). The failures are the baseline six by node and first line:

| Tests | Cause |
|---|---|
| `test_deploy_autoscaling::TestGetOrCreateLakebase` ×2 | `'provisioned' == 'autoscaling'`; `_get_or_create_lakebase_provisioned … Called 0 times` |
| `test_style_exclusivity_chokepoint::TestModelDumpIsNotTheChokepoint` ×3 | `'_FakeSession' object has no attribute 'execute'` |
| `test_style_exclusivity_persistence_boundary::…::test_session_manager_create_session` | `no active Graph Release` |

No new cause, and the run did not cross UTC midnight.

**PostgreSQL:** every `integration-graph` file, one invocation each, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres` set explicitly, **0 skips across all files**.

- **The 4 #269 files:**
  - publication 21;
  - session ordering 29;
  - evidence 18;
  - acceptance 3.
- **The files #269 extends:**
  - constraints 66;
  - bootstrap 3;
  - workbench 49;
  - overlay 10.
- **The remaining files:**
  - orchestration 19;
  - graph mode turn 39;
  - pin migration 1;
  - shared-deck migration 3;
  - lifecycle 4;
  - collaboration history 30;
  - mixed-release collaboration 26;
  - pin creation 2;
  - mixed creation 14;
  - creator exclusions 4;
  - runtime failures 7;
  - pin acceptance 1;
  - dirty-marker routes 11;
  - sweeper 18;
  - architect reply 9;
  - insert slide 8;
  - slide id 14;
  - deck spec change 9;
  - spec row alignment 10;
  - claim exclusivity 3 passed + 1 xfailed.
- **Exception:** `test_shared_deck_mutation_attribution.py` hung, and the same hang reproduces at base (§9).
- **Databases:** afterwards the `tellr_int_*` list is exactly the 4 older databases, and none leaked. `ai_slide_generator` was never touched.

**Frontend:**
- Vitest 886/886 (20 files).
- `tsc -b` clean.
- ESLint clean on every changed `.ts`/`.tsx` file.

**Playwright:**
- `agent-definition-workbench`, `graph-release-review` and `admin-route-gate`: 93/93 passed.
- Port 3000 was free before and after.

## 11. Sabotages (temp worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/wbr-269`, detached at HEAD, removed afterwards)

**S1 — a draft save bypasses `_lock_current_parents`** (cross-cutting: save ↔ publication ↔ AST scanner).
- **Change:** `_read_workbench_for_draft_write` calls a new inline `_wbr269_rogue_parents` instead. It reads the release unlocked and locks only `graph_draft` `FOR UPDATE`.
- **Marker:** `WBR269_S1_ROGUE`, anchor count 1 (the replaced call). There are 2 marker hits in `src`: the call and the helper, both on the executed path.
- **RED:**
  - unit `test_only_lock_current_parents_locks_both_graph_parents` (1 failed / 197);
  - PG publication 2 failed / 19: `test_publication_first_then_draft_save_gets_stale_not_500` and `test_draft_save_first_then_publication_is_stale`, both at the race harness ("waiter never reached its lock" / "blocker never paused").
- **Restore:** `git checkout -- src`. The tree is clean, with 0 marker hits.
- **GREEN:** PG publication 21 + scanner 2 = 23 passed, 0 skips.

**S2 — publication writes the draft audit without the shared `_advance_locked_draft`** (the `lock_version` bump is dropped; cross-cutting: publication ↔ draft save ↔ stale publisher).
- **Change:** `publication.py:547` becomes `draft_row.updated_by, draft_row.updated_at = actor, timestamp`.
- **Marker:** `WBR269_S2_NOBUMP`, anchor count 1.
- **RED:**
  - unit 2/80: `test_publish_two_changed_roles_creates_v2_with_exact_seven_mappings` and `test_an_approved_change_publishes_the_exact_200_body`;
  - PG 9/24, among them `test_publication_first_then_draft_save_gets_stale_not_500`, `test_two_publishers_one_winner_one_exact_stale_conflict[alpha|beta]`, `test_sequential_retry_after_success_is_stale`, `test_stale_publisher_after_intervening_save_is_conflict_not_v3` and the acceptance `test_edit_test_approve_preview_publish_pin_flow`.
- **Restore:** `git checkout -- src`. The tree is clean, with 0 marker hits.
- **GREEN:** unit 80/80, PG 24/24, 0 skips.

**S3 (extra, from the suggested list) — the gate reads the draft agent hashes before L1.** This takes the snapshot before `_lock_all_draft_agents`.
- **Marker:** `WBR269_S3_PRE_L1`, anchor count 1.
- **Prediction:** equivalent, because all draft-agent writers hold L0 `UPDATE`.
- **Result:** 1 failed / 111 across PG publication, evidence and acceptance plus unit publication and evidence. The one failure is only `test_publication_lock_statement_sequence`, the shape pin, so the prediction held (m7).
- **Restore:** clean, 0 markers. **GREEN:** PG publication 21/21.

Every sabotage DB was dropped by its fixture: the `tellr_int_*` count stayed at 4.

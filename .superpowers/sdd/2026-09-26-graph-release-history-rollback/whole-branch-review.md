# #270 whole-branch review: Graph Release history and rollback

- **Reviewer:** final whole-branch review (Opus), 2026-09-27.
- **Range:** `c7ea1d943..HEAD`. HEAD is `0a870f29c` on `plan/release-history-rollback-270`. 54 commits. The code diff has 35 files, +11,962/−166, excluding `docs/` and `.superpowers/`. Diff: `/tmp/wbr-270.diff`.
- **Read:**
  - `progress.md` (the whole ledger), `PLAN-CORRECTIONS.md` (C1–C47), and the task reports;
  - every changed `src/` file in full: `graph_configuration_rollback.py`, `graph_release_history.py`, the `graph_configuration_draft.py` extraction, the facade, the route block, and both schemas;
  - #269's `graph_configuration_publication.py` and `graph_release_evidence.py`;
  - #268's `eligible_approval_clause`, readiness, cleanup and verdict writer;
  - the frontend hook, reducer, tab, fixtures and the e2e spec;
  - #269's `whole-branch-review.md`, for the writer and lock tables.

## Verdict: MERGE AFTER FIXES

- **Counts:** Critical 0, Important 0, Minor 14, plus 1 observation.
- **Scope of the fix wave:** every fix is small.
  - It touches production code in two places: the m-2 de-dup, and the rollback log record for Task 6 m1.
  - Everything else is tests, fixtures or lint.
- **Nothing found touches** the publication safety invariant, the rollback guarantee, the lock order, or ids ≠ versions.

---

## 1. Writer-by-writer table (#269's table, extended)

Rows W1–W10 and R1 are unchanged from #269. I re-verified them at HEAD: the only #269 source change is the C36 extraction inside W4. The rows below are #270's additions, followed by W4 as changed.

| # | Writer (file:line) | Writes | Txn | Locks, in order | Predicates / guards | C33 | Shared helper |
|---|---|---|---|---|---|---|---|
| W11 | `restore_release` (`graph_configuration_rollback.py:311`) → #269 `_commit_locked_publication` (`publication.py:470`) | `graph_release` (close + insert, `restored_from_release_id`), `graph_release_agent` ×7, `graph_release_test_run` (historical_restore), `graph_draft` (rebase + audit, via the core), `graph_draft_agent` (reset roles only) | Own `with session.begin()` (:335). Every refusal returns or raises inside it, before the first write. | L0 release→draft `FOR UPDATE` (`_lock_current_parents(exclusive=True)`, the first statement, :336) → L1 all 7 draft agents `ORDER BY agent_key` (:339, #269's `_lock_all_draft_agents`) → L3 the source's linked candidate runs `FOR UPDATE OF agent_test_run ORDER BY id`, `populate_existing` (:569). No L2, and no gate (C30). | Request shape before any lock (:332). Stale lock → not found → source active → matches_active (revision ids) → incompatible (C32 validators, including #266's endpoint policy). All seven mappings `reused` (:385). `_verify_rebased_draft` re-reads the draft (:398). It also gets every core guard: the timestamp, `max(version)=active`, unchanged-reuse, the mapping read-back and the link read-back. | Yes. The snapshot, history and source are read after L0+L1. After L3 the link count is a NEW statement (:574). | `_lock_current_parents` ✔, `_lock_all_draft_agents` ✔, `_commit_locked_publication` ✔ (the one publication writer), `_assign_locked_candidate` ✔, `_read_history`/`_release_definitions` ✔ (C33). ✘ `_structural_issues` duplicates `_changed_candidate_issues` (m-2). |
| W12 | The three-way rebase: `_assign_locked_candidate` (`graph_configuration_draft.py:1013`), called from W11 (:391) and from `_write_locked_content` (:1032) | `graph_draft_agent` content columns + `candidate_hash` | The caller's | Its caller's L1 row lock (W11 holds all 7; W4 holds the selected role) | `reset` only when the draft hash equals the pre-rollback active hash and the restored hash differs (`_draft_effect`, :526). `kept` and `unchanged` are never written. | n/a (runs under the caller's locks) | Yes: the one attribute writer of `candidate_hash`, and the W4 hand copy was removed. The lock-version bump stays the core's single `_advance_locked_draft`. **Caveat:** `graph_configuration_content.py:129` also sets `candidate_hash=` as a keyword, in bootstrap's builder. That is why Task 3a m1's test overclaims. |
| W13 | `link_release_evidence` for `historical_restore` (`graph_release_evidence.py:211`), from the core's `_link_evidence` (:596) | `graph_release_test_run` rows with `evidence_kind='historical_restore'` and `source_release_id` = the selected source | W11's | None of its own. W11's L3 already holds every linked run `FOR UPDATE` in id order (#269's carry (2), C28). The FK `KEY SHARE` lands on runs it already holds, and on the closed source release. | No duplicate run; every run exists; exact read-back including kind and source. The wire pairs "source set" with "kind is historical_restore" on both sides (C38). | n/a (relies on W11's L3) | the one linker ✔ |
| R2 | `preview_rollback` (`rollback.py:248`) | none | Own | L0 `FOR SHARE` (the first statement). The remote endpoint check runs after the `with` block (:294), once per distinct endpoint (C34). | Same checks as W11, collected without raising | — | `_lock_current_parents` ✔, `_historical_evidence(lock=False)` ✔ (the same statement as W11 without the lock) |
| R3 | `compare_with_active` (:221), `list_release_history`, `read_release_detail` (`graph_release_history.py`) | none | Own (a service or route `db.begin()`) | None. The first statement fixes the release set with `populate_existing`, and later reads are filtered to it. | Exactly one active row, complete mappings, hash-validated revisions, candidate-only links | — | `_read_history` ✔ (one snapshot shared by history, detail, compare and restore) |
| W4 (changed) | Draft saves → `_write_locked_content` → `_assign_locked_candidate` | unchanged | unchanged | unchanged | unchanged | unchanged | Behaviour-identical extraction (C36). |

**Diverged-copy hunt:**
- **Publication writes.** The only writers of `graph_release` / `graph_release_agent` are still W1/W11, through `_commit_locked_publication`, plus bootstrap. The only `graph_release_test_run` writer is `link_release_evidence`.
- **Draft content writes.** The only `candidate_hash` attribute writer is `_assign_locked_candidate`. The only lock-version bump is `_advance_locked_draft`.
- **`_structural_issues` against #269's `_changed_candidate_issues` (parked m-2).**
  - The two loop bodies are byte-identical: `_save_local_validators()` then `post_stale_validators` in one `try`, re-fielded as `definitions.<key>.<field>`. Only the input differs: a contents mapping over all seven roles, against `model_nodes[key].draft.content` over the changed roles.
  - `_GraphConfigurationRollback` subclasses `_GraphConfigurationPublication`, so de-duplicating is a ~6-line change. `_changed_candidate_issues` would delegate to one helper that takes a contents mapping and iterates it in role order.
  - **Ruling: de-duplicate now.** The drift mode is real. A future validator phase added to publication would not apply to rollback. Rollback and publication would then disagree on what is publishable, and C32 exists to prevent exactly that.
- **`_RollbackRace` / `_seed_v4` against #269's `_Race` / `_seed` (parked Minor 3).**
  - `_RollbackRace` (`test_graph_release_session_ordering_postgres.py:550`) is a ~110-line near-copy of `_Race` (:144) in the same file. It differs only in thread names, the pause matcher and the absence of `publisher_holds`.
  - It is test-only, with no production drift risk, and each copy is exercised by its own 28 tests.
  - **Ruling: park** as a follow-up, parameterising `_Race` by writer name.
- **An unguarded copy of the core would pass the suite.** My sabotage S2 (§ Sabotage) shows it. Nothing pins that W11 writes through `_commit_locked_publication`: a faithful hand copy of the core that drops its integrity guards passes 249 of 250 tests. **New Minor N1:** add a unit spy asserting `restore_release` calls `_commit_locked_publication` exactly once, with `restored_from_release_id` = the source id. Alternatively, add an AST pin that `GraphRelease(` is constructed only in `publication.py` and `bootstrap.py`.

## 2. Lock order and deadlock-freedom, with rollback

Global order, unchanged: **[advisory] → L0 release → L0 draft → L1 draft agents → L2 case rows → L3 run rows**.

| Path | L0 release | L0 draft | L1 | L2 | L3 | Remote call under a lock? |
|---|---|---|---|---|---|---|
| W11 rollback | UPDATE (first stmt) | UPDATE (same stmt) | UPDATE ×7 by key | — | UPDATE `OF agent_test_run`, id order | **No** (`_structural_issues` runs the local + post-stale phases only; must-not-run fakes pinned) |
| R2 rollback preview | SHARE (first stmt) | SHARE | — | — | — | **No.** `_endpoint_warnings` runs after the txn commits (`rollback.py:294`), pinned by `test_preview_runs_the_remote_check_after_the_locked_transaction`. |
| R3 history / detail / compare | — | — | — | — | — | No |
| W1–W10, R1 | as in #269 | | | | | W4's #266 check under L0 is pre-existing |

**Ruling: deadlock-free.** Rollback acquires a prefix-consistent subsequence of the global order, skipping L2. Against each other writer:
- **Publish (W1) and a second rollback.** Both take L0 X as their first statement, so they serialise at L0. Task 4 proves both orders, and the C6 erratum lands the loser's wait on the `effective_to` UPDATE: a named RED, not a deadlock.
- **Draft save (W4).** L0 X: serialised.
- **Run insert (W7), cleanup (W9) and bootstrap re-boot.** Each needs L0 SHARE, which is excluded while rollback holds L0 X.
- **Case writers (W6).** They take only L2, which rollback never takes. There is no shared lock.
- **Verdict writer (W8).** It takes one run `FOR UPDATE`, then a new-statement link re-check (#269 C48). Rollback holds L3 on the source's runs in id order and only then inserts links. W8 holds a single row and waits on nothing else, so there is no cycle. Task 4 proves the `change_refused` and `identical_noop` cases.
- **Session creation (W10).** It locks the release only and never holds the draft. Task 5 proves 7 creators × both orders.
- **Implicit FK locks.** Mapping inserts take `KEY SHARE` on reused revisions, which no writer ever locks. Link inserts take `KEY SHARE` on runs rollback already holds, and on the closed source release, which no writer locks. After #269 no path locks a non-active release.

**Confirmations:**
- **Every lock is the first statement of a fresh transaction.** W11 and R2 open `session.begin()` and call `_lock_current_parents` first. The AST scanner `test_graph_parent_lock_is_single_sourced.py` is **GREEN** at HEAD.
- **No remote call under L0.** Confirmed for W11, R2 and R3.
- **The preview's remote check follows its commit (C34).** Confirmed.

## 3. Rollback guarantee (six injection stages)

**Ruling: no partial state is possible, and no `IntegrityError` is swallowed.**
- **One transaction.** Every W11 write runs inside the one `with session.begin()` at `rollback.py:335`: the interval close, the new release, the mappings, the links, the core's draft rebase and audit, the reset writes, and the verification. Every exception rolls the whole block back.
- **Exceptions caught in the service.** Only two:
  - `DraftContentRejected`, which becomes an issues list (`:516`, `:607`);
  - `PublicationRejected`, which is merged in `_validate_rollback_request` before any lock (`:429`).
- **Exceptions caught in the rollback route** (`agent_definitions.py:1977`): `PublicationRejected`, `GraphVersionNotFound`, `RollbackIncompatible` and `GraphConfigurationIntegrityError`. All four are raised before any write, or roll the transaction back.
- **`sqlalchemy.exc.IntegrityError`** is caught nowhere in the new code. The test-only `except Exception` in the acceptance file's session manager re-raises.
- **Injection stages.** `test_injected_failure_rolls_back_every_row[stage]` covers `interval_closed`, `mappings_read_back`, `evidence_linked`, `draft_rebased`, `draft_reset` and `commit` (a real deferred-constraint IntegrityError at COMMIT). For every stage it asserts the byte-identical DB, no `historical_restore` rows, the pin still on v7, and a gap-free version on retry with the burned id. All 12 are GREEN on PostgreSQL at HEAD.

## 4. Publication safety invariant after rollback (re-derived)

**Claim:** `historical_restore` evidence can never satisfy the gate or readiness for a new publication.

**Derivation:**
- **Neither decision reads links.**
  - The gate's L3 predicate (`graph_release_evidence.py:98–116`) and its re-verify (`eligible_approval_clause`, `agent_test_workbench.py:640`) are functions of `agent_test_run` columns, the case row, and `graph_draft_agent.candidate_hash` only.
  - Readiness (`_readiness_statement`) uses the same clause.
  - Neither statement references `graph_release_test_run`. Links appear only in `_linked_run` (cleanup protection) and in the verdict writer's C48 refusal, and both of those move only in the refusing direction.
- **Linking a run as `historical_restore` changes nothing about that run.** It changes no run column, so it cannot make any run eligible. The linked runs were already linked to the source, so their verdicts were already frozen and cleanup already protected them. The restore link adds no new freeze.
- **After a rollback,** the draft's base is the restoring release, and `changed` is computed against it:
  - reset and unchanged roles are not changed, so they are never gated;
  - a kept or new edit is gated on runs of its own hash and its case's current version.
- **A source approval can still count only on the #269 terms.** It counts again only if a new draft's hash equals that run's hash and the case version is unchanged. That is the #269 definition of approval (content hash plus case version), not a restore effect.
- **The link's `source_release_id` is display-only.** Confirmed.

**Proof in the suite.** `test_historical_restore_evidence_never_satisfies_readiness[new_edit_after_rollback|kept_edit_from_before]` asserts that readiness and the locked gate both refuse. My sabotage S1 makes the gate treat a historical_restore link of the case as an approval, and both variants go RED. **The invariant holds.**

**The disclosed Q7 caveat.** A kept edit X that already had an approved run stays approved after the rollback.
- **Why it is not a safety hole:**
  - The invariant is defined over the candidate hash and the case version, and it still holds.
  - The approval certifies X's behaviour on the case. The case runs one role in isolation, and eligibility has never been base-relative: `compared_release_id` is not in the clause. #269 already permits the same thing on every ordinary publish, where an approval taken against v7 stays valid after v8 changes another role.
  - Nothing publishes X without an explicit publish. The Review & Publish preview, which rollback refetches (sabotage S3 proves this), shows the real v3→X diff before that publish.
- **Ruling: acceptable.** Recorded as observation O1.
- **Optional UX follow-up (park):** make the `kept` label say "Pending edit kept; its existing approvals still count."

## 5. ids ≠ versions

**Ruling: no version is resolved by id anywhere in #270, #269 or #268.**
- **#270:**
  - Every route addresses `{version_number}`.
  - `_source_from_history` and `read_release_detail` match `e.version_number == version_number`.
  - `next_version_number` is `release_row.version_number + 1`, and the default note uses `source.ref.version_number`.
  - The frontend `releaseVersionUrl` takes a version.
  - No component reads any `*_release_id` field. A grep over `frontend/src` outside the API module and the tests is empty.
  - The fixtures use id = version + 40 (frontend), a v1 id of 11 (SQLite), and a real burned sequence value (PostgreSQL).
- **#269 / #268:**
  - `grep` for `.id ± 1`, a `version_number`↔`.id` comparison, or `session.get(GraphRelease, …version)` over `src` returns only `rollback.py:393`, which is `get(GraphRelease, published.release.release_id)`, an id. That is correct.
  - The publication core uses `max(version_number) + 1`.
  - Pins, bootstrap and the workbench carry both fields explicitly.
  - `conversation_pins.py:171` looks up v1 by `version_number == 1`, which is correct.
  - #268's `compared_release_id` and `base_release_id` are ids, used as ids.
- **The carry to #271 can be closed.**

## 6. Contract parity

**Python wire:** `graph_release_history.py` plus the widened `graph_releases.py:104–146`.
**TS parsers:** `agentDefinitions.ts`, #270 block.
**Joins (all 6 GREEN in the unit gate):** `test_graph_release_client_join`, `test_graph_release_history_client_join`, `test_draft_readiness_client_join`, `test_endpoint_name_policy_client_join`, `test_probe_failure_contract_client_join`, `test_test_run_failure_contract_client_join`.

- **Checked and matching:**
  - exact keys at every level;
  - the `evidence_kind` pair, where the source is set exactly for `historical_restore`, on both the wire item and the history item;
  - publication stays approval-only on both sides (`graph_releases.py:144`; TS `every(... === 'approval')`);
  - a rollback success must have all seven mappings reused and historical_restore-only evidence;
  - `restorable` is exactly `blocked is None`;
  - the seven roles in order for `agents`, `definitions`, `draft_effect` and `mappings`;
  - the literal sets for `DraftEffect` and `RollbackBlock`, verdicts and execution statuses;
  - the five refusal codes;
  - `next_version_number ≥ 2`, and `version_number ≥ 1`.
- **#269's edits** (the join test, the route body test, `source_release_id: None`) are extensions, not loosenings: the approval-only rule is now asserted by name for each kind.
- **The TS side is stricter in harmless places:** Graph-ordered `changed_agents`, ascending `restored_by`, newest-first ordering with one active row equal to `active_release`, and instant parsing.
- **Nothing is loosened.**
- **Not checked on either side:** that each success evidence item's `source_release_id` equals `restored_from.release_id`. The service guarantees it (`rollback.py:585`), so there is no parity gap. Optional.

## 7. Frontend

- **One gate for both writes.**
  - There is one `useReducer`, one `nextRequestIdRef`, and one `writeInFlightRef` shared by `publish` and `confirmRollback` (`useReviewAndPublish.ts`).
  - The reducer also cross-gates: `canPublish` refuses while `rollingBack`, and `canConfirmRollback` refuses while `publishing`.
  - `confirmRollback` decides on `stateRef.current`, the reducer-synchronous mirror, so #269's m4 is not copied (#269's `publish` still reads the last render: parked there).
- **Refetches.** A rollback success refetches the history and the preview exactly once each. A publish success refetches a loaded history too.
- **Text-only rendering.** No `dangerouslySetInnerHTML`, `innerHTML`, `eval` or dynamic `href`: the only `href` is the static "Back to Admin". A release note of `<img onerror>` renders as text (Vitest).
- **Forbidden actions.** `ALLOWED_ACTION_NAMES` has length 8, asserted in `AgentDefinitionWorkbench.test.tsx:378`. The stem sweep covers the workbench only, per C40 and the stem-name ruling. e2e (h) proves the workbench sweep still flags "Release history" / "Rollback release".
- **New Minor N2:** ESLint on the changed files reports **1 error**: `rollbackPreviewCallCount` is assigned but never used at `frontend/tests/e2e/graph-release-history.spec.ts:645`. CI runs no ESLint job, which is why it survived. Fix: delete the counter.

## 8. CI

- **PostgreSQL enrolment.** All 4 new PostgreSQL files are in `integration-graph` (`test.yml:469–472`), and the list now has 33 files. Each is pinned in `test_ci_collects_integration_tests.py`, which is GREEN.
- **e2e matrix.** `graph-release-history` is in it (`test.yml:731`), and `test_e2e_matrix_covers_specs` is GREEN.

## 9. Fix-wave adjudication

| Item | Ruling | Why / what |
|---|---|---|
| Task 3a m1: the AST "only candidate_hash writer" test overclaims | **Fix now** | The test sees attribute assignment only. It misses the keyword `candidate_hash=` at `graph_configuration_content.py:129` (bootstrap's builder), `setattr` and Core `.values`. Rename it to "only attribute writer" and extend it to keyword args and `.values(...)` with an explicit allowlist (`graph_configuration_content.py` builder). Test-only. |
| Task 3a m2: no restore-level endpoint-policy refusal case | **Fix now** | Add a case where `restore_release` raises `RollbackIncompatible` on an endpoint-policy name and writes nothing. It pins the refusal before the write, not just in the preview. Test-only. |
| Task 3b M1: per-release historical_restore check | **Accept** | The global `count(*) = 0` is strictly stronger than a per-release check, because no restore link exists before the test. |
| Task 5 Minor 1: literal id pairs in `_seed_v4`, and v5 id 6 | **Fix now** | Cheap. It carries the ids ≠ versions proof into the 28 session tests. |
| Task 5 Minor 2: `race.scans` in the flushed-rollback test | **Fix now** | Cheap test assertion. |
| Task 5 Minor 4: Task 4's cleanup test asserts R2's full link list | **Fix now** | Cheap test assertion. |
| Task 6 m1: rollback log record missing | **Fix now** for raw `IntegrityError` and `AssertionError`: wrap the service call and outcome mapping, and on any other exception log one ERROR record `outcome="error"` with `error_class` and no traceback, then re-raise. **Accept** the path-int 422: FastAPI rejects it before the handler runs, and the client cannot produce it (`releaseVersionUrl`). | Keeps the rule of one record per handled call. |
| Task 8: `syntheticHistoryEntry` produces invalid days | **Fix now** in `mocks.ts`: compute dates with `Date.UTC(2026, 8, 20 + v)` → ISO. Drop `historyV12`'s local override. | The bug starts at **v = 10**, not 11: `effective_to` is day 31, and V8 silently rolls `2026-09-31` to Oct 1. Days of 32 or more are NaN. |
| Task 9 M01: step 11 checks `changed` for 3 of 7 roles | **Fix now** | Assert the full seven-key mapping. |
| Task 2 m-2: `_structural_issues` duplicates `_changed_candidate_issues` | **Fix now** | See §1. Re-run #269's publication, preview and route tests after the change. |
| Task 5 Minor 3: `_RollbackRace` / seed duplication | **Park** | Test-only, with no production drift. Follow-up issue. |
| **N1 (new):** no pin that rollback writes through the core | **Fix now** | A unit spy on `_commit_locked_publication`, or an AST pin on `GraphRelease(` constructors. See S2. |
| **N2 (new):** ESLint unused variable in the e2e spec (`:645`) | **Fix now** | A one-line delete. |
| **N3 (new):** the "gate never reads links" invariant is proven only on PostgreSQL | **Park** | S1 went RED on PostgreSQL (2) but on no unit test (0/143). CI runs the PostgreSQL file, so this is not a gap in CI. An optional unit AST pin could assert that `graph_release_evidence`'s gate functions and `_readiness_statement` never reference `GraphReleaseTestRun`. |
| **O1:** the Q7 caveat | **Accept** | See §4. Optional follow-up on the label copy. |

## 10. Merge verdict: MERGE AFTER FIXES

**Fixes:** 3a-m1, 3a-m2, 5-M1, 5-M2, 5-M4, 6-m1 (IntegrityError and AssertionError logging), the Task 8 fixture, 9-M01, 2-m-2, N1, N2.

**Park:** 5-M3, N3, and the O1 label copy.

**Accept:** 3b-M1, and the path-int 422 part of 6-m1.

---

## Gates at HEAD `0a870f29c`

- **Full unit suite** (from inside the tree, SQLite `/tmp/wbr-270.sqlite`): **6 failed / 7149 passed / 110 skipped** in 7:23. The 6 are the baseline nodes and causes:
  - `test_deploy_autoscaling` ×2 (`'provisioned' == 'autoscaling'`; the provisioned mock was not called);
  - `test_style_exclusivity_chokepoint` ×3 (`'_FakeSession' object has no attribute 'execute'`);
  - `test_style_exclusivity_persistence_boundary` ×1 (`no active Graph Release`).

  The run did not cross midnight, and no other cause appeared.
- **PostgreSQL:** all **33** `integration-graph` files, one invocation each, with `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres` and a per-file SQLite `DATABASE_URL`.
  - **549 passed**, 0 failed, **0 skipped**, every exit 0. There is 1 xfail in `test_claim_exclusivity_postgres.py`, which is a pre-existing marker, not a skip.
  - `test_shared_deck_mutation_attribution.py` ran under `timeout 120`: 60 passed in 17 s. The intermittent hang did not reproduce.
  - The #270 files: history 5, rollback 12, rollback ordering 12, rollback acceptance 1. #269's session ordering with Task 5 appended: 57.
  - `tellr_int_*` list identical before and after, the 5 older ones only; nothing leaked and nothing dropped.
- **Frontend:**
  - `npx vitest run`: **21 files / 1090 passed**.
  - `npm run typecheck` (`tsc -b`): clean.
  - ESLint on the 14 changed TS/TSX files: **1 error** (N2).
- **Playwright** (the only lane on :3000; the server was Playwright-managed and has stopped): graph-release-history 9, graph-release-review 9, admin-route-gate 6, agent-definition-workbench 78, which is **102 passed**.

## Sabotage (temp worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/wbr-270`, detached at HEAD, since removed)

**S1: the publication gate accepts `historical_restore` links as approvals.**
- **Anchor:** `        covered = {case.agent_key for case in cases}` in `graph_release_evidence.py`, count 1.
- **Change:** injected before the anchor. For each case with no chosen approval, it takes any run linked with `evidence_kind='historical_restore'` for that case as the approval.
- **Marker:** `WBR270_S1`, count 1, on the executed path of `lock_and_verify`.
- **RED:**
  - PostgreSQL `test_graph_release_rollback_postgres.py`: **2/12**, `test_historical_restore_evidence_never_satisfies_readiness[new_edit_after_rollback]` and `[kept_edit_from_before]`. Both fail with `PublishedRelease(... version_number=9 ...)` where `PublicationNotReady` was expected.
  - Evidence PostgreSQL 18/18, publication PostgreSQL 21/21 and rollback acceptance 1/1 stayed green.
  - Unit rollback/evidence/history/publication: 0/143 (N3).
- **Restore:** `git checkout -- src`, marker 0, `git diff --exit-code` clean.
- **GREEN:** rollback PostgreSQL 12/12.

**S2: rollback bypasses `_commit_locked_publication` and writes its own release row.**
- **Anchor:** `            published = self._commit_locked_publication(` in `graph_configuration_rollback.py`, count 1. The call was redirected to `_wbr270_s2_bypass`, a faithful hand copy of the core with its integrity guards dropped: the timestamp ordering, `max(version)=active`, unchanged-reuse and the mapping read-back.
- **Marker:** `WBR270_S2`, count 2 (the call and the method). The remaining `_commit_locked_publication(` count in the module is 0.
- **A first attempt was discarded.** It imported the clock from `graph_configuration_content` and went RED 15 on SQLite, via `ck_graph_release_interval`. That RED came from missing the tests' clock seam, not from detecting the bypass. I re-ran with the clock resolved through the publication module.
- **RED:**
  - Unit rollback/history/history-routes/publication: **0/178**.
  - PostgreSQL: rollback **1/12** (`test_injected_failure_rolls_back_every_row[mappings_read_back]`, only because the copy omits the read-back statement the injector matches); rollback ordering 0/12; acceptance 0/1; session ordering 0/57; history 0/5.
- **Finding:** a bypass that keeps the read-back would be 0 RED. This is N1.
- **Restore:** `git checkout -- src`, marker 0, clean.
- **GREEN:** rollback PostgreSQL 12 + rollback unit 57 + history routes 69 = 138 passed.

**S3: rollback success does not refetch the #269 preview.**
- **Anchor:** `if (restored) await Promise.all([loadHistory(), reloadPreview()]);` in `useReviewAndPublish.ts`, count 1. Changed to `Promise.all([loadHistory()])`.
- **Marker:** `WBR270_S3`, count 1.
- **RED:**
  - Vitest GraphRelease: **1/354** (`Release History: confirming a rollback > shows the success, then refetches the history and the release preview exactly once each`).
  - Playwright `graph-release-history`: **1/9** (`(d) successful rollback: … Changes & Approvals shows Draft base: Graph Version 8`, `toBeVisible` failed).
- **Restore:** `git checkout -- src`, marker 0, clean.
- **GREEN:** Vitest GraphRelease 354/354. Port 3000 was free afterwards.

Temp worktree removed (`git worktree list` shows no `wbr-270`). The `node_modules` symlink was removed first.

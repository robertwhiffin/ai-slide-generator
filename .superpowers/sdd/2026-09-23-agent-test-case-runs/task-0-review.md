# #267 Task 0 — independent task review

Range reviewed: `a143090164042b12d19a7693f10a4c6d06c76e4b..4d685d03d` (`c80ab897f`, `17cf746ec`, plus the report commit). Reviewer: independent task reviewer, 2026-09-26. Temporary worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/rev-267-0` (detached at `4d685d03d`). It was removed afterwards: `git worktree list | grep -c rev-267-0` returned 0.

## Spec Compliance: ✅ (with ⚠️)

The spec was read against the plan's Task 0 and PLAN-CORRECTIONS C1, C2, C11, C19, C21, C24 and C29–C40. Every binding item is present in the code:

- **C1 and C2.** `Float` is imported. Every FK is a named `ForeignKeyConstraint(..., ondelete="RESTRICT")`. `ForeignKey` is not imported.
- **C19, columns and FKs.**
  - `run_kind` has its own check.
  - `model_payload` is NOT NULL and `assembled_prompt` is nullable.
  - Both `compared_*` columns are NOT NULL.
  - `deterministic_check_results` is NOT NULL, with no server default.
  - The composite FK `fk_agent_test_run_compatible_revision` is `(compared_definition_revision_id, agent_key) → agent_definition_revision(id, agent_key)`.
  - Case-to-run `agent_key` equality is left to the service, as C19 requires.
- **C19, checks, indexes and exports.**
  - `ck_agent_test_run_completed_has_output` is present.
  - Both indexes are there, with no `index=True`.
  - Both models are exported from `src/database/models/__init__.py`.
  - The pins are extended: `EXPECTED_TABLES`, `ROLE_TABLES`, `EXPECTED_CHECKS`, FK count 12, and timestamps.
- **C21, test honesty.**
  - The PostgreSQL FK tests assert `pgcode == "23503"` and `diag.constraint_name`.
  - The `graph_release` targets are proved through `pg_constraint` (`confdeltype = 'r'`).
  - The linked-run delete uses a raw-SQL link row.
  - The check tests assert `23514` plus the constraint name. The NOT NULL tests assert `23502` plus `diag.column_name`.
- **C24.**
  - `trg_agent_test_run_evidence_immutable` is `BEFORE UPDATE` only, so DELETE stays allowed.
  - It is idempotent: `CREATE OR REPLACE FUNCTION` followed by `DROP TRIGGER IF EXISTS`. The idempotence test is extended.
  - It raises `23514`.
- **Scope.** The diff touches only the three Task 0 files, `src/database/models/__init__.py` and the report. Bootstrap, seed and hashing are unchanged.

⚠️ **Accepted deviation from the letter of C19.** The evidence JSON columns use `_EVIDENCE_JSON_DOCUMENT` (`none_as_null=True`) rather than `_JSON_DOCUMENT`. The ledger ruling stands. The deviation is pinned by the unit test, and the controller's sabotage proved it.

⚠️ **C24's "any column other than the four verdict columns" is implemented correctly but is only partly proved.** See I1.

## Strengths

- **The trigger compares the whole row** (`to_jsonb(NEW) - verdict[]` against `to_jsonb(OLD) - verdict[]`). A column added later is immutable by default, which is the right polarity for evidence.
- **I re-probed the trigger by column type in a throwaway PostgreSQL 14 database.** The setup was `create_all` plus `_run_migrations` ×3. The following verdict-only updates all passed:
  - a row whose `latency_ms` is `NaN`;
  - nested JSONB floats (`1e-300`, `0.1`), a nested null, and non-ASCII text;
  - a session `TimeZone` of `Asia/Kolkata` against a `run_at` set by the server default;
  - an ORM flush;
  - approve → reject, and clear-to-NULL.

  A no-op self-assignment of evidence columns also passes. Real changes to `run_at`, `id`, `agent_key`, `latency_ms` (`0.1` → `0.1000001`) and `model_payload` are rejected with 23514.
- **Coexistence.** After three `_run_migrations` runs there is exactly one `guard_agent_test_run_evidence_mutation` function and one trigger. All pre-existing graph and collaboration triggers are still present and enabled (`tgenabled='O'`). The new block sits between the release-immutable and exactly-one-active blocks and reuses their `qualified()` and `preparer.quote()` pattern.
- **Test honesty is good.** There is no bare-`IntegrityError` FK assertion in PostgreSQL. The unlinked-run delete is proved to succeed, which keeps #268's cleanup possible. The `none_as_null` behaviour is proved with SQL `IS NULL` in PostgreSQL. The NOT NULL tests name the column.
- **Whole-repo `create_all`** builds cleanly on SQLite (unit fixtures) and PostgreSQL (the fixture plus my probe DB). There is no index-name collision and no FK-ordering or trigger-install failure.
- **The unit baseline was re-derived by cause.** It shows exactly 6 failed, 6194 passed and 110 skipped. The causes are identical to C39: autoscaling ×2 (`'provisioned' == 'autoscaling'`, `called 0 times`), `_FakeSession ... 'execute'` ×3, and `no active Graph Release` ×1.

## Issues

### Critical
None.

### Important

**I1 — the immutability test does not prove C24 for 6 of the 23 non-verdict columns: `id`, `test_case_id`, `agent_key`, `compared_release_id`, `compared_definition_revision_id` and `run_at`.**
- **Where:** `tests/integration/test_graph_configuration_constraints_postgres.py:423` (`EVIDENCE_COLUMN_REWRITES`), used by `:808` `test_postgres_agent_test_run_evidence_columns_are_immutable`.
- **What:** the parametrization covers only 17 columns. As mutation M3 below shows, adding all six missing columns to the trigger's exempt array leaves the file **59/59 GREEN**.
- **Why:**
  - These are the run's identity columns: which case, role, release and revision the evidence belongs to.
  - #269's approval gate filters on `test_case_id` and `agent_key`, and #268's readiness does the same. A regression that makes them writable would let an approved run be re-pointed at another case or release, and no test would notice.
  - `run_at` is also the timestamp with a server default that the named risk calls out.
  - The trigger is correct today, so this is a test gap, not a code defect.
- **Fix:**
  - Add rewrites for the six columns:
    - `run_at` → `now() + interval '1 second'` (or a fixed datetime);
    - `test_case_id` → a second architect case;
    - `compared_release_id` → the id of a second release;
    - `compared_definition_revision_id` → a second architect revision;
    - `agent_key` → a builder value (the trigger fires BEFORE the FK, so the result is 23514);
    - `id` → `id + 1000`.
  - Add a completeness assertion, so a future column cannot be silently left out:

    ```python
    set(EVIDENCE_COLUMN_REWRITES) == set(AgentTestRun.__table__.columns.keys()) - VERDICT_COLUMNS
    ```

  - Re-run M3; it should go RED on six ids.

### Minor

**M1 — the DDL lets a `published_baseline` run carry `verdict='approved'`.**
- **Where:** `src/database/models/graph_configuration.py:475`.
- **What:** my probe inserted an approved baseline run successfully.
- **Why:** #268's readiness query and #269's gate (plan :727-735) do not filter on `run_kind`. A baseline's `candidate_hash` is the published revision's hash, so it matches only in edge cases, such as a draft whose candidate equals the active revision when base ≠ active. The carry-forward is already in `progress.md`.
- **Fix (a product call for the controller):** either add an additive check such as `ck_agent_test_run_verdict_only_on_candidate` (`verdict IS NULL OR run_kind = 'candidate'`), or keep the carry-forward and make #268 and #269 filter `run_kind='candidate'` in their gates. Record which.

**M2 — `verdict_reviewer` has no non-blank check, and `verdict_notes` can be set with no verdict.**
- **Where:** `graph_configuration.py:424-426`.
- **What:** my probe accepted `verdict_reviewer='  '` on an approval, and it accepted a lone `verdict_notes` on a verdict-less row.
- **Why:** every sibling actor column has a `_nonblank` check (`run_by` `:487`, `created_by`, `updated_by`). #268 takes the reviewer from the principal, so the risk is low.
- **Fix:** optionally add `ck_agent_test_run_verdict_reviewer_nonblank` (`verdict_reviewer IS NULL OR length(trim(verdict_reviewer)) > 0`) and `(verdict IS NOT NULL) OR verdict_notes IS NULL`. Otherwise carry both to #268.

**M3 — the run's `test_case_version` and `agent_key` are not tied to the referenced case row.**
- **Where:** `graph_configuration.py:385-386`.
- **What:** my probe inserted a run with `test_case_version=7` against a version-1 case, and a `builder` run on an architect case.
- **Why:** C22 makes each version its own row, so `test_case_version` is a redundant snapshot. C19 accepted service-side enforcement for `agent_key`, and the same applies to the version. #269's gate compares both `test_case_id` and `test_case_version` against the locked case. A service bug that writes the wrong version would therefore make a valid approval permanently unusable, and the trigger would make it uncorrectable.
- **Fix:** Task 4 needs a test asserting that the run's `(agent_key, test_case_version)` equals the case row's values. Add it to the Task 4 brief next to C19's `agent_key` service-test note.

**M4 — the SQLite delete tests match only `"FOREIGN KEY"`.**
- **Where:** `tests/unit/test_graph_configuration_models.py:704` and `:711`.
- **What and why:** SQLite does not name the violated FK, so these tests cannot distinguish the case FK from the run-link FK. That is acceptable, because the PostgreSQL 23503 tests carry the proof.
- **Fix:** none needed, beyond a one-line comment saying so.

## Consumer-fit table

| Consumer | Assumption | DDL at `4d685d03d` | Fit |
|---|---|---|---|
| #267 Task 4 executor | Inserts the run once, verbatim, in transaction 2 under `_lock_current_parents(exclusive=False)` (C8, C32) | The insert takes FK `KEY SHARE` on `graph_release`, `agent_definition_revision` and `agent_test_case`. The release is already held `FOR SHARE` in release → draft order, so it is compatible and there is no new lock order. | ✅ |
| #267 Task 4 | Writes `run_kind`, `model_payload`, `assembled_prompt`, both `compared_*`, and `deterministic_check_results` with no default | All NOT NULL except `assembled_prompt`; there is no default on the check results | ✅; the service must also write the case's `agent_key` and `version` (M3) |
| #267 Task 5 | Serializes the columns with verdict excluded | The column set is stable | ✅ |
| #268 `record_verdict` | Updates only the four verdict columns, and may reverse approve ↔ reject | The trigger exempts exactly `verdict`, `verdict_reviewer`, `verdict_at` and `verdict_notes`. Reverse and clear both passed my probe. | ✅ |
| #268 Task 1 test | A direct `UPDATE verdict='approved'` on a failing run gives `IntegrityError` | This raises 23514 `ck_agent_test_run_approved_only_if_completed_and_passing` (the trigger passes, because only verdict columns change) | ✅; #268 should assert the constraint name, not a bare `IntegrityError` |
| #268 fixtures | Any fixture that "stales" a run by updating `candidate_hash`, `test_case_version` or `deterministic_checks_passed` | Rejected by the trigger with 23514 | ⚠️ differs: #268 and #269 tests must stale the **draft or case**, never the run row |
| #268 readiness and cleanup | Readiness filters `verdict`, `candidate_hash` and `test_case_version`. Cleanup is a `DELETE` with `NOT EXISTS` on `graph_release_test_run`, and `ix_graph_release_test_run_run` supports it. | DELETE is allowed on unlinked runs (proved) and gives 23503 on linked runs (proved) | ✅; ⚠️ differs: readiness does not filter `run_kind='candidate'` (M1, carry-forward) |
| #268 retention | Keeps the latest 20 per case by `run_at` | `ix_agent_test_run_case_run_at (test_case_id, run_at)` | ✅ |
| #269 approval gate (plan :727-745) | `FOR UPDATE` on runs by case, version, key and hash, then `verdict='approved'`, `completed` and `passed` | All the columns exist. The re-verified columns (`candidate_hash`, `test_case_version`, checks) are now DB-immutable, so the re-verify reduces to checking the verdict. | ✅; ⚠️ differs: no `run_kind` filter (M1) |
| #269 `link_release_evidence` | Inserts `(release, run, 'approval', NULL)` and reads it back | The PK `(graph_release_id, agent_test_run_id)`, the kind check and the source pairing all match plan :82 | ✅ |
| #269 retention ("cleanup cannot remove linked evidence") | `fk_graph_release_test_run_run` RESTRICT | Proved by 23503 and the constraint name. `pg_constraint` shows `confdeltype='r'` on all six FKs. | ✅ |
| #269 C14 `trg_agent_test_run_linked_verdict_immutable` | `BEFORE UPDATE OF verdict…`, body `IF EXISTS` link, same install function | Disjoint from this trigger: ours passes verdict-only updates. Name order is `evidence` < `linked`, so ours fires first. Both use 23514, and the messages differ. | ✅; #269's idempotence test must expect both `agent_test_run` rows, because the existing test pins an exact list (`:352`) |
| #269 lock order (L3 `FOR UPDATE` on runs, then the link insert) | The link insert takes `KEY SHARE` on runs that its own transaction already holds | No conflict. A verdict `UPDATE` takes `FOR NO KEY UPDATE`, which does not conflict with other transactions' `KEY SHARE`. | ✅ |
| #270 rollback via `HistoricalRestoreEvidenceGate` | Relinks the source release's runs to the new release as `historical_restore` with `source_release_id`, locking the runs `FOR SHARE` | A run can link to many releases (the PK is per release). `source_release_id` is NOT NULL only when the kind is `historical_restore`, and it is RESTRICT. | ✅; restoring V1 (no evidence) yields zero links, and whether `source_release_id` is the immediate or the original release is #270's decision |
| #270 or #271 | Graph Release rows are never deleted | Every FK into `graph_release` is RESTRICT, which is harmless | ✅ |

## Sabotage evidence

The environment for every run: `PYTHONPATH=<rev>:<rev>/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/rev-267-0.sqlite`, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, and `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:cacheprovider`, with one file per invocation. `test ! -e .venv` was checked before and after.

**GREEN baseline at `4d685d03d`:**
- `tests/unit/test_graph_configuration_models.py`: 27 passed.
- `tests/integration/test_graph_configuration_constraints_postgres.py`: 59 passed, 0 skipped.

**M1 (assigned target): widen the C24 exempt array with `'run_by'`**
- **Anchor:** the exempt array `ARRAY['verdict', 'verdict_reviewer', 'verdict_at', 'verdict_notes']` at `src/core/database.py:1083` and `:1086`.
  - It is one logical anchor with two textual sites (the NEW side and the OLD side). The assertion found `count == 2`, and I edited both sites.
  - Widening only one side would make every update fail, which would be RED for the wrong reason.
- **Marker:** `/*REV267_0_RUN_BY*/`, and `grep -c` gave 2.
- **Scope:** the PostgreSQL constraints file.
- **RED 1/59:** `test_postgres_agent_test_run_evidence_columns_are_immutable[run_by]`.
- **Restore:** `git checkout -- src/core/database.py`. The marker `grep -c` then gave 0 and `git status` was clean.
- **GREEN:** 59/59. This is the baseline run: the file was byte-identical after restore.

**M2 (own target): drop role-compatibility from `fk_agent_test_run_compatible_revision`**
- **Change:** `(compared_definition_revision_id, agent_key) → (id, agent_key)` became `(compared_definition_revision_id) → (id)`.
- **Anchor count:** 1. **Marker:** `# REV267_0_ROLE_FK`, and `grep -c` gave 1.
- **Unit scope, RED 1/27:** `test_agent_test_run_model_exists`.
- **PostgreSQL scope, RED 1/59:** `test_postgres_run_revision_fk_is_role_compatible`. The builder-revision insert was accepted instead of raising 23503.
- **Restore:** `git checkout`, marker 0, clean.
- **GREEN:** 27 and 59. These are the baseline runs; the file was byte-identical.
- **Why not the column-order swap:** reordering to `(agent_key, id)` pairs a VARCHAR with an INTEGER, so `create_all` would fail for every fixture. That is RED for the wrong reason, so I did not use it.

**M3 (gap probe, which is the evidence for I1): exempt `id`, `test_case_id`, `agent_key`, `compared_release_id`, `compared_definition_revision_id` and `run_at`**
- **Anchor count:** 1 logical anchor with 2 sites (`count == 2` asserted). **Marker:** `/*REV267_0_GAP*/`, and `grep -c` gave 2.
- **Scope:** the PostgreSQL constraints file.
- **Result: GREEN 59/59.** No test caught it, which is I1.
- **Restore:** `git checkout`, marker 0, clean.

**Direct trigger probe:** a throwaway database `rev267_0_probe_<hex>` was created and then dropped. The results are listed under Strengths. The dev database `ai_slide_generator` was not touched.

**Full unit suite at `4d685d03d`:** 6 failed, 6194 passed, 110 skipped. The six causes are identical to C39.

## Task quality: Approved

The DDL and trigger are correct and fit every consumer. I1 is a test-completeness gap in a correct trigger. It is cheap to close, and it should be closed before the whole-branch review, or at the latest in Task 4's first commit touching this file. M1–M3 are carry-forward and product decisions for the controller.

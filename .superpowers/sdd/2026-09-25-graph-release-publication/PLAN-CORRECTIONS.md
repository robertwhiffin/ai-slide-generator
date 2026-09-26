# PLAN-CORRECTIONS.md — this file overrides docs/superpowers/plans/2026-09-25-graph-release-publication.md wherever they differ.

- **Source:** `plan-review-1.md` (APPROVE WITH CORRECTIONS; 2 Critical, 12 Important, 14 Minor), and the controller rulings Q1, Q3, Q5 and Q6 in `progress.md`.
- **Plan at:** `d04b07aa5` on `plan/publish-release-269`. **Code base:** `c040dbde0`. `git diff --stat c040dbde0 HEAD -- src tests frontend packages` is empty.
- **Authority:** the plan file stays unchanged. Where they differ, this file wins. Attach it to every implementer and reviewer brief, as plan line 15 requires. The plan's Task 0 Step 2 prescribes a different first line for this file; the first line above supersedes it.
- **Numbering:** Correction 1–2 = C1–C2, 3–14 = I1–I12, 15–28 = M1–M14. Each correction states the plan line it overrides, its evidence, the instruction, any sabotage target, the phase it binds, and its cost if wrong.
- **Phases:** **Phase A** = in force before Task 1 dispatches. **Phase B** = in force before Task 4 dispatches, i.e. at Task 0 Step 4. When a correction has parts in both phases, it says which part is which.

## Probes run for this file (read-only, throwaway databases)

Scripts are in `/tmp/corr269/`. The interpreter was `/Users/robert.whiffin/.pyenv/shims/python` with `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr`.

**`probe_sqlite.py`** (in-memory SQLite, followed by `bootstrap_v1`):
- `GraphRelease.effective_from` loads as `datetime(2026, 9, 25, 14, 53, 6)` with `tzinfo None`.
- `_database_timestamp` returns the same second with `tzinfo=timezone.utc`.
- `ts <= effective_from` raises `TypeError: can't compare offset-naive and offset-aware datetimes`. This confirms I1.

**`probe_pg.py`:**
- It created `tellr_corr269_probe_<hex>` on `postgresql+psycopg2://localhost:5432/postgres`, ran `create_all` plus `_run_migrations`, then `bootstrap_v1`. It dropped the database in `finally`, and a `pg_database` check confirmed the drop (`dropped: True`). It never touched `ai_slide_generator`.
- **A (confirms C2):**
  - Setup: an `after_cursor_execute` listener on the `boot` thread fired after `_validate_current_graph`'s release read (`… ORDER BY graph_release.id`). It then committed a complete simulated publication on another connection: close v1, insert v2 and seven mappings, rebase the draft.
  - Result: `bootstrap_v1` raised `GraphConfigurationIntegrityError('release mapping rows do not belong to the complete release history')`. In production, `run.py:66-69` turns that into `SystemExit(1)`.
  - A plain `bootstrap_v1` run afterwards returned `BootstrapResult(created=False, release_id=2, version_number=2)`, so the persisted state itself is valid.
- **D:** while a session held `_lock_current_parents(exclusive=False)`, a second connection's `SELECT … FROM graph_release WHERE effective_to IS NULL FOR UPDATE NOWAIT` raised `LockNotAvailable`. So a share-locked bootstrap does exclude a publisher.
- **B (rules out REPEATABLE READ for C2):**
  - Setup: two REPEATABLE READ connections. A took `pg_advisory_xact_lock`. B then called the same advisory lock and blocked. A inserted a row and committed.
  - Result: B's `count(*)` returned **0**. B's snapshot was taken when its advisory-lock statement started, before it blocked.
- **C (confirms I12):**
  - `CREATE TRIGGER … FOR EACH ROW WHEN (EXISTS (SELECT …))` was rejected with `FeatureNotSupported: cannot use subquery in trigger WHEN condition`.
  - The alternative worked: a plpgsql function that checks `EXISTS (…)` in its body, with `WHEN (OLD.verdict IS DISTINCT FROM NEW.verdict)`. It rejected the linked-row update with `CheckViolation` and allowed the unlinked-row update.

---

## Critical

### Correction 1 (C1) — a changed role with no active required case is a readiness gap (Q5)

**Overrides:**
- plan lines 111–116: `PublicationNotReady.locked_gaps: tuple[tuple[AgentKey, int], ...]`
- line 193: the wire `gaps: [{agent_key, test_case_id}]`
- lines 721–752: the gate code
- line 755: "default: … treat absence as `GraphConfigurationIntegrityError`"
- line 385: the Task 1 fixture `locked_gaps=(("architect", 1),)`

**Evidence:**
- In the plan's gate, `gaps` is derived only from `cases` (lines 747–748). A changed key with zero active required cases adds no gap, so the gate returns `()`, and `_commit_locked_publication` publishes that role with no evidence.
- Ruling Q5 (`progress.md`): this situation is a readiness gap and publication is refused with an ordered issue. It is **not** an integrity error.
- It is reachable at runtime. `_validate_current_graph` enforces required-case coverage only at boot (`src/services/graph_configuration_bootstrap.py:187-198`, re-verified), and #267's case writers can deactivate a case.

**Instruction:**
1. **Gap type.** Task 1 defines it in `graph_configuration_publication.py` (Phase A, so the stable interface is final before anything consumes it):
   ```python
   PublicationGapCode = Literal["no_required_case", "no_eligible_approval"]

   @dataclass(frozen=True)
   class PublicationGap:
       agent_key: AgentKey
       test_case_id: int | None       # None iff code == "no_required_case"
       code: PublicationGapCode

   @dataclass(frozen=True)
   class PublicationNotReady:
       locked_gaps: tuple[PublicationGap, ...]   # non-empty; ordered as below
       readiness: object
   ```
   - `__post_init__` raises `ValueError` for any of: an empty `locked_gaps`; a `no_required_case` gap with a non-None `test_case_id`; a `no_eligible_approval` gap with a None `test_case_id`.
   - **Order:** by `GRAPH_V1_AGENT_KEYS` index, then `test_case_id`. A key has either one `no_required_case` gap or ≥1 case gaps, never both.
   - Export `PublicationGap` and `PublicationGapCode` in `__all__`.
   - Task 1's `test_gate_not_ready_writes_nothing` uses `PublicationNotReady(locked_gaps=(PublicationGap("architect", 1, "no_eligible_approval"),), readiness="sentinel")`.
2. **Gate (Task 4, `ApprovalEvidenceGate.lock_and_verify`).** After the L2 case query:
   - Compute `covered = {c.agent_key for c in cases}`.
   - Emit `PublicationGap(k, None, "no_required_case")` for every `k in changed_agent_keys` with `k not in covered`.
   - Emit `PublicationGap(c.agent_key, c.id, "no_eligible_approval")` for every case without a chosen run.
   - Sort by the order above. If there are any gaps, return `PublicationNotReady(gaps, self._readiness(session))`.
   - Keep the `if cases else []` guard on the run query, so zero cases means zero run locks.
   - Never link optional or inactive cases, and link only the newest eligible approval per required case (Q5).
3. **Wire (Task 5).** `409 {"code": "publication_not_ready", "gaps": [{"agent_key": AgentKey, "test_case_id": int | null, "code": "no_required_case" | "no_eligible_approval"}], "readiness": <#268 response>}`. The keys are exactly these three, in gap order.
4. **Frontend (Tasks 6–7).**
   - The strict parser accepts exactly those three keys and both codes, and rejects any other code, or a `test_case_id` whose null/non-null state disagrees with the code.
   - The not-ready panel renders `no_required_case` as `<Role label>: no active required test case`.
   - Add one Vitest parser case and one page case for it, and one Playwright mock in Task 7(b).
5. **Preview (Task 5).** A changed role with no active required case makes `publishable` false (see Correction 22).
6. **New RED tests (Task 4).**
   - **PostgreSQL** `test_changed_role_without_active_required_case_is_not_ready`:
     - Setup: save architect. Deactivate architect's only required case, using #267's case writer if the Task 0-B probe shows it allows this; otherwise use an ORM update, and record that choice here.
     - Assert: `publish_draft` returns exactly `PublicationNotReady(locked_gaps=(PublicationGap("architect", None, "no_required_case"),), readiness=<#268 result>)`.
     - Assert: the revision, release, mapping, `graph_release_test_run`, draft-parent and draft-agent tuples are identical before and after, and a fresh `lock_active_graph_release` returns v1.
   - **SQLite unit:** architect has no required case and builder has only a stale-hash approval. Assert that `locked_gaps == (PublicationGap("architect", None, "no_required_case"), PublicationGap("builder", <case id>, "no_eligible_approval"))`, in that order.

**Sabotage (controller, Task 4, replacing plan line 758's controller target; see Correction 11):** delete the `no_required_case` emission. Predicted RED: `test_changed_role_without_active_required_case_is_not_ready`, which returns `PublishedRelease(version_number=2)` with `evidence == ()` instead of `PublicationNotReady`.

**Binds:** Phase A for the type and wire shape (Task 1 produces it). Phase B for the gate, tests and sabotage (blocking).

**Carry-forward (not solved here):** a deactivated last required case also makes the **next boot** raise at `bootstrap.py:196-198` and exit. Record in #267's corrections that its case writer must refuse to deactivate a role's last active required case, or rule otherwise.

**Cost if wrong:** a role ships to every new conversation with no approval evidence, which violates the publication gate.

### Correction 2 (C2) — boot validation must read under one consistent parent lock (new Task 2 Steps 4a–4d)

**Overrides:** plan line 51 ("an un-rebased draft bricks the next boot" is the only boot risk named) and Task 2 (which has no bootstrap step).

**Evidence:**
- `packages/databricks-tellr-app/databricks_tellr_app/run.py:54-69` runs `bootstrap_graph_configuration` on every start and turns any exception into `SystemExit(1)`.
- `_validate_current_graph` (`graph_configuration_bootstrap.py:121-199`) runs one statement per read under READ COMMITTED, with no locks: releases at `:122`, mappings at `:129`, `session.get` revisions in the loop, drafts at `:159`, draft agents at `:170`, and cases at `:187`.
- `_take_bootstrap_lock` (`:76-82`) takes only an advisory lock, which publication never takes.
- Probe A reproduced the race: a publication committed between `:122` and `:129` makes bootstrap raise `"release mapping rows do not belong to the complete release history"`.
- #269 is the first ticket that can commit a publication, so the race is new with this plan.

**Choice: take share locks in the global lock order, not REPEATABLE READ.**

Justification:
1. Probe B shows that a REPEATABLE READ snapshot is fixed when the advisory-lock statement *starts*. So a second bootstrap queued on the advisory lock during first-ever startup would read `count(GraphRelease) == 0` after the first bootstrap committed v1. It would then try to insert a second v1. That breaks `tests/integration/test_graph_configuration_bootstrap_postgres.py:105` (`test_two_bootstraps_observe_second_backend_waiting_on_advisory_lock`, which expects `second.created is False`).
2. Setting the isolation level per transaction would also need a connection-level execution option, which the session-factory-based bootstrap does not own.
3. With share locks, `_lock_current_parents(exclusive=False)` holds `FOR SHARE` on the active release and the draft. Nothing else can then change the validated rows:
   - Closed releases and mappings are immutable under the guards (`database.py:935-1081`).
   - New releases and mappings are written only by publication, which needs `FOR UPDATE` on both parents (probe D).
   - Draft agents are written only by the draft writer, which takes L0 `FOR UPDATE` first.
4. The locks follow the global order: advisory lock (bootstrap only, never taken by any other locker) → L0 release → L0 draft. So no cycle is possible.

**Instruction (Phase A; new steps in Task 2 after the retry's Step 4 GREEN, because a bootstrap queued behind a committing publication needs the Task 2 handoff retry):**
- **4a. RED tests** in `tests/integration/test_graph_release_publication_postgres.py`. Capture each backend's PID by overriding `_take_bootstrap_lock` / `_lock_current_parents` to run `SELECT pg_backend_pid()` first (pattern: `test_graph_configuration_bootstrap_postgres.py:114-116`; see Correction 5).
  - **`test_boot_validation_queued_behind_publication_sees_new_release`:**
    - Pause the publisher (`publish_draft`) on the `after_cursor_execute` of its mapping read-back statement (after the mapping flush).
    - Start `GraphConfiguration().bootstrap_v1(factory)` on thread `boot`, and assert `_await_blocked_by(waiter=boot_pid, blocker=publisher_pid)`.
    - Release the publisher. Assert that the publisher returns `PublishedRelease` v2 and that the bootstrap returns exactly `BootstrapResult(False, v2.id, 2)`.
  - **`test_publication_during_boot_validation_waits_for_boot`:**
    - An `after_cursor_execute` listener on the `boot` thread matches the release list read: normalized text contains `FROM GRAPH_RELEASE ORDER BY GRAPH_RELEASE.ID` and no `FOR`. On that statement it starts `publish_draft` on thread `publisher`.
    - It waits (bounded) until `_await_blocked_by(waiter=publisher_pid, blocker=boot_pid)` holds, then returns.
    - Assert that the bootstrap returns exactly `BootstrapResult(False, v1.id, 1)`, then the publisher returns v2 with `previous_release_id == v1.id`. Assert the listener fired exactly once.
- **4b. RED run.** Record the causes:
  - The first test fails at `_await_blocked_by`, which is False because bootstrap reads committed v1 without blocking.
  - The second test fails with `GraphConfigurationIntegrityError("release mapping rows do not belong to the complete release history")`, as in probe A.
- **4c. Implement.** The first statement of `_validate_current_graph` becomes `release_row, draft_row = self._lock_current_parents(session, exclusive=False)`.
  - Keep every existing check and message. The lock's own diagnoses for zero or several active releases, a missing draft, and a base mismatch use the same strings (`graph_configuration_workbench.py:211-237` against `bootstrap.py:123-168`, re-verified).
  - Bootstrap reaches `_lock_current_parents` only through the `GraphConfiguration` facade (`graph_configuration.py:44-54`; every bootstrap test instantiates `GraphConfiguration()`). Add a one-line docstring note that `_GraphConfigurationBootstrap` depends on `_GraphConfigurationWorkbench` in the facade MRO.
  - On SQLite, `FOR SHARE` is not rendered, so SQLite behaviour is unchanged.
- **4d. GREEN.**
  - Run the two new tests.
  - Run `test_graph_configuration_bootstrap_postgres.py`, including the two-bootstrap test at `:105`, whose advisory-lock ordering is unchanged.
  - Run the SQLite corrupt-state parametrization in `tests/unit/test_graph_configuration_bootstrap.py` (`:633-695`), which must stay GREEN with unchanged exception types.

**Sabotage (controller, an extra sabotage within Task 2):** delete the new lock line. Predicted RED:
- `test_publication_during_boot_validation_waits_for_boot` fails with the exact integrity error above;
- `test_boot_validation_queued_behind_publication_sees_new_release` fails at `_await_blocked_by`.

Restore, prove the marker is gone, then GREEN.

**Binds:** Phase A (blocking).

**Cost if wrong:**
- A replica that restarts while another replica publishes exits with `SystemExit(1)`.
- The share lock means a conversation creation (release `FOR UPDATE`) waits for the length of boot validation. That is accepted and bounded: the cost is linear in release history, and there are seven hash checks per release.

---

## Important

### Correction 3 (I1) — normalise timezone awareness at the core's comparison point

**Overrides:** plan lines 395–402 (the helper normalises only the transaction timestamp) and lines 520–523 (the comparison `timestamp <= release_row.effective_from`).

**Evidence:** `probe_sqlite.py`, above. `GraphRelease.effective_from` is `DateTime(timezone=True)` (`src/database/models/graph_configuration.py:198`), and SQLite loads it naive. PostgreSQL loads it aware.

**Instruction (Task 1):**
- Add `as_utc_aware(value: datetime) -> datetime` to `graph_configuration_content.py`. It returns `value.replace(tzinfo=timezone.utc)` when `value.tzinfo is None`, and otherwise returns `value` unchanged. It never converts an aware value to another timezone.
- The core compares `timestamp <= as_utc_aware(release_row.effective_from)`, with `timestamp` from `database_transaction_timestamp`. This is the only comparison point.
- **Unit tests:**
  - `as_utc_aware(naive)` has `utcoffset() == timedelta(0)` and the same wall-clock fields;
  - `as_utc_aware(aware)` is `is`-identical to its input;
  - the SQLite happy path (`test_publish_two_changed_roles_creates_v2_with_exact_seven_mappings`) reaches the guard. Spy on `as_utc_aware` in the publication module and assert that it was called once, with a naive argument, and returned an aware value.
- SQLite interval assertions must compare values **read back in a fresh session** (all naive), or compare both sides through `as_utc_aware`. Naive-vs-aware `==` is silently `False` in Python.

**Sabotage (reviewer, a Task 1 addition):** replace the call with a bare `release_row.effective_from`. Predicted RED: every SQLite test that reaches the core fails with `TypeError: can't compare offset-naive and offset-aware datetimes`.

**Binds:** Phase A (blocking).

**Cost if wrong:** every SQLite publish (Task 1 unit tests, Task 5 route tests) raises `TypeError`, which is a 500.

### Correction 4 (I2) — the same-second test uses an injected transaction timestamp

**Overrides:** plan line 387 (`test_same_second_timestamp_raises_before_write`, "without backdating").

**Evidence:**
- The test passes only if bootstrap, two saves and the publish all fall within one wall-clock second of SQLite `CURRENT_TIMESTAMP`, which has one-second resolution (plan line 72).
- If the run crosses a second boundary, the test goes GREEN by luck, or RED under an unrelated sabotage.

**Instruction (Task 1):**
- `graph_configuration_publication.py` imports the helper by name: `from src.services.graph_configuration_content import database_transaction_timestamp`.
- The core calls that module-level name.
- The test backdates v1 as the other unit tests do.
- It reads `v1_from = as_utc_aware(<v1.effective_from from a fresh session>)` and monkeypatches `src.services.graph_configuration_publication.database_transaction_timestamp` to `lambda session: v1_from + offset`, parametrized with offset `timedelta(0)` and `timedelta(seconds=-1)`.
- Assert: `pytest.raises(GraphConfigurationIntegrityError, match="^publication timestamp does not follow the active release interval$")`.
- Assert: every artefact tuple is unchanged, and the gate was called at most once (the guard runs after the gate).
- Assert: the patched callable was invoked exactly once, which makes the test non-vacuous.

**Sabotage:** n/a (the finding broke no sabotage). If one is wanted, flip `<=` to `<`. The `timedelta(0)` case should then RED with an `IntegrityError` from `ck_graph_release_interval` at flush, instead of the named error.

**Binds:** Phase A (blocking).

**Cost if wrong:** a flaky gate test that proves nothing about the guard.

### Correction 5 (I3) — capture waiter PIDs with `pg_backend_pid()` before the blocking statement

**Overrides:** plan line 625 ("records `conn.connection.driver_connection.get_backend_pid()` for each thread" from an `after_cursor_execute` listener).

**Evidence:**
- Each waiter's first statement is the L0 statement: `save_editable_model_draft`, `read_workbench` and `publish_draft` all enter `_lock_current_parents` right after `session.begin()`.
- `after_cursor_execute` fires only after that statement unblocks, so no PID exists while the waiter is waiting.
- The correct existing patterns (re-verified):
  - `tests/integration/test_agent_definition_workbench_postgres.py:170-176`: override `_lock_current_parents` to run `session.scalar(text("SELECT pg_backend_pid()"))` before `super()`;
  - `tests/integration/test_graph_configuration_bootstrap_postgres.py:114-116`: the same idea on `_take_bootstrap_lock`;
  - `tests/integration/test_mixed_release_creation_postgres.py:245-253`: a `before_cursor_execute` listener recording `_backend_pid(conn)` for creators. The review cited `:222-231`; the lines above are the actual ones.

**Instruction (Tasks 2–4, and Correction 2's tests):**
- **Waiters that enter through `_lock_current_parents`** (draft saver, workbench reader, loser publisher, bootstrap, #268 readiness): a test subclass overrides `_lock_current_parents` to run `SELECT pg_backend_pid()` on the session's connection, store it under the thread name, set an "attempted" event, then call `super()`.
- **Bootstrap:** the `_take_bootstrap_lock` override.
- **Creators (Task 3)**, whose blocking statement is inside `lock_active_graph_release`: the existing `before_cursor_execute` recipe at `test_mixed_release_creation_postgres.py:245-253`. It is the fixture pattern already in use, and it reports the same backend PID without a round trip.
- **Cleanup and verdict waiters (Task 4):** override or wrap the #268 entry point to run `SELECT pg_backend_pid()` before its first locking statement (record the exact method at Task 0-B).
- Every `_await_blocked_by` call must be preceded by a wait on that thread's "PID recorded" event.
- `after_cursor_execute` is used **only** to pause the blocker after its lock statement.

**Sabotage:** n/a.

**Binds:** Phase A (blocking; Tasks 2–3). It carries into Phase B for Task 4.

**Cost if wrong:** every ordering test fails with no PID, or waits on a stale PID, which is a harness bug mistaken for a lock result.

### Correction 6 (I4) — re-aim Task 3's controller sabotage

**Overrides:** plan line 675 (the controller's predicted RED is "creation-first") and the pause matcher implied by lines 625 and 669.

**Evidence:**
- Under the sabotage (publication locks only `graph_draft` and reads the release unlocked), the creation-first test stays GREEN. The publisher still blocks on its `UPDATE graph_release SET effective_to` flush (plan line 537), because the creator holds the release `FOR UPDATE`.
- The publication-first test *does* go RED: the creator is never blocked while the publisher is paused after its draft-only lock.
- A pause matcher that requires `GRAPH_RELEASE` **and** `GRAPH_DRAFT` would never fire under this sabotage. The test would then fail on a pause timeout, which is the wrong reason.

**Instruction (Task 3):**
- **Publisher pause.** In both Task 3 tests, the publisher pause fires after the publisher thread's **first** statement containing `FOR UPDATE`, with no table filter. The test records that statement's normalized text.
- **Publication-first assertion order:**
  1. `assert _await_blocked_by(waiter=creator_pid, blocker=publisher_pid)`;
  2. then assert that the recorded statement contains `GRAPH_RELEASE` and `GRAPH_DRAFT`;
  3. then the pin assertions.
- **Creation-first strengthening.** While the publisher is observed blocked, read `pg_stat_activity.query` for `publisher_pid` and assert that its upper-cased, whitespace-normalized text contains `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT`, i.e. the publisher is blocked on L0 and not on a later write.

**New sabotage target (controller):** the same mutation (draft-only lock plus an unlocked release read). Predicted RED:
- **Primary:** `test_publication_first_each_creator_pins_exact_new_release`, every `CREATORS` parametrization, at `_await_blocked_by(...)` (False: the creator pins v1 and commits).
- **Secondary:** `test_creation_first_publisher_waits_and_creator_keeps_v1`, at the new `pg_stat_activity.query` assertion (the observed query is the `UPDATE graph_release …`).

**Binds:** Phase A (blocking).

**Cost if wrong:** the one sabotage meant to prove that publication linearizes at the release row passes, or fails for an unrelated reason.

### Correction 7 (I5) — the "Review & Publish" exemption moves into Task 6

**Overrides:** plan lines 838 and 877 (Task 6 adds the link and runs the workbench Vitest suite) and lines 887–888 (Task 7 adds the exemption and the length updates).

**Evidence (re-verified):**
- `FORBIDDEN_ACTION_STEMS` includes `review\s*&\s*publish|publish` (`frontend/tests/fixtures/forbiddenActionNames.ts:17-18`), and `ALLOWED_ACTION_NAMES` has three entries (`:27-31`).
- `expectNoForbiddenActionNames` sweeps every `link` (`AgentDefinitionWorkbench.test.tsx:72-88`).
- Lengths are asserted in two places: `toHaveLength(3)` at `AgentDefinitionWorkbench.test.tsx:243` and at `frontend/tests/e2e/agent-definition-workbench.spec.ts:1462`.
- So Task 6 Step 4 goes RED until Task 7 lands.

**Instruction:**
- **Task 6** also modifies:
  - `frontend/tests/fixtures/forbiddenActionNames.ts`: append exactly `'Review & Publish'`, with capital P, so it matches the header anchor text;
  - `AgentDefinitionWorkbench.test.tsx:243` and `agent-definition-workbench.spec.ts:1462`: change to `toHaveLength(4)`.
- **Constraint:** `forbidsActionName` removes allowed names with a case-sensitive `split` (`:34-39`). So `forbidsActionName('Review & publish')` (lowercase p, asserted true at `AgentDefinitionWorkbench.test.tsx:234`) must stay true.
  - Do not change the stem, and do not add a case-insensitive exemption.
  - Add one assertion: `forbidsActionName('Review & Publish now')` stays false only for the exact name; `'Review & Publish, then rollback'` is true.
- **Task 7** keeps only the Playwright sweep check (f) and the new spec, and no longer edits `forbiddenActionNames.ts`.

**Sabotage:** Task 7's controller sabotage (label → `Publish draft`) is unchanged. The GREEN gate for Task 6 Step 4 now holds.

**Binds:** Phase B (Task 6 runs in Phase B). The review grouped I5 with the Phase A corrections, but no Phase A task touches the frontend. It is recorded now, and it is blocking for Task 6.

**Cost if wrong:** Task 6 cannot reach GREEN, or an implementer loosens the forbidden stem to get there.

### Correction 8 (I6) — failure injection at every write seam, each proving full rollback

**Overrides:** plan line 571 (a single injection point, at `_link_evidence`) and Task 3 (which pauses only after L0).

**Evidence:**
- The only injection is after the mappings are written. Task 4 replaces `_link_evidence`, and nothing then proves that `graph_release_test_run` rows roll back.
- These points are never exercised: interval close → insert; evidence → draft rebase; and a commit-time failure.
- AC5 ("no conversation observes a partial release") is never tested while writes are flushed.

**Instruction:**
1. **Task 1** replaces `test_failure_after_mappings_rolls_back_every_row` with `test_injected_failure_rolls_back_every_row`, parametrized over stage.
   - The injection is an `after_cursor_execute` listener, restricted to the publisher thread, that raises `RuntimeError(f"injected at {stage}")` after the first statement matching the stage's matcher (normalized upper-case text):

     | stage | statement matcher |
     |---|---|
     | `interval_closed` | `UPDATE GRAPH_RELEASE SET EFFECTIVE_TO` |
     | `mappings_read_back` | `SELECT GRAPH_RELEASE_AGENT.AGENT_KEY` |
     | `draft_rebased` | `UPDATE GRAPH_DRAFT SET` |
     | `commit` | no listener: a test-only `CREATE CONSTRAINT TRIGGER test_fail_publication_at_commit AFTER INSERT ON graph_release DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION …` whose body raises `'injected commit failure'`, installed in the throwaway database for this parametrization only |

   - For each stage, assert all of the following:
     - `pytest.raises` with the exact injected error (`IntegrityError` matching `injected commit failure` for `commit`);
     - the listener or trigger fired exactly once;
     - the revision, release (id, version, `effective_from`, `effective_to`), mapping, draft-parent and draft-agent tuples equal the "before" capture exactly;
     - a fresh `lock_active_graph_release` returns v1;
     - a subsequent un-injected `publish_draft` with the same lock returns version **2** (no gap in the version sequence).
   - No production hook is added.
2. **Task 4** adds the stage `evidence_linked` (matcher `INSERT INTO GRAPH_RELEASE_TEST_RUN`). For every stage, it also asserts that `SELECT count(*) FROM graph_release_test_run` is 0 and that the evidence runs' verdict columns are unchanged.
3. **Task 3** adds `test_creator_behind_fully_flushed_publication_never_sees_partial_release`, parametrized over `CREATORS` × outcome ∈ {`rollback`, `commit`}.
   - Pause the publisher after its `UPDATE GRAPH_DRAFT SET` statement (all writes flushed), and assert `_await_blocked_by(waiter=creator_pid, blocker=publisher_pid)`.
   - For `rollback`, the publisher then raises the injected error: the creator pins exactly v1, and v1 is still active.
   - For `commit`, the creator pins exactly v2 after scanning `[1, 1]`.

**Sabotage (reviewer, Task 1, replacing plan line 578's reviewer target, which moves to Task 9's final pool):** in `publish_draft`, replace `with session.begin():` with an explicit `session.begin()` / `try: … finally: session.commit()`, so the transaction commits on the exception path. Predicted RED:
- `[mappings_read_back]` and `[draft_rebased]` fail on the after == before assertion (v2 is committed);
- `[interval_closed]` fails with `IntegrityError` from `trg_graph_release_exactly_one_active` instead of `RuntimeError`;
- `[commit]` stays GREEN. It fails at COMMIT either way; record why.

**Binds:** Phase A for parts 1 and 3 (blocking). Phase B for part 2 (blocking).

**Cost if wrong:** a partial-release or orphan-evidence defect ships unproved, which violates AC5.

### Correction 9 (I7) — Task 2's reviewer sabotage predicts `NothingToPublish`; add a test that produces a v3

**Overrides:** plan line 652 ("RED on two-publisher and retry tests (a v3 appears)").

**Evidence:** with the stale branch deleted, the loser (after the retry) or the sequential retry sees a draft rebased onto v2 with every hash equal. `changed` is empty, so the result is `NothingToPublish`, not v3.

**Instruction (Task 2):** add `test_stale_publisher_after_intervening_save_is_conflict_not_v3`, a sequential test:
1. Publish v2 at lock L (the lock becomes L+1).
2. Save architect again (the lock becomes L+2).
3. Publish with `expected_lock_version=L`.
4. Assert exactly `PublicationConflict(expected_lock_version=L, current_lock_version=L+2, active_release_id=v2.id, active_version_number=2, draft=<current>)`, exactly two releases, and no new revision.

**New sabotage target (reviewer):** the same mutation (delete the `expected_lock_version != draft_row.lock_version` branch). Predicted RED:
- **Primary:** the new test, whose observed outcome is `PublishedRelease(version_number=3)`. A stale request published content it never previewed.
- **Secondary (record as expected):** `test_two_publishers_one_winner_one_exact_stale_conflict` (both parametrizations) and `test_sequential_retry_after_success_is_stale`. Both fail with an observed `NothingToPublish`.

**Binds:** Phase A (blocking).

**Cost if wrong:** a mismatch between observed and predicted causes, logged as a harness bug, or accepted without the real stale-publish seam ever being proved.

### Correction 10 (I8) — apply rulings Q1, Q3, Q5 and Q6 throughout

**Overrides:** plan lines 93, 189, 193, 687, 703, 755, 797, 812, 893(d), 910 and 941–946.

**Evidence:** `progress.md` records the rulings. The plan predates them.

**Instruction:**
- **Q1** (#269 owns the publication transaction, evidence links and the Review & Publish page; #268 owns readiness, verdicts and cleanup only):
  - Delete Q1 from the open questions (line 941) and treat line 93 as ruled.
  - At Task 0 Step 4, finding any #268 publication code, `publish_draft`, or Review & Publish page is a **stop** condition, not a record. The fix belongs in #268's own PLAN-CORRECTIONS.
- **Q3** (a verdict on a linked run is immutable; the trigger is mandatory):
  - The Task 4 file entry at line 687 becomes unconditional: "Modify `src/core/database.py` …".
  - The DDL follows Correction 14.
  - `test_publication_first_then_verdict_change` (line 703) expects the verdict writer to fail with the trigger's `IntegrityError` (SQLSTATE `23514`), the run to stay `approved`, and the evidence link to stay in place.
- **Q5:** Correction 1. Link only the newest eligible approval per required case, never optional cases.
- **Q6** (publish returns 200; `409 nothing_to_publish` is kept; notes are capped at 2000 characters):
  - **Status 200** in: the wire table (line 189); the route decorator (line 812: `@router.post("/releases", response_model=PublishReleaseSuccessResponse)`, with no `status_code`, matching `agent_definitions.py:380`, `:456` and `:496`); the route tests (line 797: "exact 200 body"); the Playwright mocks and scenario (d) (line 893); and the Task 8 assertion (line 910).
  - **Note length:** `_validate_publication_request` appends `DraftValidationIssue("release_note", "too_long", "Release note must be at most 2000 characters.")` when `len(release_note) > 2000`, where `len` counts Python `str` code points. The blank check applies first, so the two are mutually exclusive.
  - The Pydantic `PublishReleaseRequest` carries **no** `max_length`. The service is the one authority, so the route emits the same triple: 422 `{"code":"invalid_publication","errors":[{"field":"release_note","code":"too_long","message":"Release note must be at most 2000 characters."}]}`.
  - **Tests:** Task 1 (unit) checks that 2000 characters are accepted and stored verbatim, and that 2001 are rejected before any lock, using the lock spy. Task 5 (route) checks the exact 422 body for 2001 characters. Task 6 checks that the reducer treats `note.length > 2000` as not publishable and renders the server's 422 beside the textarea.

**Binds:** Phase A for the Q6 note cap (Task 1) and the recording of Q1. Phase B for everything else (blocking).

**Cost if wrong:** status-code and length drift at the wire; published evidence that can be edited retroactively; or duplicated publication code across #268 and #269.

### Correction 11 (I9) — re-aim Task 4's controller sabotage

**Overrides:** plan line 758 (controller: drop the `candidate_hash` term, RED on the stale-hash test).

**Evidence:** the re-verify loop (plan lines 738–742) compares `run.candidate_hash` with `hashes[case.agent_key]` and skips the stale run. So dropping the query term leaves `test_stale_hash_approval_is_not_ready_and_writes_nothing` GREEN.

**New sabotage target (controller):** delete the `no_required_case` gap emission (Correction 1). Predicted RED: `test_changed_role_without_active_required_case_is_not_ready`, with an observed `PublishedRelease(version_number=2, evidence=())`.
- The reviewer's sabotage (remove `.with_for_update()` from the run query; RED on `test_verdict_rejection_first_then_publication`, where the publisher is not observed waiting) is unchanged.
- If the whole-branch review wants the hash seam proved, the sabotage must remove the hash term from **both** the query and the re-verify. Predicted RED: the stale-hash test, which then links the stale run and publishes.

**Binds:** Phase B (blocking).

**Cost if wrong:** a sabotage marked RED that never went RED, so the gate's zero-case seam ships unproved.

### Correction 12 (I10) — re-aim Task 8's reviewer sabotage

**Overrides:** plan line 912 (reviewer: the gate chooses the oldest eligible run, RED on exact evidence IDs) and line 910 (the flow).

**Evidence:** the flow approves exactly one run per required case, so "oldest" and "newest" select the same run and the sabotage cannot go RED.

**Instruction (Task 8 flow additions, in this order):**
1. After running and approving builder's required case once, run it **again** through #267's route and approve the second run through #268's route.
2. Before approving architect's run, POST with the current lock. Assert the exact `409 publication_not_ready` with `gaps == [{"agent_key":"architect","test_case_id":<id>,"code":"no_eligible_approval"}]`, and a `readiness` body from #268's real readiness that marks architect's case `Awaiting review`. This proves the route's production readiness binding end-to-end, which Task 5 fakes.
3. The success assertion becomes: evidence IDs == {architect's approved run, **builder's second** approved run}, exactly.

**New sabotage target (reviewer):** in `ApprovalEvidenceGate.lock_and_verify`, flip the newest selection (`>` → `<` at plan line 744). Predicted RED: the Task 8 exact-evidence assertion, which observes builder's first run ID. This does not collide with Task 4's pair (Corrections 11 and 1), because Task 4 no longer uses the newest-selection seam.

**Binds:** Phase B (blocking).

**Cost if wrong:** the acceptance flow cannot detect wrong evidence selection or a broken readiness binding.

### Correction 13 (I11) — #267's run executor must hold no lock across a model call (Phase B blocking)

**Overrides:**
- plan line 208 ("#267 must not hold a transaction open across a model call (assumed; re-probe)");
- line 212 (the deadlock-freedom argument);
- line 200 (L0 release → L0 draft presented as a controlled order).

**Evidence:**
- The #267 draft, `docs/superpowers/plans/2026-09-23-agent-test-case-runs.md:806-811` (read only, re-verified), has these steps:
  - step 1 "Lock the singleton draft … (same lock pattern as draft write)";
  - step 3 `runtime.run_candidate(...)`;
  - step 6 "Insert an `AgentTestRun` row in the same transaction".
- So it holds the lock across the model call. There are two ways this goes wrong:
  - **(a)** If #267 reuses `_lock_current_parents(exclusive=True)`, the release row is `FOR UPDATE` for the whole model call, which blocks every conversation creation and publication.
  - **(b)** If #267 takes only the draft lock, its insert takes FK `KEY SHARE` on `graph_release` (through `compared_release_id`). That is draft → release, and the review's second probe showed it **deadlocks** with the publication's L0 statement (release → draft).
- The release → draft order inside one statement is PostgreSQL's rowmark order. The review confirmed it by probe, but no test pins it.

**Ruling (binding):**
- The #267 test-run executor (`execute_candidate_run`, `execute_baseline_rerun`) must **commit or release every lock before any model call**:
  1. Transaction 1: read the case, candidate and hash under the `read_workbench` share pattern, then commit.
  2. The model call runs with no open transaction.
  3. Transaction 2: re-lock through `_lock_current_parents` (release → draft), re-verify that the candidate hash and case version are unchanged, then insert the run.
- **Carry this ruling into #267's own PLAN-CORRECTIONS when #267 executes.** The #269 plan must not assume any other shape.

**Instruction:**
1. **Task 0 Step 4 re-probe (blocking).**
   - With #267's fake adapter paused inside `run_candidate`, assert that the executor's backend has `pg_stat_activity.state` ≠ `'idle in transaction'` and holds no `pg_locks` row on `graph_release`, `graph_draft` or `agent_test_run`.
   - Record the transaction-2 lock statement text.
   - If either check fails, stop and route the fix to #267.
2. **Task 1 addition (lands in Phase A; pins a confirmed fact):** `test_parent_lock_statement_takes_release_before_draft`.
   - Session X holds `graph_draft FOR SHARE`.
   - A publisher's L0 statement is observed blocked by X's PID.
   - A third session's `SELECT id FROM graph_release WHERE effective_to IS NULL FOR UPDATE SKIP LOCKED` returns zero rows, i.e. the waiting L0 statement already holds the release.
   - Release X; the publisher returns v2.
3. **Task 4 addition:** `test_test_run_insert_and_publication_serialize_without_deadlock`, run in both orders.
   - #267's real transaction 2 is paused after its lock statement; then the publisher, and the reverse.
   - Each waiter is observed blocked by the other's PID. Neither side raises `DeadlockDetected`.
   - In run-first order, the run records `compared_release_id == v1.id`. In publication-first order, the run's re-verify sees the rebased draft, and its outcome is exactly what #267's corrections specify.
4. Rewrite the lock-order table row "implicit" and the deadlock argument (line 212) to cite this ruling and these tests, instead of "assumed".

**Binds:** Phase B (blocking). Sub-item 2 is a Phase A addition to Task 1 and is not blocking on its own.

**Cost if wrong:** production deadlocks between test runs and publication, or tens-of-seconds stalls in every conversation creation during a test run.

### Correction 14 (I12) — the verdict-freeze trigger checks inside its function body, and is proved through the migration path

**Overrides:** plan line 755 (`CREATE TRIGGER … FOR EACH ROW WHEN (EXISTS …)`).

**Evidence:**
- Probe C: PostgreSQL rejects a subquery in a trigger `WHEN` with `FeatureNotSupported: cannot use subquery in trigger WHEN condition`.
- The guards run inside `_run_migrations` (`src/core/database.py:624`), which is called from `init_db` (`:414`) and by the `postgres_engine` fixture (`tests/integration/conftest.py:269-270`). An invalid DDL therefore aborts startup and every PostgreSQL fixture.

**Instruction (Task 4, inside `_install_graph_configuration_mutation_guards`):**
- **Function:** `qualified("reject_linked_agent_test_run_verdict_change")`, `RETURNS trigger LANGUAGE plpgsql`. The body is:
  ```sql
  IF EXISTS (SELECT 1 FROM <qualified graph_release_test_run> WHERE agent_test_run_id = OLD.id) THEN
    RAISE EXCEPTION 'agent test run % is linked to a release; its verdict is immutable', OLD.id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
  ```
  - Schema-qualify the table inside the body using the same `qualified()` helper (`database.py:953-954`). Search-path drift must not change the answer.
- **Trigger:** `trg_agent_test_run_linked_verdict_immutable`, preceded by the existing idempotent `DROP TRIGGER IF EXISTS … ON …` (pattern: `database.py:1047`, `:1058`, `:1070`). Define it as `BEFORE UPDATE OF <verdict columns> ON <qualified agent_test_run> FOR EACH ROW WHEN (<column comparisons only, e.g. OLD.verdict IS DISTINCT FROM NEW.verdict OR OLD.verdict_reviewer IS DISTINCT FROM NEW.verdict_reviewer OR …>) EXECUTE FUNCTION <function>`.
  - Take the verdict column list from the Task 0-B probe of #267's real `AgentTestRun`, not from plan line 755.
  - Use `CREATE OR REPLACE FUNCTION`, so re-running is idempotent.
- **PostgreSQL tests (migration-safe proof):**
  - Extend `test_postgres_mutation_guard_migration_is_idempotent_and_schema_objects_are_active` (`tests/integration/test_graph_configuration_constraints_postgres.py:324`, which already calls `_run_migrations` twice at `:327-328`). Assert that the new trigger exists exactly once in `pg_trigger` and is enabled after both runs.
  - In `test_graph_release_evidence_postgres.py`, run `_run_migrations(postgres_engine)` again on the fixture engine, then publish v2 linking run *b* (committed). A direct `UPDATE agent_test_run SET verdict='rejected' WHERE id=b` must raise `IntegrityError` with SQLSTATE `23514`, and the same update on an **unlinked** run must succeed.
  - `test_publication_first_then_verdict_change` uses #268's real `record_verdict` against the committed link (Correction 10).

**Sabotage (a Task 4 addition, run by the controller after Correction 11's):** drop the `IF EXISTS … RAISE` block from the function body, leaving `RETURN NEW`. Predicted RED: the direct-update test and `test_publication_first_then_verdict_change`, where the verdict changes to `rejected`.

**Binds:** Phase B (blocking).

**Cost if wrong:** the migration aborts every startup and every PostgreSQL fixture, or published evidence can be edited.

---

## Minor

### Correction 15 (M1) — `DraftFieldErrorResponse` citation

**Overrides:** plan lines 62 and 774 (`schemas/agent_definitions.py:301–319`).

**Evidence (re-verified):** `ActiveReleaseResponse` `:301` and `DraftMetadataResponse` `:313` are correct. `DraftFieldErrorResponse` is at `:403`.

**Instruction:** cite `:403` for `DraftFieldErrorResponse`, and let Task 5 import it from there.

**Sabotage:** n/a. **Binds:** Phase B (Task 5), non-blocking.

**Cost if wrong:** a mis-cited import during Task 5 review.

### Correction 16 (M2) — `_validate_complete_snapshot` citation

**Overrides:** plan line 245 (`persisted_graph_release.py:166–204`).

**Evidence (re-verified):** `def _validate_complete_snapshot` is at `src/services/persisted_graph_release.py:167`.

**Instruction:** cite `:167`.

**Sabotage:** n/a. **Binds:** Phase A (the fact table), non-blocking.

**Cost if wrong:** negligible.

### Correction 17 (M3) — `_validate_publication_request` is specified exactly

**Overrides:** plan line 567.

**Evidence (re-verified):** `_validate_common(actor, lock_version, agent_key)` (`graph_configuration_draft.py:547-582`) always validates `agent_key` and raises `DraftContentRejected`, not `PublicationRejected`. The plan's sentence also merges the non-str note issue and the blank-note issue into one.

**Instruction (Task 1):**
- Extract `_actor_and_lock_issues(actor, lock_version) -> list[DraftValidationIssue]` from `_validate_common`'s first two blocks (`:548-572`), unchanged. `_validate_common` then calls it, so its behaviour stays byte-identical and `test_graph_configuration_draft.py` stays GREEN.
- `_validate_publication_request` calls `_actor_and_lock_issues`, then appends exactly one note issue:
  - `DraftValidationIssue("release_note", "strict_type", "Release note must be a string.")` if the note is not a `str`;
  - else `DraftValidationIssue("release_note", "blank", "Release note must not be blank.")` if `not note.strip()`;
  - else the `too_long` issue (Correction 10).
- It then raises `PublicationRejected(*issues)` if there are any issues. The order is `actor`, `lock_version`, `release_note`.
- `test_blank_note_and_bad_types_reject_before_any_lock` asserts these exact triples per parametrization.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking but required before Task 1 review.

**Cost if wrong:** `DraftContentRejected` leaks from the publish path (wrong 422 family) or wrong issue codes.

### Correction 18 (M4) — Task 2's expected RED includes the two-publisher test

**Overrides:** plan line 632 ("the three waiter tests").

**Evidence:** the two-publisher loser queues on L0 behind the committing winner, so it hits the same zero-row scan.

**Instruction:** the expected RED is `test_publication_first_then_draft_save_gets_stale_not_500`, `test_publication_first_then_workbench_read_sees_new_release`, and `test_two_publishers_one_winner_one_exact_stale_conflict[both]`, all with `GraphConfigurationIntegrityError("graph configuration parent snapshot is inconsistent")`. The controller sabotage at line 652 predicts the same set.
- Correction 9's test and `test_sequential_retry_after_success_is_stale` are GREEN at the RED step.
- Correction 2's tests are written after Step 4 and are excluded.

**Sabotage:** the Task 2 controller set as above. **Binds:** Phase A, non-blocking.

**Cost if wrong:** an "unexpected" RED is logged as a harness defect.

### Correction 19 (M5) — the cleanup-first scenario uses exact ID sets

**Overrides:** plan line 700.

**Evidence:**
- "25 runs … approval is the oldest … 5 ineligible runs older than position 20" needs 26 runs.
- The expected outcome also depends on whether #268's cleanup keeps an unlinked approval outside the latest 20, which the draft does not settle.

**Instruction (Task 4):**
- Create exactly 25 runs `r1 … r25` for architect's required case, in strictly increasing `(run_at, id)`:
  - `r1` is the only eligible approval (current hash, completed, checks passed, approved);
  - `r2 … r5` (4 runs) are ineligible (rejected);
  - `r6 … r25` (20 runs, the latest-20 window) are ineligible (stale hash).
- At Task 0-B, record #268's retention rule for an unlinked eligible approval outside the window, and pin one of the following:
  - **(a)** If it is retained: cleanup deletes exactly `{r2 … r5}`, the retained set is `{r1, r6 … r25}`, and the publisher links exactly `r1`.
  - **(b)** If it is not retained: cleanup deletes exactly `{r1 … r5}`, and the publisher returns `PublicationNotReady((PublicationGap("architect", case.id, "no_eligible_approval"),), …)` with zero writes. Also raise a #268 correction, because deleting the only approval defeats the gate.

**Sabotage:** n/a. **Binds:** Phase B, non-blocking once ruled at Task 0-B.

**Cost if wrong:** an off-by-one scenario asserting an impossible retained set.

### Correction 20 (M6) — the L2 `FOR SHARE` claim is narrowed

**Overrides:** plan line 206 ("a case cannot be deactivated/re-versioned between readiness and link").

**Evidence:** #267's `update_test_case` *inserts* a new version row ("old rows remain unchanged"), and a row lock does not block inserts.

**Instruction:** the L2 row lock blocks only in-place updates (such as deactivating or flipping `is_required`) of the locked case rows. Re-versioning is covered by the gate's `test_case_version == case.version` predicate against the locked row, together with Q8's ruling at Task 0-B. `test_case_version_bump_after_approval_is_not_ready` must assert whichever mechanism Q8 establishes.

**Sabotage:** n/a. **Binds:** Phase B, non-blocking.

**Cost if wrong:** a false serialization claim in the whole-branch review's lock table.

### Correction 21 (M7) — route tests fake only the readiness callable

**Overrides:** plan line 797 ("readiness and gate monkeypatched to deterministic fakes").

**Evidence:** faking the gate contradicts `assert type(captured_gate) is ApprovalEvidenceGate`.

**Instruction (Task 5):**
- Monkeypatch only the route module's `_readiness_callable` to return a deterministic sentinel-producing callable. The route constructs the real `ApprovalEvidenceGate`.
- On SQLite:
  - produce not-ready by saving a role with no approval;
  - produce success by ORM-seeding one eligible approved `AgentTestRun` per required case of each changed role (shape per Task 0-B);
  - produce `no_required_case` by deactivating the case.
- Capture the gate by wrapping `ApprovalEvidenceGate.__init__` (a spy that calls through). Assert the gate's type and that its `_readiness` is the patched callable.

**Sabotage:** n/a. **Binds:** Phase B, non-blocking.

**Cost if wrong:** route tests pass while the production gate is never constructed or bound.

### Correction 22 (M8) — one definition of `publishable`

**Overrides:** plan lines 797 and 844, and Task 6's sabotage prediction at line 878.

**Evidence:** the plan implies both "changed ≠ ∅ only" and "changed, all ready, no issues".

**Instruction:**
- **Server (Task 5):**
  ```
  publishable = bool(changed)
      and not validation_issues
      and every changed role has ≥1 active required case
      and #268 readiness reports no blocking item for any changed role
  ```
  (`blocking_agents ∩ changed == ∅`, field names per Task 0-B.) It is advisory; the publication gate stays authoritative.
- **Client (Task 6):** `canPublish = state === 'ready' && preview.publishable && note.trim() !== '' && note.length <= 2000`.
- Task 6's controller sabotage (drop `preview.publishable &&`) predicts RED on "Publish is disabled with blocking readiness" (server `publishable: false`, non-blank note). The blank-note test stays GREEN under that sabotage.
- Add a Task 5 preview test for each false clause.

**Sabotage:** Task 6's controller target, with the prediction above. **Binds:** Phase B, non-blocking.

**Cost if wrong:** the page enables Publish for an unpublishable draft (a guaranteed 409), or the sabotage predicts the wrong test.

### Correction 23 (M9) — the deferred-guard test asserts something new

**Overrides:** plan line 574 (`test_deferred_guard_accepts_close_and_insert_only_via_core`).

**Evidence:** re-opening a closed release is already covered by `test_graph_configuration_constraints_postgres.py:257` (`…allow_only_first_close`).

**Instruction:**
- Rename the test to `test_published_history_rejects_reopen_and_second_close`.
- After publication, assert both of the following raise `IntegrityError`, each in its own transaction:
  - `UPDATE graph_release SET effective_to = NULL WHERE id = v1`;
  - `UPDATE graph_release SET effective_to = now() + interval '1 hour' WHERE id = v1` (a second close).
- Assert that v1's `effective_to` still equals v2's `effective_from` exactly.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking.

**Cost if wrong:** a duplicate test counted as new coverage.

### Correction 24 (M10) — Task 1's PostgreSQL file defines its own gate and save helpers

**Overrides:** plan line 601 ("copy `_NoEvidenceGate` into this file").

**Evidence:** Task 1's PostgreSQL file already publishes (plan lines 569–574), so it needs the gate and a save helper at Task 1.

**Instruction:**
- Task 1 defines `_NoEvidenceGate` and a PostgreSQL `_save_prompt(factory, agent_key, suffix, *, lock)` at the top of `tests/integration/test_graph_release_publication_postgres.py`. These are test-only, never imported by `src`, and use no backdating.
- Task 2 appends to the same file and reuses them without copying.
- Task 3 imports them from that module by underscore name only.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking.

**Cost if wrong:** duplicated helpers drift between files.

### Correction 25 (M11) — the `materialize_or_reuse_revision` docstring

**Overrides:** plan line 410 ("Never flushes").

**Evidence:** under autoflush, the `session.scalar` lookup flushes pending revisions added by earlier loop iterations.

**Instruction:** the docstring reads "Never calls `flush()` itself; the lookup may autoflush revisions added earlier in the same session, which is harmless because each is complete." The seam table's "never flushes" (line 219) reads the same.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking.

**Cost if wrong:** a reviewer chases a non-defect.

### Correction 26 (M12) — Phase B's task range and the reader ordering claim

**Overrides:**
- plan line 7 ("Phase B (Tasks 4–8)") against line 16 ("Tasks 4–9");
- line 204 (the reader proved "in both orders").

**Instruction:**
- **Phase range:** Phase B is Tasks 4–8. Task 9 is the whole-slice verification that follows Phase B.
- **Reader-first test (Task 2):** `test_workbench_read_first_then_publication_waits`.
  - The reader, inside `read_workbench`, is paused after its `FOR SHARE` L0 statement.
  - The publisher is observed blocked by the reader's PID.
  - Release the reader: it returns `active_release.release_id == v1.id` with the pre-publication draft. The publisher then returns v2.
- **Line 204** then reads "writer, reader and publisher × publisher, both orders", which is now true.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking.

**Cost if wrong:** #268's readiness, which reuses the reader pattern, is asserted to serialize in an order that was never tested.

### Correction 27 (M13) — the PostgreSQL matrices name the missing `integration-graph` files

**Overrides:** plan lines 299–305 (the Task 0 Step 3 baseline loop) and line 932 (the Task 9 matrix).

**Evidence (re-verified):**
- `.github/workflows/test.yml:452` runs `test_conversation_pin_migration_postgres.py` and `:461` runs `test_conversation_creator_exclusions_postgres.py` in `integration-graph`, and neither is in the plan's matrices.
- `test_mixed_release_collaboration_acceptance_postgres.py` (`:456`) appears in Task 9 but is absent from the Task 0 baseline.
- The #264 house plan names the migration file explicitly (`2026-09-22-safe-output-schema-overlays.md:126`, `:202`).

**Instruction:**
- Add these three files to Task 0 Step 3's loop: `test_conversation_pin_migration_postgres`, `test_conversation_creator_exclusions_postgres` and `test_mixed_release_collaboration_acceptance_postgres`.
- Add the first two to Task 9's matrix.
- Each runs as its own command, with zero skips recorded per file.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking (it affects the baseline).

**Cost if wrong:** a regression in pin migration or creator exclusion goes unseen until CI.

### Correction 28 (M14) — both Task 3 sabotages restore, prove marker removal, and re-run GREEN

**Overrides:** plan line 675 ("restore" is stated for the reviewer only).

**Evidence:** plan line 24 requires every sabotage to be restored, to prove its marker is gone with a clean diff, and to capture GREEN.

**Instruction:** for Task 3's controller sabotage (Correction 6) **and** its reviewer sabotage (`MAX_ACTIVE_RELEASE_LOCK_SCANS = 1`), do all of the following: restore exactly, show `rg` with no marker hit, show `git diff --exit-code` for the touched file, and re-run Task 3's Step 3 GREEN. The same applies to every sabotage added by Corrections 1–14.

**Sabotage:** n/a. **Binds:** Phase A, non-blocking.

**Cost if wrong:** a sabotage left in place leaks into the Task 3 commit.

---

## Blocking summary

- **Phase A (before Task 1):**
  - Correction 2 (C2);
  - Corrections 3–6 and 8–9 (I1–I4, I6 parts 1 and 3, I7);
  - the Phase A parts of Correction 1 (the gap type and wire) and Correction 10 (the Q6 note cap, the Q1 record).
- **Phase B (before Task 4):**
  - Correction 1 (C1: the gate, tests and sabotage);
  - Correction 7 (I5, needed for Task 6);
  - Correction 8 part 2 (the evidence-link injection);
  - Corrections 10–14 (I8–I12).
- **Non-blocking (apply in the task named):** Corrections 15–28 (M1–M14).

## Correction 29 — BLOCKING (Phase B, Task 4): the case lock must not filter; a concurrent supersede drops a required case out of the gate

Source: #267's whole-branch review (`.worktrees/issue-267-plan/.superpowers/sdd/2026-09-23-agent-test-case-runs/whole-branch-review.md`, I-2), proved on a throwaway PostgreSQL database.

The plan's case-lock statement (plan :721-725) takes `FOR SHARE` on the ACTIVE REQUIRED cases of the changed roles and gates on that result set. #267's case writer supersedes a case by UPDATE-retiring the old row and INSERTing `version+1` in one transaction. When the publisher's `FOR SHARE` waits behind that writer, PostgreSQL's READ COMMITTED re-check re-evaluates the retired row, finds it no longer matches `is_active`, and drops it; the new version is an INSERT the statement never sees. Measured: the publisher's locked set was `[A]`; a fresh re-read showed `[A, B v2]`. The required case B drops out of the gate and publication proceeds with no approval for it.

This supersedes Correction 20's reasoning and the #267 ledger's "false no_required_case, retry clears" note, both wrong for roles with more than one required case.

Replacement instruction: lock the changed roles' `agent_test_case` rows WITHOUT an `is_active`/`is_required` filter, ordered by id (`FOR SHARE`), as #267's `_lock_role_of` does for writers; then, in a NEW statement, re-select the active required cases and gate on that. Add a PostgreSQL ordering test with a role holding two required cases, where a supersede of one commits while the publisher waits: the gate must see the new version (and refuse if it is unapproved). Sabotage: restore the filtered lock → that test REDs.

Cost if wrong: an unapproved required case is published.

## Correction 30 — carried from #267's whole-branch review

- `run_kind='candidate'` must filter the evidence gate's run query (plan :727-735).
- The verdict route path is `/api/admin/agent-definitions/test-runs/{run_id}/verdict` (#267 C23), not `/api/admin/agent-test-runs/...`.
- #269's C14 trigger coexists with #267's `trg_agent_test_run_evidence_immutable`; the idempotence test expects both.
- Verdict columns: `verdict`, `verdict_reviewer`, `verdict_at`, `verdict_notes`. ORM fallbacks must supply `run_kind`, `model_payload`, both `compared_*` and `deterministic_check_results`.
- The fake adapter lives at `tests/fixtures/deterministic_model_adapter.py`.

## Correction 31 — the release routes attach to the existing admin router

Source: #270's plan review (Minor), and #267 C23's precedent. The plan puts the preview and publish handlers on a new `graph_releases.py` router. Replacement: the handlers may live in their own module, but they register on the EXISTING admin prefix `/api/admin/agent-definitions` with the same router-level `require_admin` and `require_draft_write_principal` dependencies; no second `APIRouter` with its own prefix, and no `main.py` change. Model-free routes still parse the body after authorisation. Cost if wrong: two admin routers whose auth dependencies can drift.

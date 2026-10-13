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

## Correction 32 — BLOCKING (Phase B, Tasks 4-5): #268's readiness is informational inside publication, never the gate

Source: #268 Task 2 review (`.worktrees/issue-268-plan/.superpowers/sdd/2026-09-23-test-evidence-readiness/task-2-review.md`, I1). #268 ships `AgentTestWorkbench.readiness_under_parent_lock(session)` as #269's Q4 binding: plain SELECTs, no row locks, safe to call inside #269's exclusive L0 and before or after the C29 case lock (no deadlock). It is a consistent snapshot that can be STALE.

#269 must NOT:
1. decide publication on its result (`all_ready`, `blocking_agents`, `missing_required_case`, `status`) — the evidence gate decides, with its own locks;
2. link `cases[].run_id` from it — that run was read without an L3 lock, so its verdict can flip before the link is inserted;
3. skip its own C29 sequence (unfiltered L2 case-row lock, re-select active required cases, L3 `FOR UPDATE` on runs, re-verify);
4. call it after any publication write — after the draft rebase every role reads unchanged and `all_ready=True`.

Permitted use: the 409 not-ready body and the preview, computed BEFORE any write. A body may show a case `approved` while the gate lists it as a gap (the safe direction only).

CONTROLLER CORRECTION: #268's ledger recorded this as "carried to #269's ledger" before it was written; it is written here now.

Cost if wrong: publication proceeds on stale readiness and links a run whose verdict changed.

### Correction 33 — a correlated `NOT EXISTS` protection is not re-checked by a row-lock wait; lock first, re-check in a new statement — BLOCKING (every #269 DELETE/UPDATE/INSERT…SELECT guarded by a correlated predicate, incl. the gate re-verify)

Source: #268 Task 4 (`3b0d2070a`), reproduced on PostgreSQL by `test_postgres_cleanup_*` ordering test with PID-observed blocking. A single DELETE whose outer `WHERE` repeated `NOT EXISTS(link)` / `NOT EXISTS(eligible approval)` on the target row still deleted a row approved by a writer it had waited on: PostgreSQL plans each `NOT EXISTS` as an anti-join, and READ COMMITTED's EvalPlanQual recheck re-runs that join against the rows originally fetched (none), so the now-protected row still qualifies. C19e's prescribed single-statement fix is therefore WRONG.

Ruling for #269: any write whose safety depends on a correlated sub-predicate over rows another transaction may change must (1) lock the target rows `FOR UPDATE` (id order) in one statement, then (2) re-evaluate the predicate in a NEW statement (fresh READ COMMITTED snapshot) before or as part of the write. The C29 gate re-verify already follows (1)+(2) — keep it that way; do not collapse it into one statement. Each such site needs a PID-observed ordering test, or a ledgered argument that no concurrent writer can change the sub-predicate's rows.

Cost if wrong: publication links, or cleanup deletes, a row whose protection committed during the wait.

Addendum (from #268 Task 4 review): every multi-row L3 run lock in #269 (the gate re-verify, the linker) takes rows `FOR UPDATE` in `ORDER BY id`, matching #268 cleanup, so two L3 lockers never cross.

---

# Task 0 corrections pass (2026-09-26) — corrections 34–55

- **Probed at:** `plan/publish-release-269` HEAD `cd63aa09b`, which is `16aa02b76` (Merge #268 on `feat/langgraph-core`) plus plan/ledger docs only. All four predecessors (#264, #266, #267, #268) are integrated, so Task 0 phases A and B ran together. Bases and heads: `TASK1_BASE`, `INTEGRATION_BASE`, `predecessor-heads.md`. Baselines: `reports/preflight.md`.
- **Corrections 1–33 are not edited.** Where one is now wrong, an erratum correction below says so (35 → C31, 44 → C7, 36 → C17).
- **"Reasoned"** marks a claim from code plus documented PostgreSQL semantics that was not run as a probe; the named task's RED must confirm it. Everything else was read from the code at the cited line or run.
- **Q-answers:** Q2 → Correction 40, Q4 → 39, Q8 → 42, Q9 → 41. C19 outcome (a) → 43. Fake adapter → 38. #268 publication code: none (→ 38, row "publication").

### Correction 34 — the "Verified code facts" table, re-anchored at `cd63aa09b`

**Overrides:** plan lines 30–70 (every row's `file:line`), and every task "Files:" line that cites them (lines 335–338, 595, 769, 837–838, 888). **Evidence:** each row re-read at HEAD. **Ruling:** briefs cite the right-hand column. A row marked **CHANGED** changes the fact itself, not only the line, and has its own correction.

| Plan row | Plan cite | Actual at `cd63aa09b` | Fact still true? |
|---|---|---|---|
| `AgentDefinitionRevision` + both uniques | `graph_configuration.py:152–183` | `src/database/models/graph_configuration.py:159–190` (`uq_…_agent_hash` :180–184, `uq_…_id_agent` :185–189) | yes |
| `GraphRelease`, strict interval, `uq_graph_release_one_active` (PG + SQLite) | `:186–238`, `:231–237` | `:193–245`; `ck_graph_release_interval` :233–236; index :238–244 (`postgresql_where` + `sqlite_where`) | yes |
| `GraphReleaseAgent` PK + composite FK RESTRICT | `:241–267` | `:248–274` (FK :264–269) | yes |
| `GraphDraft` singleton, `base_release_id` FK, `lock_version >= 0` | `:270–297` | `:277–304` | yes |
| `GraphDraftAgent` PK, `candidate_hash` | `:300–318` | `:307–325` | yes |
| `AgentTestCase` + `uq_agent_test_case_agent_name_version` | `:321–363` | `:328–370` (unique :364–369) | yes; see C42 for versioning |
| mutation guards | `src/core/database.py:935–1081` | `:935–1122`. Now also installs #267's `trg_agent_test_run_evidence_immutable` (:1076–1107; function compares `to_jsonb(NEW/OLD)` minus the four verdict columns). The deferred `trg_graph_release_exactly_one_active` is :1110–1122. | yes, plus #267's evidence trigger (C30 already notes coexistence) |
| `read_workbench` (`FOR SHARE`) | `workbench.py:179–186` | `src/services/graph_configuration_workbench.py:179–186` | yes, unchanged |
| `_lock_current_parents` (one statement; ≠1 rows raises; base check) | `:188–238`, `:210–227`, `:234–237` | `:188–238`; diagnosis :209–227; base check :234–237 | yes, unchanged |
| `_snapshot_locked_workbench`, `changed` | `:240–361`, `:325` | `:240–361`, `:325` | yes |
| `_read_workbench_for_draft_write` | `:363–408` | `:363–408` | yes |
| `ActiveReleaseSnapshot`, `DraftMetadataSnapshot` | `:39–59` | `:39–59` (classes at :40, :53) | yes |
| validator tuples | `draft.py:250–256` | `src/services/graph_configuration_draft.py:346–352` | **CHANGED** — the saves also run `_endpoint_name_policy_validator` through `_save_local_validators()` (:380–387) and a remote phase `_validate_remote_endpoint` (:389–397). See C37. |
| `_run_candidate_validators` | `:258–268` | `:368–378` | yes |
| `DraftValidationIssue`, `DraftContentRejected` | `:103–117` | `:154–168` | yes |
| `_draft_aggregate_snapshot` | `:736–752` | `:973–989` | yes |
| `_write_locked_content`; timestamp; audit | `:754–793`, `:767–773`, `:774–776` | `:991–1029`; timestamp :1003–1009; audit :1010–1012 | yes |
| `_validate_common` (C17's `:547–582`, `:548–572`) | — | `:765–777` + `_lock_and_agent_key_issues` :787–817 | **CHANGED** shape — see C36 |
| `_database_timestamp` | `bootstrap.py:84–93` | `src/services/graph_configuration_bootstrap.py:84–93` | yes |
| bootstrap reuse-by-hash | `:215–241` | `:214–241` (lookup :218–224, insert :226–230, validate :231–240) | yes |
| `_validate_current_graph`; mappings; base check | `:121–199`, `:129–157`, `:164–168` | `:121–198`; mappings :129–157; base check :165–168; required-case coverage :187–198 | yes |
| content seam | `content.py:100–112`, `:128–146`, `:71–81` | `revision_from_definition` :100, `validate_definition_hash` :128, `definition_content_values` :71 | yes |
| facade, `__all__` | `graph_configuration.py:44–49`, `:57–79` | class :47–52 (bases: Draft, Workbench, Bootstrap); `__all__` :88–114; also `build_remote_endpoint_draft_validator` :55–80 | yes |
| `lock_active_graph_release`, `MAX_ACTIVE_RELEASE_LOCK_SCANS` | `conversation_pins.py:66–74`, `:55` | `:66–74`, `:55`; `_active_release_for_update` :58–63; `get_conversation_graph_version` :99–111 (Task 8's sabotage line is :108, the `is_older_than_active` term) | yes |
| pin call sites | `session_manager.py:759`, `:897`, `:1245` | `:759`, `:897`, `:1245` | yes |
| `PersistedGraphReleaseLoader` cache by id | `persisted_graph_release.py:91–139` | `:91–138` (cache :96, :104–106, :138); `_validate_complete_snapshot` :167 | yes |
| `canonical_payload`; `temperature` | `graph_definition_manifest.py:281–290`, `:96` | `:281–290`, `:96` | yes |
| admin router | `agent_definitions.py:51–55` | `src/api/routes/agent_definitions.py:102–107` | yes |
| `require_draft_write_principal` | `:58–66` | `:110–118` | yes |
| router registration | `main.py:23`, `:484` | `:23`, `:484` | yes; see C35 |
| response models | `schemas/agent_definitions.py:301–319` | `ActiveReleaseResponse` :301, `DraftMetadataResponse` :313, `DraftFieldErrorResponse` :403 (C15) | yes |
| PG helpers | `postgres_concurrency_helpers.py:32`, `:202–212` | `_WAIT_SECONDS` :32; `_await_lock_waiters` :202 | yes |
| creator harness | `test_mixed_release_creation_postgres.py:26–34`, `:125–126`, `:129–172`, `:175–190` | `CREATORS` :27, `_seed` :71, `_backend_pid` :125, `_create` :129, `_creator_patches` :175; `before_cursor_execute` recipe :245; `INSERT INTO user_sessions` matcher :305 | yes |
| workbench PG pattern | `test_agent_definition_workbench_postgres.py:164–190`, `:1280–1304` | PID override :174–176; pause listener :184; `real_route_stack` :1283–1310; `SELECT CURRENT_TIMESTAMP` capture :137–141 and assertion :282 | yes |
| route unit fixture | `test_agent_definition_workbench_routes.py:117–135`, `:137–157` | `session_factory` :129–148; `_accepting_remote_endpoint_validator` :150; `_app_for` :155; `_force_admin` :202 | yes, lines moved |
| forbidden-action rule | `forbiddenActionNames.ts`, `ALLOWED` = 3, `:1462` | stems :18–19; `ALLOWED_ACTION_NAMES` :36–44 = **7** entries; lengths `AgentDefinitionWorkbench.test.tsx:378` and `agent-definition-workbench.spec.ts:1518` | **CHANGED** — see C44 |
| workbench header | `AgentDefinitionWorkbench.tsx:31–48`, `:139–144` | header `<header>` :112–130 (Graph Version :115, Draft base :121–122, Lock version :125) | yes, lines moved |
| admin route gate | `App.tsx:27–33`, `:53` | `RequireAdmin` :27–33, `/admin` :53 | yes |
| workbench client | `agentDefinitions.ts:328`, `:698–722` | `AgentDefinitionApiError` :328; settled memo :696–722 | yes |
| CI job | `test.yml ~447–474` | `integration-graph` :410; `run:` block :447–473 | yes |

**Cost if wrong:** a brief sends an implementer to the wrong line; the CHANGED rows ship a validator or a guard count that no longer matches the code.

### Correction 35 — erratum to C31: a module that decorates the existing router after `include_router` registers nothing

**Overrides:** C31 ("the handlers may live in their own module … no `main.py` change"), plan lines 180, 238, 239, 768–769, 801–816.

**Evidence:**
- `src/api/main.py:484` runs `app.include_router(agent_definitions.router)` once at import time.
- Probe (`/tmp`, a plain FastAPI app): a route added to an `APIRouter` **after** `app.include_router(router)` is absent from `app.routes`. The output was `['/p/a']` with `/p/late` missing. FastAPI copies routes when `include_router` is called.
- So a `graph_releases.py` that decorates `agent_definitions.router` registers nothing, unless it is imported before `main.py:484`. Importing it from `agent_definitions.py` would be circular, because it needs `router`, `require_draft_write_principal` and `get_agent_test_workbench` from there.
- Precedent: #267 and #268 put their routes (test runs :1125–1203, verdict :1289, readiness :1347) directly in `agent_definitions.py`.

**Ruling:**
- Task 5 adds the two handlers `GET /release-preview` and `POST /releases` **in `src/api/routes/agent_definitions.py`**, on the existing `router`.
- The wire models go in a new `src/api/schemas/graph_releases.py`, imported by the route module.
- No `graph_releases.py` route module, and no `main.py` change.
- `test_main_app_registers_release_routes` builds `src.api.main.app` and asserts each path exists exactly once, so it would catch a late registration.
- Task 5's Files list changes accordingly. This touches a #267/#268-owned file, which plan line 238 said would not happen, but Task 5 is the only task that touches it.

**Cost if wrong:** routes that exist in the module but return 404 in the app. Task 5's route tests build their own app with `include_router` after import, so they would pass while production is broken.

### Correction 36 — erratum to C17: `_validate_common` has no separable actor+lock block any more

**Overrides:** C17's "Extract `_actor_and_lock_issues(actor, lock_version)` from `_validate_common`'s first two blocks (`:548-572`)".

**Evidence:**
- The actor checks are inline at `graph_configuration_draft.py:765–777`.
- The lock checks are fused with the agent-key check in `_lock_and_agent_key_issues(lock_version, agent_key)` (:787–817), which is shared with `_validate_lock_and_agent_key` (:779–785, used by the probe/test-run read at :700).

**Ruling (Task 1):**
- Extract two static helpers:
  - `_actor_issues(actor) -> list[DraftValidationIssue]`, the body of :766–775;
  - `_lock_version_issues(lock_version) -> list[DraftValidationIssue]`, the lock-version part of :787–809.
- `_lock_and_agent_key_issues` becomes `_lock_version_issues(lock_version) + <the unchanged agent_key check>`.
- `_validate_common` becomes `_actor_issues + _lock_and_agent_key_issues`, with byte-identical issues and order.
- `_validate_publication_request` = `_actor_issues + _lock_version_issues + <one note issue>` (C17's note rules unchanged), raising `PublicationRejected`.
- **Gate:** `tests/unit/test_graph_configuration_draft.py` and `test_agent_definition_workbench_routes.py` stay GREEN.

**Sabotage (optional):** none new; C17 stands.

**Binds:** Phase A (Task 1), blocking, because C17 is required before Task 1 review.

**Cost if wrong:** an implementer passes a dummy `agent_key` to reuse the fused helper, or duplicates the lock rules, which then drift.

### Correction 37 — publication runs #266's local endpoint-name policy, and never the remote endpoint check

**Overrides:** plan line 23 ("the writer's `local_candidate_validators` / `post_stale_validators` tuples"), line 44, lines 502–514 (`_validate_changed_candidates`), and line 344.

**Evidence:**
- #266 made the saves run `self._save_local_validators()` = `local_candidate_validators + (_endpoint_name_policy_validator,)` (`graph_configuration_draft.py:380–387`, used at :449 and :508). Then comes `post_stale_validators`, then `_validate_remote_endpoint` (:389–397), a network call to the catalog.
- The remote check runs **under L0 `FOR UPDATE`** in the saves, bounded to ~15 s (`model_endpoint_catalog.py:106–111`).
- #267's candidate read re-runs only the local policy (:719–721).
- Running only the two class tuples, as the plan does, would let a URL-shaped endpoint that bypassed the save (an ORM write, a future writer) be published.

**Ruling (Task 1):**
- `_validate_changed_candidates` runs `self._save_local_validators()`, then `self.post_stale_validators`, for each changed role, prefixing with `definitions.<key>.` as the plan says.
- It **never** calls `_validate_remote_endpoint`:
  - that would hold the release row `FOR UPDATE` across a network call, which blocks every conversation creation;
  - every candidate already passed the remote check at its save.
- **Tests (SQLite unit):**
  - an ORM-written `endpoint_name = "https://x/y"` on builder's draft row (hash recomputed) → `PublicationRejected` with exactly `DraftValidationIssue("definitions.builder.candidate.model.endpoint_name", "endpoint_url_not_allowed", "Endpoint must be a Databricks endpoint name, not a URL.")`, nothing written, gate not called;
  - a publish through `GraphConfiguration(remote_endpoint_validator=<spy>)` leaves the spy's call list empty.

**Sabotage (reviewer, Task 1, an addition):** replace `self._save_local_validators()` with `self.local_candidate_validators`. Predicted RED: the endpoint test (it publishes v2).

**Binds:** Phase A (Task 1), blocking.

**Cost if wrong:** a URL-shaped endpoint ships in a release, or publication stalls conversation creation behind a network call.

### Correction 38 — the "Consumed #267/#268 outputs" table, as built

**Overrides:** plan lines 76–93 (every row is "assumed from the draft plan") and line 184.

**Evidence:** code at HEAD. Every row was re-read; ORM columns were printed by the plan's Step 4 probe. **Ruling:** this table replaces the plan's.

| Plan row | As built (file:line) | Differs from the plan? |
|---|---|---|
| `AgentTestRun` | `graph_configuration.py:373–490`. Columns: `id, test_case_id, test_case_version, agent_key, run_kind, candidate_hash, compared_release_id, compared_definition_revision_id, model_payload, assembled_prompt, candidate_raw_output, candidate_structured_output, baseline_raw_output, baseline_structured_output, deterministic_check_results, deterministic_checks_passed, execution_status, error_detail, latency_ms, input_tokens, output_tokens, run_by, run_at, verdict, verdict_reviewer, verdict_at, verdict_notes`. `execution_status IN ('completed','model_error','assembly_error','incomplete')` :460–463; `run_kind IN ('candidate','published_baseline')` :456–459. FKs RESTRICT to `agent_test_case` :429–434, `graph_release` (`compared_release_id`) :435–440, and the composite revision :441–446. Index `ix_agent_test_run_case_run_at` :489. | Adds `run_kind` (C30), `compared_*`, tokens. No `test_case_version` FK. |
| `ck_agent_test_run_approved_only_if_completed_and_passing` | :476–480 | same name |
| `GraphReleaseTestRun` | :493–537. PK `(graph_release_id, agent_test_run_id)`; `evidence_kind IN ('approval','historical_restore')` :526–529; `(evidence_kind='historical_restore') = (source_release_id IS NOT NULL)` :530–533; three FKs RESTRICT :508–525; `ix_graph_release_test_run_run` :536 | as assumed |
| `DraftReadinessResult` etc. | `agent_test_workbench.py:579–625`: `TestCaseReadinessItem(agent_key, test_case_id, test_case_name, test_case_version, status, blocking, run_id, run_verdict, run_checks_passed)`, `AgentReadinessItem(agent_key, candidate_hash, is_changed_from_base, ready, missing_required_case, cases)`, `DraftReadinessResult(draft_lock_version, base_release_id, all_ready, blocking_agents, agents)`; `status ∈ {needs_test, test_failed, awaiting_review, approved}` :576 | adds `missing_required_case` |
| readiness entry point | `AgentTestWorkbench.readiness_under_parent_lock(session)` :1543–1631 (C39). `draft_readiness` :1534–1541 owns its transaction and is **not** for #269. | see C39 |
| readiness wire | `DraftReadinessResponse` `src/api/schemas/agent_definitions.py:751–763` (+ `AgentReadinessResponse` :740, `TestCaseReadinessResponse` :722); route `GET /api/admin/agent-definitions/readiness` `agent_definitions.py:1347–1365` | **path differs**: the plan's line 85 says `/api/admin/graph-draft/readiness` |
| cleanup | `cleanup_unpublished_test_runs(session, *, per_case_limit=20) -> int` :1634–1666 (C40) | locks **both** parents, not the draft only |
| verdict writer | `record_verdict(session, *, run_id, verdict, reviewer, notes)` :1471–1531. There is **no `actor` kwarg**; the reviewer is the principal. L3 only (C41). | signature differs from plan line 87 |
| run route / verdict route | `POST /api/admin/agent-definitions/draft/{agent_key}/test-runs` (`agent_definitions.py:1125–1153`, 201); `POST /api/admin/agent-definitions/test-runs/{run_id}/verdict` (:1289–1344, 200) | verdict path per C30 |
| fake adapter | `tests/fixtures/deterministic_model_adapter.py:85` `DeterministicFakeModelAdapter` (modes incl. `success`, `pause`). The route test recipe overrides `agent_definitions.get_agent_test_workbench` (:1022) with `AgentTestWorkbench(runtime=AgentRuntime(persisted_release_loader=…, model_adapter=adapter, identity_sink=…))`, per `_pg_executor` (`test_agent_definition_workbench_postgres.py:2141–2147`) and the override at :2465 | resolves the plan's ambiguity: `tests/fixtures/` |
| frontend readiness client | `frontend/src/api/agentDefinitions.ts`: `getDraftReadiness()` :1878, `parseDraftReadinessResponse` :1864, `DraftReadiness` :1797, `AgentReadiness` :1783, `TestCaseReadiness` :1769, `ReadinessStatus` :1766, `InvalidReadinessResponseError` :1808, key lists :1819–1830; the comment at :1662 says "#269 consumes these names; it must not define a second readiness type". `DraftStatus` (6 values) `draftEditorState.ts:40`; `draftStatus()` :697 | names now known |
| publication | none. `rg "def publish|publish_draft|Review & Publish|release-preview|publishRelease"` over `src frontend/src` finds only the forbidden-name *test* lists (`AgentDefinitionWorkbench.test.tsx:366`, `agent-definition-workbench.spec.ts:1509`, which ban `'Review & publish'`). No `graph_release_test_run` writer exists. `GraphReleaseTestRun` is read only by #268's `_linked_run` (:700–707). | Q1 held; no stop condition |

**Instruction:**
- Task 4's ORM fallback rows (C30) must set every NOT NULL column above.
- A `completed` row also needs `candidate_structured_output` (`ck_agent_test_run_completed_has_output` :481–484).
- `candidate_hash` must be 64 characters long (:485–488).

**Binds:** Phase B, blocking Task 4 (all rows ruled).

**Cost if wrong:** Task 4 or Task 5 codes against a shape that does not exist.

### Correction 39 — Q4 answered: the one readiness binding is `AgentTestWorkbench().readiness_under_parent_lock`

**Overrides:** plan lines 84, 178, 715–716, 805–807, 944 (Q4), and C21's "the route module's `_readiness_callable`".

**Evidence:**
- `readiness_under_parent_lock` (`agent_test_workbench.py:1543–1631`) never begins, commits or rolls back. It raises `RuntimeError` when `not session.in_transaction()` (:1570–1574), takes no row lock, and touches no runtime.
- `AgentTestWorkbench.__init__` (:995–1004) resolves the runtime lazily, so `AgentTestWorkbench()` builds nothing.
- The docstring (:1558–1568) restates C32.
- `draft_readiness` (:1534–1541) begins its own transaction, which makes it unusable inside publication.

**Ruling:**
- **Route side (Task 5):**
  - `_readiness_callable()` in `agent_definitions.py` returns `get_agent_test_workbench().readiness_under_parent_lock`. It goes through the route module's existing dependency function (:1022), so Task 8's single override of `get_agent_test_workbench` covers runs, verdicts and readiness alike.
  - The wire value is `DraftReadinessResponse.model_validate(result, from_attributes=True)`, as at :1365.
- **Call sites:**
  - the gate calls it only on the not-ready path, before any write (C32);
  - `preview_release` calls it after `_lock_current_parents(exclusive=False)`, inside its own `session.begin()`.
- **Unit test (Task 4):** calling the gate's readiness outside a transaction raises that `RuntimeError`. This pins that the gate is only ever invoked inside `publish_draft`'s transaction.
- C21 stands: monkeypatch `_readiness_callable`.

**Binds:** Phase B, blocking Tasks 4–5.

**Cost if wrong:** readiness opens a nested transaction inside publication (`InvalidRequestError`), or the route binds `draft_readiness` and every not-ready publish becomes a 500.

### Correction 40 — Q2 answered: cleanup locks L0 (both parents, `FOR SHARE`), then L3 in id order, then deletes in a new statement

**Overrides:** plan lines 86, 204 ("#268 cleanup (assumed): draft only `FOR SHARE`"), 207, 212, 700 ("paused after its `graph_draft FOR SHARE` statement"), and 942 (Q2).

**Evidence:** `cleanup_unpublished_test_runs` (`agent_test_workbench.py:1634–1666`) runs in its own transaction:
1. `self._graph_configuration._lock_current_parents(session, exclusive=False)` (:1660), the L0 statement `… FOR SHARE OF graph_release, graph_draft`.
2. `_cleanup_targets_statement` (:741–759): ranks the deletable candidates (`run_kind='candidate'`, not linked, not a retained approval, :728–737) by `ROW_NUMBER() OVER (PARTITION BY test_case_id ORDER BY run_at DESC, id DESC)`, and locks those past the limit with `FOR UPDATE OF agent_test_run ORDER BY id`.
3. `_cleanup_delete_statement` (:762–777): a new DELETE statement, re-checking `_deletable_candidate` (the C33 pattern).

It takes no case lock. #268 gives it **no production caller** (#268 Q1 ruling).

**Ruling (Task 4 ordering tests):**
- **Pause matcher.** Cleanup is paused after the first statement on thread `cleanup` whose normalized text contains `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT`, not a draft-only statement.
- **PID capture.** Construct `AgentTestWorkbench(graph_configuration=<subclass overriding _lock_current_parents to run SELECT pg_backend_pid() first>)`, precedent `_PidCapturingGraphConfiguration` (`test_agent_definition_workbench_postgres.py:3391`).
- **Where they serialize.** Cleanup and publication meet at L0 (share against update), in both orders, never at L3. In `test_publication_first_then_cleanup`, cleanup is blocked on its L0 statement. Assert that through `pg_stat_activity.query` for the cleanup PID, as C6 does.
- **Lock table.**
  - Row L0 "other holders" becomes: "#268 cleanup, both parents `FOR SHARE`".
  - Row L3 becomes: "#268 cleanup: `FOR UPDATE` in id order, only after its L0".
  - The deadlock argument's "cleanup holds L0-draft" becomes "cleanup holds L0 (both)".
- Every #269 multi-row L3 lock is `ORDER BY id` (C33 addendum), which matches cleanup.

**Binds:** Phase B, blocking Task 4.

**Cost if wrong:** a pause that never fires, which reads as a lock result; or a lock-table claim the whole-branch reviewer cannot re-derive.

### Correction 41 — Q9 answered: neither the case writers nor the verdict writer takes L0

**Overrides:** plan lines 206 ("#267 case writers (assumed; lock mode unspecified)"), 207, 212, and 949 (Q9).

**Evidence:**
- **Verdict writer.** `record_verdict` (:1471–1531) runs in its own transaction. Its only lock is `_verdict_lock_statement` (:531–538): `SELECT agent_test_run WHERE id=:id FOR UPDATE` with `populate_existing`. Then comes a Core `UPDATE` of exactly the four verdict columns (:1511–1524). No parent lock and no case lock (#268 C6).
- **Case writers.** `create_test_case` (:1034–1093), `update_test_case` (:1095–1180) and `deactivate_test_case` (:1182–1205) each take L2 only: `_role_lock_statement` (:212–224), which is **every row of the role, unfiltered, `ORDER BY id`, `FOR UPDATE`**, followed by `_reread_role_rows` (:232–…). This is taken directly or through `_lock_role_of` (:1207–1224). No L0.

**Ruling (lock table and argument):**
- **L2** "other holders": "#267 case writers: `FOR UPDATE`, every row of one role, id order, then a new-statement re-read". The gate's L2 `FOR SHARE` (C29) conflicts with that, and neither side then takes an earlier lock, so there is no cycle.
- **L3** "other holders": "#268 verdict writer: `FOR UPDATE` on one run row only".
- **The implicit row gains one conflict.** Publication's `graph_release_test_run` INSERT takes FK `FOR KEY SHARE` on each linked run. That conflicts with the verdict writer's explicit `FOR UPDATE`. It is harmless, because publication already holds those rows `FOR UPDATE` (L3), but see C47.
- **PID capture for the verdict thread (C5):** its first DB statement *is* the L3 lock, so use the `before_cursor_execute` thread-name recipe (`test_mixed_release_creation_postgres.py:245`).

**Binds:** Phase B, blocking Task 4.

**Cost if wrong:** the whole-branch reviewer cannot re-derive deadlock freedom from the plan's table.

### Correction 42 — Q8 answered: a new test-case version is a new row with a new id

**Overrides:** plan line 699 (`test_case_version_bump_after_approval_is_not_ready`, "per #267's versioning semantics recorded at Task 0-B"), lines 91 and 948 (Q8), and C20's final sentence.

**Evidence:**
- `update_test_case` (:1095–1180) locks the role (L2). It then sets `old.is_active = False`, flushes, and inserts `AgentTestCase(agent_key, name, version=old.version+1, is_active=True, …)`, a new row with a new `id`. Both happen in one transaction.
- An identical-content update is a no-op, with no new row (:1144–1152).
- A name change is refused (`name_immutable`, :1122–1131).
- `uq_agent_test_case_agent_name_version` (`graph_configuration.py:364–369`) enforces the lineage.
- A run snapshots `test_case_id` and `test_case_version` of the row it ran (#267; `AgentTestRun` :382–383). Readiness keys on both (`_current_candidate_evidence_clause` :627–637).

**Ruling (Task 4):**
- **Gate.** The gate keys on the locked case row's `(id, version)`. The version term is redundant with `id`, but keep it: there is no FK tying `test_case_version` to the row.
- **`test_case_version_bump_after_approval_is_not_ready`:**
  1. Approve a run of architect's required case (row X, version 1).
  2. Call `AgentTestWorkbench().update_test_case(test_case_id=X, …)` with **changed** `synthetic_payload`, giving row Y with version 2.
  3. Publish.
  4. Assert exactly `PublicationNotReady(locked_gaps=(PublicationGap("architect", Y, "no_eligible_approval"),), …)`, zero writes, and that X's approved run is not linked.
- **C29's two-required-case test** uses `update_test_case` as its concurrent supersede.

**Binds:** Phase B, blocking Task 4.

**Cost if wrong:** a version-bump test that is a no-op (identical content) and passes vacuously.

### Correction 43 — C19 is outcome (a); and C1's no-required-case state is reachable only by a direct write

**Overrides:** C19's "record at Task 0-B … pin one of" (it is now pinned), and C1 part 6's "using #267's case writer if the Task 0-B probe shows it allows this".

**Evidence:**
- **C19.** `_retained_approval` (`agent_test_workbench.py:710–725`) protects an approved, eligible candidate run of an active required case at the current draft hash. `_deletable_candidate` (:728–737) removes protected rows **before** ranking (:741–759), so they take no window slot (#268 C19d).
- **C1.** #267's writers refuse to retire the last active required case of a role:
  - `update_test_case` refuses `is_required → False` on the last one (:1133–1141);
  - `deactivate_test_case` refuses deactivating it (:1197–1198), with `_last_required_issue`.
  - A supersede keeps the role covered, because the new version is active.

**Ruling:**
- **C19 is outcome (a).** With C19's 25 runs: cleanup deletes exactly `{r2, r3, r4, r5}`; the retained set is `{r1, r6 … r25}`; the publisher links exactly `r1`. No #268 correction is needed.
- **C1's test** `test_changed_role_without_active_required_case_is_not_ready` produces the state with a direct write, `UPDATE agent_test_case SET is_active = false WHERE id = <architect's only required case>`, because the service refuses it. The gate's `no_required_case` emission stays: it is defence in depth for a direct write.
- **C1's carry-forward** ("#267's case writer must refuse to deactivate a role's last active required case") is **satisfied** by #267 as built. Close it.

**Binds:** Phase B, non-blocking (recording).

**Cost if wrong:** the cleanup-first test asserts outcome (b)'s impossible retained set, or C1's test calls a writer that refuses.

### Correction 44 — erratum to C7: the allowed list is now 7 entries, the exemption is exact whole-name, and #269 makes it 8

**Overrides:**
- C7's evidence (3 entries, `toHaveLength(3)` at `AgentDefinitionWorkbench.test.tsx:243` and `agent-definition-workbench.spec.ts:1462`);
- C7's constraint ("`forbidsActionName` removes allowed names with a case-sensitive `split` (`:34-39`)");
- C7's extra assertion;
- plan lines 67, 227, 887–888.

**Evidence:**
- `ALLOWED_ACTION_NAMES` (`frontend/tests/fixtures/forbiddenActionNames.ts:36–44`) has **7** entries. #267 added `Run test case` and `Run published baseline`; #268 added `Approve run` and `Reject run` (#268 C23; `task-6-report.md`).
- `toHaveLength(7)` is at `AgentDefinitionWorkbench.test.tsx:378` and `agent-definition-workbench.spec.ts:1518`.
- `forbidsActionName` (:53–57) exempts only an **exact whole name** after whitespace normalization (`includes`, case-sensitive), then tests the stems (`/…|review\s*&\s*publish|publish|…/i`, :18–19).
- Both sweeps list `'Review & publish'` (lowercase p) as a name that must stay forbidden (`AgentDefinitionWorkbench.test.tsx:366`, `agent-definition-workbench.spec.ts:1509`).

**Ruling (Task 6, as C7 placed it):**
- Append exactly `'Review & Publish'`, with a doc-comment line in the #267/#268 style.
- Set both lengths to `toHaveLength(8)` and add `toContain('Review & Publish')`.
- Replace C7's extra assertion with exactly these three:
  - `forbidsActionName('Review & Publish')` is `false`;
  - `forbidsActionName('Review & Publish now')` is `true`;
  - `forbidsActionName('Review & publish')` is `true`.

**Sabotage:** Task 7's controller sabotage (label → `Publish draft`) is unchanged.

**Binds:** Phase B, blocking Task 6.

**Cost if wrong:** Task 6 sets the length to 4 and REDs, or an implementer adds a case-insensitive exemption that spares `'Review & publish'`.

### Correction 45 — the gate's eligibility is the shared clause, term for term, and its lock reads refresh the identity map

**Overrides:** plan lines 721–745 (the gate's run predicate), and extends C30's `run_kind` item.

**Evidence:**
- `eligible_approval_clause` (`agent_test_workbench.py:640–658`) is #268's one eligibility predicate, shared by readiness (:693) and cleanup (:723). Its terms are:
  - `run_kind='candidate'`
  - `test_case_id`
  - `test_case_version`
  - `run.agent_key = case.agent_key`
  - `draft_agent.agent_key = case.agent_key`
  - `candidate_hash = draft_agent.candidate_hash`
  - `verdict='approved'`
  - `execution_status='completed'`
  - `deterministic_checks_passed`
- The plan's gate predicate omits `run_kind`, so a third copy of eligibility would drift.
- #267/#268 lock reads carry `populate_existing=True` (:226–229, :536–537).

**Ruling (Task 4):**
- Keep the plan's shape: a literal per-case predicate on `agent_test_run` columns only in the L3 `FOR UPDATE` statement, plus the Python re-verify on the locked rows.
  - **Why not the correlated clause itself:** a correlated or joined predicate in a locking statement is exactly C33's EvalPlanQual hazard.
- Add `run_kind == "candidate"` to both the query and the re-verify.
- Add `.execution_options(populate_existing=True)` to the L2 and L3 lock statements and to the C29 re-select.
- **Parity unit test (SQLite).** Parametrize over the nine terms above. For each, build one approved run that differs from an eligible one in exactly that term, and assert that both `readiness_under_parent_lock` and `ApprovalEvidenceGate.lock_and_verify` refuse it. The precedent is #268's `test_an_approval_that_differs_in_one_identity_term_is_never_found`.

**Sabotage (reviewer, Task 4, an addition):** drop `run_kind` from both the query and the re-verify. Predicted RED: the `run_kind` parametrization, where a `published_baseline` approval is linked.

**Binds:** Phase B, blocking Task 4.

**Cost if wrong:** publication links a baseline approval, or an approval readiness would not count. Either way the page and the gate disagree in the unsafe direction.

### Correction 46 — Task 5's publish handler runs the service off the event loop

**Overrides:** plan lines 812–816 (`async def publish_release` calling `publish_draft` directly).

**Evidence:**
- Every async write route in `agent_definitions.py` calls its service through `await run_in_threadpool(...)` (:621, :802, :935, :966, :1081, :1316).
- #268 pins this with `test_the_verdict_route_waits_on_the_run_row_lock_off_the_event_loop`.
- `publish_draft` can wait on L0 behind a draft save's remote endpoint check, up to ~15 s (`model_endpoint_catalog.py:106–111`), which would stall every request in the worker.

**Ruling (Task 5):**
- The POST handler parses the body after both auth gates, then calls `await run_in_threadpool(GraphConfiguration().publish_draft, db, …)`.
- The GET preview may be a plain `def`, which FastAPI already runs in the threadpool, as the readiness route does at :1347.
- **Route test:** the POST is observed waiting on a held lock while another request on the same app is served. Use the #268 test's pattern.

**Binds:** Phase B, non-blocking but required before Task 5 review.

**Cost if wrong:** one publish blocks a whole uvicorn worker for as long as its lock wait.

### Correction 47 — re-aim Task 4's reviewer sabotage: without the L3 lock the publisher still waits, at the evidence INSERT

**Overrides:** plan line 758, reviewer sabotage ("remove `.with_for_update()` from the run query → … publisher not observed waiting"), also cited in C11.

**Evidence (reasoned from the documented PostgreSQL row-lock conflict table; Task 4's RED must confirm):**
- In `test_verdict_rejection_first_then_publication`, the verdict writer holds the run `FOR UPDATE` (`agent_test_workbench.py:531–538`).
- With the gate's `FOR UPDATE` removed, the gate's plain SELECT reads the committed `approved` row and does not wait.
- But `link_release_evidence`'s INSERT into `graph_release_test_run` runs the FK check `SELECT 1 FROM agent_test_run … FOR KEY SHARE` on that run. `FOR KEY SHARE` conflicts with `FOR UPDATE`, so the publisher **is** observed blocked by the verdict PID, at its INSERT.
- After the verdict commits, the FK check passes and a run that is now `rejected` is linked. The C14 trigger fires only on `agent_test_run` UPDATE, so it does not catch this.

**Ruling (Task 4):**
- In the two verdict-ordering tests, after `_await_blocked_by`, assert that the waiter's `pg_stat_activity.query`, normalized, contains `FROM AGENT_TEST_RUN` and `FOR UPDATE`. That is, the publisher waits on its L3 statement, not on a later write (the C6 technique).
- **Revised prediction for the reviewer sabotage.** RED at that query-text assertion (the observed query is `INSERT INTO graph_release_test_run …`). If the assertion were absent, it would be RED at the outcome assertion instead (`PublishedRelease` linking a `rejected` run, where `PublicationNotReady` was expected).

**Binds:** Phase B, blocking Task 4.

**Cost if wrong:** a sabotage logged as "not RED for the predicted reason", or a lock claim the test never checks.

### Correction 48 — Q3's trigger turns a verdict change on a published run into an HTTP 500 at #268's verdict route (controller ruling needed)

**Overrides:** C10's Q3 bullet ("the verdict writer fails with the trigger's `IntegrityError`"), and plan line 238 ("`agent_definitions.py`, schemas: **no change**").

**Evidence:**
- `record_verdict` propagates `IntegrityError` unchanged (docstring :1488–1489; #268 C7).
- The verdict route maps only `VerdictRejected`, `TestRunNotFound` and `IneligibleForApprovalError` (`agent_definitions.py:1314–1344`). The comment at :1245–1247 says: "#269's linked-verdict trigger … propagates as a 500 and #269 owns any friendlier mapping".
- #268's ledger (Task 3) records the same carry-forward: "any new ineligibility reason must be added to the route's message table and response literal, or it becomes a 500 (pinned)".
- It is reachable in normal use. After a publish, the workbench still shows the linked run's `VerdictControls` (`TestRunPanel.tsx:132–195`), and "Reject run" is enabled on an approved run.

**Proposed ruling (default; the controller may override):**
- Task 4 adds a typed refusal as the first check after the L3 lock in `record_verdict`, as a **new statement** (C33): `EXISTS graph_release_test_run WHERE agent_test_run_id = :id` → `IneligibleForApprovalError(run_id, "linked_to_release")`.
  - A publication that linked the run holds it `FOR UPDATE` until commit, so the verdict writer's lock wait ends after the link is visible to a new statement.
- Extend:
  - `IneligibleReason` (`agent_test_workbench.py:503`);
  - `IneligibleForApprovalResponse.reason` (`schemas/agent_definitions.py:712–719`);
  - `_INELIGIBLE_MESSAGES` (`agent_definitions.py:1249–1252`), with "This run is evidence for a published Graph Version; its verdict cannot change.";
  - the TS `INELIGIBILITY_REASONS` (`agentDefinitions.ts:1699`) and `TestRunIneligibilityReason`. The TS side belongs to Task 6, and `tests/unit/test_draft_readiness_client_join.py` pins the parity.
- The C14 trigger stays as the backstop for direct writes.
- `test_publication_first_then_verdict_change` then expects `IneligibleForApprovalError(reason="linked_to_release")`, with the run still `approved` and the link in place. A separate direct-UPDATE test proves the trigger's 23514 (C14).
- **Alternative:** accept the 500 and file a follow-up. That costs nothing now, but every attempt ends in an unexplained 500.

**Sabotage (controller, Task 4, an addition):** delete the pre-check. Predicted RED: `test_publication_first_then_verdict_change`, which observes an `IntegrityError` (23514) where the typed refusal was expected.

**Binds:** Phase B, blocking Task 4, since it decides that test's expectation. It needs a controller ruling before Task 4 dispatches.

**Cost if wrong:** an admin who clicks Reject on published evidence gets an unexplained 500. Or, the other way, #269 edits three #268 files it would otherwise leave alone.

### Correction 49 — Task 2's handoff retry has more consumers than the seam table lists; keep the diagnosis string byte-identical

**Overrides:** plan line 223 (the handoff-retry consumers), and Task 2 Step 4 (the GREEN list).

**Evidence:** `_lock_current_parents` is also called by:
- #267 `_persist_run` transaction 2 (`agent_test_workbench.py:1767–1771`). It retries **itself** once when the error text equals `_PARENT_HANDOFF_DIAGNOSIS = "graph configuration parent snapshot is inconsistent"` (:388–390, :1802–1804).
- #268 `draft_readiness` (:1540), whose route maps the handoff to a 500 (`agent_definitions.py:1358–1364`).
- #268 `cleanup_unpublished_test_runs` (:1660).
- C2's bootstrap.

**Ruling (Task 2):**
- Keep the diagnosis text and exception type unchanged (plan Step 3 already says "diagnosis unchanged"). #267's outer retry then only ever sees a double handoff.
- **Consumers.** Add these to the seam table: #267 `_persist_run`, #268 `draft_readiness`, `readiness_under_parent_lock` callers, `cleanup_unpublished_test_runs`, and bootstrap (C2).
- **Step 4 GREEN also runs:**
  - `tests/unit/test_agent_test_workbench.py`, which includes `test_a_handoff_race_in_transaction_two_is_retried_once` :1545 and `test_a_second_handoff_race_or_another_integrity_failure_is_unavailable` :1562;
  - the PG tests `test_candidate_run_insert_waits_behind_an_exclusive_parent_holder_without_deadlock` (`test_agent_definition_workbench_postgres.py:2373`), `test_postgres_readiness_waits_behind_an_exclusive_parent_holder_and_reads_its_hash` (:2868) and `test_postgres_cleanup_waits_behind_a_draft_save_and_uses_its_new_hash` (:3466). These are inside the workbench PG file already in Step 4.

**Binds:** Phase A (Task 2), non-blocking.

**Cost if wrong:** a retry refactor rewords the diagnosis, and #267's run persist silently stops retrying.

### Correction 50 — C13's Task 0-B re-probe is closed by an existing GREEN test

**Overrides:** C13 instruction 1 (the Task 0 Step 4 probe with the fake adapter paused).

**Evidence:**
- `test_candidate_run_holds_no_lock_while_the_model_call_is_in_flight` (`test_agent_definition_workbench_postgres.py:2272–2360`) pauses `DeterministicFakeModelAdapter(mode="pause")` inside the model call and asserts:
  - `pg_locks` count 0 overall and 0 on the run tables;
  - `pg_stat_activity.state != 'idle in transaction'`;
  - a concurrent save commits unblocked.
- It is GREEN at baseline (the file ran 49 passed, 0 skipped; `reports/preflight.md`).
- In code, `execute_candidate_run` raises if `session.in_transaction()` before the call (:1274–1275).
- Transaction 2's lock statement is `_lock_current_parents(exclusive=False)`, i.e. `SELECT … FROM graph_release JOIN graph_draft ON true WHERE graph_release.effective_to IS NULL FOR SHARE OF graph_release, graph_draft` (:1767–1771).
- Its FK `KEY SHARE` on `compared_release_id` comes after its own `FOR SHARE` on the active release, or lands on an already-closed release when a publication intervened. That is release before anything, so there is no cycle (reasoned).

**Ruling:**
- C13 instruction 1 is satisfied: record it in the ledger, no new probe.
- C13 instruction 3 (Task 4's run-insert-vs-publication test, both orders) stands. Its run-first order pauses #267 after the T2 statement above.

**Binds:** Phase B, closed.

**Cost if wrong:** negligible; the Task 4 test re-proves it.

### Correction 51 — the lock-order table gains #266's remote check under L0

**Overrides:** plan line 204, L0 "other holders".

**Evidence:** both saves run `_validate_remote_endpoint` while holding L0 `FOR UPDATE` (`graph_configuration_draft.py:452`, :511). It is bounded to ~15 s (`model_endpoint_catalog.py:106–111`).

**Ruling:**
- Add to L0: "draft writer, including #266's remote endpoint check (≤ ~15 s)". Publication and every creator can wait that long behind a save.
- The Task 2/3 ordering tests use fake validators (`_accepting_remote_endpoint_validator`, `real_route_stack`), so `_WAIT_SECONDS = 30` (`postgres_concurrency_helpers.py:32`) is ample.
- #269 adds no remote call under L0 (C37).

**Binds:** Phase A, non-blocking (the table and the whole-branch review).

**Cost if wrong:** the whole-branch reviewer misses the longest L0 hold in the system.

### Correction 52 — the test matrices name the #266/#267/#268 files

**Overrides:** plan line 757 ("#267/#268's PostgreSQL files recorded at Task 0-B"), line 929 ("every #267/#268 unit file recorded at Task 0-B"), and line 932.

**Evidence:**
- #267 and #268 added **no new PostgreSQL files**. Their PG tests live in `tests/integration/test_agent_definition_workbench_postgres.py` (49 tests at baseline) and `test_graph_configuration_constraints_postgres.py` (66).
- Their unit files are `tests/unit/test_agent_test_workbench.py`, `test_draft_readiness_client_join.py` and `test_test_run_failure_contract_client_join.py`.
- #266 added `test_endpoint_name_policy_client_join.py`, `test_model_endpoint_catalog.py` and `test_model_endpoint_probe.py`.

**Ruling:**
- Task 4 Step 5, Task 9 backend and Task 9 PG matrices include:
  - those four client-join and workbench unit files;
  - the workbench and constraints PG files (already named).
- Tasks 1, 2, 4 and 5 add `tests/unit/test_agent_test_workbench.py` to their unit GREEN gate:
  - Task 1 changes `_validate_common`'s internals (C36);
  - Task 2 changes the lock #267/#268 call;
  - Tasks 4 and 5 edit #268's writer and routes (C48, C35).
- Task 6 adds `tests/unit/test_draft_readiness_client_join.py` when it edits the TS reasons (C48).

**Binds:** Phase A (Task 1 gate) and Phase B, non-blocking.

**Cost if wrong:** a #267/#268 regression is noticed only in CI.

### Correction 53 — harness anchors for Tasks 5 and 8, and no second `_await_blocked_by`

**Overrides:** plan lines 797 ("SQLite fixture copied from `:106–157`"), 908 (`real_route_stack` recipe) and 603–623.

**Evidence:**
- `session_factory` is at `test_agent_definition_workbench_routes.py:129–148` and `_force_admin` at :202.
- `real_route_stack` (`test_agent_definition_workbench_postgres.py:1283–1310`) overrides only `get_db` and the remote endpoint validator.
- A near-duplicate `_pg_wait_blocked_by` exists at :3375–3389. It lacks `wait_event_type = 'Lock'` and is private to that test module.

**Ruling:**
- **Task 8** also overrides `agent_definitions.get_agent_test_workbench` with the `_pg_executor` recipe (C38 fake-adapter row). Readiness then comes from the same workbench (C39).
- **Task 5** copies the fixture from :129–207.
- **Task 2** writes `_await_blocked_by` in `postgres_concurrency_helpers.py` as the plan says. No #269 file imports from `test_agent_definition_workbench_postgres.py`, because underscore helpers in a test module would re-collect its tests.

**Binds:** Phase A (Task 2) and Phase B (Tasks 5, 8), non-blocking.

**Cost if wrong:** Task 8 calls the real bounded runtime, or re-collects 49 tests into a new file.

### Correction 54 — the Review & Publish page needs a case-status label map; none is exported

**Overrides:** plan line 844 ("each required case's readiness status text from #268 (`Needs test`, …)") and line 841.

**Evidence:**
- #268 exports the snake_case `ReadinessStatus` (`agentDefinitions.ts:1766`) and a *role*-level `draftStatus()` (`draftEditorState.ts:697–709`), which maps the case codes inline.
- There is no exported case-code → label function. `rg "awaiting_review" frontend/src --glob '!*.test.*'` finds only :1766, :1816 and `draftEditorState.ts:694`/`:706`.

**Ruling (Task 6):**
- Add `readinessStatusLabel(status: ReadinessStatus)` in `frontend/src/components/Admin/GraphRelease/reviewAndPublishState.ts`, mapping `needs_test→'Needs test'`, `test_failed→'Test failed'`, `awaiting_review→'Awaiting review'`, `approved→'Approved'`.
- Do not modify `draftStatus`.
- A Vitest case asserts that the labels equal the corresponding `DraftStatus` members (a type-level `satisfies DraftStatus` on each value).
- Parse the 409 `readiness` with `parseDraftReadinessResponse`. Never define a second readiness type (the comment at `agentDefinitions.ts:1662`).
- Place the header link inside the `<header>` at `AgentDefinitionWorkbench.tsx:112–130`, not `:31–48`. Its text must stay outside any nav button, which is #268's I1 lesson for the text-content guard.

**Binds:** Phase B, non-blocking.

**Cost if wrong:** the page shows raw `awaiting_review` codes, or duplicates the readiness type.

### Correction 55 — the Task 0 phase split collapses: both bases are one commit

**Overrides:** plan lines 16 (distinct bases; rebase Phase A above `INTEGRATION_BASE`), 312 (rebase Tasks 1–3 and prove `INTEGRATION_BASE..HEAD`), 678, and 935 ("rebased Tasks 1–3 plus Tasks 4–8").

**Evidence:** `predecessor-heads.md`. `TASK1_BASE` = `INTEGRATION_BASE` = `cd63aa09b`, both written once and read-only.

**Ruling:**
- No Phase A rebase will happen, and Task 0 Step 4's rebase proof is vacuous.
- Task 9's whole-branch diff is `INTEGRATION_BASE..HEAD` = Tasks 1–8 exactly.
- Every Phase B correction (1, 7, 8 part 2, 10–14, 29, 30, 32, 33, 38–48) is known now. It must be in the brief of the task it binds. "Before Task 4" stays the gate for 38–48, but nothing is pending on outside work.

**Binds:** Phase A, recording.

**Cost if wrong:** a controller waits for a rebase that cannot happen, or a reviewer demands a two-segment diff proof.

---

## Per-task self-consistency (Tasks 1–9) at `cd63aa09b`, with Corrections 1–55 applied

"Tests vs code" asks whether each test the task specifies can go RED against the code the task writes, and GREEN after it. "Creates vs later touches" asks whether every file a task creates or modifies is the one later tasks expect.

| Task | Tests specified vs code specified | Files created vs files later touched | Open mismatches |
|---|---|---|---|
| 1 | The SQLite happy path needs C3 (aware compare) and C37 (endpoint policy). The invalid-candidate test monkeypatches `local_candidate_validators`, which `_save_local_validators()` still concatenates, so it stays valid. The blank-note test needs C36's helpers. `_save_prompt` builds `EditableModelDraft(prompt_text, endpoint_name, temperature, max_tokens, top_p)`; the class accepts exactly these plus optional `assembly_rules`/`schema_overlay` (`draft.py:51–61`), and `GraphConfiguration()` has no remote validator, so the saves skip the network. The PG tests need C8 (stages) and C13-2 (release-before-draft pin). | **Creates** `graph_configuration_publication.py`, `tests/unit/test_graph_release_publication.py`, `tests/integration/test_graph_release_publication_postgres.py` (with C24's helpers). **Modifies** content, bootstrap (`:84–93`, `:208`, `:214–241`), draft (`:765–817` per C36, `:991–1029`), facade (`:47–52`, `:88–114`), `test.yml`. Task 2 modifies bootstrap again (C2) and the PG file; Task 4 modifies the publication module. | none after C36/C37 |
| 2 | The waiter RED cause is confirmed by probe (plan review 1). The two-publisher RED is per C18. The v3 test is per C9. The reader-first test is per C26. The boot tests are per C2, using `_lock_current_parents(exclusive=False)` as the first statement of `_validate_current_graph` (`bootstrap.py:121`). The GREEN list gains the #267/#268 consumers (C49). | **Modifies** `graph_configuration_workbench.py:188–238`, `bootstrap.py:121–198` (C2), the Task 1 PG file, and `postgres_concurrency_helpers.py` (appends `_await_blocked_by`). Task 3 imports the helper. Task 4 uses it. | none |
| 3 | The creator harness names resolve (C34 row). The publisher pause and assertions are per C6. The partial-release variant is per C8-3. No production code. | **Creates** `test_graph_release_session_ordering_postgres.py`. **Modifies** `test.yml`. It imports `_NoEvidenceGate`/`_save_prompt` from Task 1's PG module (C24) and `_await_blocked_by` from the helpers (Task 2). | none |
| 4 | The gate is C1 + C29 + C33 + C45. The tests use the as-built shapes (C38), the cleanup order (C40), the writer locks (C41), versioning (C42), C19 (a) and the C1 direct write (C43). The trigger is C14 (a column-only `WHEN`, the function body checks the link). The verdict outcome is C48. Sabotage targets: controller C11/C1 + C14 + C48; reviewer C47 (re-aimed) + C45. | **Creates** `graph_release_evidence.py`, `tests/unit/test_graph_release_evidence.py`, `tests/integration/test_graph_release_evidence_postgres.py`. **Modifies** the publication module (`_link_evidence`), `src/core/database.py` (after :1107, C14), `test.yml`, and `test_graph_configuration_constraints_postgres.py:327` (C14 idempotence). **If C48 is ruled as proposed:** also `agent_test_workbench.py` (`record_verdict`, `IneligibleReason`), `schemas/agent_definitions.py:712–719`, and `routes/agent_definitions.py:1249–1252`. Task 5 later also edits `routes/agent_definitions.py`; the two touch disjoint regions and run sequentially. | **C48 needs a controller ruling** |
| 5 | The route tests are C21 + C35 (handlers on the existing router) + C46 (threadpool) + C39 (binding). The preview is per C22. The diffs are per plan: `DefinitionContent` fields = `agent_key, definition_version, prompt_text, model, schema_overlay, assembly_rules, protected_assembly, schema_contract`, so `_DIFF_FIELDS` covers all but the identity-constant `agent_key`. | **Modifies** the publication module (preview) and `routes/agent_definitions.py` (C35). **Creates** `schemas/graph_releases.py`, `tests/unit/test_graph_release_preview.py`, `tests/unit/test_graph_release_routes.py`. **No** `routes/graph_releases.py`, **no** `main.py` edit (C35). | none after C35 |
| 6 | The reducer, parser, `lineDiff` and page tests are per plan + C1 + C10 + C22 + C54. The forbidden-list edits are per C44 (7→8). | **Modifies** `api/agentDefinitions.ts` (append release types; plus the reasons if C48 lands), `App.tsx:53`, `AgentDefinitionWorkbench.tsx:112–130`, `forbiddenActionNames.ts`, `AgentDefinitionWorkbench.test.tsx:378`, `agent-definition-workbench.spec.ts:1518`, and `tests/unit/test_draft_readiness_client_join.py` (if C48). **Creates** the `GraphRelease/` module (7 files). | none (C48 conditional) |
| 7 | Playwright (a)–(f), with the 409 bodies per C1 and status 200 per C10. It no longer edits `forbiddenActionNames.ts` (C7/C44). | **Creates** `tests/e2e/graph-release-review.spec.ts`. **Modifies** `admin-route-gate.spec.ts`. The spec reads Task 6's `data-testid`s. | none |
| 8 | The flow is per plan + C12 + C30 (verdict path) + C53 (workbench override). Builder's required case must complete **with passing checks** under the fake adapter to be approvable. `test_every_role_model_sees_exactly_the_projected_seed_keys[builder]` (`test_agent_test_workbench.py:1949`) proves only `completed` — reasoned, re-probe at Task 8 RED. | **Creates** `test_graph_release_publication_acceptance_postgres.py`. **Modifies** `test.yml`. | builder-checks re-probe (non-blocking) |
| 9 | The matrices are per C27 + C52. The diff is per C55. The final sabotage is per plan. | none | none |

## Producer/consumer table (every task pair that shares a file or interface)

| Producer → Consumer | Shared file / interface | Contract the consumer relies on | Hazard |
|---|---|---|---|
| 1 → 2 | `test_graph_release_publication_postgres.py`; `publish_draft`; `_NoEvidenceGate`, `_save_prompt` (C24) | Task 2 appends tests and reuses the helpers unchanged | Task 2 must not redefine the helpers |
| 1 → 2 | `graph_configuration_bootstrap.py` (Task 1 swaps in the helpers; Task 2 adds C2's lock line) | bootstrap suites byte-identical after Task 1 | a sequential edit of one function region; Task 2 rebases nothing |
| 1 → 3 | `publish_draft`, `PublishedRelease.release.release_id`; helpers imported by underscore name | the exact field names in "Stable interfaces" | an import that re-collects tests (C24/C53) |
| 2 → 3, 4 | `_await_blocked_by(engine, *, waiter_pid, blocker_pid)` in `postgres_concurrency_helpers.py` | the signature is fixed at Task 2 | — |
| 2 → 4, 5, 8, #267/#268 | the `_lock_current_parents` retry | same statement, same diagnosis text (C49) | rewording breaks #267's own retry |
| 1 → 4 | `PublicationEvidenceGate` protocol; `PublicationNotReady` / `PublicationGap` (C1); `EvidenceLink`; `_link_evidence` hook | Task 4 replaces only the `_link_evidence` body | C1's type must be final at Task 1 |
| 1 → 4, 5 | `_validate_publication_request`, `PublicationRejected` issue triples (C17/C36/C10) | Task 5 maps them to 422 `invalid_publication` verbatim | — |
| 1, 4 → 5 | `publish_draft(..., evidence_gate=ApprovalEvidenceGate(readiness=...))` | the route constructs the production gate (C21) | — |
| 4 → 5, 8 | `ApprovalEvidenceGate(readiness=Callable[[Session], object])`; readiness = `readiness_under_parent_lock` (C39) | called only in-transaction and before writes (C32) | — |
| 4 → 6 (conditional) | `IneligibleReason` + `IneligibleForApprovalResponse.reason` → TS `INELIGIBILITY_REASONS` (C48) | a Python/TS join test pins the parity | a Task 4-only change leaves the TS parser rejecting the new 422 (it becomes `InvalidTestRunResponseError`) |
| 4 → 5 | `routes/agent_definitions.py` (Task 4 only if C48; Task 5 always, C35) | disjoint regions, sequential | — |
| 5 → 6 | the HTTP wire (preview, publish; status 200 per C10; gaps per C1; readiness verbatim) | the strict TS parsers mirror the Pydantic models | — |
| 5 → 8 | the same routes on the real app/router | Task 8 extends, never rewrites (#271) | — |
| 6 → 7 | `data-testid`s, `/admin/agent-definitions/review` route, `forbiddenActionNames.ts` (7→8, C44) | Task 7 edits no fixture | — |
| 1, 3, 4, 8 → CI | `.github/workflows/test.yml` `integration-graph` `run:` block (:447–473) | one appended file per task; `tests/unit/test_ci_collects_integration_tests.py` GREEN after each | sequential edits of one block |
| #268 → 4, 5, 6 | `eligible_approval_clause` (C45), `DraftReadinessResponse`, `parseDraftReadinessResponse` / `DraftReadiness` (C38, C54) | no second readiness type; eligibility parity test | — |

## Blocking summary for corrections 34–55

- **Before Task 1:** 36 (the C17 erratum), 37 (endpoint policy). 34 and 55 are recording.
- **Before Task 2:** 49 (the GREEN list; non-blocking).
- **Before Task 4:** 38, 39, 40, 41, 42, 45, 47, and **48, which needs a controller ruling**. 43 and 50 are recorded and closed.
- **Before Task 5:** 35 (the C31 erratum), 39, 46.
- **Before Task 6:** 44 (the C7 erratum), 54. Also 48's TS half, if ruled as proposed.
- **Non-blocking:** 51, 52, 53.

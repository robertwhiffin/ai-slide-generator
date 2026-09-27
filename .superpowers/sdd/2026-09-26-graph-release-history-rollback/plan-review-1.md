# Plan review 1: #270 Graph Release history and rollback

- **Plan:** `docs/superpowers/plans/2026-09-26-graph-release-history-rollback.md` (1075 lines), branch `plan/release-history-rollback-270` at `fbe7e1c82`.
- **Code base:** `a08389ec3`. `git diff --stat a08389ec3 HEAD` touches only the plan and `progress.md`.
- **Controller rulings read:** OQ1–OQ9 in `progress.md`.
- **Authorities read:**
  - issues #270, #269 and #271 (via `gh` as `robertwhiffin`, read-only);
  - spec §§5.2–5.5, 11.4, 12, 13.2, 14–17;
  - #269's plan and its 30 corrections;
  - #268's PLAN-CORRECTIONS (C6, C7, C10–C12, C18–C20, C23, C24, C27, C28);
  - the code at `a08389ec3`.
- **Probe:** one read-only in-memory SQLite probe. `select(func.current_timestamp())` returned `datetime(2026, 9, 26, 13, 29, 6)`: naive, at one-second resolution. No PostgreSQL probe was needed.

## Verdict: APPROVE WITH CORRECTIONS

| Severity | Count |
|---|---|
| Critical | 1 |
| Important | 6 |
| Minor | 16 |

The architecture holds. Rollback really is a thin caller of `_commit_locked_publication`:
- It uses one transaction.
- It adds no second publication core.
- It adds no second parent-audit writer.
- `_assign_locked_candidate` is a pure extraction. It is safe for all four `_write_locked_content` callers:
  - `save_editable_model_draft`, `:453`;
  - `save_draft_content`, `:512`;
  - `upgrade_draft_protected_assembly`, `:551`;
  - `upgrade_draft_schema_contract`, `:605`.
  It is also safe for the `staticmethod` wrappers in `test_agent_schema_overlay_postgres.py:485/650/787`, which still call the original.

The lock order is acyclic. I re-derived it against the following:
- #269's global order, including C29's unfiltered L2. Rollback skips L2, and both publication and rollback are serialized behind L0 `FOR UPDATE`.
- #268 C18 cleanup (L0 `FOR SHARE`, then DELETE).
- #268 C6 `record_verdict` (L3 only).
- #267's transaction 2 at `agent_test_workbench.py:1238–1242` (L0 `FOR SHARE`, then insert).
- #267's case writer (L2 `FOR UPDATE` only, `:199–211`).
- Conversation creation (release `FOR UPDATE` only, `conversation_pins.py:57–74`).
- Bootstrap (advisory lock, then L0 share, per #269 C2).

The history read is coherent under READ COMMITTED. The first-statement release set filters every later read. Releases, mappings and revisions are guarded, and no writer touches an existing release's links (M3 records that the links guard is conventional only).

The defects are in the fixtures, the tests and the sabotage predictions, and in two controller rulings (OQ5 and OQ9) that the plan predates. Every one can be fixed in `PLAN-CORRECTIONS.md`.

---

## Critical

### C1: every multi-publish SQLite fixture hits the core's same-second guard

**Plan lines:**
- 529 (Task 2: "SQLite, v1 backdated one hour … Build v2, v3 and v4 through #269's real `publish_draft`");
- 646 (Task 3: v2–v7 through `publish_draft`, then a rollback);
- 873 (Task 6: route fixture, "v1 backdating, with v2–v4 built through `publish_draft`");
- also 663–667 (the refusal fixtures) and 533 (v5).

**Evidence:**
- On SQLite, `select(func.current_timestamp())` returns a **naive value at one-second resolution** (probe above, and #269 plan :72).
- #269's core raises `GraphConfigurationIntegrityError("publication timestamp does not follow the active release interval")` when `timestamp <= as_utc_aware(release_row.effective_from)` (#269 plan :520–523, with C3/C4).
- Backdating v1 by one hour covers only the v1 → v2 step. The publishes of v3, v4, … v7, and then the rollback itself (v5 or v8), run in the same wall-clock second as the one before. So each raises the named error before any write.
- #269 never needed this, because none of its SQLite tests publishes twice. Its multi-publish tests are all PostgreSQL.
- As written:
  - Tasks 2, 3 and 6 fail at their GREEN step for a harness cause, or pass only when the run happens to cross a second boundary.
  - An implementer is likely to "fix" this with a `sleep(1)` per publish (slow and flaky) or by loosening the core's guard (a real regression in #269's code).

**Fix (corrections, blocking before Task 2):**
- Define one test helper for all three SQLite suites. It monkeypatches `src.services.graph_configuration_publication.database_transaction_timestamp` (the module-level name #269 C4 makes injectable) with a strictly increasing clock: `v1_from + n hours` for the n-th publication or rollback in the test.
- An alternative: before each publish, uniformly backdate every existing `graph_release` row's `effective_from`, `effective_to` and `published_at` by one hour. SQLite has no guards, so this is allowed. Keep `effective_to > effective_from`.
- Pin the helper with one assertion: the patched callable ran exactly once per publish or rollback.
- Keep the real clock on PostgreSQL.

**Cost if wrong:** three tasks stall at GREEN, or the core guard is weakened.

---

## Important

### I1: ruling OQ9 is not applied (preview must warn on removed endpoints, outside any lock)

**Plan lines:**
- 26 ("no endpoint-catalog or remote endpoint validation");
- 263 (the preview wire has no `warnings`);
- 536 (`test_preview_is_read_only_and_calls_no_model` uses `remote_endpoint_validator=_MustNotRun()` on the **preview**);
- 618 ("never the remote endpoint validator");
- 877 (Task 6 overrides `get_remote_endpoint_draft_validator` to raise for "every new route", which includes the preview);
- 1075 (OQ9 still open).

**Evidence:** OQ9 says:
- rollback (the POST) does **not** block on the remote check;
- the **preview** runs #266's bounded remote endpoint validation outside any lock, and shows a warning for each restored endpoint that no longer resolves.

As written, the plan pins the opposite with two tests and one reviewer sabotage.

**Fix:**
- **Task 2:** `preview_rollback` does its `FOR SHARE` read, commits, and only then calls `self._remote_endpoint_validator.validate(content)` for each of the seven historical contents. It collects `EndpointValidationFailure` into a new `warnings: tuple[DraftValidationIssue, ...]` (field `definitions.<key>.candidate.model.endpoint_name`, the catalog's code and message).
  - Warnings never set `blocked`.
  - If the validator is `None`, the check is skipped (the existing trusted-composition rule, `graph_configuration_draft.py:354–366`).
- **Tests:**
  - A fake validator that records `session.in_transaction()` and asserts it is `False`.
  - A failing fake gives a warning and `restorable is True`.
  - `restore_release` still never calls the validator (keep the must-not-run fake on the POST path, Task 3 :668).
- **Task 6:**
  - Add `"warnings": [{"field","code","message"}]` to the preview wire.
  - The no-remote-dependency test covers the four other routes, not the preview.
  - The reviewer sabotage stays on the rollback POST.
- **Task 7:** show a non-blocking warning panel in the preview.
- Close OQ9 in the plan's open questions.

**Cost if wrong:** the shipped preview contradicts the binding ruling, and an admin gets no warning before restoring a dead endpoint.

### I2: ruling OQ5 is not applied (numbered accessible names)

**Plan lines:**
- 27;
- 346–347 (Review Focus 5);
- 922–926 (the names `Inspect Graph Version N` and `Roll back to Graph Version N`);
- 939–940;
- 973;
- 977–978 ((f) and (g));
- 988 (Task 8 controller sabotage);
- 1071 (OQ5 still open).

**Evidence:** OQ5 says: "exact whole-name exemptions only; controls must use FIXED accessible names (e.g. 'Roll back to this version', 'Inspect this version') scoped by their row, with the version number in visible text or a description, never a numbered accessible name."

**Fix:**
- **Names:** use the fixed names `Inspect this version` and `Roll back to this version` inside each `release-history-row-<version>`. Show the version in visible row text, or `aria-describedby` pointing at the row's `Graph Version N` heading.
- **Tests query by row:** `within(getByTestId('release-history-row-12')).getByRole('button', { name: 'Roll back to this version', exact: true })`.
- **Review Focus 5 / (g):** rows 1 and 12 each contain exactly one such control. The page-level count of `Roll back to this version` equals the number of non-active rows.
- **(f)** becomes: no two **different** names are equal (case-insensitive) or substrings of one another. Repeats of the same fixed name across rows are allowed.
- Rewrite the component-test and Playwright steps (940, 973) and Task 8's controller sabotage to match.
- Close OQ5.

**Cost if wrong:** the UI ships a naming scheme the controller has ruled out, and it cannot be exempted exactly if a sweep is ever added to the page.

### I3: #269's own page test forbids the controls #270 adds, but the plan says #269's tests stay green

**Plan lines:**
- 329 ("`frontend/src/components/Admin/GraphRelease/*` … #269 tests stay green");
- 910–915 (Task 7 files omit `ReviewAndPublishPage.test.tsx`).

**Evidence:** #269's Task 6 page test (#269 plan :844) asserts "no `History` or `Rollback` control (they belong to #270)". No #269 correction changes that. #270 adds a `Release History` tab and rollback controls to that same page, so #269's assertion goes RED at Task 7 Step 4.

**Fix:**
- Add `frontend/src/components/Admin/GraphRelease/ReviewAndPublishPage.test.tsx` to Task 7's modified files.
- Replace #269's absence assertion with a positive one: exactly three tabs, in the order `Changes & Approvals`, `Definition Diff`, `Release History`.
- Record in corrections that this is the one deliberate edit to a #269 test, and that the controller must approve it at Task 0-B.

**Cost if wrong:** Task 7 cannot reach GREEN, or an implementer deletes #269's assertion without review.

### I4: Task 9's acceptance assertions are wrong for builder

**Plan lines:** 1005 (v3 also changes builder), 1009 (step 5), 1010 (step 6).

**Evidence:**
- Builder is changed only at n = 3. v4–v7 reuse v3's builder revision.
- So in step 5, v7's builder is v3's builder: `same_revision: true`, not false.
- In step 6, builder is clean and its restored hash equals its active hash, so its draft effect is `"unchanged"`, not `"reset"`.
- The step 11 wording ("architect and builder clean") is still true.

**Fix:**
- Step 5: architect `same_revision: false` with an exact `prompt_text` diff; builder and the other five `same_revision: true` with `field_diffs: []`.
- Step 6: `draft_effect == {"architect": "reset", "fixer": "kept", <other five>: "unchanged"}`.
- If a two-role reset is wanted, make **v5** change builder as well. Then v3's builder differs from v7's, and `builder: "reset"` holds. State which option is chosen.
- Re-check the reviewer sabotage prediction (reset-all) against the chosen fixture.

**Cost if wrong:** the acceptance test is RED at GREEN for a fixture error, or it is "fixed" by loosening an assertion.

### I5: Task 4's controller sabotage predicts the wrong RED

**Plan lines:** 784 (the pause rule: after "the first statement containing `FOR UPDATE`"), 814 (the sabotage and its prediction).

**Evidence:** with `exclusive=False`, the L0 statement renders `FOR SHARE OF graph_release, graph_draft` and contains no `FOR UPDATE`. So:
1. The winner's pause fires after **L1** (`SELECT … graph_draft_agent … FOR UPDATE`), not after L0.
2. The loser takes L0 `FOR SHARE` (granted), then blocks on L1 behind the winner. So `_await_blocked_by(loser, winner)` is **True**, and the predicted RED "at `_await_blocked_by` … not blocked" does not occur.
3. What actually happens:
   - The recorded-text assertion `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT` fails.
   - If the test runs past that, the winner's `UPDATE graph_release SET effective_to` waits on the loser's share lock while the loser waits on L1. That is `DeadlockDetected`.

   Plan line 28 says a sabotage that does not RED as predicted is a plan defect.

**Fix:** follow #269 C6's pattern:
- The pause fires after the first statement containing both `GRAPH_RELEASE` and `GRAPH_DRAFT` and a `FOR` clause, whatever its mode. Record its text.
- Assert `_await_blocked_by` first, then the text.
- Predicted RED: `_await_blocked_by` is False, because the loser's share lock is granted. Record `DeadlockDetected` as the expected secondary outcome if the test proceeds.
- Apply the same matcher to every Task 4 and Task 5 rollback pause.

**Cost if wrong:** the one sabotage meant to prove rollback's exclusive L0 is recorded as passing for a reason nobody predicted, or as a harness bug.

### I6: Task 8's controller sabotage targets an assertion that (a) does not contain

**Plan lines:** 972 ((a)), 988 (the sabotage).

**Evidence:**
- Line 988 predicts RED on "(a)'s 'active row has no rollback control' assertion", but (a) at line 972 asserts no such thing. That assertion exists only in the Task 7 Vitest (line 938), which Task 8 does not run.
- (a) also says "history renders **seven** versions with the `Restores Graph Version 3` badge on **v8**". A v8 means eight versions.

**Fix:**
- Add to (a): the active row contains zero rollback controls, and every non-active row contains exactly one (row-scoped, per I2).
- Correct "seven" to "eight".

**Cost if wrong:** the controller sabotage cannot go RED in the suite it names.

---

## Minor

### M1: router location

**Plan lines:** 24, 326, 865, 879, 1074.

**Evidence:** #269's plan creates `src/api/routes/graph_releases.py`, with its own `APIRouter` and the same prefix, and adds `include_router` in `main.py` (#269 plan :180, :767–769, :801–803). No #269 correction reverses this. So "the one existing admin router" (24) and "expected `agent_definitions.py`" (865) describe the wrong module. OQ8 already rules that #270 follows #269's module.

**Fix:**
- State that the expected module is `graph_releases.py`, and give I9 this location.
- Keep the "no `main.py` change" gate.
- Reword the registration test (879) as "registered once in `app.routes`".

### M2: stale #268 facts

**Plan lines:** 91, 294, 296, 847.

**Evidence:**
- #268 C18: cleanup is `AgentTestWorkbench.cleanup_unpublished_test_runs(self, session, *, per_case_limit)`. It owns its transaction, rejects `bool`, and its first statement is `_lock_current_parents(exclusive=False)`, i.e. **release and draft** `FOR SHARE`, not "`graph_draft FOR SHARE`".
- #268 C4: `record_verdict` has one principal and owns its transaction.
- The pause "after its `graph_draft FOR SHARE`" (847) must match `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT`.
- Line 296: #267's transaction-2 FK `KEY SHARE` falls on `compared_release_id`, which is transaction 1a's base (`agent_test_workbench.py:938–941`) and may be a closed release. It is not necessarily "the active release". The conclusion holds, because nobody locks a closed release.
- Cleanup can never delete a run linked to the source (`NOT EXISTS` link, FK RESTRICT; #268 C19f). So Task 5's cleanup tests are regression pins, not a race that could lose evidence. Say so, and pin the deleted set now from #268 C19(d): the window is over unprotected rows, and linked rows are removed before ranking.

**Fix:** update the four lines, and adopt the exact-set rule above in Task 5.

### M3: "links are insert-only or immutable" is conventional, not enforced

**Plan lines:** 285, 287, 454–455.

**Evidence:**
- `_install_graph_configuration_mutation_guards` guards `agent_definition_revision`, `graph_release_agent`, `graph_release` and `agent_test_run` (`database.py:1041–1108`).
- It installs **no** trigger on `graph_release_test_run`, and neither does #269 (C14 is on `agent_test_run`).
- History coherence still holds, because only publication and rollback insert links, and only for their own new release.

**Fix:** state that the rule is "no writer inserts, updates or deletes links of an existing release", cite the writers, and add it to Task 10's writer-by-writer table. Adding a guard is #269's call, not #270's.

### M4: the lock-free history read can be served from a stale identity map

**Plan line:** 457.

**Evidence:** `session.scalars(select(GraphRelease))` does not overwrite attributes already loaded in the session. A caller that loaded the active release earlier in the same session would see `effective_to=None` on two rows and raise "exactly one active". All planned callers use fresh sessions.

**Fix:** add `.execution_options(populate_existing=True)` to the first statement, as #268 C6 does for its run lock.

### M5: private import and exception mapping in `_load_source`

**Plan lines:** 436, 560–562.

**Evidence:**
- Task 1 says `_validate_complete_snapshot` is "reimplemented … not imported privately", but Task 2 calls `PersistedGraphReleaseLoader._validate_complete_snapshot` directly.
- The loader itself also maps `TypeError`/`ValueError` from that method (`persisted_graph_release.py:125–132`). `_load_source` catches only `GraphReleaseIncompleteError`, so those surface as an unmapped 500.

**Fix:** pick one approach. Either reuse Task 1's validation or state the private import. Map `TypeError`/`ValueError` to `GraphConfigurationIntegrityError`.

### M6: log contract ambiguities

**Plan lines:** 334–338, 878, 892.

**Evidence:**
- "Exactly one record per outcome, at INFO" conflicts with "logs at ERROR through `logger.exception`", and with the existing idiom `logger.exception("Persisted Graph Configuration is incomplete")` (`agent_definitions.py:521`), which would add a second record.
- The traceback can carry ids: #269's `GraphConfigurationIntegrityError` messages include revision ids (for example "reusable revision {id} …"). That breaks "no release id".

**Fix:** on `integrity_error`, emit exactly one `graph_release_rollback` record at ERROR with `error_class`, and no `exc_info`. Pin both with `caplog`.

### M7: Task 0 baseline omissions (the #269 C27 pattern repeats)

**Plan lines:** 381–392.

**Evidence:**
- The PostgreSQL loop omits `test_agent_schema_overlay_postgres`, `test_conversation_pin_migration_postgres` and `test_mixed_release_collaboration_acceptance_postgres`, all of which are in `integration-graph` (`test.yml:452, 456, 464`).
- The unit list omits `test_graph_definition_content_mapping.py`.
- Task 10 does list the PostgreSQL files.

**Fix:** add them to the loop.

### M8: the injected-failure test drops #269 C8 part 2's evidence assertions

**Plan line:** 743.

**Fix:** for every stage, also assert:
- that the release's `SELECT count(*) FROM graph_release_test_run` is 0 for v8;
- that the source runs' verdict columns are unchanged;
- that a GREEN retry produces exactly the v8 link set.

### M9: Task 3 is oversized

**Plan lines:** 632–770.

**Evidence:** one task and one review cover all of the following:
- a shared-file extraction with four callers;
- the rollback service;
- seven unit tests;
- six PostgreSQL tests, including five injection stages and runtime execution.

**Fix:** split it into 3a and 3b.
- **3a:** extraction, service and unit tests, with the existing sabotages.
- **3b:** the PostgreSQL file. Give it its own sabotage pair, e.g. controller `lock=False` in `restore_release`'s `_historical_evidence` call, which REDs the Task 4 verdict ordering test. Move that test here, or pick a 3b-local seam.

### M10: Task 5's reviewer sabotage is outside #270's diff and duplicates #269's Task 3

**Plan line:** 855.

**Fix:** keep it as an extra check if wanted. Assign a #270 seam as the reviewer target, e.g. dropping the `_lock_current_parents` handoff retry call path by calling a local single-scan copy in `restore_release`. Predicted RED: `test_publication_first_then_rollback_is_stale_and_not_v6`, with an integrity error.

### M11: the "matching mapping" refusal has no fixture in the v2–v7, architect-only seed

**Plan line:** 663.

**Fix:** specify it. For example, save architect back to v5's text, publish v8 (which reuses v5's architect revision), then restore v5 and expect `RollbackMatchesActive`.

### M12: issue code for `version_number < 1`

**Plan lines:** 242, 727.

**Evidence:** a value of 0 or below gets `strict_type`, which is the wrong code for an int that is out of range. The route maps these to 404 before the service anyway (`_is_storable_row_id`, `agent_definitions.py:1066`).

**Fix:** use `out_of_range` for a value below 1, and keep `strict_type` for a non-int or a `bool`.

### M13: user-visible consequences to disclose with OQ1

**Plan lines:** 97–114, 618.

**Evidence:**
- **(a)** A *kept* pending edit that already has an approved run stays `ready` after the rollback. #268 C11 readiness is keyed by hash and ignores `compared_release_id`, even though the approval was reviewed against v7's baseline.
- **(b)** Structural validation excludes `_endpoint_name_policy_validator`, which is local and makes no network call. So a historical endpoint name that fails today's policy is restored and reset into the draft. Every later save of that role then fails the policy until the endpoint is changed.

**Fix:** record both under the OQ1 disclosure. Either add the local policy validator to `_structural_issues`, or rule it out explicitly.

### M14: `_verify_rebased_draft` needs an ORM release row

**Plan line:** 728.

**Evidence:** `PublishedRelease.release` is an `ActiveReleaseSnapshot`, not a `GraphRelease` row, and `_snapshot_locked_workbench` reads `release.id` and `release.version_number` from the row it is given.

**Fix:** use `session.get(GraphRelease, published.release.release_id)`, and state it.

### M15: `compare_with_active` takes L0 `FOR SHARE` without needing it

**Plan line:** 287.

**Evidence:** a comparison has no draft component, yet its `FOR SHARE` on the release row stalls every conversation creation for the length of the call.

**Fix:** make the comparison lock-free, like history (first-statement active id, then filtered reads). Keep the preview's shared lock, since the draft effect needs it.

### M16: the page's "one request counter" and "one gate" are stated as fact

**Plan lines:** 7 and 27, against 89.

**Evidence:** line 89 admits that #269's plan is silent on both, yet lines 7 and 27 state them as fact.

**Fix:** make line 27 conditional on Task 0-B. If #269 has no counter, Task 7 adds exactly one on the page reducer, and records that addition in corrections.

---

## Checks that passed (no finding)

**Citations.** Every `a08389ec3` file:line citation in "Verified code facts" was re-read. All are accurate within one line, including:
- models `:159–537`;
- guards `:935–1121` and `:1098`;
- workbench `:179–361`;
- validators `:226–387`;
- `_write_locked_content` `:991–1029` (assignment `:999–1002`, audit `:1009–1011`);
- the loader `:91–204`;
- `conversation_pins.py:55`, `:66–74`, `:101–113`;
- the router `:97–112`, and `_is_storable_row_id` `:1066–1067`;
- `AgentRuntime` `:796–835`;
- the harness lines (`:245–253`, `:1284`, `:125–182`, `:375–385`, `:27/125/129/175`, `conftest.py:235`);
- the CI block `:447–473`;
- the forbidden-name fixture `:17–18`/`:31–37`, and both `toHaveLength(5)` sites (`:351`, `:1505`).

**I1–I12 against #269's plan plus its corrections.**

| Interface | Checked against |
|---|---|
| I1 | C3/C4 timestamp, `max+1`, close-before-insert, read-back, `_advance_locked_draft` |
| I2 | C1 `PublicationGap` |
| I3 | — |
| I4 | C29 unfiltered L2 plus re-select; C30 `run_kind` |
| I5 | Task 2 retry; `_lock_all_draft_agents` |
| I6 | C17/C10 note order and the 2000 cap |
| I7 | Task 5 |
| I8 | Task 6 names and test ids |
| I9 | C10: 200 |
| I10 | C14 |
| I11 | C2 |
| I12 | C24 helper homes |

All match, apart from the handler module (M1).

**The thin caller and the one writer.**
- It is one `session.begin()`.
- The core is called once. `_advance_locked_draft` runs once, inside the core.
- The reset uses only `_assign_locked_candidate`, under L0 exclusive and L1.
- No second parent writer and no second router or reducer is planned.

**The evidence rule.** Readiness (#268 C11) never reads links. It is keyed by hash and case version, and filtered on `run_kind='candidate'`.
- The Task 3 negative test binds both #268 readiness and `ApprovalEvidenceGate`.
- Task 10's final sabotage (the gate accepts runs linked to the active release) REDs it.

**Forbidden-action counts.** `ALLOWED_ACTION_NAMES` is unchanged by #270. With #268 C23 the length is 7, and with #269 C7 it is 8 (#268 C23's note). The plan defers the number to Task 0-B, which is correct.

**Sabotages that can go RED as predicted:**
- Task 1: both.
- Task 2: both. The reviewer's hash-compare flip turns architect into `kept`.
- Task 3: both.
- Task 5: the controller.
- Task 6: both.
- Task 7: both.
- Task 9: both.
- Task 10: the final sabotage.

**Scope.** All ten #270 acceptance criteria are covered. Nothing claims #269's publication gate or #271's bundle retention.

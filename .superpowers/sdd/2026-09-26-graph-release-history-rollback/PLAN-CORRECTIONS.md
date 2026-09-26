# PLAN-CORRECTIONS.md — this file overrides docs/superpowers/plans/2026-09-26-graph-release-history-rollback.md wherever they differ.

- **Source:** `plan-review-1.md` (APPROVE WITH CORRECTIONS; 1 Critical, 6 Important, 16 Minor), controller rulings OQ1–OQ9 in `progress.md`, and the binding corrections in this file's commissioning prompt.
- **Plan at:** `fbe7e1c82` on `plan/release-history-rollback-270`. **Code base:** `a08389ec3`. `git diff --stat a08389ec3 HEAD -- src tests frontend packages` is empty.
- **Authority:** the plan file stays unchanged. Where they differ, this file wins. Attach it to every implementer and reviewer brief, as plan line 15 requires. The plan's Task 0 Step 2 prescribes a different first line for this file; the first line above supersedes it.
- **Numbering:** Correction 1 = C1, Corrections 2–7 = I1–I6, Corrections 8–23 = M1–M16. Each states the plan line(s) overridden, the evidence (re-verified against code where noted), the replacement instruction, any replacement sabotage target, the phase it binds, and its cost if wrong.
- **Phases:** **Phase A** = in force before Task 1 dispatches. **Phase B** = in force after #268 and #269 are integrated locally, before the named task dispatches.

---

## Critical

### Correction 1 (C1) — SQLite multi-publish fixtures hit the same-second guard

**Overrides:** plan lines 529 (Task 2: "v2, v3 and v4 through #269's real `publish_draft`"), 533 (v5), 646 (Task 3: v2–v7 through `publish_draft`), 663–667 (refusal fixtures), 873 (Task 6 route fixture, "v2–v4 built through `publish_draft`").

**Evidence:** On SQLite, `select(func.current_timestamp())` returns a naive value at one-second resolution (plan line 72; confirmed by the review probe). #269's core raises `GraphConfigurationIntegrityError("publication timestamp does not follow the active release interval")` when `timestamp <= as_utc_aware(release_row.effective_from)` (#269 plan :520–523 as corrected by C3/C4). Backdating v1 by one hour covers only the v1 → v2 step; v3, v4, …, v7, and the rollback itself (v5 or v8), run in the same wall-clock second as the preceding publish and each raises before any write.

**Instruction:**
1. Define one test helper used by all three SQLite suites (Tasks 2, 3 and 6). It monkeypatches `src.services.graph_configuration_publication.database_transaction_timestamp` (the module-level name #269 C4 creates) with a strictly increasing clock: `v1_from + n * timedelta(hours=1)` for the n-th publication or rollback call, where `v1_from = as_utc_aware(<v1.effective_from read back in a fresh session>)`. Never use `time.sleep` or per-publish `sleep(1)`.
2. Pin the helper with one assertion per test: `assert patched_callable.call_count == <expected_publish_count>` at the end of each setup block.
3. Provide one GREEN demonstration test (placed in Task 2's unit file) that exercises v2–v8 in sequence on SQLite and asserts all eight releases exist with no `GraphConfigurationIntegrityError`.
4. Keep the real clock on every PostgreSQL test (no monkeypatch).

**Sabotage:** n/a (the finding corrects the test scaffolding, not a production seam).

**Binds:** Phase B, blocking before Task 2. The helper must exist in the test suite before Task 2, Task 3 or Task 6 is dispatched.

**Cost if wrong:** Tasks 2, 3 and 6 stall at GREEN for a harness cause, or an implementer weakens #269's core interval guard to make the tests pass.

---

## Important

### Correction 2 (I1) — OQ9 ruling not applied: the preview runs remote endpoint validation outside its lock

**Overrides:** plan lines 26 ("no endpoint-catalog or remote endpoint validation"), 263 (preview wire has no `warnings`), 536 (`test_preview_is_read_only_and_calls_no_model` uses `_MustNotRun()` on the **preview**), 618 ("never the remote endpoint validator"), 877 (Task 6 overrides `get_remote_endpoint_draft_validator` to raise for "every new route", including the preview), 1075 (OQ9 still open).

**Evidence:** OQ9 ruling (progress.md): "rollback does NOT block on the remote endpoint check (no network call under the publication lock), but the rollback PREVIEW runs #266's bounded remote endpoint validation outside any lock and shows a warning for any restored endpoint that no longer resolves." As written, the plan pins the opposite: two tests and one route sabotage assert the preview never calls the validator.

**Instruction:**
1. **Task 2 — `preview_rollback` implementation:** after the `FOR SHARE` transaction commits (and only then), call `self._remote_endpoint_validator.validate(content)` for each of the seven historical contents. Collect `EndpointValidationFailure` results into a new `warnings: tuple[DraftValidationIssue, ...]` field on `RollbackPreview`, with `field="definitions.<key>.candidate.model.endpoint_name"`, the catalog's error code (`endpoint_unavailable` or `endpoint_url_not_allowed`), and no endpoint URL text in the message. Warnings never set `blocked`. If `self._remote_endpoint_validator` is `None`, skip the check (the trusted-composition rule at `graph_configuration_draft.py:354–366`).
2. **Task 2 — replace plan line 536's test:** replace `test_preview_is_read_only_and_calls_no_model` with two tests:
   - A fake validator that records `session.in_transaction()` at call time; assert it is `False`. This proves the validator runs outside the transaction.
   - A failing fake (returns one `EndpointValidationFailure` per role) gives `len(preview.warnings) == 7` and `preview.restorable is True` (warnings do not block).
3. **Task 3 — `restore_release`:** still never calls the remote validator. Keep plan line 668's `_MustNotRun()` on the POST path unchanged.
4. **Task 6 — route tests and wire:**
   - Add `"warnings": [{"field": str, "code": str, "message": str}]` to the rollback-preview wire (plan line 263 and the HTTP contract table for the `GET …/rollback-preview` response).
   - The "no model or remote work" route test (plan line 877) covers the list, detail, comparison and rollback POST routes, not the preview route. Reword accordingly.
   - The reviewer sabotage (plan line 899: inject the remote validator into the rollback handler) is unchanged.
5. **Task 7:** add a non-blocking warning panel to the rollback preview UI. Close OQ9 in the plan's open-questions section.

**Replacement sabotage target:** for the Task 2 reviewer, the old must-not-run fake on the preview becomes: construct with a fake validator that returns one failure; assert `preview.restorable is True` and `len(preview.warnings) == 7`. The rollback-POST must-not-run test (Task 3 :668) is unchanged.

**Binds:** Phase B, blocking before Task 2.

**Cost if wrong:** the shipped preview contradicts the binding ruling; an admin gets no warning before restoring a removed endpoint.

---

### Correction 3 (I2) — OQ5 ruling not applied: accessible names must be fixed, not numbered

**Overrides:** plan lines 27 (stable names), 346–347 (Review Focus 5: "Roll back to Graph Version N"), 922–926 (per-row button names `Inspect Graph Version N` and `Roll back to Graph Version N`), 939–940, 973, 977–978 (Playwright checks (f) and (g)), 1071 (OQ5 still open).

**Evidence:** OQ5 ruling (progress.md): "exact whole-name exemptions only; controls must use FIXED accessible names (e.g. 'Roll back to this version', 'Inspect this version') scoped by their row, with the version number in visible text or a description, never a numbered accessible name." As written, the plan uses numbered names at every test site.

**Instruction:**
1. **Accessible names:** use the fixed strings `Inspect this version` and `Roll back to this version` on the buttons inside each `release-history-row-<version>`. Show the version number in the row's visible text or in an `aria-describedby` pointing at the row's `Graph Version N` heading.
2. **Tests query by row:** `within(screen.getByTestId('release-history-row-12')).getByRole('button', { name: 'Roll back to this version', exact: true })`.
3. **Review Focus 5 (plan lines 346–347):** rows 1 and 12 each contain exactly one rollback control queried by the fixed name within the row. The page-level count of elements with accessible name `Roll back to this version` equals the number of non-active rows.
4. **Check (f):** no two **different** accessible names on the page are equal (case-insensitive) or proper substrings of one another. Repeats of the same fixed name across different rows are allowed.
5. **Check (g):** `within(getByTestId('release-history-row-1')).getByRole('button', { name: 'Roll back to this version', exact: true })` and the same for row 12 each resolve to exactly one element. Replace plan lines 977–978.
6. Rewrite component-test and Playwright steps at plan lines 939–940 and 973. Close OQ5.

**Replacement sabotage target (Task 8 controller):** render `Roll back to this version` on the active row too. Predicted RED: Correction 7's new assertion in (a) "the active row contains zero rollback controls" (see Correction 7).

**Binds:** Phase B, blocking before Task 7.

**Cost if wrong:** the UI ships a naming scheme the controller has ruled out, and no exact-whole-name exemption can cover numbered names.

---

### Correction 4 (I3) — #269's page test forbids the controls #270 adds; Task 7 must update it

**Overrides:** plan lines 329 ("#269 tests stay green") and 910–915 (Task 7's file list, which omits `ReviewAndPublishPage.test.tsx`).

**Evidence:** #269's Task 6 page test (#269 plan :844) asserts "no `History` or `Rollback` control (they belong to #270)". No #269 correction removes that assertion. #270 adds a `Release History` tab and rollback controls to that same page, so the assertion goes RED at Task 7 Step 4.

**Instruction:**
1. Add `frontend/src/components/Admin/GraphRelease/ReviewAndPublishPage.test.tsx` to Task 7's modified-files list (plan lines 910–915).
2. Replace #269's absence assertion with a positive one: exactly three tabs present, in order `Changes & Approvals`, `Definition Diff`, `Release History`.
3. Record in this correction that this is the **one deliberate edit to a #269 test**. The controller must confirm at Task 0-B that the test exists in #269's integrated code with the expected assertion text before dispatching Task 7.

**Sabotage:** n/a.

**Binds:** Phase B, blocking before Task 7.

**Cost if wrong:** Task 7 cannot reach GREEN, or an implementer silently deletes #269's assertion without controller approval.

---

### Correction 5 (I4) — Task 9 step 5 and step 6 expected values for builder are wrong

**Overrides:** plan lines 1005 ("v3 also changes builder"), 1009 (step 5 comparison: builder `same_revision: false`), 1010 (step 6 draft_effect: builder `"reset"`).

**Evidence:** Builder is changed only at n = 3 in the Task 9 seed (step 1: "for n in 2..7, PUT an architect draft +n"). v4–v7 reuse v3's builder revision. Therefore at step 5: v7's builder revision id equals v3's builder revision id — `same_revision: true`. At step 6: the draft's builder candidate hash equals v3's builder hash, which equals v7's builder hash; by the Q7 ruling a clean role whose restored hash equals the active hash maps to `"unchanged"`, not `"reset"`.

**Instruction:**
1. **Step 5 comparison (plan line 1009):** architect `same_revision: false` with an exact `prompt_text` diff. Builder and the other five roles have `same_revision: true` and `field_diffs: []`. State the derivation rule: `same_revision` is true when the revision ids are equal, regardless of draft state.
2. **Step 6 draft_effect (plan line 1010):** `draft_effect == {"architect": "reset", "fixer": "kept", <other five including builder>: "unchanged"}`. The implementer must derive all seven values from the Q7 ruling against the fixture; never hard-code a table. State the rule for each role.
3. **Step 11** ("architect and builder clean") remains accurate: both are clean after rollback.
4. If two-role reset is needed for a richer test, change the fixture to make **v5** also change builder. Then v3's builder differs from v7's and `builder: "reset"` holds. State the chosen option explicitly; do not leave it ambiguous.
5. Recheck the reviewer sabotage (reset-all): under reset-all, builder would show `"reset"` instead of `"unchanged"`, which also REDs. Record this as an additional RED confirmation, not a conflict.

**Sabotage:** reviewer sabotage (reset-all) REDs on `fixer` being `"reset"` instead of `"kept"` (the pending fixer edit is silently overwritten). Under the corrected fixture, `builder: "unchanged"` also goes RED under reset-all.

**Binds:** Phase B, blocking before Task 9.

**Cost if wrong:** the acceptance test is RED at GREEN for a fixture error, or an assertion is loosened to pass.

---

### Correction 6 (I5) — Task 4's pause predicate and predicted RED are wrong for `exclusive=False`

**Overrides:** plan lines 784 ("after the first statement containing `FOR UPDATE`") and 814 (controller sabotage predicted RED: "`_await_blocked_by` … not blocked").

**Evidence:** With `exclusive=False`, `_lock_current_parents` renders `FOR SHARE OF graph_release, graph_draft`, which contains no `FOR UPDATE`. A pause keyed on "`FOR UPDATE`" never fires under the sabotage. Under the sabotage (`exclusive=False`), the loser takes L0 `FOR SHARE` (granted, not blocked), so `_await_blocked_by(loser, winner)` is False. Following #269 C6's pattern.

**Instruction:**
1. **Pause matcher (all Task 4 and Task 5 rollback pauses):** fire after the blocker thread's first statement whose upper-cased, normalized text contains **both** `GRAPH_RELEASE` and `GRAPH_DRAFT` and a `FOR` clause — whatever the lock mode. Record that statement's normalized text.
2. **Assertion order in every ordering test:** (a) assert `_await_blocked_by(waiter=loser_pid, blocker=winner_pid)` first; (b) then assert the recorded text contains `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT` (proving exclusive mode in the non-sabotage path).
3. **Updated sabotage predicted RED (plan line 814):** `_await_blocked_by` is False, because the loser's `FOR SHARE` is granted immediately. Record `DeadlockDetected` as the expected secondary outcome if the test proceeds past that assertion.
4. Apply the corrected matcher to every rollback pause in Task 5 as well.

**Sabotage (controller, plan line 814):** `exclusive=False`. Predicted RED: `_await_blocked_by` is False. If the test proceeds, `DeadlockDetected` follows.

**Binds:** Phase B, blocking before Task 4.

**Cost if wrong:** the sabotage passes for an unrelated reason; the exclusive L0 is never proved.

---

### Correction 7 (I6) — Task 8 controller sabotage targets an assertion that does not exist in (a), and (a)'s version count is wrong

**Overrides:** plan lines 972 ((a)'s assertion text) and 988 (controller sabotage, which predicts RED on "(a)'s 'active row has no rollback control' assertion").

**Evidence:**
- Plan line 988 predicts RED on "(a)'s 'active row has no rollback control' assertion", but (a) at line 972 asserts no such thing. That assertion exists only in the Task 7 Vitest (line 938), which Task 8 does not run.
- Line 972 says "history renders **seven** versions … on **v8**". A fixture with versions v1–v8 has eight versions.

**Instruction:**
1. **Add to check (a) (plan line 972):** after the existing assertions, assert that the active row (v8) contains zero rollback controls, and every non-active row (v1–v7) contains exactly one rollback control — queried with the fixed name `Roll back to this version` within the row, per Correction 3.
2. **Correct the count in (a):** "history renders **eight** versions with the `Restores Graph Version 3` badge on v8."
3. The controller sabotage (plan line 988: render `Roll back to this version` on the active row too) now correctly targets (a)'s new assertion "the active row contains zero rollback controls". Predicted RED: (a) observes one rollback control on v8.

**Sabotage (controller):** render `Roll back to this version` on the active row. Predicted RED: (a)'s "active row contains zero rollback controls" assertion.

**Binds:** Phase B, blocking before Task 8.

**Cost if wrong:** the controller sabotage cannot go RED in the suite it names.

---

## Minor

### Correction 8 (M1) — router location: #269 C31 requires handlers on the existing admin prefix

**Overrides:** plan lines 24 ("the one existing admin router"), 326 ("or #269's release-route module per Task 0-B"), 865 ("expected `src/api/routes/agent_definitions.py`"), 879 (registration assertion), 1074 (OQ8 still open).

**Evidence:** #269's plan creates `src/api/routes/graph_releases.py` with its own `APIRouter` and the same prefix, plus `include_router` in `main.py` (#269 plan :180, :767–769, :801–803). No #269 correction prior to C31 reverses this. OQ8 rules #270 follows #269's module. However, #269 C31 (added after the #270 plan was written) rules that all release handlers must register on the **existing** admin prefix `/api/admin/agent-definitions` with the same router-level `require_admin` and `require_draft_write_principal`, no second `APIRouter` with its own prefix, and no `main.py` change. The `graph_releases.py` module may exist as a code-organization file but it registers on the existing router.

**Instruction:**
- At Task 0-B, re-probe the exact registration shape per #269 C31.
- Plan line 865: change "expected `agent_definitions.py`" to "expected `graph_releases.py` (or wherever #269 C31 puts them) on the existing admin prefix."
- Plan line 879: reword as "registered exactly once in `app.routes` at the expected prefix `/api/admin/agent-definitions`."
- Confirm no `main.py` change. Close OQ8.

**Sabotage:** n/a.

**Binds:** Phase A (informational for Task 0-B). Blocking before Task 6 dispatch.

**Cost if wrong:** two admin routers whose auth dependencies can drift, or Task 6 adds a `main.py` change that #269 C31 forbids.

---

### Correction 9 (M2) — stale #268 cleanup facts at plan lines 91, 294, 296 and 847

**Overrides:** plan lines 91 (cleanup signature and lock), 294 ("cleanup takes L0-draft `FOR SHARE`"), 296 ("the active release"), 847 ("after its `graph_draft FOR SHARE`").

**Evidence:** From #268 PLAN-CORRECTIONS.md (`.worktrees/issue-268-plan/.superpowers/sdd/2026-09-23-test-evidence-readiness/PLAN-CORRECTIONS.md`):
- **C18:** `AgentTestWorkbench.cleanup_unpublished_test_runs(self, session, *, per_case_limit: int)`. First statement: `_lock_current_parents(exclusive=False)` — i.e., `FOR SHARE OF graph_release, graph_draft`, not draft alone.
- **C19(d):** Protected rows are removed before ranking; the DELETE retains the latest 20 unprotected candidate runs per case row plus every protected row.
- **C19(f):** Linked exclusion is `NOT EXISTS (SELECT 1 FROM graph_release_test_run ...)`, backed by FK RESTRICT. Cleanup can **never** delete a run linked to any release (FK RESTRICT prevents it and the NOT EXISTS guards it explicitly).
- **Plan line 296:** #267's transaction-2 FK `KEY SHARE` is on `compared_release_id`, which is the base release at run time — it may be a closed release, not necessarily the active one.

**Instruction:**
1. Plan line 91: `cleanup_unpublished_test_runs(self, session, *, per_case_limit: int = 20)`. First statement: `_lock_current_parents(exclusive=False)`, which takes `FOR SHARE OF graph_release, graph_draft`.
2. Plan line 294: "cleanup takes L0 share of **both** parents (release and draft), then L3 row locks."
3. Plan line 296: replace "the active release" with "the base release (which may be a closed release)."
4. Plan line 847: the pause matcher must match `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT` (not `FOR SHARE` of draft alone). Apply Correction 6's general matcher.
5. Task 5 cleanup-scenario description: state that cleanup can never delete a linked run (FK RESTRICT plus NOT EXISTS guard), so the ordering tests are **regression pins** for lock-order proof, not evidence-loss races.

**Sabotage:** n/a.

**Binds:** Phase B, Task 5, non-blocking before Task 4.

**Cost if wrong:** incorrect lock-order analysis; and a cleanup test that claims to exercise a race that physically cannot happen.

---

### Correction 10 (M3) — "links are insert-only or immutable" is conventional, not schema-enforced

**Overrides:** plan lines 285, 287 ("insert-only or immutable") and 454–455.

**Evidence:** `_install_graph_configuration_mutation_guards` guards `agent_definition_revision`, `graph_release_agent`, `graph_release` and `agent_test_run` (`database.py:1041–1108`). It installs no trigger on `graph_release_test_run`, and neither does #269 C14.

**Instruction:**
1. Change the wording at plan lines 285, 287 and 454–455 to: "the rule is that **no writer inserts, updates or deletes links of an existing release**. The writers (`link_release_evidence` for publication; `_historical_evidence`+`link_release_evidence` for rollback) only insert links for their own new release. This rule is conventional; no DDL trigger enforces it."
2. Note this in Task 10's writer-by-writer table. Adding a guard trigger on `graph_release_test_run` is #269's decision.

**Sabotage:** n/a.

**Binds:** Phase B, Task 10 (whole-slice review), non-blocking for implementation tasks.

**Cost if wrong:** a reviewer expects a trigger that does not exist; a violation of the insert-only rule is invisible to the constraint system.

---

### Correction 11 (M4) — `list_release_history` must add `populate_existing=True` to its first statement

**Overrides:** plan line 457 (`releases = list(session.scalars(select(GraphRelease).order_by(…)))`).

**Evidence:** `session.scalars(select(GraphRelease))` does not overwrite attributes already in the session's identity map. A caller that previously loaded the active release in the same session would see `effective_to=None` on two rows and raise "exactly one active". All planned callers use fresh sessions, but this is a latent fragility. Matching #268 C6's pattern for its run lock.

**Instruction:** The first statement of `list_release_history` becomes:
```python
releases = list(session.scalars(
    select(GraphRelease).order_by(GraphRelease.version_number.desc())
    .execution_options(populate_existing=True)
))
```

**Sabotage:** n/a.

**Binds:** Phase A (Task 1 code template), blocking for Task 1 brief.

**Cost if wrong:** a test that pre-loads the active release before calling `list_release_history` sees two rows with `effective_to=None` and raises a spurious integrity error.

---

### Correction 12 (M5) — `_load_source` inconsistency: private import vs. reimplementation, and unmapped exceptions

**Overrides:** plan lines 436 (Task 1: "reimplemented … not imported privately") and 560–562 (Task 2's `_load_source` template, which calls `PersistedGraphReleaseLoader._validate_complete_snapshot` directly).

**Evidence:**
- Plan line 436 says the validation is "reimplemented through the same `validate_definition_hash`, not imported privately". Task 2's code template (lines 559–563) calls `PersistedGraphReleaseLoader._validate_complete_snapshot` directly — a private import.
- The loader internally maps `TypeError`/`ValueError` from `_validate_complete_snapshot` (`persisted_graph_release.py:125–132`). `_load_source` catches only `GraphReleaseIncompleteError`, so `TypeError`/`ValueError` surface as an unmapped 500.

**Instruction:**
1. Pick one approach and state it before dispatching Task 2:
   - **Option A (private import):** call `PersistedGraphReleaseLoader._validate_complete_snapshot` directly and also catch `TypeError` and `ValueError`, re-raising as `GraphConfigurationIntegrityError("historical release is invalid: {e}")`.
   - **Option B (reimplementation):** call `validate_definition_hash` on each mapping row directly, as `read_release_detail` does in Task 1, and skip the loader entirely in `_load_source`.
2. Whichever option is chosen, add a unit test in Task 2: monkeypatch the validation step to raise `TypeError`; assert that `_load_source` raises `GraphConfigurationIntegrityError`, not a bare `TypeError`.

**Sabotage:** n/a.

**Binds:** Phase B, blocking before Task 2.

**Cost if wrong:** a malformed historical release returns 500 with a raw `TypeError` traceback; or the implementation contradicts the stated interface contract.

---

### Correction 13 (M6) — `integrity_error` log must not include a traceback

**Overrides:** plan lines 334–338 ("logs at ERROR through `logger.exception`, the existing idiom"), 878 and 892 (`caplog` assertions referencing this).

**Evidence:**
- `logger.exception(...)` passes `exc_info=True` by default and emits a traceback. Plan line 338 calls this "the existing idiom", but OQ7 ruling (progress.md) says "Logs carry only the outcome code and role key names." A traceback includes class name and call-stack lines — not key names.
- `logger.exception("Persisted Graph Configuration is incomplete")` at `agent_definitions.py:521` would add a second log record with a traceback, contradicting "exactly one record per outcome."
- Binding: "log contract carries outcome code and role key names only. Where it conflicts with `logger.exception`, rule class-name-only logging and no traceback, matching #267's R1/I-2 precedent."

**Instruction:**
1. On `integrity_error`, emit exactly one `graph_release_rollback` record at ERROR using `logger.error("graph_release_rollback", extra={"outcome": "integrity_error", "agent_keys": [], "error_class": type(exc).__name__})`. Do **not** use `logger.exception` (which adds `exc_info=True`).
2. Update `caplog` assertions (plan lines 878, 892): assert `record.levelname == "ERROR"`, `record.message == "graph_release_rollback"`, `record.exc_info is None`, and `record.extra["error_class"] == "GraphConfigurationIntegrityError"`.

**Sabotage:** n/a.

**Binds:** Phase B, Task 6, non-blocking before earlier tasks.

**Cost if wrong:** the log emits a traceback that violates "key names only"; or `caplog` assertions pass vacuously without checking `exc_info`.

---

### Correction 14 (M7) — Task 0 Step 3 baseline loop omits three integration files and one unit file

**Overrides:** plan lines 381–392 (the PostgreSQL and unit baseline lists).

**Evidence:** The following are in the `integration-graph` CI job (`.github/workflows/test.yml:452, 456, 464`) but absent from the Task 0 Step 3 loop:
- `test_agent_schema_overlay_postgres.py` (:452)
- `test_conversation_pin_migration_postgres.py` (:456)
- `test_mixed_release_collaboration_acceptance_postgres.py` (:464)
The unit list also omits `test_graph_definition_content_mapping.py`. Task 10 does list the PostgreSQL files.

**Instruction:**
1. Add all three PostgreSQL files to the Task 0 Step 3 loop, each as a separate command with zero skips recorded per file.
2. Add `tests/unit/test_graph_definition_content_mapping.py` to the unit list.
3. Task 10's PostgreSQL matrix already includes these files; it stays correct.

**Sabotage:** n/a.

**Binds:** Phase A (Task 0 Step 3, before Task 1's baseline is recorded). Non-blocking for Task 1 implementation.

**Cost if wrong:** a regression in schema overlays, pin migration or collaboration acceptance goes unseen until CI.

---

### Correction 15 (M8) — the injected-failure test must assert evidence invariants at every stage

**Overrides:** plan line 743 (the injected-failure test assertions).

**Evidence:** Plan line 743 asserts artefact tuples equal "before" exactly and that a retry produces version 8. This matches #269 C8 part 1. It omits #269 C8 part 2's evidence assertions.

**Instruction:** For every injection stage in `test_injected_failure_rolls_back_every_row` (Task 3b per Correction 16), also assert:
1. `SELECT count(*) FROM graph_release_test_run WHERE graph_release_id = <new_id>` is 0 (no v8 evidence rows survived).
2. The source runs' verdict columns (all four: `verdict`, `verdict_reviewer`, `verdict_at`, `verdict_notes`) are byte-identical to before the injected failure.
3. An un-injected retry with the same `lock_version` produces exactly the expected v8 link set (`historical_restore`, `source_release_id == v3.id`).

**Sabotage:** n/a.

**Binds:** Phase B, Task 3b (blocking for that task's GREEN step).

**Cost if wrong:** AC5 ("no conversation observes a partial release") is untested for the evidence-row path.

---

### Correction 16 (M9) — Task 3 is oversized; split into 3a (extraction, service, unit) and 3b (PostgreSQL)

**Overrides:** plan lines 632–770 (single Task 3 boundary).

**Evidence:** Task 3 covers a shared-file extraction, the rollback service, seven unit tests, five injection stages, and runtime execution — an overly wide review surface.

**Instruction:**
1. **Task 3a:** `_assign_locked_candidate` extraction, `restore_release`, `_validate_rollback_request`, `_verify_rebased_draft`, and all SQLite unit tests. Use the existing sabotages from plan lines 766–767.
2. **Task 3b:** `tests/integration/test_graph_release_rollback_postgres.py` only. Give Task 3b its own controller sabotage seam distinct from 3a's: pass `source_release_id=release_row.id` (the active release) to `_historical_evidence` instead of `source.id`. Predicted RED: `test_v8_restores_v3_with_exact_intervals_mappings_and_evidence`, which observes v7's run links (or zero links if v7 has none) instead of v3's.
3. Tasks 3a and 3b dispatch sequentially; 3b requires 3a's commit as its base.

**Replacement sabotage (Task 3b controller):** pass `source_release_id=release_row.id`. Predicted RED: evidence link sets name the active release's runs.

**Binds:** Phase B, blocking before Task 3a dispatch.

**Cost if wrong:** the review covers too much at once; the sabotage scope is unclear between extraction and PostgreSQL steps.

---

### Correction 17 (M10) — Task 5's reviewer sabotage is outside #270's diff

**Overrides:** plan line 855 (reviewer: set `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1`).

**Evidence:** `MAX_ACTIVE_RELEASE_LOCK_SCANS` is at `conversation_pins.py:55`, owned by #259/#260. Modifying it in Task 5's reviewer sabotage leaks a change outside #270's diff and requires a non-trivial restore-and-diff step that the controller cannot cleanly verify.

**Instruction:** Replace the reviewer sabotage in Task 5 with a #270-owned seam. For example: in `restore_release`, drop the `_lock_current_parents` handoff-retry call by substituting a local single-scan call directly (bypassing the retry loop). Predicted RED: `test_publication_first_then_rollback_is_stale_and_not_v6`, which now observes `GraphConfigurationIntegrityError` (stale snapshot) instead of `PublicationConflict`. Keep `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1` as an informational verification note only.

**Replacement sabotage (Task 5 reviewer):** drop the `_lock_current_parents` retry. Predicted RED: `test_publication_first_then_rollback_is_stale_and_not_v6` with `GraphConfigurationIntegrityError`.

**Binds:** Phase B, Task 5, non-blocking.

**Cost if wrong:** the reviewer sabotage produces a diff outside #270's scope; the whole-branch review flags the stale change.

---

### Correction 18 (M11) — the `matches_active` refusal fixture is unspecified

**Overrides:** plan line 663 ("a matching mapping gives `RollbackMatchesActive`" with no fixture detail).

**Evidence:** In the v2–v7 architect-only seed, restoring v7 gives `source_is_active`, not `matches_active`. There is no published state where a non-active version's seven revision ids equal the active mapping unless constructed explicitly.

**Instruction:** Specify the fixture:
1. After publishing v2–v7 (architect +2 … +7), save architect back to its v5 text and publish v8 via `publish_draft` (with `_NoEvidenceGate`). v8's architect revision equals v5's; all other roles are shared.
2. `preview_rollback(version_number=5)` gives `blocked == "matches_active"`.
3. `restore_release(version_number=5, ...)` returns `RollbackMatchesActive`.
4. Assert artefact tuples are unchanged.

Record this fixture choice in corrections before Task 3a is dispatched.

**Sabotage:** n/a.

**Binds:** Phase B, Task 3a (refusal unit tests), blocking for that task's RED step.

**Cost if wrong:** the `matches_active` test cannot be built, or an incorrect fixture is invented.

---

### Correction 19 (M12) — `version_number < 1` must use `out_of_range`, not `strict_type`

**Overrides:** plan lines 242 ("`PublicationRejected` issue `version_number/strict_type`") and 727 ("`_validate_rollback_request` prepends a `version_number` `strict_type` issue for … a value below 1").

**Evidence:** `strict_type` is the code for a value of the wrong Python type (string, bool, float). A value of 0 or −1 is an `int` of the wrong range; `out_of_range` is the correct code. The route maps these to 404 via `_is_storable_row_id` before the service, but the unit test must assert the correct code.

**Instruction:**
1. `_validate_rollback_request` emits `DraftValidationIssue("version_number", "out_of_range", "version_number must be a positive integer.")` for an `int` value ≤ 0.
2. It emits `DraftValidationIssue("version_number", "strict_type", "version_number must be an integer.")` for a non-`int` value (including `bool`).
3. Update plan line 242's description and plan line 727's instruction to match.
4. Unit tests parametrize over `version_number=0`, `version_number=-1`, `version_number=True`, `version_number="3"` and assert the exact code per case.

**Sabotage:** n/a.

**Binds:** Phase B, Task 3a (request validation), non-blocking.

**Cost if wrong:** wrong error code in the 422 body; a unit assertion that accepts the wrong code.

---

### Correction 20 (M13) — two user-visible rollback consequences must be disclosed under OQ1

**Overrides:** plan lines 97–114 (Q7 ruling table) and 618 ("never the remote endpoint validator" log claim is incomplete).

**Evidence:**
1. **(a) Kept pending edit that already has an approved run stays `ready` after rollback.** #268 C11's readiness is keyed by `(candidate_hash, case_version, run_kind='candidate')` and ignores `compared_release_id`. A pending edit whose run was approved against the pre-rollback base (v7) remains `ready` and the next publish will succeed — even though the approval reviewed v7's baseline, not the new v8 baseline.
2. **(b) A historical endpoint name that fails today's local policy is restored silently.** `_endpoint_name_policy_validator` is in `_save_local_validators` (`graph_configuration_draft.py:380–387`), not in `local_candidate_validators` or `post_stale_validators`. `_structural_issues` uses only the latter two tuples, so the local policy check does not run during rollback. A historical endpoint name that now violates the policy is restored successfully; every subsequent save of that role then fails the policy until the endpoint is changed.

**Instruction:**
1. Add both consequences to the OQ1 user-confirmation disclosure (plan lines 97–114).
2. Under `_structural_issues` (plan lines 565–575): state explicitly that the endpoint name policy (`_endpoint_name_policy_validator`) is **not** included. Record the consequence at (b). Before Task 2 is dispatched, decide: either add `_endpoint_name_policy_validator` to the `local_candidate_validators` tuple in `_structural_issues`, or rule it out and document the consequence. Record the decision in corrections.

**Sabotage:** n/a.

**Binds:** Phase B, blocking before Task 2 (affects `_structural_issues` scope).

**Cost if wrong:** an admin restores a release with a now-invalid endpoint name with no warning; every subsequent save of that role fails validation.

---

### Correction 21 (M14) — `_verify_rebased_draft` receives an `ActiveReleaseSnapshot`, not a `GraphRelease` row

**Overrides:** plan line 728 ("`_verify_rebased_draft` re-snapshots through `_snapshot_locked_workbench(session, release=<new release row>, draft=draft_row)`").

**Evidence:** `published` is `PublishedRelease`, and `PublishedRelease.release` is `ActiveReleaseSnapshot` (#269 I2). `_snapshot_locked_workbench` expects a `GraphRelease` ORM row (it reads `.id` and `.version_number`). Passing `published.release` raises `AttributeError`.

**Instruction:**
1. Fetch the new release ORM row after the core returns: `new_release_row = session.get(GraphRelease, published.release.release_id)`.
2. Assert `new_release_row is not None`; a `None` would indicate a defect in `_commit_locked_publication`.
3. Call `_verify_rebased_draft(session, release_row=new_release_row, draft_row=draft_row, effect=effect, before=snapshot, restored=contents)`.

**Sabotage:** n/a.

**Binds:** Phase B, Task 3a, blocking (the code template has a latent `AttributeError`).

**Cost if wrong:** `_verify_rebased_draft` raises `AttributeError` and the rebase verification is skipped entirely.

---

### Correction 22 (M15) — `compare_with_active` takes a `FOR SHARE` lock it does not need

**Overrides:** plan line 287 ("`compare_with_active` and `preview_rollback` take `_lock_current_parents(exclusive=False)` … because the draft effect must be coherent").

**Evidence:** `compare_with_active` returns a `ReleaseComparison` of the active release's revision ids against the historical mapping. It has no draft component; no `draft_effect` field appears on `ReleaseComparison`. Taking `FOR SHARE` on the release and draft rows unnecessarily stalls every conversation creation for the length of the call. The draft-effect coherence requirement belongs only to `preview_rollback`, which does include `draft_effect`.

**Instruction:**
1. **`compare_with_active`:** make it lock-free, mirroring `list_release_history`. Read the active release id in the first statement and filter every subsequent statement to that id. Take no row lock.
2. **`preview_rollback`:** keep `_lock_current_parents(exclusive=False)` (`FOR SHARE`); the draft effect requires a consistent snapshot of the active release and draft.
3. Update the lock-order table at plan line 287: `compare_with_active` takes no lock; `preview_rollback` takes L0 share.

**Sabotage:** n/a.

**Binds:** Phase B, Task 2, blocking.

**Cost if wrong:** `compare_with_active` stalls every conversation creation for the duration of a history comparison; unnecessary lock contention.

---

### Correction 23 (M16) — "one request counter" and "one in-flight gate" are stated as fact but depend on #269

**Overrides:** plan lines 7 ("uses that page's one reducer, one counter, and one in-flight gate") and 27 ("uses its one request counter, and joins its one in-flight gate").

**Evidence:** Plan line 89 admits "#269's plan is silent on both". Lines 7 and 27 then state them as established facts.

**Instruction:**
1. Reword plan line 27 to: "If #269's integrated code has a request counter, #270 uses it; if not, Task 7 adds exactly one and records that addition in corrections. The same applies to the in-flight gate."
2. Task 0-B must re-probe whether the counter and gate exist and record their exact names and locations.
3. If Task 0-B finds they exist: Task 7 extends them as planned.
4. If Task 0-B finds they do not exist: Task 7 adds them, with a corrections entry recording the addition before Task 7 is dispatched.

**Sabotage:** n/a.

**Binds:** Phase A (informational for Task 0-B). Blocking before Task 7.

**Cost if wrong:** Task 7 either duplicates or omits the counter/gate, and out-of-order responses render stale state.

---

## Blocking summary

- **Phase A (before Task 1):**
  - Correction 11 (M4): `list_release_history` code template; must be in Task 1's brief.
  - Correction 14 (M7): Task 0 Step 3 baseline loop; apply before recording the Task 1 baseline.

- **Phase B (before Task 2):**
  - Correction 1 (C1): SQLite same-second guard; required for Tasks 2, 3 and 6.
  - Correction 2 (I1): preview remote endpoint validation.
  - Correction 12 (M5): `_load_source` import choice and unmapped exceptions.
  - Correction 20 (M13): OQ1 disclosure and `_structural_issues` scope decision.
  - Correction 22 (M15): `compare_with_active` lock-free.

- **Phase B (before Task 3a):**
  - Correction 15 (M8): injected-failure evidence assertions.
  - Correction 16 (M9): split Task 3 into 3a and 3b.
  - Correction 18 (M11): `matches_active` fixture specification.
  - Correction 19 (M12): `out_of_range` code for `version_number < 1`.
  - Correction 21 (M14): `_verify_rebased_draft` needs an ORM release row.

- **Phase B (before Task 4):**
  - Correction 6 (I5): pause matcher and predicted RED.

- **Phase B (before Task 6):**
  - Correction 13 (M6): log contract, no traceback.

- **Phase B (before Task 7):**
  - Correction 3 (I2): fixed accessible names.
  - Correction 4 (I3): `ReviewAndPublishPage.test.tsx` in Task 7's file list.
  - Correction 23 (M16): request counter and gate conditional on Task 0-B.

- **Phase B (before Task 8):**
  - Correction 7 (I6): Task 8 controller sabotage and (a) count.

- **Phase B (before Task 9):**
  - Correction 5 (I4): Task 9 expected values for builder.

- **Non-blocking (apply in named task):**
  - Correction 8 (M1): router location (Task 0-B and Task 6).
  - Correction 9 (M2): stale #268 cleanup facts (Task 5 descriptions).
  - Correction 10 (M3): links conventional not enforced (Task 10 writer table).
  - Correction 17 (M10): Task 5 reviewer sabotage replacement.

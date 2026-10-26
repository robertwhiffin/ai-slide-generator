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

---

# Task 0 phase B corrections (2026-09-27) — corrections 24–47

- **Probed at:** `plan/release-history-rollback-270` HEAD `7465854f4` = INTEGRATION_BASE `c7ea1d943` (Merge #269) + the rebased Task 1 `29df4c318` + docs. Predecessor heads and ancestry: `predecessor-heads.md`. Baselines: `reports/preflight-phase-b.md`.
- **Sources read:** #269's ledger (`.worktrees/issue-269-plan/.superpowers/sdd/2026-09-25-graph-release-publication/`: `progress.md`, `PLAN-CORRECTIONS.md` C1–C55 + C33 addendum, `whole-branch-review.md`, `task-*-report.md` via progress), then the code as built. Every line below is from the code at HEAD unless marked **reasoned**.
- **Corrections 1–23 are not edited.** Where one is now wrong or needs completion, an erratum below says so: **Correction 37 is an erratum to Correction 8**; 31 completes I6; 32 resolves Correction 20(b); 33 resolves Correction 12; 34 completes Correction 2; 37 also corrects Correction 13's line cite; 39 resolves Correction 23 and confirms Correction 4.
- **#269 carries (progress.md "Phase B start", BINDING):** (1) → Correction 38; (2) → 28; (3) → 29; (4) → 29; (5) → 28 and 29; (6) → 37. The #269 whole-branch park m4 → 39.
- **Probe:** `/tmp/t270b/probe_restore.py` ran the whole rollback write path against the real core on SQLite (report §4): v4 restores v2 with a `historical_restore` link, all seven revisions reused, lineage exact — and the parent-only rebase leaves architect `changed is True`.

### Correction 24 — the bases and the range, as they actually are

**Overrides:** plan line 17 and Task 0 Step 4 (plan line 397: "prove `INTEGRATION_BASE..HEAD` is exactly the rebased Task 1"); plan line 15 ("never commit SDD evidence except the ledger `progress.md`").

**Evidence:** `git log c7ea1d943..HEAD` = 8 commits: 7 docs commits (`144deba26`, `2d31172fe`, `c073f6990`, `7610fe177`, `7efbee74f`, `c3e1dbc8e`, `7465854f4`) and the rebased Task 1 `29df4c318`. `git diff --stat c7ea1d943 29df4c318 -- src tests frontend packages .github` equals the same diff to HEAD (5 files, +1094); from `29df4c318` to HEAD it is empty. `git range-diff` of `d0e4d693a` vs `29df4c318` differs only in the two append-only conflict contexts. The corrections file and `task-1-report.md` are already committed (`c073f6990`, `7610fe177`), and the controller's standing instruction is to force-add the whole SDD dir.

**Proposed ruling:** the range proof is **code-wise**: `git diff --stat INTEGRATION_BASE..HEAD -- src tests frontend packages .github` must equal the union of the rebased Task 1 and Tasks 2–9, and every other commit in the range must touch only `docs/` or `.superpowers/`. Task 10's whole-branch package is generated with those pathspecs. SDD files are force-added and committed (controller instruction supersedes plan line 15).

**Binds:** Task 10 (range proof). Non-blocking now.

**Cost if wrong:** a reviewer rejects a correct range because it contains ledger commits, or an SDD artifact is lost.

### Correction 25 — "Verified code facts" re-anchored at HEAD (every row the plan cites)

**Overrides:** the plan's "Verified code facts" table (plan lines 34–70) and plan line 70 ("Absent at `a08389ec3`").

| Plan row | Plan location | At HEAD | Change |
|---|---|---|---|
| `GraphReleaseTestRun` checks | models :526–533 | `src/database/models/graph_configuration.py:526–532` (kind :527–528, paired :531–532), index :535 | lines only; columns and constraints unchanged (no model file change `a08389ec3..c7ea1d943`) |
| `read_workbench` | workbench :179–186 | `graph_configuration_workbench.py:182–189` | lines |
| `_lock_current_parents` | :188–238, "no handoff retry" | :191–248; **retry landed**: `_MAX_PARENT_LOCK_SCANS = 2` :172, loop :212–219; diagnosis string unchanged | behaviour (expected, #269 Task 2) |
| `_snapshot_locked_workbench` | :240–361 | :250–371; `changed = draft_row.candidate_hash != revision.content_hash` | lines |
| validator tuples | draft :346–352 | `graph_configuration_draft.py:347–353` | lines |
| `_run_candidate_validators` | :368–378 | :369–379 | lines |
| `_endpoint_name_policy_validator` / `_save_local_validators` | :276–284 / :380–387 | :277–285 / :381–388 | lines; **publication now also composes the policy** (see Correction 32) |
| `_write_locked_content` | :991–1029 (assign :999–1002) | :1013–1051 (column loop + hash :1020–1024); `_advance_locked_draft` :1004–1010 (extracted by #269) | lines + the #269 extraction |
| `_assembly_candidate_validator` | :226–234 | :227–235; `resolve_bundle` field rule `prompt_assembler.py:412–426` (`protected_assembly.digest` if the version is known, else `.version`) | lines |
| mutation guards | database.py :935–1121 | :935–~1170; `trg_agent_test_run_evidence_immutable` :1100; **`trg_agent_test_run_linked_verdict_immutable` :1112–1158 (#269 C14)**; `trg_graph_release_exactly_one_active` :1160 | #269 addition |
| admin router | routes :97–101 | `src/api/routes/agent_definitions.py:127–131` | lines |
| `require_draft_write_principal` | :104–112 | :134–142 | lines |
| `_is_storable_row_id` | :1066–1067 | :1096–1097 (`MAX_ROW_ID = 2**31 - 1`, `schemas/agent_definitions.py:593`) | lines |
| `AgentRuntime` / `AgentAssemblyContext` | runtime :796–807, :829–835, :151 | :796–806 ctor (keyword `persisted_release_loader, model_adapter, identity_sink`), `run` :829 (four positional), `AgentAssemblyContext(design_system_active, root_session_id="", actor_session_id="")` :151–167 | lines; constructor recorded (plan line 752 asked) |
| forbidden-action rule | fixture :17–18, :31–37, five exemptions | `frontend/tests/fixtures/forbiddenActionNames.ts:18–19` stems, **8** exemptions :40–49 | #268/#269 raised it to 8 (Correction 40) |
| admin route gate | App.tsx :27–33, :53 | `RequireAdmin`; review route `App.tsx:55` | #269 addition |
| route test fixture / PG route stack | :118–157 / :1284–1310 | `real_route_stack` `tests/integration/test_agent_definition_workbench_postgres.py:1284` (#269's acceptance file copies it, `:16`) | unchanged |
| facade | bases | `src/services/graph_configuration.py:66–71`: `(_GraphConfigurationPublication, _GraphConfigurationDraft, _GraphConfigurationWorkbench, _GraphConfigurationBootstrap)`; MRO printed in report §4 | Task 2 prepends `_GraphConfigurationRollback` → the plan line 324 MRO |

**Present now (plan line 70 listed them absent):** `graph_configuration_publication.py`, `graph_release_evidence.py`, #268's readiness/verdict/cleanup, the Review & Publish page, `GET /release-preview`, `POST /releases`, the handoff retry.

**Proposed ruling:** implementers and reviewers cite these lines, not the plan's. **Binds:** all Phase B tasks (informational). **Cost if wrong:** mis-aimed sabotage anchors.

### Correction 26 — I1 as built: the core restores historical content end to end, but guards nothing rollback-specific

**Overrides:** plan I1 (line 76) and plan line 89 ("#269's plan is silent on whether `_commit_locked_publication` asserts anything about `restored_from_release_id`").

**Evidence:**
- Signature exactly as I1: `_commit_locked_publication(self, session, *, release_row, draft_row, snapshot, contents, evidence, release_note, actor, restored_from_release_id) -> PublishedRelease` (`graph_configuration_publication.py:470–482`).
- Checks, in order: exactly seven contents (:484–489); `database_transaction_timestamp(session) > as_utc_aware(release_row.effective_from)` (:490–494); `materialize_or_reuse_revision` per role (:495–500); an unchanged role must reuse its revision (:502–510); `max(version_number) == release_row.version_number` (:511–515); close before insert (:516–518); new release with `restored_from_release_id` written verbatim (:519–529); seven mappings + read-back (:530–551); `self._link_evidence` → `link_release_evidence` (:552, :596–608, lazy import); `draft_row.base_release_id = new` + `_advance_locked_draft` (:553–554).
- It asserts **nothing** about `restored_from_release_id`, and it accepts a no-op: `test_core_writes_restored_from_verbatim` (`tests/unit/test_graph_release_publication.py:698`, GREEN at HEAD) restores the active mapping with `changed_agent_keys == ()`.
- `changed_agent_keys` is relative to the **active** release (:569–573).
- Probe (report §4): rollback with historical contents, `historical_restore` links and `restored_from_release_id` works as planned; no new revision; lineage exact.

**Proposed ruling:** keep the plan's thin-caller design. Rollback owns every rollback-specific refusal (`source_is_active`, `matches_active`, `incompatible`) before calling the core, because the core would happily write a no-op v(n+1). The call runs inside rollback's own single `with session.begin()` (the #269 whole-branch §3 rollback guarantee). The `reused` post-check in the plan (line 716) stays.

**Binds:** Tasks 2, 3a. **Cost if wrong:** a no-op release is creatable if a refusal is dropped (the core will not catch it).

### Correction 27 — I2/I3 types as built

**Overrides:** plan I2/I3 (lines 77–78).

**Evidence:** `EvidenceKind = Literal["approval", "historical_restore"]` (:80); `EvidenceLink(agent_test_run_id, agent_key, test_case_id, evidence_kind, source_release_id)` (:84–90); `PublicationGap(agent_key, test_case_id: int | None, code)` (:93–98); `PublicationNotReady(locked_gaps, readiness)` (:101–119); `PublishedMapping` (:132–138); `PublishedRelease(release: ActiveReleaseSnapshot, previous_release_id, changed_agent_keys, mappings, evidence, draft)` (:141–148); `PublicationConflict(expected_lock_version, current_lock_version, active_release_id, active_version_number, draft)` (:151–157); `NothingToPublish` (:160–164, not in I2); `PublicationRejected(*issues)` (:167–176). `link_release_evidence(session, *, release_id, evidence)` (`graph_release_evidence.py:211–262`) is kind-agnostic: it refuses a repeated `(run, kind, source)` triple, checks every run exists (plain read), inserts, and reads back exactly. The DB CHECKs accept `historical_restore` with a non-null source (probe).

**Proposed ruling:** as planned. `PublishedRelease.release` is an `ActiveReleaseSnapshot` (field `release_id`), so Correction 21 stands. Rollback never returns `NothingToPublish`.

**Binds:** Tasks 2, 3a. **Cost if wrong:** none beyond Correction 21.

### Correction 28 — #269 carry (2) and (5): the rollback's L3 is `FOR UPDATE … ORDER BY id`, not `FOR SHARE`

**Overrides:** plan line 284 (L3 row: `FOR SHARE OF agent_test_run`), line 599 (`with_for_update(read=True, of=AgentTestRun)`), line 804 (Task 4 listener matches `… FOR SHARE OF AGENT_TEST_RUN`), and the lock table's "`KEY SHARE` on runs is compatible with L3 `FOR SHARE`".

**Evidence:** `link_release_evidence` "takes no lock of its own … a caller that links runs must lock them first, in id order (Correction 33 addendum)" (`graph_release_evidence.py:217–220`). #269 whole-branch review §8: "The restore must lock the source release's linked runs `FOR UPDATE ORDER BY id` before linking … Keep the lock anyway, so two L3 lockers never cross." #269's other multi-row L3 lockers are `FOR UPDATE` in id order: the gate (`graph_release_evidence.py:91–121`) and cleanup (`agent_test_workbench.py:737–760`).

**Proposed ruling:**
1. `_historical_evidence(lock=True)` is `select(AgentTestRun).join(GraphReleaseTestRun, …).where(graph_release_id == source, run_kind == 'candidate').order_by(AgentTestRun.id).with_for_update(of=AgentTestRun).execution_options(populate_existing=True)`. `lock=False` (preview) takes no row lock.
2. **C33 (carry 5):** the linked-vs-unfiltered `count(*)` that follows is a NEW statement, so it is the post-wait re-check. Ledgered argument for why no further re-check is needed: the predicate's rows cannot move under a waiter — the source's link rows are insert-only for their own release and never rewritten (Correction 10), `run_kind` is immutable (`trg_agent_test_run_evidence_immutable`), a linked run cannot be deleted (FK RESTRICT) and its verdict cannot change (C48 refusal + `trg_agent_test_run_linked_verdict_immutable`).
3. The lock table's L3 row reads `FOR UPDATE OF agent_test_run`, id order. The implicit FK `KEY SHARE` from the link INSERT is on rows this transaction already holds `FOR UPDATE` (as in publication).
4. Task 4's verdict test pauses the rollback after its first statement matching `FROM AGENT_TEST_RUN JOIN GRAPH_RELEASE_TEST_RUN` and `FOR UPDATE OF AGENT_TEST_RUN`.
5. Deadlock-freedom is unchanged: rollback's L3 and the gate's L3 never overlap (both need L0 `UPDATE`); cleanup needs L0 `SHARE`; the verdict writer takes L3 only (one row).

**Sabotage (Task 4 reviewer, an addition if the controller wants one):** drop the L3 lock (`lock=False` in `restore_release`). Predicted RED: `test_verdict_change_on_source_linked_run_waits_then_is_refused` at `_await_blocked_by` (the verdict writer is never blocked).

**Binds:** Task 2 (the helper), Task 3a (the call), Task 4 (the matcher). Blocking before Task 2.

**Cost if wrong:** two L3 lock modes in the system, and a verdict writer that races rather than waits.

### Correction 29 — #269 carries (3) and (4): lock discipline, the AST scanner, and the import cycle

**Overrides:** plan lines 610, 690–692 (the lock statements' context) and Task 2's file list.

**Evidence:**
- The L0 statement (`graph_configuration_workbench.py:198–211`) and L1 (`graph_configuration_publication.py:350–366`) carry no `populate_existing` (#269 whole-branch m3); they are correct only as the first statement of a fresh transaction. `Session.begin()` on a session with an open transaction raises, and the route sessions use `expire_on_commit`.
- `tests/unit/test_graph_parent_lock_is_single_sourced.py:18,38–63` fails for any function outside `_lock_current_parents` whose AST names `with_for_update` together with both `GraphRelease` and `GraphDraft` (names include type annotations and attributes).
- `graph_configuration_publication.py:604–606`: `graph_release_evidence` is imported lazily because it imports the publication module and #268's workbench, which imports the `GraphConfiguration` facade (`agent_test_workbench.py:86`). The facade will import the rollback module.

**Proposed ruling:**
1. `compare_with_active`, `preview_rollback` and `restore_release` each open `with session.begin():` on a session with no open transaction, and their first statement is `_lock_current_parents` (preview, restore) or `_read_history`'s `populate_existing` statement (compare, Correction 33). Nothing reads the graph rows before that.
2. No rollback function contains `with_for_update` together with the names `GraphRelease` and `GraphDraft`. Keep the L3 lock in `_historical_evidence`, and do not annotate it with those types. The scanner must stay GREEN unchanged (its `_ALLOWED` set is not edited).
3. `graph_configuration_rollback.py` imports neither `graph_release_evidence` nor `agent_test_workbench` at module scope. It needs neither: the core links evidence through its own lazy import. Tests import `ApprovalEvidenceGate` freely.

**Binds:** Tasks 2, 3a. Blocking before Task 2.

**Cost if wrong:** a stale identity-map row used as a lock result; a scanner RED; an `ImportError` at app start.

### Correction 30 — rollback runs no approval gate; what "historical links never satisfy the gate" really means

**Overrides:** nothing in the plan's design (confirmed: lines 5, 26, 79, 283, 310 say rollback calls no gate and re-verifies nothing). It sharpens the wording of lines 79, 345 and 1052.

**Evidence:** `restore_release` (plan lines 686–724) calls no gate. The gate never reads `graph_release_test_run`: L3 selects runs by case id + version + role + **current draft candidate hash** + approved + completed + checks passed (`graph_release_evidence.py:91–121`), re-verified with `eligible_approval_clause` (`agent_test_workbench.py:640–654`). Readiness uses the same clause. So a `historical_restore` link neither helps nor hurts eligibility; eligibility is keyed by content hash.

**Proposed ruling:**
1. Confirmed: rollback must NOT run the approval gate (§12: emergency rollback bypasses model tests and approvals). It links the source's evidence instead.
2. Review Focus 4 (`test_historical_restore_evidence_never_satisfies_readiness`) is valid as specified: the new architect content H has a new hash, so no approved run is eligible. State in the test docstring that the refusal comes from the hash key, not from any link filter.
3. Disclose (with Correction 20(a)): a later draft whose content hash equals an old approved run's hash is eligible through that run, linked or not. This is #268 C11's design, pre-existing, and not a #270 defect.
4. Task 10's final controller sabotage stays as written; it adds a link-based acceptance that does not exist today.

**Binds:** Task 3b (test docstring), Task 10. Non-blocking.

**Cost if wrong:** a reviewer hunts for a link filter that does not exist, or misreads the negative proof.

### Correction 31 — I6: there is no `_actor_and_lock_issues`; how `_validate_rollback_request` reuses #269's rules

**Overrides:** plan I6 (line 81), line 311, lines 727 and 242; completes Correction 19.

**Evidence:** #269 C36 replaced C17's helper: `_GraphConfigurationDraft._actor_issues` (`graph_configuration_draft.py:775`) and `_lock_version_issues` (:812). The note rules are inline in `_GraphConfigurationPublication._validate_publication_request(actor, lock_version, release_note)` (`graph_configuration_publication.py:333–347`) with module-private constants `_NOTE_NOT_STRING`, `_BLANK_NOTE`, `_NOTE_TOO_LONG` (:68–78). There is no separable note helper, and the plan forbids editing the publication module (line 325).

**Proposed ruling:**
```python
def _validate_rollback_request(self, version_number, actor, lock_version, release_note):
    issues = _version_number_issues(version_number)          # Correction 19: strict_type / out_of_range
    try:
        self._validate_publication_request(actor, lock_version, release_note)
    except PublicationRejected as rejection:
        issues.extend(rejection.issues)
    if issues:
        raise PublicationRejected(*issues)
```
This keeps one copy of the actor, lock and note rules, in the order `version_number, actor, lock_version, release_note`, and needs no change to #269's file. The route maps an `actor` issue to 403, exactly like the publish route (`agent_definitions.py:1611–1618`); every other issue is `422 invalid_rollback`.

**Binds:** Task 3a (service), Task 6 (route). Blocking before Task 3a.

**Cost if wrong:** a second copy of the note rules drifts from publication's, or a blank principal returns 422 instead of 403.

### Correction 32 — structural validation uses publication's exact phases, including the endpoint-name policy (resolves Correction 20(b))

**Overrides:** plan lines 568 (`self.local_candidate_validators`), 618 ("exactly the two tuples #269's publication gate uses"), 1075 (OQ9's scope text); resolves Correction 20(b)'s open decision.

**Evidence:** #269 C37: publication runs `self._save_local_validators()` (= `local_candidate_validators + (_endpoint_name_policy_validator,)`, `graph_configuration_draft.py:381–388`) then `self.post_stale_validators`, in one `try`, per changed role, prefixing `definitions.<key>.` (`_changed_candidate_issues`, `graph_configuration_publication.py:444–468`). It never runs the remote check. So "the two tuples" in plan line 618 is no longer what publication uses.

**Proposed ruling:** `_structural_issues(contents)` loops over `GRAPH_V1_AGENT_KEYS`, and for each role runs `self._save_local_validators()` then `self.post_stale_validators` inside one `try` (a failed local phase skips post-stale, matching `_changed_candidate_issues`), prefixing `definitions.<key>.`. It cannot call `_changed_candidate_issues` directly, because that reads `node.draft.content`, not a contents mapping. Consequence to disclose under OQ1: a historical release whose endpoint name fails **today's** local policy is refused as `rollback_incompatible` (it is not restorable until a newer release is chosen). The alternative (rule the policy out) restores it and then every save of that role fails the policy (Correction 20(b)).
- **Task 2 test (addition):** ORM-write a URL-shaped `endpoint_name` into v2's architect revision (recompute the hash; SQLite has no guards) → `preview_rollback(2)` has `blocked == "incompatible"` and the first issue `DraftValidationIssue("definitions.architect.candidate.model.endpoint_name", "endpoint_url_not_allowed", …)`.
- **Sabotage (Task 2 reviewer, an addition):** replace `self._save_local_validators()` with `self.local_candidate_validators`. Predicted RED: the endpoint test (`blocked is None`).

**Binds:** Task 2. Blocking before Task 2 (controller ruling: include the policy, or rule it out).

**Cost if wrong:** rollback validates less than publication and restores a mapping publication would refuse; or (if the controller rules it out) a restored role becomes unsaveable.

### Correction 33 — `_load_source` and `compare_with_active` reuse Task 1's read model (resolves Correction 12); Task 1 needs no change for #269

**Overrides:** plan lines 549–563 (`_load_source` via `PersistedGraphReleaseLoader._validate_complete_snapshot`) and resolves Correction 12 (Option A vs B) and the shape of Correction 22.

**Evidence:**
- `validate_definition_hash` already maps `TypeError`/`ValueError` to `GraphConfigurationIntegrityError("… has invalid semantic content")` (`graph_configuration_content.py`, `validate_definition_hash`), so Option B needs no extra mapping.
- Task 1's `read_release_detail` (`src/services/graph_release_history.py:217–244`) already builds exactly the seven `ReleaseDefinition(agent_key, agent_definition_revision_id, content_hash, content)` the plan's `resolved[k]` uses, with the role check and hash validation.
- `_read_history` (:119–199) is the one first-statement-coherent read (with `populate_existing`, Correction 11).
- #269 changed no model file and did not change `validate_definition_hash` (`git diff a08389ec3 c7ea1d943 -- src/database/models/graph_configuration.py` is empty; the content-module diff only adds `as_utc_aware`, `database_transaction_timestamp`, `materialize_or_reuse_revision` and drops an unused import). Task 1's unit file (17) and PG file (4) are GREEN at HEAD.

**Proposed ruling:**
1. **Task 1 needs no change because of #269.**
2. Task 2 makes one behaviour-preserving extraction in #270's own module: `_release_definitions(session, mapping) -> Mapping[AgentKey, ReleaseDefinition]` from `read_release_detail` :217–244. `read_release_detail` calls it; Task 1's tests stay GREEN unchanged.
3. `_load_source(session, *, version_number)` = `snapshot = _read_history(session)`; find the entry (else `GraphVersionNotFound`); `definitions = _release_definitions(session, snapshot.mappings[entry.release_id])`. This is Option B; the private loader import is dropped. Inside rollback's L0 transaction these are plain SELECTs, which is allowed.
4. `compare_with_active` (lock-free per Correction 22) = one `_read_history` (first statement fixes the set; its one active entry is "active"), then `_release_definitions` for the active and the historical mappings. No second history read, so no two-snapshot skew.
5. Correction 12's unit test re-targets: monkeypatch `src.services.graph_configuration_content.definition_content_from_row` (as imported by `validate_definition_hash`) to raise `TypeError` → `_load_source` raises `GraphConfigurationIntegrityError`.

**Binds:** Task 2. Blocking before Task 2.

**Cost if wrong:** a second revision-validation path that drifts from history's, or a comparison built from two different release sets.

### Correction 34 — completes Correction 2 (OQ9): how the preview's remote check is wired, and its latency bound

**Overrides:** completes Correction 2 steps 1 and 4.

**Evidence:** the remote phase helper exists: `_GraphConfigurationDraft._validate_remote_endpoint(content)` (`graph_configuration_draft.py:390–397`) returns early when `self._remote_endpoint_validator is None` and wraps `EndpointValidationFailure` as `DraftContentRejected(_endpoint_issue(failure))` with field `candidate.model.endpoint_name` and the catalog's own code/message (no endpoint text, :271–274). The facade gets the validator from `__init__(remote_endpoint_validator=…)` (:355–367). The PUT route builds `GraphConfiguration(remote_endpoint_validator=remote_endpoint_validator)` from `Depends(get_remote_endpoint_draft_validator)` (`agent_definitions.py:145–152`, :597–599, :645–657). Each remote check is bounded to ~15 s (#269 C51).

**Proposed ruling:**
1. `preview_rollback` commits its `FOR SHARE` transaction first; then, outside any transaction, calls `self._validate_remote_endpoint(content)` once per **distinct** endpoint name among the seven historical contents, and maps each failure to a warning `DraftValidationIssue(f"definitions.{key}.candidate.model.endpoint_name", code, message)` for **every** role using that endpoint, in `GRAPH_V1_AGENT_KEYS` order. De-duplication bounds the preview to (number of distinct endpoints) × ~15 s; seven sequential checks could otherwise approach ~105 s.
2. The rollback-preview handler is a plain `def` (FastAPI runs it in the threadpool, like `get_graph_release_preview`, `agent_definitions.py:1561`), depends on `get_remote_endpoint_draft_validator`, and builds the facade with it. The four other new routes and the POST do not depend on it (Correction 2 step 4).
3. Correction 2's "validator records `session.in_transaction()` is `False`" test stays.

**Binds:** Task 2 (service), Task 6 (route). Blocking before Task 2, with Correction 2.

**Cost if wrong:** a preview that holds the release row `FOR SHARE` across a network call (stalling session creation), or a preview that takes over a minute.

### Correction 35 — Q7 (OQ1) is flagged for the user: what the default does, and what binds where

**Overrides:** nothing; records the flag the controller asked for. Completes Correction 20(a).

**Evidence:** controller ruling OQ1 (progress.md, 2026-09-26): three-way rebase ACCEPTED and "reported to the user as a visible behaviour they may override". No user confirmation is recorded in the ledger. The probe (report §4) shows why a choice is needed: after the core's parent-only rebase, a clean architect still holds the rolled-back-from content and reads `changed is True` against the restored release.

**The default, in plain words:** the shared draft is the one set of seven in-progress definitions all admins edit. When an admin rolls back from v7 to v3, the system publishes v8 = v3's definitions and then looks at each role in the shared draft:
- if nobody had edited that role since v7 was published (its draft still equals v7), the draft for that role is **replaced with the restored v3 content**, so it shows as unchanged against v8;
- if somebody **had** saved an unpublished edit to that role, the edit is **kept exactly as it was**, and it now shows as a change against v8 (it still needs its own approval before it can be published);
- if the role's content is the same in v7 and v3, nothing happens to it.
So rollback never throws away anyone's saved work, and it never leaves the rolled-back content sitting in the draft ready to be re-published by accident. The two alternatives are: "reset everything" (simpler, but silently deletes unpublished edits) and "only move the draft's base" (keeps everything, but the draft then still contains v7's content for every clean role, so the next Review & Publish offers to re-publish exactly what the emergency rollback removed).
Also disclosed (Correction 20(a)): a kept edit that already had an approved test run stays approved after the rollback, although that approval was reviewed against v7's baseline.

**Proposed ruling:** keep the default; the controller surfaces it to the user before Task 3a (where the reset loop is written). Task 2 builds `_draft_effect` for the preview; an override later changes only `_draft_effect`, the reset loop and their tests.

**Binds:** Task 2 (`draft_effect` in the preview, non-blocking), Task 3a (the reset loop — **user confirmation or an explicit "proceed on the default" ruling before Task 3a dispatch**), Task 9 (step 6 expectations).

**Cost if wrong:** the rollback's draft effect differs from what admins expect; one function and its tests.

### Correction 36 — `_assign_locked_candidate` against `_write_locked_content` as built

**Overrides:** plan lines 673–684 and 114.

**Evidence:** `_write_locked_content` is a `@staticmethod` (`graph_configuration_draft.py:1012–1051`); it computes `old_hash` / `new_hash` (:1020–1021), runs the column loop and sets `candidate_hash` (:1022–1024), then takes the timestamp and calls `_GraphConfigurationDraft._advance_locked_draft` (:1025–1028), then flushes. `_advance_locked_draft` (:1003–1010) is the one parent-audit write, used by both the saves and publication (`graph_configuration_publication.py:554`). No other `src` code writes `candidate_hash` (`rg "candidate_hash =" src` → only :1024). Suites that exercise `_write_locked_content`: `tests/unit/test_graph_configuration_draft.py`, `tests/unit/test_agent_runtime.py`, `tests/integration/test_agent_definition_workbench_postgres.py`, `tests/integration/test_agent_schema_overlay_postgres.py`.

**Proposed ruling:**
1. `_assign_locked_candidate(row, content)` is a `@staticmethod` on `_GraphConfigurationDraft` holding exactly :1022–1024 (with `row.candidate_hash = definition_content_hash(content)`).
2. `_write_locked_content` keeps `new_hash = definition_content_hash(content)` before the call (it still feeds `changed`), and calls `_GraphConfigurationDraft._assign_locked_candidate(locked.selected_row, content)`.
3. `restore_release` applies resets **after** the core returns (the core already advanced the parent once) and then flushes; it never calls `_advance_locked_draft` itself.
4. Task 3a's GREEN adds `tests/unit/test_agent_runtime.py` and the two PG files above to the gate.

**Binds:** Task 3a. Blocking before Task 3a.

**Cost if wrong:** a second content writer, or a draft save whose `changed` flag is computed after the assignment (always `False`).

### Correction 37 — erratum to Correction 8: #270's handlers go in `agent_definitions.py`; plus the log idiom (corrects Correction 13's cite)

**Overrides:** Correction 8's instruction ("expected `graph_releases.py` (or wherever #269 C31 puts them)"), plan lines 24, 326, 865, 879; corrects Correction 13's cite `agent_definitions.py:521`.

**Evidence:** #269 C35 (erratum to C31): a module that decorates the router after `include_router` registers nothing (FastAPI copies routes at `include_router`, `src/api/main.py:484`). #269 put `GET /release-preview` and `POST /releases` in `src/api/routes/agent_definitions.py` (:1556–1621) on the one `router` (:127–131); `src/api/routes/graph_releases.py` does not exist; wire models are in `src/api/schemas/graph_releases.py`. Publication success is 200 (:1575, C10). `_graph_integrity_failure` (:1446–1448) calls `logger.exception("Persisted Graph Configuration is incomplete")`.

**Proposed ruling:**
1. Task 6 adds its five handlers to `src/api/routes/agent_definitions.py` after #269's release handlers, on `router`. New wire models go in the new `src/api/schemas/graph_release_history.py` (plan line 327 stands). No `main.py` change. The registration test builds `src.api.main.app` and asserts each method+path exactly once (#269's `test_the_client_routes_are_the_mounted_routes` pattern).
2. Rollback success is **200**. The POST runs the service with `run_in_threadpool` (C46; it can wait on L0 behind a save's remote check). The body parser mirrors `_parse_publish_request` (:1424–1443) with code `invalid_rollback`.
3. **Log (with Correction 13):** the rollback handler must not call `_graph_integrity_failure`; on `GraphConfigurationIntegrityError` it emits the one `graph_release_rollback` ERROR record (no `exc_info`) and raises `HTTPException(500, "Graph configuration is incomplete")` directly. The four read handlers may use `_graph_integrity_failure` (they are outside the rollback log contract).

**Binds:** Task 6. Blocking before Task 6.

**Cost if wrong:** routes that 404 in the app while route tests pass; a traceback in the rollback log.

### Correction 38 — #269 carry (1): widen the release-evidence wire, atomically, in Task 6

**Overrides:** plan line 328 ("no existing parser changed"), lines 909–915 (Task 7 "append"), line 264 (rollback `evidence` wire), and I3's wire assumption.

**Evidence:** `ReleaseEvidenceResponse` has `evidence_kind: Literal["approval"]` and no `source_release_id` (`src/api/schemas/graph_releases.py:104–108`); the publish route builds it without the source (`agent_definitions.py:1503–1511`). The TS side mirrors it: `ReleaseEvidence` (`frontend/src/api/agentDefinitions.ts:1963–1968`), `RELEASE_EVIDENCE_KEYS` (:2066), `isReleaseEvidence` requires `evidence_kind === 'approval'` (:2171–2177). #269 pins both: `tests/unit/test_graph_release_client_join.py:79` (key list, order) and `:131–134` (`(kind,) = get_args(...)` — a one-element unpack that fails when widened); `frontend/src/components/Admin/GraphRelease/releaseClient.test.ts:184–185` rejects a `historical_restore` kind and an extra `source_release_id` key on a **publish** 200; exact bodies at `tests/unit/test_graph_release_routes.py:~765–775`, `frontend/tests/fixtures/mocks.ts:1970`, and the `syntheticPublishSuccess` fixtures (`releaseClient.test.ts`, `reviewAndPublishState.test.ts`, `ReviewAndPublishPage.test.tsx`).

**Proposed ruling (honours the carry and keeps #269's publish strictness):**
1. Python: `ReleaseEvidenceResponse` gains `source_release_id: _RowId | None` (after `evidence_kind`) and `evidence_kind: Literal["approval", "historical_restore"]`, with a validator: `source_release_id is None` iff `evidence_kind == "approval"`. `PublishReleaseSuccessResponse` gains a validator: every evidence item is `approval`. The publish route passes `source_release_id=link.source_release_id`. The rollback success body reuses `ReleaseEvidenceResponse` with a validator that every item is `historical_restore`.
2. TS, **in the same commit:** `ReleaseEvidence` widened with `source_release_id: number | null`; `RELEASE_EVIDENCE_KEYS` appends `'source_release_id'`; `isReleaseEvidence` checks the kind pair and the pairing; `parsePublishReleaseSuccessResponse` requires every item to be `approval`.
3. #269 test edits (the second deliberate edit of #269 tests, after Correction 4): the join test's `:131–134` becomes a two-literal check (`set(get_args(...)) == {"approval", "historical_restore"}` and both spellings present in the TS source); the exact publish bodies and fixtures add `"source_release_id": null`; `releaseClient.test.ts:184–185` keep their intent (both still REJECT on a publish 200: 184 via the approval-only rule, 185 via the pairing rule once the fixture carries `source_release_id: null`) — relabel 185 "an approval with a source".
4. The history detail's evidence (with verdict, run time, source `Ref`) is a separate #270 model in `schemas/graph_release_history.py`; it does not reuse `ReleaseEvidenceResponse`.
5. Because `test_graph_release_client_join.py` reads both sides, the Python and TS halves must land in one Task 6 commit. Task 6's file list therefore adds `frontend/src/api/agentDefinitions.ts` (the evidence parser only), the four frontend fixture/test files above, and `tests/unit/test_graph_release_client_join.py`; Task 6's gate adds the GraphRelease Vitest and `npm run typecheck`. Task 7 then appends the history/rollback types and parsers.

**Sabotage (Task 6, an addition):** drop the pairing validator. Predicted RED: a route/unit test that a `historical_restore` item without a source (or an `approval` with one) is refused.

**Binds:** Task 6 (atomic), Task 7 (consumer). Blocking before Task 6.

**Cost if wrong:** the rollback wire drops `source_release_id`, or Task 6 is RED at the join test until Task 7, or a publish body silently starts accepting restore evidence.

### Correction 39 — the Review & Publish page as built (resolves Correction 23, confirms Correction 4, carries #269 m4)

**Overrides:** plan lines 7, 27, 83 (I8), 912–915, 950; resolves Correction 23; confirms Correction 4.

**Evidence:**
- Page `frontend/src/components/Admin/GraphRelease/ReviewAndPublishPage.tsx`; hook `useReviewAndPublish.ts`; state `reviewAndPublishState.ts`; `lineDiff.ts`; `index.ts` (exports). Route `App.tsx:55` inside `RequireAdmin`.
- **One reducer:** `useReducer(reviewAndPublishReducer, …)` (`useReviewAndPublish.ts:17`); `ReviewStatus` is one enum (`reviewAndPublishState.ts:28–37`) with `publishing` guards in `reloadPreview`/`noteChanged`/`publishStarted` (:138–166).
- **One counter:** `nextRequestIdRef` (`useReviewAndPublish.ts:18`). **One gate:** `publishInFlightRef` (:19), checked in `reloadPreview` (:22) and `publish` (:40); `canPublish` (`reviewAndPublishState.ts:96–102`).
- The **tab** is `useState<TabId>('changes')` in the page (:164), not the reducer. The tablist and both panels render only inside `preview !== null` (:255–330), and `aria-labelledby` is a two-way ternary (:287–288).
- Client tests live in `GraphRelease/releaseClient.test.ts`; `frontend/src/api/agentDefinitions.test.ts` does not exist (plan line 914).
- Correction 4's assertion exists verbatim: `ReviewAndPublishPage.test.tsx:205–215`, "offers no History or Rollback control (they belong to #270)", regex `/history|rollback|roll back/i`, tabs exactly `['Changes & Approvals', 'Definition Diff']`.
- #269 whole-branch m4 (parked): `publish()` checks `canPublish` against the render-closure `state` and sends the POST even if the reducer then refuses `publishStarted`.

**Proposed ruling:**
1. Correction 23's condition is met: the counter and gate exist. Task 7 extends them and adds none.
2. The one gate covers both writes: generalise `publishInFlightRef` into one write-in-flight ref (a rename is allowed) that `publish`, `confirmRollback` and `reloadPreview` all check; the reducer refuses `publishStarted` while a rollback is in flight and `rollbackStarted` while `status === 'publishing'`.
3. Do not copy m4: `confirmRollback` sends its POST only if the reducer accepted `rollbackStarted` (re-check against a `stateRef` or the reducer's result), and the Vitest proves a refused start sends zero POSTs. (Fixing publish's m4 is optional and out of scope.)
4. Render the tablist outside the `preview !== null` block, so the Release History tab is reachable when the release preview fails (an emergency path must not depend on the publish preview). Replace the two-way `aria-labelledby` ternary with a map over three tabs. The Publish section stays tied to the release preview.
5. Task 7's file list uses `releaseClient.test.ts` (not `agentDefinitions.test.ts`) and includes `ReviewAndPublishPage.test.tsx` per Correction 4, whose replacement assertion is exactly three tabs in order.

**Binds:** Task 7. Blocking before Task 7.

**Cost if wrong:** a second gate, a rollback reachable only when the publish preview loads, or a rollback POST sent after the reducer refused it.

### Correction 40 — forbidden actions: the count stays 8; OQ5's trigger did not fire

**Overrides:** plan line 27 (`toHaveLength(5)` at `AgentDefinitionWorkbench.test.tsx:351` / `agent-definition-workbench.spec.ts:1505`), line 952 ("at the Task 0-B value"), line 1071 (OQ5), and Task 8 (h).

**Evidence:** `ALLOWED_ACTION_NAMES` has 8 entries (`forbiddenActionNames.ts:40–49`: three restores, `Run test case`, `Run published baseline`, `Approve run`, `Reject run`, `Review & Publish`). The length is pinned at 8 in `AgentDefinitionWorkbench.test.tsx:378` and `agent-definition-workbench.spec.ts:1518`. #269's page has **no** rendered-control forbidden sweep: `graph-release-review.spec.ts:466–476` only asserts `forbidsActionName('Release history')`, `('Rollback release')`, `('Publish draft')` stay true and `('Review & Publish')` stays false, statically. The sweep applies to the workbench panel only.

**Proposed ruling:** #270 adds no exemption; the count stays **8** and neither length pin is edited. The Release History tab lives on the review page, reached through the existing `Review & Publish` header link. OQ5's "stop" condition (a page-level sweep) is not met, and Correction 3's fixed names stand. Only if the controller wants a workbench-header link straight to the history tab would one exemption be added — exactly `'Release History'` (whole name), making the count **9** and editing both pins; not recommended. Task 8 (h) keeps asserting `forbidsActionName('Release history')` and `('Rollback release')` are still true (they are different strings from the tab name `Release History` only by case; the rule is case-insensitive, so a workbench `Release History` control would still be flagged).

**Binds:** Tasks 7, 8. Blocking before Task 7 (the controller confirms 8).

**Cost if wrong:** a length pin edited for nothing, or a history control leaks into the workbench panel.

### Correction 41 — Task 4's verdict-change test: the outcome is C48's typed refusal, not an `IntegrityError`; `_await_blocked_by` keyword names

**Overrides:** plan lines 803–807 (the verdict writer "fails with `IntegrityError` SQLSTATE `23514` (I10)") and every `_await_blocked_by(waiter=…, blocker=…)` in Tasks 4–5 (lines 788, 790, 800–801, 834, 838, 847–848).

**Evidence:** `record_verdict` (`agent_test_workbench.py:1471–1545`) locks the run (`_verdict_lock_statement`, `FOR UPDATE`, `populate_existing`, :531–538), then for a changed verdict re-checks the link in a NEW statement and raises `IneligibleForApprovalError(run_id, "linked_to_release")` (:1511–1519); an identical re-submit is a no-op. R2 is linked to v2 as `approval` before the rollback starts, so the refusal does not depend on the rollback's link; the trigger (`database.py:1112–1158`) is only the backstop for direct writes. The helper is `_await_blocked_by(engine, *, waiter_pid: int, blocker_pid: int)` (`tests/integration/postgres_concurrency_helpers.py:215`).

**Proposed ruling:** the test asserts (a) the verdict writer is observed blocked by the rollback PID (`_await_blocked_by(engine, waiter_pid=…, blocker_pid=…)`, the wait comes from Correction 28's L3 `FOR UPDATE`); (b) after release it raises exactly `IneligibleForApprovalError` with `.reason == "linked_to_release"` and `.run_id == R2`; (c) R2's four verdict columns are byte-identical; (d) both links exist (`(v2, R2, approval, NULL)`, `(v5, R2, historical_restore, v2)`). Add: an identical re-submit during the same pause also waits and then returns the unchanged evidence (no-op). Every `_await_blocked_by` call uses the `waiter_pid` / `blocker_pid` keywords.

**Binds:** Task 4 (and Task 5's calls). Blocking before Task 4.

**Cost if wrong:** a test that waits for an `IntegrityError` that never comes (RED for the wrong reason), or a `TypeError` on the helper call.

### Correction 42 — the test harness as built (I12), and Correction 1 validated

**Overrides:** plan I12 (line 87), lines 529, 737–743 (injection stages), and completes Correction 1.

**Evidence:**
- `_NoEvidenceGate`: `tests/unit/test_graph_release_publication.py:56` (module level; also `tests/integration/test_graph_release_publication_postgres.py:51`). `_save_prompt`: unit :108, PG :62. `_publish`: unit :222, PG :95. `_backdate_v1`: unit :98.
- Injection: `_STAGE_MATCHERS` (`test_graph_release_publication_postgres.py:288–292`: `interval_closed`, `mappings_read_back`, `draft_rebased` = `UPDATE GRAPH_DRAFT SET`), `_install_commit_failure` / `_drop_commit_failure` (:295–331), evidence stage `INSERT INTO GRAPH_RELEASE_TEST_RUN` (`test_graph_release_evidence_postgres.py:577`). #269's session-ordering file already imports helpers by underscore name from these modules (`test_graph_release_session_ordering_postgres.py:42–56`).
- Correction 1's patch point exists: `database_transaction_timestamp` is a module-level name in `graph_configuration_publication.py` (:35, used :490). #269's own test uses exactly this monkeypatch (`test_graph_release_publication.py:796`). The probe (report §4) ran v2, v3 and a restore under a `v1_from + n h` clock (3 calls) with no integrity error. Draft saves use the draft module's own name, which the patch does not touch, and nothing compares a draft timestamp with a release interval.

**Proposed ruling:** import these helpers; never copy them (plan line 87). The rollback injection stages are `interval_closed`, `mappings_read_back`, `evidence_linked`, `draft_rebased` (the core's parent update), `draft_reset` (`UPDATE GRAPH_DRAFT_AGENT SET`, the rollback's own write) and `commit` — six, not five (Correction 15's assertions apply to each). Correction 1's helper stands; with the patched clock no backdating is needed (it is harmless).

**Binds:** Tasks 2, 3a, 3b, 6 (fixtures); Task 3b (stages). Blocking before Task 2 (the C1 helper).

**Cost if wrong:** duplicated helpers drift; the parent-rebase stage goes unproved.

### Correction 43 — Task 5: seven creators, not four paths

**Overrides:** plan lines 5 and 822–830 ("all four conversation-creation paths"), Task 5 Step 1.

**Evidence:** `CREATORS` has 7 entries (`tests/integration/test_mixed_release_creation_postgres.py:27–35`: `explicit-root`, `chat-generated-id`, `chat-supplied-id`, `chat-service-sync`, `chat-service-streaming`, `contributor`, `duplicate`) over the three `lock_active_graph_release` call sites (`session_manager.py:759, :897, :1245`, #269 Task 3 review). #269's `_seed` in the session-ordering file seeds v1 plus the creator's source (`test_graph_release_session_ordering_postgres.py:82`), and its first-lock matcher keys on `FOR UPDATE` (`_is_first_for_update`, :69).

**Proposed ruling:** Task 5 parametrizes over all 7 `CREATORS`; it builds v2–v4 after `_seed` (with the real clock on PG); the rollback pause uses Correction 6's mode-agnostic matcher, not `_is_first_for_update`.

**Binds:** Task 5. Non-blocking before Task 4.

**Cost if wrong:** three creator paths unproved against rollback.

### Correction 44 — Task 8: the route gate is already covered; nothing else from #269's specs needs editing

**Overrides:** plan lines 967 and 974 ((e) no-flash).

**Evidence:** `frontend/tests/e2e/admin-route-gate.spec.ts:141–183` already asserts a non-admin visiting `/admin/agent-definitions/review` is redirected with no review content and zero preview GETs (#269 Task 7 fix `ed8e05dd8`). `graph-release-review.spec.ts` asserts two tabs only by `aria-selected` (:171, :190–191), not by count.

**Proposed ruling:** Task 8 does not modify `admin-route-gate.spec.ts`; scenario (e) is dropped as already covered (or kept as one assertion that the history tab's content is absent during the identity hold, reusing the existing test's pattern). `graph-release-review.spec.ts` needs no edit for the third tab; its publish-success mocks gain `source_release_id: null` via `mocks.ts` per Correction 38.

**Binds:** Task 8. Non-blocking.

**Cost if wrong:** a duplicated route-gate test.

### Correction 45 — the #268 facts, re-verified (Correction 9 stands)

**Overrides:** plan line 91 (already corrected by Correction 9); records the entry points plan Task 0 Step 4 asked for.

**Evidence:** `AgentTestWorkbench(*, runtime=None, graph_configuration=None)` (`agent_test_workbench.py:992–1004`). `cleanup_unpublished_test_runs(self, session, *, per_case_limit: int = 20)` (:1647): `_require_no_transaction`, L0 `FOR SHARE` via `self._graph_configuration._lock_current_parents(exclusive=False)` (:1673), targets `SELECT agent_test_run.id … FOR UPDATE OF agent_test_run ORDER BY id` (:737–760), then a NEW-statement DELETE re-checking `_deletable_candidate` (:763–780; never a linked run, :700–705). `record_verdict` (:1471), L3 only (:531–538). `draft_readiness` (:1547, own txn + L0 share) and `readiness_under_parent_lock` (:1556, caller's L0) — the production binding is `workbench.readiness_under_parent_lock` (`agent_definitions.py:1408–1414`). `execute_candidate_run` (:1227). Eligibility `eligible_approval_clause` (:640–654).

**Proposed ruling:** Task 3b's evidence uses `execute_candidate_run` with `DeterministicFakeModelAdapter` (`tests/fixtures/deterministic_model_adapter.py:85`) and `record_verdict`, as #269 Task 8 did (builder approvable as-is); Task 3b's negative proof builds `ApprovalEvidenceGate(readiness=AgentTestWorkbench(...).readiness_under_parent_lock)`. Task 5's cleanup scenario pause matches `FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT` (Correction 9 step 4) and records the exact deleted id set.

**Binds:** Tasks 3b, 4, 5. Non-blocking.

**Cost if wrong:** a fixture built on a guessed signature.

### Correction 46 — the rollback preview's HTTP shape follows #269's preview idiom

**Overrides:** plan line 263 (rollback-preview wire) and line 262 (comparison `field_diffs` keys), completing Correction 2's `warnings`.

**Evidence:** `FieldDiff(field, published, candidate)` (`graph_configuration_publication.py:204–210`); wire `FieldDiffResponse(field: DiffFieldName, published, candidate)` (`schemas/graph_releases.py:54–57`); `DiffFieldName` is the 12-name literal pinned to `DIFF_FIELD_NAMES` (:30–43, join test). The TS `RELEASE_DIFF_FIELDS` exists (`agentDefinitions.ts` ~:1901).

**Proposed ruling:** #270's comparison uses its own `ReleaseFieldDiffResponse(field: DiffFieldName, active: JsonValue, historical: JsonValue)` (keys per plan line 262; `DiffFieldName` imported, not copied) with `extra="forbid"`; the service maps `FieldDiff.published → active`, `.candidate → historical` (plan line 187). The preview wire adds `warnings` (Correction 2) after `issues`. #270 adds its own join test file (`tests/unit/test_graph_release_history_client_join.py`) pinning every new key list and the literals to the TS parsers, on the #269 pattern.

**Binds:** Tasks 6, 7. Non-blocking before Task 6.

**Cost if wrong:** a `published`/`candidate` key on a comparison whose sides are active/historical, or unpinned parity.

### Correction 47 — Task 1 needs no change after #269 (answering the Task 0-B question directly)

**Overrides:** nothing.

**Evidence:** Correction 33 (models and `validate_definition_hash` unchanged; Task 1 GREEN at HEAD: unit 17/17, PG 4/4 with zero skips; the full unit run's +18 includes them). #269 adds no writer of `graph_release_test_run` other than `link_release_evidence`, which only inserts links for its own new release, so Task 1's "links are never rewritten for an existing release" premise holds (Correction 10). `ReleaseEvidence.evidence_kind` in Task 1 already allows `historical_restore` and `source`.

**Proposed ruling:** no Task 1 change. The only edit to `graph_release_history.py` in Phase B is Correction 33's extraction in Task 2.

**Binds:** Task 2. **Cost if wrong:** none.

---

## Per-task self-consistency (Tasks 2–9) at `7465854f4`, with Corrections 1–47 applied

| Task | Tests specified vs code specified | Files created vs later touched | Open mismatches |
|---|---|---|---|
| 2 | Comparison/preview tests need C1's clock (validated, C42), C22 lock-free compare built on `_read_history` (C33), C2+C34 preview warnings outside the txn, C32 endpoint-policy test, C12's TypeError test re-aimed (C33). `_draft_effect` reads `node.draft.candidate_hash` / `node.published.content_hash` (`ModelAgentNodeSnapshot`, workbench :330–348): names exist. `_historical_evidence(lock=False)` is the preview read; `lock=True` form per C28. Sabotages: controller `_structural_issues → ()` still REDs the incompatible test; reviewer's `_draft_effect` sabotage still REDs; plus C32's addition. | **Creates** `graph_configuration_rollback.py`, `tests/unit/test_graph_release_rollback.py`. **Modifies** `graph_configuration.py` (bases, `__all__`), `graph_release_history.py` (C33 extraction). Task 3a modifies the rollback module and unit file again. | C32 (policy in or out) and C35's flag need controller rulings; C34's de-duplication needs acceptance |
| 3a | `restore_release` template: `_lock_all_draft_agents` returns a list (C27), `PublicationConflict` positional order matches (:151–157), `_verify_rebased_draft` needs an ORM row (C21), `_validate_rollback_request` per C31 + C19, resets via `_assign_locked_candidate` after the core (C36), L3 per C28, refusals before any write (C26), matches-active fixture per C18. | **Modifies** rollback module, `graph_configuration_draft.py` (C36), the unit file. | Q7 confirmation (C35) before dispatch |
| 3b | PG: evidence via #267/#268 writers (C45), stages ×6 (C42 + C15), readiness negative proof (C30), Review Focus 1/2, pinned-runtime test with the recorded `AgentAssemblyContext` ctor (C25). Controller sabotage per C16. | **Creates** `tests/integration/test_graph_release_rollback_postgres.py`; **modifies** `test.yml` + a CI pin in `test_ci_collects_integration_tests.py` (the plan omits the pin; #269 and Task 1 each added one). | none |
| 4 | Orderings: C6 matcher; L3 `FOR UPDATE` matcher (C28); verdict outcome per C41; `_await_blocked_by` keywords (C41). Controller sabotage `exclusive=False` per C6; reviewer per plan. | **Creates** `test_graph_release_rollback_ordering_postgres.py`; **modifies** `test.yml` + CI pin. Task 5 appends to it. | none |
| 5 | 7 creators (C43); cleanup facts per C9/C45; reviewer sabotage per C17. | **Modifies** #269's `test_graph_release_session_ordering_postgres.py` (append) and Task 4's ordering file. | none |
| 6 | Routes in `agent_definitions.py` (C37), 403 for an actor issue (C31), log per C13 + C37, preview depends on the remote validator (C34) and the other four do not (C2), evidence wire widened atomically (C38), comparison diff keys (C46). | **Creates** `schemas/graph_release_history.py`, `tests/unit/test_graph_release_history_routes.py`, `tests/unit/test_graph_release_history_client_join.py` (C46). **Modifies** `routes/agent_definitions.py`, `schemas/graph_releases.py`, `frontend/src/api/agentDefinitions.ts` (evidence parser only), #269's `test_graph_release_client_join.py`, `test_graph_release_routes.py`, `releaseClient.test.ts`, `reviewAndPublishState.test.ts`, `ReviewAndPublishPage.test.tsx` fixtures, `frontend/tests/fixtures/mocks.ts` (C38). | C46's join file cannot pin TS parsers that Task 7 writes: Task 6's join test pins only the Python-side lists that already have TS mirrors (evidence), and Task 7 extends the join file with the new lists — sequential, same file |
| 7 | Reducer/gate/counter per C39; fixed names per C3; tab outside the preview block (C39); three-tab assertion (C4); count 8 (C40); warnings panel (C2). | **Creates** `ReleaseHistoryTab.tsx` + test. **Modifies** state, hook, page, `agentDefinitions.ts` (append), `releaseClient.test.ts`, `ReviewAndPublishPage.test.tsx`, `index.ts`, and the Task 6 join file (C46). | none |
| 8 | Fixed names (C3), (a) count and active-row assertion (C7), (e) covered already (C44), (h) per C40. | **Creates** `graph-release-history.spec.ts`; **must also add it to the e2e matrix in `test.yml`** (#269 Task 8 found this miss: `test_e2e_matrix_covers_specs.py`). | e2e-matrix enrolment missing from the plan's file list — add it |
| 9 | Expected values per C5; `real_route_stack` recipe (C25); evidence via the HTTP run/verdict routes (C45). | **Creates** the acceptance PG file; **modifies** `test.yml` + CI pin. | none |

## Producer/consumer table (Phase B)

| Producer → Consumer | Shared file / interface | Contract the consumer relies on | Hazard |
|---|---|---|---|
| #269 → 2, 3a | `_commit_locked_publication`, `_lock_all_draft_agents`, `_model_nodes`, `_validate_publication_request`, `PublicationRejected` | signatures in C26/C27/C31; called inside one `session.begin()` | editing `graph_configuration_publication.py` (forbidden by plan line 325) |
| #269 → 2, 3a | `_lock_current_parents` (+retry), AST scanner | first statement of a fresh txn (C29) | a second both-parent locker |
| #269 → 3a | `link_release_evidence` (via the core) | caller locks runs `FOR UPDATE ORDER BY id` first (C28) | linking unlocked runs |
| Task 1 → 2 | `_read_history`, `_release_definitions` (C33), `GraphVersionNotFound`, `ReleaseRef` | first-statement coherence; behaviour of `read_release_detail` unchanged | Task 1 tests must stay GREEN after the extraction |
| 2 → 3a | `_load_source`, `_structural_issues`, `_draft_effect`, `_historical_evidence(lock)` | identical checks in preview and restore (plan line 254) | two copies of a check |
| 3a → 3b, 4, 5, 9 | `restore_release`, `RestoredRelease`, refusal types | "Stable interfaces" + C21/C31 | — |
| draft module (#263–#269) → 3a | `_write_locked_content` → `_assign_locked_candidate` (C36) | save behaviour byte-identical | `changed` computed after assignment |
| #269 PG harness → 3b, 4, 5 | `_NoEvidenceGate`, `_save_prompt`, `_STAGE_MATCHERS`, `_install_commit_failure`, `_await_blocked_by`, `CREATORS`, `_seed` | imported by underscore name (C42, C43) | copies drift |
| 2, 3a → 6 | service outcomes and exceptions | mapping table (plan lines 887–892) + C31 403 + C37 log | — |
| 6 → 7 | the #270 wire + the widened evidence wire (C38) | exact-key parsers; join file (C46) | a Task 6-only wire change REDs the join test |
| #269 page → 7 | one reducer, `nextRequestIdRef`, the write-in-flight ref, `canPublish` (C39) | extended, never duplicated | m4 copied into rollback |
| 7 → 8 | `data-testid`s, fixed names (C3) | exact whole names within rows | — |
| 1, 3b, 4, 9 → CI | `integration-graph` block + CI pins; 8 → e2e matrix | one append per task | sequential edits of one block |

## Blocking summary for corrections 24–47 (with 1–23)

- **Before Task 2:** 1 (C1 helper, validated by 42), 2 + 34, 12 → resolved by 33, 20 → (a) disclosed by 35, (b) resolved by 32, 22 (via 33), 26, 27, 28, 29, 32 (**controller ruling: include the policy**), 33, 42. 35 is a flag, not a Task 2 blocker.
- **Before Task 3a:** 15, 16, 18, 19, 21, 31, 36, and **35 (user confirmation of Q7, or an explicit ruling to proceed on the default)**.
- **Before Task 3b:** 15, 30, 42, 45.
- **Before Task 4:** 6, 28, 41.
- **Before Task 5:** 9, 17, 43, 45.
- **Before Task 6:** 13, 37 (erratum to 8), 38, 46.
- **Before Task 7:** 3, 4 (confirmed by 39), 23 (resolved by 39), 39, 40.
- **Before Task 8:** 7, 40, 44, and the e2e-matrix enrolment (self-consistency table).
- **Before Task 9:** 5.
- **Task 10:** 10, 24, 30.

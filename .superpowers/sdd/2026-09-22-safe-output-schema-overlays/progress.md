# SDD ledger — plan: docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md

Task 1 base: `8c72a5a9192095e1b77986f6a4b63a10bcd2acb6` (immutable evidence in `TASK1_BASE`).
Reviewed #260 authority: `29e03411487476383b34101b7b34513dbb917f26`; proven ancestor of Task 1 base.
Corrections: `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/PLAN-CORRECTIONS.md`.

Environment baseline:
- `/Users/robert.whiffin/.pyenv/shims/python`, Python 3.11.0; `.venv` absent before and after tests.
- Shared site-packages only; no install, `uv`, `pip`, or environment creation.
- Implementation worktree is linked and isolated on `feat/schema-overlay-264`.

Cause baseline at `8c72a5a91`:
- `tests/unit/test_graph_definition_manifest.py` plus `tests/unit/test_agent_runtime.py`: 57 passed, 0 failed, 0 skipped.
- Warning causes: two repository Pydantic class-config deprecations, one repository `langchain-community` sunset warning, and two third-party Pydantic deprecations; exact paths/messages are in `reports/preflight-260.md`.

Task 0 phase A: complete — SDD workspace resolved; #260 ancestry, interpreter, `.venv`, new-file collisions, seven schemas, v1 identities/digests, manifest hash/serialization seams, test owners, per-task consistency, and every shared producer/consumer pair recorded.
Task 0 phase B: pending by design — refresh `INTEGRATION_BASE`, predecessor heads, exact owners/signatures, and cause baselines only after Task 1 and reviewed local #261/#263/#265 integration; it gates Task 2, not Task 1.
Task 1: dispatched (base `8c72a5a9192095e1b77986f6a4b63a10bcd2acb6`; implementer `/root/issue_264_task1`; brief `task-1-brief.md`; report `task-1-report.md`).
Task 1: implementer DONE at `4744b5d77b2b805646a5ba8f9a7a486e265e0553`; exactly three authorized files, focused 19 and combined 76 passed with zero skips and the five baseline warning causes unchanged.
Task 1: controller sabotage changed the executed v2 descriptor name to `speaker_notes` (`TASK1_CONTROLLER_SPEAKER_NOTES_SABOTAGE`); the exact descriptor test failed on `speaker_notes != diagnostic_notes`, restoration removed the marker, and the same test passed. Evidence: `task-1-controller-sabotage.md`.
Task 1: review failed — Spec ❌ / Task quality Needs fixes. Important: frozen `CanonicalFieldGuidance` semantics remain mutable through Pydantic's live `model_fields_set`, which changes serialization/validation/composition. Minor: direct boundary coverage is missing for blank/281-character diagnostic items and exact composed descriptor metadata. Reviewer independently removed canonical-collision reporting: RED 1 failed, restoration GREEN 1 passed, marker absent.
Task 1: fix round 1/5 dispatched to original implementer; covering files are `src/services/agent_schema_types.py`, `src/services/agent_schema_registry.py`, and `tests/unit/test_agent_schema_registry.py` only.
Task 1: fix round 1/5 committed at `abbf212c60ef31b4482ee6ee13d4d2ea8d5ca4aa`; rereview left 2 Important findings open: replaceable Pydantic private semantic state and broken `CanonicalFieldGuidance.model_copy(update=...)` from freezing Pydantic-owned field-set state.
Task 1: fix round 2/5 dispatched to original implementer; same three-file scope, TDD regression must prove private-state replacement cannot alter semantics and Pydantic `model_copy(update=...)` remains functional.
Task 1: fix round 2/5 committed at `82417e533a0d356aa110e736db5fb099b9586cac` — real RED was 2 failed/30 passed for private-state semantic replacement plus broken `model_copy(update=...)`; final focused 32 and combined 89 passed with zero skips and unchanged five-warning cause set.
Task 1: fix round 2/5 rereview left 1 Important finding open: direct mutation/removal/replacement of Pydantic `__dict__` semantic entries still changed serialization, validation, and composition; Pydantic fields-set/model-copy compatibility was addressed.
Task 1: fix round 3/5 dispatched to original implementer; regression covers successful direct field-entry mutation/removal/replacement and whole-`__dict__` replacement while preserving supplied/omitted/null semantics.
Task 1: fix round 3/5 implementation verified — real targeted RED was 5 failed/30 deselected; final focused 36 and combined 93 passed with zero skips and unchanged five-warning cause set. Commit is the fix-round commit containing this ledger line.
Task 1: fix round 3/5 rereview addressed direct-`__dict__` mutation but opened 1 Important Pydantic copy-contract regression: shallow/deep/trusted-update/field-set semantics were not preserved.
Task 1: fix round 4/5 implemented Pydantic-compatible protected shallow/deep/trusted-update copy kernels at `77223ae71`; genuine RED was 3 failed, final focused 39 and combined 96 passed with zero skips and unchanged five-warning cause set.
Task 1: fix round 4/5 rereview independently shared the shallow-copy outer extras mapping; RED 1 failed, exact restoration GREEN 1 passed. Prior Important ADDRESSED; no new Critical/Important findings; focused copy/mutation 9 and combined 96 passed.
Task 1: complete (commits `8c72a5a..1095ac2`, review clean).
Task 1: fix round 3/5 rereview left 1 Important finding open: slot-backed copies revalidated instead of preserving Pydantic shallow/deep identity, copied field-set, and trusted unvalidated-update behavior.
Task 1: fix round 4/5 implemented at the protected type boundary — real RED was 3 failed/36 deselected for shallow identity, copied field-set, and trusted invalid update; final focused 39 and combined 96 passed with zero skips and unchanged five-warning cause set. Commit is the fix-round commit containing this ledger line.

## REBASED onto the new integration head — 2026-09-24, controller
#265 integrated as merge commit `3ed8f9b6a` on `feat/langgraph-core`, which discharges this branch's phase-B predecessor gate. The controller rebased `feat/schema-overlay-264` from `ac69f62b6` onto `3ed8f9b6a`. New HEAD **`5bb2b36a2583bf4fb215165f8298d031e01a6d28`**.
Rebase evidence, not assertion. Pre-flight: this branch's own 18 commits touch exactly four non-artefact files (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md`, `src/services/agent_schema_registry.py`, `src/services/agent_schema_types.py`, `tests/unit/test_agent_schema_registry.py`), and `comm -12` against every file the integration history touched since `a94c907d2` returned **empty** — zero overlap — while both new source files were confirmed absent from `3ed8f9b6a`, so the rebase was conflict-free by construction rather than by luck. Post-rebase: triple check clean (empty `status --porcelain`, empty `diff HEAD`, empty `diff --cached`), `3ed8f9b6a` is an ancestor so the branch is 0 behind, 18 commits preserved, and `git range-diff a94c907d2..ac69f62b6 3ed8f9b6a..5bb2b36a2` reports **18 of 18 commits as exact `=` matches with zero drift lines**.
Rebase verification that actually mattered: Task 1's work **survives integrated #265**. Running this branch's own `tests/unit/test_agent_schema_registry.py` together with #265's now-integrated `test_agent_runtime.py`, `test_persisted_agent_runtime.py`, `test_graph_definition_manifest.py` and `test_prompt_assembler.py` gives **285 passed, 0 failed**, with import provenance proved inside this worktree for both `src` and `databricks_tellr`. So #265's rewrite of the schema-contract registry in `agent_runtime.py` did not break this branch's isolated registry kernel — which was the open risk the rebase existed to test.
Task 0 phase B: dispatched. It gates Task 2 and must discharge the four claims the corrections file explicitly deferred to it — correction 3's `agent_runtime_identity.py` and persisted-runtime owner signatures, correction 4's single landed writer/validator owner and order, correction 7's matrix composition without dropping the three named #261 PostgreSQL suites or accepting skips, and the blanket ruling at corrections line 62 that no final #261/#263/#265 signature or file claim is authoritative until phase B re-probes the concrete `INTEGRATION_BASE`.

## Task 0 phase B: COMPLETE — 2026-09-24
Re-probed `INTEGRATION_BASE` = `3ed8f9b6a`; HEAD `5bb2b36a2583bf4fb215165f8298d031e01a6d28` confirmed.
Import provenance proved in-worktree: `src` → `.worktrees/issue-264-schema-overlay/src/__init__.py`,
`databricks_tellr` → `.worktrees/issue-264-schema-overlay/packages/databricks-tellr/databricks_tellr/__init__.py`,
`src.services.agent_schema_registry` → this worktree; Python 3.11.0 at
`/Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python`; databricks-sdk 0.112.0; `.venv` absent
before and after every gate. Findings are corrections 8-26 in `PLAN-CORRECTIONS.md`.

Triple-check deviation at dispatch: porcelain was NOT empty — it carried the controller's own
uncommitted `progress.md` rebase addendum. `diff --cached` empty, HEAD as expected, source tree clean.
Recorded as correction 8 and carried into this phase's commit rather than silently absorbed.

The four deferred claims: correction 3 CONFIRMED with one CORRECTION (the persisted-runtime owner is
`persisted_graph_release.py`; `persisted_agent_runtime.py` does not exist) — corrections 9-11.
Correction 4 CONFIRMED and SHARPENED into two new defects (two validator tuples, not one;
the plan's upgrade precedence contradicts the landed upgrade) — corrections 15-18.
Correction 7 DISCHARGED: nothing dropped, no renames needed, three named #261 suites present and
green, one CI-enrolled PostgreSQL suite added to the matrix — correction 23.
The blanket ruling at corrections line 62 is swept across corrections 9-22 and 26.

### Cause baselines at `5bb2b36a2` — causes, not counts

**Full unit suite** (`tests/unit`, `-p no:randomly`): 14 failed, 5499 passed, 110 skipped, 136 warnings.
Failures are exactly the controller's known-inherited set — the same six files with the same per-file
counts — and **zero failures outside it**. Passed is 5499 rather than the integration head's 5460
because HEAD adds Task 1's `tests/unit/test_agent_schema_registry.py` (+39), which reconciles exactly.
The three cause classes are confirmed by traceback, not inferred from counts:

1. **9 × `ConversationGraphReleaseIntegrityError: no active Graph Release`** raised at
   `src/services/conversation_pins.py:83` — fixture class. Nodes: `test_deck_permission_routes` ×1,
   `test_session_duplicate` ×2, `test_style_exclusivity_persistence_boundary` ×1,
   `test_tour_ships_a_spec` ×5.
2. **3 × `AttributeError: '_FakeSession' object has no attribute 'execute'`** raised at
   `src/services/conversation_pins.py:79` — diverged test double. All three in
   `test_style_exclusivity_chokepoint`.
3. **2 × plain assertion failures**, unrelated to this epic, both in `test_deploy_autoscaling.py`:
   `:124 assert 'provisioned' == 'autoscaling'` and
   `:152 Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`

Refinement for later sweep sizing: cause classes 1 and 2 are **not** independent subsystems. Both
originate in `src/services/conversation_pins.py` at adjacent lines 79 and 83 — one production
chokepoint with two failure modes depending on whether the injected double implements `.execute`.
Twelve of the fourteen inherited failures funnel through that one call site. A fix there would move
both classes at once, so a future baseline that shows "12 fewer failures" is one repair, not twelve.

**Task 7 unit matrix** (the plan's 17-file gate, run verbatim): **805 passed, 0 failed, 0 skipped.**
This is the number Tasks 2-7 gate against; none of the 14 inherited failures lands in the matrix.

**PostgreSQL**, each file its own URL-prefixed invocation, zero skips recorded per file:
`test_graph_configuration_bootstrap_postgres` 2 passed · `test_graph_configuration_constraints_postgres`
7 passed · `test_persisted_graph_runtime_failures_postgres` 7 passed ·
`test_conversation_pin_migration_postgres` 1 passed · `test_conversation_pin_creation_postgres` 2 passed ·
`test_agent_definition_workbench_postgres` 15 passed. **Total 34 passed, 0 failed, 0 skipped.**
No database was created, dropped, migrated or altered by hand; fixtures owned their own throwaway databases.

**Warning cause set** for the matrix — 14 distinct locations, 8 repository / 6 third-party. Repository:
`src/api/routes/deck_contributors.py:51`, `src/api/routes/images.py:22`,
`src/api/routes/settings/contributors.py:49`, `src/api/routes/settings/deck_prompts.py:47`,
`src/api/routes/settings/slide_styles.py:50`, `src/api/schemas/requests.py:53`,
`src/api/schemas/responses.py:45` (all `PydanticDeprecatedSince20`, class-based `config`), and
`src/api/services/chat_service.py:19` (`DeprecationWarning`). Third-party:
`databricks_ai_bridge/vector_search_retriever_tool.py:107`, `unitycatalog/ai/langchain/toolkit.py:29`,
`pydantic/main.py:464`, `pyspark/sql/connect/utils.py:59`, `pyspark/sql/pandas/utils.py:51` and `:85`.
Compare this location set, not the 131/136 counts.

**Frontend baseline: DEFERRED, outstanding.** Not run — #262 Task 5 holds the lane exclusively, the
shared `node_modules` symlink has no per-worktree Vite `cacheDir`, and port 3000 is machine-global so
`reuseExistingServer: true` would test a sibling worktree's code. The four owed commands are recorded
verbatim in correction 24. No #264 task may claim matrix completion while this is open.

### Plan defects Tasks 2-7 must be corrected against
`SchemaContractIdentity` is defined twice and the plan names only the `SchemaOverlay` duplication
(c12) · there are two validator tuples and registering in the wrong one inverts the invalid-plus-stale
status (c16) · the plan's schema-upgrade precedence is the opposite of the landed assembly upgrade,
whose guard asserts `upgrade_calls == []` (c17) · ordinary saves already reject `schema_contract` with
`immutable_field`, so Task 4's "ordinary identity rejection" is landed not new (c18) · the recording
sink has no success channel at all, so "no success fields" can pass vacuously (c9) · the sink Protocol
is typed `-> BaseModel` while `ValidatedAgentOutput` is a dataclass, making Task 3's change breaking at
four sites (c9) · the compatibility loader hardcodes a literal v1 overlay that Task 2's grammar change
can RED (c11) · the CI guard requires a PostgreSQL suite the final matrix never runs (c23) · the branch
carries an artefact under the plan-forbidden obsolete path (c26).

Task 2 is now UNBLOCKED. Tasks 2-7 must be dispatched with `PLAN-CORRECTIONS.md` corrections 8-26 attached.

## Controller corrections arising from Task 0 phase B — three of mine, plus a durability fix
Phase B's re-probe corrected the controller three times and surfaced a data-loss risk. All four recorded here.
**Controller error 10 — the triple check was not clean at dispatch, and it was the controller's own fault.** Porcelain carried ` M .superpowers/sdd/.../progress.md`: the controller appended its rebase addendum to this ledger and left it uncommitted, then instructed the agent that the tree must be triple-check clean. `diff --cached` was empty, HEAD was correct and source was clean, so the dispatch was safe in substance — but the instruction and the state disagreed. The agent recorded it as its own correction 8 and carried the file into its commit rather than silently absorbing it, which is the right handling. Lesson: the controller must commit or explicitly declare its own ledger edits before asserting a clean tree to a subagent.
**Controller error 11 — the text-read join reads EIGHT files, not six.** The briefing said six. The agent's first sweep read only `test_prompt_assembler.py:915-1000`, returned three files, and it was about to record the controller's six-file claim as *overstated* — then widened and found constants at `:1275-1287` and direct reads at `:1353` and `:1361`, for **eight**. Had it trusted its own narrow probe it would have told Task 4 that its primary writer is not text-joined, which is exactly the defect class the briefing warned about. A mis-aimed probe caught by disbelief rather than by tooling, for the sixth time in this epic.
**Controller error 12 — `CUSTOM_ANCHORS` lives in `frontend/src/api/agentDefinitions.ts:28`, not `draftEditorState.ts`.** The briefing named the wrong home. `draftEditorState.ts:698` is its production *consumer*, which is what made the order load-bearing, and the join to the server's `_ANCHOR_RANK` at `prompt_assembler.py:111` is confirmed. The substance of the warning stands; its address was wrong.
**Durability fix.** The agent reported that `PLAN-CORRECTIONS.md` is not committed anywhere and that no plan in this repo tracks its corrections file, and asked rather than deciding. Controller verified: the only tracked `PLAN-CORRECTIONS.md` paths repo-wide are five obsolete `.ws4*-` files under `docs/superpowers/plans/`; **no active ticket's corrections file is tracked**, while `progress.md` and the task reports are force-added. So #262's 25 corrections, this ticket's 26 and #266's existed only on disk inside git-ignored worktree directories that a prune would destroy. Two actions taken: every active ticket's entire `.superpowers` tree is backed up outside the repository at `/Users/robert.whiffin/Documents/slide-gen-branch-eval/issue-258-sdd-backup-20260924/` (200 files across four tickets, each verified byte-identical with `diff -r`), and this ticket's corrections file is now **force-tracked** at commit `f368c97a0`, which is consistent with the already-force-added `progress.md` rather than a new convention. #262's and #265's were left alone deliberately: #262 has a reviewer holding its HEAD at `2ca0825fc` and #265's branch is already merged, so both rely on the backup.

## Task 0 phase B independent review: **GO for Task 2**
Report `task-0b-review.md` (441 lines). All eight plan defects are real and **none is WRONG**; five need amendment on magnitude or citation rather than direction. All baselines reproduce exactly: 14 failed / 5499 passed / 110 skipped with the six-file split 1/2/2/3/1/5, passes reconciling as 5460 + Task 1's 39 (verified), the Task 7 matrix at 805/0/0, PostgreSQL 2·7·7·1·2·15 = 34 with zero skips, and warnings tracked as 14 locations. Worktree left at `f368c97a0` with no commits.
Amendments Tasks 2-7 must carry, because five defects were stated too weakly or cited wrongly:
- **c12 UNDERSTATED and already load-bearing, not latent.** Live probe: `a == b` False, `isinstance` False, reprs byte-identical. The two *registries* already diverge — same digest, unequal identities — and Task 1's shipped code has a live `isinstance(existing_identity, SchemaContractIdentity)` gate at `agent_schema_registry.py:556` that a runtime-class identity **silently** falls through to the `is_dataclass` branch. Task 3 must treat this as a present defect.
- **c17 guard coverage understated and cites shifted.** The harmonisation sabotage REDs **6 tests, not 1**, and the guard REDs by a **raised exception**, not by the `upgrade_calls == []` assertion c17 names. Cites `:341`/`:349` are actually `:343`/`:350`.
- **c18 CONFIRMED on the prefix but MATERIALLY INCOMPLETE.** `_immutable_content_issues` has exactly **one** call site, `:304`, inside the trusted `save_draft_content`. The client-facing `save_editable_model_draft` **never calls it**, because it rebuilds the payload from stored content so the identities are unreachable. So a client sending `candidate.schema_contract` gets `extra_forbidden` under the `candidate.` prefix, **not** `immutable_field`. Task 4's "consumption not new work" reading is wrong for the client path. `_IMMUTABLE_DRAFT_FIELDS` is at **165-169**, not 161-165.
- **c9 CONFIRMED on vacuity, site count WRONG.** The vacuity is exact — `calls.append` precedes `callback()`. But there are **three** `invoke` definitions (`:22`, `:34`, `:51`), not four sites, and `canonical_output` **is** a `BaseModel`, so Task 3's typing change is a design choice rather than forced.
- **c11 MAGNITUDE UNDERSTATED roughly fourfold.** A tight sabotage of the literal alone REDs **30 tests across 4 files**: `test_agent_runtime.py` **20** (not 8), `test_agent_resolution_prompt.py` **7** (a file c11 omitted entirely), `test_deck_level_spec_change.py` 2, and bootstrap 1. c11's "8" counted call sites, not RED tests. Task 2/3 must know the real radius so an expected RED is not read as a second defect.
- **c23 CONFIRMED exactly, and the reviewer added the evidence phase B lacked — it ran the suite: 1 passed, zero skips.** So the ruling to add `test_conversation_pin_acceptance_postgres.py` to the matrix is safe rather than merely plausible.
Four deferred claims all DISCHARGED, with one addition: there are **four** `session.begin()` sites, not three — the fourth at `:376` is the read-only legacy-source reader — while exactly **one** `lock_version +=` exists repo-wide, at `:648`.
**Unfalsifiable claim 2 was MISCLASSIFIED, and the correction hands Task 2 an oracle it was told did not exist.** Phase B reported the "Packaged v1 content hash" column as unverified because it searched for a landed literal table. It should have **computed**: `definition_content_hash()` over `load_graph_v1_manifest().definitions` reproduces all seven values byte-for-byte. **The column is correct**, and Task 2's byte-identity gate therefore has a landed oracle. Claims 1, 3 and 4 are correctly classified, and the frontend deferral is correctly recorded with its four owed commands.
Chokepoint refinement CONFIRMED precisely and supersedes the two-subsystem framing: `_require_active_graph_release` at `:77` has an 8-line body with `db.execute(` at `:79` and the raise at `:83` — one function, adjacent lines, differing only on whether the test double implements `.execute`. Independently reproduced at 9 + 3 = **12 of 14**. One repair, not twelve.
Reviewer falsifications, both of which FAILED to break the claims — which is the result that matters. c16: post-stale registration yields `DraftSaveConflict` with `log == []`, so the validator never runs and its issues are **invisible**, while local registration yields `DraftContentRejected` with the exact issue; it included an aim check proving the marker runs for a *current* request. c17: the harmonisation sabotage REDs 6 including a route guard failing `assert 422 == 409`, so a stale upgrade flips 409 to 422 on the wire — precisely the #265 regression c17 predicted. Restored and re-GREEN at 281 (275 + 6).
**Five mis-aimed probes reported, including one that contaminated its own instrument** — the most self-critical disclosure in this epic. Its full-suite run read 5502 because its own 3-test probe file was still sitting in `tests/unit/`; collect-only gave 5626 with it and 5623 without. So phase B's 5499 stands and the reviewer's instrument was the thing at fault. The other four: a `.compatibility()` grep that came back empty because the calls are multi-line; a blast-radius run that returned completely empty because it invented a filename; a first c11 sabotage that measured a superset by breaking the manifest loader rather than the literal; and a wrong import module.
Outstanding for Tasks 2-7, from the reviewer: (1) Task 4/5 must handle the c18 gap — no immutable check exists on the client path, which is an independent second reason for c16's ruling; (2) Task 2 gets the seven verified content hashes plus a required decision between `mode='python'` (`()`) and `mode='json'` (`[]`) before claiming byte-identity; (3) Task 2/3 must carry c11's real 30-test radius; (4) Task 3 must fix the silently-failing isinstance gate at `agent_schema_registry.py:556`; (5) Task 7 may add the acceptance suite freely, and `test_claim_exclusivity_postgres.py` carries **1 xfail, not a skip**; (6) the controller must stop leaving ledger drift.
**Controller error 13, the same one for the third time.** The reviewer found `progress.md` still uncommitted — md5 unchanged at `06d9f752…` — and told the controller to commit or declare it before dispatching Task 2 so Task 2 does not burn its first probe on it. The controller appended to this ledger after the force-track commit and again left it dirty. Standing rule from here: **append to the ledger, then commit in the same action, before any dispatch that asserts a clean tree.** This entry is committed together with the fix.

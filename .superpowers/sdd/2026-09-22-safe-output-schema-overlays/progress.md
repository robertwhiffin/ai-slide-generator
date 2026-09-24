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

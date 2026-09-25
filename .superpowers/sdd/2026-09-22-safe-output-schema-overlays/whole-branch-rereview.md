# #264 whole-branch fix-wave re-review

Range: `FIX_BASE 9e7d447af0bfc12016b1e94ad21a6d6c79ce6e23 .. HEAD 077b527496d68f8888924f2a3790916bbfdc243b` (7 commits). The branch sits on `feat/langgraph-core` = `d72ad974d183f2d8330c2239b2e0f1132d3082d2`, and the merge-base equals the tip: 0 behind.
Reviewer: scoped re-review, 2026-09-25.

I did all measurement in the temporary detached worktree `/tmp/rereview-264` at the HEAD SHA. It has since been removed, and `git worktree list` no longer shows it. `.venv` was absent before and after every backend gate.

## Finding Verdicts

| Finding | Verdict | Evidence (measured unless marked "read") |
|---|---|---|
| **I1** v1 guidance | **ADDRESSED** | **Registry.** `agent_schema_registry.py:405` gives v1 an empty guidance set. My sabotage (`>= 1`) went RED 16/1051 on the matrix and 1/10 on PostgreSQL. The cross-seam test failed with `AssertionError: (1, 'description')`, i.e. the writer accepted what the runtime refused. **Wire.** Probed through the real route with a v1 architect body `{message, intent(+type), zzz}` plus `diagnostic_notes`. It returned 422 `invalid_draft` with four issues in insertion order: `message`, `intent`, `zzz` (all `overlay_unknown_canonical_field`, with the owned message), then `additional_optional_fields.0` (`overlay_optional_field_ineligible`). There was no state change. **The code-reuse claim holds.** `_REGISTRY_GRAMMAR["overlay_issues"] = dict(_OVERLAY_ISSUES)` (`:175`) is v2 digest material, so adding a new code would move all seven v2 digests. **Cross-seam test is not vacuous.** It covers 7 roles × {v1, v2 after the real upgrade} × 13 shapes, including forbidden-property, blank, empty-examples, ineligible, duplicate and collision cases. It asserts writer acceptance equals runtime execution in both directions, requires exactly 1 adapter call when the writer accepts and 0 when it rejects, and pins the accepted sets exactly: `{1: {"empty"}, 2: six legal shapes}`. **UI gate** (read, plus Vitest 225/225 and Playwright 60/60 green): canonical guidance textareas render only when `guidanceEditable={isV2Schema}`. |
| **I2** `diagnostic_notes` inputs | **ADDRESSED** | Read: `OptionalFieldRow` has no guidance props and no textareas. The descriptor text renders in the group `Code-owned guidance of diagnostic_notes`. Its absence is pinned in Vitest (`offers no description or examples input… (#264 I2)`, which asserts the only control is the checkbox) and in Playwright (`row.getByRole('textbox')` has count 0). Both suites are green at HEAD in the ticket worktree. I could not mutate the frontend, because the temp worktree has no `node_modules`; the implementer's WBFIX03 RED figure is unverified by me. |
| **I3** upgrade retention | **ADDRESSED (with ruling)** | **S2 re-run** (`replacement_overlay = SchemaOverlay()`): RED 7/1051 on the matrix, all `test_upgrade_content_to_v2_retains_a_non_empty_overlay_byte_for_byte[7 roles]`, and **0/10 on PostgreSQL**. This matches the report exactly. **Ruling: consistent with I1, and nothing is lost silently.** After I1, every writer-reachable v1 overlay is empty, so S2 is an equivalent mutant at every seam above the registry. The retention contract is pinned where it lives, in `upgrade_content_to_v2`, with a non-empty overlay compared byte-for-byte. A legacy v1 row with guidance is rejected with ordered issues and no write, and its raw jsonb, hash, lock, audit and artefacts are unchanged (unit and PG). That row was never runnable anyway, because the runtime refuses any non-empty v1 overlay. So rejecting it loses nothing, while carrying it forward would make the upgrade the only writer that admits an illegal v1 state. The cost is a UI escape gap; see N1. |
| **I4** log contract | **ADDRESSED; matches the user decision exactly** | **Comment.** `agent_runtime_identity.py:95-111` now states the 7-field error record and the 8-field success record, and that values never reach the log. **Names only.** The success record carries `additional_field_names: sorted(result.additional_fields)`, a plain `list[str]`. The error branch carries no success field. **Values stay where they belong.** The recording sink's `successes` still carry the frozen values; its error branch appends only `error_classes`. Diagnostics carry the values unchanged. **JSON probe** through the production `JSONFormatter`, with notes `[..]`, `None`, `[]` and absent: 0 handler errors. The names came out as `['diagnostic_notes']` ×3 and `[]` for absent. No note text appeared in any line. **Sabotage.** Values added back as an extra key: RED 5 (+ the env test). Values folded into the names field: RED 2 (+env). The copy removed (a `.keys()` view): RED 5 (+env), including the JSON-serializable test. Explicit `null`/`[]` dropped from the names: RED 2 (+env, `supplied1`, `supplied2`). |
| **I5** tool name | **ADDRESSED; the description restoration is endorsed** | **Probe at HEAD vs FIX_BASE, all 7 roles × v1 and v2.** The tool name now equals the canonical class name; FIX_BASE produced `…SchemaV{n}Overlay`. `additionalProperties: false` is present. Under v1 the parameters equal the canonical parameters apart from `additionalProperties`. The description equals the canonical one and is non-empty; FIX_BASE's composed description was empty. Before #264 (`d72ad974d`), the adapter received the canonical `OUTPUT_SCHEMAS` model, docstring included. So restoring `__doc__` returns v1 to its exact pre-#264 tool, which is within the finding's intent. **No digest or hash moved.** Calculated v1 digests = frozen = the PLAN-CORRECTIONS table ×7. The seven packaged v1 content hashes equal the table. Calculated v2 = frozen ×7. v2 digests, v1 hashes and upgraded-v2 hashes are identical between FIX_BASE and HEAD. **Sabotage** (name + `Composed`): RED 60/1051. |
| m1 | ADDRESSED | Read: `dict_type` removed. The terminal default is pinned by the new route test. |
| m2 | ADDRESSED | Read: `test_the_schema_upgrade_revalidates_its_target_before_writing[local, post]` pins no write in both phases. |
| m3 | ADDRESSED | Fresh interpreter with a drifted `OUTPUT_SCHEMAS["architect"]`: `import src.services.agent_schema_registry` raises `SchemaContractMaterialChangedError`, so it fails closed. Counting `AgentSchemaRegistry.__init__` across 35 `upgrade_content_to_v2` calls gives 0, so the check is not run per call. |
| m5 | ADDRESSED | Read: `routes/agent_definitions.py:411-426`. `EditableModelDraft` is a plain dataclass, so moving its construction out of the `try` cannot turn a former 422 into a 500 on any wire-valid body. |
| m6 | ADDRESSED | Read: the precondition test exists. The implementer's WBFIX16 is unverified by me. |
| m8 | ADDRESSED | Read, plus the green Vitest run: the matching-ID failure test is present. |
| m11 | ADDRESSED | `test_graph_nodes.py` diff: the helper body (+docstring, `calls = sink.calls`, two success assertions) and exactly 11 call-site argument swaps. `grep -c "_assert_traced("` = 12 (the definition + 11). No other line in #262's tests changed; this was the only #262 test file touched. The matrix is green. |
| m13 | ADDRESSED | Read: an undeclared-key row was added. The provider-error branch asserts `successes == []`. |
| m16 | ADDRESSED | Read: `optional_field_descriptor_material` is public, is used by the v2 digest and the wire schema, and is AST-guarded. The digests are unchanged (probe above). |

## New Breakage

**Critical:** none. **Important:** none.

**Minor** (none blocks the merge):
- **N1.** `frontend/src/components/Admin/AgentDefinitionWorkbench/OutputSchemaEditor.tsx:306-311`. The loose-override block excludes canonical and selectable names. Under v1, a stored canonical guidance entry is therefore now invisible, and on v2 so is a `field_overrides.diagnostic_notes` entry. That contradicts the block's own comment, "no stored guidance is hidden". Only a seeded or impossible state can reach this, but combined with the implementer's Concern 2 it leaves a legacy v1 row with an error the UI cannot clear. Recovery is by API only. Route this to a follow-up.
- **N2.** `agent_schema_registry.py:405-409`. Under v1 a real canonical field is reported as "Canonical field is not available for this agent." The wording is digest-constrained and is reachable only by direct API or a legacy row. Acceptable; a UI hint could explain it later.
- **N3.** No route-level unit test pins the v1 canonical-guidance 422 envelope. The service tests and the PG legacy test cover the issues, and my route probe shows the envelope is correct.
- **N4 (pre-existing).** The loose-override block still renders editable textareas under v1 for unknown names (the m9 fixture). The server rejects them.

## Out-of-Scope Observations

- jsonb reorders object keys, so after persistence "request insertion order" becomes the stored order. `definition_content_hash` uses `sort_keys=True`, so the hashes are unaffected. The new PG test documents this.
- The m12 needle, `"private"` vs `/private/tmp`, still REDs `test_runtime_logging_sink_success_record_is_identity_outcome_and_optional_projection_only` in any `/tmp` worktree. Confirmed by traceback as environmental.

## Sabotage evidence

Method, per mutation: a scripted substitution with the anchor count asserted to be 1; `grep -rn <marker> src tests frontend/src frontend/tests` gave 1 hit; the scopes were run; then `git checkout 077b527496d68f8888924f2a3790916bbfdc243b -- <file>` restored it. After each restore: marker hits 0, porcelain 0, diff vs HEAD 0, cached 0.

The matrix is the 17-file Task 7 list (`pytest -q -p no:randomly -p no:cacheprovider -rf`, both-path PYTHONPATH). At rest it reads 1050 passed + 1 env (m12). Every RED below is net of that env test.

| ID | Target | Mutation | RED | Failing tests |
|---|---|---|---|---|
| RR264M1 | `agent_schema_registry.py:405` | `version >= 1` | matrix 16/1051; PG overlay 1/10 | `test_v1_rejects_every_canonical_guidance…`×7, `test_every_overlay_the_writer_accepts…`×7, `test_invalid_client_overlay…[1-overlay_payload2]`, `test_a_legacy_v1_draft_with_guidance…`; PG `test_persisted_schema_upgrade_keeps_the_stored_overlay_byte_for_byte` |
| RR264M2A | `agent_runtime_identity.py:178` | a values dict added as `additional_fields` | 5 | `test_exact_optional_values…`×4, `test_the_identity_carries_the_session_ids…` |
| RR264M2B | same | values appended into the names list | 2 | `test_exact_optional_values…[supplied3]`, `test_the_success_log_record_is_json_serializable…` |
| RR264M2C | same | `.keys()` view instead of the plain sorted copy | 5 | `test_exact_optional_values…`×4, `test_the_success_log_record_is_json_serializable…` |
| RR264M2D | same | names only for truthy values | 2 | `test_exact_optional_values…[supplied1]`, `[supplied2]` |
| RR264M3 | `agent_schema_registry.py:500` | name + `Composed` | 60 | `test_the_model_facing_tool…`×14, `test_composed_v2_adapter_schema_is_bound…`×7, `test_every_model_driven_role_preserves…`×7, `test_persisted_v2_runtime_delegates…`×14, `test_explicit_persisted_v1_release…`×14, `…deck_brief…`×3, `test_persisted_runtime_uses_exact_release…` |
| RR264S2 | `agent_schema_registry.py:650` | `replacement_overlay = SchemaOverlay()` | matrix 7/1051; **PG overlay 0/10** | `test_upgrade_content_to_v2_retains_a_non_empty_overlay_byte_for_byte`×7. The PG zero is free within the writer-reachable states of that file (the I3 ruling). |

## Gates (at HEAD)

| Gate | Result |
|---|---|
| Full unit, 13:47–13:52 UTC | 7 failed / 5880 passed / 110 skipped. The failures are the 6 baseline nodes (deploy_autoscaling ×2, chokepoint ×3, persistence_boundary ×1) + the m12 env test. |
| Matrix | 1050 + 1 env |
| PostgreSQL, one invocation per file, `-rfs` | overlay 10, workbench 15, persisted_graph_runtime_failures 7, mixed_release_collaboration_acceptance 26. All passed, 0 skips. |
| Vitest, four files, ticket worktree | 225/225 |
| Playwright, chromium, `--workers=1` | 60/60. Port 3000 was free before and after. |

Not run by me: typecheck and ESLint.

## Verdict

**MERGE.** I1 through I5 and the nine listed Minors are addressed. The user's key-names-only decision is implemented exactly and is pinned. No digest or hash moved. The fix wave introduced no Critical or Important breakage.

Ticket worktree at the end: HEAD `077b52749`; `git status --porcelain`, `git diff` and `git diff --cached` are all empty. This review file is the only addition, under the ignored `.superpowers/`.

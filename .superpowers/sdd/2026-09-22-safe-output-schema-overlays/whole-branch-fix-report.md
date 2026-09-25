# #264 whole-branch fix wave: report

- FIX_BASE: `9e7d447af0bfc12016b1e94ad21a6d6c79ce6e23`
- Final code commit, pinned for every mutation restore: `b319c143236fe9631344cba4ad9e9061ee3e8c6f`
- Implementer: the single fix-wave agent, 2026-09-25.
- Mutation drivers: `/tmp/t264-wbfix/` only (`mut.py`, `gen_specs.py`, `specs.json`, `results.json`, `logs/`).

## Commits (FIX_BASE..HEAD)

| SHA | Subject |
|---|---|
| `b9f05fcd5` | fix: reject every non-empty overlay under schema contract v1 (#264) |
| `3b9d6b4d5` | fix: offer schema guidance inputs only where the server accepts them (#264) |
| `8dd04fb70` | test: pin the schema upgrade's overlay retention and its legacy v1 ruling (#264) |
| `4d5c2c753` | fix: log optional field names only, as a JSON-safe list (#264) |
| `9390e6bf7` | fix: keep the canonical tool name and description on composed schemas (#264) |
| `b319c1432` | fix: close the whole-branch review's listed minors (#264) |
| (this report) | docs: record the whole-branch fix wave (#264) |

## Findings

### I1: v1 rejects every non-empty overlay (must)

**Change.** `src/services/agent_schema_registry.py:400-405`. Under schema contract v1, `validate_overlay` now uses an empty guidance-editable field set (`guidance_names = canonical_names if identity.version >= 2 else {}`).
- Every `field_overrides` entry under v1 is reported in request insertion order.
- Each carries the existing code `overlay_unknown_canonical_field` at `candidate.schema_overlay.field_overrides.<field>`, with the message "Canonical field is not available for this agent."
- Optional names under v1 were already `overlay_optional_field_ineligible`, because v1's catalog is empty.

The runtime's own v1 guard (`agent_runtime.py:583-589`) is unchanged and stays as defence in depth.

**Why reuse this code rather than add a new one.**
- The plan's code list is closed ("Codes are exactly …").
- `_OVERLAY_ISSUES` is part of `_REGISTRY_GRAMMAR`, which is hashed into all seven frozen v2 digests. A new code would have moved every v2 digest.
- Treating v1's guidance set as empty is the exact counterpart of v1's empty optional catalog. The client routing needs no change: `candidate.schema_overlay*` already routes to the Output Schema tab.

**UI.** In `OutputSchemaEditor.tsx`, the `CanonicalFieldRow` guidance textareas render only when `guidanceEditable={isV2Schema}` (`:116`, `:279`).
- Under v1 each canonical field shows its protected labels only.
- The section text becomes "Schema Upgrade enables description and examples guidance."
- The Schema Upgrade button is unchanged.

**Tests.**
- `test_v1_rejects_every_canonical_guidance_because_it_has_no_overlay_grammar[7 roles]` (`test_agent_schema_registry.py:620`). RED before the fix for the right reason: v1 reported only the non-canonical name.
- Cross-seam test `test_every_overlay_the_writer_accepts_runs_and_every_one_the_runtime_refuses_is_rejected[7 roles]` (`test_graph_configuration_draft.py:2903`). For each role, under v1 and then v2 (after the real schema upgrade), it checks 13 overlay shapes:
  - Each shape goes through the real client save path (`save_editable_model_draft`).
  - If the writer accepts, the stored content is read back and run through `AgentRuntime`, and the adapter must be called exactly once.
  - If the writer rejects, the same content must be refused by the runtime with `PersistedConfigurationUnavailableError` and 0 adapter calls.
  - Writer acceptance must equal runtime execution for every shape.
  - Final pin: v1 accepts `{empty}` only; v2 accepts the six legal shapes.
  - RED 7/7 before the fix: `AssertionError: (1, 'description')`, i.e. the writer accepted what the runtime refused.
- The writer no-state-change matrix gains a v1-guidance row.
- Vitest: seven `… under v1 shows every canonical field as protected labels only, with no guidance input` rows.
- Playwright: the v1 test asserts no canonical guidance textbox.

**Existing tests kept under a legal v2 state.** Each still tests what it tested before; it now upgrades the schema contract first.
- `test_trusted_full_content_writer_carries_schema_overlay_through_shared_hash_seam`
- `test_valid_v2_trusted_content_save_uses_one_mapper_hash_and_audit`: both upgrades run, so the audit lock is 3.
- `test_valid_overlay_with_stale_lock_is_a_coherent_409`: the upgrade is the write that makes the lock stale.
- `test_invalid_client_overlay_rejects_with_no_state_change`: now parametrised by schema version. The blank-description and empty-examples rows run on v2.
- `test_a_client_overlay_never_reaches_the_protected_identity`
- The route test `test_put_schema_overlay_guidance_forbidden_property_is_domain_rejected`: upgrades through the route, then saves with `lock_version` 1.
- Vitest canonical-field tests and the workbench Output Schema tests: run on a v2 definition.
- The Playwright canonical save-and-reload test: runs on `workbenchWithSchemaV2()`.

### I2: no guidance inputs for `diagnostic_notes` (must)

**Change.** `OptionalFieldRow` (`OutputSchemaEditor.tsx:168`) no longer takes the guidance props or renders the two textareas.
- The descriptor's description and example render as read-only text in a group named `Code-owned guidance of diagnostic_notes` (`:208`).
- The row's only control is the selection checkbox.
- No reducer or hook path became dead: `schemaOverlayFieldDescriptionChanged` and `schemaOverlayFieldExamplesChanged` still serve the canonical rows.
- No state machine, counter or gate was added.

**Tests.**
- Vitest: `offers no description or examples input for the optional field (#264 I2)`, `shows the optional descriptor description and example as read-only code-owned text`, and the workbench tab test's "optional row has no textbox" assertion.
- Playwright: the v2 picker test asserts `row.getByRole('textbox')` has count 0, plus the code-owned text.
- Removed: the four Vitest tests that pinned the textareas' existence and change handlers.
- The disabled test now covers the canonical textareas.

### I3: overlay retention across the upgrade (must, test only)

**Ruling: a legacy v1 draft with guidance is REJECTED by the upgrade, not carried forward.**

How such a row can arise: only as pre-existing data seeded behind the writer.
- Bootstrap writes only empty v1 overlays.
- Before #264 no production writer could write an overlay at all. `EditableModelDraft` had no `schema_overlay`, and `save_draft_content` has no production caller.
- After I1 the writer cannot save v1 guidance.

The upgrade validates existing content first. That validation is the landed Task 4 precedence, which the plan requires: "existing-content validation issues retain their `candidate.schema_overlay…` fields". Such content breaks the one v1 rule every other writer and the runtime now enforce.

So the upgrade reports the ordered overlay issue and writes nothing. Carrying it forward would make the upgrade the only writer that accepts a v1 state the rest of the system refuses. The way out is an explicit empty-overlay save, which is legal under v1 and pinned; after it the upgrade succeeds.

**Consequence for S2.** Through the writer, S2 (the reviewer's mutation that swaps the stored overlay for an empty one) can now reach only an empty overlay, so it is an equivalent mutant within every writer-reachable state. The data-loss path is closed by I1 itself. S2 is RED where the retention contract lives, in `upgrade_content_to_v2`'s own test. It is RED 0 in PostgreSQL, and that zero means only "free within the writer's reachable states in that file".

**Tests.**
- `test_upgrade_content_to_v2_retains_a_non_empty_overlay_byte_for_byte[7 roles]` (`test_agent_schema_registry.py:1167`). It uses the real manifest carrier with a non-empty guidance-plus-selection overlay and checks:
  - the result is the same overlay object;
  - the `json.dumps` of the persisted `schema_overlay` value is identical, key order included;
  - the overlay is legal under the installed v2 identity.
- `test_a_legacy_v1_draft_with_guidance_is_rejected_by_the_upgrade_and_kept_byte_for_byte` (`test_graph_configuration_draft.py:3020`). The row is seeded behind the writer. The test asserts:
  - the ordered issues;
  - no write;
  - the stored column JSON is byte-identical;
  - the database snapshot is unchanged;
  - then the recovery: an explicit empty-overlay save, followed by a successful upgrade.
- PostgreSQL `test_persisted_schema_upgrade_keeps_the_stored_overlay_byte_for_byte` (`test_agent_schema_overlay_postgres.py:235`):
  - Reachable case: Builder's empty v1 overlay survives the upgrade with `schema_overlay::text` byte-identical.
  - Legacy case: seeded Architect guidance. The upgrade is rejected with ordered issues, and the raw jsonb text, hash, lock, audit and immutable artefacts are all unchanged.
  - Measured side fact: jsonb does not keep object key insertion order; it stores keys shortest first. So after persistence the issue order follows the stored order (`intent`, then `message`). The test documents this.

### I4: log contract, JSON safety, key names only (must)

**User decision (relayed by the controller):** the log carries optional field KEY NAMES only, never their values.

**Change.** `src/services/agent_runtime_identity.py:178`. The success record's field is now `additional_field_names`, a plain `list[str]`: `sorted(result.additional_fields)`, i.e. the names the model explicitly supplied.
- An explicit `null` or `[]` still counts as supplied; absence gives `[]`.
- It replaces `additional_fields`, the frozen `MappingProxyType` of values.
- Values still reach diagnostics and the recording sink's `successes` unchanged.

**Contract comment** (`:95-121`) and sink docstring (`:132-141`) now state exactly:
- the error record has 7 fields: five identity fields, `outcome="error"` and `error_class`;
- the success record has 8 fields: the same five, `outcome="success"`, `error_class=None` and `additional_field_names`;
- values never reach the log.

**Tests.**
- `SUCCESS_LOG_FIELDS` (`test_persisted_agent_runtime.py:919`) is now `PERMITTED | {"additional_field_names"}`, with the user's rule stated in its comment.
- `test_exact_optional_values_reach_diagnostics_and_both_sink_traces[4]` now asserts `additional_field_names == sorted(expected)` and that no note value is rendered into the record. The recording sink and diagnostics still get the exact values.
- New `test_the_success_log_record_is_json_serializable_with_optional_values_supplied` (`:1477`): `json.dumps` of every emitted field succeeds, and the names field is a `list`.
- All of these were RED before the fix: 7 failures, all from the missing `additional_field_names` attribute.

### I5: canonical tool name (same wave)

**Real call site.** `DatabricksModelAdapter.invoke` calls `ChatDatabricks.with_structured_output(schema)` (databricks_langchain):
- it names the forced tool `convert_to_openai_tool(schema)["function"]["name"]`;
- it runs `bind_tools([schema], tool_choice=…)`;
- it parses the call with `PydanticToolsParser`, keyed by `model_config["title"] or __name__`.

**Measured first.** A probe (`/tmp/t264-wbfix/i5_probe.py`, output in `i5_before.json` and `i5_after.json`) computed, before and after the change:
- the 7 v1 and 7 v2 digests, both from the registry calculation and from the runtime's v1 table;
- both protected-assembly digests;
- 21 manifest content hashes: v1, upgraded v2, and v2 with guidance.

All were byte-identical; only the 14 composed class names moved. No frozen material reads the composed class, so no NEEDS_CONTEXT.

**Change.** `agent_schema_registry.py:500-502`. `create_model(bundle.canonical_model.__name__, __base__=strict_base, __doc__=bundle.canonical_model.__doc__, …)`.
- The measurement also showed the composed tool had lost its description. The canonical docstring is the tool description, and the old composed class had none, so the tool description was `''`. The docstring is restored in the same line. **This goes one step beyond the brief's wording (name only); it is disclosed here.**
- `additionalProperties: false` stays, per AC3.

**Test.** `test_the_model_facing_tool_keeps_the_canonical_name_and_description[7 roles × v1, v2]` (`test_agent_schema_registry.py:688`). It asserts:
- tool name == canonical `__name__`;
- description == the canonical tool's description, and non-empty;
- parameters == the canonical parameters plus `additionalProperties: False` only;
- under v2 with guidance and a selection, the name is still canonical;
- a tool call under the canonical name parses into the composed model through `PydanticToolsParser`.

RED 14/14 before the fix. The two helper assertions that pinned `…SchemaV{n}Overlay` (`test_agent_runtime.py`, `test_persisted_agent_runtime.py`) now pin the canonical name.

### Minors

| Item | Change | Test |
|---|---|---|
| m1 | `routes/agent_definitions.py:163`: `dict_type` removed from the explicit set (behaviour-free; the terminal default serves it) | `test_a_dict_type_wire_error_is_strict_type_through_the_terminal_default` |
| m2 | none; F5 kept | `test_the_schema_upgrade_revalidates_its_target_before_writing[local, post]`: a validator that rejects only the v2 target, in either phase, means no write |
| m3 | `agent_schema_registry.py:576`: `_MODULE_REGISTRY = AgentSchemaRegistry()`; `upgrade_content_to_v2` uses it (`:643`). The frozen-digest check now also runs at import of the registry module; the draft module's import-time instance and the runtime's instance are unchanged | `test_upgrade_content_to_v2_reuses_the_module_registry` (0 constructions across 7 upgrades); `test_importing_the_registry_fails_closed_when_frozen_material_changed` (fresh interpreter, drifted Architect schema, import raises) |
| m5 | `routes/agent_definitions.py:411`: the assembly conversion moved out of the C1 `try`; the `try` wraps only `_domain_schema_overlay` | `test_the_overlay_type_error_catch_wraps_only_the_overlay_conversion` (a forced assembly `ValidationError` escapes as a 500, never a `candidate.schema_overlay` 422) |
| m6 | none | `test_no_canonical_output_schema_keeps_undeclared_top_level_keys` (all 14 bundles; aim check on an `extra="allow"` model) |
| m8 | none | `settles a Schema Upgrade failure on the matching request ID, keeping local edits (#264 m8)` (`draftEditorState.test.ts`) |
| m11 | `test_graph_nodes.py:2676`: `_assert_traced` now takes the recording sink and requires `len(successes) == len(calls)` with matching identities | the helper itself (see the mutation row) |
| m13 | none | undeclared-key row added to `test_invalid_output_logs_one_error_outcome_and_no_success_field`; the provider-error recording branch asserts `len(calls) == 1` and `successes == []` |
| m16 | `_descriptor_material` renamed to the public `optional_field_descriptor_material` (`agent_schema_registry.py:261`), used by the v2 digest and by `schemas/agent_definitions.py` | `test_no_module_imports_a_private_name_from_the_registry` (AST walk of `src`; aim check of at least 3 importers) |

**m11 deviation.** The helper received only `sink.calls`, so it could not reach `successes` by touching the helper alone. Its parameter became the sink, and the argument at its 11 call sites changed mechanically from `trace.sink.calls` to `trace.sink`. No other line of any #262 test changed.

## Clause-to-mutation table

Method, per row:
1. Triple check before the row (`git status --porcelain`, `git diff <pinned>`, `git diff --cached`) all empty.
2. Substitution applied by script with the anchor count asserted to be exactly 1.
3. Marker confirmed by `rg -n <marker> src frontend/src frontend/tests tests`: exactly the listed hits.
4. Scopes run.
5. Restore with `git checkout b319c143236fe9631344cba4ad9e9061ee3e8c6f -- <files>`.
6. Marker gone and triple check empty after the restore.

Markers sit on the mutated lines, not on length-sensitive lines. Any collection error would have shown as `ERRORS:n`; none occurred.

Declared scopes and GREEN at the pinned tree:

| Scope | Command | GREEN |
|---|---|---|
| matrix | the 17-file Task 7 matrix, `pytest -q -p no:randomly -p no:cacheprovider -rf` | 1051 passed |
| pg_overlay | `tests/integration/test_agent_schema_overlay_postgres.py` | 10 passed |
| nodes | `tests/unit/test_graph_nodes.py` | 142 passed |
| vitest4 | the four-file `npm run test:unit` command | 225 passed |
| playwright | `npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1` | 60 passed |

| Row | Clause | Mutation (marker) | Anchors | RED | Failing tests (scope) |
|---|---|---|---|---|---|
| I1-registry | v1 rejects every guidance | `guidance_names = canonical_names` (WBFIX01) | 1 | matrix 16/1051; pg 1/10 | `test_v1_rejects_every_canonical_guidance…`×7, `test_every_overlay_the_writer_accepts…`×7, `test_invalid_client_overlay…[1-overlay_payload2]`, `test_a_legacy_v1_draft_with_guidance…`; pg `test_persisted_schema_upgrade_keeps_the_stored_overlay_byte_for_byte` |
| I1-ui | v1 has no guidance inputs | `guidanceEditable` always true (WBFIX02) | 1 | vitest 8/225; pw 1/60 | `… under v1 shows every canonical field as protected labels only…`×7, `typing and navigation never save…`; pw `output schema tab: v1 shows Schema Upgrade button…` |
| I2-ui | optional row has no inputs | two textareas re-added to the optional row (WBFIX03) | 1 | vitest 3/225; pw 1/60 | `offers no description or examples input… (#264 I2)`, `disables the toggle and every canonical guidance input…`, `toggling the picker, typing guidance…`; pw `output schema tab: v2 shows diagnostic_notes picker…` |
| I3-S2 (reviewer S2) | upgrade keeps the overlay | `replacement_overlay = SchemaOverlay()` (WBFIX04) | 1 | **matrix 7/1051; pg 0/10** | `test_upgrade_content_to_v2_retains_a_non_empty_overlay_byte_for_byte`×7; pg 0 = free within the writer-reachable states of that file (see I3) |
| I3-reject-policy | the upgrade validates current content first | pre-upgrade `local_candidate_validators(current)` deleted (WBFIX05) | 1 | matrix 5/1051; pg 1/10 | `test_a_legacy_v1_draft…`, `test_an_invalid_plus_stale_schema_upgrade_is_an_ordered_422`, `test_the_schema_upgrade_validates_before_reporting_already_current`, `test_the_two_upgrades_deliberately_differ_in_precedence`, `test_the_schema_upgrade_revalidates_its_target…[local]`; pg `…keeps_the_stored_overlay_byte_for_byte` |
| I4-values-back | names only, never values | values added back as `additional_fields` (WBFIX06) | 1 | matrix 6/1051 | `test_exact_optional_values…`×4, `test_runtime_logging_sink_success_record…`, `test_the_identity_carries_the_session_ids…` |
| I4-json-copy | a plain JSON-safe copy | the frozen mapping passed as-is (WBFIX07) | 1 | matrix 6/1051 | `test_exact_optional_values…`×4, `test_runtime_logging_sink_success_record…`, `test_the_success_log_record_is_json_serializable…` |
| I5-name | canonical tool name | old `…SchemaV{n}Overlay` name restored (WBFIX08) | 1 | matrix 60/1051 | `test_the_model_facing_tool…`×14, `test_composed_v2_adapter_schema_is_bound…`×7, `test_every_model_driven_role_preserves…`×7, `test_explicit_persisted_v1_release…`×14, `test_persisted_v2_runtime_delegates…`×14, `…deck_brief…`×3, `test_persisted_runtime_uses_exact_release…` |
| I5-doc | canonical tool description | `__doc__=` removed (WBFIX09) | 1 | matrix 14/1051 | `test_the_model_facing_tool…`×14 |
| m1 | the terminal default serves `dict_type` | terminal `return "wbfix_default"` (WBFIX10) | 1 | matrix 2/1051 | `test_a_dict_type_wire_error…`, `test_put_schema_overlay_wire_type_error_uses_owned_message[schema_overlay1…]` |
| m2-local | F5 local on the target | `local(target)` deleted (WBFIX11) | 1 | matrix 1/1051 | `test_the_schema_upgrade_revalidates_its_target…[local_candidate_validators]` |
| m2-post | F5 post on the target | `post(target)` deleted (WBFIX12) | 1 | matrix 1/1051 | `…[post_stale_validators]` |
| m3-per-call | reuse the module registry | `AgentSchemaRegistry()` per call (WBFIX13) | 1 | matrix 1/1051 | `test_upgrade_content_to_v2_reuses_the_module_registry` |
| m3-import | digest check at import | module registry built with `__new__`, skipping the check (WBFIX14) | 1 | matrix 1/1051 | `test_importing_the_registry_fails_closed…` |
| m5 | the `try` wraps only the overlay | assembly conversion moved back inside the `try` (WBFIX15) | 1 | matrix 1/1051 | `test_the_overlay_type_error_catch_wraps_only_the_overlay_conversion` |
| m6 | no canonical model keeps extras | bundle canonical model subclassed with `extra="allow"` (WBFIX16) | 1 | matrix 75/1051 | includes `test_no_canonical_output_schema_keeps_undeclared_top_level_keys` (+74 bundle-dependent tests) |
| m8 | matching-ID failure settles | `schemaUpgradeFailed` returns `state` (WBFIX17) | 1 | vitest 1/225 | `settles a Schema Upgrade failure on the matching request ID… (#264 m8)` |
| m11 | traces require successes | recording sink drops the success append (WBFIX18) | 1 | **nodes 11/142 with the new helper; 0/142 with the pre-m11 helper** (from `9390e6bf7`, measured the same way and restored) | the 11 `_assert_traced` users |
| m13-undeclared | undeclared key at the logging sink | undeclared-key check disabled (WBFIX19) | 1 | matrix 4/1051 | includes the new `test_invalid_output_logs_one_error…[raw_output2]` |
| m13-provider | no success on a provider error | recording sink also appends a success in `except` (WBFIX20) | 1 | matrix 20/1051 | includes `test_provider_errors_cross_adapter_runtime_and_each_identity_sink[<lambda>0-…]`×12 |
| m16 | no private import | private alias re-added in the registry and imported by the schemas (WBFIX21, two files, 1 anchor each) | 1+1 | matrix 1/1051 | `test_no_module_imports_a_private_name_from_the_registry` |
| S1 (reviewer) | `_overlay_issue_field` projects every segment | `issue.path[:-1]` (WBFIX22) | 1 | **matrix 13/1051** (reviewer: 11/1004) | the reviewer's 11, now 12 since `test_invalid_client_overlay` gained a row, plus `test_a_legacy_v1_draft_with_guidance…` |

Every row ended `clean_after_restore = True` with its marker gone (`results.json`).

## Gates

| Gate | Command | Result |
|---|---|---|
| venv | `test ! -e .venv` before and after every backend gate | absent throughout |
| Full unit, 13:19:57 to 13:26:26 UTC | `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest tests/unit -q -p no:randomly -rf` | 6 failed / 5881 passed / 110 skipped. The 6 are exactly the baseline node IDs, and their causes were re-read by traceback: `test_deploy_autoscaling.py:124` `'provisioned' == 'autoscaling'`; `:152` provisioned called 0 times; `conversation_pins.py:79` `_FakeSession` has no `execute` (×3, chokepoint); `conversation_pins.py:83` no active Graph Release (persistence boundary). No failure outside that set. |
| 17-file Task 7 matrix | as in `task-7-brief.md`, with `-p no:randomly -p no:cacheprovider -rf` and both-path PYTHONPATH | 1051 passed / 0 failed (baseline 1004 + 47 new) |
| PostgreSQL, one invocation each | `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres … pytest -q -rs tests/integration/<file>` | bootstrap 2, constraints 7, persisted_graph_runtime_failures 7, conversation_pin_migration 1, conversation_pin_creation 2, agent_definition_workbench 15, agent_schema_overlay 10 (9 + 1 new), conversation_pin_acceptance 1, mixed_release_creation 14, conversation_creator_exclusions 4, shared_deck_mutation_migration 3, shared_deck_mutation_lifecycle 4, mixed_release_collaboration_acceptance 26, collaboration_history_api 30, shared_deck_mutation_attribution 60. All passed, 0 skips in every file. |
| Vitest | `(cd frontend && npm run test:unit -- <four files>)` | 225 passed (baseline 219, minus 4 removed I2 textarea tests, plus 7 v1 rows, 2 I2 rows and 1 m8 row) |
| Typecheck | `(cd frontend && npm run typecheck)` | exit 0 |
| ESLint | `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts)` | exit 0 |
| Playwright | `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)` | 60 passed. `lsof -i :3000` was empty before and after every run; nothing was left running. |
| ruff | `ruff check --output-format concise <11 changed .py files>`, compared with the same files at FIX_BASE | identical (125 findings, all pre-existing, all in `test_graph_nodes.py` and `test_agent_definition_workbench_routes.py`); no new finding. `ruff format --check` is not a gate and is not claimed. |

## Concerns

1. **The I3 ruling makes S2 RED at unit scope only.** Through the writer, S2 is an equivalent mutant for every reachable state, because I1 leaves only empty v1 overlays. The PostgreSQL 0/10 is scoped to that. If the controller prefers "retain" for legacy v1 guidance, the upgrade's pre-validation of the current content would need a v1-specific exemption. That would contradict I1's "writer, route and runtime agree" and the plan's existing-content rule, so it was not done.
2. **A seeded legacy v1 row with guidance is unsaveable from the UI.**
   - The client omits an unedited overlay, the server retains the stored one, and I1 rejects it.
   - The v1 UI no longer shows canonical guidance, so the UI offers no way to clear it.
   - The recovery is an explicit empty-overlay save through the API (pinned).
   - Only seeded data can reach this state. If the controller wants a UI escape, it is a small follow-up.
3. **jsonb reorders object keys** (shortest first), so after persistence "field overrides follow request insertion order" holds only for the stored order. This is pre-existing, and documented in the new PostgreSQL test.
4. **I5 also restored the tool description**, the canonical docstring. The old composed class had none, so the tool description had been `''`. This goes beyond the brief's "name" wording; it has the same root cause and is pinned by I5-doc.
5. **m11 changed the argument at 11 call sites** (`trace.sink.calls` to `trace.sink`), because the helper alone could not reach `successes`. No other line changed.
6. **m3 adds an import-time digest check to the registry module itself.** Importing `agent_schema_registry` now fails closed on drifted material, earlier than before. Existing instances are unchanged.
7. **The deferred m9 fixture still holds an impossible state.** The Architect `mocks.ts` fixture's `title` override renders loose-override textareas under v1. The new v1 Vitest test scopes its no-textbox assertion to the canonical groups and names that exception; it does not touch the fixture.
8. The recording-sink `successes` for the provider-error branch is now pinned. The same mutation also REDs 8 other tests at matrix scope; the table lists them in its count.

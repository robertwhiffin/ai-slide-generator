# #271 whole-branch review and epic #258 acceptance review (Task 14)

- **Reviewer:** final whole-branch + epic reviewer (Opus), 2026-09-27. No subagents, no commits, no pushes.
- **#271 range:** `INTEGRATION_BASE` `12a521dc7` (Merge #270) `..HEAD` `4ec1432a0` on `plan/lakebase-contract-acceptance-271`. 79 commits. `feat/langgraph-core` is still `12a521dc7` (not advanced). Code diff (excluding `docs/`, `.superpowers/` and the 1.4 MB `frontend/tests/fixtures/graphLifecycleContract.json`): 58 files, +8,117 / −690. Production files: `src/api/routes/chat.py`, `src/api/routes/sessions.py`, `src/api/services/chat_service.py`, `src/services/agent_runtime.py` (deletion), `src/services/persisted_graph_release.py`, `src/services/graph_definition_manifest.py` (docstring), `scripts/generate_graph_definition_manifest_v1.py` (deleted), three dependency manifests.
- **Epic range:** pre-epic base `60789f72f` (Merge ws4e) `..HEAD`. First epic merge `774703e44` (#260); then #263, #261, #265, #262, #264, the two identifier fixes, #266, #267, the xdist fix, #268, #269, #270 (`git log --merges --first-parent feat/langgraph-core`; `predecessor-heads.md`).
- **Read:** `progress.md` (whole), `PLAN-CORRECTIONS.md` C1–C52, `task-14-brief.md`, every `task-*-report.md` (concerns and fix rounds), the #266/#267/#268/#269/#270 whole-branch reviews, GitHub #258–#271 (read-only), every changed `src/` hunk in full, plus the surrounding lock sites, the chat routes, the job queue recovery path and the frontend chat client.

## Verdicts

- **#271: MERGE AFTER FIXES.** One Important (I1, frontend, small) and one ledger correction (m1). Nothing touches the lock order, the publication/rollback writers, pin resolution, or the deletion.
- **Epic #258: ACCEPTED LOCALLY PENDING m9** (and pending I1). No acceptance criterion is NOT MET.
- **Counts:** Critical 0 · Important 1 · Minor 6 new (m1–m6) plus 2 carried Task 11 Minors (m7, m8) · Observations 2.

---

## 1. #271 whole-branch review

### 1.1 Writer and lock deltas

`git diff 12a521dc7 HEAD -- src` adds and removes **no** `.add(`, `insert(`, `update(`, `delete(`, `.commit(`, `begin(` or `with_for_update`. **#271 adds no writer and no lock site.** Its only new database statements are reads:

| Site | Statement | Txn / locks | Rows written |
|---|---|---|---|
| `chat.py:516-525` `/chat/stream` → `resolve_engine_mode_or_unavailable` | `resolve_engine_mode`'s earliest-user-message read (unchanged) | own session; none | none |
| `chat.py:735-740` `/chat/async` | same | none | none (the user message and `chat_requests` row were written earlier by pre-existing code) |
| `chat_service.py:1171-1176` SSE turn-1 re-resolve | same | none | none (user message written just above by pre-existing code) |
| `sessions.py:322-329` `_active_graph_release_exists` (contribute route, only on `ConversationGraphReleaseIntegrityError`) | `SELECT graph_release.id WHERE effective_to IS NULL LIMIT 1` on the route's `db` | none | none |

`test_graph_parent_lock_is_single_sourced.py::test_only_lock_current_parents_locks_both_graph_parents` and the #270 writer scans (`test_graph_release_rollback.py::test_candidate_hash_writers_are_the_allowlisted_attribute_and_builder_sites`, `::test_restore_writes_through_the_one_publication_core`) are GREEN at HEAD.

### 1.2 C24/C47 fail-closed, C52 exception fix — per site

| Site | Fails closed? | Lock released? | Residue | Verdict |
|---|---|---|---|---|
| `/chat/stream` route (`chat.py:516`) | Yes: `PersistedConfigurationUnavailableError` → `HTTPException(503, {"code":"lakebase_unavailable",…})` before the response starts | Yes, explicitly (`:521-524`), since the SSE generator's `finally` never runs | Chat-generated-id path: the `user_sessions` row committed by `_maybe_create_session` (C47(e)/M1). Existing session: nothing (the message is persisted inside the service, not yet reached) | Sound backend. **Frontend renders the body as `[object Object]` (I1).** |
| `/chat/async` route (`chat.py:735`) | Yes: only the resolve call is wrapped (`_EngineModeUnresolvedError`), and its clause (`:773-777`) precedes `except Exception` | Yes, in that clause | User message + a `chat_requests` row left `pending` + (generated-id path) the empty session | Sound; **the ledger's "closed by stuck-request recovery" is false (m1)**; I1 applies |
| SSE turn-1 re-resolve (`chat_service.py:1171`) | Yes: yields the one safe `pinned_graph_configuration_unavailable` event, then raises; the route suppresses a second error event because `pinned_graph_configuration_error_emitted` is set (`chat.py:596-600`) | Yes, by the route generator's `finally` (`:603-607`) | User message | Sound |
| C52 `_context_manager_safe` (`persisted_graph_release.py:31-74`) | Lets exactly `__traceback__/__cause__/__context__/__suppress_context__/__notes__` through; declared fields stay frozen. `slots=True` dropped | n/a | n/a | Sound. I grepped `src` for any other `@dataclass(frozen=True…)` exception class: these two are the only ones. |
| Contribute route 503 (`sessions.py:366-372`) | Maps only "integrity error AND no active release" to the typed 503; any other integrity fault stays 500 | n/a | none | Sound (m4 is cosmetic) |

Two residual fail-closed weaknesses, both Minor:
- **m2.** Both route sites call `release_session_lock` inside the `except` before raising. That call opens its own DB session; in the very outage being handled it can raise, which turns the typed 503 into a plain 500 and leaves `is_processing=True` until the 300 s stale-lock timeout. Wrap the release in `try/except: logger.exception(...)` so the typed 503 always survives.
- **m1.** (see §5)

### 1.3 Deletion completeness (Task 12)

Every retired name has zero hits in `src`, `scripts`, `packages`, `frontend/src` and `.github` outside the guard's own `_RETIRED` literal: `AgentRuntime.compatibility`, `.compatibility(`, `CompatibilityResolvedDefinitionLoader`, `TEST_COMPATIBILITY_GRAPH_*`, `CodeOwnedAgentDefinitionSource`, `StaticDefinitionSource`, `AgentDefinitionSource`, `class AgentDefinition`, `_SchemaContractRegistry`, `RuntimeContractIdentityError`, `_PROTECTED_PROMPT_DIGEST`, `_SCHEMA_CONTRACT_DIGESTS` (the remaining hits are test-local frozen literals `V1_/V2_SCHEMA_CONTRACT_DIGESTS` and `EXPECTED_PROTECTED_PROMPT_DIGEST`), `generate_graph_definition_manifest`, `resolve_engine_mode_or(`.

| Guard (`tests/unit/test_lakebase_only_runtime_contract.py`) | Sound? |
|---|---|
| 1 `test_the_compatibility_runtime_is_gone` | Yes (`vars(module)` disjoint from 21 names) |
| 2 `test_no_src_module_reads_code_owned_agent_definitions` | Yes after fix round 1: absolute, `import x`, `from pkg import skills`, and every relative spelling resolve; the allowlist is exact both ways. Blind spots (aliases via `importlib`, `scripts/`, `packages/`) accepted as M3/M4 |
| 3 `test_the_bootstrap_manifest_is_read_only_by_bootstrap` | Yes (text match; reader set exact) |
| 4 `test_the_runtime_module_reads_no_code_default_model_configuration` | Yes (resolution path + `services/graph/**`) |
| 5 `test_production_runtimes_resolve_only_persisted_releases` | Yes (both factories) |
| Ledger `test_retained_bundle_ledger.py` | Yes (literals re-read; reviewer sabotage B RED) |

### 1.4 Contract and journey soundness (Tasks 6, 7, 10, 11)

- **Task 6 journey** (`graph_lifecycle_journey.py`): 17 stages pinned as literal `(code, name, ticket)` tuples; `in_stage` public. Failure attribution verified by my sabotage A (fault in #261 code labelled `[#261] S13`) and by the controller's C34/C6 sabotages.
- **Task 7 runtime**: exact `(agent_key, pin, version, revision_id, content_hash)` per role across v1/v2/v3 through the real `DatabricksModelAdapter`; `adapter.tool_bindings == []`; `with_structured_output` × every call; no identifiers in any prompt; key-name-only log records. My sabotage S0 and A both RED here.
- **Task 10 contract**: every body/request round-trips its model with exact keys; `lookahead`/`carried` pinned; the ancestry check on `recorded_at_commit` is fragile (m3).
- **Task 11 conversation journey**: `served.unmatched == []`, `lookahead == []`, `carried` pinned; UUID-only 404; the chat body carries no release id (reviewer sabotage RED). m1/m2 from its review remain (§5).
- **Contract gap feeding I1:** neither the recorded contract nor any frontend mock carries the #271 chat 503 body. `conversation-graph-version.spec.ts:110` mocks a chat-stream 503 with `detail: 'Graph runtime is unavailable'` (a string), which is not the wire shape `chat.py:63-66` now sends.

### 1.5 Findings

**I1 (Important) — the typed chat 503 renders as `[object Object]`.**
- `chat.py:74` sends `detail={"code": "lakebase_unavailable", "message": "…Please retry."}` (a dict).
- `frontend/src/services/api.ts:917-920` (`streamChat`) and `:1000-1002` (`submitChatAsync`) do `new ApiError(response.status, error.detail || '…')`. `ApiError` calls `super(message)`, so the message becomes `String(detail)`. Measured with node: `new ApiError(503, {code:…, message:…}).message === "[object Object]"`.
- `ChatPanel.tsx:336-338` shows `err.message`. So during the only outage C24 was designed for, both chat transports show the user `[object Object]` instead of "Conversation configuration is temporarily unavailable. Please retry."
- **Fix:** in both `api.ts` call sites, use `typeof error.detail === 'object' && error.detail?.message ? error.detail.message : (error.detail || '…')` (or a shared `detailMessage()` helper); change the mock at `conversation-graph-version.spec.ts:110` (and any other chat 503 mock) to the real dict body; add one Vitest on `api.ts` for each transport, sabotage-verified. The backend body is right; keep it.

Minor findings m1–m7 and observations are listed in §5.

### 1.6 Failure attribution and rollback/no-write

- Attribution: S0 (`persisted_graph_release.py`, #261/#271 seam) → `[#261] S13`; A (`conversation_pins.py`, #261) → `[#261] S13`; B (`graph_release_evidence.py`, #269) → the #268/#269 owner unit test (the journey does not exercise supersede; see §7).
- No-write on every failure-matrix case: the 22 cases in `test_lakebase_contract_failures_postgres.py` assert the before/after state with the documented residue only; all GREEN (22/22, zero skips).

---

## 2. Epic acceptance (#258 and #259–#271)

#258 has no checkbox list of its own: its 60 user stories and Implementation Decisions map one-to-one onto the child tickets below (stories 1–2 → #260/#259; 3–8 → #263/#266; 9–11 → #264; 12–15 → #265; 16–18 → #263/#268; 19–29 → #267; 30–32 → #268; 33–37 → #269; 38–41 → #270; 42–46 → #261/#262; 47–51 → #260/#261/#271; 52–58 → cross-cutting, below; 59 → #268; 60 → #259/#271).

**Summary:** 111 child ACs. **MET 108** (7 of them covered-with-ruling) · **PARTIAL 2** · **NOT MET 0** · **NOT VERIFIED 1**.

Non-MET items:
- **#266 AC1 / m9 — NOT VERIFIED.** The live `serving-endpoints get` shape for pay-per-token system endpoints (is `config_update` always present?) is unverified. `model_endpoint_catalog.py:262-270` rejects an absent value, and every draft save revalidates, so if absent, every save of the seeded role fails `endpoint_not_ready` on a real workspace. Blocked on the user's authorisation for a read-only dev-workspace probe (C43). Not a fail.
- **#268 AC7 — PARTIAL.** Retention (latest 20, protected evidence kept) is implemented and tested (`test_agent_definition_workbench_postgres.py::test_postgres_cleanup_always_retains_a_linked_run`, `::test_postgres_cleanup_retains_an_eligible_approval_outside_the_window`), but `cleanup_unpublished_test_runs` (`agent_test_workbench.py:1647`) has **no production caller** (#268 Q1). The #258 decision "unpublished test history is bounded" is therefore not enforced.
- **#271 AC3 — PARTIAL until I1.** Backend fails explicitly and preserves state (with the ratified residue), but the user-visible failure for "unavailable Lakebase" is `[object Object]`.

Covered-with-ruling (MET): #259 AC6 (compatibility parity tests deleted by #271 AC10; v1 now pinned by `test_prompt_assembler.py::test_v1_assembly_matches_independent_historical_replay`); #267 AC3 (warning only, not server-enforced, P7); #267 AC10 (tracing diverges by ruling R1: candidate runs use a pass-through sink plus their own record); #270 AC4/AC7 (Q7 kept-edit, C32 policy, OQ9 remote check warning-only); #271 AC3 residue (C47(e)); #262 AC5 (warning on ≥2 persisted versions only; legacy does not warn).

### AC table (owner test by file::test; "u/" = `tests/unit`, "i/" = `tests/integration`, "fe/" = `frontend/src`, "e2e/" = `frontend/tests/e2e`)

| AC | Owner test | Ruling |
|---|---|---|
| 259-1 seven roles via one runtime | u/test_persisted_agent_runtime.py::test_composed_v2_adapter_schema_is_bound_for_every_role; i/test_graph_lifecycle_runtime_postgres.py::test_every_pinned_release_drives_its_own_revisions_through_state_fan_out_and_traces | MET |
| 259-2 Foreman not a definition | u/test_graph_definition_manifest.py::test_manifest_contains_no_foreman_or_tool_grants; u/test_graph_builder.py::test_no_send_targets_the_foreman | MET |
| 259-3 bundle version+digest identities | u/test_graph_definition_manifest.py::test_stored_identity_resolves_the_exact_role_and_version_bundle; u/test_retained_bundle_ledger.py | MET |
| 259-4 unknown role / bundle / schema fail | u/test_prompt_assembler.py::test_unknown_bundle_identity_has_typed_early_failure; u/test_agent_runtime.py::test_incompatible_schema_contract_fails_before_model_invocation; i/test_graph_configuration_constraints_postgres.py::test_postgres_rejects_unknown_role_duplicate_hash_and_cross_role_mapping | MET |
| 259-5 tool grants inert | u/test_agent_runtime.py::test_databricks_model_adapter_never_binds_legacy_tool_grants; Task 7 `adapter.tool_bindings == []` | MET |
| 259-6 parity | u/test_prompt_assembler.py::test_v1_assembly_matches_independent_historical_replay | MET (ruling: adapter deleted by #271 AC10) |
| 260-1 fresh bootstrap once | u/test_graph_configuration_bootstrap.py::test_fresh_bootstrap_creates_exact_complete_v1 | MET |
| 260-2 manifest captures endpoint/content/bundles | u/test_graph_definition_manifest.py::test_manifest_assembly_replays_exact_runtime_prompt, ::test_hash_covers_every_semantic_field | MET |
| 260-3 DB constraints | i/test_graph_configuration_constraints_postgres.py (66, incl. ::test_postgres_enforces_one_active_release_valid_intervals_and_singleton_draft) | MET |
| 260-4 idempotent restart | i/test_graph_configuration_bootstrap_postgres.py::test_two_bootstraps_observe_second_backend_waiting_on_advisory_lock | MET |
| 260-5 admin API | u/test_agent_definition_workbench_routes.py::test_admin_workbench_returns_exact_typed_v1_contract | MET |
| 260-6 UI seven + read-only Foreman | fe/…/AgentDefinitionWorkbench.test.tsx "replaces the model definition tabs with only the deterministic Foreman explanation"; e2e/graph-release-admin-journey.spec.ts test 1 | MET |
| 260-7 non-admin cannot read | u/test_admin_route_authorization_inventory.py::test_non_admin_is_denied_before_body_or_service_is_read (24 routes) | MET |
| 260-8 PG + FE coverage | as above | MET |
| 261-1 migration/backfill/null legacy | i/test_conversation_pin_migration_postgres.py::test_postgres_migrates_and_backfills_conversation_pins_deterministically | MET |
| 261-2 root locks and verifies active | u/test_conversation_pin_creation.py::test_graph_capable_root_is_pinned_to_the_locked_active_release | MET |
| 261-3 state + every fan-out carries pin | i/test_graph_lifecycle_runtime_postgres.py::test_every_pinned_release_drives_its_own_revisions_through_state_fan_out_and_traces | MET |
| 261-4 exact persisted revisions + bundles | u/test_persisted_graph_release.py::test_resolves_v1_and_v2_by_their_persisted_ids_not_active_release; i/…runtime::test_every_readable_release_executes_with_its_own_bundles_after_it_stops_being_active | MET |
| 261-5 traces | same S13 test (identity records); u/test_graph_nodes.py::test_the_persisted_mutation_event_agrees_with_the_runtime_trace | MET |
| 261-6 UI version + start-latest | fe/Conversation/GraphVersionStatus.test.tsx "offers Start latest only when the pinned graph is older"; e2e/conversation-graph-version.spec.ts "Start latest creates graph-capable B without mutating older A" | MET |
| 261-7 explicit failures, no substitution | i/test_lakebase_contract_failures_postgres.py::test_a_lost_pinned_release_fails_the_turn_safely_and_preserves_state; i/test_persisted_graph_runtime_failures_postgres.py::test_database_failure_is_safe_and_does_not_attempt_an_active_release | MET |
| 261-8 real PG + shipped seam | i/test_conversation_pin_acceptance_postgres.py::test_persisted_conversation_pins_drive_three_real_compiled_graph_turns | MET |
| 262-1 other creators lock + pin | i/test_mixed_release_creation_postgres.py::test_publication_first_retries_each_creator_to_exact_r2 (7 creators) | MET |
| 262-2 pins never change | i/test_mixed_release_collaboration_acceptance_postgres.py::test_no_pin_moved_under_the_whole_write_sequence | MET |
| 262-3 contributor may be newer | i/…collaboration_acceptance::test_publication_first_pins_the_creator_to_exact_r2_and_attributes_r2 | MET |
| 262-4 mutation+trace attribution | i/…collaboration_acceptance::test_every_writer_records_one_root_deck_with_its_own_actor_and_release | MET |
| 262-5 mixed warning | fe/Conversation/MixedReleaseWarning.test.tsx "warns when one deck carries changes from two persisted Graph Versions"; e2e/mixed-release-collaboration.spec.ts | MET (ruling: legacy does not warn) |
| 262-6 history grouped, never root-labelled | i/…collaboration_acceptance::test_history_groups_and_warns_without_labelling_the_deck_with_the_root_version | MET |
| 262-7 both lock orders | i/test_mixed_release_creation_postgres.py::test_creation_first_holds_r1_until_each_creator_flushes + ::test_publication_first_… | MET |
| 262-8 FE coverage | e2e/graph-release-conversation-journey.spec.ts (6) | MET |
| 263-1 edit prompt/endpoint/params | e2e/graph-release-admin-journey.spec.ts test 2 | MET |
| 263-2 save validates, hashes, principal, lock++ | u/test_agent_definition_workbench_routes.py::test_put_requires_nonblank_trusted_principal_before_write; u/test_graph_configuration_draft.py::test_each_editable_field_rebuilds_the_complete_canonical_hash | MET |
| 263-3 hash covers everything | u/test_graph_definition_content_mapping.py::test_canonical_hash_covers_every_persisted_content_path | MET |
| 263-4 stale save conflict + recovery | i/test_agent_definition_workbench_postgres.py::test_real_upgrade_route_rejects_a_stale_lock_with_a_null_candidate_conflict; fe/…/AgentDefinitionWorkbench.test.tsx "dismisses only the recovery copy after Reload server without writing" | MET |
| 263-5 typing never writes | fe/…/AgentDefinitionWorkbench.test.tsx "typing and navigation never save…" | MET |
| 263-6 old-hash evidence inapplicable | i/test_agent_definition_workbench_postgres.py::test_postgres_readiness_ignores_old_hash_approvals_after_a_real_save | MET |
| 263-7 Clean/Unsaved/Needs test | fe/…/draftEditorState.test.ts (owner `:1115`) | MET |
| 263-8 admin-only + route + PW | u/…routes::test_non_admin_put_rejects_before_body_or_writer_and_does_not_echo_secrets; e2e/admin-route-gate.spec.ts | MET |
| 264-1 edit guidance, add/remove optional | u/test_agent_schema_registry.py (guidance suite); fe/…/OutputSchemaEditor.test.tsx | MET |
| 264-2 canonical changes rejected field-level | u/test_agent_schema_registry.py::test_v1_rejects_every_canonical_guidance_because_it_has_no_overlay_grammar; u/test_graph_definition_manifest.py::test_v2_rules_reject_unknown_vocabulary_extras_and_wrong_types | MET |
| 264-3 dynamic schema forbids extras | u/test_agent_schema_registry.py::test_no_canonical_output_schema_keeps_undeclared_top_level_keys | MET |
| 264-4 separate validation, overlay kept in diagnostics/traces | u/test_agent_schema_registry.py::test_canonical_and_optional_validation_fail_with_distinct_diagnostics; u/test_persisted_agent_runtime.py::test_exact_optional_values_reach_diagnostics_and_both_sink_traces | MET |
| 264-5 graph consumes canonical only | u/test_persisted_agent_runtime.py::test_composed_v2_schema_carries_field_override_guidance_without_touching_canonical; Task 7 v2 builder `diagnostic_notes` present only in `additional_field_names` | MET |
| 264-6 editor distinguishes | fe/…/OutputSchemaEditor.test.tsx | MET |
| 264-7 API cannot bypass | u/…routes::test_put_schema_overlay_type_field_is_rejected_as_extra_forbidden, ::test_put_schema_overlay_guidance_forbidden_property_is_domain_rejected | MET |
| 264-8 tests per mutation | i/test_agent_schema_overlay_postgres.py (10) | MET |
| 265-1 protected stages | u/…routes::test_workbench_get_exposes_the_exact_server_derived_v1_protected_stage_view; u/test_prompt_assembler.py::test_v2_stage_order_selects_one_environment_and_role_notice | MET |
| 265-2 custom blocks within anchors | u/test_prompt_assembler.py::test_custom_blocks_preserve_sibling_order_and_anchor_provenance, ::test_server_accepts_every_anchor_order_the_client_reducer_can_build | MET |
| 265-3 closed conditions | u/test_prompt_assembler.py::test_client_condition_and_anchor_vocabularies_match_the_server | MET |
| 265-4 invalid plans rejected pre-model | u/test_prompt_assembler.py::test_corrupt_protected_plans_are_rejected_by_exact_issue_type, ::test_semantic_multi_error_tuple_is_complete_and_assembly_emits_nothing | MET |
| 265-5 untrusted delimiter every role | u/test_prompt_assembler.py::test_hostile_payload_is_once_inside_owned_boundary, ::test_serialization_delimiter_and_anchor_contract_values_are_pinned | MET |
| 265-6 protected change = new version/digest | u/test_prompt_assembler.py::test_v2_identity_digest_is_pinned_in_a_second_committed_file; u/test_retained_bundle_ledger.py | MET |
| 265-7 UI displays protected read-only | fe/…/AssemblyEditor.test.tsx "renders every required Graph Version 1 protected row with exact locked values" | MET |
| 265-8 adversarial per role | u/test_prompt_assembler.py::test_hostile_payload_is_once_inside_owned_boundary | MET |
| 266-1 first-party contract evidence | `docs/research/2026-09-22-databricks-model-endpoint-discovery.md`; u/test_model_endpoint_catalog.py | **NOT VERIFIED (m9)** |
| 266-2 searchable, refreshable list | fe/…/AgentDefinitionWorkbench.test.tsx "exposes Refresh models, a labelled search, exact-name entries…" | MET |
| 266-3 custom name, never URL | u/test_model_endpoint_catalog.py::test_validate_endpoint_name_policy_rejects_every_url_shape | MET |
| 266-4 exact names only | u/test_model_endpoint_catalog.py::test_validate_endpoint_name_policy_preserves_accepted_input_verbatim | MET |
| 266-5 seeded Opus stays exact | u/test_model_endpoint_catalog.py::test_list_system_models_selects_foundation_endpoints_once_and_sorts_exact_names; bootstrap v1 exact-endpoint test | MET |
| 266-6 clear observable errors | u/test_model_endpoint_catalog.py::test_list_system_models_keeps_forbidden_and_unavailable_observable, ::test_validate_custom_endpoint_remote_maps_exact_outcomes; u/test_model_endpoint_probe.py::test_model_endpoint_probe_binding_rejection_is_unsupported | MET |
| 266-7 injected adapter + fakes | u/test_model_endpoint_catalog.py::test_fake_catalog_queues_discovery_and_name_keyed_validation_outcomes; u/test_model_endpoint_probe.py::test_model_endpoint_probe_route_production_dependency_is_the_databricks_probe | MET |
| 266-8 refresh/empty/failure recovery | fe/…/AgentDefinitionWorkbench.test.tsx "returns an empty list for an empty success", "a network failure is a retryable alert, not an empty catalog" | MET |
| 267-1 smoke cases seeded | i/test_graph_configuration_bootstrap_postgres.py::test_ac1_bootstrap_seeds_seven_required_active_cases_matching_smoke_payloads | MET |
| 267-2 case CRUD + versions | u/…routes::test_put_test_case_on_a_superseded_version_is_409_stale, ::test_delete_test_case_deactivates_and_returns_the_snapshot | MET |
| 267-3 synthetic only + warning | fe/…/TestRunPanel.test.tsx (warning) | MET (ruling P7: UI-only) |
| 267-4 isolated run, no writes | u/test_agent_runtime.py::test_run_candidate_runs_every_role_through_the_fake_and_bypasses_the_identity_sink; journey S07 (`[#267]`, C48 sink check) | MET |
| 267-5 evidence incl. token usage | u/test_agent_runtime.py::test_an_observed_real_provider_run_records_the_reported_token_usage (the #267 I-1 fix) | MET |
| 267-6 baseline stored, explicit rerun | u/…routes::test_a_candidate_run_after_a_baseline_carries_the_stored_baseline; u/test_agent_test_workbench.py::test_a_baseline_rerun_goes_through_the_published_entry_on_the_active_release | MET |
| 267-7 "baseline not recorded" | fe/…/TestRunPanel.test.tsx `test_no_baseline_is_shown_before_one_is_run` equivalent | MET |
| 267-8 failures persisted, not approvable | DDL `ck_agent_test_run_approved_only_if_completed_and_passing`; u/test_agent_test_workbench.py::test_an_undeclared_output_field_is_incomplete_with_its_raw_keys_and_issue | MET |
| 267-9 Input/Compare/Checks | fe/…/TestRunPanel.test.tsx (owner `:303`) | MET |
| 267-10 shared seam | u/test_agent_runtime.py (prompt/schema/config equality with `run`, one binding helper) | MET (ruling R1: tracing diverges) |
| 268-1 verdict with reviewer/time/notes | u/…routes::test_a_verdict_returns_200_evidence_with_the_principal_as_reviewer | MET |
| 268-2 same admin may do all; audited | journey S03–S11 (one `ADMIN` actor, per-row principal) | MET |
| 268-3 only completed+passing approvable | DDL check + u/test_agent_test_workbench.py verdict eligibility suite | MET |
| 268-4 ready iff every required case approved at hash+version | u/test_graph_release_evidence.py::test_gate_and_readiness_agree_on_every_eligibility_term (sabotage B RED here) | MET |
| 268-5 save invalidates, history intact | i/test_agent_definition_workbench_postgres.py::test_postgres_readiness_ignores_old_hash_approvals_after_a_real_save | MET |
| 268-6 precise gaps drive UI states | u/test_graph_release_evidence.py::test_several_required_cases_of_one_role_are_gaps_in_id_order; fe/…/verdictReadinessClient.test.ts | MET |
| 268-7 bounded cleanup | i/test_agent_definition_workbench_postgres.py::test_postgres_cleanup_retains_an_eligible_approval_outside_the_window | **PARTIAL (no production caller, Q1)** |
| 268-8 cleanup/readiness tests | as above + ::test_postgres_cleanup_deletes_a_stale_case_version_approval | MET |
| 268-9 admin-only | u/…routes::test_verdict_and_readiness_routes_deny_non_admins_before_body_or_service | MET |
| 269-1 release page | fe/GraphRelease/ReviewAndPublishPage.test.tsx; e2e/graph-release-review.spec.ts (9) | MET |
| 269-2 locks + revalidation | i/test_graph_release_publication_postgres.py::test_publication_lock_statement_sequence | MET |
| 269-3 one transaction writes all | i/test_graph_release_publication_postgres.py::test_publication_is_exact_and_contiguous_on_postgresql | MET |
| 269-4 reuse unchanged revisions | i/…publication::test_reverted_content_reuses_the_older_revision | MET |
| 269-5 all-or-nothing | i/…publication::test_injected_failure_rolls_back_every_row; i/test_graph_release_evidence_postgres.py::test_injected_failure_with_evidence_rolls_back_every_row | MET |
| 269-6 one winner, one stale | i/…publication::test_two_publishers_one_winner_one_exact_stale_conflict | MET |
| 269-7 cleanup vs publication | i/test_graph_release_evidence_postgres.py::test_cleanup_first_then_publication, ::test_publication_first_then_cleanup | MET |
| 269-8 new pins new, old retain | i/test_graph_release_session_ordering_postgres.py::test_new_conversation_after_publication_pins_new_and_old_retains | MET |
| 269-9 both orders on PG | i/…session_ordering (57) | MET |
| 269-10 admin UI | e2e/graph-release-review.spec.ts; e2e/graph-release-admin-journey.spec.ts | MET |
| 270-1 history fields | i/test_graph_release_history_postgres.py::test_history_reads_under_guards_and_restored_lineage_is_exact | MET |
| 270-2 field-level diff vs active | u/test_graph_release_rollback.py::test_compare_active_with_historical_lists_seven_roles_with_exact_diffs | MET |
| 270-3 historical readable+executable | i/test_graph_release_rollback_postgres.py::test_pinned_historical_releases_remain_readable_and_executable; i/…runtime S17 | MET |
| 270-4 preview + confirmation + note | e2e/graph-release-history.spec.ts (9) | MET (ruling OQ9) |
| 270-5 incompatible refused | u/test_graph_release_rollback.py::test_incompatible_historical_release_is_reported_per_role, ::test_endpoint_name_policy_makes_a_historical_release_incompatible | MET (ruling C32) |
| 270-6 next version, no reopen | i/…rollback::test_v8_restores_v3_with_exact_intervals_mappings_and_evidence | MET |
| 270-7 historical_restore evidence | same | MET (ruling OQ3) |
| 270-8 restore evidence never satisfies readiness | i/…rollback::test_historical_restore_evidence_never_satisfies_readiness | MET (ruling Q7) |
| 270-9 admin-only + FE | u/test_graph_release_history_routes.py (non-admin); e2e/graph-release-history.spec.ts | MET |
| 270-10 v3 while v7 → v8 | i/test_graph_release_rollback_acceptance_postgres.py::test_restore_v3_while_v7_active_over_http | MET |
| 271-1 no code-owned reads after v1 | u/test_lakebase_only_runtime_contract.py (guards 1–5); journey tripwire `reads == []` | MET |
| 271-2 every creator needs pin; nodes resolve it | i/test_lakebase_contract_failures_postgres.py (7-creator refusal); i/…runtime S13 | MET |
| 271-3 explicit failure, state preserved | i/test_lakebase_contract_failures_postgres.py (22) | **PARTIAL until I1** (residue ruled C47(e)) |
| 271-4 historical bundles resolvable | u/test_retained_bundle_ledger.py; i/…runtime S17 | MET |
| 271-5 no tools, grants not rendered | Task 7 `adapter.tool_bindings == []`; u/test_graph_definition_manifest.py::test_manifest_contains_no_foreman_or_tool_grants | MET |
| 271-6 admin-only; non-admin sees only Graph Version | u/test_admin_route_authorization_inventory.py (35-route namespace); u/test_conversation_graph_version_projection.py::test_union_of_all_six_conversation_endpoint_keys_satisfies_ac6 | MET |
| 271-7 backend acceptance flow | i/test_graph_lifecycle_acceptance_postgres.py::test_edit_test_approve_preview_publish_pin_rollback_lifecycle | MET |
| 271-8 identity through state/fan-out/traces | i/…runtime::test_every_pinned_release_drives_its_own_revisions_through_state_fan_out_and_traces | MET |
| 271-9 Playwright journeys | e2e/graph-release-admin-journey.spec.ts (8), e2e/graph-release-conversation-journey.spec.ts (6) — **run at this gate, GREEN** | MET |
| 271-10 delete only after green; one path | AC10 ordering in ledger; Task 12 gate; this gate's Playwright run | MET |

Cross-cutting stories: 52 (principal + timestamp on every write) → u/…routes principal tests + journey S14 `system:bootstrap` literal, MET; 53 (traces incl. test-run identity) → S13 + #267 R1 ruling, MET-with-ruling; 54 → 271-6; 55 → 271-6; 56 → 271-4; 57 → 261-3; 58 (cache by release id) → u/test_persisted_graph_release.py::test_resolves_v1_and_v2_by_their_persisted_ids_not_active_release (my S0 RED), MET; 59 → 268-7 protections MET, scheduling PARTIAL; 60 → 259-5/271-5.

---

## 3. Epic invariants, re-derived at HEAD

| Invariant | Re-derivation at HEAD | Structural owner | Ruling |
|---|---|---|---|
| One locked draft writer | Only `_assign_locked_candidate` writes `candidate_hash` as an attribute; lock bump only in `_advance_locked_draft`; #271 adds no writer (§1.1) | u/test_graph_release_rollback.py::test_candidate_hash_writers_are_the_allowlisted_attribute_and_builder_sites, ::test_candidate_hash_writer_scan_detects_each_write_form | HOLDS |
| One structured-output binding | `grep -c "with_structured_output(" src` = **1** (`agent_runtime.py:241`); `bind_tools(` = 0 | u/test_agent_runtime.py::test_structured_output_binding_has_one_call_site_and_the_probe_has_none | HOLDS |
| One L0 parent-lock helper | Both-parent locks only via `_lock_current_parents` (workbench, test workbench ×3, rollback ×2, bootstrap, publication ×2) | u/test_graph_parent_lock_is_single_sourced.py::test_only_lock_current_parents_locks_both_graph_parents (AST) | HOLDS |
| Global lock order + deadlock freedom (#267–#271) | [advisory] → L0 release → L0 draft → L1 draft agents (agent_key) → L2 case rows (id) → L3 run rows (id). Session creation takes L0-release only; verdict takes one L3 row; cleanup L0-share → L3; publication L0X→L1→L2 share→L3; rollback L0X→L1→L3 (skips L2); preview L0-share only, remote check after commit. #271 adds none (no `with_for_update` in its diff); its reads take no locks; the chat session lock (`user_sessions.is_processing`, own transaction) is never held across an L-lock acquisition by #271 code | #269/#270 ordering suites (57 + 12 + 12 + 18), GREEN | **Deadlock-free**: every path acquires a prefix-consistent subsequence of one order |
| One eligibility clause | `eligible_approval_clause` (`agent_test_workbench.py:640`) used by readiness, cleanup and the gate re-verify (`graph_release_evidence.py:144`); the gate's L3 lock predicate repeats its literal terms by design (C45) | u/test_agent_test_workbench.py::test_the_eligibility_clause_carries_every_term_including_the_ddl_backed_ones; u/test_graph_release_evidence.py::test_gate_and_readiness_agree_on_every_eligibility_term | HOLDS (sabotage B RED) |
| One publication writer, used by rollback | `GraphRelease(` constructed only in `graph_configuration_publication.py` and bootstrap; rollback → `_commit_locked_publication` | u/test_graph_release_rollback.py::test_restore_writes_through_the_one_publication_core | HOLDS |
| No session/turn ids in any model payload | Per-role literal key sets; Task 7 asserts no session id, actor, turn id or forbidden key in any of 30 prompts | u/test_agent_model_payload.py; u/test_graph_nodes.py payload-key pins; i/…runtime S13 | HOLDS |
| ids ≠ versions | #270 §5 closed it for #268–#270. #271: routes address versions; Task 7 journey has id 3 = v2, `(id, version)` asserted as pairs; `_active_graph_release_exists` selects by interval, not version | i/test_graph_release_history_postgres.py::test_ids_diverging_from_versions_resolve_by_version_everywhere | HOLDS |
| Lakebase is the only definition source | Compatibility runtime gone; `src.core.skills` read only for 6 protected-bundle names; manifest read only by bootstrap | u/test_lakebase_only_runtime_contract.py (5 guards + 14 import-walk cases); journey tripwire | HOLDS (the legacy monolith engine is out of #258 scope, "Changes to legacy monolith calls") |
| Fail-closed engine mode | All three resolution sites fail closed | u/test_engine_mode_wiring.py (inverted ws4d tests); i/test_lakebase_contract_failures_postgres.py | HOLDS for `/chat/stream`, `/chat/async`, SSE turn 1. Gap m5: sync `POST /api/chat` never resolves engine mode (pre-existing ws4d; no product caller) |
| One reducer, counter and gate per page | `useReducer(` appears exactly twice in `frontend/src/components/{Admin,Conversation}`: `useDraftEditor.ts:52` (workbench) and `useReviewAndPublish.ts:35` (Review & Publish, incl. History tab) | Counter/gate: fe/…/draftEditorState.test.ts `:1115`, `:2654`; reviewAndPublishState.test.ts `:477/:508/:516`; TestRunPanel.test.tsx `:303`; AgentDefinitionWorkbench.test.tsx `:3319`. **Reducer: no structural pin** | **Covered-with-ruling.** Re-derived to hold today by grep; a structural `useReducer` count test is cheap (one Python text-read test) and optional — park as a follow-up |
| Forbidden-action count is 8 | `ALLOWED_ACTION_NAMES` has 8 entries; asserted `toHaveLength(8)` in the workbench spec and both #271 journeys | e2e/agent-definition-workbench.spec.ts:1519; e2e/graph-release-admin-journey.spec.ts:167; e2e/graph-release-conversation-journey.spec.ts:527 | HOLDS |

---

## 4. Accepted rulings the user may want to override

| Ruling | Re-assessment |
|---|---|
| **C24 fail-closed** (reverses the ratified ws4d fail-open) | **Uphold.** The fail-open ran pinned graph conversations on the monolith with code prompts during any DB blip, violating spec §15 and #271 AC3; "fail only when pinned" needs the failed read. Cost: during a DB blip even monolith decks get a 503. The UX half is broken until I1 is fixed. |
| **Q7 rollback: a kept edit stays approved** | **Uphold.** Eligibility is hash + case version and has never been base-relative; the preview shows the real diff before any publish. Optional UX: label "Pending edit kept; its existing approvals still count." |
| **C32: rollback applies today's endpoint policy** | **Uphold.** It is the name-shape policy (no URLs), not endpoint existence; OQ9 makes the remote check a preview warning only, so an emergency rollback is never blocked by a missing endpoint — the user should know the flip side: a rollback can restore a release whose endpoint was removed, and its conversations then fail with `PinnedInvocationEndpointError` (explicit). |
| **C48: typed refusal for a verdict on a published run** | **Uphold.** Published evidence is immutable (Q3, DB trigger + typed 422). |
| **Partial-narration residue** when a later chat node fails (Task 8 concern 2) | **Product question, still open.** Nodes that finished before a later-node failure keep their committed narration. Rolling it back needs a compensating delete in the failure path. Recommend: accept for now, file an issue. |
| **#268 Q1: cleanup has no production caller** | **Needs the user's decision.** Without a trigger, #268 AC7 / the #258 "bounded to 20" decision is not enforced. Recommend an admin-triggered route or a scheduled sweeper, batched (Task 4 M1). |
| **1.4 MB recorded contract** | **Accept.** 70 exchanges; ~14 full workbench reads at ~95 KB each dominate. It is test data with code-owned prompt text only. Optional follow-up: dedupe identical workbench bodies. |
| **C47(e) residue** (user message, `chat_requests` row, empty session) | **Uphold, but correct the rationale (m1):** no existing recovery closes a `pending` row. |
| **#267 R1** (candidate runs bypass the production identity sink) | Uphold (privacy); it is a controller ruling on a ticket AC (#267 AC10, story 53). |
| **P7** (synthetic-data warning is UI-only) | Uphold; flag that nothing server-side rejects real data in a test case. |

---

## 5. Fix-wave list

| Item | Ruling |
|---|---|
| **I1** `[object Object]` for the typed chat 503 (`api.ts:917-920`, `:1000-1002`; mock `conversation-graph-version.spec.ts:110`) | **FIX NOW** (blocks merge) |
| **m1** `/chat/async` leaves the `chat_requests` row `pending` forever: `recover_stuck_requests` (`job_queue.py:306-345`) only handles `status == "running"`, the in-memory sweeper only `running` jobs, and `SessionManager.cleanup_stale_requests` (`session_manager.py:3328`) has no caller. The C47(e)/Task 8 report claim is false | **FIX NOW (ledger):** correct the rationale in `progress.md`/C47(e). Code: park (a best-effort `status='error'` in the `_EngineModeUnresolvedError` clause, or schedule `cleanup_stale_requests`) — same pre-existing gap as the route's `except Exception` |
| **m2** `release_session_lock` raising inside either fail-closed `except` turns the 503 into a 500 and leaves the lock until its 300 s expiry | Park (follow-up) — or fix with I1 if convenient (a 4-line try/log) |
| **m3** `test_graph_lifecycle_playwright_contract.py::test_recorded_at_commit_is_an_ancestor_of_head` goes RED after any rebase of this branch or a squash-merge of `feat/langgraph-core` into `main` (the recording commit `eba136e66` is branch-local) | Park; decide before the `main` PR (merge commit keeps it; squash breaks it). A local `--no-ff` merge is safe |
| **m4** contribute route: the "no active release" 503 is decided before the permission check, so any authenticated caller can observe it | Accept (a deployment-wide fact, no deck data) |
| **m5** sync `POST /api/chat` never resolves engine mode, so a graph-capable deck's turn there runs the monolith | Accept for #271 (pre-existing ws4d, no product caller, #258 excludes monolith changes); follow-up issue |
| **m6** the gate's case-version term is guarded only by the SQLite unit `test_gate_and_readiness_agree_on_every_eligibility_term[test_case_version]`; no PG or journey test catches sabotage B (supersede writes a new case row, so the id term masks it in PG) | Accept (the owner went RED) |
| **m7** Task 11 m1 — collaboration stubs' call counts not pinned | **FIX NOW** (test-only, a few lines) |
| **m8** Task 11 m2 — dangling `page.on('request')` accumulator after step 4 | **FIX NOW** (test-only) |
| Task 6 m3 — readiness stale-hash invisible to the journey | Park / accept (owner tests cover it) |
| Task 2 M1 — local `_STANDARD_LOG_RECORD_ATTRS` duplicate at `test_persisted_agent_runtime.py:917` | Fix now if trivial (import `STANDARD_LOG_RECORD_ATTRS` from `tests/fixtures/log_records.py`); otherwise park |
| Task 10 concern 1 — recording gaps (8 `lookahead` + 6 `carried` reads replayed from a nearby recording) | Park → follow-up issue (record UI reads in Task 6) |
| Task 10 concerns 2–4 | Accept |
| Task 12 M2 — `test_graph_definition_manifest.py:268` ties skills text to the manifest | Park → OQ2 follow-up |
| Task 12 M3/M4 — guard blind spots | Accept |
| Task 8 M1 — empty session on the chat-generated-id 503 | Accept |
| Task 7 m, Task 1 m | Accept |

**Observations.** O1: a pin in graph state that disagrees with the actor's persisted pin (sabotage A, and Task 7's controller sabotage) makes `commit_placeholder` fail and the foreman re-dispatch until `GraphRecursionError` (limit 10 007). It is unreachable in production (both come from the same row), but the failure mode is a long loop rather than a fast typed error; worth an issue for the graph owners. O2: `test_dependencies_resolve_on_proxy` (`@live @slow`) is not deselected locally (no `addopts -m "not live"`); it passed here.

---

## 6. Follow-up GitHub issues for the user to file (read-only here; drafts)

1. **deploy_autoscaling: two `TestGetOrCreateLakebase` tests fail on `main`** — `test_returns_autoscaling_when_available` gets `'provisioned'`; `test_falls_back_when_autoscaling_creation_fails` never calls the provisioned path. Predates the epic (also fails on `main` `f6b1506c5`); `packages/databricks-tellr/deploy.py`.
2. **`model_endpoint_tool.py:75` interpolates a user-configured endpoint name into `serving_endpoints.get` under the OBO client (#266 m7)** — same unescaped-path class #266 fixed for Agent Definitions. Apply `validate_endpoint_name_policy` before the call.
3. **`test_usage_service` fails near 00:00 UTC** — date-boundary flake. Freeze the clock or compute the day window from one `now`.
4. **`test_shared_deck_mutation_attribution.py` intermittently hangs** — not reproduced (60 passed in 18 s under `timeout 120`). Add a per-test timeout and capture `pg_stat_activity` on hang.
5. **CI has no ESLint job** — `frontend` lint runs only locally. Add `npx eslint .` (or on changed files) to `test.yml`.
6. **Delete the now-unread authored prompt text in `src/core/skills` (OQ2)** — keep the six protected-bundle constants `prompt_assembler.py` imports, and first decouple `tests/unit/test_graph_definition_manifest.py:268` (it ties skills text to the frozen manifest).
7. **Choose a trigger for unpublished test-run cleanup (#268 Q1)** — `cleanup_unpublished_test_runs` has no production caller, so the "latest 20 per case" bound is unenforced. Add an admin route or schedule; batch the target list (Task 4 M1).
8. **Make the Python-read frontend file list exhaustive (C40)** — join tests text-parse frontend files (`reviewAndPublishState.ts`, `agent-definition-workbench.spec.ts`, `AssemblyEditor.tsx`, `slideDocument.ts`, `services/api.ts`, …) with no registry. Add one registry + a guard so a reformat cannot silently break a join test.
9. **Record the UI's real read sequence in the lifecycle contract (#271 Task 10 gaps)** — 14 reads are replayed from a nearby recording. Record boot readiness, the first catalog read and pre-run run lists in the Task 6 journey.
10. **Orphan `pending` `chat_requests` rows are never closed** — `recover_stuck_requests` handles only `running`; `cleanup_stale_requests` has no caller. Close them after a failed async submit and schedule the cleanup.
11. **Sync `POST /api/chat` ignores engine mode** — a graph-capable deck's turn there runs the monolith. Resolve engine mode and fail closed like the stream/async routes, or retire the route.
12. **Graph recursion loop when a placeholder commit keeps failing (O1)** — the foreman re-dispatches to `GraphRecursionError` (10 007 steps). Fail the turn after N consecutive placeholder failures.
13. **Recorded-contract ancestry check breaks on rebase or squash (m3)** — decide before the `feat/langgraph-core` → `main` PR.
14. **(Optional) Pin "one reducer per page" structurally** — a text-read test that `useReducer(` occurs only in `useDraftEditor.ts` and `useReviewAndPublish.ts`.
15. **Partial narration kept when a later graph node fails (Task 8 concern 2)** — product decision: roll back narration from earlier nodes or keep it.
- **Release gate, not an issue:** #266 m9 — authorise the read-only `databricks serving-endpoints get databricks-claude-opus-4-6 --profile tellr-dev -o json` probe (C43), then keep or relax the absent-`config_update` rule.

---

## 7. Gates at HEAD `4ec1432a0`

| Gate | Result |
|---|---|
| `test ! -e .venv` | absent |
| Full unit (`DATABASE_URL=sqlite:////tmp/wbr-271.sqlite`, `-p no:randomly`), 21:37:29–21:44:01 UTC | **2 failed / 7436 passed / 110 skipped** (392 s). The 2 are the deploy_autoscaling pair with the baseline causes (`'provisioned' == 'autoscaling'`; provisioned called 0 times). No `test_usage_service` failure (not near midnight). Skip causes unchanged (105 huashu, 3 RC, 1 otel, 1 RLIMIT). |
| PostgreSQL `integration-graph`, 36 files, one invocation each, `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres -m "not live"` | **575 passed, 0 skipped, 1 xfailed** (claim_exclusivity's documented xfail). Attribution file under `timeout 120`: 60 passed in 17.8 s (no hang). New #271 files: lifecycle acceptance 2, lifecycle runtime 2, lakebase contract failures 22. |
| Other integration touched by Task 8 | `test_streaming.py` 28 passed; `test_api_routes.py` 87 passed, 2 skipped (pre-existing MLflow skips) |
| `tellr_int_*` databases | 5 before, 5 after (none created or dropped) |
| Vitest | 21 files / 1099 passed |
| Typecheck | `tsc --noEmit -p` app 0, node 0, e2e 0; `tsc -b` exit 0; worktree clean after |
| ESLint on #271's 7 changed frontend files | exit 0 |
| Playwright, sequential, `--project=chromium --workers=1`, only this lane on :3000 | graph-release-admin-journey 8 · graph-release-conversation-journey 6 · graph-release-review 9 · graph-release-history 9 · admin-route-gate 6 · agent-definition-workbench 78 · conversation-graph-version 7 · admin-page 17 · mixed-release-collaboration 6 = **146 passed, 0 failed**. No listener on :3000 afterwards. **AC10 gate satisfied.** |
| Pre-merge gate facts | `feat/langgraph-core` = `12a521dc7` = INTEGRATION_BASE (no advance); predecessor ancestry recorded in `predecessor-heads.md` |

## 8. Sabotage (temp worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/wbr-271`, detached at HEAD, removed; `git worktree list` shows no `wbr-271`; every run grepped for the `WBR271_*` marker on the executed line, then `git checkout -- src`, marker count 0, porcelain clean)

| # | Sabotage | Scope run | Result |
|---|---|---|---|
| S0 (brief Step 4) | `PersistedGraphReleaseLoader._load_complete_release` caches under a constant key (release id ignored), `persisted_graph_release.py:152,186` | lifecycle runtime PG + persisted/packaged loader units | **RED 3/163**: `[#261] S13 … new-root (pin id 3, v2)` identities mismatch; S17 bundles; `test_resolves_v1_and_v2_by_their_persisted_ids_not_active_release`. As predicted. |
| A (epic) | After a rollback (active release has `restored_from_release_id`), `load_conversation_pin` silently returns the active release instead of the pin (`conversation_pins.py:159-161`) | lifecycle runtime, lifecycle acceptance, rollback acceptance, pin acceptance, runtime failures, Lakebase contract failures (PG) | **RED 8/35**, labelled `[#261] S13` (correct owning ticket). Observed cause `GraphRecursionError` (O1), not an identity diff. `test_restore_v3_while_v7_active_over_http` stayed GREEN (it runs no turn) — the runtime journey is the only catcher. |
| B (epic) | The publication gate alone accepts evidence from a superseded case version: version term dropped from the L3 lock predicate and the re-verify replaced by the clause minus `test_case_version` (`graph_release_evidence.py:105,144`); readiness untouched | #268/#269 evidence + publication units and PG, publication acceptance, lifecycle acceptance | **RED 1/113**: `test_graph_release_evidence.py::test_gate_and_readiness_agree_on_every_eligibility_term[test_case_version]`. No PG or journey test caught it (m6). |

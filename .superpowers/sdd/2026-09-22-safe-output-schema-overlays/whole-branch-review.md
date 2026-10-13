# #264 whole-branch review — safe output-schema overlays

Range: `INTEGRATION_BASE d72ad974d183f2d8330c2239b2e0f1132d3082d2 .. HEAD 92b2e8a34f933272aa82fafbb463be22ed05f57b`
(0 behind, 57 ahead, re-probed with `git rev-list --count` both ways). Reviewer: whole-branch, Opus, 2026-09-25.

**Verdict: MERGE WITH LISTED FIXES.** 0 Critical, 5 Important (4 must-fix), 16 Minor.

## How this was read

- Requirements: issue #264's eight ACs, design §8 and §13.1, the plan in full (global constraints, "Stable registry, trace, and wire interfaces"), all 65 corrections, the ledger (every `Ruling:`, every `minor (deferred)`), and the Task 5 and Task 6 reviews.
- Code package: `review-whole-branch-d72ad974d..92b2e8a34-code.diff` (555 KB, 13,029 lines), read by file section in passes: workflow and CI guard; frontend api, reducer, hook and editor; routes and schemas; runtime and identity sink; registry and types; draft writer and manifest; then the PostgreSQL file and the test files where a finding needed them. All eight production Python files were also read whole at HEAD.
- Blast radius, read outside the diff: `src/services/graph/nodes.py` (runtime callers and their `except Exception` handlers), `src/utils/logging_config.py` and `src/core/otel_logging.py` (who formats the sink's record), `DatabricksModelAdapter` (what the composed class becomes on the wire), `tests/unit/test_graph_nodes.py` (#262's trace tests on the retyped sink), and `graph_configuration_workbench.py`.
- Excluded, as instructed: the plan file, and `.superpowers/sdd/2026-09-22-schema-driven-config-ui/plan-review-ce04afd08.md`, an obsolete-path artefact (correction 26) that I did not count as #264 work.

## Gates re-run by me (not relayed)

All ran in the temporary detached worktree `/tmp/review-264` at `92b2e8a34`, with `PYTHONPATH=<tree>:<tree>/packages/databricks-tellr`. Provenance was checked: `src` and `databricks_tellr` both resolved inside the tree, and `.venv` was absent before and after.

| Gate | Command scope | Result |
|---|---|---|
| Full unit, 11:48–11:55 UTC (well clear of midnight) | `pytest -q -p no:randomly -p no:cacheprovider -rf tests/unit` | 7 failed / 5833 passed / 110 skipped. Six are the baseline set, matched by node and cause: deploy_autoscaling ×2, style_exclusivity_chokepoint ×3, persistence_boundary ×1. The 7th is `test_runtime_logging_sink_success_record_is_identity_outcome_and_optional_projection_only`, and its cause is environmental (see m12). |
| Task 7 17-file matrix | the plan's list | 1003 passed + the same one environmental failure |
| PostgreSQL, one invocation per file, `-rs` | bootstrap 2, constraints 7, persisted_runtime_failures 7, pin_migration 1, pin_creation 2, pin_acceptance 1, workbench 15, schema_overlay 9, mixed_release_collaboration_acceptance 26 | all passed, 0 skips in every file |

The environmental failure: the test's secret needle `"private"` matches the record's `pathname` because `/tmp` resolves to `/private/tmp` on macOS. It is not a code defect, and the needle predates #264 (it came from #262 in `fb88cca3a`).

I ran no frontend commands. The temporary worktree has no `node_modules`, and Vitest's cache lives inside the shared symlinked `node_modules`. See "Declined to judge".

---

## 1. Ticket-level spec review

### Issue #264 acceptance criteria

| # | AC | Verdict | Evidence |
|---|---|---|---|
| 1 | Edit canonical descriptions and examples; add or remove overlay-owned optional fields | **PASS (with I1)** | `agent_schema_registry.py:392-433` validates the overlay; `agent_schema_registry.py:457-476` composes it; the editor is `OutputSchemaEditor.tsx:280-309` (canonical rows) and `:312-331` (optional picker); removal is `overlayFromForm` dropping empty guidance (`draftEditorState.ts`) plus the toggle reducer. Caveat I1: the UI, route and writer accept guidance on a **v1** contract, and the runtime refuses it. |
| 2 | Changing name, type, requiredness, enum, default or validator is rejected with field-level errors | **PASS** | Everything except description and examples is held in `extra_properties` and reported as `overlay_guidance_property_forbidden` at `…field_overrides.<f>.<p>` (`agent_schema_registry.py:409-417`). An unknown field is `overlay_unknown_canonical_field`. There is no request path that names a type or default. The wire DTO is `extra="forbid"` at top level (`schemas/agent_definitions.py:359`). The controller's Task 5 sabotage ("admits `type`") went RED 1. |
| 3 | The model-facing schema combines canonical and allowlisted overlay fields and forbids undeclared extras | **PASS** | `compose` subclasses the canonical model with `extra="forbid"` and adds only catalog descriptors (`agent_schema_registry.py:448-482`); the adapter is bound to `composed.model` (`agent_runtime.py:655`); raw keys are checked before projection (`:497-508`). See I5 for an undeclared side effect on v1. |
| 4 | Canonical and overlay fields are validated separately; overlay values are kept in diagnostics and traces | **PASS** | Canonical validation `:510-521`, optional validation `:523-541`; diagnostics `agent_runtime.py:683`; recording sink `agent_runtime_identity.py` (`successes`); logging sink `:163`. The absent, `null` and `[]` distinction is pinned by `test_exact_optional_values_reach_diagnostics_and_both_sink_traces`, which the controller's Task 7 sabotage turned RED 2. |
| 5 | Graph logic consumes only canonical fields | **PASS** | `output=validated.canonical_output` (`agent_runtime.py:673`). No `src/services/graph` or `src/api` module reads `diagnostics.additional_fields` (grep is empty). The canonical projection's filter is correct but is pinned only by a precondition (m6). |
| 6 | The editor clearly distinguishes protected canonical properties from editable overlay content | **FAIL (I2)** | Canonical rows: correct. Protected labels are read-only and only description and examples are inputs. Optional rows: `OutputSchemaEditor.tsx:206-238` offer "Description override" and "Examples override" inputs for `diagnostic_notes`. The plan makes that descriptor text code-owned, and the server always rejects it (I2). |
| 7 | Direct API calls cannot bypass the UI's validation | **PASS** | The route parses only after `Depends(require_draft_write_principal)` (`routes/agent_definitions.py:384`, `:498`), then goes through the one writer, whose validator tuple the UI cannot skip. The C1 type-error path returns an ordered 422 (`:407-421`). The identity is unreachable from the client (corrections 44 and 49a). |
| 8 | Tests cover every allowed and forbidden mutation, preservation of optional fields, and rejection of undeclared extras | **PASS, with gaps** | Registry, writer, route, runtime and PostgreSQL suites cover the listed mutations. Gaps: overlay retention across the schema upgrade is pinned by nothing (I3, my sabotage RED 0/1004 and 0/9 PG); the canonical filter is equivalent-mutant only (m6). |

### Design §8, clause by clause

| Clause | Verdict | Evidence |
|---|---|---|
| Python schemas remain executable contracts | PASS | `OUTPUT_SCHEMAS` is unmodified. v1 digests are retained and re-verified at construction (`agent_schema_registry.py:354-367`). |
| An overlay may change descriptions and examples | PASS (I1 caveat) | `:457-464` |
| An overlay may add optional fields | PASS | closed catalog `:115-124`, `:419-433` |
| An overlay may remove optional fields it previously added | PASS | the toggle reducer and the tuple replace. The writer treats an absent overlay as "retain" and an explicit one as "replace" (M21). |
| An overlay may not change name, type, requiredness, enum, default or validator | PASS | AC2 evidence above |
| Publish-time validation with field-level errors | **Not yet reachable** | No publish path exists at HEAD. Draft-time validation is the stand-in. The future publisher must re-run `validate_overlay`, and I1 must be resolved first. |
| A dynamic Pydantic model with allowlisted overlay fields; undeclared extras forbidden | PASS | AC3 evidence above |
| Canonical and overlay fields validated separately; overlay values kept in `additional_fields` | PASS | AC4 evidence above |
| Both serialized into diagnostics, test output and traces | PASS for diagnostics and traces; test output **not yet reachable** (no test-run path; #266). The plan's "logging materializes a JSON-safe copy" is **not met** (I4). |
| Must not rely on constructing the canonical model with unknown extras | PASS in code (`:510`), unpinned (m6) |
| Graph logic consumes canonical fields | PASS | AC5 evidence above |

### Design §13.1 (Output Schema tab)

PASS. The tab renders `OutputSchemaEditor` (`DefinitionEditor.tsx`). Schema-contract and overlay issues route to the `output-schema` tab. The Schema Upgrade action uses the one `operationBlocked()` gate (`useDraftEditor.ts`). The status vocabulary is unchanged.

---

## 2. Writer-by-writer comparison

The one locked write is `_write_locked_content` (`graph_configuration_draft.py:755-800`). It computes the hash with `definition_content_hash(content)`, maps columns through `definition_content_values`, sets `candidate_hash`, reads the transaction timestamp from the database, does `lock_version += 1`, `updated_by` and `updated_at`, then `flush`, and returns `changed = new_hash != old_hash`. Every draft-content writer below reaches it inside one `with session.begin()` after exactly one `_read_workbench_for_draft_write` (the row lock).

| Entry point | Validators, in order, relative to the stale check | Mapper and hash | Lock and audit | Rejected request | Pinning tests |
|---|---|---|---|---|---|
| `save_editable_model_draft` (`:270`) | Before the transaction: `_validate_actor_lock_and_editable_candidate`, which adds a `schema_overlay` `strict_type` check. Inside: lock → payload rebuilt from stored content, with `schema_overlay` replaced only if supplied → `DefinitionContent.model_validate` → **local** (`_assembly_candidate_validator`, then `_schema_overlay_candidate_validator`) → **stale** → post-stale `()` → write | one writer | +1, actor, database timestamp | `DraftContentRejected` raised inside `begin()`, rollback, nothing flushed | `test_invalid_client_overlay_rejects_with_no_state_change[0-3]`, `test_invalid_overlay_and_stale_lock_is_an_ordered_422_with_no_write`, `test_overlay_validation_is_registered_in_the_pre_stale_tuple_only`; PG `test_persisted_invalid_overlay_writes_nothing_at_all`, `test_two_sessions_serialize_an_invalid_overlay_save_against_an_upgrade`, `test_a_client_overlay_is_validated_against_the_contract_read_under_the_lock` |
| `save_draft_content` (`:331`) | `_validate_common` → isinstance → lock → re-validate → `_immutable_content_issues` (`schema_contract` → `immutable_field`) → **local** → **stale** → post → write | one writer | same | same | `test_invalid_trusted_overlay_rejects_with_no_state_change`; the M13 and M14 literal immutable tests |
| `upgrade_draft_protected_assembly` (`:389`, #265, untouched) | common → lock → **stale first** → `PromptAssembler.upgrade_definition_to_v2` → local (now including the overlay validator) → post → write | one writer | same | same | `:1517` guard, `test_the_two_upgrades_deliberately_differ_in_precedence` (M7 RED 4/116) |
| `upgrade_draft_schema_contract` (`:428`, new) | common → lock → **local on current** → **stale** → `already_current` → `upgrade_content_to_v2` → local and post **on target** (F5) → write | one writer | same | same; `already_current` raises before any mutation | PG `test_persisted_schema_upgrade_installs_v2_and_retains_v1_history`, `…repeated_schema_upgrade_is_already_current_and_writes_nothing`, `test_two_sessions_serialize_two_schema_upgrades_and_reject_the_waiter[architect,deck_reviewer]`; units `test_stale_schema_upgrade_is_a_conflict_even_when_content_is_already_current` (F1), `test_schema_upgrade_path_performs_exactly_one_row_lookup` (F2), `test_the_schema_upgrade_validates_before_reporting_already_current` |
| `get_draft_legacy_prompt_source` (`:482`) | read-only; stale → 409 | none | none | n/a | #265 suites |
| `bootstrap_v1` (bootstrap module) | writes draft rows through `draft_from_definition`, **not** the locked writer; unchanged by #264, and it only ever writes empty v1 overlays | its own | n/a | n/a | bootstrap PG 2/2 |

Rulings:
- There is one writer, one lookup and one mapper/hash. There is no second transaction or DTO. The F2 lookup pin is live.
- One unflagged widening: the overlay validator now also runs on `save_draft_content` and on #265's protected-assembly upgrade. A stored draft already carrying an invalid overlay becomes unsaveable and unupgradeable until the overlay is cleared. No real database can hold one: bootstrap writes only empty overlays, and the only invented names were in #263/#265 test fixtures, which Task 4 repaired. I am declaring it, not blocking on it.

## 3. Sink outcome table

The recording sink appends `calls` before the callback, `successes` only after it returns, and `error_classes` only when it raises. "Keys" is the logging record's `emitted_fields` set.

| Outcome | Recording `calls` / `successes` / `error_classes` | Logging record keys (exact) | `additional_fields` value | Pinning test |
|---|---|---|---|---|
| Success, no optional selected (v1) | 1 / 1 (`{}`) / `[]` | `PERMITTED_LOG_FIELDS ∪ {additional_fields}`, i.e. `graph_version, graph_release_id, agent_key, agent_definition_revision_id, content_hash, outcome, error_class, additional_fields` | `{}` | `test_runtime_logging_sink_success_record_is_identity_outcome_and_optional_projection_only`; recording: `…:368-370` |
| Success, optional selected but absent | 1 / 1 (`{}`) / `[]` | same 8 | `{}` | `test_exact_optional_values_reach_diagnostics_and_both_sink_traces[{}]` (controller sabotage RED) |
| Explicit `null` | 1 / 1 (`{"diagnostic_notes": None}`) / `[]` | same 8 | `{"diagnostic_notes": None}` | `…[supplied1]` |
| `[]` | 1 / 1 (`{"diagnostic_notes": ()}`) / `[]` | same 8 | `{"diagnostic_notes": ()}` | `…[supplied2]` |
| Non-empty `diagnostic_notes` | 1 / 1 (stripped tuple) / `[]` | same 8 | `{"diagnostic_notes": ("a note","another")}`: **model-authored values** | `…[supplied3]`, `test_diagnostics_optional_projection_is_immutable_and_deeply_frozen` |
| Invalid canonical, invalid optional, undeclared key | 1 / 0 / `["AgentOutputValidationError"]` | exactly the 7 `PERMITTED_LOG_FIELDS` | absent | recording: `test_invalid_output_records_one_error_and_no_success_fields_in_the_recording_sink[4 cases]`; logging: `test_invalid_output_logs_one_error_outcome_and_no_success_field[canonical, optional]`. The undeclared-key case is not asserted at the logging sink (m13). |
| Provider error | 1 / 0 (not asserted) / `["PinnedInvocationEndpointError"]` | the 7 | absent | `test_provider_errors_cross_adapter_runtime_and_each_identity_sink`. The recording branch does not assert `successes == []` (m13). |
| Persisted configuration invalid or unavailable | 0 / 0 / `[]`; the sink is never reached | no record | n/a | `test_a_v1_schema_contract_still_rejects_a_non_empty_overlay_before_the_model`, `test_an_unresolvable_schema_contract_digest_fails_before_the_model_and_sink` |

**Correction 43 ruling.** `4b4fbddcf` is truly positive. Both branches assert exact-set equality, plus `msg ==` and `args in (None, ())`. It covers the success branch (the no-optional, `null`, `[]` and non-empty cases) and the error branch (an ordinary exception, invalid canonical, invalid optional, and a provider error). The only gap is the undeclared-key case on the logging sink, which is the same `except` branch (m13). RM1–RM5 are consistent with it.

**The docstring.** The class docstring (`agent_runtime_identity.py:122-128`) literally says "canonical model output never reach[es] a log record". As scoped to canonical output, that is true. The false text is the contract comment above `_LOGGED_IDENTITY_FIELDS` (`:95-101`). It quotes #260's PRD amendment: "**only** graph version … outcome, and error class; **it never logs payload, prompt, output**" and "seven emitted in total". Both statements are now false on the success branch (see I4).

## 4. Rollback and no-write ruling

**Every rejected request changes no candidate, hash, lock, audit, revision or release state. Upheld.**

Evidence:
- Every rejection is raised before `_write_locked_content`, inside `with session.begin()`, so the transaction rolls back and nothing was flushed. This covers:
  - `DraftContentRejected` from strict, immutable, local and `already_current` checks
  - `DraftSaveConflict`, which returns before the write
  - the route's C1 422 and malformed-JSON 422, which return before the service is called
- PostgreSQL, run by me with 0 skips: `test_persisted_invalid_overlay_writes_nothing_at_all` compares the stored candidate and hash, the draft `(lock_version, updated_by, updated_at)` triple, and `_immutable_graph_artifacts` (revisions including overlay and contract columns, release mappings, release interval) before and after. The repeated-upgrade and both two-session tests assert the loser's no-write, including PIDs and an observed lock wait.
- Unit: every `…rejects_with_no_state_change` test and every ordered-422-plus-stale test.

One caveat on the upgrade path: the *success* side's retention of the stored overlay is unpinned (I3). That is a correctness gap on a write that happens, not a no-write gap.

## 5. My sabotage

The seams already used were checked first by grepping every `task-*-review*.md`, `task-*-report.md`, ledger and corrections entry, including the controller's final `validate_output` absent-optional skip. None of the seams below appears.

All three ran in the temporary detached worktree `/tmp/review-264` at `92b2e8a34f933272aa82fafbb463be22ed05f57b`. Scope was the Task 7 17-file matrix (`pytest -q -p no:randomly -p no:cacheprovider <17 files>`; 1004 collected), plus PostgreSQL where noted. At rest the matrix reads 1003 passed + 1 environmental failure (m12). Every figure below is net of that one.

**S1, the scored sabotage (RED).**
- Target: the path-join line inside `_overlay_issue_field` in `graph_configuration_draft.py:196`, which projects each registry path segment into the wire field. The mutation drops the final segment (`issue.path[:-1]`).
- Anchor count: 1. The substitution was asserted by script.
- `rg -n "REV264SAB3" src` → `src/services/graph_configuration_draft.py:196`, on the executed located-issue return.
- Result: **RED 11/1004.** Failing tests:
  - `test_invalid_overlay_and_stale_lock_is_an_ordered_422_with_no_write`
  - `test_invalid_client_overlay_rejects_with_no_state_change[overlay_payload0..3]` (4)
  - `test_invalid_trusted_overlay_rejects_with_no_state_change`
  - `test_the_optional_catalog_becomes_selectable_only_after_the_schema_upgrade`
  - `test_the_schema_upgrade_validates_before_reporting_already_current`
  - `test_put_schema_overlay_domain_rejections_carry_candidate_prefix`
  - `test_put_schema_overlay_guidance_forbidden_property_is_domain_rejected`
  - `test_put_schema_overlay_invalid_plus_stale_returns_ordered_422`
- Restore: `git checkout 92b2e8a34f933272aa82fafbb463be22ed05f57b -- src/services/graph_configuration_draft.py`. The marker is gone, `status --porcelain` is empty, and the matrix is back to GREEN (1003 + the environmental 1).

**S2, a finding (RED 0).**
- Target: the upgrade's overlay retention in `upgrade_content_to_v2` (`agent_schema_registry.py:622`). `replacement_overlay = existing_overlay` became `replacement_overlay = SchemaOverlay()  # REV264SAB`.
- Anchor count: 1. `rg` put the marker at `:622`, the `isinstance(existing_overlay, SchemaOverlay)` branch that every `DefinitionContent` takes.
- Result: **RED 0/1004 matrix and RED 0/9 PostgreSQL** (`test_agent_schema_overlay_postgres.py`). A schema upgrade that silently wipes an admin's saved canonical guidance ships green. The PostgreSQL assertion `after.schema_overlay == before.schema_overlay` holds only because the bootstrapped overlay is empty. Task 6's `keepLocal () => true` ruling rests on this behaviour. See I3.
- Restored with `git checkout 92b2e8a34… -- src/services/agent_schema_registry.py`; marker gone; clean.

**S3, a finding (RED 0, an equivalent mutant).**
- Target: the canonical filter in `validate_output` (`:510`), mutated to `canonical_raw = dict(raw_output)  # REV264SAB2`. Anchor count 1.
- Result: RED 0/1004. This is equivalent today because all seven canonical models have default `extra` (None, which means ignore; probed), so the extras are dropped anyway. See m6.
- Restored and clean.

Two further probes:
- A plugin wrapping `RecordingAgentInvocationIdentitySink.invoke` to catch #262 trace tests passing on a failed invocation. It found 0 callback failures across `test_graph_nodes`, `test_persisted_graph_release`, `test_agent_runtime`, `test_deck_level_spec_change`, `test_agent_resolution_prompt`, `test_graph_configuration_bootstrap` and `test_graph_builder` (312 passed). Across the nine PostgreSQL files the only failure was the intended provider error.
- The v1 cross-seam probe behind I1.

**Temporary worktree:** removed with `git worktree remove /tmp/review-264`; `git worktree list` shows no entry.

---

## Findings

### Important

**I1 — MUST-FIX. Writer, route and UI admit v1 canonical guidance that the runtime refuses.**
- Where it breaks: `_schema_overlay_candidate_validator` returns `()` for architect v1 with `field_overrides={"intent":{"description":…}}` (probed). The UI renders editable canonical rows regardless of version (`OutputSchemaEditor.tsx:280`, no `isV2Schema` gate). `test_graph_configuration_draft.py:409` and `:1827` save exactly this shape. Meanwhile `agent_runtime.py:583` rejects any v1 overlay that is not empty. My probe ran the same content through `AgentRuntime.run`: `schema_contract_unavailable`, adapter calls 0. This is pinned intentionally by `test_a_v1_schema_contract_still_rejects_a_non_empty_overlay_before_the_model`.
- Impact: once a publish or test-run path executes draft content (#266 starts from this commit), an admin's v1 guidance edit makes that role fail every invocation. For architect, that is every turn.
- Fix: choose one rule. I recommend rejecting non-empty overlays under v1 in the registry and gating the canonical rows behind `isV2Schema`, because v1 digest material carries no overlay grammar. Add a cross-seam test that every overlay the writer accepts composes and runs, for all seven roles under v1 and v2.

**I2 — MUST-FIX. The editor offers guidance inputs for `diagnostic_notes` that the server always rejects (AC6).**
- Where it breaks: `OutputSchemaEditor.tsx:206-238`. `validate_overlay` accepts `field_overrides` keys only for canonical names (`agent_schema_registry.py:392-396`), so `field_overrides.diagnostic_notes` yields `overlay_unknown_canonical_field` whether or not the field is selected (probed). The plan makes descriptor description and example code-owned. `OutputSchemaEditor.test.tsx:212-225` pins the editability.
- Ledger Minor m3 said the server rejects only "on an unselected optional field". It rejects in every case.
- Fix: render the descriptor text read-only, remove both textareas, and pin their absence.

**I3 — MUST-FIX (test only). Nothing pins that the schema upgrade keeps the stored overlay.** Sabotage S2 went RED 0/1004 and 0/9 PG. Add one unit test and one PostgreSQL test that upgrade a v1 draft carrying saved canonical guidance and assert the overlay is retained byte-for-byte. The data-loss path and Task 6's reducer ruling both depend on it.

**I4 — MUST-FIX (comment, plus a recorded user decision). The combined log record contradicts the contract comment in its own file and is not JSON-safe.**
- The contract: `agent_runtime_identity.py:95-101` still states the #260 PRD contract ("never logs … output", "seven emitted in total"). The success record now carries 8 keys, including up to 8 × 280 characters of model-authored prose (correction 43).
- JSON safety: the plan says "logging materializes a JSON-safe copy", but the sink passes the frozen `MappingProxyType` of tuples (`:163`). `src/utils/logging_config.JSONFormatter` calls `json.dumps` with no `default`, so it would raise `TypeError` and drop every success record. Today that formatter has no caller, and the production OTel `LoggingHandler` accepted the mapping in my in-memory probe.
- Must-fix:
  - Correct the comment.
  - Materialize a plain `dict`/`list` copy.
  - Record the user's decision on values versus key names only. I recommend key names only: #260's amendment is the stricter binding privacy contract, and the values remain available in diagnostics.

**I5 — not must-fix, but fix in the same wave. Every v1 release's model-facing tool name changed.**
- `convert_to_openai_tool` now names the tool `ArchitectOutputSchemaV1Overlay` instead of `ArchitectOutput`, and adds `additionalProperties: false`. That is probed for architect, and the same `compose` naming applies to all seven roles.
- The `additionalProperties` part is mandated by AC3; the rename is not. The prompts still say "Return an ArchitectOutput". The plan says to preserve v1 bundle behaviour.
- The risk is low, because `with_structured_output` forces the tool.
- Fix: set the composed model's title or `__name__` to the canonical name.

### Minor (none blocks the merge)

- **m1 `dict_type` (correction 63): remove it.** It is dead: RED 0/157, and the terminal default already returns `strict_type`. A dead entry that reads as load-bearing is worse than none. Removing it is behaviour-free.
- **m2 F5: keep, and pin.** The post-upgrade re-validation is redundant only given today's catalogs. It enforces the writer invariant "every write's content passed the validator tuple" and mirrors the sibling upgrade. Cost is one `validate_overlay` plus one `PromptAssembler.validate` on a rare admin path. Add a test that registers a target-only-rejecting validator and asserts no write. The RED 0 is not a licence to delete it.
- **m3 F6, with #265's `prompt_assembler.py:377-384`: accept both.** Measured: `AgentSchemaRegistry()` costs about 11 ms and the draft writer has one importer (the API facade). Fail-closed at import is the right failure mode for frozen identities, and it matches #265. Record the coupling in the module docstring. Separately, `upgrade_content_to_v2` builds a fresh registry, and so repeats the 14 digests, on every call (`:614`); reuse the module one.
- **m4.** An unresolvable stored bundle on the ordinary save is reported on field `schema_contract`, where the plan's wire table says `candidate.schema_overlay`. The code's rationale is reasonable, but no correction records the deviation. Add one.
- **m5.** The C1 `try` in the route also wraps `_domain_assembly_rules`. A `ValidationError` from `AssemblyRulesV2`, if reachable, would be reported under a `candidate.schema_overlay.*` prefix. I did not measure whether it is reachable. Narrow the `try` to the overlay conversion.
- **m6.** The canonical filter (`:510`) is an equivalent mutant today (S3). Add a precondition test, in the style of correction 37, that no canonical output schema sets `extra="allow"`.
- **m7 (correction 61, with Task 5 m4).** The upgrade route has no route test for invalid-content-plus-stale, and no plain-stale test (v1 content, lock advanced by an unrelated edit). The service layer covers both. Add route tests in a follow-up.
- **m8.** `schemaUpgradeFailed` for the *matching* request ID (`failOperation`) is untested at unit scope; only the stale-ID ignore is tested.
- **m9.** The `mockModelNodes` architect fixture (`mocks.ts:1177-1180`) carries `speaker_notes` and a `title` override that is not an architect canonical field, on a v1 contract. That is an impossible server state. It does not *admit* `speaker_notes` into any product path, so the global constraint is not violated, but it is a trap for future readers. Replace it with a legal state in a follow-up.
- **m10.** Carried Minors, unchanged and not blocking:
  - Task 5 m2–m7 (m1 is ruled above).
  - Task 6 m2, m4–m9, n1 and n2. m3 is superseded by I2.
  - The label builder's limits for optional `Literal` and `default_factory` fields (no current field is affected).
  - Label wording.
  - Route tests that text-read `mocks.ts`.
- **m11, #262∩#264 drift.** #262's trace tests (`_assert_traced`, `test_graph_nodes.py:2686`) assert only `sink.calls`, the attempt log. After #264 an invocation can fail in `validate_output` and still add to `calls`. Measured: 0 wrong-reason passes today. Make `_assert_traced` also require `len(successes) == len(calls)`. No other drift was found in `agent_runtime.py`, `agent_runtime_identity.py`, `test.yml`, the CI guard or `test_persisted_agent_runtime.py`: the overlay file is present in the run block, the guard is enrolled, and the `lambda: None` fix is correct.
- **m12.** The secret needle `"private"` in the success-record test (inherited from #262, `fb88cca3a`) matches `pathname` under `/private/tmp`. The test REDs for environmental reasons. Route to the epic and use a unique token.
- **m13.** The undeclared-key error is not asserted at the logging sink, and the provider-error recording branch does not assert `successes == []`.
- **m14, the tsconfig gap: stays routed epic-wide; #264 need not close it.** #264 adds about 320 spec lines and 133 mock lines that nothing typechecks directly. `mocks.ts` is reached through `src` test imports, but the e2e spec is not. The gap predates #264 and spans #263 and #265. Closing it here would widen the ticket's file set into shared config. Record it as an epic item before #266.
- **m15, gates that never ran.** Tasks 5 and 6 did not run the matrix. Beyond `test_graph_definition_content_mapping.py`, three ledger claims rest on gates that did not cover what they claim:
  - "typecheck exit 0" does not cover `frontend/tests/` (m14).
  - The CI integration-graph job has never executed this branch. The guard is a textual check, so enrolment is proved but CI execution is not.
  - Correction 64's claim that the frontend field is "correct" rested on an unrun server comparison (already corrected by c65).

  Everything else I re-ran at HEAD, listed under "Gates re-run by me".
- **m16.** `schemas/agent_definitions.py:21` imports the private `_descriptor_material` across modules. Expose a public name.

## 6. Declined to judge

- The four-file Vitest run, typecheck, ESLint and Playwright at HEAD: not re-run. The temporary worktree has no `node_modules`, Vitest's cache would write into the shared symlink, and the controller's Task 7 run (219, 0, 0, 60) is on the same source tree.
- OTLP exporter encoding of an explicit-`null` attribute: the exporter is not installed locally, so I could not measure it.
- The effect of the I5 tool rename on model output quality: not measurable offline.
- The publish-time validation clause and the "test output" serialization: no publish or test-run path exists at HEAD (#266 and later).
- Whether `diagnostic_notes` values may be logged at all: this is a product and privacy decision for the user. I4 gives a recommendation, not a ruling.
- Task 1's freeze machinery for Pydantic private state (`CanonicalFieldGuidance`): four review rounds already covered it, and I found nothing in the whole-branch view that touches it.

## 7. Verdict

**MERGE WITH LISTED FIXES.** Fix I1–I4 before the local merge. I3 is test-only. I4 is a comment and a copy, plus the user's recorded decision. I5 is recommended in the same wave. After the fix wave, one scoped re-review should cover:
- the I1 cross-seam test for all seven roles under both versions
- the I2 UI change
- the I3 retention tests, re-running S2, which must then go RED
- the I4 comment and copy

No Critical findings. The one-writer, no-write, trace-ordering and direct-API guarantees hold.

# Safe Output-Schema Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: use `executing-plans-tellr` and `superpowers:subagent-driven-development` together. The spec and issue are binding; this plan is a hypothesis until Task 0 records code-verified corrections.

**Goal:** Let administrators safely tune canonical-field guidance and select the code-owned `diagnostic_notes` optional field without changing executable graph contracts, while preserving optional values in diagnostics and invocation traces.

**Architecture:** Task 1 creates only collision-free schema types, registry code, and its focused test on the reviewed #260 base. After reviewed #261, #263, and #265 are integrated locally after #260, Tasks 2–6 extend the one manifest, persisted runtime, identity/tracing sink, locked draft writer, aggregate save route, and frontend state machine. `AgentSchemaRegistry` owns versioned canonical schema bundles, overlay validation, dynamic model composition, raw-key rejection, and projection to the original Pydantic model. The sink callback does not report success until output validation/projection and `additional_fields` freezing are complete. A server-owned schema-contract upgrade uses the same locked writer; ordinary saves cannot name either protected identity.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, React 19, TypeScript 5.9, Vitest, Playwright.

**Binding inputs:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` §§7–8, 11, 14–18; GitHub issues #258 and #264. The exact optional catalog literals embedded below are authoritative; there is no dependency on an untracked `.superpowers` ruling.

## Global constraints and execution protocol

- Task 0 runs before any implementation dispatch. It creates `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/PLAN-CORRECTIONS.md`, whose first line says it overrides this plan, and records a cause-based baseline against the reviewed #260 base. Attach that exact file to **every** implementer and reviewer brief, including Task 1.
- Task 1 is the only pre-integration implementation task. It starts from the reviewed local #260 merge and creates only `src/services/agent_schema_types.py`, `src/services/agent_schema_registry.py`, and `tests/unit/test_agent_schema_registry.py`; it modifies no #261/#263/#265-owned file.
- Before Task 2, refresh and expand the same corrections file against one concrete reviewed **local** integration commit containing #260, the final reviewed #261 head, the final reviewed #263 head, and reviewed #265. Re-probe heads immediately before the gate: #261 moved during plan correction from `439971b3448fd6d0d64a9993305da47193754a56` to `785d9aaca35a3a9103cd4283afdc6bda3b679882`, and #263 advanced from the supplied interface checkpoint `771910ca1045d165a54e794f48fd4f0c206e4fa7` to E2E-only commit `1d706e21b92aad68314da2e79bb4d1d5626663b7`, so no observed SHA is execution authority until review is final. Record full SHAs, prove each is an ancestor of `INTEGRATION_BASE`, rebase the implementation branch while retaining Task 1, and prove `INTEGRATION_BASE` is an ancestor of `HEAD`. Never fetch or depend on a remote integration ref; never use `447791d7af34aafc18612cecead6a90805b367ec`.
- Local shared-file order is exactly **#265 → #264 → #266**. Merge #264 locally only after its most-capable whole-branch review. No push, PR, publish, or remote merge is part of this plan.
- Invoke `/Users/robert.whiffin/.pyenv/shims/python -m pytest` exactly. Run `test ! -e .venv` before every backend gate and after it. Never run `uv`, `pip`, dependency installation, or create an environment.
- Run Playwright only from `frontend` with its checked-in dependency and config: `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)`. Do not run `npx` from the repository root and do not install anything.
- Preserve every v1 schema identity, bundle behavior, serialized payload, hash, revision, release, pinned conversation, exact-ID loader, four-argument `AgentRuntime.run(agent_key, graph_release_id, payload, assembly_context)`, and no-fallback behavior. A compatibility loader is test-only.
- Preserve #263/#265 wire contracts exactly: editable request content is under `candidate`; validation is `{"code":"invalid_draft","errors":[{"field":...,"code":...,"message":...}]}`; save conflicts retain #263's `stale_draft` family and coherent exact-seven server snapshot. Do not introduce `invalid_definition`, `path`, or unprefixed editable fields.
- The sole initial optional catalog name for all seven roles is `diagnostic_notes`. Never admit `speaker_notes`. Its type is `list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]] | None`, maximum eight, default `None`. Absence is omitted; explicit `null` and `[]` are retained as distinct values in diagnostics and traces.
- Persist only selected optional names and canonical-field guidance. Descriptor name/type/default/validator/description/example/eligibility are code-owned. Graph logic receives the original canonical Pydantic output only.
- Every explicit valid same-content save advances the shared lock/audit exactly once and returns `changed: false`. Every rejected request changes no candidate/hash/lock/audit/revision/release state.
- PostgreSQL files use `pytestmark = pytest.mark.postgres`, are explicitly collected by `integration-graph`, and execute with zero skips. Concurrency assertions cover identities, content, hash, actor, locks, backend PIDs, observed waiting, and no-write behavior—not counts.
- Before each task record `TASK_BASE=$(git rev-parse HEAD)`. After implementation/fixes and restored controller sabotage, record `TASK_HEAD`, then generate the review package from exactly `TASK_BASE..TASK_HEAD`. Every controller and reviewer sabotages a different executed production seam, verifies its marker with `rg`, captures real RED, restores exactly, proves marker removal/clean diff, and captures GREEN. Never use `HEAD~1` for review packages.
- The SDD workspace, corrections, briefs, reports, and packages all live under `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/`. No artifact for this plan may use the obsolete `2026-09-22-schema-driven-config-ui` path.

## Task 0: Correct the plan against code and record cause baselines

**Files (ignored execution evidence only):**

- `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/IMPLEMENTATION_BASE`
- `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/PLAN-CORRECTIONS.md`
- `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/reports/`
- `.superpowers/sdd/2026-09-22-safe-output-schema-overlays/packages/`

- [ ] **Step 1: Resolve the workspace and prove the reviewed #260 base before Task 1.** Run the SDD workspace helper for `docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md`. Re-probe the local reviewed #260 merge (plan-review evidence was `feat/langgraph-core` at `774703e4487877bf65e0eeff173892d3e00ceac5`, containing reviewed #260 head `29e03411487476383b34101b7b34513dbb917f26`), record the current full SHA instead of trusting these observations, prove the reviewed head is its ancestor, and base the implementation branch there. Do not commit Task 0 evidence.
- [ ] **Step 2: Write the pre-Task-1 corrections table.** Make the first line of `PLAN-CORRECTIONS.md` state that it overrides this plan. Include one row for every task's internal file/code/test consistency and one row for every task pair sharing a file or producer/consumer interface. Against #260, inventory the seven `OUTPUT_SCHEMAS`, v1 identities/digests, manifest serialization/hash seams, new-file collision check, exact interpreter, and relevant current test owners. Rule on every mismatch before Task 1. Every Task 1 brief and review receives this file.
- [ ] **Step 3: Record baseline causes, not counts.** Run `test ! -e .venv`; then `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py`; then `test ! -e .venv`. Record every failing node ID and first causal traceback/assertion, and every skip with its reason, in `reports/preflight-260.md`. Add any renamed/replacement file found by Step 2. An expected missing new Task 1 module is not an existing baseline cause.
- [ ] **Step 4: Refresh before Task 2 on concrete integrated code.** After Task 1 and only after reviewed #265 is locally integrated after final reviewed #261/#263, record `INTEGRATION_BASE` and all four predecessor heads, prove ancestry, rebase while retaining Task 1, and prove base ancestry of `HEAD`. Re-read the integrated manifest; runtime and persisted loader; `agent_runtime_identity.py`; recording/logging sink tests; all #261 graph callers/retries/failure suites; #263 writer/facade/route/schema/envelope/frontend owners; #265 validators/upgrade/UI; bootstrap; CI; PostgreSQL; and browser gates. Expand the same tables with exact owners, signatures, test names, baseline failure/skip causes, and rulings. Re-derive baselines after manifest/runtime/schema changes. Do not dispatch Task 2 until complete.

## Stable registry, trace, and wire interfaces

`src/services/agent_schema_types.py` exports recursive JSON types; frozen `CanonicalFieldGuidance`; frozen `SchemaOverlay`; `OptionalFieldDescriptor`; `SchemaContractIdentity`; `ValidatedAgentOutput(canonical_output: BaseModel, additional_fields: Mapping[str, JsonValue])`; and `ComposedAgentSchema(model, canonical_model, declared_optional_names)`. `additional_fields` is a `MappingProxyType` containing only explicitly supplied selected optional values.

`src/services/agent_schema_registry.py` exports retained v1/v2 bundles and `AgentSchemaRegistry.validate_overlay(agent_key, identity, overlay)`, `compose(agent_key, identity, overlay)`, `validate_output(composed, raw_output)`, `identity_for(agent_key, version)`, and `upgrade_content_to_v2(content)`. It owns exact digest checking, raw-key validation before Pydantic projection, separate canonical/optional validation, canonical reconstruction by canonical names only, and frozen optional projection.

The v2 bundle material is the v1 canonical material plus registry grammar, top-level `extra="forbid"`, raw-key policy, and each role's descriptor metadata. Freeze calculated SHA-256 literals; retain all seven v1 literals unchanged. V1 has no optional catalog. V2 has exactly `diagnostic_notes` with these authoritative description/example pairs:

| Role | Description | Example |
|---|---|---|
| Architect | Concise assumptions or ambiguities that influenced the selected intent; never substitute for `message`, `deck_spec`, `data_request`, targets, or a design proposal. | Assumed the request refers to the existing Q2 deck; no target slide numbers were supplied. |
| Analyst | Concise retrieval limitations, source disagreement, or interpretation assumptions; never replace `outcome`, `synthesis`, `sources`, `gap`, `reason`, or `tried_tools`. | The two sources use different fiscal calendars; synthesis compares calendar-quarter totals. |
| Builder | Concise non-executable rendering/design trade-offs or unavailable inputs; never contain HTML, scripts, image IDs, or a substitute for canonical slide output. | No supplied image IDs; used a text-and-chart composition. |
| Build Reviewer | Concise review-scope/evidence notes; never hide, replace, or add a finding outside canonical `findings`. | Contrast was assessed against the resolved style tokens supplied in this invocation. |
| Fixer | Concise reason for a narrowly limited or declined attempted fix; never replace `changed` or `change_summary`. | Did not alter the chart because the reported issue concerns only title overflow. |
| Fix Reviewer | Concise evidence about whether the original issue was resolved or a review limitation; never replace the canonical verdict/findings. | Verified the original overflow against the corrected title container. |
| Deck Reviewer | Concise deck-level review scope/limitations; never replace deck findings or introduce slide-level findings. | Narrative assessment used the supplied slide sequence; no presenter notes were available. |

Extend #261's identity/tracing boundary without adding a second sink. Its callback returns `ValidatedAgentOutput`, not an unvalidated model. Inside the callback, in order: invoke the adapter; convert provider failures exactly as #261 does; compare raw keys; validate the composed output; reconstruct the canonical model; freeze `additional_fields`. Only then may the recording or logging sink record success. A success event carries the identity plus allowlisted `additional_fields`; logging materializes a JSON-safe copy without prompt, payload, or canonical output. Required trace values are exactly `{}` for absent, `{"diagnostic_notes": null}` for explicit null, and `{"diagnostic_notes": []}` for an explicit empty list. Invalid canonical or optional output is observed by both sinks as an error and emits no success fields. Invalid persisted overlay/identity still fails before model invocation and before the sink; provider conversion remains inside the callback.

The ordinary PUT extends the landed aggregate request beneath `candidate.schema_overlay`; it never creates a sibling request convention. All editable overlay errors use fields `candidate.schema_overlay.field_overrides.<field>.<property>` or `candidate.schema_overlay.additional_optional_fields.<index>`. Errors retain registry order: local #263 validation, then registered validators in registration order, then each validator's issue order; field overrides follow request insertion order and property check order `description`, `examples`, while optional names follow tuple index. Codes are exactly `overlay_unknown_canonical_field`, `overlay_guidance_property_forbidden`, `overlay_description_blank`, `overlay_examples_empty`, `overlay_examples_invalid_json`, `overlay_optional_field_blank`, `overlay_optional_field_duplicate`, `overlay_optional_field_canonical_collision`, `overlay_optional_field_ineligible`, and `overlay_schema_contract_unavailable`. Runtime-only codes are `output_undeclared_top_level_field`, `output_invalid_canonical_field`, and `output_invalid_optional_field`.

The registry emits these exact editable issue literals; `<field>`, `<property>`, and `<index>` are replaced without altering the rest of the string:

| Condition | Field | Code | Message |
|---|---|---|---|
| unknown canonical field | `candidate.schema_overlay.field_overrides.<field>` | `overlay_unknown_canonical_field` | `Canonical field is not available for this agent.` |
| protected/unknown guidance property | `candidate.schema_overlay.field_overrides.<field>.<property>` | `overlay_guidance_property_forbidden` | `Only description and examples are editable.` |
| blank description | `candidate.schema_overlay.field_overrides.<field>.description` | `overlay_description_blank` | `Description must not be blank.` |
| empty examples | `candidate.schema_overlay.field_overrides.<field>.examples` | `overlay_examples_empty` | `Examples must contain at least one item.` |
| non-JSON example | `candidate.schema_overlay.field_overrides.<field>.examples` | `overlay_examples_invalid_json` | `Examples must contain JSON-compatible values.` |
| blank optional name | `candidate.schema_overlay.additional_optional_fields.<index>` | `overlay_optional_field_blank` | `Optional field name must not be blank.` |
| second/subsequent optional name | `candidate.schema_overlay.additional_optional_fields.<index>` | `overlay_optional_field_duplicate` | `Optional field names must be unique.` |
| canonical collision | `candidate.schema_overlay.additional_optional_fields.<index>` | `overlay_optional_field_canonical_collision` | `Optional field name collides with a canonical field.` |
| name absent from the role's closed catalog | `candidate.schema_overlay.additional_optional_fields.<index>` | `overlay_optional_field_ineligible` | `Optional field is not available for this agent.` |
| retained identity/digest cannot resolve | `candidate.schema_overlay` | `overlay_schema_contract_unavailable` | `Schema contract bundle is unavailable.` |

All admin `422` responses use this exact family:

```json
{"code":"invalid_draft","errors":[{"field":"candidate.schema_overlay.additional_optional_fields.0","code":"overlay_optional_field_ineligible","message":"Optional field is not available for this agent."}]}
```

Malformed JSON uses `{"field":"$","code":"invalid_json","message":"Request body must be valid JSON."}` in that envelope; strict parser errors retain request traversal order. Protected/unknown keys are `extra_forbidden`. `DraftContentRejected` preserves its already ordered issues without sorting or regrouping.

`POST /api/admin/agent-definitions/draft/{agent_key}/schema-contract-upgrade` accepts exactly `{"lock_version": 4}`. It parses only after admin/principal dependencies. Repeated current-version upgrade is `422 {"code":"invalid_draft","errors":[{"field":"schema_contract","code":"already_current","message":"Schema contract is already current."}]}`. An unavailable server-owned bundle is the same envelope with field `schema_contract`, code `overlay_schema_contract_unavailable`, and message `Schema contract bundle is unavailable.` Existing-content validation issues retain their `candidate.schema_overlay...` fields and ordered tuple. Invalid-plus-stale returns ordered `422`; valid stale returns `409`.

Ordinary-save `409` remains #263's body with the submitted aggregate `client_candidate`. Upgrade `409` is explicitly the same family with `client_candidate: null`:

```json
{"code":"stale_draft","expected_lock_version":4,"current_lock_version":5,"client_candidate":null,"server":{"draft":"<current DraftMetadata>","definitions":{"architect":"<DraftDefinition>","data_analyst":"<DraftDefinition>","builder":"<DraftDefinition>","build_reviewer":"<DraftDefinition>","fixer":"<DraftDefinition>","fix_reviewer":"<DraftDefinition>","deck_reviewer":"<DraftDefinition>"}}}
```

`server.definitions` must contain those exact seven keys, no missing or extra key, and every definition plus `server.draft` comes from one coherent locked snapshot. Both valid stale operations are no-writes. The client parses the null upgrade candidate explicitly and feeds the same seven-role merge/recovery reducer.

## Task 1: Isolated overlay types and retained registry kernel

**Files:** create only `src/services/agent_schema_types.py`, `src/services/agent_schema_registry.py`, and `tests/unit/test_agent_schema_registry.py`.

- [ ] Write RED tests for frozen recursive JSON, exact serialization, all seven retained v1 identities/empty catalogs, all seven v2 identities/catalog literals, digest mismatch/role mismatch, every allowed guidance mutation, every forbidden protected/nested property, blank/non-JSON/empty examples, optional blank/duplicate/canonical collision/ineligible/`speaker_notes`, dynamic `extra="forbid"`, raw-key rejection, canonical-class projection, immutable diagnostics, and absent/null/empty-list distinction.
- [ ] Run RED only after `test ! -e .venv`: `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py`; confirm failure is missing implementation, then `test ! -e .venv`.
- [ ] Implement without importing the manifest/runtime or editing an existing file. Registry construction consumes the seven existing `OUTPUT_SCHEMAS`; no request supplies JSON Schema or a contract identity.
- [ ] Run GREEN with the same gates. Controller sabotages the v2 descriptor map to `speaker_notes`; reviewer sabotages canonical collision or v1/v2 identity selection. Each proves distinct RED/restored GREEN.
- [ ] Commit only the three files with `feat: add isolated schema overlay registry`.

## Task 2: Integrate typed overlay grammar and retained identities

**Files:** modify `src/services/graph_definition_manifest.py`, `tests/unit/test_graph_definition_manifest.py`; extend `tests/unit/test_agent_schema_registry.py`.

- [ ] After Task 0's integration refresh, write RED tests proving byte-identical v1 payloads/hashes, typed guidance round-trip, v2 hash change, all v1/v2 identities, fail-closed missing/mismatched role/version/digest, and independent #265 assembly identity validation.
- [ ] Run `test ! -e .venv`; then `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_schema_registry.py`; then `test ! -e .venv`. RED must be the manifest integration, not a missing Task 1 module.
- [ ] Import/re-export typed overlay grammar while retaining `ContentIdentity(version, digest)` as storage/wire carrier. Do not regenerate Graph V1, couple schema and assembly versions, or accept client-selected identities.
- [ ] GREEN and compare cause sets. Controller alters a v1 digest/serialization; reviewer sabotages role-matched v2 resolution.
- [ ] Commit with `feat: type retained schema overlay identities`.

## Task 3: Runtime composition, canonical projection, diagnostics, and traces

**Files:** modify the integrated owners, expected `src/services/agent_runtime.py`, `src/services/agent_runtime_identity.py`, `tests/unit/test_agent_runtime.py`, `tests/unit/test_persisted_agent_runtime.py`; extend `tests/unit/test_agent_schema_registry.py`. Record replacements in corrections before dispatch.

- [ ] Write RED tests across all seven roles for composed v2 adapter schemas; canonical validators; undeclared/unselected optional rejection; original canonical output class; immutable diagnostics; and exact `{}`/null/empty-list values in both diagnostics and successful recording/logging traces. For both sinks, invalid canonical and invalid optional output must record/log one error outcome and no success fields. Retain provider conversion inside callback and pre-sink persisted-config failure. Re-run exact-ID loader, four-argument callers/retries, typed failures, and no-fallback tests from final #261.
- [ ] Run `test ! -e .venv`; then `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_agent_runtime.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_persisted_graph_release.py tests/unit/test_graph_nodes.py`; then `test ! -e .venv`. Compare failure causes.
- [ ] Extend the existing sink protocol/classes; do not add a parallel trace sink. Put adapter conversion plus `validate_output` inside the callback. The runtime consumes the returned `ValidatedAgentOutput`, exposes canonical output to graph logic, and copies the same frozen mapping into diagnostics. Preserve exact release selection, latency, protected assembly, retries, and error typing.
- [ ] GREEN. Controller removes raw-key comparison; reviewer moves validation after sink success (or drops trace fields). Each targeted test must RED/restored GREEN.
- [ ] Commit runtime, identity sink, and focused tests with `feat: trace validated schema overlay output`.

## Task 4: One locked v2 upgrade/save pipeline

**Files:** modify only integrated #263/#265 owners recorded by Task 0, expected `src/services/graph_configuration_draft.py`, `src/services/graph_configuration.py`, `src/services/graph_configuration_workbench.py`, `tests/unit/test_graph_configuration_draft.py`; create `tests/integration/test_agent_schema_overlay_postgres.py`; modify CI collection files only as needed.

- [ ] Write RED unit/PostgreSQL tests for ordinary identity rejection; registered validator order; server-owned v2 upgrade; retained v1 history/release; valid same-content lock/audit; invalid overlay total no-write; and forced two-session winner/loser with exact coherent snapshot, PIDs, waiter, content/hash/actor/lock.
- [ ] Run `test ! -e .venv`; then `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_graph_configuration_draft.py tests/unit/test_ci_collects_integration_tests.py`; then `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres /Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/integration/test_agent_schema_overlay_postgres.py`; then `test ! -e .venv`. PostgreSQL coverage has zero skips.
- [ ] Register schema validation in the existing immutable ordered validator tuple after local #263 checks and in the Task-0-recorded order relative to #265. Add the named schema upgrade through the same selected locked aggregate and common mapper/hash/flush/audit/lock path. Never add a second lookup, transaction, writer, mapper, route, or identity DTO.
- [ ] GREEN. Controller bypasses the schema validator; reviewer sabotages same-content audit or stale-loser no-write behavior.
- [ ] Explicitly enroll the PostgreSQL file in CI, rerun the collection guard, and commit with `feat: validate schema overlays in draft writer`.

## Task 5: Strict aggregate admin wire contract

**Files:** modify `src/api/schemas/agent_definitions.py`, `src/api/routes/agent_definitions.py`, `tests/unit/test_agent_definition_workbench_routes.py` after re-probing landed #265 ownership.

- [ ] Write RED direct-route tests for every allowed/forbidden mutation, exact ordered `{field, code, message}` tuples, malformed/protected keys, `candidate.schema_overlay...` prefixes, auth-before-body parsing, invalid-plus-stale `422`, same-content behavior, upgrade success/repeated/unavailable/stale, ordinary `client_candidate`, upgrade `client_candidate: null`, and exact-seven coherent `409` snapshots. Assert every rejection/stale path is a no-write.
- [ ] Run `test ! -e .venv`; then `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py`; then `test ! -e .venv`.
- [ ] Extend the landed aggregate `candidate` DTO; return read-only descriptor display data; reuse the one writer/upgrade and existing response helpers. Parse only after authorization/principal dependencies and never echo a non-admin body.
- [ ] GREEN. Controller admits protected `type`; reviewer disrupts issue order or exact-seven snapshot validation.
- [ ] Commit with `feat: expose safe schema overlay editing`.

## Task 6: Typed client, protected schema editor, and browser proof

**Files:** extend the Task-0-recorded #263/#265 owners, expected `frontend/src/api/agentDefinitions.ts`, `AgentDefinitionWorkbench.tsx`, `DefinitionEditor.tsx`, `useDraftEditor.ts`, `draftEditorState.ts` and their direct tests; add an `OutputSchemaEditor` and direct test if needed; modify mocks and `frontend/tests/e2e/agent-definition-workbench.spec.ts`. Do not add a second state machine, request counter/ref, pending gate, conflict model, or autosave path.

- [ ] Write RED parser/reducer/component/API tests for seven descriptors; exact request and `invalid_draft` parsers; read-only protected labels; no editable type/default/enum/validator; v1 until upgrade; select/remove/save; cross-tab/role local persistence; ordered 422; ordinary/upgrade 409 including null candidate; exact-seven merge; A2→A3 preservation; one aggregate Save/Assembly Upgrade/Schema Upgrade gate; monotonic response IDs; and zero requests from typing/navigation.
- [ ] Run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)` plus direct landed #265/editor tests named by corrections; run `(cd frontend && npm run typecheck)` and scoped lint. Use checked-in dependencies only.
- [ ] Extend `agentDefinitions.ts` transport/parsers and #263's single hook/reducer/controller. The Output Schema tab displays code-owned name/type/required/default/enums and only editable description/examples plus the closed `diagnostic_notes` picker. Preserve all #265 aggregate operations and exact-seven conflict recovery.
- [ ] GREEN. Controller injects `candidate.schema_overlay.field_overrides.intent.type`; reviewer sabotages cross-operation response ordering or A2→A3 preservation.
- [ ] Add Playwright proof for explicit edit/save/reload, v2 selection, absent protected controls, stable direct malformed-API 422, and Save/Upgrade gate. Run `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)`.
- [ ] Commit with `feat: edit output schema overlays`.

## Task 7: Whole-slice verification, review, and local handoff

- [ ] Run `test ! -e .venv`, then the full cause-based backend matrix with `/Users/robert.whiffin/.pyenv/shims/python -m pytest -q`: registry, manifest, runtime, identity/trace sinks, final #261 persisted loader/callers/retries/failures, #263/#265 draft/route/content mapping, bootstrap, CI collection, all prompt-assembly tests, and all three PostgreSQL suites. Use the explicit PostgreSQL URL required by the integrated suite. Zero PostgreSQL skips; compare named failure/skip causes, then `test ! -e .venv`.
- [ ] Run final #263/#265/#264 frontend units, typecheck, scoped lint, and `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)`. Compare warning causes, not counts.
- [ ] Controller performs a final sabotage on a production seam unused by every task reviewer. Verify v1 reproducibility; seven-role validators/routing isolation; exact-ID/no fallback; invalid output as trace error; successful `{}`/null/empty-list recording and logging traces; direct API protection; exact-one-write concurrency; no `speaker_notes`; one writer/route/state machine; #265 independence; and CI collection.
- [ ] Generate the whole-branch package from the exact recorded implementation base to `HEAD`. Dispatch the most-capable available reviewer with the corrections file, reports, every ledger ruling/deferred item, and controller sabotage evidence. Require a writer-by-writer comparison, sink outcome table, rollback/no-write ruling, and merge/no-merge verdict. If needed, use one fix wave and one scoped re-review.
- [ ] Only after clean review, commit any reviewed test corrections, then merge #264 **locally** into `feat/langgraph-core` after #265 and record the merge commit. Do not push or open a PR. #266 starts only from that reviewed local commit.

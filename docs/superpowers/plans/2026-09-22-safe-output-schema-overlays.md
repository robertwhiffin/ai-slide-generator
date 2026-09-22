# Safe Output-Schema Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans-tellr` and `superpowers:subagent-driven-development` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let administrators safely tune canonical-field guidance and select the code-owned `diagnostic_notes` optional field without changing executable graph contracts.

**Architecture:** `AgentSchemaRegistry` is the only owner of versioned canonical schema bundles, overlay validation, dynamic model composition, and projection back to the original Pydantic model. The #263 locked writer remains the only mutation path: its ordered hooks validate endpoint, schema overlay, and protected assembly, then it performs one map/hash/flush/audit/lock update. A server-owned schema-contract upgrade changes a mutable draft from retained v1 to retained v2; ordinary saves cannot name either identity.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, React 19, TypeScript 5.9, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` §§7–8, 11, 14–18; GitHub #264; `.superpowers/issue-264-optional-catalog-ruling.md` from the #260 worktree.

## Global Constraints

- Begin only from one reviewed integration commit containing #260, #261, and #263; never from `447791d7a`. Before the shared slice, rebase on that commit and re-probe every route, type, hook, writer, response, and frontend state seam named below. Record the commit and corrections ledger.
- Land #265 protected-assembly integration first. Then land this plan's schema/runtime/draft-writer/route/client/workbench slice; #266's endpoint/client/editor slice follows. Isolated registry/types/tests may be developed earlier, but may not edit shared files.
- Python is `/Users/robert.whiffin/.pyenv/shims/python` at 3.11. Use `python -m pytest`; never use `uv`, pip, or a virtual environment. Stop if `.venv` exists.
- Preserve every v1 schema identity, bundle behavior, hash, revision, release, and pinned conversation. Add retained server-owned v2 identities/digests; no normal #263 save accepts `schema_contract` or protected identities.
- The sole initial optional catalog name is `diagnostic_notes`, for all seven keys. Never admit `speaker_notes`. It is `list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]] | None`, maximum eight, default `None`: absent is omitted from diagnostics, explicit null is retained, and `[]` is retained.
- Persist only selected optional names and canonical-field guidance. Descriptor name/type/default/validator/description/example/eligibility are code-owned. Canonical graph output remains the original Pydantic model; diagnostics retain an immutable mapping separate from it.
- All explicit valid same-content saves advance #263's shared lock/audit exactly once and return `changed: false`.
- New PostgreSQL files declare `pytestmark = pytest.mark.postgres`, are explicitly named in the `integration-graph` command in `.github/workflows/test.yml`, and are protected by `tests/unit/test_ci_collects_integration_tests.py`.

## Mandatory integration gate (before Task 1)

Confirm #265's protected-assembly integration is merged and reviewed, then rebase this branch onto the single reviewed #260+#261+#263+#265 integration commit. Record `git rev-parse HEAD`, the #265 commit, and a corrections ledger after re-reading `graph_definition_manifest.py`, `agent_runtime.py`, `graph_configuration_draft.py`, `graph_configuration.py`, `graph_configuration_workbench.py`, `agent_definitions.py` route/schema, `agentDefinitions.ts`, workbench state/component, and their unit/integration/browser tests. Stop and correct this plan if #263's writer hook, route envelope, upgrade protocol, or #265's content validator uses a different name; do not create an adapter route, a second writer, or a compatibility guess.

## Stable interfaces and error contract

`src/services/agent_schema_registry.py` exports `JsonScalar = str | int | float | bool | None`, recursive `JsonValue`, `CanonicalFieldGuidance(description: str | None, examples: tuple[JsonValue, ...] | None)`, `OptionalFieldDescriptor(name, annotation, default, description, examples)`, `ValidatedAgentOutput(canonical_output: BaseModel, additional_fields: Mapping[str, JsonValue])`, `ComposedAgentSchema(model, canonical_model, declared_optional_names)`, and `AgentSchemaRegistry.validate_overlay(agent_key, identity, overlay)`, `compose(agent_key, identity, overlay)`, `validate_output(composed, raw_output)`, `identity_for(agent_key, version)`, and `upgrade_content_to_v2(content)`. `additional_fields` is `MappingProxyType`.

The v2 bundle material is the v1 canonical material plus registry grammar, top-level `extra="forbid"`, raw-key policy, and each role's descriptor metadata. Freeze its calculated SHA-256 literals in source/tests; retain the existing seven v1 literals unchanged. `identity_for(..., 1)` has no optional catalog; `identity_for(..., 2)` has exactly `diagnostic_notes` with these fixed descriptions/examples: Architect “Concise assumptions or ambiguities that influenced the selected intent; never substitute for `message`, `deck_spec`, `data_request`, targets, or a design proposal.” / “Assumed the request refers to the existing Q2 deck; no target slide numbers were supplied.”; Analyst “Concise retrieval limitations, source disagreement, or interpretation assumptions; never replace `outcome`, `synthesis`, `sources`, `gap`, `reason`, or `tried_tools`.” / “The two sources use different fiscal calendars; synthesis compares calendar-quarter totals.”; Builder “Concise non-executable rendering/design trade-offs or unavailable inputs; never contain HTML, scripts, image IDs, or a substitute for canonical slide output.” / “No supplied image IDs; used a text-and-chart composition.”; Build Reviewer “Concise review-scope/evidence notes; never hide, replace, or add a finding outside canonical `findings`.” / “Contrast was assessed against the resolved style tokens supplied in this invocation.”; Fixer “Concise reason for a narrowly limited or declined attempted fix; never replace `changed` or `change_summary`.” / “Did not alter the chart because the reported issue concerns only title overflow.”; Fix Reviewer “Concise evidence about whether the original issue was resolved or a review limitation; never replace the canonical verdict/findings.” / “Verified the original overflow against the corrected title container.”; Deck Reviewer “Concise deck-level review scope/limitations; never replace deck findings or introduce slide-level findings.” / “Narrative assessment used the supplied slide sequence; no presenter notes were available.”

Under #263's `invalid_definition` 422 envelope each field error is `{path, code, message}`. Use paths `schema_overlay.field_overrides.<field>.<property>` and `schema_overlay.additional_optional_fields.<index>` and codes exactly: `overlay_unknown_canonical_field`, `overlay_guidance_property_forbidden`, `overlay_description_blank`, `overlay_examples_empty`, `overlay_examples_invalid_json`, `overlay_optional_field_blank`, `overlay_optional_field_duplicate`, `overlay_optional_field_canonical_collision`, `overlay_optional_field_ineligible`, `overlay_schema_contract_unavailable`, `output_undeclared_top_level_field`, `output_invalid_canonical_field`, `output_invalid_optional_field`. Rejections change no candidate/hash/lock/audit/revision/release state.

### Task 1: Typed overlay grammar and retained schema registry

**Files:** Modify `src/services/graph_definition_manifest.py`, `src/services/agent_runtime.py`, `tests/unit/test_graph_definition_manifest.py`; create `src/services/agent_schema_registry.py`, `tests/unit/test_agent_schema_registry.py`.

**Interfaces:** Replace arbitrary `SchemaOverlay.field_overrides` with `Mapping[str, CanonicalFieldGuidance]`; retain serialized empty v1 shape. Registry resolves `(agent_key, ContentIdentity)` before validation and raises `IncompatibleSchemaContractError` for missing/mismatched retained bundles.

- [ ] **Step 1: Write RED tests** for all seven v1 identities resolving an empty catalog, all seven v2 identities resolving only `diagnostic_notes`, stable v1 hash/serialization, v2 identity/hash difference, every fixed descriptor string/example, allowed canonical description/examples, and every forbidden mutation: unknown/nested field, blank description, empty/non-JSON examples, descriptor `type/default/enum/validator/schema/name`, blank/duplicate/canonical/ineligible optional names, and `speaker_notes`.
- [ ] **Step 2: Run RED.** `python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_graph_definition_manifest.py` must fail because the grammar/registry/v2 bundles do not exist.
- [ ] **Step 3: Implement minimally.** Put frozen Pydantic grammar in the manifest, canonical JSON freeze/thaw support in the existing serializer, and all bundle/canonical-field introspection/catalog/digest logic in the new registry. Do not make the registry infer schema from persisted JSON or accept JSON Schema.
- [ ] **Step 4: Run GREEN** with the Step 2 command. Sabotage review: replace the v2 descriptor map with `speaker_notes`, prove the ineligible-field test is RED, restore, then rerun GREEN.
- [ ] **Step 5: Commit.** `git add src/services/graph_definition_manifest.py src/services/agent_runtime.py src/services/agent_schema_registry.py tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_schema_registry.py && git commit -m "feat: add safe schema overlay registry"`

### Task 2: Composition, validation, canonical projection, and diagnostics

**Files:** Modify `src/services/agent_runtime.py`, `tests/unit/test_agent_runtime.py`; extend `tests/unit/test_agent_schema_registry.py`.

**Interfaces:** Add `schema_overlay: SchemaOverlay` to `AgentDefinition` and `additional_fields: Mapping[str, JsonValue]` to `AgentInvocationDiagnostics`. `AgentRuntime.run` resolves registry bundle, passes `ComposedAgentSchema.model` to the adapter, calls `validate_output`, returns `canonical_output` as `result.output`, and copies the frozen diagnostic mapping. `CodeOwnedAgentDefinitionSource` supplies empty v1 overlay.

- [ ] **Step 1: Write RED tests** parameterized across all seven roles proving the adapter receives a composed v2 model; `diagnostic_notes` absent/null/[] remain three distinct states; output is the original role class and has no diagnostic attribute; unknown raw top-level fields fail; all unselected optional fields fail; and Architect build-without-deck-spec, Analyst success-without-synthesis/sources, and Builder `<style>` still fail canonical validators.
- [ ] **Step 2: Run RED.** `python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_agent_runtime.py` must fail on composition/projection.
- [ ] **Step 3: Implement minimally.** Configure dynamic subclasses `extra="forbid"`, compare raw keys before Pydantic projection, validate composed data, construct the canonical model from canonical names only, and retain only explicitly supplied selected values. Preserve model invocation, latency, protected assembly, and v1 behavior. Do not add diagnostics to graph state, deck rows, findings, or user messages.
- [ ] **Step 4: Run GREEN** with Step 2. Reviewer sabotage: remove raw-key comparison (or change composed config to `extra="ignore"`), prove undeclared-top-level RED, restore and rerun GREEN.
- [ ] **Step 5: Commit.** `git add src/services/agent_runtime.py tests/unit/test_agent_runtime.py tests/unit/test_agent_schema_registry.py && git commit -m "feat: compose safe agent output schemas"`

### Task 3: Rebase/re-probe gate and one locked v2 upgrade/save pipeline

**Files:** Modify only landed #263 seams: `src/services/graph_configuration_draft.py`, `src/services/graph_configuration.py`, `src/services/graph_configuration_workbench.py`, `tests/unit/test_graph_configuration_draft.py`; create `tests/integration/test_agent_schema_overlay_postgres.py`; modify `.github/workflows/test.yml`, `tests/unit/test_ci_collects_integration_tests.py` only if its existing discovery guard needs an explicit pin.

**Interfaces:** Use the recorded integration-gate names. Extend #263's registered validator protocol, not its route/writer, to order endpoint hook, `AgentSchemaRegistry` overlay/identity validation, #265 assembly hook, then one existing mapper/hash/flush/audit/lock update. Add `upgrade_draft_schema_contract(session, *, agent_key: AgentKey, expected_lock_version: int, actor: str) -> DraftSaveResult | DraftSaveConflict[None]`; it locks through the same writer, changes only schema identity to v2, validates the complete content, and follows same-content lock/audit semantics.

- [ ] **Step 1: Write RED unit and PostgreSQL tests.** Assert normal `save_draft_content` rejects supplied changed identity; named upgrade retains v1 history and mints v2 candidate hash; v1 release remains resolvable after v2 upgrade; a valid same-content save returns false while lock/audit advance once; invalid overlay leaves all rows unchanged; stale winner/loser returns one coherent lock snapshot and loser makes no write. PostgreSQL test must use two sessions/threads and assert backend PIDs, lock waiting, exact winner content/hash/actor/lock and loser snapshot, not counts.
- [ ] **Step 2: Run RED.** `python -m pytest -q tests/unit/test_graph_configuration_draft.py tests/integration/test_agent_schema_overlay_postgres.py tests/unit/test_ci_collects_integration_tests.py` must fail before the hook/upgrade exist.
- [ ] **Step 3: Implement minimally.** Register schema validation and the named upgrade with the existing #263 locked aggregate; never add a second lookup, route, transaction, mapper, hash, or identity writable DTO. Persist only validated guidance/selected names and server-selected v2 identity.
- [ ] **Step 4: Run GREEN** with Step 2. Reviewer sabotage: bypass the overlay hook in the trusted full-content save, prove direct invalid-content test RED, restore and rerun GREEN.
- [ ] **Step 5: CI enrollment and commit.** Add the new file to `integration-graph`'s explicit pytest list and preserve `pytestmark = pytest.mark.postgres`; run `python -m pytest -q tests/unit/test_ci_collects_integration_tests.py`; commit `feat: validate schema overlays in draft writer`.

### Task 4: Strict admin wire contract and protected upgrade operation

**Files:** Modify `src/api/schemas/agent_definitions.py`, `src/api/routes/agent_definitions.py`, `tests/unit/test_agent_definition_workbench_routes.py`.

**Interfaces:** Extend the single landed `PUT /api/admin/agent-definitions/draft/{agent_key}` DTO with strict `schema_overlay`; it accepts only guidance description/examples and optional name strings, never identities/descriptors/schema/default/type/validator. Add admin-only `POST /api/admin/agent-definitions/draft/{agent_key}/schema-contract-upgrade` accepting only `lock_version`; it calls the Task 3 operation. Both map `DraftContentRejected` to exact ordered `invalid_definition` field errors and stale results to #263's existing 409 shape.

- [ ] **Step 1: Write RED direct-route tests** for all allowed mutations and all codes/paths above, malformed/protected descriptor keys, non-admin-before-body parsing, stale no-write, repeated save lock bump/`changed:false`, and v2 upgrade success/stale/forbidden identity injection.
- [ ] **Step 2: Run RED.** `python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py`.
- [ ] **Step 3: Implement and run GREEN.** Parse only strict DTOs, invoke the one writer/upgrade seam, and return descriptor display metadata read-only in workbench responses. Sabotage review: add `type` to guidance request DTO, prove protected-property route test RED, remove it and rerun GREEN.
- [ ] **Step 4: Commit.** `git add src/api/schemas/agent_definitions.py src/api/routes/agent_definitions.py tests/unit/test_agent_definition_workbench_routes.py && git commit -m "feat: expose safe schema overlay editing"`

### Task 5: Typed client, protected schema editor, and browser proof

**Files:** Modify `frontend/src/api/agentDefinitions.ts`, `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`, `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`, `frontend/tests/fixtures/mocks.ts`, `frontend/tests/e2e/agent-definition-workbench.spec.ts`; create `frontend/src/components/Admin/AgentDefinitionWorkbench/schemaOverlayState.ts` and `schemaOverlayState.test.ts`.

**Interfaces:** Export exact overlay guidance, read-only descriptor, save request/response/error parsers, and `upgradeSchemaContract(agentKey, lockVersion)`. State retains local overlay by agent, serializes only guidance/name selections, rehydrates server snapshots/lock after success, retains local values on 422/409, and has no autosave. The Output Schema tab renders protected canonical name/type/required/default/enums plus only description/examples inputs and the closed `diagnostic_notes` picker; never raw JSON or editable protected metadata.

- [ ] **Step 1: Write RED reducer/component/API tests** for all seven descriptors, protected labels and absent editable type/default/enum/validator controls, select/remove/save, local persistence across tabs/agents, exact PUT body, 422 paths, 409 recovery, v2 upgrade, and no typing/navigation request.
- [ ] **Step 2: Run RED.** `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/schemaOverlayState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)`.
- [ ] **Step 3: Implement then GREEN.** Parse responses before reducer dispatch. Reviewer sabotage: inject `schema_overlay.field_overrides.intent.type` into serialized request; prove request-shape test RED, restore and rerun GREEN.
- [ ] **Step 4: Add and run Playwright proof.** Test an admin changes Architect guidance, selects `diagnostic_notes`, explicitly saves, reloads, sees v2/selection; verify protected controls never appear and a direct malformed API request receives the stable 422. Run `npx playwright test frontend/tests/e2e/agent-definition-workbench.spec.ts`.
- [ ] **Step 5: Commit.** `git add frontend/src/api/agentDefinitions.ts frontend/src/components/Admin/AgentDefinitionWorkbench frontend/tests/fixtures/mocks.ts frontend/tests/e2e/agent-definition-workbench.spec.ts && git commit -m "feat: edit output schema overlays"`

### Task 6: Whole-slice verification and handoff

- [ ] **Step 1: Run** `python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py tests/unit/test_graph_configuration_draft.py tests/unit/test_agent_definition_workbench_routes.py tests/integration/test_agent_schema_overlay_postgres.py tests/unit/test_ci_collects_integration_tests.py` and the Task 5 browser command.
- [ ] **Step 2: Review** v1 pinned-release reproducibility; all seven role validators/routing isolation; absent/null/[] diagnostics; direct-API bypass; exactly-one-write concurrency; no `speaker_notes`; one writer/route; and test collection. The diagnostic trace scope is intentionally limited to `AgentInvocationDiagnostics.additional_fields`; do not claim MLflow serialization because current `AgentRuntime` has no trace hook. When #258's test-workbench sink lands, it must serialize that mapping verbatim and receive a separate test.
- [ ] **Step 3: Commit any review corrections** with `test: harden schema overlay regressions`.

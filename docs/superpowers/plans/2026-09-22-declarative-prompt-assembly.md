# Declarative Protected Prompt Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every model-driven graph role a versioned declarative prompt assembler with editable custom blocks only at protected legal anchors.

**Architecture:** `PromptAssembler` owns protected bundle resolution, validation, condition evaluation, serialization, and assembly. `AgentRuntime` remains the sole graph-facing caller and model adapter owner. Frozen v1 definitions retain their historical byte-compatible plan; v2 persists only custom blocks and enters a draft through #263's one locked writer and an explicit server-owned identity upgrade.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, FastAPI, React 19, TypeScript 5.9, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (§§7, 9, 11.1, 14–17), GitHub issues #258, #263, and #265; `docs/superpowers/plans/2026-09-22-shared-graph-draft-editing.md`.

## Global Constraints

- Start only from a reviewed merge base containing completed #260 and #263. Write its full SHA to `.superpowers/2026-09-22-declarative-prompt-assembly/IMPLEMENTATION_BASE`; do not use research branch/commit `447791d7a` as a base or source of production changes.
- Load `executing-plans-tellr` and `superpowers:subagent-driven-development`, create `PLAN-CORRECTIONS.md`, and re-probe all interfaces before Task 1. The plan is not runtime evidence.
- Use `/Users/robert.whiffin/.pyenv/shims/python` with `python -m pytest`; never run `uv`, `pip`, install dependencies, or create `.venv`. Stop if `.venv` exists.
- `src/services/agent_definition_manifest_v1.py`, generated v1 JSON, v1 identities/digests, published revisions, and releases are historical. Never regenerate or mutate them for v2.
- V1 remains exact: `DefinitionContent.validate_role_assembly` must still compare a v1 document to `assembly_rules_for(agent_key)`. V2 must validate against a code-owned bundle plan, not a loosened v1 literal.
- Conditions are exactly `always`, `design_system_active`, `design_system_inactive`, and `payload_has_deck_brief`; the latter is `bool(payload.get("deck_brief"))`. No stored code, expression, or caller-provided condition truth is permitted.
- Only `PromptAssembler` serializes a v2 payload, exactly once with `json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)`, between code-owned `<untrusted-data>` delimiters. Only `DatabricksModelAdapter` calls `with_structured_output`.
- Normal #263 saves retain both protected identities. An explicit protected-assembly upgrade shares #263's locked transaction, validation, canonical mapper/hash, audit update, lock increment, and conflict envelope; it is not a second writer. Explicit same-content saves advance lock/audit once and return `changed:false`.
- Isolated modules/tests may be prepared concurrently, but all shared manifest/runtime/draft-writer/route/client/workbench integration is serialized after reviewed #264 and before #266. Rebase and re-probe immediately before Task 4.
- No #264 overlay policy, #266 endpoint policy, migration/DDL, publication/evidence, graph payload construction, tool wiring, or Foreman change is in scope.
- Every task is RED → minimal GREEN → sabotage RED → restore GREEN and ends in its listed commit. PostgreSQL coverage must execute rather than skip.

## Stable interfaces

In `src/services/graph_definition_manifest.py`, replace the current single rules type with this discriminated frozen union; all models retain `extra="forbid", frozen=True`.

```python
AssemblyCondition: TypeAlias = Literal[
    "always", "design_system_active", "design_system_inactive", "payload_has_deck_brief",
]
CustomAnchor: TypeAlias = Literal[
    "after_authored_prompt", "after_deck_brief", "after_environment_constraints",
]

class CustomTextBlock(_FrozenModel):
    kind: Literal["custom_text"]
    block_id: UUID
    anchor: CustomAnchor
    condition: AssemblyCondition
    text: str

class AssemblyRulesV1(_FrozenModel):
    format_version: Literal[1]
    separator: Literal["\n\n"]
    blocks: tuple[AssemblyBlockV1, ...]

class AssemblyRulesV2(_FrozenModel):
    format_version: Literal[2]
    custom_blocks: tuple[CustomTextBlock, ...]

AssemblyRules: TypeAlias = Annotated[
    AssemblyRulesV1 | AssemblyRulesV2, Field(discriminator="format_version")
]
```

Whitespace-only custom text and duplicate UUIDs are rejected without rewriting text. `after_deck_brief` is allowed only for `build_reviewer` with condition `payload_has_deck_brief`; the other anchors are legal for all seven roles. No anchor can occur after payload or terminal binding.

Create `src/services/prompt_assembler.py`:

```python
@dataclass(frozen=True)
class AssembledPrompt:
    prompt: str
    terminal_binding: Literal["langchain.with_structured_output"]
    protected_stages: tuple[ResolvedProtectedStage, ...]

class PromptAssemblyRejected(ValueError):
    issues: tuple[PromptAssemblyIssue, ...]

class PromptAssembler:
    def resolve_bundle(self, identity: ContentIdentity) -> ProtectedAssemblyBundle:
        raise NotImplementedError
    def validate(self, *, definition: DefinitionContent) -> None:
        raise NotImplementedError
    def assemble(self, *, definition: DefinitionContent,
                 payload: Mapping[str, object],
                 context: AgentAssemblyContext) -> AssembledPrompt:
        raise NotImplementedError
    def protected_stage_view(self, *, agent_key: AgentKey,
                             identity: ContentIdentity) -> tuple[ResolvedProtectedStage, ...]:
        raise NotImplementedError
```

V2 stage order is authored prompt; legal custom blocks after authored prompt; generated Build Reviewer criteria for that role; conditional deck brief and its legal custom blocks; exactly one environment constraint and its legal custom blocks; notice; opening delimiter; canonical JSON; closing delimiter; terminal binding. V1 resolves forever with its existing stage order/raw serialization.

After #263/#264 integration, extend the existing facade rather than creating a service/route writer:

```python
def upgrade_draft_protected_assembly(
    self, session: Session, *, agent_key: AgentKey,
    expected_lock_version: int, actor: str,
) -> DraftSaveResult | DraftSaveConflict[None]:
    raise NotImplementedError
```

Expose `POST /api/admin/agent-definitions/draft/{agent_key}/protected-assembly-upgrade`, strict body `{"lock_version": 4}`. No version/digest/stage/client actor is accepted. Under #263's existing locks, it replaces only stored v1 identity/rules with the server's v2 identity and empty custom blocks; it preserves authored/model/overlay/schema identity and calls `_write_locked_content` once. Existing v2 is `422 already_current`; stale is #263's 409. The existing one writer validates endpoint, #264 schema, then `PromptAssembler.validate`, before mapping/hash/flush/audit/lock.

### Task 1: Freeze v1 and define v2 content grammar

**Files:**
- Modify: `src/services/graph_definition_manifest.py:47-239`
- Modify: `tests/unit/test_graph_definition_manifest.py:1-442`
- Create: `tests/unit/test_prompt_assembler.py`

**Produces:** `AssemblyRulesV1`, `AssemblyRulesV2`, `CustomTextBlock`, and `AssemblyRules` for all following tasks.

- [ ] **Step 1: Write failing grammar/hash tests**

Keep the independent v1 replay helper and assert every generated v1 record is `AssemblyRulesV1` and still fails if any literal block is changed. Add a v2 factory using fixed UUIDs. Test hash changes for reorder, UUID, text, anchor, and condition; test all four legal conditions and anchors; test duplicate UUID, whitespace text, unknown kind/condition/anchor, extras, non-Reviewer deck anchor, and non-`payload_has_deck_brief` deck anchor.

```python
def test_v2_hash_includes_custom_identity_and_order() -> None:
    first = _v2("architect", [_custom("00000000-0000-0000-0000-000000000001", "one"), _custom("00000000-0000-0000-0000-000000000002", "two")])
    second = first.model_copy(update={"assembly_rules": AssemblyRulesV2(format_version=2, custom_blocks=tuple(reversed(first.assembly_rules.custom_blocks)))})
    assert definition_content_hash(first) != definition_content_hash(second)
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_graph_definition_manifest.py tests/unit/test_prompt_assembler.py
test ! -e .venv
```

Expected: collection fails because v2 grammar/assembler do not exist; current v1 test selection stays green.

- [ ] **Step 3: Implement frozen discriminated models**

Rename current v1 aliases to `AssemblyBlockV1`/`AssemblyRulesV1`; preserve `assembly_rules_for()` byte-for-byte. Branch `DefinitionContent.validate_role_assembly`: exact current equality for v1; structural v2 role/anchor checks only. Do not import the assembler or generated manifest.

- [ ] **Step 4: GREEN and sabotage**

Run Step 2. Then temporarily make `block_id` a private/non-dumped attribute and mark `TASK1_BLOCK_ID_HASH_SABOTAGE`; run:

```bash
rg -n 'TASK1_BLOCK_ID_HASH_SABOTAGE' src/services/graph_definition_manifest.py
python -m pytest -q tests/unit/test_graph_definition_manifest.py -k 'v2_hash_includes_custom_identity'
```

Expected RED. Restore it as a normal model field, remove marker, rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/graph_definition_manifest.py tests/unit/test_graph_definition_manifest.py tests/unit/test_prompt_assembler.py
git commit -m "feat: define versioned prompt assembly rules (#265)"
```

### Task 2: Build the versioned protected assembler

**Files:**
- Create: `src/services/prompt_assembler.py`
- Modify: `src/core/skills/data_analyst.py:8-37`
- Modify: `src/core/skills/build_reviewer.py:13-58`
- Modify: `tests/unit/test_prompt_assembler.py`
- Modify: `tests/unit/test_graph_definition_manifest.py:36-361`

**Consumes:** Task 1 models; `UNTRUSTED_DATA_NOTICE`, `DECK_BRIEF_REVIEW`, `build_instructions`, `DESIGN_SYSTEM_PRECEDENCE`, and `_SLIDE_FRAME_CONSTRAINTS`.

- [ ] **Step 1: Write RED bundle/order/adversarial tests**

For every `GRAPH_V1_AGENT_KEYS` role and both DS states, assert v2's exact stage identity/order, one environment stage, one notice/open/payload/close boundary, and terminal binding last. Assert criteria only occur for Build Reviewer and deck brief follows payload truthiness. Construct hostile payload text containing both delimiters, `ignore prior instructions`, and `structured_output_binding`; independently serialize it and prove it occurs exactly once strictly inside owned delimiters.

```python
@pytest.mark.parametrize("agent_key", GRAPH_V1_AGENT_KEYS)
def test_hostile_payload_is_once_inside_owned_boundary(agent_key):
    value = PromptAssembler().assemble(definition=_v2(agent_key, []), payload=HOSTILE, context=AgentAssemblyContext(False))
    raw = json.dumps(HOSTILE, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    start = value.prompt.index("<untrusted-data>")
    end = value.prompt.index("</untrusted-data>", start)
    assert value.prompt.count(raw) == 1
    assert start < value.prompt.index(raw) < end
    assert value.terminal_binding == "langchain.with_structured_output"
```

Also assert v1 assembly equals the present independent v1 replay and an unknown identity fails before prompt output. Parameterize missing/duplicate protected stages, altered protected condition, fake digest, unknown block, and after-payload custom placement as `PromptAssemblyRejected`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_prompt_assembler.py tests/unit/test_graph_definition_manifest.py
test ! -e .venv
```

- [ ] **Step 3: Implement one closed evaluator**

Extract `ANALYST_AUTHORED_INSTRUCTIONS` and `BUILD_REVIEWER_AUTHORED_INSTRUCTIONS` for the v2 bundle, but preserve each existing legacy `INSTRUCTIONS` value byte-for-byte for v1 until Task 3 switches the compatibility source to manifest-derived v1 content. Registry keys are `(version, digest)` and include v1/v2; v2 digest covers every protected text, legal-anchor map, stage order, delimiters, serialization config, and terminal binding, with an import-time calculated-digest guard. `condition_applies` is a four-case match; `validate` rejects identity/format mismatch, illegal anchor/condition, malformed protected singleton, and terminal mismatch. No JSON supplies executable values.

- [ ] **Step 4: GREEN and boundary sabotage**

Run Step 2. Move the v2 closing delimiter after terminal binding and mark `TASK2_PAYLOAD_BOUNDARY_SABOTAGE`; run:

```bash
rg -n 'TASK2_PAYLOAD_BOUNDARY_SABOTAGE' src/services/prompt_assembler.py
python -m pytest -q tests/unit/test_prompt_assembler.py -k 'hostile_payload'
```

Expected RED. Restore bundle order/remove marker/rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/prompt_assembler.py src/core/skills/data_analyst.py src/core/skills/build_reviewer.py tests/unit/test_prompt_assembler.py tests/unit/test_graph_definition_manifest.py
git commit -m "feat: add protected prompt assembler (#265)"
```

### Task 3: Delegate runtime assembly without bypasses

**Files:**
- Modify: `src/services/agent_runtime.py:33-510`
- Modify: `tests/unit/test_agent_runtime.py:1-363`
- Modify: `tests/unit/test_graph_definition_manifest.py:307-361`

**Produces:** `AgentDefinition.assembly_rules` and one v1/v2 runtime assembly path, preserving the public `run(agent_key, payload, assembly_context)` interface.

- [ ] **Step 1: Write RED runtime tests**

Build v1 definitions from manifest content and assert exact present prompts across seven roles/DS states. Build v2 definitions and assert hostile boundary/diagnostic equality. Each malformed v2 definition must raise `PromptAssemblyRejected` and leave `RecordingModelAdapter.calls == []`. Add search proof that `agent_runtime.py` and `graph/nodes.py` have no `json.dumps(payload` and only adapter code has `with_structured_output(`; include Builder/Fixer retry call sites.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_agent_runtime.py tests/unit/test_graph_definition_manifest.py
test ! -e .venv
```

- [ ] **Step 3: Make runtime an assembler client**

Add `assembly_rules` to `AgentDefinition`. Make `CodeOwnedAgentDefinitionSource` derive v1 content from `load_graph_v1_manifest()` rather than independently recreating rules. Replace private `_assemble_prompt`/bundle registry use with `PromptAssembler.assemble`; require terminal binding then call unchanged adapter. Preserve unknown role/schema-contract behavior and do not edit graph nodes.

- [ ] **Step 4: GREEN and delegation sabotage**

Run Step 2. Replace assembler call with `prompt = definition.prompt_text  # TASK3_RUNTIME_BYPASS_SABOTAGE`, then:

```bash
rg -n 'TASK3_RUNTIME_BYPASS_SABOTAGE' src/services/agent_runtime.py
python -m pytest -q tests/unit/test_agent_runtime.py -k 'hostile or v2 or deck_brief'
```

Expected RED. Restore/rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/agent_runtime.py tests/unit/test_agent_runtime.py tests/unit/test_graph_definition_manifest.py
git commit -m "feat: route runtime prompts through assembler (#265)"
```

### Task 4: Serialize #265 backend integration through #263's writer

**Gate:** #264 must be reviewed and merged first. Rebase, record its SHA and actual interface corrections in the ledger, then inspect the single resulting validation pipeline. This is #265's shared backend integration before #266.

**Files:**
- Modify: `src/services/graph_configuration_draft.py`
- Modify: `src/services/graph_configuration.py`
- Modify: `src/api/schemas/agent_definitions.py`
- Modify: `src/api/routes/agent_definitions.py`
- Modify: `tests/unit/test_graph_configuration_draft.py`
- Modify: `tests/unit/test_agent_definition_workbench_routes.py`
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`

- [ ] **Step 1: Write RED writer/route/PostgreSQL tests**

Valid v2 trusted content writes via `definition_content_values`, hash, lock/audit once, and preserves schema identity. Fake digest, invalid placement, payload block, duplicate terminal, and unknown condition return structured 422 before any row/lock/audit mutation or model call. A valid stale candidate produces coherent #263 409/no mutation. A repeated valid same-content save returns `changed=False`, unchanged hash, but increments lock/audit exactly once.

Seed v1 then call the upgrade: only `assembly_rules`, protected identity, candidate hash, parent audit/lock change; prompt/model/overlay/schema/base revision/release/published v1 remain identical. Repeated upgrade is 422 `already_current`; stale is 409. POST accepts only lock; direct protected identity, terminal, format, digest, or actor input is rejected.

In real PostgreSQL, first session holds the #263 locks for a valid v2 save, second session upgrade waits, then sees stale 409. Assert distinct backend PIDs, observed waiter, winner lock 1, loser no mutation, and fresh upgrade at lock 1 yields lock 2.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_graph_configuration_draft.py tests/unit/test_agent_definition_workbench_routes.py
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres python -m pytest -q tests/integration/test_agent_definition_workbench_postgres.py -k 'assembly or upgrade or two_writers'
test ! -e .venv
```

- [ ] **Step 3: Extend the one transaction**

In existing #263 writer path invoke endpoint validation, #264 schema validation, then `PromptAssembler.validate`, before `definition_content_hash`, `definition_content_values`, flush, audit, and lock increment. Extend the strict editable save DTO with optional `candidate.assembly_rules`: omission retains the stored rules for a v1 model/prompt save; when supplied it must be the exact v2 `{format_version: 2, custom_blocks: [...]}` record, which the server rehydrates onto stored server-owned fields. It must reject v1 client rule records, identities, protected-stage records, delimiters, serialization settings, and terminal binding. GET/success/409 definition serializers additionally return the server-derived `protected_stage_view` (stage label, condition, locked boolean, bundle version/digest, and legal anchors), never raw bundle material. Normal saves keep strict protected identity comparison. Upgrade obtains #263 locked aggregate/stale result, server-constructs `AssemblyRulesV2(format_version=2, custom_blocks=())` and v2 identity, then calls the same validator/writer once; never direct-assign an ORM content column or re-query selected row. Add strict admin POST after existing authorization/body ordering and reuse #263 serializers/errors.

- [ ] **Step 4: GREEN and writer sabotages**

Run Step 2. Directly assign `locked.selected_row.protected_assembly_version = 2` before common writer with `TASK4_SECOND_WRITER_SABOTAGE`; focused upgrade/hash tests must RED. Restore. Remove same-content lock increment with `TASK4_SAME_CONTENT_LOCK_SABOTAGE`; the repeated-save test must RED. Restore and rerun Step 2 GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/graph_configuration_draft.py src/services/graph_configuration.py src/api/schemas/agent_definitions.py src/api/routes/agent_definitions.py tests/unit/test_graph_configuration_draft.py tests/unit/test_agent_definition_workbench_routes.py tests/integration/test_agent_definition_workbench_postgres.py
git commit -m "feat: validate and upgrade protected draft assembly (#265)"
```

### Task 5: Add strict v2 client transport and Assembly editor

**Files:**
- Modify: `frontend/src/api/agentDefinitions.ts`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.tsx`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/useDraftEditor.ts`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`
- Modify: `frontend/tests/fixtures/mocks.ts`

- [ ] **Step 1: Write RED parser/state/component tests**

Add recursive exact parsers for v1/v2 rules, UUIDs, closed anchors/conditions, protected-stage views, and upgrade responses. Reject non-records, extras, unknown literals, duplicate IDs, bad digest, and response mismatch. A v2 editable save candidate carries custom blocks; a v1 candidate omits assembly rules and keeps #263's model/prompt save behavior. Protected identities/stages/terminal text are response-only.

State tests prove add/edit/delete/reorder is local to selected role, uses `crypto.randomUUID()` in hook/controller (not reducer), marks Unsaved, and sends zero PUT before explicit Save. Existing #263 pending aggregate gate disables Save/Upgrade globally but retains typing and A2→A3/409 recovery blocks. Component tests prove locked stage label/condition/version/digest, legal anchors (deck only Build Reviewer), no post-payload affordance, block-id 422 alert, role/tab persistence, and POST body exactly `{lock_version: 0}`.

- [ ] **Step 2: Run RED**

```bash
(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)
(cd frontend && npm run typecheck)
```

- [ ] **Step 3: Implement local-only editor and shared hook operation**

Keep types/parsers/save/upgrade client in `agentDefinitions.ts`. `AssemblyEditor` takes immutable v2 rules and `onAssemblyRulesChange`; it never fetches. Render protected server view as locked rows and controls only under legal anchors; arrows reorder siblings, delete uses UUID, text label includes UUID. Compose it in #263 `DefinitionEditor` and extend its existing full local candidate immutably. `useDraftEditor` alone executes upgrade under the current pending request-id/ref gate, preserving the same parsed 200/409/422 recovery logic; no separate lock/status/conflict/autosave/refetch model.

- [ ] **Step 4: GREEN and sabotage**

Run Step 2. Inject `void onSave(agentKey); // TASK5_ASSEMBLY_AUTOSAVE_SABOTAGE` into custom-text change handler; focused no-save test must RED. Restore. Render an Add control after payload with `TASK5_AFTER_PAYLOAD_SABOTAGE`; no-post-payload test must RED. Restore/rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/agentDefinitions.ts frontend/src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.tsx frontend/src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts frontend/src/components/Admin/AgentDefinitionWorkbench/useDraftEditor.ts frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx frontend/tests/fixtures/mocks.ts
git commit -m "feat: edit anchored prompt blocks (#265)"
```

### Task 6: Browser, runtime, PostgreSQL, and scope proof

**Files:**
- Modify: `frontend/tests/e2e/agent-definition-workbench.spec.ts`
- Modify: `tests/unit/test_agent_runtime.py`
- Modify: `tests/unit/test_prompt_assembler.py`
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`

- [ ] **Step 1: Add Playwright RED coverage**

Mock GET/PUT/upgrade POST. Verify legal add/edit/reorder/delete, no PUT until Save, authoritative success/Needs test, inline 422, exact-seven 409 Reload/Keep local, v1 upgrade exact body/no identity, and repeated same-content save lock/audit response. Preserve lazy GET, topology, Foreman, keyboard tabs, errors, and overflow; replace only #260's obsolete “no Save Draft” guard, retaining Run/Approve/Publish/History/Rollback absence.

- [ ] **Step 2: Run RED then finish only test fixture wiring**

```bash
(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)
```

Expected RED until mocks match Tasks 4–5; then GREEN. Do not add production behavior here.

- [ ] **Step 3: Run final matrix**

```bash
python -m pytest -q tests/unit/test_graph_definition_manifest.py tests/unit/test_prompt_assembler.py tests/unit/test_agent_runtime.py tests/unit/test_graph_configuration_draft.py tests/unit/test_agent_definition_workbench_routes.py
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres python -m pytest -q tests/integration/test_agent_definition_workbench_postgres.py
test ! -e .venv
(cd frontend && npm run test:unit)
(cd frontend && npm run typecheck)
(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)
git diff --check
```

- [ ] **Step 4: Independent reviewer sabotages**

Make `payload_has_deck_brief` always true (`TASK6_DECK_BRIEF_CONDITION_SABOTAGE`); deck-brief tests must RED. Replace upgrade's `_write_locked_content` with direct row assignment (`TASK6_UPGRADE_WRITER_BYPASS_SABOTAGE`); real PostgreSQL upgrade/two-writer tests must RED. Send `{lock_version, protected_assembly:{version:2}}` in UI (`TASK6_CLIENT_IDENTITY_SABOTAGE`); exact-body Playwright test must RED. Restore each and rerun its exact test GREEN.

- [ ] **Step 5: Scope check and commit**

```bash
rg -n 'json\.dumps\(payload|with_structured_output\(' src/services/agent_runtime.py src/services/graph/nodes.py src/services/prompt_assembler.py
git diff --name-only "$(cat .superpowers/2026-09-22-declarative-prompt-assembly/IMPLEMENTATION_BASE)"..HEAD
git diff --check
git status --short
git add frontend/tests/e2e/agent-definition-workbench.spec.ts tests/unit/test_agent_runtime.py tests/unit/test_prompt_assembler.py tests/integration/test_agent_definition_workbench_postgres.py
git commit -m "test: verify protected prompt assembly flows (#265)"
```

Expected: only assembler has `json.dumps(payload`; only adapter has `with_structured_output`; no generated v1, migration, graph-node production, package, #264, or #266 files changed.

## Final review handoff

Review from `IMPLEMENTATION_BASE`, never `447791d7a`. Require: one-writer route/facade table; v1/v2 identity matrix; seven-role hostile payload matrix; same-content lock/audit proof; real PostgreSQL winner/loser proof; legal-anchor/422/409/no-write UI matrix; and a merge decision before #266 starts shared integration.

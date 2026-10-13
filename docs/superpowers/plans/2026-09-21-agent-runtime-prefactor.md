# AgentRuntime Prefactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all seven model-driven Graph Nodes through one behavior-preserving `AgentRuntime` interface while keeping Foreman deterministic and code-owned Agent Definitions as the temporary source.

**Architecture:** `src/services/agent_runtime.py` becomes a deep module whose single production interface resolves a code-owned Agent Definition, verifies protected-assembly and canonical-schema identities, assembles the exact current prompt, invokes the exact current structured model, and returns canonical output plus diagnostics. The graph depends only on that interface; definition and model adapters remain injectable internal seams for deterministic tests and later Lakebase cutover.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, Databricks LangChain, pytest, mypy, Ruff

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (issue #259 scope: runtime prefactor only)

## Global Constraints

- All seven model-driven roles execute through one `AgentRuntime` contract with behavior equivalent to the current shipped definitions.
- Foreman is not an Agent Definition and continues to execute deterministic routing code.
- Current protected prompt material and canonical schema contracts have stable version and SHA-256 digest identities resolved explicitly by the runtime.
- Unknown role keys, unavailable protected bundles, and incompatible schema contracts fail before any model call.
- Legacy `tool_grants` metadata remains inert; Agent Definition invocation never binds tools.
- Preserve the current prompt bytes, endpoint `databricks-claude-opus-4-6`, temperature `0.7`, maximum tokens `60000`, top-p `0.95`, canonical Pydantic output schemas, and returned graph behavior.
- Do not add Lakebase persistence, Conversation Pins, editable assembly, schema overlays, or tool resolution; those belong to issues #260 onward.
- Do not install dependencies into the shared pyenv site-packages.

---

### Task 1: Introduce the deep AgentRuntime module

**Files:**
- Create: `src/services/agent_runtime.py`
- Create: `tests/unit/test_agent_runtime.py`
- Reference: `src/core/skills/__init__.py`
- Reference: `src/services/agent_resolution.py`
- Reference: `src/domain/skill_io.py`

**Interfaces:**
- Consumes: current `Skill` records from `load_skill`, `DEFAULT_CONFIG["llm"]`, protected prompt constants, and `OUTPUT_SCHEMAS`.
- Produces: `AgentRuntime.run(agent_key: str, payload: Mapping[str, Any], assembly_context: AgentAssemblyContext) -> AgentInvocationResult`, `get_agent_runtime() -> AgentRuntime`, explicit runtime-contract exceptions, and immutable identity/diagnostic values.

- [ ] **Step 1: Write the failing runtime contract tests**

Add tests that import the not-yet-created runtime and specify its public behavior:

```python
@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
def test_every_model_driven_role_preserves_prompt_model_schema_and_output(agent_key):
    model = RecordingModelAdapter(output_for(agent_key))
    runtime = AgentRuntime.compatibility(model_adapter=model)

    result = runtime.run(
        agent_key,
        payload_for(agent_key),
        AgentAssemblyContext(design_system_active=False),
    )

    assert result.output == output_for(agent_key)
    assert model.calls[0].prompt == expected_current_prompt(agent_key)
    assert model.calls[0].configuration == AgentModelConfiguration(
        endpoint_name="databricks-claude-opus-4-6",
        temperature=0.7,
        max_tokens=60000,
        top_p=0.95,
    )
    assert model.calls[0].schema is OUTPUT_SCHEMAS[agent_key]
    assert result.diagnostics.agent_key == agent_key
```

Cover build-reviewer deck-brief conditioning, design-system precedence, frame constraints, JSON serialization, stable literal digests, and the absence of a `foreman` definition.

- [ ] **Step 2: Run the new test file and verify RED**

Run: `python -m pytest -q tests/unit/test_agent_runtime.py`

Expected: FAIL during import because `src.services.agent_runtime` does not exist.

- [ ] **Step 3: Add explicit failure and inert-tool tests**

Specify these cases before implementation:

```python
with pytest.raises(UnknownAgentKeyError):
    runtime.run("foreman", {}, AgentAssemblyContext(False))

with pytest.raises(ProtectedPromptBundleUnavailableError):
    runtime_with_unknown_bundle.run("architect", {}, AgentAssemblyContext(False))

with pytest.raises(IncompatibleSchemaContractError):
    runtime_with_builder_schema_for_architect.run(
        "architect", {}, AgentAssemblyContext(False)
    )

assert model.calls[0].tools == ()
```

Also prove every failure occurs with zero model-adapter calls.

- [ ] **Step 4: Implement the minimal deep module**

Implement immutable role, definition, identity, model-configuration, assembly-context, result, and diagnostics records. Keep the public interface to `run` and `get_agent_runtime`; keep definition, protected-bundle, schema-registry, prompt-assembler, and model adapters inside the module.

The compatibility definition source must adapt exactly seven current `Skill` records:

```python
MODEL_DRIVEN_AGENT_KEYS = (
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
)
```

The runtime order is fixed: validate role -> resolve definition -> resolve and verify protected bundle -> resolve and verify role-compatible schema -> assemble prompt -> invoke structured model -> return output and diagnostics.

- [ ] **Step 5: Run the runtime tests and verify GREEN**

Run: `python -m pytest -q tests/unit/test_agent_runtime.py`

Expected: all tests pass.

- [ ] **Step 6: Run typechecking and lint for the new module**

Run: `python -m mypy src/services/agent_runtime.py`

Run: `python -m ruff check src/services/agent_runtime.py tests/unit/test_agent_runtime.py`

Expected: both commands exit 0.

### Task 2: Cut all model-driven Graph Nodes over to AgentRuntime

**Files:**
- Modify: `src/services/graph/nodes.py`
- Modify: `tests/unit/conftest_graph.py`
- Modify: `tests/unit/test_graph_nodes.py`
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/conftest_stub_skills.py`
- Modify: `tests/integration/test_architect_reply_is_persisted.py`
- Modify: `tests/integration/test_graph_mode_turn.py`
- Modify: `tests/integration/test_graph_live_real_model.py`

**Interfaces:**
- Consumes: `get_agent_runtime`, `AgentAssemblyContext`, and `AgentInvocationResult.output` from Task 1.
- Produces: every Architect, Data Analyst, Builder, Build Reviewer, Fixer, Fix Reviewer, and Deck Reviewer model call crossing the same runtime seam; Foreman has no runtime call.

- [ ] **Step 1: Write a failing graph-seam test**

Add a behavioral test using the Graph Node fixture's recording fake runtime:

```python
def test_model_driven_nodes_use_agent_runtime_and_foreman_does_not(graph_env):
    # Exercise the seven existing node paths with their normal public node functions.
    assert set(graph_env.runtime.agent_keys_seen) == set(MODEL_DRIVEN_AGENT_KEYS)
    before = len(graph_env.runtime.calls)
    foreman_node(foreman_state)
    assert len(graph_env.runtime.calls) == before
```

Retain the existing per-node behavior assertions; the fake changes interface, not outputs.

- [ ] **Step 2: Run the focused graph test and verify RED**

Run: `python -m pytest -q tests/unit/test_graph_nodes.py -k agent_runtime`

Expected: FAIL because nodes still call `call_skill` and the fixture has no runtime recorder.

- [ ] **Step 3: Replace every model call in `nodes.py`**

At each existing invocation, call:

```python
out = get_agent_runtime().run(
    agent_key="builder",
    payload=skill_payload,
    assembly_context=AgentAssemblyContext(
        design_system_active=design_system_active,
    ),
).output
```

Apply the same shape to retries and all seven role keys. Do not change payloads, exception behavior, routing, persistence, or Foreman.

- [ ] **Step 4: Convert graph test fakes at the runtime seam**

Give existing recorders a `run(...) -> AgentInvocationResult` method, patch `nodes.get_agent_runtime` to return them, and preserve their existing call records (`name`, payload, and `design_system_active`) so behavioral assertions remain meaningful.

- [ ] **Step 5: Run unit and integration graph suites**

Run: `python -m pytest -q tests/unit/test_graph_nodes.py tests/integration/test_graph_orchestration.py tests/integration/test_graph_mode_turn.py tests/integration/test_architect_reply_is_persisted.py -m 'not live'`

Expected: all tests pass.

- [ ] **Step 6: Run typechecking and lint for graph changes**

Run: `python -m mypy src/services/graph/nodes.py src/services/agent_runtime.py`

Run: `python -m ruff check src/services/graph/nodes.py src/services/agent_runtime.py tests/unit/conftest_graph.py tests/unit/test_graph_nodes.py tests/integration/conftest.py tests/integration/conftest_stub_skills.py`

Expected: both commands exit 0.

### Task 3: Retire the old invocation implementation and preserve public parity coverage

**Files:**
- Modify: `src/core/skills/__init__.py`
- Modify: `src/services/agent_resolution.py`
- Modify: `src/services/graph/state.py`
- Modify: `src/core/skills/build_reviewer.py`
- Modify: `tests/unit/test_agent_resolution_prompt.py`
- Modify: `tests/unit/test_deck_level_spec_change.py`
- Modify: `tests/agentic/*.py`

**Interfaces:**
- Consumes: runtime public interface from Task 1.
- Produces: one owner for prompt assembly and structured invocation; compatibility skill loading remains available solely as the temporary definition source.

- [ ] **Step 1: Add ownership tests before deleting old code**

Extend `test_agent_runtime.py` to prove the runtime owns conditional instruction assembly and model construction. Update prompt parity tests to call `AgentRuntime.run` with a recording model adapter and assert independently known prompt text rather than a second assembly implementation.

- [ ] **Step 2: Run ownership tests before the move**

Run: `python -m pytest -q tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py tests/unit/test_deck_level_spec_change.py`

Expected: the new ownership assertions fail while the old implementation remains authoritative.

- [ ] **Step 3: Remove the superseded invocation path**

Delete `call_skill`, `_with_conditional_instructions`, `assemble_skill_prompt`, and `get_structured_model`. Keep `Skill`, `load_skill`, and `list_skills` as the compatibility definition source. Update comments and direct layer-3 tests to invoke `get_agent_runtime().run(...).output`.

- [ ] **Step 4: Run all focused parity and graph tests**

Run: `python -m pytest -q tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py tests/unit/test_skills.py tests/unit/test_skill_prose.py tests/unit/test_deck_level_spec_change.py tests/unit/test_graph_nodes.py tests/agentic -m 'not live'`

Expected: all non-live tests pass; live-gated model tests remain skipped by their existing gates.

- [ ] **Step 5: Sabotage-verify the parity suite**

Temporarily alter one protected prompt block, one schema identity, and one endpoint value in turn; for each mutation run the single corresponding parity test and observe a failure. Restore the production value after each probe and rerun the test green.

- [ ] **Step 6: Run changed-file typechecking and lint**

Run: `python -m mypy src/services/agent_runtime.py src/services/graph/nodes.py src/core/skills`

Run: `python -m ruff check src/services/agent_runtime.py src/services/graph/nodes.py src/core/skills tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py`

Expected: both commands exit 0.

### Task 4: Review, verify, and commit issue #259

**Files:**
- Review: all changes since `a266d91a6`
- Commit: only issue #259 files; exclude existing `CLAUDE.md`, `.claude/`, `.isaac/`, and unrelated `docs/agents/` changes.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: reviewed, verified commit implementing issue #259.

- [ ] **Step 1: Run the two-axis code review**

Use `/code-review` with fixed point `a266d91a6`, issue #259 as the spec source, documented repo conventions, and the Fowler smell baseline. Resolve every valid Standards or Spec finding and rerun focused tests for each correction.

- [ ] **Step 2: Run fresh final verification**

Run: `python -m pytest -q -m 'not live'`

Run: `python -m mypy src/services/agent_runtime.py src/services/graph/nodes.py src/core/skills`

Run: `python -m ruff check src/services/agent_runtime.py src/services/graph/nodes.py src/core/skills tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py`

Expected: no new failures; compare the full suite with the recorded baseline of exactly two unrelated `test_deploy_autoscaling.py` failures if they persist.

- [ ] **Step 3: Inspect the final diff and requirement checklist**

Run: `git diff --check`

Run: `git status --short`

Confirm every issue #259 acceptance criterion has direct code and test evidence, and confirm unrelated dirty files are unstaged.

- [ ] **Step 4: Commit the completed implementation**

```bash
git add docs/superpowers/plans/2026-09-21-agent-runtime-prefactor.md \
  src/services/agent_runtime.py src/services/graph/nodes.py \
  src/services/graph/state.py src/services/agent_resolution.py src/core/skills \
  tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py \
  tests/unit/test_deck_level_spec_change.py tests/unit/test_graph_nodes.py \
  tests/unit/conftest_graph.py tests/integration tests/agentic
git commit -m "feat: prefactor graph nodes behind AgentRuntime (#259)"
```

- [ ] **Step 5: Verify the commit and remaining worktree state**

Run: `git show --stat --oneline HEAD`

Run: `git status --short --branch`

Expected: the issue #259 files are committed and pre-existing unrelated changes remain untouched.

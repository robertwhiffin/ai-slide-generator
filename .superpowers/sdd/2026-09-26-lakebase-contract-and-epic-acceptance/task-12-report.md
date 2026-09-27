# Task 12 Report — Delete the compatibility runtime; guard the Lakebase-only contract (AC1, AC5, AC10)

**Date:** 2026-09-27
**Branch:** `plan/lakebase-contract-acceptance-271`
**TASK_BASE:** `a2793d8fe` (the controller's `d4d59b0e2` docs commit landed in between; this task's commit sits on top of it)

## Commits

| SHA | Message |
|-----|---------|
| `2698aa414` | `refactor: delete the compatibility runtime; Lakebase releases are the only definition source (#271)` |

The commit includes the AC10 gate record, `reports/task12-gate.md`, which was force-added. This report is committed separately.

## Step 1 — AC10 gate (at `a2793d8fe`, in a clean detached worktree)

- All 37 `integration-graph` files: green, one invocation each, **zero skips**.
  - `test_claim_exclusivity_postgres.py` has one pre-existing xfail.
  - `test_shared_deck_mutation_attribution.py` ran under `timeout 120`: 60 passed.
- Python joins for Tasks 3, 5, 6, 9 and 10: 28 + 145 + 17 + 30 + 5 passed. The generator tests: 3 passed.
- Full output is in `reports/task12-gate.md`.
- **Playwright journeys were not run.** The Task 11 spec did not exist at the base and is being built right now. C11 serialises Playwright on port 3000, so a run from here would collide with the Task 11 agent. This task changes no frontend file and no recorded contract. The controller must run both journeys, one after the other.

## Pre-deletion re-verification: no production caller

At the base, `rg` found every compatibility name only in:
- `src/services/agent_runtime.py` (the definitions themselves, plus the `compatibility()` body);
- `scripts/generate_graph_definition_manifest_v1.py`;
- `tests/unit/test_packaged_release_loader.py` (the parity half);
- `tests/unit/test_graph_definition_manifest.py` (the generator import and tests);
- `tests/integration/graph_lifecycle_journey.py` (`UNTIL_TASK_12`);
- `tests/unit/test_graph_lifecycle_stage_attribution.py` (tripwire targets). **The brief did not list this file.**
- two docstring-only mentions (`tests/fixtures/packaged_release_loader.py:8`, `tests/unit/test_agent_runtime.py:568`).

No `src/` module other than `agent_runtime.py` itself used any of these names, and nothing in `packages/` did either. I also ran an AST import census over `src`, `tests`, `scripts` and `packages`. It showed that the only deleted name imported from `agent_runtime` was `CodeOwnedAgentDefinitionSource`, and only by the generator. `RecordingAgentInvocationIdentitySink` is imported from `agent_runtime` by two files, so it is kept as an explicit re-export (C14).

## Deletion inventory

`src/services/agent_runtime.py` shrank by about 280 lines:

| Row | Deleted |
|-----|---------|
| R1 | `AgentRuntime.compatibility` |
| R2 | `CompatibilityResolvedDefinitionLoader`, `TEST_COMPATIBILITY_GRAPH_RELEASE_ID`, `TEST_COMPATIBILITY_GRAPH_VERSION` |
| R3 | `CodeOwnedAgentDefinitionSource` |
| R4 | `AgentDefinitionSource`, `AgentDefinition` (with `legacy_tool_grants`) |
| R5 | `_SchemaContractRegistry`, `_canonical_digest`, `_schema_contract_material`, `_schema_configuration_material`, `_schema_validator_material`, `_SCHEMA_CONTRACT_DIGESTS`, `_SCHEMA_CONTRACT_VERSION`, `_PROTECTED_PROMPT_VERSION`, `_PROTECTED_PROMPT_DIGEST`, `RuntimeContractIdentityError` |
| R7 (with C14) | imports `hashlib`, `inspect`, `json`, `textwrap`, `cast`, `DEFAULT_CONFIG`, `load_skill`, `OUTPUT_SCHEMAS`, `AssemblyRules`, `load_graph_v1_manifest` |

Other changes in `agent_runtime.py`:
- The module docstring is rewritten: the runtime resolves only persisted Graph Releases, and Foreman is absent.
- The check at old `:1018` now reads `schema_identity.version == V1_SCHEMA_IDENTITIES[definition.agent_key].version`. It goes through a local `v1_version`, and its behaviour is identical (C32).
- Kept: `ProtectedPromptIdentity`, `IncompatibleSchemaContractError`, `AgentModelConfiguration`, `AgentAssemblyContext`, `AgentInvocationResult`, `AgentInvocationDiagnostics`, and every #266/#267 name.

Other files:
- **R6:** deleted `scripts/generate_graph_definition_manifest_v1.py`, and in `test_graph_definition_manifest.py` its import and its three tests (`test_generator_*`, `test_generated_python_literal_*`). Removing them left `importlib.util` and `Path` unused, so those imports went too.
  - `:265-283` (`test_packaged_v1_manifest_hashes_and_contracts_match_stable_literals`) had no compatibility references left after Task 3, so it is **kept**.
  - Nothing else used the generator: there is no Makefile, CI or packaging reference to it. Deleting it broke nothing.
- `test_packaged_release_loader.py`: deleted the 14 parity tests, `_RecordingAdapter` and the imports they needed. 16 tests remain. The docstring is updated.
- `graph_lifecycle_journey.py`: removed `UNTIL_TASK_12` and its patch loop from the tripwire, and updated the docstring.
- `test_graph_lifecycle_stage_attribution.py`: removed the two retired entries from `test_every_code_owned_source_is_trapped`. **This was not in the brief's file list**, but the file would have failed with `AttributeError` without the change.
- Docstrings only: `tests/fixtures/packaged_release_loader.py` and `tests/unit/test_agent_runtime.py`.
- `docs/technical/`: none of the retired names appear there, so nothing needed changing.

**After** (`rg` of the brief's pattern plus `AgentDefinitionSource`, `RuntimeContractIdentityError`, `StaticDefinitionSource`, `UNTIL_TASK_12` and `legacy_tool_grants`, excluding `docs/`, `.superpowers/`, `.worktrees/` and `.claude/`):
- The guard file's `_RETIRED` set, which is expected.
- `test_agent_runtime.py:367`, `test_databricks_model_adapter_never_binds_legacy_tool_grants`. This is a behaviour test name, not a deleted symbol.

## Guards (TDD)

**`tests/unit/test_lakebase_only_runtime_contract.py`** (5 tests):

1. **Retired names.** `AgentRuntime` has no `compatibility` attribute, and `vars(agent_runtime)` contains none of the brief's 7 names plus `_SchemaContractRegistry`. I widened it to cover the R5 helpers and the R7 names: `load_skill`, `DEFAULT_CONFIG`, `OUTPUT_SCHEMAS`, `load_graph_v1_manifest`.
2. **`src.core.skills` imports.** An exact AST allowlist keyed on `(file, module, name)`: the 6 names in 2 modules from C31, with `src/core/skills/` exempt. It catches all three import forms:
   - `from src.core.skills[.x] import y`;
   - `ast.Import` (`import src.core.skills[.x]`, recorded as name `*`, which can never be allowlisted);
   - `from src.core import skills`.

   It also asserts that the allowlist is exactly the set of imports actually seen.
3. **Manifest readers.** They are exactly `{graph_definition_manifest.py, graph_configuration_bootstrap.py}` (C30).
4. **Model defaults and tool grants.** `agent_runtime.py` contains neither `DEFAULT_CONFIG` nor `tool_grants`. A regex for `DEFAULT_CONFIG["llm"` / `DEFAULT_CONFIG.get("llm"` runs over C6's widened set: `agent_runtime`, `persisted_graph_release`, `prompt_assembler`, `agent_schema_registry` and `services/graph/**`. As C31 requires, `tool_grants` is not scanned in `nodes.py`.
5. **Loader regression pin.** Both factories build a `PersistedGraphReleaseLoader`, checked with `type() is`.

**`tests/unit/test_retained_bundle_ledger.py`** (18 tests):
- The full 64-hex literals from C44: 2 protected-assembly identities and 14 schema identities.
- Each protected identity resolves through `PromptAssembler().resolve_bundle`.
- Each schema identity resolves (C32): `identity_for(role, v) == SchemaContractIdentity(...)`, and `compose(role, identity, SchemaOverlay())` succeeds.
- The ledger covers all 7 roles × versions {1, 2}.
- The resolvable sets (`PromptAssembler()._bundles` keys and `SCHEMA_CONTRACT_BUNDLES`) are a superset of the ledger.

**RED on the base code, before the deletion** (C13/C30):
- Guards 1–4 failed: guard 1 on the `compatibility` attribute; guard 2 on `agent_runtime.py` importing `load_skill`; guard 3 on `agent_runtime.py` alone; guard 4 on `DEFAULT_CONFIG`.
- Guard 5 and all 18 ledger tests passed.
- Result: 4 failed / 19 passed.

**GREEN after the deletion:** 23 passed.

## Gates (after the deletion, at `2698aa414`)

- **New guards + ledger:** 23 passed.
- **`test_packaged_release_loader.py`:** 16 passed. The 14 parity tests are gone.
- **Directly affected unit files** (`test_packaged_release_loader`, `test_graph_definition_manifest`, `test_graph_lifecycle_stage_attribution`, `test_agent_runtime`, `test_persisted_agent_runtime`, `test_prompt_assembler` and the guards): 459 passed.
- **Full unit suite:** 2 failed / 7423 passed / 110 skipped. The two failures are `test_deploy_autoscaling.py` ×2 (`test_returns_autoscaling_when_available` and `test_falls_back_when_autoscaling_creation_fails`), which is exactly the baseline cause set.
  - The run was from the worktree, with the env vars set and 8 xdist workers.
  - During the run, only the guard file's `_RETIRED` set was widened. The guards were re-run afterwards (23 passed), and the mutation baseline confirms the same.
- **Every `integration-graph` file, one invocation each, in a clean detached worktree at `2698aa414`:** all 37 green, **zero skips**. Every per-file count equals the gate count, including `test_shared_deck_mutation_attribution.py` (60 passed under `timeout 120`) and Tasks 6–8's files (2 / 2 / 22).
- **The generator's own tests:** 3 passed at the base; deleted with the script (R6).
- **`test_app_wheel_dependencies.py`:** 5 passed.
- **ruff:** clean on every changed or created Python file.
- `.venv`: absent. No `pip` was used.
- **PostgreSQL:** there were 5 `tellr_int_*` databases before and 5 after. A 6th appeared mid-run and cleaned itself up. I dropped none, and never touched `ai_slide_generator`.

## Mutation table

Every mutation ran in its own temp worktree at `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-12-mut`, detached at `2698aa414`. Before each mutation, `src` and `tests` were restored with `git checkout 2698aa414 -- src tests` plus `git clean`. At the end, `git status` was clean and the worktree was removed. The shared tree was never mutated.

| # | Mutation | Predicted RED | Actual |
|---|----------|---------------|--------|
| M01 | re-add the `AgentRuntime.compatibility` classmethod | guard 1 | RED: guard 1 only |
| M02–M09 | re-add a module global for each of `CodeOwnedAgentDefinitionSource`, `CompatibilityResolvedDefinitionLoader`, `AgentDefinitionSource`, `AgentDefinition`, `TEST_COMPATIBILITY_GRAPH_RELEASE_ID`, `TEST_COMPATIBILITY_GRAPH_VERSION`, `RuntimeContractIdentityError`, `_SchemaContractRegistry` (one mutation each) | guard 1 | RED: guard 1 only, ×8 |
| M10–M12 | re-add `_canonical_digest`, `_SCHEMA_CONTRACT_VERSION`, `_PROTECTED_PROMPT_DIGEST` in `agent_runtime` | guard 1 | RED: guard 1 only, ×3 |
| M13 | `from src.core.skills import load_skill` in `agent_runtime` | guards 1 and 2 | RED: guards 1 and 2 |
| M14 | module-level `import src.core.skills` in `persisted_graph_release.py` | guard 2 | RED: guard 2 only |
| M15 | function-level `import src.core.skills` + a `load_skill` call in `graph/nodes.py` | guard 2 | RED: guard 2 only |
| M16 | `from src.core import skills` in `chat_service.py` | guard 2 | RED: guard 2 only |
| M17 | an allowlisted name (`data_analyst.INSTRUCTIONS`) imported from a non-allowlisted file (`agent_runtime`) | guard 2 | RED: guard 2 only |
| M18 | import `load_graph_v1_manifest` in `agent_runtime` | guards 1 and 3 | RED: guards 1 and 3 |
| M19 | import `DEFAULT_CONFIG` in `agent_runtime` | guards 1 and 4 | RED: guards 1 and 4 |
| M20 | `DEFAULT_CONFIG.get("llm")` in `persisted_graph_release.py` (widened scope) | guard 4 | RED: guard 4 only |
| M21 | `DEFAULT_CONFIG["llm"]` in `graph/nodes.py` (widened scope) | guard 4 | RED: guard 4 only |
| M22 | the text `tool_grants` in `agent_runtime` | guard 4 | RED: guard 4 only |
| M23 | `get_agent_test_runtime` builds a `PersistedGraphReleaseLoader` subclass | guard 5 | RED: guard 5 only |
| M24 | **plan REVIEWER sabotage:** delete the v1 entry from `_default_bundles()` | the ledger, and Task 7's S17 on `old-root` | Ledger RED: `resolves[1-e4ff…]` and the superset test. `test_graph_lifecycle_runtime_postgres.py` RED: 2 of 2. **But it fails earlier than S17:** `[#260] S01 bootstrap via GET …/workbench: ValidationError: 14 validation errors for GraphWorkbenchResponse`. See the deviations. |
| M25 | drop schema bundle `("builder", 2)` from `SCHEMA_CONTRACT_BUNDLES` | the ledger | RED: `resolves[builder-2-65f2…]` and the superset test |

Not run: the plan's CONTROLLER sabotage (C6), a function-level `load_skill` inside `PersistedGraphReleaseLoader._load_complete_release`. That one belongs to the controller. M15 uses the same `ast.Import` form in a different module.

The mutation runner is at `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-12-mut.py`, outside the repo.

## Breakage found

- None in production.
- One brief omission: `tests/unit/test_graph_lifecycle_stage_attribution.py` pinned both retired tripwire targets by attribute access. I fixed it in the same commit.
- The generator was not needed by anything else, so deleting it broke nothing.

## Deviations

1. **Guard 1's retired set is wider than the brief's 7 names.** It adds `_SchemaContractRegistry`, the R5 helpers and constants, and the R7 names. The brief's names are all still included.
2. **Guard 2 goes beyond the C31 allowlist in two ways.** It also asserts that the allowlist is exactly the set of imports seen, so a stale entry fails. And it also catches `from src.core import skills`.
3. **Guard 4 keeps the brief's `agent_runtime.py` text check** (`DEFAULT_CONFIG` and `tool_grants`) and adds C6's widened `DEFAULT_CONFIG["llm"]` scan.
4. **`RecordingAgentInvocationIdentitySink` is kept as a redundant-alias re-export** (`X as X`, per C14), with a comment. Ruff accepts it without `noqa`.
5. **The reviewer sabotage's secondary prediction was wrong.** "S17 on old-root" never runs: without the v1 bundle, the S01 workbench bootstrap already fails. The test is still RED, but at S01, not S17. Plan :925 and C32 need an erratum. If the controller wants S17 itself to prove bundle retention, the sabotage has to leave bootstrap intact, for example by dropping the bundle after S16.
6. **Playwright journeys were not run** in either the gate or Step 4. See the Step 1 section: the controller must run them.
7. **One commit, not a RED commit followed by a GREEN one.** The RED state was proven and recorded above: 4 failed / 19 passed before the deletion.

## Concerns

1. **The controller has to run the Playwright journeys** before calling AC10 satisfied: Task 10's, and Task 11's once it lands.
2. **Guard 2 does not catch dynamic imports.** `importlib.import_module("src.core.skills")` and `__import__` are invisible to the AST walk. The C6 tripwire (`_SKILLS` trap) still covers runtime reads during the lifecycle journey.
3. **The ledger's superset check reads the private `PromptAssembler()._bundles`.** There is no public enumeration. Renaming the attribute would turn it RED with `AttributeError`, which is loud, not silent.
4. **Nothing structurally forbids a new generator script under `scripts/`,** since the guards scan only `src/`. Any such script would have no code-owned source to import, because guard 1 keeps the deleted classes gone.

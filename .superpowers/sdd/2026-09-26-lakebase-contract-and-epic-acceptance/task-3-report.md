# Task 3 Report — Packaged V1 Loader and Caller Migration

**Date:** 2026-09-27  
**Branch:** `plan/lakebase-contract-acceptance-271`  
**Task base:** `7d6fbd231` (controller ledger commit; immediately before this task's work)

---

## Commits

| SHA | Message |
|-----|---------|
| `b2fee4ba0` | `test: run runtime unit tests from the packaged manifest, not the compatibility loader (#271)` |

---

## Gates

### New file (test_packaged_release_loader.py)
`30 passed` — all seven roles, hash literals, GraphReleaseNotFoundError, override test, and 14 parity tests (7 roles × 2 design_system_active values).

### Modified files (all together)
`605 passed` — test_packaged_release_loader.py + all 9 modified files.

### Full unit suite
`2 failed (deploy_autoscaling pair, pre-epic baseline), 7204 passed, 110 skipped`  
Cause set equals the Task 1 baseline pair. No new failures.

### PostgreSQL files named in the brief
- `test_agent_definition_workbench_postgres.py`: 49 passed, 0 skips  
- `test_graph_configuration_bootstrap_postgres.py`: 3 passed, 0 skips

### Ruff
All newly created/modified files pass ruff with zero errors introduced.  
Pre-existing errors in `test_deck_level_spec_change.py` (28, all F811/I001) and `test_graph_configuration_bootstrap.py` (8, all E501 in comment table) are unchanged from HEAD.

---

## Caller Inventory

### Before (at task base)

**R1: `AgentRuntime.compatibility(`** — 13 callers in 4 files:
- `tests/unit/test_agent_runtime.py`: ×9 (lines ~166, 209, 231, 324, 339, 359, 472, 487, 586)
- `tests/unit/test_graph_configuration_bootstrap.py`: ×1 (line ~414)
- `tests/unit/test_agent_resolution_prompt.py`: ×1 (line ~76)
- `tests/unit/test_deck_level_spec_change.py`: ×2 (lines ~1026, 1085)

**R3: `CodeOwnedAgentDefinitionSource`** — importers in tests:
- `tests/unit/test_agent_runtime.py`, `tests/unit/test_graph_configuration_bootstrap.py`, `tests/unit/test_graph_definition_manifest.py`, `tests/unit/test_agent_resolution_prompt.py`

**R4: `StaticDefinitionSource`** (defined and used in test_agent_runtime.py):
- Used in 2 tests (unavailable protected bundle, incompatible schema contract)

**R2/R3: `CompatibilityResolvedDefinitionLoader` / `TEST_COMPATIBILITY_GRAPH_RELEASE_ID`**:
- `tests/unit/test_persisted_agent_runtime.py`: ×2 imports, used in test_compatibility_loader_constructs_exact_synthetic_persisted_definitions
- `tests/unit/test_prompt_assembler.py`: ×3 imports + 2 test bodies

**R5: `_SchemaContractRegistry`** (import from agent_runtime):
- `tests/unit/test_agent_schema_registry.py:1322` — one function-level import

### After (verified by rg)

**Remaining hits** (all expected per the brief):
- `src/services/agent_runtime.py` — production code stays until Task 12
- `scripts/generate_graph_definition_manifest_v1.py` — generator script (allowed)
- `tests/unit/test_packaged_release_loader.py` — parity test uses `AgentRuntime.compatibility` (explicitly allowed; will be deleted in Task 12)
- `tests/unit/test_agent_runtime.py:569` — docstring reference only, not a code import

**Zero test callers** to `AgentRuntime.compatibility`, `CompatibilityResolvedDefinitionLoader`, `CodeOwnedAgentDefinitionSource`, `TEST_COMPATIBILITY_GRAPH_RELEASE_ID`, or `StaticDefinitionSource` outside the explicitly allowed locations above.

---

## Mutation Table

| Target | Mutation | Predicted RED | Actual RED |
|--------|----------|---------------|------------|
| Controller: `PackagedGraphV1Loader.resolve` | Replace `if graph_release_id != self._graph_release_id: raise...` with `if False: raise...` (ignores release id) | `test_wrong_release_id_raises_graph_release_not_found_error` | CONFIRMED: 1 failure, exactly that test |
| Reviewer: `PackagedGraphV1Loader.resolve` | For `agent_key == "architect"`, return `content.model_copy(update={"prompt_text": content.prompt_text + "x"})` | Parity and hash tests for architect | CONFIRMED: 4 failures — hash test for architect, override test, and 2 parity tests (False/True) for architect |

Both mutations were restored from explicit file edits (not SHA). Fixture is clean after restoration; all 30 loader tests pass.

---

## Deviations

1. **`test_compatibility_loader_constructs_exact_synthetic_persisted_definitions` → renamed** to `test_packaged_v1_loader_constructs_exact_synthetic_persisted_definitions` in `test_persisted_agent_runtime.py`. The expected `ValueError` was changed to `GraphReleaseNotFoundError` as required by the brief. The test otherwise has identical assertions (byte-identical by value).

2. **`test_packaged_v1_loader_persisted_release_path_has_v1_byte_parity` renamed** (was `test_compatibility_persisted_release_path_has_v1_byte_parity` in `test_prompt_assembler.py`). Content identical.

3. **Parity test uses `model_json_schema()` equality** instead of `is` identity for schema comparison. The `AgentSchemaRegistry.compose()` creates a new class per runtime instance, so `schema is schema` can never hold between two separate `AgentRuntime` instances. The existing `test_candidate_prompt_schema_and_configuration_equal_the_production_path` uses the same pattern (`schema.model_json_schema() == produced.schema.model_json_schema()`). This is the correct comparison for byte-identical schema contracts.

4. **`import dataclasses`** removed from `test_graph_definition_manifest.py` (it was only used by `dataclasses.asdict(current.model_configuration)` in the old test, which now uses literal comparisons).

---

## Concerns

1. **Parity test partially validates schema equivalence.** `model_json_schema()` equality proves the JSON schema is identical but does not prove the composed validator instance is the same. A drift in registry construction order or extra Pydantic model config that doesn't appear in JSON schema would be missed. This matches the existing test's pattern and is the correct tradeoff for cross-runtime comparison.

2. **Content override test re-uses `load_graph_v1_manifest()` inline** (which is `lru_cache`d). No impact on test isolation.

3. **Pre-existing ruff errors** in `test_deck_level_spec_change.py` (I001, F811×12) and `test_graph_configuration_bootstrap.py` (E501×8, all in comment tables) were not introduced by this task and match their HEAD versions exactly.

---

## Fix Round 1 — 2026-09-27

**Review verdict:** APPROVE with 1 Important, 3 Minor.  
**Fix commit:** `5193ae9e2` — `test: fix round 1 — rename and strengthen manifest tests (#271)`

### Per-finding table

| Finding | Addressed? | Action |
|---------|-----------|--------|
| **Important** — `test_packaged_v1_loader_persisted_release_path_has_v1_byte_parity` compares manifest with itself (tautology) | ADDRESSED | Deleted the test. Assembly through `PackagedGraphV1Loader` is already covered by `test_v1_assembly_matches_independent_historical_replay` (all 7 roles × 2 design_system_active). The `GraphReleaseNotFoundError` check is covered by `test_wrong_release_id_raises_graph_release_not_found_error` in `test_packaged_release_loader.py`. |
| **Minor** — `content == _definition(agent_key)` at `:426` is a tautology | ADDRESSED | Replaced with `content.prompt_text == load_skill(agent_key).instructions`. Proved non-tautological: mutating architect's `prompt_text` in `agent_definition_manifest_v1.py` made the parametrised test RED for architect; restored from SHA `9f5516b2ae079f5d72ab0c79d67240d6bce604f2`. |
| **Minor** — `test_code_owned_contract_identities_are_stable_literals` name is misleading | ADDRESSED | Renamed to `test_manifest_v1_contract_identities_match_stable_literals`. |
| **Minor** — `test_packaged_v1_manifest_matches_exact_compatibility_definitions` name is misleading | ADDRESSED | Renamed to `test_packaged_v1_manifest_hashes_and_contracts_match_stable_literals`. |
| **Minor** — missing explicit `protected_assembly.version` and `schema_contract.version` checks | ADDRESSED | Added `assert item.schema_contract.version == 1` and `assert item.protected_assembly.version == 1` inside the per-definition loop. |

### Gates (fix round 1)

- **Modified files** (test_prompt_assembler.py, test_agent_runtime.py, test_graph_definition_manifest.py): 292 passed.
- **Full unit suite** (excluding Task 6's untracked file whose collection error was transient): 2 failed (pre-existing deploy_autoscaling pair) / 7217 passed / 110 skipped.
- **Ruff**: all three modified files pass with zero errors.

### Mutation (for the line 426 fix)

Appended `XMUTATION.` to the architect `prompt_text` in `src/services/agent_definition_manifest_v1.py`. `test_v1_assembly_matches_independent_historical_replay[False-architect]` went RED (new assert `content.prompt_text == load_skill(...)` failed). Restored from SHA `9f5516b2ae079f5d72ab0c79d67240d6bce604f2`.

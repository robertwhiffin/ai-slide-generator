# Task 1 report — isolated schema overlay registry

Status: `DONE`

Commit: `4744b5d77b2b805646a5ba8f9a7a486e265e0553` (`feat: add isolated schema overlay registry`)

## Exact implementation surface

Created and committed only:

- `src/services/agent_schema_types.py`
- `src/services/agent_schema_registry.py`
- `tests/unit/test_agent_schema_registry.py`

No existing tracked file was modified. Production imports only
`src.domain.skill_io.OUTPUT_SCHEMAS`, never the manifest or runtime. Registry
order is explicitly `architect`, `data_analyst`, `builder`, `build_reviewer`,
`fixer`, `fix_reviewer`, `deck_reviewer`.

## RED / GREEN evidence

Every command had `test ! -e .venv` before and after it and used the required
`/Users/robert.whiffin/.pyenv/shims/python -m pytest` invocation.

Initial focused RED:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py
```

Expected result: collection failed with `ModuleNotFoundError: No module named
'src.services.agent_schema_registry'`; 1 error, 5 established warnings, no
skips. The cause was the missing Task 1 implementation.

Focused GREEN, same command: `19 passed, 5 warnings in 0.26s`; no failures or
skips.

Recorded baseline regression:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py
```

Result: `57 passed, 5 warnings in 6.56s`; no failures or skips.

Final combined verification:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py
```

Result: `76 passed, 5 warnings in 7.57s`; no failures or skips.

Formatting/lint verification with the same `.venv` gates:

```text
/Users/robert.whiffin/.pyenv/shims/python -m ruff format --check src/services/agent_schema_types.py src/services/agent_schema_registry.py tests/unit/test_agent_schema_registry.py
/Users/robert.whiffin/.pyenv/shims/python -m ruff check src/services/agent_schema_types.py src/services/agent_schema_registry.py tests/unit/test_agent_schema_registry.py
```

Result: three files formatted; all checks passed.

### Cause-set comparison

The 57-test regression preserves the preflight cause set exactly:

- no failing node IDs or causal tracebacks;
- no skips;
- `src/api/schemas/requests.py:53`: established Pydantic v2 class-config warning;
- `src/api/schemas/responses.py:45`: established Pydantic v2 class-config warning;
- `src/api/services/chat_service.py:19`: established `langchain-community` warning;
- `unitycatalog/ai/langchain/toolkit.py:29`: third-party class-config warning;
- `databricks_ai_bridge/vector_search_retriever_tool.py:107`: third-party v1
  `@validator` warning.

There is no new failure, skip, or warning cause; this is not merely a matching
count.

## Identity evidence

Frozen v1 literals, verified against the complete existing canonical material:

| Role | v1 digest |
| --- | --- |
| architect | `a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd` |
| data_analyst | `610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281` |
| builder | `fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387` |
| build_reviewer | `50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d` |
| fixer | `7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297` |
| fix_reviewer | `31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df` |
| deck_reviewer | `56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467` |

Frozen v2 literals, calculated from complete canonical v1 material, registry
grammar/diagnostics, `extra="forbid"`, raw-key/projection policies, and exact
role descriptor metadata:

| Role | v2 digest |
| --- | --- |
| architect | `a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122` |
| data_analyst | `0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5` |
| builder | `65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad` |
| build_reviewer | `20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1` |
| fixer | `a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143` |
| fix_reviewer | `bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99` |
| deck_reviewer | `c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3` |

Tests prove every v1 catalog empty, every v2 catalog contains only the exact
role-specific `diagnostic_notes`, maps/bundles use explicit role order, changed
descriptor material fails closed, and digest/role/version mismatches yield only
`overlay_schema_contract_unavailable`.

## Falsification evidence

### Raw-key rejection

Inserted `allowed_names.update(raw_output)  # TASK1_SABOTAGE_RAW_KEY_REJECTION`.
`rg` found it on the executed production path. Targeted test:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py -k raw_keys_are_rejected_before_pydantic_projection
```

RED: `Failed: DID NOT RAISE AgentOutputValidationError`; 1 failed, 18 deselected.
Restored exactly; `rg` proved marker absence; GREEN: 1 passed, 18 deselected.

### Maximum-eight diagnostic limit

Changed the executed annotation to
`Field(max_length=80)  # TASK1_SABOTAGE_MAX_EIGHT`. `rg` found the marker.
Targeted test:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py -k canonical_and_optional_validation_fail_with_distinct_diagnostics
```

RED: `Failed: DID NOT RAISE AgentOutputValidationError`; 1 failed, 18 deselected.
Restored to `max_length=8`; `rg` proved marker absence; GREEN: 1 passed, 18
deselected.

These targets differ from the controller-reserved v2 descriptor `speaker_notes`
mutation and reviewer-reserved collision/identity-selection mutation.

## Self-review

- Staged checks proved the commit contains exactly the three authorized files;
  `git diff --cached --check` was clean.
- Recursive overlay containers, descriptor/identity/bundle tables, diagnostics,
  and optional projection are immutable/frozen.
- Validation preserves request field order, fixed `description` then `examples`
  order, and tuple-index optional order without sorting.
- Raw keys are rejected before Pydantic; canonical reconstruction uses canonical
  names and the exact canonical class; optional validation is separate.
- Absent, explicit `null`, and explicit empty-list values remain distinct; only
  selected and explicitly supplied optional keys are retained.
- Schema, descriptor, and identity material stays server-owned.
- No sabotage marker remains.

## Concerns

None within Task 1. Manifest/runtime convergence remains intentionally deferred
to the later integration task in `PLAN-CORRECTIONS.md`.

## Fix round 1/5 — frozen guidance mutation state

Review source: `task-1-review.md`. Fix commit:
`abbf212c60ef31b4482ee6ee13d4d2ea8d5ca4aa` (`fix: freeze schema overlay
mutation state`).

### Finding verification and RED

The Important finding reproduced: clearing the public live
`guidance.model_fields_set` changed an existing overlay's serialized guidance
from the supplied description/examples to `{}`. A test was added first that
attempts both `clear()` on supplied mutations and `add()` on an omitted
mutation, then checks serialization, ordered overlay validation, and composed
JSON Schema semantics.

Command, with `.venv` absence guards before and after:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py
```

RED: `1 failed, 30 passed, 5 warnings in 0.47s`. Exact failure:
`test_guidance_supplied_mutations_cannot_be_changed_through_model_fields_set`
observed `field_overrides.message == {}` after `model_fields_set.clear()`.

### Fix

`CanonicalFieldGuidance` now snapshots the explicitly supplied
`description`/`examples` names into a private `frozenset` during construction,
freezes Pydantic's exposed field set itself, and exposes only the read-only
`mutation_is_supplied()` query. Serialization, overlay validation, and dynamic
composition all use that immutable snapshot; no semantic path reads the live
public set. Omitted versus explicitly supplied guidance remains distinct.

The Minor coverage request added:

- accepted diagnostic items at 1 and 280 characters after stripping;
- rejected whitespace-only and 281-character items;
- exact composed `diagnostic_notes` description and list-shaped example
  metadata for each of all seven roles;
- retained assertions for default `None`, maximum eight, absence, explicit
  null, and explicit empty list.

### GREEN and regression evidence

Focused immutable-state test:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py::test_guidance_supplied_mutations_cannot_be_changed_through_model_fields_set
```

Result: `1 passed, 5 warnings in 0.05s`.

Full focused suite:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py
```

Result: `31 passed, 5 warnings in 0.38s`; no failures or skips.

Final combined manifest/runtime regression after formatting:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py
```

Result: `88 passed, 5 warnings in 6.86s`; no failures or skips.

Cause comparison: the warnings are still exactly the two established local
Pydantic class-config warnings, the established `langchain-community` sunset
warning, and the two established third-party Pydantic warnings. There are no
new warning causes, failures, or skips.

Formatting/lint command used the absolute interpreter with `.venv` guards:

```text
/Users/robert.whiffin/.pyenv/shims/python -m ruff format src/services/agent_schema_types.py src/services/agent_schema_registry.py tests/unit/test_agent_schema_registry.py
/Users/robert.whiffin/.pyenv/shims/python -m ruff check src/services/agent_schema_types.py src/services/agent_schema_registry.py tests/unit/test_agent_schema_registry.py
```

Result: all checks passed.

### Fix-round self-review

- `rg` confirms production reads `__pydantic_fields_set__` only once during
  construction to make the private immutable snapshot; serializer, validator,
  and composer paths use `mutation_is_supplied()`.
- The regression proves attempted public-set removal cannot remove supplied
  semantics and attempted addition cannot create omitted semantics.
- Every new boundary expectation is literal and exercises production behavior.
- The fix commit contains only the original three authorized files;
  `git diff --cached --check` was clean.
- No identity literal, descriptor text, registry ordering, or existing tracked
  integration file changed.

Fix-round concerns: none.

## Fix round 2/5 — value-owned omission semantics

Rereview source: `task-1-rereview-1.md`. Fix commit: `PENDING_FIX_ROUND_2_COMMIT`.

### Finding verification and RED

Both Important findings reproduced against fix-round-1 head
`abbf212c60ef31b4482ee6ee13d4d2ea8d5ca4aa`.

The regression was changed first to replace `_supplied_mutations` through both
normal private-attribute assignment and the publicly reachable
`__pydantic_private__` mapping, then assert unchanged serialization,
validation, and composition. A second regression calls
`CanonicalFieldGuidance.model_copy(update={"description": "Copied"})` and
checks copied serialization/validation/composition plus omitted versus explicit
null behavior.

Focused suite command, guarded by `test ! -e .venv` before and after:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py
```

Real RED: `2 failed, 30 passed, 5 warnings in 1.49s`.

- private-state replacement changed supplied serialization to `{}`;
- `model_copy(update=...)` raised `AttributeError: 'frozenset' object has no
  attribute 'update'` from Pydantic updating `__pydantic_fields_set__`.

After introducing value-owned omission state, a direct serialization assertion
was added for omitted guidance. Its targeted real RED was
`1 failed, 5 warnings in 0.15s`: `model_dump(mode="json")` could not serialize
`PydanticUndefined`. This was fixed with a plain model serializer that emits
only supplied guidance mutations.

### Fix

The replaceable `PrivateAttr` snapshot was removed entirely. `description` and
`examples` now use Pydantic's singleton `PydanticUndefined` as their omitted
default. Semantic presence is derived only from the frozen field value, not
from private state or Pydantic's mutable field-set bookkeeping.

- Normal assignment to the two semantic fields remains rejected by
  `frozen=True`.
- Assigning an arbitrary `_supplied_mutations` attribute or replacing
  `__pydantic_private__` cannot affect semantics because neither is read.
- Clearing/adding names in `model_fields_set` succeeds and cannot affect
  semantics because it is not read.
- Pydantic retains ownership of its ordinary mutable `__pydantic_fields_set__`,
  so `model_copy(update=...)` works.
- Custom guidance serialization hides the internal omitted sentinel while
  preserving explicit null distinctly from omission.

The registry code did not change: all serialization, overlay validation, and
schema composition already call `mutation_is_supplied()`, whose source is now
the protected frozen field values.

### GREEN and regression evidence

Fresh targeted command after the final implementation:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py::test_guidance_supplied_mutations_cannot_be_changed_through_model_fields_set tests/unit/test_agent_schema_registry.py::test_guidance_model_copy_update_preserves_pydantic_and_omission_semantics
```

Result: `2 passed, 5 warnings in 0.06s`.

Full focused suite:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py
```

Result: `32 passed, 5 warnings in 0.40s`; no failures or skips.

Combined manifest/runtime regression:

```text
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_agent_schema_registry.py tests/unit/test_graph_definition_manifest.py tests/unit/test_agent_runtime.py
```

Result: `89 passed, 5 warnings in 6.65s`; no failures or skips.

Cause-set comparison: the five warnings remain exactly the two repository
Pydantic class-config warnings, the repository `langchain-community` sunset
warning, and the two established third-party Pydantic warnings. No new warning
cause, failure, or skip appeared.

Ruff verification, with `.venv` absence guards:

```text
/Users/robert.whiffin/.pyenv/shims/python -m ruff format --check src/services/agent_schema_types.py src/services/agent_schema_registry.py tests/unit/test_agent_schema_registry.py
/Users/robert.whiffin/.pyenv/shims/python -m ruff check src/services/agent_schema_types.py src/services/agent_schema_registry.py tests/unit/test_agent_schema_registry.py
```

Result: `3 files already formatted`; all checks passed.

### Fix-round self-review

- Production contains no `_supplied_mutations`, `model_fields_set`,
  `__pydantic_fields_set__`, or `__pydantic_private__` semantic read.
- The regression successfully mutates/replaces the former private locations
  and successfully mutates Pydantic's field set in both directions; all three
  semantic paths remain unchanged.
- Frozen normal-field assignment is explicitly rejected in the regression.
- `model_copy(update=...)` produces independently serialized, validated, and
  composed copied guidance.
- Omitted, supplied, and explicit-null semantics are asserted separately.
- The tracked diff is limited to `agent_schema_types.py` and its Task 1 unit
  test; identity literals, catalogs, registry order, and integrations are
  unchanged.

Fix-round concerns: none.

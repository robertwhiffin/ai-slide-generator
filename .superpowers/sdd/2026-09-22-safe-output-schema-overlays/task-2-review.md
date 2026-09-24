# Task 2 independent review — Integrate typed overlay grammar and retained identities (#264)

**Reviewer:** independent; did not write this code. Every claim below is re-measured in the
worktree, not relayed from `task-2-report.md`.

- Worktree: `.worktrees/issue-264-schema-overlay`, branch `feat/schema-overlay-264`.
- HEAD at entry and exit: `cb9654810de1d14005271bd80b070256d3bfb172`. **Triple check clean at
  entry and at exit** — empty `git status --porcelain`, empty `git diff HEAD`, empty
  `git diff --cached`. Only artefact left behind is this review file.
- Range reviewed: `f94757d315a8d0314744f33426e80c6a95df404e..caa304201027e5b477fcadd110c8da0c002c8e00`
  — 5 files (3 source/test, 2 SDD artefacts), +956/-47.
- Provenance, proved once: `python 3.11.0 /Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python`,
  `databricks-sdk 0.112.0`. `test ! -e .venv` passed. No `pip`, `uv`, `uv run`, `.venv`.
  **No frontend command of any kind was issued.**
- Mutation driver kept **outside** the repo at `/tmp/t2rev/`. Every mutation asserts its anchor
  count (correction C-27) and refuses a count other than the expected one; every restore is from
  a `cp` backup with drift enumerated from `git diff --name-only HEAD`.

---

## VERDICTS

### Spec compliance: **PASS**

Every clause the brief mandates is implemented, and each is guarded by at least one test I
measured to RED. One row of the required clause-to-mutation deliverable is factually wrong
(finding F3), and the deliverable's measurement scope is undeclared (F4), but no clause is left
unguarded.

### Task quality: **NEEDS FIXES**

The implementation is sound and the scope discipline is exemplary. The fixes are to the
**report and ledger**, plus one missing test — not to shipped behaviour:

- **F1 (Important):** the report's headline finding — "the hash gate is blind to serialisation
  mode … changes no hash at all … RED 0" — is **refuted by measurement**. The swap REDs **4**
  tests in the focused suite, two of them fail-closed guards. This false finding is already
  written into `progress.md:164-165` as an *accepted ruling*, where it will mislead Tasks 3-7.
- **F2 (Important):** the compensated behaviour change only **half** moved. The removed helper
  raised on non-string object keys as well as non-JSON values; nothing replaces the key half, and
  two semantically distinct overlays now hash identically. No test guards it.
- **F3 (Important):** mutation-table row **M7 is wrong** — it claims RED 1 at a node that does
  not RED at all; the real radius is 13. The error propagated into the report's concern #5 and
  into the controller's forward item (d).

---

## Spec compliance, clause by clause

| Brief clause | Verdict | Evidence I measured |
| --- | --- | --- |
| Byte-identical v1 payloads | **PASS** | All three mode assertions have teeth (see below). |
| Byte-identical v1 hashes | **PASS** | Oracle recomputed independently: `definition_content_hash()` over `load_graph_v1_manifest().definitions` reproduces all seven literals. Serializer-probe mutation REDs the oracle test. |
| Explicit `mode='python'` vs `mode='json'` decision | **PASS** (reasoning partly wrong — F1) | `mode='json'` is correctly identified as the persisting form: `graph_configuration_content.py:79` does `value.model_dump(mode="json")` for `json_document=True` fields, and `schema_overlay` is one (`:44`). Both modes pinned separately. |
| Typed guidance round-trip | **PASS** | Absent-vs-explicit-null retention asserted in both directions; `mutation_is_supplied` distinguishes them. |
| v2 hash change | **PASS** | 7 roles × v1/v2; M5-style mutation REDs 10. |
| All v1/v2 identities resolve from the retained carrier | **PASS** | 14 parametrized rows; my MUT-1 REDs 16. |
| Fail-closed missing/mismatched role/version/digest | **PASS** | 6 cases + registry bridge test; MUT-1 makes 2 of the 6 wrongly resolve → RED. |
| Independent #265 assembly identity validation | **PASS** | Proved in both directions (schema upgrade leaves assembly; assembly upgrade leaves schema contract). |
| Import/re-export typed grammar; retain `ContentIdentity` | **PASS** | `manifest_module.SchemaOverlay is agent_schema_types.SchemaOverlay`; `__module__` asserted as a literal string; `ContentIdentity` byte-unchanged apart from a docstring. |
| Do not regenerate Graph V1 | **PASS** | Packaged snapshot identity and `lru_cache` identity both asserted. |
| Do not couple schema and assembly versions | **PASS** | Both directions. |
| Do not accept client-selected identities | **PASS**, radius wider than reported | Role is taken from the owning record. The bridge **structurally cannot** take a role from `stored`, because `ContentIdentity` carries none. |
| c12 Task-2 half: converge the carrier and the freeze helper | **PASS** | `_freeze_json_containers` / `_thaw_json_containers` gone; `grep -rn "def freeze_json_containers\|def _freeze_json_containers" src/` now returns **exactly one** definition repo-wide (`agent_schema_types.py:33`). |
| Correction C-24: exact values as literals, not imports | **PASS** | The 7 content hashes, 7 v1 digests, 7 v2 digests and both assembly digests are hand-written literals at `test_graph_definition_manifest.py:744-773` and inline; nothing imported from source. |
| Correction C-27: mutation harness asserts its anchor count | **PASS** (mine does; author's driver claims to) | My driver refuses any count but the expected one. |
| Required deliverable: clause-to-mutation table | **PRESENT, one row wrong** | See F3/F4. |

### Scope discipline — confirmed, and it was the harder choice

`git diff --quiet` over the review range: `src/services/agent_runtime.py`,
`src/services/agent_schema_registry.py`, `src/services/agent_schema_types.py` are all
**UNCHANGED**. Also unchanged: `src/api/schemas/agent_definitions.py`,
`src/services/graph_configuration_draft.py`, `frontend/src/api/agentDefinitions.ts`.

- `SchemaContractIdentity` is still defined twice (`agent_runtime.py:126`,
  `agent_schema_types.py:367`). The divergence is **neither deepened nor resolved** — the new
  bridge imports the `agent_schema_types` one, the declared public home, so it consumes the
  public type rather than adding a third.
- The silently-failing gate at `agent_schema_registry.py:556`
  (`if isinstance(existing_identity, SchemaContractIdentity):`) is **byte-unchanged**. Correctly
  left for Task 3. This deserves the credit the brief suggests: the task exercised the adjacent
  `BaseModel` branch — the one `ContentIdentity` actually takes — without touching the gate line.
- `graph_configuration_draft.py` untouched, so neither the loud-refactor nor the silent-reformat
  hazard in `test_prompt_assembler.py`'s eight-file text join applies. `CUSTOM_ANCHORS` not
  reordered.

---

## 1. The mode-blindness finding — **REFUTED by measurement** (finding F1)

### What is true

`_normalize_canonical_value` (`graph_definition_manifest.py:317-321`) does route `list` and
`tuple` through one branch, so `()` vs `[]` in the overlay is invisible to the hash. I confirmed
by direct computation that for **all seven packaged v1 definitions** the two dump modes yield
byte-identical hashes:

```
architect       python=e77e69b18cb9d843 json=e77e69b18cb9d843 equal=True
data_analyst    python=1ffb1fb3f31a20b9 json=1ffb1fb3f31a20b9 equal=True
builder         python=1549a4231b3a4a62 json=1549a4231b3a4a62 equal=True
build_reviewer  python=1a895f4bee426041 json=1a895f4bee426041 equal=True
fixer           python=fb9dc5a2bddb783f json=fb9dc5a2bddb783f equal=True
fix_reviewer    python=e6d4a4801abc7b65 json=e6d4a4801abc7b65 equal=True
deck_reviewer   python=8c876db55cddbaa2 json=8c876db55cddbaa2 equal=True
v1 differing roles: 0
```

So the narrow claim "hash-equivalent **for v1**" is correct.

### What is false

The report generalises that to "swapping `canonical_payload`'s `mode="python"` for
`mode="json"` **changes no hash at all** — measured, RED=0. **The hash gate therefore cannot
detect the swap.**" Both sentences are wrong.

`model_dump(mode="json")` serializes a `Decimal` to a **string**, which
`_normalize_canonical_value` passes straight through as a `str` instead of normalising it as a
number. `Decimal` is exactly the shape these values take when they cross the SQLAlchemy boundary
— which is what `canonical_payload`'s own docstring exists to handle:

```
=== non-empty typed overlay + Decimal temperature: python vs json ===
python: 6bb91bc558496bda55145fc7314eeec9c0871844f1dbdd2354d9dbe40d6266f5
json  : 247ff01a9d717a7e06ed70b8f9e659c33d265a1d58ae6ad8a5c112c4488c8a6f
equal : False
python model dump: {'temperature': Decimal('0.700000'), ...}
json   model dump: {'temperature': '0.700000', ...}
```

**Measured radius of the mode swap, focused suite: 4 failed, 137 passed** (anchor count asserted
== 1 on `dumped = self.model_dump(mode="python")`):

```
FAILED tests/unit/test_graph_definition_manifest.py::test_hash_normalizes_manifest_floats_and_database_decimals
FAILED tests/unit/test_graph_definition_manifest.py::test_hash_rejects_non_finite_numeric_values[temperature-value2]
FAILED tests/unit/test_graph_definition_manifest.py::test_hash_rejects_non_finite_numeric_values[top_p-value3]
FAILED tests/unit/test_graph_definition_manifest.py::test_hashing_still_fails_closed_on_a_non_json_guidance_value
4 failed, 137 passed, 5 warnings in 8.09s
```

Causes, by traceback:

```
>       assert definition_content_hash(database_shape) == definition_content_hash(original)
E       AssertionError: assert 'e2b89a97af13...85d303ba5c172' == 'e77e69b18cb9...ff7566d1dcb33'
E         - e77e69b18cb9d843a1754dab65a79941ede8cfa7c8266292580ff7566d1dcb33
E         + e2b89a97af139a4a2053d5dcda97721ccc9e061f0c2048e796c85d303ba5c172

field = 'temperature', value = Decimal('NaN')
>       with pytest.raises(ValueError, match="finite"):
E       Failed: DID NOT RAISE <class 'ValueError'>

field = 'top_p', value = Decimal('Infinity')
>       with pytest.raises(ValueError, match="finite"):
E       Failed: DID NOT RAISE <class 'ValueError'>

src/services/graph_definition_manifest.py:288: in canonical_payload
    dumped = self.model_dump(mode="json")
E       pydantic_core._pydantic_core.PydanticSerializationError: Unable to serialize unknown type: <class 'object'>
```

Three consequences the report and the ledger both miss:

1. **Three pre-existing tests in the very file the task edited** detect the swap. The hash gate
   is *not* blind to the mode.
2. **Two of those are fail-closed guards.** Under `mode="json"`, `Decimal("NaN")` and
   `Decimal("Infinity")` become strings, so `_normalize_canonical_value`'s finiteness check never
   fires and a non-finite numeric would be **silently hashed**. The mode is load-bearing for a
   fail-closed guarantee — the opposite of "the hash gate cannot see the mode".
3. **The task's own new test REDs too**, and for a different reason than it asserts
   (`PydanticSerializationError`, not `TypeError`).

**Why the author measured 0.** Scoped to the row's own named test
(`test_packaged_v1_content_hashes_are_the_seven_frozen_literals` plus the byte-identity test),
the swap really is RED 0 — I measured `2 passed`. So the *number* is defensible under an
undeclared per-named-test scope (F4). The defect is the **conclusion drawn from it**, which was
generalised from "the seven empty-overlay v1 rows" to "no hash at all" and "the hash gate cannot
detect the swap", and then recorded as an accepted ruling at `progress.md:164-165`. The
controller's verification confirmed only the *code reading* (list and tuple share a branch) —
true, but it does not establish the conclusion, and nobody measured.

**Concrete downstream hazard:** a Task 3-7 agent reading the ledger ruling "the hash gate is
blind to the mode" could swap `canonical_payload`'s mode believing it free, and would silently
break Decimal normalisation and the non-finite fail-closed guard while all seven v1 hashes stayed
green.

### Both mode assertions have teeth — verified

`test_packaged_v1_overlay_payload_is_byte_identical_under_the_chosen_mode` carries three
assertions. I aimed a distinct mutation at each:

| Assertion | Mutation (anchor count asserted == 1) | Result |
| --- | --- | ---: |
| 1. `mode='json'` → `additional_optional_fields: []`, `field_overrides: {}` | `SchemaOverlay.serialize_field_overrides` emits an extra `_probe` key | **RED** |
| 2. `mode='python'` → `additional_optional_fields: ()` | `additional_optional_fields: tuple[str, ...] = ()` → `list[str] = []` | **RED** |
| 3. exact persisted JSON bytes | the same `_probe` serializer mutation | **RED** |

```
E           AssertionError: assert {'additional_...'_probe': {}}} == {'additional_...verrides': {}}
E             Differing items:
E             {'field_overrides': {'_probe': {}}} != {'field_overrides': {}}
1 failed, 5 warnings in 0.27s
```

The `mode='json'` choice is verified correct as *the persisting one*:
`_PERSISTED_CONTENT_FIELDS` marks `schema_overlay` `json_document=True`
(`graph_configuration_content.py:44`), and `definition_content_values` does
`value.model_dump(mode="json")` at `:79`.

**Minor caveat (F5):** assertion 3's comment calls it "the exact persisted bytes for the JSON
column", but the test re-serialises the mapper's dict with its own
`json.dumps(sort_keys=True, separators=…)`. It pins the mapper's **value**, not the bytes
SQLAlchemy emits. The assertion is sound; the comment overstates it.

---

## 2. Reproduction of the discriminating 30-test sabotage — **EXACT**

Anchor `"field_overrides": {},` in `src/services/agent_runtime.py`, **count asserted == 1**
(grep confirms exactly one occurrence, at `:455`). Replaced with a value the old untyped
`Mapping[str, object]` accepted and the typed grammar rejects:

```
"field_overrides": {"message": "REVIEWER_DISCRIMINATING_NOT_A_MAPPING"},
```

| File | Reviewer RED | Author RED | Amended c11 |
| --- | ---: | ---: | ---: |
| `tests/unit/test_agent_runtime.py` | **20** | 20 | 20 |
| `tests/unit/test_agent_resolution_prompt.py` | **7** | 7 | 7 |
| `tests/unit/test_deck_level_spec_change.py` | **2** | 2 | 2 |
| `tests/unit/test_graph_configuration_bootstrap.py` | **1** | 1 | 1 |
| **Total** | **30 across 4 files** | 30 | 30 |

```
--- test_agent_runtime ---            20 failed, 10 passed
--- test_agent_resolution_prompt ---   7 failed,  1 passed
--- test_deck_level_spec_change ---    2 failed, 47 passed
--- test_graph_configuration_bootstrap 1 failed, 18 passed
```

Cause, confirming the literal is genuinely on the typed path and that the sabotage discriminates
between the two grammars rather than breaking something incidental:

```
E       pydantic_core._pydantic_core.ValidationError: 1 validation error for DefinitionContent
E       schema_overlay.field_overrides.message
E         Input should be a valid dictionary or instance of CanonicalFieldGuidance
E         [type=model_type, input_value='REVIEWER_DISCRIMINATING_NOT_A_MAPPING', input_type=str]
src/services/agent_runtime.py:448: ValidationError
```

**GREEN after restore** (`cp` backup; `git diff --name-only HEAD` empty):

```
tests/unit/test_agent_runtime.py test_agent_resolution_prompt.py
test_deck_level_spec_change.py test_graph_configuration_bootstrap.py    106 passed
test_graph_configuration_draft.py test_prompt_assembler.py
test_graph_definition_content_mapping.py test_agent_definition_workbench_routes.py
test_graph_configuration_models.py test_persisted_agent_runtime.py      380 passed
```

**The zero-RED radius is established.** 30 reproduces byte-identically, including
`test_agent_resolution_prompt.py` which c11 omitted entirely — so the phase-B reviewer's
amendment from 8 to 30 is independently re-confirmed, and the task's own 0 RED is *correct rather
than lucky*: `{"field_overrides": {}, "additional_optional_fields": []}` is valid under both
grammars, which was the point of converging by re-export.

---

## 3. The vacuous-test repair — **verified, and it fails for the right reason**

### The vacuity was real

Replaying the pre-change assertions (the diff's `-` side) against pristine post-change code:

```
type of o['outer'] : CanonicalFieldGuidance
frozen container?  : False

  o["outer"]["added"] = False                   -> TypeError: 'CanonicalFieldGuidance' object does not support item assignment
  o["outer"]["values"][0]["enabled"] = False    -> TypeError: 'CanonicalFieldGuidance' object is not subscriptable
  o["outer"]["values"][0] = {"enabled": False}  -> TypeError: 'CanonicalFieldGuidance' object is not subscriptable
```

Three for three, byte-identical to the messages in the report. The old body would have stayed
**green while measuring nothing** about container immutability. The repair — reaching the frozen
containers via `forbidden_properties()` with `MappingProxyType` and `tuple` isinstance checks —
is the right fix, and the class of defect ("a test that keeps passing for a reason your own change
introduced") is correctly identified as new to this epic.

### The repaired test has teeth, at the immutability assertion

This is my **MUT-2** (below): a non-recursive freeze through sequences REDs it at
`pytest.raises(TypeError)` → `DID NOT RAISE`, i.e. at the immutability claim itself, not
collaterally.

### Sweep for other assertions whose pass condition the change altered

I enumerated every `schema_overlay` / `field_overrides` reference in `tests/` and traced each
against what the change altered (values became models; both carrier fields gained defaults; the
local `ValueError` raises were removed).

| Site | Pass condition altered? | Verdict |
| --- | --- | --- |
| `test_graph_definition_manifest.py:301` `test_cached_manifest_overlay_cannot_mutate_shared_or_canonical_state` | No — top-level `field_overrides` is still a `MappingProxyType`, now via `SchemaOverlay.freeze_field_overrides` | Still measures what it claims |
| `test_graph_definition_manifest.py:194` `_semantic_mutations` / `test_hash_covers_every_semantic_field` (`len == 12`) | No — mutates `additional_optional_fields`, untouched by the grammar change | Sound |
| `test_graph_definition_content_mapping.py:52-59` | No — same `additional_optional_fields` route | Sound |
| `test_graph_configuration_draft.py:401`, `:1816` | No — same route | Sound |
| `test_agent_definition_workbench_routes.py:807` `("candidate.schema_overlay", {}, …, "extra_forbidden")` | No — asserts the PUT DTO refuses `schema_overlay` as an extra field; independent of the overlay grammar | Sound |
| `test_agent_definition_workbench_routes.py:296` `set(published["schema_overlay"]) == {…}` | No — key-set only | Sound, but see forward item (a) |
| Any test depending on the removed `ValueError` | None exists (I re-grepped both message strings across `src/` and `tests/`: zero hits) | Author's claim confirmed |
| **Any test exercising a non-string overlay object key** | **None exists** | **This is finding F2** |
| **Any test asserting the carrier requires both overlay fields** | **None exists**, and the requirement was silently dropped | **Finding F6** |

Two items the sweep surfaced beyond the author's own catch — F2 and F6 below. The brief's
expectation that "one instance usually means more" was correct.

---

## 4. The compensated behaviour change — **half the guarantee survived** (finding F2)

The removed `_freeze_json_containers` carried **two** raises:

```python
raise ValueError("schema overlay object keys must be strings")
raise ValueError(f"schema overlay values must be JSON-compatible, received {value!r}")
```

### The value half genuinely survives, at two homes

```
=== (a) non-JSON VALUE: object() in examples ===
  definition_content_hash:                              TypeError: unsupported canonical value <object object at …>
  definition_content_values (persist path, mode=json):  PydanticSerializationError: Unable to serialize unknown type: <class 'object'>
  PydanticSerializationError MRO: ['PydanticSerializationError', 'ValueError', 'Exception', …]
```

And **nothing reachable can persist a non-JSON overlay value.** I traced every write path; all
four compute the hash, and three of them before or alongside the mapper:

- `revision_from_definition` (`graph_configuration_content.py:108-109`) — mapper then hash, both
  as keyword arguments, so the exception propagates before the ORM row is constructed.
- `draft_from_definition` (`:122-124`) — same shape.
- `_write_locked_content` (`graph_configuration_draft.py:637-638`) — `definition_content_hash`
  runs **first**, before any `setattr`.
- `agent_runtime.py:471` — hash computed on the resolved content.

`validate_definition_hash` (`:131-143`) additionally catches `TypeError`/`ValueError` on read.
The author's new `test_hashing_still_fails_closed_on_a_non_json_guidance_value` is genuine — a
`repr(value)` mutation in place of the `raise TypeError` REDs it (**RED 1**, matching the
report's M13, the one table row that matched exactly).

### The key half did **not** survive, and nothing guards it

```
=== (b) non-string nested OBJECT KEY: {1: 'a'} in examples ===
  int key {1:'a'}: hash=3b0f99866da532e835babeb7e646943ead92cb42d103d4bedd773baeb7b82ef0
  str key {'1':'a'}: hash=3b0f99866da532e835babeb7e646943ead92cb42d103d4bedd773baeb7b82ef0
  COLLISION (distinct values, same hash): True
  persist path int key -> {'field_overrides': {'message': {'examples': [{'1': 'a'}]}}, …}

=== (b2) MIXED keys {1:'a','b':2} ===
  TypeError: '<' not supported between instances of 'str' and 'int'

=== old helper behaviour, reconstructed from the diff ===
  old helper on object():       ValueError: schema overlay values must be JSON-compatible…
  old helper on int key:        ValueError: schema overlay object keys must be strings
  old helper on nested int key: ValueError: schema overlay object keys must be strings
```

Three distinct consequences:

1. Two semantically distinct overlay payloads — `{1: "a"}` and `{"1": "a"}` — now produce the
   **same content hash**. The removed helper prevented this by raising.
2. The persist path **silently coerces** `1` → `"1"`, so the value written differs from the value
   validated, with no diagnostic.
3. Mixed key types fail only *accidentally*, via `json.dumps(sort_keys=True)` raising
   `TypeError: '<' not supported between instances of 'str' and 'int'` — an opaque message from
   the wrong layer.

**Reachability is low**, which is why I grade this Important rather than Critical: overlay values
arrive either from the HTTP wire or from a JSONB column, and both force string keys. A non-string
key requires in-process Python construction. But the report states flatly that "the fail-closed
guarantee is **not** dropped with it — it moves to the hashing boundary". That is true for values
and **false for keys**, and the report's own sentence acknowledges both raises existed before
claiming the guarantee moved intact. Disclosure of the premise does not cover the wrong
conclusion.

**Fix:** either restore a key check (in `freeze_json_containers`, or as a key-type branch in
`_normalize_canonical_value`) with a test, or record an explicit ruling that the key half is
deliberately dropped and why the collision is acceptable.

---

## Rulings on the four forward items

### (a) `SchemaOverlayResponse.field_overrides: dict[str, object]` — **correctly deferred**

Probed with a real non-empty overlay including a forbidden extra property:

```
field_overrides['message'] type: CanonicalFieldGuidance
model_dump(mode=json): {'field_overrides': {'message': {'description': 'Say why.',
  'examples': [{'a': [1, 2]}], 'bogus_extra': {'k': [1]}}}, 'additional_optional_fields': ['diagnostic_notes']}
model_dump_json: {"field_overrides":{"message":{"description":"Say why.", …}}}
```

No exception, no warning, no leaked model repr: pydantic's `object` serializer falls through to
`CanonicalFieldGuidance`'s own `@model_serializer(mode="plain")` → `serialized_mutations()`,
which yields clean JSON. So this is **not** a Task 2 gap — the DTO works today. What remains is
genuinely a Task 5 decision: the **declared** OpenAPI shape is `object` rather than the guidance
schema, and the correct behaviour depends on a serializer in a file Task 5 owns, which is a
latent coupling worth Task 5 pinning with a test. Correctly flagged rather than changed.

### (b) `CanonicalFieldGuidance` `extra="allow"` until c16 registers overlay validation — **correctly deferred, and narrower than stated**

Confirmed: `local_candidate_validators` at `graph_configuration_draft.py:193` contains only
`_assembly_candidate_validator`; no overlay validator is registered. So the carrier does validate
overlays the registry would reject.

But the window is **not reachable from any client path today**, which the report does not claim
and could have: the workbench PUT DTO refuses `schema_overlay` outright (asserted by the
pre-existing `extra_forbidden` case at `test_agent_definition_workbench_routes.py:807`), and
`agent_runtime.py:547` hard-rejects any non-empty overlay for Graph V1. Latent, not live.
Correctly deferred; the task was appropriately conservative about its own exposure.

### (c) `agent_runtime.py:547` still hard-rejects any non-empty overlay for Graph V1 — **correctly deferred**

Read at `:541-547`. It tests `content.schema_overlay.field_overrides or
content.schema_overlay.additional_optional_fields` before resolving the contract. The field is
now a mapping of typed guidance, and the truthiness check behaves identically on a
`MappingProxyType`. Correct for v1, Task 3's to relax. Not a Task 2 gap.

### (d) "M7's radius is one node" — **the premise is FALSE; not a Task 2 gap** (finding F3)

I re-ran the author's M7 exactly as its table describes it (`agent_key=agent_key` →
`agent_key="architect"`, anchor count asserted == 1).

**Scoped to the tests M7's own row names:**

```
-- test_stored_identity_resolution_fails_closed (row's named test):  6 passed
-- registry bridge test (row's second named test):                   1 failed
```

The row says "**RED 1** (the `not_a_role` case now resolves)". That test does **not** RED — it
stays 6/6 green. Reasoning: with the role hardcoded, `not_a_role` still misses
`SCHEMA_CONTRACT_BUNDLES[("not_a_role", 1)]`, so `_resolve` still returns `None` and the case
still fails closed. So the row is wrong about **which** node REDs, not merely about how many.

**Focused suite: RED 13**, not 1:

```
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-data_analyst]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-builder]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-build_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-fixer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-fix_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-deck_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-data_analyst]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-builder]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-build_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-fixer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-fix_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-deck_reviewer]
FAILED tests/unit/test_agent_schema_registry.py::test_registry_resolves_identities_bridged_from_the_stored_content_identity
13 failed, 128 passed
```

**Ruling: not a Task 2 gap.** The role-passthrough clause is guarded by **13** nodes, not one, so
the report's concern #5 and the controller's forward item (d) are both based on a bad measurement
and should be struck from the ledger. The code is better than its own report says.

One genuine residual, which I record rather than grade as a defect: the *direction* of the role
is not distinguished anywhere. `_resolve` (`agent_schema_registry.py:361-367`) keys on the
`agent_key` **argument**, and no test passes an identity whose `agent_key` differs from that
argument — the bridge always makes them agree. A bridge that derived the role from the digest
instead of from the owning record would therefore pass the whole suite, though the registry's
`bundle.identity != identity` check backstops it so the consequence is benign today. The
structural protection is stronger than any test: `ContentIdentity` carries **no role**, so the
bridge literally cannot take one from a stored or submitted pair.

---

## My two mutations

Both anchors count-asserted per correction C-27; both restored from `cp` backups with
`git diff --name-only HEAD` verified empty. Both distinct from the author's 17.

### MUT-1 — role safety / cross-role contract selection: the bridge stops passing the presented digest through

Aimed at `schema_contract_identity`'s third field, the one the author's M5 (`version`) and M7
(`agent_key`) left uncovered. Substituting architect's v1 digest means every other role's stored
pair selects **architect's** contract material instead of its own.

```
[mutate] src/services/graph_definition_manifest.py: 1 unique anchor patched (count asserted == 1)
-        digest=stored.digest,
+        digest="a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd",
```

**RED 16 / 125 passed** (focused suite):

```
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-data_analyst]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-builder]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-build_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-fixer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-fix_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[1-deck_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-architect]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-data_analyst]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-builder]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-build_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-fixer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-fix_reviewer]
FAILED …::test_stored_identity_resolves_the_exact_role_and_version_bundle[2-deck_reviewer]
FAILED …::test_stored_identity_resolution_fails_closed[architect-1-000…000-mismatched digest]
FAILED …::test_stored_identity_resolution_fails_closed[architect-1-a03aefb1…-v2 digest under v1]
FAILED tests/unit/test_agent_schema_registry.py::test_registry_resolves_identities_bridged_from_the_stored_content_identity
16 failed, 125 passed, 5 warnings in 12.76s
```

The two most security-relevant REDs — a bogus all-zeros digest and a v2 digest presented under
v1 both now **resolve** instead of failing closed:

```
reason = 'mismatched digest'
>       assert [issue.code for issue in issues] == ["overlay_schema_contract_unavailable"], reason
E       AssertionError: mismatched digest
E       assert [] == ['overlay_sch..._unavailable']
E         Right contains one more item: 'overlay_schema_contract_unavailable'

reason = 'v2 digest under v1'
E       AssertionError: v2 digest under v1
E       assert [] == ['overlay_sch..._unavailable']

>       assert (identity.agent_key, identity.version, identity.digest) == (
E       AssertionError: assert ('data_analys...fefd4423fafd') == ('data_analys...7e22a6bfc281')
E         At index 2 diff: 'a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd'
E                       != '610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281'
```

`architect`/v1 correctly still passes — it is the identity case. **GREEN after restore:**
`141 passed, 5 warnings in 8.36s`; `git diff --name-only HEAD` empty.

**Verdict:** the "no client-selected identities" clause is guarded far more widely than the report
claims. 16 nodes, spanning both the happy path and two fail-closed cases.

### MUT-2 — the item-3 sweep target: the recursive freeze stops reaching through JSON arrays

#### MUT-2a, mis-aimed — reported as required

First aim: `freeze_json_containers`'s sequence branch returns a `list` instead of a `tuple`.

```
[mutate] src/services/agent_schema_types.py: 1 unique anchor patched (count asserted == 1)
-        return tuple(freeze_json_containers(item) for item in value)
+        return [freeze_json_containers(item) for item in value]
7 failed, 134 passed
```

It REDs the repaired test, but at the **wrong place** — `thaw_json_containers` only thaws
`tuple`, so an unthawed `mappingproxy` reaches the hash and blows up before the immutability
assertions are ever evaluated:

```
>       before_hash = definition_content_hash(candidate)
>       raise TypeError(f"unsupported canonical value {value!r}")
E       TypeError: unsupported canonical value mappingproxy({'enabled': True})
```

A collateral RED proves the wrong thing, so I re-aimed rather than bank it.

#### MUT-2b, re-aimed — isolates the claim

Keep the sequence a `tuple` (leaving the thaw/hash path untouched, so it cannot supply a
collateral RED) but make the freeze **non-recursive through sequences**, so nested objects inside
a JSON array stay mutable dicts. This is exactly what the repaired test now claims, and exactly
what the old vacuous body could not have measured. Distinct from the author's M12, which targeted
the `Mapping` branch.

```
[mutate] src/services/agent_schema_types.py: 1 unique anchor patched (count asserted == 1)
-        return tuple(freeze_json_containers(item) for item in value)
+        return tuple(value)

FAILED tests/unit/test_graph_definition_manifest.py::test_nested_overlay_containers_are_immutable_but_dump_as_json_containers
FAILED tests/unit/test_graph_definition_manifest.py::test_typed_guidance_nested_containers_are_frozen_inside_the_carrier
FAILED tests/unit/test_agent_schema_registry.py::test_guidance_model_copy_update_is_trusted_and_semantically_protected
3 failed, 138 passed, 5 warnings in 7.11s
```

RED at the immutability assertion itself — **the right reason**:

```
>       with pytest.raises(TypeError):
E       Failed: DID NOT RAISE <class 'TypeError'>
FAILED tests/unit/test_graph_definition_manifest.py::test_nested_overlay_containers_are_immutable_but_dump_as_json_containers
```

**GREEN after restore:** `141 passed, 5 warnings in 8.36s`; `git diff --name-only HEAD` empty.

**Verdict:** the repair is real and load-bearing. The rewritten test fails when and only when the
containers are genuinely not frozen, which is precisely what the pre-change version could not
detect.

### Re-measurement of the author's own table (to gauge the deliverable's reliability)

| Row | Author | Reviewer (focused suite) | Reviewer (row's named test) | |
| --- | ---: | ---: | ---: | --- |
| c11 sabotage | 20/7/2/1 = 30 | **20/7/2/1 = 30** | — | exact |
| M13 | RED 1 | **RED 1** | — | exact |
| M1 | RED 1 | RED 3 | RED 1 | scope-consistent |
| M12 | RED 2 | RED 3 | RED 2 | scope-consistent |
| M5 | RED 7 | RED 10 | RED 7 | scope-consistent |
| M2 | RED 0 | **RED 4** | RED 0 | number defensible, **conclusion wrong (F1)** |
| M7 | RED 1 | **RED 13** | **RED 1, but at a node the row does not name** | **wrong (F3)** |

---

## Findings

### Critical
None. No shipped behaviour is wrong, no clause is unguarded, and scope discipline is intact.

### Important

**F1 — The mode-blindness finding is false, and is recorded as an accepted ruling.**
`.superpowers/.../task-2-report.md` ("The mode decision" section) and `progress.md:164-165`.
The mode swap REDs **4** focused tests, two of which are fail-closed guards for non-finite
`Decimal` values; `mode="json"` turns a `Decimal` into a `str`, which
`_normalize_canonical_value` (`src/services/graph_definition_manifest.py:317-321`) passes through
un-normalised. "Changes no hash at all" and "the hash gate cannot detect the swap" are both
wrong; only "hash-equivalent for the seven v1 rows" is true. Concrete hazard: a later task
trusting the ledger ruling could swap the mode believing it free.
**Fix:** correct the report and the ledger ruling; state the true radius and that the mode is
load-bearing for Decimal normalisation and the non-finite check.

**F2 — The fail-closed guarantee only half moved; the key half is gone and unguarded.**
`src/services/graph_definition_manifest.py` (removed `_freeze_json_containers`, diff `-102..-112`)
vs `src/services/agent_schema_types.py:33-40`. The removed helper raised
`ValueError("schema overlay object keys must be strings")`; nothing replaces it.
`{1: "a"}` and `{"1": "a"}` inside `examples` now produce the **same** content hash
(`3b0f9986…`), the persist path silently coerces `1` → `"1"`, and mixed key types fail only
accidentally via `json.dumps(sort_keys=True)`. No test in the repo exercises a non-string overlay
key. Low reachability (wire and JSONB both force string keys), hence Important not Critical.
**Fix:** restore a key-type check with a test, or record an explicit ruling that the key half is
deliberately dropped and why the collision is acceptable.

**F3 — Mutation-table row M7 is factually wrong, and the error propagated.**
`task-2-report.md` (table row M7 and concern #5); `progress.md:171`; brief forward item (d).
Claims "RED 1 (the `not_a_role` case now resolves)". Measured: that test stays **6/6 green**, and
the real radius is **13** across the focused suite. Since the clause-to-mutation table is the
epic's required deliverable and the mechanism by which under-guarded clauses are found, a row that
misidentifies its own RED node undermines the deliverable. It also caused the task to report a
weakness that does not exist.
**Fix:** correct the row and strike concern #5 / forward item (d) from the ledger.

### Minor

**F4 — The clause-to-mutation table's measurement scope is never declared.**
`task-2-report.md`. Four rows (M1, M5, M12, and M2's zero) are consistent with a per-named-test
scope and understated against a focused-suite measurement. The direction is conservative — the
guards are stronger than claimed, so no clause is left unguarded — but the table is not
self-describing, and F1 shows what happens when a scoped number is generalised in prose.
**Fix:** state the scope in the table header.

**F5 — "The exact persisted bytes" overstates what the assertion pins.**
`tests/unit/test_graph_definition_manifest.py:817-819`. The test re-serialises the mapper's dict
with its own `json.dumps(sort_keys=True, separators=…)`, so it pins the mapper's **value**, not
the bytes SQLAlchemy writes. The assertion is sound and has teeth; only the comment is too strong.

**F6 — The converged carrier defaults two fields the removed one required, undisclosed and untested.**
`src/services/agent_schema_types.py:336-337` vs the removed carrier (diff `-118..-120`, no
defaults on either field).

```
new SchemaOverlay required fields: []
  schema_overlay={} (both keys absent)           -> ACCEPTED as field_overrides=mappingproxy({}) additional_optional_fields=()
  schema_overlay=only field_overrides            -> ACCEPTED
  schema_overlay=only additional_optional_fields -> ACCEPTED
```

All three previously raised `ValidationError: missing`. A truncated or empty persisted
`schema_overlay` column now silently becomes an empty overlay rather than failing validation.
Impact is genuinely small — `validate_definition_hash` would catch a truncation whose original
overlay was non-empty, and all seven v1 overlays are empty so the two forms hash identically
today — but the loosening is undisclosed and no test covers it. Worth a line in the ledger so
Tasks 4/5, which introduce the first non-empty overlays, do not inherit it silently.

---

## Baselines — all independently re-run and confirmed

| Gate | Claimed | Reviewer measured | |
| --- | --- | --- | --- |
| Focused (`test_graph_definition_manifest.py` + `test_agent_schema_registry.py`) | 141 / 0 / 0 | **141 passed, 0 failed, 0 skipped** | ✅ |
| Task 7 unit matrix (17 files, enumerated from the plan) | 844 / 0 / 0, 131 warnings | **844 passed, 0 failed, 0 skipped, 131 warnings** | ✅ |
| Full `tests/unit` | 14 / 5538 / 110, 136 warnings | **14 failed, 5538 passed, 110 skipped, 136 warnings** | ✅ |
| Six-file split | 1 / 2 / 2 / 3 / 1 / 5 | **1 / 2 / 2 / 3 / 1 / 5** | ✅ |
| Failure **causes** by traceback | 9 @ `:83`, 3 @ `:79`, 2 assertions | **9 / 3 / 2, verified** | ✅ |
| PostgreSQL, 6 matrix files, separate invocations | 2·7·7·1·2·15 = 34, zero skips | **15+2+1+2+7+7 = 34 passed, 0 failed, 0 skipped** | ✅ |
| PostgreSQL, c23's acceptance suite | 1 passed, 0 skipped | **1 passed** | ✅ |
| `ruff check` on the three changed files | clean | **All checks passed!** | ✅ |

Cause verification, from tracebacks rather than node names:

```
ConversationGraphReleaseIntegrityError: no active Graph Release   9   (conversation_pins.py:83)
AttributeError: '_FakeSession' object has no attribute 'execute'  3   (conversation_pins.py:79)
AssertionError: assert 'provisioned' == 'autoscaling'             1   (test_deploy_autoscaling.py)
AssertionError: Expected '_get_or_create_lakebase_provisioned'
                to have been called once. Called 0 times.         1   (test_deploy_autoscaling.py)
```

Twelve of fourteen funnel through `_require_active_graph_release` — one repair, not twelve.
**Zero failures outside the inherited set**, and none of the 14 lands in the Task 7 matrix.

Note on scope: `ruff check src tests` reports 2601 repo-wide errors. That is pre-existing and
unrelated; the task claimed cleanliness only for its three changed files, which is accurate and
appropriately scoped.

---

## Cannot verify

1. **Frontend lane.** Not run, by instruction — another agent holds it exclusively
   (correction 24). The four owed commands remain outstanding. The task's inspection claim that
   `frontend/tests/fixtures/mocks.ts:1085` already uses a valid `CanonicalFieldGuidance` shape is
   an inspection, not a test result, and I did not re-verify it by execution either. **No #264
   task may be signed off as matrix-complete while this is open.**
2. **The author's remaining mutation rows** (M2b, M3, M4, M6, M8, M9, M10, M11, M14, M15, M16). I
   re-measured 7 of 17 rows plus the c11 sabotage. Of those, two matched exactly, four are
   scope-consistent understatements, and one (M7) is wrong. I did not re-run the other ten, so I
   cannot certify the table row by row — F4's undeclared scope applies to all of them.
3. **Whether the author's driver actually asserted anchor counts.** It lived at
   `/tmp/t2-mutate.py`, outside the repo (correct hygiene, and I confirmed no probe file was left
   in `tests/`), so the file is not in the review range and I could not inspect it. The claim is
   plausible but unverifiable from the commit.
4. **Actual persisted bytes at the database layer.** F5's caveat: I verified the mapper's value
   and the ORM write path, not the byte sequence SQLAlchemy's JSON serializer emits.

---

## What this task did notably well

Recorded because the epic's practice is to reward the behaviours that catch real defects:

- **The vacuity catch is genuine, self-found, and correctly repaired in the same commit.** I
  reproduced all three wrong-reason `TypeError` messages byte-for-byte. A test that keeps passing
  for a reason your own change introduced is a class this epic had not seen, and it was caught by
  probing a green rather than trusting it.
- **The discriminating sabotage is the right way to establish a zero.** 30 across 4 files
  reproduces exactly, including the file c11 omitted. "Prove the absence, do not report it" was
  executed properly.
- **Scope discipline under temptation.** The silently-failing `isinstance` gate at
  `agent_schema_registry.py:556` sits one line from a branch the task deliberately exercised, and
  it was left byte-unchanged for the review scoped to catch it. That is harder than fixing it.
- **The mode decision itself is correct**, and for the right reason — `mode='json'` is provably
  the persisting form. Only the accompanying blindness finding is wrong.
- **Correction C-24 followed without prompting**: 23 exact digests carried as hand-written
  literals, none imported from the implementation.

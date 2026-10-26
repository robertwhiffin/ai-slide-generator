# Task 2 report — Integrate typed overlay grammar and retained identities (#264)

**Status: DONE**

- Base: `f94757d315a8d0314744f33426e80c6a95df404e` (triple check clean at dispatch — empty
  `git status --porcelain`, empty `git diff HEAD`, empty `git diff --cached`; HEAD as briefed).
- Implementation commit: **`38e1c46217627bfb04ee55a6262ae56c4165fb05`**
  (`feat: type retained schema overlay identities`).
- Files changed (`git diff --name-only f94757d3 HEAD`), exactly the three authorized:
  `src/services/graph_definition_manifest.py`,
  `tests/unit/test_graph_definition_manifest.py`,
  `tests/unit/test_agent_schema_registry.py`.

## Import provenance (proved in-worktree, once)

```
python                     3.11.0  /Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python
src                        <wt>/src/__init__.py
databricks_tellr           <wt>/packages/databricks-tellr/databricks_tellr/__init__.py
graph_definition_manifest  <wt>/src/services/graph_definition_manifest.py
agent_schema_registry      <wt>/src/services/agent_schema_registry.py
agent_schema_types         <wt>/src/services/agent_schema_types.py
databricks-sdk             0.112.0
```

`<wt>` = `/Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-264-schema-overlay`.
`test ! -e .venv` ran before and after every gate and passed every time. No `pip`, `uv`,
`uv run`, or `.venv` creation. No frontend command of any kind was run.

## The oracle

Confirmed before writing anything: `definition_content_hash()` over
`load_graph_v1_manifest().definitions` reproduces **all seven** "Packaged v1 content hash"
values byte-for-byte. The column is correct and was used as the oracle for the byte-identity
gate rather than asserting against my own output. The seven values are carried in the test as
literals (correction C-24), not imported.

The same probe independently re-confirmed that the seven **frozen v1 digests** in the
corrections table equal the packaged `schema_contract` digests, and that all seven
`protected_assembly` identities are `(1, e4ff3d61…)`.

## The mode decision — `mode='json'`, explicitly

**Decision: `mode='json'` is the byte-identity claim; `mode='python'` is pinned separately as
a second assertion so the two can never be silently swapped.**

Reason, from landed code rather than preference: the storage/wire serialization of the overlay
is `mode='json'`. `src/services/graph_configuration_content.py:79`
(`definition_content_values`) is the one landed mapper that writes the `schema_overlay` JSON
column, and it calls `value.model_dump(mode="json")`. That is the byte sequence that actually
persists and round-trips, so that is the one whose byte-identity is load-bearing. It yields
`additional_optional_fields: []`.

`mode='python'` yields `()`. It is *not* the wire form, but it is on the hash path
(`DefinitionContent.canonical_payload` dumps `mode="python"`), so it is asserted separately
rather than ignored. `test_packaged_v1_overlay_payload_is_byte_identical_under_the_chosen_mode`
therefore asserts three things per role:

1. `model_dump(mode="json")["schema_overlay"] == {"field_overrides": {}, "additional_optional_fields": []}`
2. `model_dump(mode="python")["schema_overlay"] == {"field_overrides": {}, "additional_optional_fields": ()}`
3. the exact persisted bytes: `'{"additional_optional_fields":[],"field_overrides":{}}'`

**A finding that came out of making the choice explicit**, recorded because it is the reason
the instruction to decide was right: the two modes are **hash-equivalent** for v1.
`_normalize_canonical_value` maps every tuple to a list, so swapping `canonical_payload`'s
`mode="python"` for `mode="json"` changes no hash at all — measured, RED=0 (mutation
M2-MISAIMED below). The hash gate therefore *cannot* detect the swap. Had the byte-identity
claim been left to whichever serialization call I happened to write, an implicit change of
mode would have been invisible. Assertion 2 is the only thing that catches it (mutation M1,
RED=1).

## What changed

One defect the plan names for Task 2 — two competing `SchemaOverlay` definitions — is closed.

- `src/services/graph_definition_manifest.py` no longer defines a second, untyped
  `SchemaOverlay(field_overrides: Mapping[str, object], additional_optional_fields)`. It
  imports and re-exports Task 1's typed `SchemaOverlay` and `CanonicalFieldGuidance` from
  `src/services/agent_schema_types.py`, which is the declared public home. An explicit
  `__all__` records the re-export as deliberate.
- The module's private `_freeze_json_containers` / `_thaw_json_containers` — the third copy of
  the #260 `MappingProxyType` pattern — are removed, per correction c12's ruling that Task 2
  converge the freeze helper alongside `SchemaOverlay` rather than leave a third copy. The
  shared helpers in `agent_schema_types` are now the only ones.
- `ContentIdentity(version, digest)` is **unchanged** and remains the storage/wire carrier.
  Its docstring now records *why* it carries no role.
- New: `schema_contract_identity(agent_key, stored: ContentIdentity) -> SchemaContractIdentity`
  — the server-owned bridge from the stored pair to the registry lookup key. The role is
  supplied by the caller from the owning record, never by the stored or submitted identity, so
  a mismatched role, version or digest **fails to resolve** rather than resolving to something
  else. This is the seam the corrections' producer/consumer table assigns to 2 → 3 and 2 → 4.

Graph V1 is not regenerated; the packaged snapshot and the `lru_cache`d manifest are untouched.
Schema-contract versions are not coupled to #265's protected-assembly versions — proved in
both directions.

### A behaviour change I had to compensate for, stated plainly

The removed local `_freeze_json_containers` **raised** `ValueError` on non-JSON overlay values
and non-string keys. The typed grammar deliberately does not: `CanonicalFieldGuidance` retains
invalid leaves so the registry can return its own ordered domain diagnostic
(`overlay_examples_invalid_json`) instead of leaking Pydantic's message. That is Task 1's
design, so convergence necessarily drops the manifest-level raise.

The fail-closed guarantee is not dropped with it — it moves to the hashing boundary, where
`_normalize_canonical_value` still raises `TypeError`. I added
`test_hashing_still_fails_closed_on_a_non_json_guidance_value` so that guarantee is asserted
somewhere rather than silently disappearing with the helper. Mutation M13 REDs it. No test
anywhere depended on the removed `ValueError` (grepped: the two message strings had no
consumer outside the helper itself).

### A pre-existing test that my change made vacuous — found and repaired

`test_nested_overlay_containers_are_immutable_but_dump_as_json_containers`
(`test_graph_definition_manifest.py`) put arbitrary nested JSON directly into
`field_overrides` and asserted `pytest.raises(TypeError)` on three nested mutations. Under the
typed grammar `field_overrides["outer"]` is a `CanonicalFieldGuidance` **model**, so all three
raise `TypeError` merely because a model is not subscriptable:

```
o["outer"]["added"] = False              -> TypeError 'CanonicalFieldGuidance' object does not support item assignment
o["outer"]["values"][0]["enabled"] = ... -> TypeError 'CanonicalFieldGuidance' object is not subscriptable
o["outer"]["values"][0] = {...}          -> TypeError 'CanonicalFieldGuidance' object is not subscriptable
```

It would have stayed green while measuring nothing about container immutability — the same
shape as the epic's vacuous-mock defect. Probed explicitly (output above), then repaired to
reach the frozen containers through `guidance.forbidden_properties()`, with `isinstance`
assertions on `MappingProxyType` and `tuple` so the raises cannot be satisfied by the wrong
mechanism. Mutation M12 REDs both it and the new nested-freeze test.

## Test results

| Gate | Result | Baseline | Reconciliation |
| --- | --- | --- | --- |
| Focused (`test_graph_definition_manifest.py` + `test_agent_schema_registry.py`) | **141 passed, 0 failed, 0 skipped** | 102 | 102 + 39 new |
| Task 7 unit matrix (17 files, verbatim) | **844 passed, 0 failed, 0 skipped** | 805 | 805 + 39 new |
| Full `tests/unit` | **14 failed, 5538 passed, 110 skipped, 136 warnings** | 14 / 5499 / 110 / 136 | 5499 + 39 new |
| PostgreSQL, 6 baseline files, separate invocations | **2 · 7 · 7 · 1 · 2 · 15 = 34 passed, 0 failed, 0 skipped** | 34, zero skips | identical |
| PostgreSQL, `test_conversation_pin_acceptance_postgres.py` (c23's addition) | 1 passed, 0 skipped | 1 passed | identical |
| `ruff check` on the three changed files | All checks passed | — | — |

**Full-suite failure causes verified by traceback, not inferred from counts.** The 14 are
exactly the inherited set, same six files, same split **1 / 2 / 2 / 3 / 1 / 5**, with **zero
failures outside it**:

- 9 × `ConversationGraphReleaseIntegrityError: no active Graph Release`, raised at
  `src/services/conversation_pins.py:83`
- 3 × `AttributeError: '_FakeSession' object has no attribute 'execute'`, raised at
  `src/services/conversation_pins.py:79`
- 2 × plain assertions in `test_deploy_autoscaling.py`:
  `assert 'provisioned' == 'autoscaling'` and
  `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`

Twelve of the fourteen funnel through `_require_active_graph_release` — one repair, not twelve,
as the reviewer's refinement states. Warnings unchanged at 136 (and 131 for the matrix),
same location set.

**Frontend: not run, deferred.** Another agent holds the lane exclusively. No frontend command
was issued. Still outstanding as correction 24 records.

## RED gate (plan requirement: RED must be the manifest integration, not a missing Task 1 module)

Tests were written first and run against the un-integrated manifest: **23 failed, 113 passed**.
Causes grouped from the actual output, not asserted:

| Count | Cause |
| ---: | --- |
| 20 | `ImportError: cannot import name 'schema_contract_identity' from 'src.services.graph_definition_manifest'` |
| 1 | `AssertionError: <class 'graph_definition_manifest.SchemaOverlay'> is <class 'agent_schema_types.SchemaOverlay'>` |
| 1 | `AssertionError: assert 'mappingproxy' == 'CanonicalFieldGuidance'` |
| 1 | `AttributeError: 'mappingproxy' object has no attribute 'examples'` |

All four are the manifest integration. Task 1's module imported cleanly throughout; no RED was
a missing-module error. All 102 pre-existing tests stayed green through the RED phase.

## Measured radius of the grammar change vs the expected 30 / 4 files

**Measured radius of my change: 0 RED, in all four c11 files and in six more.**

```
test_agent_runtime.py, test_agent_resolution_prompt.py,
test_deck_level_spec_change.py, test_graph_configuration_bootstrap.py   106 passed, 0 failed
test_graph_configuration_draft.py, test_prompt_assembler.py,
test_graph_definition_content_mapping.py, test_agent_definition_workbench_routes.py,
test_graph_configuration_models.py, test_persisted_agent_runtime.py     380 passed, 0 failed
```

The brief's instruction was: if fewer go red than expected, do not assume luck — check the
change reached the literal. Zero is correct, and here is why, proved two ways rather than
argued.

**Aim check 1 — the literal now validates through the typed class.** Resolving through
`CompatibilityResolvedDefinitionLoader` (the owner of the hardcoded v1 overlay at
`agent_runtime.py:452`):

```
resolved overlay class : src.services.agent_schema_types.SchemaOverlay
is agent_schema_types.SchemaOverlay : True
field_overrides annotation : Mapping[str, src.services.agent_schema_types.CanonicalFieldGuidance]
content_hash : e77e69b18cb9d843a1754dab65a79941ede8cfa7c8266292580ff7566d1dcb33   (= architect's packaged v1 hash)
```

So the change did reach the literal. Zero RED is because
`{"field_overrides": {}, "additional_optional_fields": []}` is valid under **both** grammars —
which was the design intent of converging by re-export rather than by rewriting the carrier.

**Aim check 2 — a discriminating sabotage of the literal, which reproduces c11's amended
radius exactly.** I changed the literal to `{"message": "TASK2_AIM_CHECK_NOT_A_MAPPING"}` — a
value the *old* untyped `Mapping[str, object]` accepted and the typed grammar rejects, so it
REDs only if the literal is on the typed path:

| File | RED | Amended c11 figure |
| --- | ---: | ---: |
| `tests/unit/test_agent_runtime.py` | **20** | 20 |
| `tests/unit/test_agent_resolution_prompt.py` | **7** | 7 |
| `tests/unit/test_deck_level_spec_change.py` | **2** | 2 |
| `tests/unit/test_graph_configuration_bootstrap.py` | **1** | 1 |
| **Total** | **30 across 4 files** | **30 across 4 files** |

Byte-identical to the reviewer's amended figure, including the file c11 omitted. This
independently re-confirms the amendment (c11's original "8" counted call sites) and proves the
literal is genuinely on my typed path. Restored from a `cp` backup and verified byte-identical
to base with `diff`; `git diff --name-only HEAD` then showed only my two authorized files.

## REQUIRED DELIVERABLE — clause-to-mutation table

Seventeen runs, one per clause plus one reported mis-aim. **Blank count: 0** — every clause
this task mandates has at least one mutation measured to RED it. Each mutation was applied to
a single unique anchor (the driver refuses a missing or non-unique anchor), run, then restored
from a `cp` backup with `git diff --name-only HEAD` asserted empty before the next.

| # | Brief clause | Test that claims it | Mutation that would RED it | Measured |
| --- | --- | --- | --- | ---: |
| M1 | byte-identical v1 payloads; the explicit `json` vs `python` decision | `test_packaged_v1_overlay_payload_is_byte_identical_under_the_chosen_mode` | `agent_schema_types`: `additional_optional_fields: tuple[str, ...] = ()` → `list[str] = []` | **RED 1** |
| M2 | byte-identical v1 hashes — **first attempt, MIS-AIMED** | same hash test | `graph_definition_manifest`: `canonical_payload` `mode="python"` → `mode="json"` | **RED 0** (see below) |
| M2b | byte-identical v1 hashes — re-aimed at the overlay serializer | `test_packaged_v1_content_hashes_are_the_seven_frozen_literals` | `agent_schema_types.SchemaOverlay.serialize_field_overrides` emits an extra `_probe` key | **RED 1** |
| M3 | typed guidance round-trip: absent vs explicitly-null retention | `test_typed_guidance_round_trips_through_the_storage_carrier` | `serialized_mutations`: drop the `mutation_is_supplied("description")` guard | **RED 1** |
| M4 | v2 hash change; server-owned v2 identity | `…_upgrade_changes_the_hash_and_only_the_schema_identity` (×7 roles) + `…_keeps_the_manifest_identity_carrier_type` | `upgrade_content_to_v2`: `identity_for(key, 2)` → `identity_for(key, 1)` | **RED 8** |
| M5 | all v1/v2 identities resolve from the retained carrier | `test_stored_identity_resolves_the_exact_role_and_version_bundle` (7 roles × 2 versions) | `schema_contract_identity`: `version=stored.version` → `version=1` | **RED 7**, 7 pass (precisely the 7 v2 rows) |
| M6 | fail-closed on mismatched role / version / digest | `test_stored_identity_resolution_fails_closed` (6 cases) + registry bridge test | `AgentSchemaRegistry._resolve`: drop `or bundle.identity != identity` | **RED 5**, 2 pass (the 2 genuinely-absent-bundle cases, correctly still closed) |
| M7 | no client-selected identities: role comes from the owning record | `test_stored_identity_resolution_fails_closed` + registry bridge test | `schema_contract_identity`: `agent_key=agent_key` → `agent_key="architect"` | **RED 1** (the `not_a_role` case now resolves) |
| M8 | one `SchemaOverlay`; import/re-export, no competing class | `…_is_the_one_typed_grammar_and_not_a_second_definition` + `test_registry_overlay_grammar_is_the_storage_carriers_overlay_grammar` | re-introduce a local `class SchemaOverlay(_FrozenModel)` shadowing the import | **RED 2** |
| M9 | do not regenerate Graph V1 | `test_schema_contract_upgrade_does_not_regenerate_graph_v1` | `upgrade_content_to_v2`: mutate the shared record in place instead of `model_copy` | **RED 1** |
| M10 | retain `ContentIdentity(version, digest)` as storage/wire carrier | `test_upgrade_content_to_v2_keeps_the_manifest_identity_carrier_type` | `upgrade_content_to_v2` BaseModel branch returns the registry dataclass, not `type(existing).model_validate(...)` | **RED 1** |
| M11 | converge the freeze helper; no third copy (c12 ruling) | `…_is_the_one_typed_grammar_and_not_a_second_definition` | re-add `_freeze_json_containers` to the manifest module | **RED 1** |
| M12 | the recursive #260 freeze reaches through the typed grammar | `…_nested_containers_are_frozen_inside_the_carrier` + the repaired `…_immutable_but_dump_as_json_containers` | `freeze_json_containers`: return a plain `dict` instead of `MappingProxyType` | **RED 2** |
| M13 | hashing still fails closed on a non-JSON guidance value | `test_hashing_still_fails_closed_on_a_non_json_guidance_value` | `_normalize_canonical_value`: `return repr(value)` instead of `raise TypeError` | **RED 1** |
| M14 | a v2 typed overlay round-trips through the one landed mapper | `test_upgraded_content_round_trips_through_the_persistence_mapper` | `definition_content_values`: `mode="json"` → `mode="python"` | **RED 1** |
| M15 | independent identities: a schema upgrade must not touch #265's assembly | `…_upgrade_changes_the_hash_and_only_the_schema_identity` (×7) | `upgrade_content_to_v2` also writes `protected_assembly` | **RED 7** |
| M16 | independent identities: an assembly upgrade must not touch the schema contract | `test_assembly_upgrade_leaves_the_schema_contract_untouched` | `prompt_assembler.upgrade_definition_to_v2` also writes `schema_contract` | **RED 1** |

### The mis-aimed attempt, reported

**M2 measured RED 0.** My first aim at the v1-hash clause was to swap `canonical_payload`'s
dump mode. I suspected my aim before the suite, and the aim was indeed the problem — but the
reason is substantive rather than clumsy: `_normalize_canonical_value` normalizes every tuple
to a list, so `mode="python"` and `mode="json"` produce the *same* canonical payload for v1,
and no hash can distinguish them. The mutation is not a hash mutation at all. Re-aimed at the
overlay serializer (M2b) and got RED 1.

This is exactly why the brief demanded the mode decision be explicit: the hash gate is blind
to it, so only a direct payload assertion (M1) guards it. The zero is reported because it is
the informative half of the result.

## Task 3's scope, untouched

Verified by `git diff --quiet f94757d3 HEAD -- <file>`:

- `src/services/agent_runtime.py` — **UNCHANGED**
- `src/services/agent_schema_registry.py` — **UNCHANGED**
- `src/services/agent_schema_types.py` — **UNCHANGED**

- `SchemaContractIdentity` is still defined twice, at `agent_runtime.py:126` and
  `agent_schema_types.py:367`. The divergence is neither deepened nor resolved. My new
  `schema_contract_identity` imports the `agent_schema_types` one — the declared public home —
  so it consumes the public type rather than adding a third.
- The `isinstance(existing_identity, SchemaContractIdentity)` gate at
  `agent_schema_registry.py:556` is **not patched**. Mutation M10 exercised the adjacent
  `BaseModel` branch (the branch `ContentIdentity` actually takes) and was restored; the gate
  line itself was never edited. Leaving it is deliberate: fixing it here would move a defect
  out from under the review scoped to catch it.
- Nothing was done about c25's accepted Build Reviewer deck-brief debt.
- `CUSTOM_ANCHORS` not reordered; `frontend/src/api/agentDefinitions.ts` not opened for edit.
- `src/services/graph_configuration_draft.py` — not modified at all, so neither the loud
  refactor nor the silent reformat hazard in `test_prompt_assembler.py`'s eight-file text join
  applies. `test_prompt_assembler.py` passes (part of the 380 above).

## Hygiene

- Every mutation restored from a `cp` backup, never `git checkout <commit> -- <paths>`.
- Drift enumerated from `git diff --name-only HEAD` after every restore, never from
  expectation. Final triple check clean; HEAD `38e1c4621`.
- The mutation driver lives at `/tmp/t2-mutate.py`, deliberately **outside** the repository:
  phase B's reviewer contaminated its own full-suite count by leaving a probe file in
  `tests/unit/`. `git status --porcelain` is empty, so no probe file was left behind, and the
  5538 figure is uncontaminated.
- No push, no PR, no merge, no deploy. No subagents. No database created, dropped, migrated or
  altered by hand.

## Concerns for the reviewer and for Task 3 / Task 4 / Task 5

1. **`SchemaOverlayResponse` is now typed loosely against a typed source, and no test covers a
   non-empty overlay on the wire.** `src/api/schemas/agent_definitions.py:44` declares
   `field_overrides: dict[str, object]` and reads it off the content via
   `from_attributes=True`. The values are now `CanonicalFieldGuidance` models rather than plain
   dicts. All seven packaged v1 overlays are empty, so nothing exercises it today and the read
   route is green — but the first non-empty overlay reaches that DTO as model instances under
   an `object` annotation. **Task 5 owns this DTO** and should decide explicitly whether it
   serializes guidance models or is retyped to the guidance schema. Flagging rather than
   changing it: it is Task 5's file and a wire-shape decision.

2. **`agent_runtime.py:547` still hard-rejects any non-empty overlay for Graph V1**
   (`IncompatibleSchemaContractError("Graph Version 1 requires an empty schema overlay")`), and
   it checks `field_overrides or additional_optional_fields` before resolving the contract. That
   is correct for v1 and is Task 3's to relax for v2. Noting it so Task 3 does not discover it
   as a surprise: with my change the field it tests is now a mapping of typed guidance, and the
   truthiness check still behaves identically.

3. **`CanonicalFieldGuidance` has `extra="allow"` by design, so the manifest carrier now accepts
   unknown guidance properties at the Pydantic layer** and defers rejection to the registry's
   `overlay_guidance_property_forbidden`. That is Task 1's deliberate design (retain extras for
   a stable domain diagnostic), and it is why correction c16's ruling matters: the rejection
   only happens if Task 4 registers overlay validation in `local_candidate_validators`. Until
   Task 4 lands, `DefinitionContent` will validate an overlay the registry would reject. Not a
   defect in Task 2's slice, but it is a real open window and Task 4 closes it.

4. **The frontend baseline remains outstanding** (correction 24). No #264 task may claim matrix
   completion while it is open, and Task 2 does not claim it. The existing fixture at
   `frontend/tests/fixtures/mocks.ts:1085` already uses
   `{ title: { description: "…" } }`, which is a valid `CanonicalFieldGuidance` shape, so the
   typed grammar appears wire-compatible with the shipped client — but that is an inspection,
   not a test result, because I ran no frontend command.

5. **M7's radius is narrow (RED 1 of 7).** Hardcoding the bridge's role REDs only the
   `not_a_role` case. The registry-side cross-role assertions still pass because
   `validate_overlay` carries its own `agent_key` argument independently of the identity. The
   clause is guarded, but by one node; a reviewer wanting a wider net on
   "no client-selected identities" could add a case where the stored digest belongs to the
   hardcoded role.

---

# Task 2 — fix round 1 of 5. Corrections 27 through 30.

**Status: DONE.** Fix-round base `e5cfb11dfd6e90e24e5f2def4fe39c35b06f8e90` (triple check
clean). No shipped-behaviour finding was raised against round 1; three of the four items are
report and ledger corrections, and one restored a guard.

Commits in this round:

- **`1fe251549a649c97ef50c41c2fd000fd176b175f`** — `fix: restore the non-string-key guard and
  pin two disclosed behaviours (#264)`. Two files: `src/services/graph_definition_manifest.py`
  (+11), `tests/unit/test_graph_definition_manifest.py` (+103).
- the commit carrying this appendix and its ledger entry.

I lost the session to an infrastructure error (ENOTFOUND) partway through the closing gates.
`1fe251549` had already landed. The controller salvaged and independently re-verified it; I
re-verified the base, re-confirmed all three new tests are present in the committed tree, and
finished the gates I died during. **One correction to the re-dispatch brief: item 3 / F6 is
already tested**, not "undisclosed and untested" — `test_converged_overlay_defaults_two_fields_the_removed_carrier_required`
landed in `1fe251549`. What remained for F6 was the prose disclosure, which is below.

## ITEM 1 — my mode-blindness conclusion was FALSE. Re-measured myself.

I did not take this on report. I reproduced it against the pristine tree and then probed the
mechanism directly.

**Measurement.** With the anchor count asserted at exactly 1, swapping `canonical_payload`'s
`mode="python"` for `mode="json"`:

- at the row's own named selector — `1 passed`, **RED 0**. My round-1 number.
- at full focused-suite scope — **RED 6**, named:

```
test_hash_normalizes_manifest_floats_and_database_decimals
test_hash_rejects_non_finite_numeric_values[temperature-Decimal('NaN')]
test_hash_rejects_non_finite_numeric_values[top_p-Decimal('Infinity')]
test_hashing_still_fails_closed_on_a_non_json_guidance_value          (mine, round 1)
test_canonical_payload_mode_is_load_bearing_for_the_finiteness_guard  (mine, this round)
test_hashing_rejects_non_string_object_keys_inside_guidance           (mine, this round)
```

**Mechanism, probed directly rather than reasoned about.** On the shipped `mode='python'` path
a non-finite `Decimal` raises `ValueError: canonical numeric values must be finite`. Under the
mutation it is **silently hashed** to `140de6a94eff…`, and `Decimal('0.700000')` stops hashing
equal to the packaged float `0.7`. So the mode is load-bearing for two independent guarantees —
Decimal normalisation, which is what `canonical_payload`'s own docstring exists for, and a
fail-closed finiteness guard. `Decimal` is exactly the shape these values take crossing the
SQLAlchemy boundary.

**One thing I found that goes beyond correction 27.** The mode also protects the *key* half:
node 6 above REDs because `mode='json'` coerces an `int` key to `"1"` before the normaliser can
see it, so the new key check cannot fire either. The mode guards **both** halves of the removed
helper's fail-closed behaviour, not just the numeric one.

**The corrected conclusion.** My round-1 number was right under an undeclared per-named-test
scope; the defect was generalising it. "Changes no hash at all" and "the hash gate cannot detect
the swap" are both **false and withdrawn**. What survives is the mode *choice*: `mode='json'` is
provably the persisting form, because `schema_overlay` is `json_document=True`
(`graph_configuration_content.py:44`) and `definition_content_values` dumps `mode="json"` at
`:79`. Both mode assertions have teeth, each proved by a distinct mutation. The requirement to
decide explicitly was right; my reasoning in support of it was wrong, and it was wrong in the
dangerous direction — it would have told a later task that removing a fail-closed guard was free.

Pinned by `test_canonical_payload_mode_is_load_bearing_for_the_finiteness_guard`, which asserts
the payload keeps a real `float` (not a stringified Decimal), that the Decimal and float forms
hash equal, and that both non-finite Decimals raise. Mutation M2 REDs it.

## ITEM 2 — the M7 row named the wrong node. Re-measured myself.

Hardcoding the bridge's role to `"architect"`:

- `test_stored_identity_resolution_fails_closed` — **6 passed, 0 failed.** My round-1 row
  claimed this was the RED node. It is not, and the reason is instructive: `_resolve` keys the
  bundle lookup on the `agent_key` **argument**, so `("not_a_role", 1)` still misses the
  registry and still fails closed regardless of what role the identity carries.
- real radius, both scopes — **RED 13**: twelve parametrisations of
  `test_stored_identity_resolves_the_exact_role_and_version_bundle` (the six non-architect roles
  × two versions) plus `test_registry_resolves_identities_bridged_from_the_stored_content_identity`.

**Residual, corrected.** My round-1 concern 5 said the clause was "guarded, but by one node".
That was wrong — it is guarded by thirteen. The real residual is narrower and different: **no
test distinguishes the role *direction***, because `_resolve` keys on the argument and nothing
in the suite passes an identity whose role differs from it. I am not adding one, because the
structural protection is stronger than a test would be: `ContentIdentity` carries no role at
all, so the bridge **cannot** take one from a stored pair. A test could only assert something
the type system already makes unconstructible.

## ITEM 3 (c29) — the fail-closed guarantee had moved only half. Guard restored.

Verified myself before fixing: `{1: "a"}` and `{"1": "a"}` inside `examples` both hashed to
`3b0f99866da532e835babeb7e646943ead92cb42d103d4bedd773baeb7b82ef0`, the persist path silently
coerced `1` to `"1"` (`{'examples': [{'1': 'a'}]}`), and mixed keys failed only incidentally
with `TypeError: '<' not supported between instances of 'str' and 'int'` — a `json.dumps`
sort-comparison leak, not a domain check.

**Decision: restore the key check, with tests.** I took this over the accepted-coercion ruling
for three reasons. The removed helper carried the raise, so dropping it silently is the exact
"half-moved guarantee" defect. The incidental mixed-key failure is a Pydantic/stdlib
implementation leak, which is what Task 1's design explicitly exists to avoid. And two distinct
semantic inputs sharing one content hash is an identity collision in a system whose entire point
is content-addressed identity — low reachability is a reason to rank it Important, not a reason
to accept it.

**Placement.** In `_normalize_canonical_value`, the same hashing boundary the value half now
lives at, and inside my own authorized file — no Task-3 file touched. Every write path reaches
it before mutating a row: I confirmed `_write_locked_content` computes
`definition_content_hash(content)` at `graph_configuration_draft.py:637`, **before** the
`definition_content_values(content)` mapper call at `:638`. Int keys and mixed keys now raise
`TypeError: canonical object keys must be strings, received 1`; the string-keyed sibling still
hashes to `3b0f9986…` unchanged, so no existing hash moved.

## ITEM 3 / F6 (c30) — the disclosed relaxation, in prose

`agent_schema_types.py:336-337` — the converged carrier declares
`field_overrides: Mapping[str, CanonicalFieldGuidance] = Field(default_factory=dict)` and
`additional_optional_fields: tuple[str, ...] = ()`. The removed manifest-local overlay declared
both **without defaults**. So `schema_overlay: {}` previously raised two `missing` errors and
now validates to an empty overlay.

This is a real, undisclosed narrowing of validation that I should have stated in round 1 and did
not. It is harmless today only because all seven packaged v1 overlays are empty; Tasks 4 and 5
introduce the first non-empty ones. It is a **defaults-only** relaxation — unknown keys are
still refused, which the test asserts — and the defaults equal the packaged values, so it cannot
move a v1 hash. Pinned by
`test_converged_overlay_defaults_two_fields_the_removed_carrier_required`; mutation M18 REDs it
(RED 46 at focused scope, because much of the suite constructs overlays relying on the default).

## ITEM 4 / F4 — the table's measurement scope, declared

**Declared scope for every row below: two numbers per row.** "named" is the row's own named test
selectors, which is the only scope round 1 reported and reported without declaring. "focused" is
the whole focused suite — `tests/unit/test_graph_definition_manifest.py` plus
`tests/unit/test_agent_schema_registry.py`, 144 tests. Neither number is the full-suite radius.

Round 1's numbers were all scope-consistent and all understatements — M1, M5, M12 and M2's zero
— which left no clause unguarded, but an undeclared narrow scope is precisely what let a reader
generalise M2's zero into a false general claim. That is the failure this declaration exists to
prevent.

Per **C-27**, the harness now asserts its anchor count and **hard-fails** on anything but
exactly one occurrence. All 19 rows below asserted at exactly 1.

| # | Clause | Test that claims it | Mutation | named | focused |
| --- | --- | --- | --- | ---: | ---: |
| M1 | byte-identical v1 payloads; the explicit mode decision | `…_payload_is_byte_identical_under_the_chosen_mode` | `additional_optional_fields: tuple[str, ...] = ()` → `list[str] = []` | 1 | 4 |
| **M2** | **the canonical dump mode is load-bearing** (CORRECTED) | `…_mode_is_load_bearing_for_the_finiteness_guard` | `canonical_payload` `mode="python"` → `mode="json"` | **1** | **6** |
| M2b | byte-identical v1 hashes | `…_content_hashes_are_the_seven_frozen_literals` | overlay serializer emits an extra `_probe` key | 1 | 18 |
| M3 | typed guidance round-trip: absent vs explicit null | `…_round_trips_through_the_storage_carrier` | drop the `mutation_is_supplied("description")` guard | 1 | 7 |
| M4 | v2 hash change; server-owned v2 identity | `…_only_the_schema_identity` ×7 + `…_keeps_the_manifest_identity_carrier_type` | `identity_for(key, 2)` → `identity_for(key, 1)` | 8 | 10 |
| M5 | all v1/v2 identities resolve | `…_resolves_the_exact_role_and_version_bundle` | `version=stored.version` → `version=1` | 7 | 10 |
| M6 | fail-closed on mismatched role/version/digest | `…_resolution_fails_closed` + registry bridge | `_resolve`: drop `or bundle.identity != identity` | 5 | 6 |
| **M7** | **role comes from the owning record** (CORRECTED) | `…_resolves_the_exact_role_and_version_bundle` ×12 + registry bridge | `agent_key=agent_key` → `agent_key="architect"` | **13** | **13** |
| M8 | one `SchemaOverlay`; no competing class | `…_not_a_second_definition` + `…_storage_carriers_overlay_grammar` | re-introduce a shadowing local `SchemaOverlay` | 2 | 20 |
| M9 | do not regenerate Graph V1 | `…_does_not_regenerate_graph_v1` | upgrade mutates the shared record in place | 1 | 12 |
| M10 | retain `ContentIdentity` as storage/wire carrier | `…_keeps_the_manifest_identity_carrier_type` | BaseModel branch returns the registry dataclass | 1 | 8 |
| M11 | freeze-helper convergence, no third copy (c12) | `…_not_a_second_definition` | re-add `_freeze_json_containers` to the manifest | 1 | 1 |
| M12 | the recursive #260 freeze reaches the typed grammar | `…_frozen_inside_the_carrier` + the repaired `…_dump_as_json_containers` | `freeze_json_containers` returns a plain `dict` | 2 | 3 |
| M13 | hashing fails closed on a non-JSON **value** | `…_fails_closed_on_a_non_json_guidance_value` | `return repr(value)` instead of `raise TypeError` | 1 | 1 |
| M14 | a v2 typed overlay round-trips through the one mapper | `…_round_trips_through_the_persistence_mapper` | mapper `mode="json"` → `mode="python"` | 1 | 1 |
| M15 | a schema upgrade must not touch #265's assembly | `…_only_the_schema_identity` ×7 | upgrade also writes `protected_assembly` | 7 | 8 |
| M16 | an assembly upgrade must not touch the schema contract | `…_leaves_the_schema_contract_untouched` | `upgrade_definition_to_v2` also writes `schema_contract` | 1 | 1 |
| **M17** | **hashing fails closed on a non-string KEY** (c29, new) | `…_rejects_non_string_object_keys_inside_guidance` | neutralise the key loop | **1** | **1** |
| **M18** | **the disclosed defaults relaxation** (c30, new) | `…_defaults_two_fields_the_removed_carrier_required` | remove `field_overrides`' default | **1** | **46** |

**19 rows. Blank count 0 at both declared scopes** — no row REDs nothing at either scope.

## Two mis-aimed probes of my own, this round

Reported because the habit matters more than the tidiness of the result.

1. **A probe where I forgot to restore, so both halves measured the same thing.** Comparing the
   shipped mode against the mutated mode, I left the previous call's mutation in place, so my
   "shipped `mode=python`" arm was actually running json mode. Both arms returned the identical
   hash `140de6a9…` and I nearly recorded "not fail-closed" for the shipped path. **The C-27
   anchor assertion caught it**: the second mutation attempt found 0 occurrences of the
   `mode="python"` anchor and hard-failed instead of measuring. That is precisely the failure
   mode C-27 was adopted for, on the first run after adopting it. Re-probed against a tree
   verified byte-identical to base with `diff -q`, and got the correct result.

2. **My first full table run had a stale baseline, inflating every focused number by 1.** The
   driver's `cp` backups were taken *before* the ITEM 3 key check, so `restore_all()` silently
   reverted it and left `test_hashing_rejects_non_string_object_keys_inside_guidance` failing in
   every focused run. I caught it because M17's anchor then failed to exist at all — the same
   assertion firing a second time. Re-baselined the backups from the committed state and re-ran
   all 19 rows. **The numbers in the table above are from the re-run**; the first run's focused
   column was uniformly one too high and is discarded.

## Gates

| Gate | Result | Prior | Reconciliation |
| --- | --- | --- | --- |
| Focused (manifest + registry tests) | **144 passed, 0 failed, 0 skipped** | 141 | 141 + 3 new |
| Task 7 unit matrix (17 files, verbatim) | **847 passed, 0 failed, 0 skipped** | 844 | 844 + 3 new |
| Full `tests/unit` | **14 failed, 5541 passed, 110 skipped, 136 warnings** | 14 / 5538 / 110 / 136 | 5538 + 3 new |
| PostgreSQL, 6 baseline files, separate invocations | **2 · 7 · 7 · 1 · 2 · 15 = 34 passed, 0 skipped** | 34, zero skips | identical |
| PostgreSQL `test_conversation_pin_acceptance_postgres.py` | 1 passed, 0 skipped | 1 passed | identical |
| `ruff check` / `ruff format --check` on changed files | clean | — | — |

Full-suite causes re-verified by traceback: 9 × `ConversationGraphReleaseIntegrityError` at
`conversation_pins.py:83`, 3 × `AttributeError: '_FakeSession'…execute` at `:79`, 2 ×
`test_deploy_autoscaling.py` assertions. Same six files, split **1/2/2/3/1/5**, **zero new
failure causes**. PostgreSQL was re-run in full this round specifically because the ITEM 3 change
sits on `_normalize_canonical_value`, which every persistence write crosses.

`.venv` absent before and after every gate. No `pip`, `uv`, `uv run`. **No frontend command
run** — that lane is held elsewhere and correction 24's four owed commands remain deferred.

## Scope discipline held

`git diff --name-only 2cf82b34e HEAD -- src tests` is exactly
`src/services/graph_definition_manifest.py` and `tests/unit/test_graph_definition_manifest.py`.
`agent_runtime.py`, `agent_schema_registry.py` and `agent_schema_types.py` remain **UNCHANGED**
across the whole task. `SchemaContractIdentity` is still defined twice; the `isinstance` gate at
`agent_schema_registry.py:556` is still byte-unchanged, one line from the `BaseModel` branch
mutations M4/M10 deliberately exercised and restored. No database created, dropped, migrated or
altered by hand. All mutations restored from `cp` backups; drift enumerated from
`git diff --name-only HEAD` after each. Driver kept outside the repository at
`/tmp/t2r2/mutate2.py`.

## Concerns after this round

1. **I generalised an undeclared-scope measurement into a general claim, and it was a claim that
   would have made a fail-closed guard look free to remove.** That is the most serious thing in
   either round, and it was mine. The mechanical fix is the declared two-scope table; the
   judgement fix is that a zero measured at a narrow scope licenses no statement about any wider
   scope. My M7 error has the same root: I asserted *which node* RED without checking.
2. **The role-direction residual stands, deliberately untested** (ITEM 2 above). Structural, not
   testable, because `ContentIdentity` carries no role.
3. **The three round-1 forward items ruled correctly deferred are unchanged**, and the
   `extra="allow"` window is narrower than I stated — unreachable from any client path today
   because the PUT DTO refuses `schema_overlay` and `agent_runtime.py:547` hard-rejects
   non-empty. I was conservative about my own exposure; noting that the correction was in the
   safe direction, not that it was harmless.
4. **`test_hashing_rejects_non_string_object_keys_inside_guidance` asserts a hash literal
   (`3b0f9986…`) for the string-keyed sibling.** That is deliberate — it proves the new check
   moved no existing hash — but it is a second place that hash now lives, and a future
   legitimate change to guidance serialisation will need to update it.
5. **Frontend baseline still outstanding** under correction 24.

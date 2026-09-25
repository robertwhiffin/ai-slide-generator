# Task 3 report — Runtime composition, canonical projection, diagnostics and traces (#264)

**Status: DONE_WITH_CONCERNS** — the work is complete and every gate is green, but three
things a reviewer must weigh are disclosed rather than absorbed: the file set is wider than the
plan's Files block, half the tests were written after the implementation rather than RED-first,
and the production logging sink now emits one model-derived field where it previously emitted
none.

- Base: `1fb5141ccc7c4267cc10018f2271e4c28f08d24e`. Triple check clean at dispatch — empty
  `git status --porcelain`, empty `git diff HEAD`, empty `git diff --cached`. HEAD as briefed.
- Commits:
  - **`cca068af3252410b92f3be44e0550c3eb81d900c`** `feat: trace validated schema overlay output`
  - **`87676a04fdf215d34fe0ba80f9241806a55c67ed`** `test: pin the generic fallback and the dump-mode precondition (#264)`
  - plus the artefact commit carrying this report, the corrections append and the ledger append.
- Branch `feat/schema-overlay-264`. No push, no PR, no merge, no deploy, no subagents.

## Import provenance (proved in-worktree, once)

```
python            3.11.0  /Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python
databricks-sdk    0.112.0
src                      <wt>/src/__init__.py
databricks_tellr         <wt>/packages/databricks-tellr/databricks_tellr/__init__.py
agent_runtime            <wt>/src/services/agent_runtime.py
agent_runtime_identity   <wt>/src/services/agent_runtime_identity.py
agent_schema_registry    <wt>/src/services/agent_schema_registry.py
agent_schema_types       <wt>/src/services/agent_schema_types.py
```

`<wt>` = `/Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-264-schema-overlay`.
`test ! -e .venv` ran before and after every gate and passed every time. No `pip`, no `uv`, no
`uv run`, no `.venv` creation. **No frontend command of any kind was run** — correction 24 is
still outstanding and this task did not touch that lane.

---

# THE THREE THINGS TASK 2 LEFT

## 1. How the duplicated `SchemaContractIdentity` was converged

**Measured first, then fixed.** The live divergence reproduced exactly as briefed:

```
runtime class is public class:  False
a == b:                         False
isinstance(a, PublicIdentity):  False
reprs byte-identical:           True
_SchemaContractRegistry().identity_for('architect')
    == V1_SCHEMA_IDENTITIES['architect']:   False        <- the two registries diverged
    .digest == .digest:                     True         <- on the same digest
```

**The convergence deletes the duplicate rather than reconciling it.** `agent_runtime.py` no
longer defines `class SchemaContractIdentity` at all; it imports the public one from
`src/services/agent_schema_types.py`, which correction 12 names as the declared public home.
Nothing outside `agent_runtime.py` imported the runtime copy (grepped repo-wide before the
change), so the convergence is a pure deletion-plus-import inside a Files-block file. **No file
outside the plan's Files block was needed for the convergence**, which is why I did not need to
ask — the scope question the brief gated on did not arise.

Two consequences, both deliberate:

- `_SchemaContractRegistry` and `AgentSchemaRegistry` now build the **same class**, so
  `identity_for(role) == V1_SCHEMA_IDENTITIES[role]` is True for all seven roles and `isinstance`
  holds in both directions. Pinned by
  `test_runtime_and_registry_agree_on_identity_class_equality_and_isinstance`.
- The runtime stopped hand-building the identity. `_run_resolved` now calls Task 2's
  `schema_contract_identity(definition.agent_key, content.schema_contract)` — the bridge Task 2
  built for exactly this seam, which takes the role from the owning record so a stored pair
  cannot select another role's contract.

**A guard against re-duplication, not just a fix.**
`test_schema_contract_identity_is_defined_exactly_once_in_the_repository` scans every `.py` under
`src/` for `^class SchemaContractIdentity[(:]` and asserts the sorted result is exactly
`["services/agent_schema_types.py"]`. It also asserts `agent_runtime.SchemaContractIdentity is
agent_schema_types.SchemaContractIdentity` and the same for the manifest.

> **A mis-aim in my own test, reported.** My first version of that scan matched the substring
> `"class SchemaContractIdentity"`, which the *new* `class SchemaContractIdentityCarrierError`
> also contains — so the test failed against a correct tree. Re-aimed to an anchored regex. My
> second mis-aim was in the same test: I asserted the shadow class's repr equals the real one's,
> which is false for a function-local class because `__qualname__` carries the enclosing scope.
> Re-aimed at `fields()` + `astuple()` equality, which is the property that actually makes the
> shadow indistinguishable.

## 2. How the `:556` gate was made to fail LOUDLY rather than silently

The brief's standard was explicit: *"a fix that merely stops the fall-through without making the
failure loud is half a fix."* Convergence alone would have stopped this particular
fall-through — with one class, `isinstance` succeeds — and left the gate's *shape* intact. So the
gate was rebuilt, not just unblocked.

The whole branch chain moved into `_replacement_schema_contract_identity`, with a new
`SchemaContractIdentityCarrierError(TypeError)`, and three separate loud failures:

| Carrier | Before | After |
| --- | --- | --- |
| the public `SchemaContractIdentity` | first branch | unchanged |
| a Pydantic carrier (`ContentIdentity`) | second branch | unchanged |
| **a class with the identity's own field triple that is not that class** | fell through to `is_dataclass` and was replaced structurally, **silently** | `SchemaContractIdentityCarrierError`, naming the offending class and the module to converge on |
| **a dataclass that cannot hold `version`/`digest`** | `dataclasses.replace` raised a generic `TypeError: got an unexpected keyword argument` | `SchemaContractIdentityCarrierError`, naming the expected and found fields |
| **anything else** (`None`, a `str`, an `int`, a tuple, a plain dict) | `else: replacement_identity = identity` — **silently substituted the server-owned identity and discarded the carrier** | `SchemaContractIdentityCarrierError`, naming the carrier type |

The catch-all `else` was the loudest silence of the three: it accepted *any* object and replaced
it, so a carrier bug could not surface at all. It is now a raise.

The shadow-class branch is the direct re-arm against correction 12: if someone re-duplicates
`SchemaContractIdentity` tomorrow, the gate names it instead of handling it structurally. Mutation
**M2** proves that branch is load-bearing (RED 1/1), **M3** the catch-all (RED 5/5), **M4** the
missing-fields branch (RED 1/1).

## 3. Was the recording sink's success channel vacuous? YES — verified before building on it

The brief said to verify before building. I ran HEAD's sink directly rather than reading it:

```
HEAD sink public state:                      ['calls', 'error_classes']
any success-named channel:                   []
after a FAILED invoke -> calls: 1, error_classes: ['ValueError']
"no success fields" is vacuous:              True
calls.append precedes callback():            True
```

So the plan's "invalid output emits no success fields" had **nothing to assert**. Worse than
vacuous in one reading: if a reader took `calls` for the success channel, `calls == []` on failure
is *false*, so the only way such a test could pass was by asserting nothing meaningful.

**What I did:** added `AgentInvocationSuccess(identity, additional_fields)` and a `successes` list
to `RecordingAgentInvocationIdentitySink`, appended **only after** the callback returns, and added
`additional_fields` to the logging sink's **success** record only. The three channels are now
documented as distinct in the class docstring: `calls` is an attempt log, `successes` an outcome
channel, `error_classes` the other outcome.

Non-vacuity is measured, not assumed:

- **M12** moves the success append to *before* the callback → RED 6 named / 12 focused.
- **M13** deletes the success channel entirely → RED 19 named / 27 focused.
- **M15** adds `additional_fields` to the *error* record → RED 2/2.
- `test_recording_sink_records_the_attempt_before_and_the_success_after_the_callback` observes
  `(len(calls), len(successes))` *from inside the callback* — `(1, 0)` on the failing call and
  `(2, 0)` on the succeeding one — so the ordering is asserted directly, not inferred.

---

# What the runtime now does

- `_run_resolved` bridges the stored identity, guards a v1 contract against a non-empty overlay,
  then **composes** the role's schema from the persisted overlay through the one public
  `AgentSchemaRegistry`.
- The adapter is bound to `composed.model` — a strict (`extra="forbid"`) subclass of the canonical
  class named `…SchemaV{n}Overlay`, carrying `diagnostic_notes` when the overlay selects it.
- **Inside the sink callback**: provider conversion (`_supplied_output_keys`) then
  `validate_output`. Provider-failure conversion to `PinnedInvocationEndpointError` stays inside
  the callback and still precedes validation.
- The runtime consumes the returned `ValidatedAgentOutput`: `result.output` is
  `validated.canonical_output`, an instance of the **original canonical class**, and the frozen
  optional projection is copied into `AgentInvocationDiagnostics.additional_fields`.
- `AgentRuntime.__init__` builds `AgentSchemaRegistry` in place of `_SchemaContractRegistry`.
  Correction 13's concern is honoured: no third `_SchemaContractRegistry` instance exists, and the
  construction-time fail-closed check at that site is *strengthened* (v1 **and** v2 material for
  all seven roles). Pinned by
  `test_agent_runtime_construction_still_fails_closed_on_contract_material_drift`.
- `_SchemaContractRegistry` keeps its digest check and `identity_for` for the code-owned source and
  **loses its now-unreachable `resolve`**, so an unreachable second contract check cannot read as a
  live guard.

### Two deliberate design choices, stated

1. **`exclude_unset=True` at the adapter-conversion boundary is load-bearing, not tidiness.** The
   registry distinguishes an absent optional from an explicit `null` by raw key presence, so a
   field sitting at its declared `None` default must not arrive as an explicit null. **M8** REDs it.
2. **`AgentInvocationDiagnostics.__post_init__` freezes unconditionally.** The plan says "copies
   the same frozen mapping into diagnostics". I chose equality-plus-independent-freeze over object
   identity, because an unconditional freeze also protects any *other* construction site from
   handing diagnostics a live container — `freeze_json_containers` returns a new proxy, so identity
   and unconditional freezing cannot both hold. Both halves are separately tested
   (`…_is_immutable_and_deeply_frozen`, `…_freeze_a_mutable_mapping_from_any_construction_site`)
   and **M11** REDs them.

### The plan's typing question, answered

c9 (amended) says the `-> BaseModel` change is a design choice, not forced, because
`canonical_output` *is* a `BaseModel`. I retyped the Protocol and all **three** `invoke`
definitions to `ValidatedAgentOutput` anyway: the sinks need `additional_fields` to have a success
channel at all, and returning only `canonical_output` would have thrown the projection away before
it reached either sink. Three definitions, as amended — not four sites.

---

# REQUIRED DELIVERABLE — clause-to-mutation table

## Declared measurement scopes

| Column | Scope |
| --- | --- |
| **named** | the row's own pytest selectors, printed per row |
| **focused** | the six unit files this task changed, **264 tests**: `test_agent_schema_registry.py`, `test_agent_runtime.py`, `test_persisted_agent_runtime.py`, `test_agent_resolution_prompt.py`, `test_deck_level_spec_change.py`, `test_graph_configuration_bootstrap.py` |
| **matrix** (rows M9w, M18w only) | the plan's whole 17-file Task 7 unit matrix, **887 tests** |

Every row was measured on the **committed** tree at `87676a04f`. The whole table was re-run from
scratch after the second commit rather than mixing numbers from two HEADs — correction 32's bias
is exactly what a partial re-run would reintroduce.

## Blank count: **1** — and it is one clause, reported at two scopes

| # | Clause | Mutation | named | focused |
| --- | --- | --- | ---: | ---: |
| M1 | `SchemaContractIdentity` is converged to one class | re-add a shadow `SchemaContractIdentity` dataclass in `agent_runtime.py` | **2**/2 | **2**/264 |
| M2 | the gate NAMES a shadow identity class rather than handling it structurally | delete the `names == _CANONICAL_IDENTITY_FIELD_NAMES` raise | **1**/1 | **1**/264 |
| M3 | the gate REFUSES an unrecognised carrier rather than substituting | restore `return identity` in place of the final raise | **5**/5 | **5**/264 |
| M4 | the gate names a dataclass carrier that cannot hold the values | delete the `_STRUCTURAL_IDENTITY_FIELD_NAMES` raise | **1**/1 | **1**/264 |
| M5 | the adapter is bound to the COMPOSED schema | `schema=composed.model` → `composed.canonical_model` | **8**/8 | **51**/264 |
| M6 | `validate_output` projects onto the ORIGINAL canonical class | `composed.canonical_model.model_validate` → `composed.model.model_validate` | **11**/12 | **51**/264 |
| M7 | `validate_output` runs INSIDE the sink callback | callback returns `ValidatedAgentOutput(provider_output, {})` unvalidated | **10**/11 | **59**/264 |
| M8 | `exclude_unset` keeps an absent optional distinct from an explicit null | drop `exclude_unset=True` | **1**/4 | **1**/264 |
| **M9** | the adapter-conversion dump mode is `python`, not `json` | `mode="python"` → `mode="json"` | **0**/136 | **0**/264 |
| M10 | diagnostics carry the validated optional projection | `additional_fields=validated.additional_fields` → `{}` | **4**/5 | **4**/264 |
| M11 | diagnostics freeze their projection unconditionally | `freeze_json_containers(...)` → `dict(...)` | **2**/2 | **2**/264 |
| M12 | the success channel is appended AFTER the callback | move the append before the callback | **6**/6 | **12**/264 |
| M13 | the recording sink HAS a success channel at all | delete the append | **19**/19 | **27**/264 |
| M14 | the logging sink logs the optional projection on success | drop `additional_fields` from the success `extra` | **4**/4 | **5**/264 |
| M15 | the logging sink's ERROR record carries no success field | add `additional_fields` to the error `extra` | **2**/2 | **2**/264 |
| M16 | a v1 schema contract still requires an empty overlay | delete the v1 guard | **1**/1 | **1**/264 |
| M17 | an unresolvable contract identity maps to `schema_contract_unavailable` | collapse the overlay handler to `invalid_persisted_definition` | **2**/2 | **2**/264 |
| M18x | **MIS-AIMED, reported** — intended the overlay fallback, hit the GENERIC fallback | generic handler's code → `schema_contract_unavailable` | **0**/1 | **1**/264 |
| M18b | **RE-AIMED**: an invalid persisted OVERLAY maps to `invalid_persisted_definition` | the `SchemaOverlayValidationError` fallback's code | **1**/1 | **1**/264 |
| M19 | the identity bridge takes the role from the resolved definition | hardcode `"architect"` in the bridge call | **6**/8 | **59**/264 |
| M20 | an undeclared or unselected top-level output key is rejected | `undeclared` list forced empty | **2**/5 | **3**/264 |
| M21 | **c11 radius re-measurement** — the compatibility loader's hardcoded v1 overlay literal | `additional_optional_fields: []` → `[{"not": "a string"}]` | **30**/107 | **31**/264 |
| **M9w** | WIDENED: the dump mode, at matrix scope | as M9 | **0**/887 | **0**/264 |
| M18w | WIDENED: the GENERIC fallback's code, at matrix scope | as M18x | **1**/887 | **1**/264 |

### The mis-aim, reported in full (correction 27)

**M18x measured RED 0 named.** I intended to mutate the `SchemaOverlayValidationError` handler's
fallback and instead anchored on the *generic* `(ValidationError, ValueError, TypeError)` handler.
The anchor count was 1, so the harness had nothing to complain about — this is the failure mode
the anchor rule does **not** catch: a unique anchor on the wrong line.

I suspected my instrument before the code, and probed it directly: the two suites that assert
`invalid_persisted_definition` through the runtime both reach it via the **`PromptAssemblyRejected`**
clause, confirmed by inspecting `__cause__` on a live run
(`code: invalid_persisted_definition | __cause__ type: PromptAssemblyRejected`). So the zero was
real and my aim was the problem. **M18b** is the re-aim: RED 1/1 named, 1/264 focused — the clause
*is* guarded.

And the mis-aim paid for itself. It found that the generic fallback was reached by **no test at
either scope** — a pre-existing gap in code I only added a clause above. `test_a_role_mismatch_
between_release_and_content_is_invalid_persisted_definition` now pins it, which is why **M18w**
reads RED 1/887 rather than 0.

### The one blank row, stated at its declared scopes only

**M9/M9w — swapping `_supplied_output_keys`' dump mode REDs nothing at either measured scope:
0 of 264 in the focused suite and 0 of 887 in the whole Task 7 unit matrix.**

Per correction 31 the only honest statements are "free within these scopes" or "widen and measure
again". I widened once, to the matrix, and it is still free there. **I am not claiming the gate
cannot detect it.**

I then probed the *mechanism* instead of generalising the zero. Walking every field annotation of
all **13 models** reachable from the seven canonical output schemas found **zero** field types the
two modes serialise differently — no `Decimal`, `datetime`, `date`, `time`, `timedelta`, `UUID`,
`bytes`, `Enum`, `set`, `frozenset` or tuple-typed leaf anywhere. So the two modes are equivalent
*for these schemas*, which is a **precondition, not a guarantee**.

That precondition is now itself asserted:
`test_no_canonical_schema_carries_a_dump_mode_divergent_field_type`. The mutation stays blank —
correctly, it tests nothing about the mode — but adding such a field to any output schema now REDs
a test instead of silently making the mode load-bearing. This is deliberately **not** the same
decision as correction 33's `canonical_payload` mode, which I did not touch: that one guards three
fail-closed guarantees and is not a free token.

> An aim check is built into that guard: it asserts `len(walked) >= 13`, so a walker that silently
> stopped at the roots would fail rather than report a comfortable zero.

## Measured radius near `agent_runtime.py:452` against the expected 30

The brief's expectation: a discriminating sabotage of the compatibility loader's hardcoded v1
overlay literal REDs **20 / 7 / 2 / 1 = 30 across four files**. The literal now sits at
`agent_runtime.py:467-468`.

**Row M21 reproduces it exactly: 30 RED across the same four files, on the Task-3 tree.**

Separately, **my own change's** radius across that same neighbourhood, measured before repair:

| File | My change's RED | c11's amended figure |
| --- | ---: | ---: |
| `tests/unit/test_agent_runtime.py` | 18 | 20 |
| `tests/unit/test_agent_resolution_prompt.py` | **7** | **7** |
| `tests/unit/test_deck_level_spec_change.py` | **2** | **2** |
| `tests/unit/test_graph_configuration_bootstrap.py` | **1** | **1** |
| four-file total | **28** | **30** |
| `tests/unit/test_persisted_agent_runtime.py` (outside c11's list) | 34 | — |
| `tests/integration/test_conversation_pin_acceptance_postgres.py` | 1 | — |

Three of the four files match byte-for-byte; `test_agent_runtime.py` is 18 against 20, which is
expected rather than troubling — c11's sabotage breaks the *literal*, mine changes the runtime's
whole composition path, so the two are different mutations that happen to share a neighbourhood.
**This is the expected radius, not a second defect**, and M21 confirms the literal's own radius is
still exactly 30.

One cause, one repair: every one of the 63 was an adapter double returning
`schema.model_construct()` (an empty shell that cannot survive `validate_output`), except the
acceptance suite's `assert isinstance(output, schema)`, which cannot hold once the bound schema is
a strict *subclass* of the output's class.

---

# Gates

| Gate | Result | Baseline | Reconciliation |
| --- | --- | --- | --- |
| Focused (the six changed unit files) | **264 passed, 0 failed, 0 skipped** | — | — |
| Task 7 unit matrix (17 files, verbatim) | **887 passed, 0 failed, 0 skipped** | 847 | 847 + 40 new |
| Full `tests/unit` | **14 failed, 5581 passed, 110 skipped, 136 warnings** | 14 / 5541 / 110 / 136 | 5541 + 40 new, warnings unchanged |
| PostgreSQL, 6 baseline files, separate URL-prefixed invocations | **7 · 1 · 2 · 2 · 7 · 15 = 34 passed, 0 failed, 0 skipped** | 34, zero skips | identical |
| PostgreSQL, `test_conversation_pin_acceptance_postgres.py` (c23) | **1 passed, 0 skipped** | 1 | identical |
| `ruff check` on all ten changed files | **zero NEW findings** — see below | — | — |
| `test ! -e .venv` before and after every gate | passed every time | — | — |
| frontend | **not run** — correction 24 still outstanding | — | — |

**`ruff check`, stated precisely rather than as "clean".** `ruff check src tests` reports 2604
findings on this repo and always has; scoped to my ten changed files it reports **28**, and the
*same* 28 appear when the identical file list is checked from `git show HEAD:` copies of the
pre-change versions. Diffing the two normalised finding sets gives **zero new findings**. All 28
are pre-existing `F811 graph_env` redefinitions in `test_deck_level_spec_change.py`, untouched by
my edit at a different line.

**`ruff format --check` is NOT clean and I am not claiming it is.** It reports **6 of my 7
originally-checked files would be reformatted**. Per the Task-2 re-review's F7 this is harmless —
`ruff format` is not a repo gate, the configured gate is `[tool.ruff.lint] select = ["E","F","I","N","W"]`
at line-length 100 and it passes — but the Task-2 report claimed that row clean when it was not,
and the brief named that as the same species of over-broad claim. So: lint gate green, format
gate not a gate and not clean.

Test-count reconciliation, collected not assumed: `test_agent_schema_registry.py` 43 -> **52**
(+9), `test_agent_runtime.py` 30 -> **31** (+1), `test_persisted_agent_runtime.py` 75 -> **105**
(+30). Total **+40**, which is exactly 5541 -> 5581 and 847 -> 887.

**Full-suite failure causes verified by traceback, not inferred from counts.** The measured set is
exactly the inherited fourteen, in the same six files with the split **1 / 2 / 2 / 3 / 1 / 5**,
with **zero failures outside it**:

- **9** × `ConversationGraphReleaseIntegrityError: no active Graph Release` at
  `src/services/conversation_pins.py:83`
- **3** × `AttributeError: '_FakeSession' object has no attribute 'execute'` at
  `src/services/conversation_pins.py:79`
- **2** × plain assertions in `test_deploy_autoscaling.py`, at `:124`
  (`assert 'provisioned' == 'autoscaling'`) and `:152`
  (`Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`)

Twelve of the fourteen funnel through `_require_active_graph_release` — one repair, not twelve.

---

# Files changed, and the three replacements beyond the plan's Files block

The plan's Task-3 Files block names `agent_runtime.py`, `agent_runtime_identity.py`,
`test_agent_runtime.py`, `test_persisted_agent_runtime.py`, and "extend
`test_agent_schema_registry.py`". Ten files changed. Recorded here and as correction 34, per the
plan's own "Record replacements in corrections" step:

| File | In the Files block? | Why |
| --- | --- | --- |
| `src/services/agent_runtime.py` | yes | composition, projection, diagnostics, convergence |
| `src/services/agent_runtime_identity.py` | yes | the sink success channel and retyping |
| `tests/unit/test_agent_runtime.py` | yes | — |
| `tests/unit/test_persisted_agent_runtime.py` | yes | — |
| `tests/unit/test_agent_schema_registry.py` | yes (extend) | convergence + gate tests |
| `src/services/agent_schema_registry.py` | **no** | the `:556` gate — **named explicitly in the brief's three items**, so authorized there rather than by the Files block |
| `tests/unit/test_agent_resolution_prompt.py` | **no** | 7 RED; c11's amended radius names this file and this exact count |
| `tests/unit/test_deck_level_spec_change.py` | **no** | 2 RED; c11's amended radius, 2 |
| `tests/unit/test_graph_configuration_bootstrap.py` | **no** | 1 RED; c11's amended radius, 1 |
| `tests/integration/test_conversation_pin_acceptance_postgres.py` | **no** | 1 RED; c23's matrix addition |

**Why I did not ask first.** The brief's ask-gate is specific: *"Ask me before starting if the
**convergence** would require touching a file outside your plan's Files block."* The convergence
did not — it is contained in `agent_runtime.py`, verified by a repo-wide grep before I started.
The four test-file replacements are not the convergence; they are the cause baseline rule applied
("anything outside that inherited set is yours"), each one a single adapter double that the
composition change necessarily invalidated, each one predicted by name and count in the c11
radius the brief handed me. Each change is mechanical: return a valid instance of the schema the
adapter was handed, instead of an empty `model_construct()` shell. **No production behaviour is
changed in any of the four.**

I am flagging this prominently because it is the widest scope decision I made without asking, and
a reviewer may legitimately disagree with it.

---

# Concerns

1. **Half the tests were written after the implementation, not RED-first.** The registry half was
   genuine TDD: **9 RED measured** before any implementation, then GREEN. The runtime and sink
   tests were written *after* the implementation existed, so I cannot claim a pre-implementation
   RED for them. They are proved by the mutation table instead — every runtime/sink clause has a
   measured RED at both declared scopes — which is the epic's own standard, but it is not the same
   evidence and should not be read as if it were.
2. **The production logging sink now emits one model-derived field where it previously emitted
   none.** `LoggingAgentInvocationIdentitySink` adds `additional_fields` to its success record.
   This is plan-mandated (c9 consequence 3; the plan's "successful … logging traces" clause) and
   the values are allowlisted by construction — only `composed.declared_optional_names` can
   appear, capped at 8 items × 280 characters. But it is a real change to what reaches application
   logs, and **the adjacent test is named
   `test_runtime_logging_sink_does_not_log_prompt_payload_or_model_output`** — a name that is now
   *broader* than the guarantee it holds. Rather than rename it and lose the history, I added an
   explicit in-test disclosure asserting that exactly one model-derived key is present and that it
   is the empty mapping under a v1 overlay. A reviewer may prefer the rename, or may want the
   logging of diagnostic notes dropped entirely.
3. **`agent_runtime.py:87-96` still holds a third copy of the seven v1 digests**
   (`_SCHEMA_CONTRACT_DIGESTS`), alongside `agent_schema_registry._V1_DIGESTS` and the corrections
   table. Correction 13 warned about a third *registry instance*, not a third *table*, and
   converging the table means touching `CodeOwnedAgentDefinitionSource`'s fail-closed check, which
   is outside the brief's three items. Left deliberately, recorded as a forward item.
4. **The dump-mode blank is a precondition guard, not a mutation.** I closed it the only honest way
   I could find, but a reviewer wanting a mutation-backed row for that clause will not get one from
   me, and I would rather say so than manufacture a row.
5. **`VALID_OUTPUT_VALUES` now appears in four test modules** (three unit, one inline in bootstrap)
   as fixture data. I chose duplication over a new shared helper module to avoid widening the file
   set further, but it is five hand-maintained copies of the same small map and a reviewer may
   prefer one shared fixture.
6. **Frontend baseline still outstanding** under correction 24. No frontend command was run.
7. `AgentInvocationSuccess` is deliberately **not** re-exported from `agent_runtime` — the other
   four sink names are, but re-exporting an otherwise-unused name trips `F401`, and nothing imports
   it that way today. A future consumer will need `from src.services.agent_runtime_identity import
   AgentInvocationSuccess`.

# Hygiene

- Mutation driver at `/tmp/t3-mutate/driver.py`, **outside** the repository. It **refuses** to
  mutate on a stale backup or a dirty tree, asserts every anchor count and hard-fails on any other
  number, and asserts the triple check after every restore. `git status --porcelain` is empty at
  the end, so no probe file contaminated any count.
- **Correction 32 was exercised for real, not just implemented.** After the second commit the
  driver refused to run: `REFUSING: stale backup. backup HEAD cca068af3… != working HEAD
  87676a04f…`. Backups were re-taken and **the entire 24-row table was re-run from scratch** rather
  than splicing new rows onto old numbers.
- Every restore was from `cp`, never `git checkout <commit> -- <paths>`.
- No database created, dropped, migrated or altered by hand; PostgreSQL fixtures owned their own
  throwaway databases and `ai_slide_generator` was untouched.

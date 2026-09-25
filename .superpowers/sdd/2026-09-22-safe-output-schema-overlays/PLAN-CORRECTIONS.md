# PLAN-CORRECTIONS.md — this file overrides `docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md` wherever they differ.

Pre-Task-1 authority is `TASK1_BASE` = `8c72a5a9192095e1b77986f6a4b63a10bcd2acb6`, which contains reviewed #260 head `29e03411487476383b34101b7b34513dbb917f26` as an ancestor. The later Task-2 integration refresh remains mandatory and will extend this file rather than replace it.

## Code inventory and immutable v1 evidence

The seven-role order is `architect`, `data_analyst`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`, `deck_reviewer`. `OUTPUT_SCHEMAS` is the schema source but its dictionary insertion order places `fixer` before `build_reviewer`; registry ordering, issue ordering, descriptors, and identity tables must use the seven-role order above rather than inheriting that insertion order.

| Role | v1 schema version | Frozen v1 digest | Packaged v1 content hash |
| --- | ---: | --- | --- |
| architect | 1 | `a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd` | `e77e69b18cb9d843a1754dab65a79941ede8cfa7c8266292580ff7566d1dcb33` |
| data_analyst | 1 | `610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281` | `1ffb1fb3f31a20b9424007eefdf918620f1058386a2ba81bfd22347510ce6803` |
| builder | 1 | `fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387` | `1549a4231b3a4a6221842f3eca6699097199b28d8283b8995af7c90b406fe5c4` |
| build_reviewer | 1 | `50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d` | `1a895f4bee426041088635f7fa182200827db14ab35a229def6f8932d1516b18` |
| fixer | 1 | `7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297` | `fb9dc5a2bddb783ff2fd2eec54a3809e38cef2d0bc683daec3568005b8643c7b` |
| fix_reviewer | 1 | `31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df` | `e6d4a4801abc7b654f262f905f4b198d4c134d29801d2ecd09ed09cff2ec164f` |
| deck_reviewer | 1 | `56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467` | `8c876db55cddbaa2f9015321117e36adb5b63fb7c47dbb067a432d04c30cf54e` |

All seven packaged v1 overlays serialize as `field_overrides={}` plus `additional_optional_fields=[]`. Task 1 must retain these identities literally and define an empty v1 optional catalog. The v2 digest material must include the canonical v1 material plus registry grammar, `extra="forbid"`, raw-key policy, and all role-specific descriptor metadata; calculate once, freeze literal SHA-256 values, and test that changing material without changing the literal fails closed.

## Per-task internal consistency scan

| Task | Declared files/code/tests against current owners | Finding / ruling |
| --- | --- | --- |
| 0 | Ignored SDD evidence only; checks #260 ancestry, files, identities, tests, interpreter. | Pre-Task-1 phase is complete. Integration refresh remains pending until reviewed #261/#263/#265 are locally present. |
| 1 | Creates only two service modules and one unit test; consumes `src/domain/skill_io.py::OUTPUT_SCHEMAS`. | New paths are collision-free. Ruling: do not import manifest/runtime and do not edit their private registries. Use the explicit seven-role order above. Explicitly supplied optional keys—not a defaulted `None`—govern absent versus explicit-null retention. Cost if wrong: role/issue order drifts or absent values are falsely traced as null. |
| 2 | Replaces the manifest's current generic `SchemaOverlay` carrier with the Task-1 typed grammar while preserving v1 bytes/hashes and independent assembly identity. | Current carrier already freezes/thaws arbitrary JSON. Ruling: Task 2 must import/re-export the Task-1 type and prove old v1 dumps/hashes byte-identical before adding v2; it must not leave two competing `SchemaOverlay` definitions. Cost if wrong: persisted v1 hashes become unreadable or callers resolve different overlay classes. |
| 3 | Extends runtime, identity sink, persisted loader, registry tests after #261 integration. | `agent_runtime_identity.py` and persisted runtime owners are absent on this pre-integration branch by design. Ruling: do not infer their final signatures now; Task 0 phase B must record them from the concrete integration base before dispatch. Cost if wrong: Task 3 creates a parallel sink or breaks exact-ID execution. |
| 4 | Extends the single #263/#265 locked writer, mapper, validators, audit and concurrency tests. | Final shared writer/validator tuple is not present on this base. Ruling: Task 0 phase B must identify the one landed owner/order; no Task-1 code may anticipate it. Cost if wrong: duplicate transaction/writer or validation order drift. |
| 5 | Extends the landed aggregate candidate DTO/route and exact response envelopes. | Final #263/#265 route/schema owners are not present on this base. Ruling: retain only `candidate.schema_overlay`, `invalid_draft`, exact ordered issues, auth-before-body, and #263 stale family after re-probe. Cost if wrong: incompatible wire convention or sensitive body parsing before auth. |
| 6 | Extends the single #263/#265 client/reducer/controller and adds one protected editor. | Final frontend state machine/gate/conflict owners are not present on this base. Ruling: re-probe after integration and add no second request counter, pending gate, reducer, autosave, or conflict model. Cost if wrong: stale responses or upgrades overwrite newer edits. |
| 7 | Runs the named backend/PostgreSQL/frontend matrix and reviews only `INTEGRATION_BASE..HEAD`. | Several final files depend on #261/#263/#265. Ruling: phase B may add renamed replacements but may not drop the three named #261 PostgreSQL suites or accept skips. Cost if wrong: broad green counts conceal missing no-fallback/concurrency coverage. |

## Shared-file and producer/consumer scan

| Tasks | Producer → consumer / shared seam | Finding / required order |
| --- | --- | --- |
| 0 → 1 | Corrected identities, collision inventory, and cause baseline → isolated registry kernel. | Task 1 receives this file and `preflight-260.md`; no implementation before these artifacts. |
| 1 → 2 | `SchemaOverlay`, identities, descriptors, registry → manifest typed carrier and retained v1/v2 identities. | Sequential. Task 2 re-exports one type rather than duplicating it. |
| 1 → 3 | composed schemas and `ValidatedAgentOutput` → runtime callback, diagnostics, sink. | Sequential after local integration; runtime uses canonical output plus frozen explicitly supplied optional values. |
| 1 → 4 | overlay validation and v2 upgrade → shared locked writer and ordered validator tuple. | Sequential; registry is pure/deep and the writer owns persistence/locking. |
| 1 → 5 | descriptor/issue vocabulary → aggregate DTO and route response. | Sequential; routes never accept contract identities or descriptor definitions from clients. |
| 1 → 6 | descriptors/closed catalog → read-only protected UI and `diagnostic_notes` picker. | Sequential; client displays code-owned metadata but sends only overlay selections/guidance. |
| 2 → 3 | retained schema identity/typed persisted overlay → exact-ID runtime resolution. | Sequential; schema and assembly identities remain independent. |
| 2 → 4 | typed `DefinitionContent` and hash material → locked v2 upgrade/save. | Sequential; the writer uses the one canonical mapper/hash path. |
| 2 → 5 | aggregate content serialization → strict wire DTO. | Sequential; storage identity remains server-owned and is never an editable request field. |
| 2 → 7 | v1 byte/hash preservation and v2 resolution → final reproducibility gate. | Final review must compare both identities and serialized material, not counts. |
| 3 → 4 | runtime validator/registry semantics → persisted candidate acceptance and upgrade. | Task 4 validates before mutation; runtime still fails closed if invalid state somehow exists. |
| 3 → 7 | canonical projection, diagnostics and sink ordering → whole-slice runtime/trace review. | Final reviewer receives a sink outcome table and no-fallback evidence. |
| 4 → 5 | one writer/upgrade, ordered issues, coherent stale snapshot → API route. | Sequential same transaction boundary; route only maps domain outcomes. |
| 4 → 6 | save/upgrade/stale semantics → client reducer/gate. | Backend contract must be stable before UI implementation. |
| 4 → 7 | same-content audit, invalid no-write, concurrency loser → rollback/no-write ruling. | PostgreSQL evidence must assert exact identities/content/actor/locks/PIDs and zero skips. |
| 5 → 6 | strict aggregate request/response parsers → typed client and editor. | Sequential; ordinary save candidate and upgrade null candidate remain distinct. |
| 5 → 7 | direct auth/validation/stale contract → whole-slice route review. | Final gate checks direct API protection and exact ordered envelopes. |
| 6 → 7 | one state machine/editor/browser path → final frontend/E2E verification. | Playwright and unit/type/lint gates use checked-in dependencies only. |

## Pre-Task-1 rulings

- Ruling: use the explicit seven-role order above rather than `OUTPUT_SCHEMAS` insertion order — the manifest/runtime order is the product contract — cost if wrong is unstable descriptors and issue ordering.
- Ruling: Task 1 may coexist temporarily with the private `_SchemaContractRegistry` and manifest `SchemaOverlay` because it changes only new files; Tasks 2 and 3 must converge to the one public registry/type after integration — cost if wrong is duplicate authorities escaping into production.
- Ruling: distinguish an absent optional output from explicit null using raw key presence before/default-aware validation; retain only selected and explicitly supplied optional fields — cost if wrong is trace/diagnostic ambiguity that violates the spec's `{}` versus null contract.
- Ruling: no final #261/#263/#265 signature or file claim is authoritative until Task 0 phase B re-probes the concrete local `INTEGRATION_BASE` — cost if wrong is implementing against stale plan-era interfaces.

No other pre-Task-1 contradiction, file collision, impossible test, or review-rubric conflict was found. Cause baseline details are in `reports/preflight-260.md`.

## Pre-rebase Task-1 history audit — 2026-09-23

Current pre-rebase authority is `ac69f62b6792d812f99eef53f725085bc90c61a6`.
The complete linear source interval from
`a94c907d2db75e53743289651443fe9583bfa8f7..ac69f62b6792d812f99eef53f725085bc90c61a6`
contains nine #264 plan-history commits followed by nine Task-1
implementation/fix/review/finalization commits; it contains no merge commit.
The reviewed #261 head `876f2a91f1df4b4b03276a7258934a53954eb637`, #263
head `1d706e21b92aad68314da2e79bb4d1d5626663b7`, and #265 approved-plan head
`3a3583c3061456d9292c43f9a1b45dffffca52be` are not ancestors of this head.

Ruling: replay the full `a94c907d2..ac69f62b6` interval only after the Task-0
phase-B local-integration gate, and preserve every ignored artifact enumerated
with SHA-256 in `task-1-evidence-manifest.txt`.  The Task-1 source/proof chain
ends in `1095ac202` (round-4 approval) and `ac69f62b6` (terminal ledger
completion).  `progress.md` repeats the round-3/round-4 summary after its
completion line in reverse-looking order; Git and the review artifacts establish
the authoritative order as `09368a3d9` → `2500b50f4` → `77223ae71` →
`1095ac202` → `ac69f62b6`.  Treat those trailing ledger lines as duplicated
historical summaries, not later work.  A future Phase-B ledger addendum must
record this correction rather than rewrite the original evidence.

## Standing correction — frozen models holding mutable containers (carried forward from #260)

Binding for every remaining #264 task (Task 0 phase B and Tasks 2–7), and recorded here by
the #258 controller on 2026-09-23 as a standing rule rather than a per-task finding.

Any frozen model or dataclass that holds a mutable container must freeze that container
recursively, using #260's `MappingProxyType` pattern — see `src/services/graph_definition_manifest.py:71`
and `src/services/graph_configuration_draft.py:399` on the integration head. Task 1 already
honours this at seven sites in `src/services/agent_schema_registry.py` (`:49`, `:61`, `:115`,
`:126`, `:289`, `:292`, `:295`); every new frozen structure in Tasks 2–7 must do the same.

Two constraints Task 1's four fix rounds established the hard way, which this correction
exists to stop rediscovering:

1. Freezing must not be implemented by replacing or mutating a Pydantic model's private
   state. Task 1's rounds 1 through 3 each tried a variant of that and each broke something
   different — serialization, validation, composition, then `model_copy(update=...)`. The
   accepted shape is a protected type boundary, landed at `77223ae71`.
2. Pydantic copy semantics must survive freezing: shallow-copy identity, deep copy, copied
   field-set, and trusted unvalidated `model_copy(update=...)` all have to keep working.
   `agent_schema_registry.py:586` is the live consumer (`content.model_copy(update=updates)`),
   so a regression there is a production break, not a test-only one.

Cost if wrong: the same four-round loop repeats on a later task, and a frozen structure that
leaks a mutable container lets a caller mutate a schema contract that identity and hashing
assume immutable.

Note for phase B, UPDATED 2026-09-24: the rebase is **done**. This branch was 49 commits
behind `795262c16`, then 77 behind after #265 integrated; it is now rebased onto the new
integration head `3ed8f9b6a` and is 0 behind. Its recorded predecessor SHAs are still stale
and must be re-derived. The design rule above is unaffected by the rebase, but every line
number in it must be re-probed.

# ============================================================================
# Task 0 phase B — integrated-code re-probe. 2026-09-24.
# `INTEGRATION_BASE` = `3ed8f9b6a` (merge of #265 into `feat/langgraph-core`).
# Branch HEAD re-probed = `5bb2b36a2583bf4fb215165f8298d031e01a6d28`.
# Import provenance proved in-worktree: `src` and `databricks_tellr` both resolve
# under `.worktrees/issue-264-schema-overlay`; Python 3.11.0; databricks-sdk 0.112.0;
# `.venv` absent before and after every gate.
# Every correction below is a re-probe of the concrete integration base and
# supersedes the corresponding plan-era or corrections-era claim.
# ============================================================================

## Correction 8 — triple-check deviation at dispatch (process, not code)

`git status --porcelain` was **not** empty when phase B started: it carried
` M .superpowers/sdd/2026-09-22-safe-output-schema-overlays/progress.md`, the controller's
own uncommitted rebase addendum (its `## REBASED onto the new integration head` block).
`git diff --cached` was empty and HEAD was the expected `5bb2b36a2`, so this was an
uncommitted artefact edit, not a source-tree divergence — the inverse of the
index-masking-a-dirty-tree failure this epic was bitten by three times. Recorded rather
than silently committed away. Phase B carries it forward in its own ledger commit.
Ruling: the triple check is satisfied for **source**; treat the porcelain line as a known
artefact-only deviation. Cost if ignored: a later task reads a ledger that appears
committed but is not, and re-derives the rebase evidence.

## Correction 9 — CONFIRMED: `src/services/agent_runtime_identity.py` and its exact signatures

Discharges the correction-3 deferral. The file is **present** at `INTEGRATION_BASE` and
carries exactly four public names, each defined **once repo-wide**:

| Name | Kind | Exact signature / fields |
| --- | --- | --- |
| `AgentInvocationIdentity` | `@dataclass(frozen=True)`, `:13` | `graph_version: int`, `graph_release_id: int`, `agent_key: str`, `agent_definition_revision_id: int`, `content_hash: str` |
| `AgentInvocationIdentitySink` | `Protocol`, `:21` | `invoke(self, identity: AgentInvocationIdentity, callback: Callable[[], BaseModel]) -> BaseModel` |
| `RecordingAgentInvocationIdentitySink` | class, `:29` | `__init__(self) -> None`; state `calls: list[AgentInvocationIdentity]`, `error_classes: list[str]`; `invoke(...) -> BaseModel` |
| `LoggingAgentInvocationIdentitySink` | class, `:47` | `__init__(self, *, logger: logging.Logger) -> None`; `invoke(...) -> BaseModel` |

`src/services/agent_runtime.py:45-50` imports all four and re-exports them by plain import
(there is **no** `__all__` in `agent_runtime.py`). `tests/unit/test_persisted_agent_runtime.py`
imports them from `src.services.agent_runtime`, not from the identity module — both spellings
resolve to the same objects. **There is exactly one sink family; no parallel sink exists.**

Three consequences Task 3 must honour:

1. The Protocol and all three `invoke` implementations are typed `Callable[[], BaseModel] -> BaseModel`.
   `ValidatedAgentOutput` is a **frozen dataclass, not a `BaseModel`** (`agent_schema_types.py:381`).
   So the plan's "its callback returns `ValidatedAgentOutput`" is a **breaking signature change at
   four sites**, not an additive one. Task 3 must retype the Protocol and all three classes together.
2. `RecordingAgentInvocationIdentitySink` has **no success-field concept at all** today: `invoke`
   appends the identity to `self.calls` *before* calling the callback, so `calls` records
   *attempts*, not successes, and only `error_classes` distinguishes outcome. The plan's
   requirement that invalid output "is observed by both sinks as an error and emits no success
   fields" therefore requires Task 3 to **add** a success channel to the recording sink. The plan
   presents this as preserving behaviour; it is new behaviour. Cost if missed: a test asserting
   "no success fields" passes vacuously because no success field exists.
3. `LoggingAgentInvocationIdentitySink` spreads `**identity.__dict__` into `extra=` and adds only
   `outcome` and `error_class`. Allowlisted `additional_fields` must be added there, and
   `identity.__dict__` works only while `AgentInvocationIdentity` stays a non-slots dataclass.

## Correction 10 — CORRECTED: the persisted-runtime owner is `persisted_graph_release.py`

`src/services/persisted_agent_runtime.py` is **absent** at `INTEGRATION_BASE` and at HEAD, while
`tests/unit/test_persisted_agent_runtime.py` **is** present. The plan's Task-3 file list names the
test but never names a `persisted_agent_runtime.py` module, so there is no missing file — but any
reader inferring a module from the test name is wrong. The real persisted-runtime owner is
**`src/services/persisted_graph_release.py`**:

| Symbol | Line | Exact signature |
| --- | ---: | --- |
| `ResolvedDefinition` | 75 | `@dataclass(frozen=True)`: `graph_version: int`, `graph_release_id: int`, `agent_key: str`, `agent_definition_revision_id: int`, `content_hash: str`, `content: DefinitionContent` |
| `ResolvedDefinitionLoader` | 84 | `Protocol`: `resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition` |
| `PersistedGraphReleaseLoader` | 91 | `__init__(self, *, session_factory: sessionmaker)`; `resolve(graph_release_id, agent_key) -> ResolvedDefinition` |
| error hierarchy | 27-70 | `PersistedRuntimeError` ← `GraphReleaseNotFoundError`, `GraphReleaseIncompleteError`, `PersistedConfigurationUnavailableError(code=...)`, `PinnedInvocationEndpointError` |

`AgentRuntime.run(self, agent_key: str, graph_release_id: int, payload: dict[str, Any],
assembly_context: AgentAssemblyContext) -> AgentInvocationResult` at `agent_runtime.py:512`
— the plan's **four-argument signature claim is CONFIRMED verbatim**. It resolves through
`self._persisted_release_loader.resolve(graph_release_id, agent_key)` at `:520`.
`AgentRuntime.__init__` is keyword-only: `persisted_release_loader`, `model_adapter`, `identity_sink`.

## Correction 11 — CONFIRMED: the compatibility loader is test-only, and it hardcodes the v1 overlay

The plan's "A compatibility loader is test-only" is **CONFIRMED**, with a nuance worth recording:
`CompatibilityResolvedDefinitionLoader` (`agent_runtime.py:438`) is production-resident code, and
is instantiated inside production module code at `agent_runtime.py:502` — but only inside the
`AgentRuntime.compatibility()` classmethod, whose callers are **exclusively tests**
(`test_agent_runtime.py` ×8, `test_graph_configuration_bootstrap.py`, `test_deck_level_spec_change.py`;
nothing in `src/api`, `src/main.py`, `src/core`). It also self-gates: `resolve` raises
`ValueError("compatibility runtime requires graph release 1")` for any
`graph_release_id != TEST_COMPATIBILITY_GRAPH_RELEASE_ID`.

The production runtime is `get_agent_runtime()` at `agent_runtime.py:633`, `@lru_cache(maxsize=1)`,
wiring `PersistedGraphReleaseLoader` + `DatabricksModelAdapter` + **`LoggingAgentInvocationIdentitySink`**.
So the production sink is the logging one and `RecordingAgentInvocationIdentitySink` is the
compatibility/test default. Task 3's "both sinks" work therefore spans one production and one test sink.

**Task-3 touchpoint the plan does not name:** `CompatibilityResolvedDefinitionLoader.resolve`
hardcodes a literal v1 overlay — `"schema_overlay": {"field_overrides": {}, "additional_optional_fields": []}`
— and a literal `"schema_contract": {"version": ..., "digest": ...}`, then validates them through
`DefinitionContent.model_validate`. Any Task-2 change to the overlay grammar must keep this literal
valid or eight `test_agent_runtime.py` tests RED. Cost if missed: Task 2 is blamed for a Task-3 break.

## Correction 12 — NEW DEFECT: `SchemaContractIdentity` is defined twice

`agent_runtime.py:126` and `agent_schema_types.py:367` **both** define a frozen
`SchemaContractIdentity` with the identical field triple `agent_key: str`, `version: int`,
`digest: str`. The plan names the competing-`SchemaOverlay` problem (Task 2) but **never names this
second collision**, and corrections line 60 only anticipated it generically.

Also duplicated in spirit: the freeze helper. `graph_definition_manifest.py:73`
`_freeze_json_containers` and `agent_schema_types.py`'s `freeze_json_containers` both implement the
#260 `MappingProxyType` pattern over JSON containers.

Ruling: Task 3 (not Task 2) owns converging `SchemaContractIdentity` to the one public type, because
`agent_runtime.py` is a Task-3 file and `agent_schema_types.py` is the declared public home. Task 2
converges `SchemaOverlay` and should converge the freeze helper at the same time rather than leave a
third copy. Cost if wrong: two identity classes that compare unequal across an `isinstance` or `==`
boundary while looking identical in a traceback — and `_SchemaContractRegistry` already builds the
`agent_runtime` one at `:291`.

## Correction 13 — CONFIRMED: the retained v1 digests, and where the *third* digest table lives

`agent_runtime.py:87-96` holds `_SCHEMA_CONTRACT_VERSION = 1` and `_SCHEMA_CONTRACT_DIGESTS`, whose
seven values are **byte-identical to this file's "Frozen v1 digest" column** for all seven roles.
So the pre-Task-1 identity table was derived from landed code and remains correct at
`INTEGRATION_BASE`. The probe is self-proving: `_SchemaContractRegistry.__init__`
(`agent_runtime.py:276-296`) recomputes `_canonical_digest(_schema_contract_material(...))` for every
role at construction and raises `RuntimeContractIdentityError` on any mismatch — importing
`src.services.agent_runtime` succeeded, so the computed material still equals the frozen literals.
Had any v1 material drifted, import itself would have raised.

v1 material composition (`_schema_contract_material`, `:200`) is exactly:
`agent_key`, `qualified_name`, `json_schema` (`mode="validation"`), `model_configurations`
(`_schema_configuration_material`), `validators` (`_schema_validator_material`).
Task 1's v2 material must **extend** this, and Task 2's "prove v1 bytes unchanged" compares against it.

`_SchemaContractRegistry` is instantiated **twice**: `CodeOwnedAgentDefinitionSource.__init__`
(`:320`, as `self._schemas`) and `AgentRuntime.__init__` (`:490`, as `self._schema_contracts`).
Both re-validate all seven digests. Ruling: Task 3 must add **no third instance** and must not
convert either to a module-level singleton without accounting for the validation-on-construction
side effect. Cost if wrong: the fail-closed identity check stops running at one of the two sites.

## Correction 14 — CONFIRMED: seven-role order, and the one ordering trap

Live probe at `INTEGRATION_BASE`:

- `GRAPH_V1_AGENT_KEYS` == the seven-role order == `('architect','data_analyst','builder','build_reviewer','fixer','fix_reviewer','deck_reviewer')` → **True**
- `MODEL_DRIVEN_AGENT_KEYS` == the seven-role order → **True**
- `OUTPUT_SCHEMAS` insertion order == the seven-role order → **False**; it is
  `architect, data_analyst, builder, fixer, build_reviewer, fix_reviewer, deck_reviewer`

This **confirms** the pre-Task-1 ruling and its stated reason. Consume `GRAPH_V1_AGENT_KEYS` or
`MODEL_DRIVEN_AGENT_KEYS`; never iterate `OUTPUT_SCHEMAS` for order.

Trap: the `_SCHEMA_CONTRACT_DIGESTS` **literal** at `agent_runtime.py:88` is written in
`OUTPUT_SCHEMAS` order (`fixer` before `build_reviewer`). It is a lookup table so its own order is
inert, but it reads like an authority. `_SchemaContractRegistry` correctly iterates
`MODEL_DRIVEN_AGENT_KEYS`, not this dict.

## Correction 15 — CONFIRMED and SHARPENED: the one landed writer, mapper, audit and lock owner

Discharges the correction-4 deferral. The single owner is
**`src/services/graph_configuration_draft.py`**, class `_GraphConfigurationDraft(_GraphConfigurationWorkbench)`
at `:189`. The one mapper/hash/flush/audit/lock write is the single private
**`_write_locked_content` (`:629`, `@staticmethod`)** — and it is the only place that:
advances `locked.draft_row.lock_version += 1`, sets `updated_by`/`updated_at` from
`select(func.current_timestamp())`, writes `candidate_hash = definition_content_hash(content)`
via `definition_content_values(content)`, calls `session.flush()`, and returns
`DraftSaveResult(..., changed=new_hash != old_hash)`.

Three public entry points reach it, all wrapping `with session.begin():` and
`self._read_workbench_for_draft_write(...)` (the lock):

| Entry point | Line | Client candidate on conflict |
| --- | ---: | --- |
| `save_editable_model_draft` | 212 | the editable candidate |
| `save_draft_content` | 269 | the validated `DefinitionContent` |
| `upgrade_draft_protected_assembly` | 327 | `None` |

Ruling: Task 4 adds **`upgrade_draft_schema_contract`** as a fourth entry point that reuses
`_write_locked_content` unchanged. It must add no second transaction, lock read, mapper, hash call
or audit write. The `changed: false` same-content contract is already satisfied by
`_write_locked_content`'s `changed=new_hash != old_hash` while still advancing lock/audit — so the
plan's "every explicit valid same-content save advances the shared lock/audit exactly once and
returns `changed: false`" is **landed behaviour, not new work**.

## Correction 16 — NEW DEFECT: there are TWO validator tuples, and the plan names one

The plan says "the existing immutable ordered validator tuple" (singular). There are **two** class
attributes on `_GraphConfigurationDraft`:

- **`local_candidate_validators`** (`:193`), default `(_assembly_candidate_validator,)` — #265's landed
  assembly validator. Documented "Deterministic/local validators; they run **before** the stale comparison."
- **`post_stale_validators`** (`:198`), default `()` — "Remote/expensive … run **only for a current
  candidate** and immediately before the one mapper/hash/flush/audit/lock write."

Both are run by `_run_candidate_validators` (`:200`), which aggregates "one reached phase in validator
order, then issue order" and raises `DraftContentRejected(*issues)`.

**Ruling: Task 4 must register schema-overlay validation in `local_candidate_validators`, appended
after `_assembly_candidate_validator`.** This is forced, not stylistic. In `save_draft_content` the
order is: `_validate_common` → lock → strict type → `_immutable_content_issues` →
**local validators (`:311`)** → stale check (`:312`) → post-stale validators (`:319`) → write.
Registering in `post_stale_validators` would make an invalid-plus-stale request return **409 instead
of the plan-mandated ordered 422**, because the stale check short-circuits first. The landed guard for
this is `tests/unit/test_graph_configuration_draft.py:905`
`test_local_invalid_stale_request_is_ordered_422_without_post_stale_or_mutation`
(and `:1889` for the trusted-content path). Cost if wrong: the invalid-plus-stale wire contract
inverts, and the defect surfaces only in a two-condition test.

## Correction 17 — NEW DEFECT: the plan's upgrade precedence contradicts the landed upgrade

Measured precedence at `INTEGRATION_BASE`:

| Path | Landed order | Effect |
| --- | --- | --- |
| ordinary save (`save_draft_content`, `save_editable_model_draft`) | local-invalid **before** stale | invalid+stale → ordered **422** |
| `upgrade_draft_protected_assembly` (`:327`) | stale **before** any validation | invalid+stale → **409** |

`upgrade_draft_protected_assembly` returns `DraftSaveConflict` at `:341` *before* calling
`_PROMPT_ASSEMBLER.upgrade_definition_to_v2` at `:349`. The landed guard is
`tests/unit/test_graph_configuration_draft.py:1517`
`test_stale_upgrade_never_reaches_the_transition_authority`, which monkeypatches the assembler and
asserts **`upgrade_calls == []`** plus an unchanged database snapshot.

The plan requires the *schema-contract* upgrade to behave the **opposite** way: "Existing-content
validation issues retain their `candidate.schema_overlay...` fields and ordered tuple.
**Invalid-plus-stale returns ordered 422; valid stale returns 409.**"

Ruling: this is a genuine plan-vs-code divergence and the plan wins for the **new** route, but Task 4
must implement it as a **separate method** and must **not** "make the siblings consistent" by moving
the stale check in `upgrade_draft_protected_assembly` — that REDs `:1517` and silently changes #265's
shipped wire contract. Record in the Task 4 brief explicitly: the two upgrade methods deliberately
differ in precedence. Cost if wrong: either the new route ships the wrong status, or a #265
regression is shipped under a #264 commit.

`already_current` is owned by **`src/services/prompt_assembler.py:844`**
(`PromptAssemblyIssue("protected_assembly.version", "already_current", "Protected assembly is already current.")`),
raised from `upgrade_definition_to_v2` **after** `self.validate(definition=definition)` — i.e. invalid
content validates before `already_current` is reported (`test_prompt_assembler.py:722`). Task 4's
schema equivalent must mirror that inner ordering with field `schema_contract`.

## Correction 18 — CONFIRMED: ordinary saves already reject the protected identities

`graph_configuration_draft.py:161-165` `_IMMUTABLE_DRAFT_FIELDS = ("definition_version",
"protected_assembly", "schema_contract")`, with `_IMMUTABLE_ISSUES["schema_contract"] =
DraftValidationIssue("schema_contract", "immutable_field", "Schema contract identity is immutable in
a draft save.")`, enforced by `_immutable_content_issues` (`:590`) before any candidate validator runs.

So the plan's Task-4 "ordinary identity rejection" is **already landed**, and it rejects with code
`immutable_field` on field `schema_contract` — **not** with any `overlay_*` code and not under a
`candidate.` prefix. Ruling: Task 4/5 must consume this, not re-implement it, and must not
"harmonise" the field name to `candidate.schema_contract`. Cost if wrong: a duplicate rejection path
with a second code for one condition, or a changed #263/#265 error field.

## Correction 19 — CONFIRMED: Task 5's landed wire owners, and the two still-absent pieces

| Plan claim | Verdict | Evidence at `INTEGRATION_BASE` |
| --- | --- | --- |
| `invalid_draft` envelope exists | CONFIRMED | `src/api/schemas/agent_definitions.py:308` `DraftValidationErrorResponse.code: Literal["invalid_draft"]` |
| `stale_draft` family exists | CONFIRMED | `:324` `DraftSaveConflictResponse.code: Literal["stale_draft"]` |
| upgrade 409 can carry `client_candidate: null` | CONFIRMED — **already nullable** | `:330` `client_candidate: EditableModelDraftRequest \| None` |
| `{"lock_version": N}` is the only upgrade body | CONFIRMED — reuse, don't add | `:290` `DraftLockRequest`, docstring "The only accepted body for the upgrade and legacy-source POST routes" |
| `candidate` DTO to extend | CONFIRMED | `:272` `EditableModelDraftRequest(prompt_text, model, assembly_rules)` — **has no `schema_overlay`**; Task 5 adds it |
| `schema-contract-upgrade` route | STILL-ABSENT (expected) | repo-wide grep for `schema-contract-upgrade`/`schema_contract_upgrade` across `src/`, `tests/`, `frontend/` returned empty, while the same grep shape finds the sibling `protected-assembly-upgrade` at `src/api/routes/agent_definitions.py:388` — so the probe discriminates and the absence is real |
| auth before body parsing | CONFIRMED by mechanism | `save_agent_definition_draft` (`routes/agent_definitions.py:329`) takes `request: Request` and `actor: Annotated[str, Depends(require_draft_write_principal)]`, then parses with `await request.json()` **inside** the body. FastAPI resolves `Depends` before the handler runs. Had the route declared a typed body parameter instead, FastAPI would parse and 422 the body *before* the dependency, inverting the claim |
| `SchemaOverlayResponse` read side | CONFIRMED present | `:43` |

All `422` bodies route through `_draft_validation_response` / `_rejection_response`, and malformed
JSON through `_malformed_json_response()` — one helper set Task 5 must reuse.

## Correction 20 — CORRECTED: the source-text join set is EIGHT files, not six

The briefed claim that `src/services/graph_configuration_draft.py` is read **as text** by a Python
test is **CONFIRMED** — `tests/unit/test_prompt_assembler.py:1361`. The membership list is corrected.
`test_prompt_assembler.py` text-reads (via `_read_client`, `:959`, off `_REPO_ROOT`, `:921`):

| # | File | Read at | What is joined |
| ---: | --- | ---: | --- |
| 1 | `frontend/tests/fixtures/mocks.ts` | 922 | 422 fixtures, stage fixtures, `LEGACY_COMPOSITE_ROLES` |
| 2 | `frontend/src/api/agentDefinitions.ts` | 923 | condition/anchor vocabularies, `CUSTOM_ANCHORS` |
| 3 | `frontend/src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.tsx` | 925 | universal-anchor legality |
| 4 | `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts` | 1275/1281 | `LEGACY_COMPOSITE_ROLES` |
| 5 | `frontend/tests/e2e/agent-definition-workbench.spec.ts` | 1284 | `const AFFECTED_ROLES` loop driver |
| 6 | `tests/integration/test_agent_definition_workbench_postgres.py` | 1287 | `AFFECTED_ROLES = (` |
| 7 | `src/services/prompt_assembler.py` | 1353 | enforcement set + transition `Literal` annotation |
| 8 | `src/services/graph_configuration_draft.py` | 1361 | `_LEGACY_SOURCE_ROLES` |

The affected-role join asserts **seven copies** equal across files 3-8 plus two inside file 7 — the
briefed "seven hand-typed copies" is CONFIRMED; the briefed six-file list substituted files 2 and 3
for files 6 and 7. **Two of the corrected entries are directly in #264's path:** file 8 is Task 4's
primary writer, and file 6 is in Task 7's own PostgreSQL matrix.

The reformat hazard is CONFIRMED at the parser: `_TS_STRING`
(`r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\""`) matches single and double quotes **only — not
backticks**. And the `graph_configuration_draft.py` read is positional:
`facade.index("_LEGACY_SOURCE_ROLES")` → `.index("= (")` → strings up to the first `")"`.
Ruling: when Task 4 edits that file, do not reflow `_LEGACY_SOURCE_ROLES`, do not convert it to
backticks, and do not introduce an earlier module-level name containing the substring
`_LEGACY_SOURCE_ROLES`. Rename loudly; never reformat quietly.

## Correction 21 — CORRECTED: `CUSTOM_ANCHORS` lives in `agentDefinitions.ts`, not `draftEditorState.ts`

The briefed rule "do not reorder `CUSTOM_ANCHORS` in `draftEditorState.ts`" is right about the
prohibition and wrong about the file. `CUSTOM_ANCHORS` is **defined** at
`frontend/src/api/agentDefinitions.ts:28-32` (`['after_authored_prompt','after_deck_brief','after_environment_constraints'] as const`,
with `export type CustomAnchor = typeof CUSTOM_ANCHORS[number]` at `:34`). `draftEditorState.ts`
**imports** it (`:4`) and consumes its order in production at `:698`
(`const rankOf = (anchor: CustomAnchor) => CUSTOM_ANCHORS.indexOf(anchor)`), which the surrounding
comment (`:690-697`) documents as deliberately joined to the server. The server side is
`_ANCHOR_RANK` at `src/services/prompt_assembler.py:111`, exported as `"legal_anchor_rank"` (`:345`)
and consumed at `:497`. The join is `test_client_condition_and_anchor_vocabularies_match_the_server`
(`test_prompt_assembler.py:1153`) reading `export const CUSTOM_ANCHORS` at `:1219`.
Ruling unchanged, file corrected: **do not reorder `CUSTOM_ANCHORS` in `frontend/src/api/agentDefinitions.ts`.**

## Correction 22 — CONFIRMED: one reducer, one request-ID counter, one pending gate

| Singleton | Location |
| --- | --- |
| reducer | `draftEditorState.ts:660` `export function draftEditorReducer`, wired by the **only** `useReducer` at `useDraftEditor.ts:30` |
| request-ID counter | `useDraftEditor.ts:31` `const nextRequestIdRef = useRef(1)`, incremented at `:49` and `:102` |
| in-flight / pending gate | `useDraftEditor.ts:32` `inFlightRequestIdRef`, combined into the one predicate at `:39` `operationBlocked = () => inFlightRequestIdRef.current !== null \|\| state.pendingSave !== null` |

Ruling: Task 6's "one aggregate Save / Assembly Upgrade / Schema Upgrade gate" **is**
`operationBlocked()`. Consume it; add no second ref, counter, reducer or gate.

Also re-confirmed for Task 6: `frontend/tsconfig.app.json:32` includes only `["src"]` and
`tsconfig.node.json:25` only `["vite.config.ts","playwright.config.ts","vitest.config.ts"]`, so e2e
spec bodies are typechecked by nothing, while `frontend/tests/fixtures/mocks.ts` is reached through
`src/**/*.test.ts` imports. A type error in a new spec surfaces only at runtime.

## Correction 23 — Correction 7 discharged: the matrix composition

Every file in the plan's Task-7 matrix was probed for existence at `INTEGRATION_BASE` and HEAD.

**Unit matrix (17 files): all present.** `tests/unit/test_agent_schema_registry.py` is absent at
`INTEGRATION_BASE` and present at HEAD — correct, it is Task 1's file. The other 16 are present at both.

**PostgreSQL matrix (7 files): 6 present, 1 correctly absent.**
`tests/integration/test_agent_schema_overlay_postgres.py` is absent at both — Task 4 creates it.
**The three named #261 suites that may not be dropped are all present and all pass with zero skips:**
`test_persisted_graph_runtime_failures_postgres.py`, `test_conversation_pin_migration_postgres.py`,
`test_conversation_pin_creation_postgres.py`. **No renames were needed and nothing was dropped.**

**Gap found — two existing PostgreSQL suites the matrix omits.** `tests/integration/` holds nine
`*postgres*` files. The matrix names seven (six existing). The two existing omissions are:

- `tests/integration/test_conversation_pin_acceptance_postgres.py` — **enrolled in the CI collection
  guard** at `tests/unit/test_ci_collects_integration_tests.py:220`, alongside the three #261 suites
  at `:187`, `:198`, `:209`. A file CI requires but the final gate never runs.
- `tests/integration/test_claim_exclusivity_postgres.py` — in neither the matrix nor the guard.

Ruling: Task 7 **adds** `test_conversation_pin_acceptance_postgres.py` to its PostgreSQL matrix, on
the plan's own "may add renamed replacements" latitude and because the CI guard already treats it as
required #261-family coverage. `test_claim_exclusivity_postgres.py` is out of this epic's slice and
stays out; recorded so a later reviewer does not read its absence as an oversight. Task 4 must enroll
its new `test_agent_schema_overlay_postgres.py` in the same guard and re-run it — the guard's shape at
`:187-220` is one `target = "tests/integration/<file>"` assertion per file against the CI run blocks.

## Correction 24 — the frontend baseline is an explicitly DEFERRED phase-B item

Not run, and deliberately not run. Another agent holds the frontend lane exclusively
(#262 Task 5). Re-probed reasons, both machine-global and both real:
`frontend/node_modules` is a **symlink** shared by the sibling worktrees, and Vite's dep-optimise
cache has no per-worktree `cacheDir`; port 3000 is machine-global, so Playwright's
`reuseExistingServer: true` would test another worktree's code and report it as this branch's.

The commands owed, to be run by whoever next holds the lane (Task 6 or Task 7), all from `frontend`
with checked-in dependencies only and **no** `npm install` / `npm ci` / `npx playwright install`:

```
(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx src/components/Admin/AgentDefinitionWorkbench/AssemblyEditor.test.tsx src/components/Admin/AgentDefinitionWorkbench/OutputSchemaEditor.test.tsx)
(cd frontend && npm run typecheck)
(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/AgentDefinitionWorkbench tests/fixtures/mocks.ts tests/e2e/agent-definition-workbench.spec.ts)
(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)
```

`OutputSchemaEditor.test.ts(x)` does not exist yet, so the first command is only fully runnable after
Task 6. Correction 7's **no-skips rule applies to this lane when it runs**, and no #264 task may be
signed off as matrix-complete while this item is outstanding. Reported as outstanding, not skipped.

## Correction 25 — accepted debt, not a defect (carried in so no #264 task "fixes" it)

For Build Reviewer, adding a deck-brief custom block creates an unsaveable draft until the admin
changes the condition dropdown: the reducer hardcodes `condition: 'always'` while the server requires
`payload_has_deck_brief` for that anchor, and the 422 names the exact field. Triaged under #265 and
out of #264's scope. Ruling: no #264 task may "fix" this as drive-by work — it would change #265's
shipped behaviour inside a #264 commit.

## Correction 26 — artefact hygiene defect in the branch itself

`git diff --name-only 3ed8f9b6a HEAD` includes
`.superpowers/sdd/2026-09-22-schema-driven-config-ui/plan-review-ce04afd08.md`. The plan's global
constraints state: "No artifact for this plan may use the obsolete `2026-09-22-schema-driven-config-ui`
path." The file is inherited through this branch's own commits, not created by Task 1's source work.
Ruling: **not** a source defect and not grounds to rewrite history now; Task 7 must exclude it from the
`INTEGRATION_BASE..HEAD` review package's "#264 work" accounting, or relocate it under the correct
path in the reviewed test-corrections commit. Cost if ignored: the whole-branch reviewer counts an
obsolete-path artefact as #264 deliverable and fails the package on the plan's own constraint.

## Correction 27 — WITHDRAWN RULING: the hash gate is NOT blind to serialisation mode

**This strikes an accepted controller ruling. Any task that read the ledger before this entry has
read a false claim. Read this instead.**

The ledger recorded, as an accepted ruling, that the two serialisation modes are hash-equivalent so
that "swapping `canonical_payload`'s mode changes no hash at all" and "the hash gate is blind to the
mode; only the direct payload assertion catches it". **Both statements are false**, and Task 2's
independent reviewer measured it.

What is true: for the seven packaged v1 definitions the modes *are* hash-equivalent — the reviewer
computed it and found zero differing roles. What does not follow, and what nobody measured before
recording it, is the general claim.

`model_dump(mode="json")` serialises a `Decimal` to a **string**, which `_normalize_canonical_value`
passes through un-normalised. `Decimal` is exactly the shape these values take crossing the
SQLAlchemy boundary — the case `canonical_payload`'s own docstring exists for. Swapping the mode,
with the anchor count asserted at 1, REDs **four** tests in the focused suite, not zero:

    FAILED test_hash_normalizes_manifest_floats_and_database_decimals
    FAILED test_hash_rejects_non_finite_numeric_values[temperature-Decimal('NaN')]
    FAILED test_hash_rejects_non_finite_numeric_values[top_p-Decimal('Infinity')]
    FAILED test_hashing_still_fails_closed_on_a_non_json_guidance_value
    4 failed, 137 passed

Two of those are **fail-closed guards**. In json mode `Decimal("NaN")` and `Decimal("Infinity")`
become strings, so the finiteness check never fires and a non-finite numeric would be **silently
hashed**. The mode is therefore load-bearing for a fail-closed guarantee — the precise opposite of
the withdrawn claim. The fourth failure is the author's own new fail-closed test.

**Why the original measurement showed zero, and why that was defensible while the conclusion was
not.** Scoped to the row's own named hash test, RED really is 0 — the reviewer reproduced `2
passed`. The number is correct under an undeclared per-named-test scope. The defect is the
**conclusion generalised from it**.

**The controller's confirmation checked the wrong thing.** It read `_normalize_canonical_value` and
verified that `list` and `tuple` route through one branch. That is true, and it establishes nothing
about whether any *other* mode difference reaches the hash. Reading one branch of a normaliser
cannot establish blindness to a whole serialisation mode; only measurement can, and nobody measured
before it was recorded as accepted.

**Downstream hazard this entry exists to stop.** A Task 3 through 7 agent trusting "the hash gate is
blind to the mode" could swap the mode believing the change free, silently breaking Decimal
normalisation and the non-finite guard **while all seven v1 hashes stay green**. That is a false
green on a fail-closed path.

**What survives.** The mode *choice* is correct and independently verified: `mode='json'` is
provably the persisting form, because `schema_overlay` is `json_document=True`
(`graph_configuration_content.py:44`) and `definition_content_values` does
`value.model_dump(mode="json")` at `:79`. Both of Task 2's mode assertions have teeth, each proved
by a distinct mutation. The requirement to declare the mode explicitly was right; the reasoning
recorded in support of it was wrong.

Cost of the original error: a later task could have treated a fail-closed guard as free to remove.

## Correction 28 — mutation row M7 is factually wrong; forward item (d) and concern 5 are struck

Task 2's clause-to-mutation row M7 claims "RED 1 (the `not_a_role` case now resolves)", and the
ledger propagated that into forward item (d) and concern 5 as "M7's radius is one node".

Measured by the reviewer: that test stays **6/6 green** — hardcoding the bridge's role still misses
the bundle key, so it still fails closed — and the real radius is **RED 13**.

So the task reported a weakness that does not exist, and the controller recorded it as a forward
item for Tasks 3-7. **Strike forward item (d) and concern 5.** A row that misidentifies its own RED
node undermines the deliverable it belongs to, which is why the reviewer graded it Important rather
than Minor.

One residual is worth keeping: no test distinguishes the role **direction**, because `_resolve` keys
on the `agent_key` argument and nothing passes an identity whose role differs from it. But the
structural protection is stronger than any test would be — `ContentIdentity` carries no role, so the
bridge literally cannot take one from a stored pair.

## Correction 29 — the fail-closed guarantee moved only half

Task 2 reported that the removed local helper's fail-closed behaviour moved to the hashing boundary.
The **value** half did, at two independent homes: `definition_content_hash` raises `TypeError` and
`definition_content_values` raises `PydanticSerializationError`. The reviewer traced all four write
paths — `revision_from_definition`, `draft_from_definition`, `_write_locked_content` (hash first at
`graph_configuration_draft.py:637`) and `agent_runtime.py:471` — and confirmed **nothing reachable
can persist a non-JSON overlay value**.

But the removed helper carried **two** raises, and the non-string-key raise has **no replacement**.
`{1:"a"}` and `{"1":"a"}` inside `examples` now produce the **same content hash** (`3b0f9986…`), the
persist path silently coerces `1` to `"1"`, and mixed keys fail only accidentally through
`json.dumps(sort_keys=True)`. No test exercises it. Reachability is low, because both the wire and
JSONB force string keys, which is why it is Important rather than Critical.

Either restore a key check with a test, or record an explicit ruling that the coercion is accepted.
Do not leave it implicit.

## Correction 30 — the converged carrier relaxed two required fields, undisclosed

`agent_schema_types.py:336-337`: the converged carrier **defaults** two fields that the removed one
**required**, so `schema_overlay: {}` now validates where it previously raised `missing`. Undisclosed
and untested. Impact is small today because all seven v1 overlays are empty, but Tasks 4 and 5
introduce the first non-empty overlays, so it must be disclosed and pinned before then.

## Correction 31 — EPIC-WIDE: a zero at a narrow scope licenses no statement about any wider scope

This is the generalisable lesson behind correction 27, named by the implementer that made the
original error, and it is the single most reusable sentence produced by this ticket.

The mode-blindness claim was not built on a bad measurement. Scoped to the row's own named
selectors, RED really was 0. The defect was **generalising that zero into a statement about the hash
gate as a whole** — and the controller then ratified it after verifying a different proposition
entirely (that `list` and `tuple` share a normaliser branch, which is true and irrelevant).

**Binding rule, two parts.** Mechanically: every clause-to-mutation table in this epic **declares its
measurement scope**, and where a row's own scope is narrower than the suite, it reports **both**
numbers. Task 2's corrected table does this — "named" for the row's own selectors, "focused" for the
full suite — and the two columns differ on the row that caused the problem: M2 is RED 1 named and
**RED 6** focused.

By judgement: a zero measured at a narrow scope supports **no** claim at a wider one. If a mutation
appears free, the only honest statements are "free within this scope" or "widen the scope and
measure again". Never "the gate cannot detect this".

Cost if wrong: a fail-closed guard is recorded as free to remove, which is exactly what happened
here and was caught only because an independent reviewer re-measured at a wider scope.

## Correction 32 — extends C-27: a `cp` backup taken before a change silently reverts it

C-27 required mutation harnesses to assert their anchor count. On its first outing that rule fired
**twice**, both times on the same agent, and both were reported rather than absorbed. The second is a
new trap worth recording in its own right.

The harness took its `cp` backups **before** the c29 non-string-key guard was written, so every
`restore_all()` silently reverted that guard and **inflated every focused number by exactly 1**.
Nothing about the runs looked wrong; the discrepancy surfaced only when a later mutation's anchor
failed to exist, because the anchor lived in the code the stale restore kept removing. The agent
re-baselined, re-ran all 19 rows and discarded the first run's focused column.

The first instance was simpler: a probe it failed to restore, so both arms of a comparison measured
json mode and returned the same hash — caught when the next mutation found 0 anchors.

**Binding addition to C-27: a mutation harness re-takes its backups after any commit, and asserts
that a restore reproduces the committed tree** — the triple check against HEAD is sufficient. A
stale backup set is indistinguishable from a passing suite, and it biases every subsequent number in
the same direction, which is worse than a single wrong measurement because the bias looks like
consistency.

## Correction 33 — the dump mode guards BOTH halves of the fail-closed behaviour

Extends correction 27 beyond what the reviewer established. `mode='json'` does not only stringify
`Decimal` so the finiteness check cannot fire — it also **coerces an integer object key to `"1"`
before the normaliser can see it**, so the new c29 non-string-key guard cannot fire either.

So the canonical dump mode protects **both** halves of the removed helper's original fail-closed
behaviour: the value half through the non-finite check, and the key half through c29. Measured, with
`mode='python'` shipped: a non-finite Decimal raises `ValueError: canonical numeric values must be
finite`; under the swap it is silently hashed to `140de6a9…`, and `Decimal('0.700000')` stops hashing
equal to `0.7`.

Any later task that touches the canonical dump mode is touching two independent fail-closed
guarantees, not one.

# ============================================================================
# Task 3 — runtime composition, canonical projection, diagnostics and traces.
# 2026-09-24. Base `1fb5141cc`; commits `cca068af3`, `87676a04f`.
# ============================================================================

## Correction 34 — Task 3's real file set: four replacements beyond the plan's Files block

The plan's Task-3 Files block names `src/services/agent_runtime.py`,
`src/services/agent_runtime_identity.py`, `tests/unit/test_agent_runtime.py`,
`tests/unit/test_persisted_agent_runtime.py` and "extend `tests/unit/test_agent_schema_registry.py`".
Task 3 changed **ten** files. Recorded here per the plan's own "Record replacements in corrections"
step.

| File | Why | Authority |
| --- | --- | --- |
| `src/services/agent_schema_registry.py` | the `:556` identity-carrier gate | named explicitly in the Task-3 brief's three items, so authorized there rather than by the Files block |
| `tests/unit/test_agent_resolution_prompt.py` | 7 RED — `PromptCaptureAdapter` returned `schema.model_construct()` | c11's amended radius names this file and this exact count |
| `tests/unit/test_deck_level_spec_change.py` | 2 RED — two `Capture` doubles, same cause | c11's amended radius, 2 |
| `tests/unit/test_graph_configuration_bootstrap.py` | 1 RED — `RecordingAdapter`, same cause | c11's amended radius, 1 |
| `tests/integration/test_conversation_pin_acceptance_postgres.py` | 1 RED — `assert isinstance(output, schema)` cannot hold once the bound schema is a strict *subclass* of the output's class | c23's matrix addition, plus the cause-baseline rule |

**The convergence itself needed no file outside the Files block**, which is why the brief's
ask-gate ("ask before starting if the *convergence* would require touching a file outside your
Files block") did not fire: nothing outside `agent_runtime.py` imported the duplicate class, proved
by repo-wide grep before any edit. The four test replacements are the cause-baseline rule applied
("anything outside the inherited fourteen is yours"), each a single adapter double that the
composition change necessarily invalidated, each mechanical, and **none changes production
behaviour**.

Ruling for Tasks 4-7: a runtime *contract* change in this epic has a five-suite test-double
radius, not a two-suite one. The doubles that break are the ones returning
`schema.model_construct()` — an empty shell that cannot survive `validate_output` — plus any
`isinstance(output, schema)` guard, which must become `issubclass(schema, type(output))` now that
the bound schema is a composed subclass. Cost if wrong: a later task reads 3 extra failures as a
new defect and re-derives this.

## Correction 35 — c9's vacuity is CONFIRMED by measurement, and the success channel is new behaviour

Verified by running HEAD's sink rather than reading it:
`RecordingAgentInvocationIdentitySink`'s public state at base was exactly `['calls',
'error_classes']`, **no success-named channel of any kind**, `calls.append` provably preceded
`callback()`, and after a *failed* invoke `len(calls) == 1`. So "invalid output emits no success
fields" had nothing to assert — and if a reader took `calls` for the success channel, `calls == []`
on failure is *false*, so the only way such a test could pass was by asserting nothing.

Task 3 added `AgentInvocationSuccess(identity, additional_fields)` plus a `successes` list appended
**only after** the callback returns, and `additional_fields` on the logging sink's **success**
record only. The three channels are now documented as distinct outcomes in the class docstring.
Non-vacuity is measured: moving the append before the callback REDs 6/12, deleting it REDs 19/27,
and adding the field to the *error* record REDs 2/2.

Amended figures confirmed in passing: **three** `invoke` definitions, not four sites. The
`-> ValidatedAgentOutput` retyping was taken anyway — a design choice, as the amendment says — because
returning only `canonical_output` would discard the projection before either sink could observe it.

## Correction 36 — the canonical projection is a behaviour change with a 63-test radius, and M21 re-confirms c11's 30

`result.output` is no longer the object the adapter returned; it is
`validated.canonical_output`, a freshly validated instance of the **original canonical class**. So
`result.output is output` is no longer true anywhere, and `adapter.calls[...]["schema"] is
OUTPUT_SCHEMAS[role]` is no longer true either — the adapter is bound to a strict
(`extra="forbid"`) subclass named `…SchemaV{n}Overlay`.

Measured radius of the change, before repair: `test_agent_runtime.py` **18**,
`test_agent_resolution_prompt.py` **7**, `test_deck_level_spec_change.py` **2**,
`test_graph_configuration_bootstrap.py` **1** (the four c11 files, **28** against c11's 30),
plus `test_persisted_agent_runtime.py` **34** and the acceptance suite **1** — **63 total**.
Three of the four c11 files match byte-for-byte; `test_agent_runtime.py` differs (18 vs 20) because
c11's sabotage breaks the *literal* while this change alters the whole composition path — different
mutations sharing a neighbourhood.

**Independently, c11's own figure still reproduces exactly.** Mutation row M21 sabotaged the
compatibility loader's hardcoded v1 overlay literal, now at `agent_runtime.py:467-468`, and REDs
**30 across the same four files** on the Task-3 tree. c11's amended magnitude is confirmed a third
time.

## Correction 37 — at the adapter-conversion boundary `exclude_unset` is load-bearing and the dump mode is NOT (both scopes declared)

`_supplied_output_keys` converts one provider result to raw top-level keys with
`model_dump(mode="python", exclude_unset=True)`. The two halves behave oppositely and the
difference matters, so both are recorded:

- **`exclude_unset=True` is load-bearing.** The registry distinguishes an absent optional from an
  explicitly supplied `null` by raw key presence, so a field sitting at its declared `None` default
  must not arrive as an explicit null. Dropping the flag REDs the `{}`-vs-null row.
- **The dump mode is free at both measured scopes: RED 0 of 264 in the focused suite and RED 0 of
  887 in the whole Task 7 unit matrix.** Per correction 31 that licenses no wider claim, and **no
  claim that the gate cannot detect it** is made here.

The *mechanism* was probed rather than the zero generalised. Walking every field annotation of all
**13 models** reachable from the seven canonical output schemas found **zero** mode-divergent field
types — no `Decimal`, `datetime`, `date`, `time`, `timedelta`, `UUID`, `bytes`, `Enum`, `set`,
`frozenset` or tuple-typed leaf anywhere. The modes are therefore equivalent *for these schemas*,
which is a **precondition, not a guarantee**, and it is now asserted by
`test_no_canonical_schema_carries_a_dump_mode_divergent_field_type` (with an internal aim check,
`len(walked) >= 13`, so a walker that stopped at the roots fails rather than reporting a
comfortable zero).

**This is emphatically NOT correction 33's decision.** `canonical_payload`'s `mode="python"` guards
three fail-closed guarantees and was not touched by Task 3. The adapter-conversion mode is a
different call at a different boundary: python-to-python re-validation, not a persistence
boundary. Ruling: adding a mode-divergent field type to any of the seven output schemas REDs the
new precondition test, and whoever does it must re-examine this mode rather than discover the
difference in production.

## Correction 38 — `_run_resolved`'s generic `(ValidationError, ValueError, TypeError)` fallback was pinned by NOTHING, found by a mis-aimed mutation

A mutation intended for the `SchemaOverlayValidationError` fallback anchored uniquely on the
*generic* catch-all one line below it — the failure mode the anchor-count rule does **not** catch,
a unique anchor on the wrong line — and returned RED 0. Suspecting the instrument first, the cause
was probed directly: both suites that assert `invalid_persisted_definition` through the runtime
reach it via the **`PromptAssemblyRejected`** clause instead, confirmed by inspecting `__cause__`
on a live run. So the zero was real and the aim was wrong; the re-aim (M18b) REDs 1/1.

The mis-aim paid for itself: the generic fallback was reached by no test at either scope, in
pre-existing code that Task 3 only added a clause above.
`test_a_role_mismatch_between_release_and_content_is_invalid_persisted_definition` now pins it, so
the same mutation at matrix scope reads RED 1/887 rather than 0.

Ruling for Tasks 4-7: **report mis-aimed mutations, and probe the zero's cause rather than
re-aiming blind.** Two of this epic's findings now come from mis-aims investigated instead of
absorbed.

## Correction 39 — forward items Task 3 deliberately did not action

1. **`agent_runtime.py:87-96` is still a third copy of the seven v1 digests**
   (`_SCHEMA_CONTRACT_DIGESTS`), alongside `agent_schema_registry._V1_DIGESTS` and this file's
   table. Correction 13 warned about a third *registry instance*, not a third *table*; converging
   it means touching `CodeOwnedAgentDefinitionSource`'s own fail-closed check, outside Task 3's
   three items. `_SchemaContractRegistry` was reduced to that check plus `identity_for` and its
   now-unreachable `resolve` was removed, so no unreachable second contract check reads as a live
   guard.
2. **`LoggingAgentInvocationIdentitySink` now emits one model-derived field.** Plan-mandated, and
   allowlisted by construction (only `composed.declared_optional_names`, capped 8 × 280), but the
   adjacent test is named `test_runtime_logging_sink_does_not_log_prompt_payload_or_model_output` —
   a name now **broader** than its guarantee. An in-test disclosure was added rather than a rename;
   a reviewer may prefer the rename, or may want the notes dropped from logs entirely.
3. **`VALID_OUTPUT_VALUES` fixture data now exists in four test modules.** Duplication was chosen
   over a new shared helper to avoid widening the file set further.
4. **`AgentInvocationSuccess` is not re-exported from `agent_runtime`** — re-exporting an otherwise
   unused name trips `F401` and nothing imports it that way today.
5. `ruff format --check` reports 6 of Task 3's files would reformat. Not a repo gate (the
   configured `[tool.ruff.lint]` gate passes with **zero new findings** against the same files at
   base), recorded rather than claimed clean — the Task-2 re-review's F7 flagged exactly this
   over-claim.

## Correction 40 — controller rulings on Task 3's three disclosed decisions

**(a) The four files beyond the Files block are ALLOWED, and one of them was mine to authorize.**
Task 3 flagged this as the widest scope decision it made without asking, and invited disagreement.
It was right to flag it and the decision stands. `src/services/agent_schema_registry.py` holds the
`:556` gate that the controller's brief named as one of Task 3's **three explicit items**, so the
brief authorized it even though the plan's Files block does not list it — the same defect class as
#262's C-30, where a boundary was written from the plan's text rather than from the code that text
describes. The three test files (`test_agent_resolution_prompt.py` 7,
`test_deck_level_spec_change.py` 2, `test_graph_configuration_bootstrap.py` 1) plus
`test_conversation_pin_acceptance_postgres.py` 1 were **predicted by name and count in the c11
radius the controller supplied**, so they were foreseen rather than discovered, they are single
adapter doubles, and the cause-baseline rule makes an inherited RED the current task's to repair.
None touches production behaviour. The Files block is amended to include all four.

**(b) The partial TDD inversion is accepted on the same terms as #265 Task 5.** The registry half had
nine REDs measured before implementation; the runtime and sink tests were written after the code and
are proved by the mutation table instead. That is this epic's established substitute and it is
weaker evidence than a genuine RED, because sabotage shows a test *can* fail while TDD shows it
asserts the *requirement*. Precedent from #265 Task 5: accepted, with the residual routed to the
reviewer as an explicit objective — hunt for tests that pass for the wrong reason. Applied here too.

**(c) Concern 4 is recorded for a later task, not this one.** `agent_runtime.py:87-96` remains a
third copy of the seven v1 digests. Correction 13 warned about a third registry *instance*, not a
third *table*, so this is outside Task 3's warrant, and converging it means touching
`CodeOwnedAgentDefinitionSource`'s own fail-closed check. `_SchemaContractRegistry` did lose its
now-unreachable `resolve`, and the `AgentRuntime.__init__` check is strengthened to v1+v2 material.

## Correction 41 — EPIC-WIDE: two tickets are independently widening the application log surface

Task 3 disclosed that `LoggingAgentInvocationIdentitySink` now emits one model-derived field on its
**success** record, and that the adjacent test named `…does_not_log_prompt_payload_or_model_output`
is consequently **broader than its guarantee**. It added an in-test disclosure rather than renaming.

Independently, and on the same sink, #262's slice 4B disclosed that widening
`AgentInvocationIdentity` puts **both session IDs** into the same `persisted_agent_invocation` log
line, because the sink logs `**identity.__dict__`.

**Neither ticket is at fault and both disclosed it.** Both changes are mandated by their own plans.
But the convergence is the finding: **one logging sink is accumulating disclosure from two tickets
that cannot see each other's diffs**, and neither ticket's privacy contract covers application logs
— #262's is scoped to the API response, and #264's is scoped to persisted content.

Binding: both whole-branch reviews must rule on the **combined** log record rather than on their own
ticket's increment, and a test whose name promises more than it guarantees must be renamed to its
guarantee or widened to its name. Whichever ticket integrates second inherits the combined surface,
so it must re-read this correction rather than assume its own increment is the whole picture.

Cost if wrong: a privacy posture that holds for every individual diff and fails for their sum, with
no single review positioned to see it.

## Correction 42 — BLOCKING FIX to correction 36's ruling: the 63 REDs are FOUR causes, not one

Correction 36 attributes Task 3's 63-RED radius to a single cause and rules on that basis. **The
attribution is wrong**, measured by Task 3's independent reviewer and classified by traceback:

- **57** — adapter doubles returning an empty `model_construct()` shell → `AgentOutputValidationError`
- **4** — the bound schema is now `…SchemaV1Overlay` rather than canonical (`:276`, `:428`, `deck_reviewer`)
- **1** — `result.output is output` no longer holds (`test_agent_runtime.py:121`, `deck_reviewer`)
- **1** — the acceptance suite's `isinstance` guard

Every per-file figure matches (18/7/2/1/34 + 1 = 63); it is the **aggregation** that hid two causes.

**The load-bearing detail Task 4 needs:** the five non-shell failures are all and only
`deck_reviewer`, because its canonical schema has **no required field**, so an empty shell *survives*
validation and the **next** assertion fires instead. A Task 4 agent following correction 36 as written
would see five `deck_reviewer` REDs shaped exactly like a new defect and have no ruling that covers
them.

**Correction 36's ruling is amended to add:** a runtime contract change also REDs any
`result.output is output` assertion and any `adapter.calls[...]["schema"] is OUTPUT_SCHEMAS[role]`
assertion, and those surface precisely on roles whose canonical schema has no required field —
`deck_reviewer` today — because the empty shell survives validation there.

This was fixed before Task 4 was dispatched, because correction 36 is the artefact Task 4 will read
when its own composition change lights up the same neighbourhood.

## Correction 43 — supersedes 41 and #262's C-32: BOTH tickets hit the SAME root cause on the same sink

Corrections 41 and #262's C-32 treated two log findings as separate increments on a shared surface.
They are the **same defect**, and the reviewers found it independently from opposite directions.

**The root cause is a denylist of literal field names where a positive assertion on the permitted set
is required.** The guard at `tests/unit/test_persisted_agent_runtime.py` iterates six forbidden
*spellings* and asserts `not hasattr(record, name)`. So:

- **#262's slice 4B** slipped `root_session_id` and `actor_session_id` past the needle `session_id`
  — verified, 75 passed with a written prohibition broken.
- **#264's Task 3** can slip `validated_output` past the needle `output` — verified by mutation RM1,
  which put **the entire canonical model output** into the log record while
  `…does_not_log_prompt_payload_or_model_output` **passed**, at 0 RED of 264 and 0 of 887. The
  complementary RM1b proves the mechanism: the same leak spelled `output` REDs 1.

Two tickets, two unrelated fields, one guard, and neither ticket's own tests could see the other's
breach. **A denylist cannot be closed by adding names**, which is why both fixes are the same fix.

**Binding: replace the six-name `hasattr` denylist with ONE positive assertion** that the record's
non-intrinsic keys equal exactly `{identity fields, outcome, error_class, additional_fields}`. That
makes RM1 RED, makes #262's session-ID breach RED, and is the only form that survives two tickets
editing this sink blind to each other. Whichever ticket integrates second owns the combined
assertion.

**And the content finding, which neither controller had measured.** On the unmutated tree, up to
**2240 characters of free-form model-authored prose** reach the log per successful invocation, and the
registry's own shipped example for `architect` is *"Assumed the request refers to the existing Q2
deck…"* — paraphrasing the user's request is the field's **purpose**. So `diagnostic_notes` **is**
model output, which makes the test name `…does_not_log_prompt_payload_or_model_output` **false, not
merely broad**, and an in-test disclosure cannot repair a false name attached to an assertion that
does not assert it. Rename it to its guarantee.

The combined line will therefore carry **both session IDs and up to 2240 characters of user-derived
prose** under a name promising neither. The second integrator must also decide whether the notes
belong in the log as values at all, or only as a count or key list.

Cost of the original framing: two reviews each fixing their own increment, leaving the guard shape
that admitted both.

# ============================================================================
# Task 4 — one locked v2 upgrade/save pipeline.
# 2026-09-25. Base `80dec9e7b`; commit `418ee15c8`.
# ============================================================================

## Correction 44 — c16/c17/c18 are disjoint, and the c18 client-path gap closes by construction

The Task 4 brief required the implementer to ask before resolving a three-way precedence
question. There was none to resolve, and the reason is worth recording so a later task does not
re-derive it: the three corrections constrain **three disjoint things** — c16 constrains *where*
the overlay validator registers, c17 constrains the *new upgrade method's* internal precedence,
c18 constrains the *identity rejection's* code and field. c16 and c17 agree in direction
(validation outranks staleness); c17 only forbids touching the sibling; and c18's guard shares
neither a field nor a code with the overlay validator (`schema_contract`/`immutable_field` versus
`candidate.schema_overlay.*`/`overlay_*`).

**The c18 client-path gap is real and was confirmed by measurement**, exactly as the brief said:
`EditableModelDraftRequest` is `extra="forbid"` over `['prompt_text','model','assembly_rules']`,
so `candidate.schema_contract` yields `loc=('schema_contract',) type=extra_forbidden`, never
`immutable_field`.

**Ruling: the gap must NOT be closed by adding an `immutable_field` guard to the client path.**
c18's own cost-if-wrong is "a duplicate rejection path with a second code for one condition", and
that is precisely what such a guard would be. The identity there is not unrejected but
**unreachable**: `EditableModelDraft` has no such field and the payload is rebuilt from stored
content. Task 4 therefore converted the unreachability from an accident into a guard
(`test_the_client_candidate_cannot_name_the_protected_identity_at_all`, plus M15 which REDs 2/116
on adding the field). Cost if wrong: two codes for one condition, and a changed #263/#265 error
field.

**Forward note for Task 5:** when it adds `schema_overlay` to `EditableModelDraftRequest`, the
identity must stay out of both that DTO and `EditableModelDraft`. M15 is the guard.

## Correction 45 — the carrier gate's BaseModel hole is UNREACHABLE-BY-DIGEST, not merely unused

Task 3 left `_replacement_schema_contract_identity`'s re-arm dataclass-only; the brief routed the
BaseModel-triple hole (`agent_schema_registry.py:571-574`) to Task 4 as "fix if you are in that
file; route it if not". Task 4 was **not** in that file, so it is routed — but with a measurement
that changes the risk assessment.

Task 4 is the **first live caller** to route a Pydantic carrier (`ContentIdentity`) through that
branch, which would ordinarily *raise* the risk. It does not, because widening `ContentIdentity`
to carry the identity triple **fails closed at import time** on a pre-existing guard: measured,
adding a defaulted `agent_key` yields
`RuntimeError: Protected assembly v2 material changed without an identity update: expected
fb651a0d…, calculated 4bbdb4a5…`, because `ContentIdentity` is part of the hashed
protected-assembly material. No test in any scope even runs.

So the hazard cannot be introduced silently through the one reachable carrier. Ruling: the
general BaseModel-triple hole stays open and is **still worth closing** for a future carrier that
is not part of hashed material, but it is **not** a live defect and no task should treat it as
blocking. Task 4 pinned the reachable half
(`test_content_identity_cannot_carry_a_role_so_the_pydantic_carrier_gate_is_safe`) and recorded
that this test is belt-and-braces behind the digest guard rather than the sole guard — the kind of
over-claim the Task-2 re-review's F7 flagged.

## Correction 46 — `thaw_json_containers` is asymmetric with `freeze_json_containers`

`agent_schema_types.py`: `freeze_json_containers` handles `Mapping`, `list` **and** `tuple`;
`thaw_json_containers` handles `Mapping` and `tuple` but **not `list`**. So
`thaw_json_containers(list(frozen_tuple))` returns the list unchanged with its children still
frozen, silently.

Found because it made a Task 4 assertion pass for the wrong reason before the comparison was
fixed. Not a production defect today — no production caller passes a list — but any test or
caller that normalises a frozen structure by wrapping it in `list(...)` first will get a false
result with no error. Ruling: accepted as-is for #264; recorded so a later task adding a `list`
branch knows the asymmetry is known rather than accidental, and so no reviewer reads a
list-wrapped thaw as correct.

## Correction 47 — EPIC-WIDE: `tests/unit/test_usage_service.py` is a latent UTC-midnight flake

A full `tests/unit` run that **crosses UTC midnight** produces **four failures outside the
inherited fourteen**, in `test_usage_service.py`: `test_event_days_use_real_logins`,
`test_new_vs_returning_split`, `test_duplicate_worker_rows_count_as_one_visit`,
`test_all_data_daily_spans_from_earliest_event`. Reading 18 failed / 5608 passed instead of
14 / 5612.

Cause: `tests/unit/test_usage_service.py:80` captures `NOW = datetime.utcnow()` at **module
import** and derives `TODAY` from it; the suite takes ~5 minutes, so a run starting shortly
before midnight asserts about a `TODAY` that has since advanced.

Measured, in this order: 20/20 in isolation; 128/128 alongside the whole
`test_graph_configuration_draft.py` suite (so it is not pollution from the task's own tests); all
four names are day-window tests; clock read 00:04 UTC; and the identical suite re-run clear of
the boundary returned exactly **14 failed / 5612 passed / 110 skipped**.

**Binding for every remaining task and review on this epic: the cause baseline is 14 in six files
ONLY away from the UTC-midnight boundary.** If a run shows these four, re-run rather than
attribute them — and never absorb them into a task's own radius. Cost if wrong: an agent spends a
round hunting a defect in its own diff, or worse, "repairs" a shared analytics suite it does not
own. This is the second time on this epic that a wider-scope number needed its *cause* verified
rather than its count compared (see correction 42).

## Correction 48 — Task 4's shipped precedence, including the one sub-decision no correction covered

`upgrade_draft_schema_contract` ships as:
`validate(current) → stale → already_current → upgrade_content_to_v2 → validate(target) → write`.

c17 mandated validate-before-stale and validate-before-`already_current`. It did **not** rule on
`already_current` **versus** stale. Task 4 put `already_current` **after** the stale check, on
this reasoning: it is a judgement about content a stale client has not seen, so a stale client
receives the coherent 409 snapshot — from which it can observe the contract is already v2 — and
can retry. That keeps both upgrade methods aligned on that sub-question while differing only on
the validation question c17 sanctions.

Recorded as a disclosed decision, not a ruling. A reviewer may prefer `already_current` before
stale, which would make a stale repeated upgrade a 422.

Also recorded: the two upgrade methods' deliberate divergence is now pinned by a single test that
drives **one identical request shape** (locally invalid AND stale) through both and asserts 409
from the sibling and ordered 422 from the new method —
`test_the_two_upgrades_deliberately_differ_in_precedence`. M7 (removing the sibling's stale
short-circuit) REDs **4/116**, including the landed `:1517` guard, so the #265-regression risk
c17 named is now instrumented rather than merely avoided.

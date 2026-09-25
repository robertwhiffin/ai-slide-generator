# Task 0 phase B — integrated-code re-probe report

**Status: DONE_WITH_CONCERNS.** The gate is discharged and Task 2 is unblocked. The concerns are
(a) the frontend baseline is deferred and outstanding by design, and (b) the re-probe found three
plan defects that will mis-build Tasks 3, 4 and 5 if they are dispatched from the plan as written.

- `INTEGRATION_BASE` = `3ed8f9b6a` · HEAD re-probed = `5bb2b36a2583bf4fb215165f8298d031e01a6d28`
- No production code written. No push, PR, merge or deploy. No `pip`/`uv`/`npm` invoked; no `.venv` created.
- Findings appended to `PLAN-CORRECTIONS.md` as corrections **8-26**; baselines appended to `progress.md`.

## Import provenance

```
python 3.11.0  /Users/robert.whiffin/.pyenv/versions/3.11.0/bin/python
databricks-sdk 0.112.0
src              -> .worktrees/issue-264-schema-overlay/src/__init__.py
databricks_tellr -> .worktrees/issue-264-schema-overlay/packages/databricks-tellr/databricks_tellr/__init__.py
agent_schema_registry -> .worktrees/issue-264-schema-overlay/src/services/agent_schema_registry.py
.venv: absent before and after every gate
```

## Triple check — one deviation, recorded not absorbed

HEAD and `git diff --cached` were exactly as expected. `git status --porcelain` was **not** empty: it
held ` M .superpowers/.../progress.md`, the controller's own uncommitted rebase addendum. Source tree
clean; this is the inverse of the index-masking failure this epic has hit three times. Correction 8.

## The four deferred claims

### Correction 3 — CONFIRMED, with one CORRECTION
`src/services/agent_runtime_identity.py` is present and holds exactly four names, each defined **once
repo-wide** (`AgentInvocationIdentity` `:13`, `AgentInvocationIdentitySink` `:21`,
`RecordingAgentInvocationIdentitySink` `:29`, `LoggingAgentInvocationIdentitySink` `:47`), re-exported
by plain import at `agent_runtime.py:45-50`. **No parallel sink exists.**
Probe: repo-wide `grep "class <name>"` across `src/` and `tests/` — a second definition would have
listed a second file; each listed exactly one.
**CORRECTED:** `src/services/persisted_agent_runtime.py` **does not exist** at either commit, though
`tests/unit/test_persisted_agent_runtime.py` does. The persisted-runtime owner is
`src/services/persisted_graph_release.py` (`ResolvedDefinition` `:75`, `ResolvedDefinitionLoader`
Protocol `:84`, `PersistedGraphReleaseLoader` `:91`). Corrections 9-11.
`AgentRuntime.run(agent_key, graph_release_id, payload, assembly_context)` confirmed verbatim at `:512`.

### Correction 4 — CONFIRMED and SHARPENED into two defects
One writer: `_GraphConfigurationDraft` (`graph_configuration_draft.py:189`); one locked
mapper/hash/flush/audit/lock write: `_write_locked_content` (`:629`); three entry points reach it.
Probe: read every `session.begin()` / `lock_version +=` / `session.flush()` site in the module — all
three entry points funnel to the one static method, and no second `lock_version` mutation exists.
**Two defects:** there are **two** validator tuples, not the plan's one (`local_candidate_validators`
`:193`, `post_stale_validators` `:198`), and registering schema validation in the wrong one turns the
plan's mandated invalid-plus-stale **422 into a 409**; and the plan's schema-upgrade precedence
(invalid before stale) is the **opposite** of the landed assembly upgrade (stale before invalid),
whose guard `test_stale_upgrade_never_reaches_the_transition_authority` (`:1517`) asserts
`upgrade_calls == []`. Corrections 15-18.

### Correction 7 — DISCHARGED
All 17 unit matrix files present. Six of seven PostgreSQL files present; the seventh is Task 4's to
create. **The three named #261 suites are present and green with zero skips — nothing dropped, no
renames needed, no skips accepted.** Gap found: `test_conversation_pin_acceptance_postgres.py` exists
and is **enrolled in the CI collection guard** (`test_ci_collects_integration_tests.py:220`) but is
absent from the matrix — added by ruling. `test_claim_exclusivity_postgres.py` is out of slice and
stays out, recorded so its absence is not read later as an oversight. Correction 23.

### Blanket ruling (corrections line 62) — swept
Every final #261/#263/#265 signature and file claim in the plan and corrections is now marked
confirmed, corrected or still-absent across corrections 9-22 and 26. Confirmed: the four-argument
`run`, the test-only compatibility loader, the retained v1 digests, the seven-role order, the single
writer, the `invalid_draft`/`stale_draft` families, the already-nullable `client_candidate`, the
`DraftLockRequest` body, auth-before-body, one reducer/counter/gate, the tsconfig coverage gap.
Corrected: the persisted-runtime owner, the text-join membership set, the `CUSTOM_ANCHORS` home.
Still-absent (all expected): `schema-contract-upgrade` route, `candidate.schema_overlay`,
`OutputSchemaEditor.tsx(x)`, `test_agent_schema_overlay_postgres.py`.

## Interface-claim table

Every claim confirmed, with the probe and the counterfactual. "What I'd have seen if false" is the
column that matters; a claim without one is flagged below the table.

| # | Claim | Probe | Had it been false |
| ---: | --- | --- | --- |
| 1 | one sink family, four names | repo-wide `grep "class <name>"` | grep lists 2+ files per name |
| 2 | sink signature `Callable[[], BaseModel] -> BaseModel` | read `agent_runtime_identity.py:21-56` | a different annotation in source |
| 3 | `ValidatedAgentOutput` is a dataclass, not `BaseModel` | read `agent_schema_types.py:381` | `class ValidatedAgentOutput(BaseModel)` |
| 4 | frozen v1 digests == corrections table, all 7 | byte-compare `_SCHEMA_CONTRACT_DIGESTS` to the table | a differing hex string |
| 5 | v1 material has not drifted | `_SchemaContractRegistry.__init__` recomputes and raises `RuntimeContractIdentityError`; import succeeded | `import src.services.agent_runtime` raises |
| 6 | seven-role order == `GRAPH_V1_AGENT_KEYS` == `MODEL_DRIVEN_AGENT_KEYS` ≠ `OUTPUT_SCHEMAS` | live tuple equality, printed True/True/False | any of the three booleans inverting — and one **did** come back False as predicted, proving the probe discriminates |
| 7 | two validator tuples | read `:193` and `:198` | one attribute only |
| 8 | local validators run before the stale check | read `save_draft_content:311-319`; landed guard `:905` | the stale `return` preceding the local call |
| 9 | assembly upgrade is stale-first | landed guard `:1517` asserts `upgrade_calls == []` | a non-empty `upgrade_calls` |
| 10 | ordinary saves already reject `schema_contract` | read `_IMMUTABLE_DRAFT_FIELDS` `:161` + `_IMMUTABLE_ISSUES` | `schema_contract` absent from the tuple |
| 11 | `client_candidate` already nullable | read `schemas/agent_definitions.py:330` | no `\| None` |
| 12 | `DraftLockRequest` is the one upgrade body | read `:290` + docstring | a second lock DTO in the module |
| 13 | `candidate` DTO has no `schema_overlay` | read the full `EditableModelDraftRequest` body | the field present |
| 14 | `schema-contract-upgrade` absent | repo-wide grep; **same grep shape finds the sibling `protected-assembly-upgrade`** | a route/handler hit |
| 15 | auth precedes body parsing | route takes `request: Request` + `Depends(...)`, parses via `await request.json()` in-body | a typed body param, which FastAPI parses before dependencies |
| 16 | compatibility loader is test-only | all `.compatibility()` callers are under `tests/`; production factory `:633` uses `PersistedGraphReleaseLoader` | a caller under `src/` |
| 17 | one reducer / counter / gate | grep `useReducer`, `useRef`, `operationBlocked` | a second `useReducer` or counter ref |
| 18 | `graph_configuration_draft.py` is text-read by a Python test | `test_prompt_assembler.py:1361` | no `_read_client` of that path |
| 19 | the join parser ignores backticks | read `_TS_STRING` regex | a backtick alternative in the pattern |
| 20 | `CUSTOM_ANCHORS` defined in `agentDefinitions.ts:28` | grep `export const CUSTOM_ANCHORS`; `draftEditorState.ts:4` imports it | the definition in `draftEditorState.ts` |
| 21 | e2e spec bodies are typechecked by nothing | read both tsconfig `include` arrays | `tests` present in either |
| 22 | three named #261 PostgreSQL suites green, zero skips | ran each as its own invocation | a skip or failure line |
| 23 | Task 7 unit matrix is clean | ran the 17-file matrix verbatim | a non-zero failed/skipped |
| 24 | the 14 inherited failures split three ways | ran the six files with `--tb=line`, grouped by traceback | a fourth cause, or different proportions |

### Unfalsifiable — 4 claims, flagged

1. **The seven frozen v2 digest literals are the *correct* material.** Any recomputation runs the same
   Task-1 function that produced them, so I can establish self-consistency but not correctness. The v1
   column is falsifiable because an independent landed table exists to compare against; v2 has no such
   counterpart. Task 2's "v2 hash change" test inherits this limit.
2. **The "Packaged v1 content hash" column** in the pre-Task-1 identity table. I confirmed the *frozen
   v1 digest* column against `_SCHEMA_CONTRACT_DIGESTS`; I found no landed counterpart for the second
   column and did **not** verify it. Reported as unverified rather than carried as confirmed.
3. **The whole frontend lane.** Deferred; every frontend behavioural claim is unfalsified this phase.
4. **Schema/assembly identity independence** is confirmed *structurally* — `DefinitionContent` carries
   `protected_assembly` and `schema_contract` as separate `ContentIdentity` fields — but I ran no probe
   that would fail if they were behaviourally coupled. Structurally confirmed, behaviourally unfalsified.

### A probe that showed nothing, reported anyway

My first attempt at the text-read set was **mis-aimed** and returned three files. I had read only
`test_prompt_assembler.py:915-1000` and enumerated the `_REPO_ROOT` constants declared there, so I saw
`mocks.ts`, `agentDefinitions.ts`, `AssemblyEditor.tsx` and was about to record the briefed six-file
claim as overstated. Widening to the whole module found more constants at `:1275-1287` and direct
`_read_client(...)` calls at `:1353` and `:1361` — **eight** files, not three and not six. Had I trusted
the narrow probe I would have told Task 4 that its primary writer file is not text-joined, which is the
exact defect class the briefing warned about. Correction 20.

## Cause baselines

**Full unit suite:** 14 failed, 5499 passed, 110 skipped. Exactly the controller's known-inherited set,
same six files and per-file counts, **zero failures outside it**. Passed reconciles as 5460 + Task 1's 39.

1. **9 × `ConversationGraphReleaseIntegrityError: no active Graph Release`** at `conversation_pins.py:83` — fixture.
2. **3 × `AttributeError: '_FakeSession' object has no attribute 'execute'`** at `conversation_pins.py:79` — diverged double.
3. **2 × assertions** in `test_deploy_autoscaling.py:124` (`'provisioned' == 'autoscaling'`) and `:152` — unrelated.

Refinement: classes 1 and 2 share one production chokepoint, `conversation_pins.py` lines 79 and 83.
Twelve of fourteen failures funnel through it, so a single repair there would move both classes and a
future "12 fewer failures" is one fix, not twelve.

**Task 7 unit matrix: 805 passed, 0 failed, 0 skipped.** None of the 14 lands in the matrix.

**PostgreSQL, per file, zero skips each:** bootstrap 2 · constraints 7 · persisted-runtime-failures 7 ·
pin-migration 1 · pin-creation 2 · workbench 15. **34 passed, 0 failed, 0 skipped.**

**Warning cause set:** 14 distinct locations (8 repository, 6 third-party), enumerated in the ledger.
Compare locations, not the 131/136 counts.

**Frontend: DEFERRED / OUTSTANDING.** Four commands recorded verbatim in correction 24.

## Plan defects Tasks 2-7 must be corrected against

1. `SchemaContractIdentity` duplicated (`agent_runtime.py:126`, `agent_schema_types.py:367`); the plan
   names only the `SchemaOverlay` duplication. Task 3 owns convergence. (c12)
2. Two validator tuples; wrong choice inverts invalid-plus-stale to 409. (c16)
3. Schema-upgrade precedence is the inverse of the landed assembly upgrade; Task 4 must add a separate
   method and must not harmonise the sibling, which would RED `:1517` and change #265's shipped contract. (c17)
4. `schema_contract` rejection on ordinary saves is already landed with code `immutable_field`; Task 4's
   "ordinary identity rejection" is consumption, not new work, and the field carries no `candidate.` prefix. (c18)
5. The recording sink has **no success channel**, so "invalid output emits no success fields" can pass
   vacuously; and the sink Protocol returns `BaseModel` while `ValidatedAgentOutput` is a dataclass, making
   Task 3's change breaking at four sites. (c9)
6. The compatibility loader hardcodes a literal v1 overlay that a Task-2 grammar change can RED, and the
   plan attributes those tests to Task 3. (c11)
7. The CI guard requires `test_conversation_pin_acceptance_postgres.py`, which the final matrix never runs. (c23)
8. The branch carries `.superpowers/sdd/2026-09-22-schema-driven-config-ui/plan-review-ce04afd08.md`,
   under the path the plan's global constraints forbid. (c26)
